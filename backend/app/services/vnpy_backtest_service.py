"""
vnpy CTA 回测引擎

基于 vnpy 核心对象（BarData, TradeData, OrderData, Direction, Offset）
自建 CTA 回测引擎，不依赖 vnpy_ctabacktesting 或 polars。
"""

import asyncio
import logging
from collections import defaultdict
from copy import copy
from datetime import date, datetime
from typing import Optional

import numpy as np
import pandas as pd

from vnpy.trader.constant import Direction, Offset, Interval, Status
from vnpy.trader.object import BarData, OrderData, TradeData
from vnpy.trader.utility import round_to

from app.core.data_bridge import data_bridge, get_data_source
from app.core.strategy_adapter import VNPY_STRATEGY_MAP
from app.strategies.base import get_signal_period

logger = logging.getLogger(__name__)

# 沪深300基准数据缓存: {日期: 收盘价}
_benchmark_cache: dict[str, float] = {}
_benchmark_cache_range: tuple[str, str] = ("", "")  # (start_date, end_date)


def _fetch_benchmark_prices(start_date: str, end_date: str, data_source: str | None = None) -> dict[str, float]:
    """获取沪深300基准价格，返回 {日期: 收盘价} 映射

    使用配置的数据源获取沪深300指数日K线数据，结果缓存避免重复请求。
    """
    global _benchmark_cache, _benchmark_cache_range

    cached_start, cached_end = _benchmark_cache_range
    if _benchmark_cache and cached_start <= start_date and cached_end >= end_date:
        logger.info(f"沪深300基准数据(缓存): {len(_benchmark_cache)} 行")
        return {d: p for d, p in _benchmark_cache.items() if start_date <= d <= end_date}

    try:
        source = get_data_source(data_source)
        df = source.get_index_klines(
            index_code="000300.SH",
            period="1d",
            start=start_date,
            end=end_date,
        )
        if df.empty:
            logger.warning(f"沪深300基准数据为空 (source={source.get_name()})")
            return {}

        prices = {}
        for _, row in df.iterrows():
            day_str = row["date"].strftime("%Y-%m-%d") if hasattr(row["date"], "strftime") else str(row["date"])[:10]
            close_val = float(row["close"])
            if close_val > 0:
                prices[day_str] = close_val

        logger.info(f"沪深300基准数据({source.get_name()}): {len(prices)} 行, start={start_date}, end={end_date}")
        if prices:
            fetch_start = min(start_date, cached_start) if cached_start else start_date
            fetch_end = max(end_date, cached_end) if cached_end else end_date
            _benchmark_cache = prices
            _benchmark_cache_range = (fetch_start, fetch_end)
        return {d: p for d, p in prices.items() if start_date <= d <= end_date}
    except Exception as e:
        logger.warning(f"获取沪深300失败: {e}")
        return {}


class CtaBacktestingEngine:
    """CTA 回测引擎（基于 vnpy 核心对象）"""

    gateway_name: str = "BACKTESTING"

    def __init__(self, data_source: str | None = None, user_id: str | None = None) -> None:
        self.vt_symbols: list[str] = []
        self.interval: Interval = Interval.DAILY
        self.start: Optional[datetime] = None
        self.end: Optional[datetime] = None
        self.data_source: str | None = data_source  # 数据源名称
        self.user_id: str | None = user_id  # 用于 WebSocket 实时推送日志
        self._event_loop: Optional[asyncio.AbstractEventLoop] = None  # 主线程事件循环引用

        self.capital: float = 0
        self.rate: float = 0.0003  # 佣金率
        self.stamp_tax_rate: float = 0.001  # 印花税率（卖出）
        self.size: float = 1  # 合约乘数
        self.pricetick: float = 0.01

        self.strategy = None
        self.bars: dict[str, BarData] = {}
        self.datetime: Optional[datetime] = None

        self.history_data: dict[tuple, BarData] = {}
        self.dts: set[datetime] = set()

        self.limit_order_count: int = 0
        self.limit_orders: dict[str, OrderData] = {}
        self.active_limit_orders: dict[str, OrderData] = {}

        self.trade_count: int = 0
        self.trades: dict[str, TradeData] = {}

        self.daily_results: dict[date, DailyResult] = {}

        self.cash: float = 0
        self.pre_closes: dict[str, float] = defaultdict(float)
        self.initial_pos_data: dict[str, float] = {}  # 初始持仓（回测前设置）
        self._buy_dates: dict[str, date] = {}  # T+1 跟踪：vt_symbol → 买入成交日期
        self._strategy_logs: list[str] = []  # 策略日志收集（回测期间 write_log 的输出）
        self.incremental_mode: bool = False  # True=逐条处理K线（不预计算信号）
        self.verification_failed: bool = False  # _verify_result 验算未通过标志（供测试/调用方检测）

    def set_parameters(
        self,
        vt_symbols: list[str],
        interval: Interval,
        start: datetime,
        end: datetime,
        rate: float = 0.0003,
        stamp_tax_rate: float = 0.001,
        size: float = 1,
        pricetick: float = 0.01,
        capital: float = 1_000_000,
    ) -> None:
        self.vt_symbols = vt_symbols
        self.interval = interval
        self.start = start
        self.end = end
        self.rate = rate
        self.stamp_tax_rate = stamp_tax_rate
        self.size = size
        self.pricetick = pricetick
        self.capital = capital
        self.cash = capital

    def add_strategy(self, strategy_class: type, setting: dict) -> None:
        self.strategy = strategy_class(
            self, strategy_class.__name__, copy(self.vt_symbols), setting
        )

    def load_data(self) -> None:
        """从数据源加载历史数据"""
        self.write_log(f"开始加载历史数据 (source={self.data_source or 'default'})")
        logger.info(f"开始加载历史数据 (source={self.data_source or 'default'})")

        self.history_data.clear()
        self.dts.clear()

        for vt_symbol in self.vt_symbols:
            parts = vt_symbol.split(".")
            symbol = parts[0]
            exchange_str = parts[1] if len(parts) > 1 else "SSE"

            from vnpy.trader.constant import Exchange
            exchange = Exchange(exchange_str)

            bars = data_bridge.load_bars(
                symbol=symbol,
                exchange=exchange,
                interval=self.interval,
                start=self.start,
                end=self.end,
                data_source=self.data_source,
            )

            for bar in bars:
                self.dts.add(bar.datetime)
                self.history_data[(bar.datetime, vt_symbol)] = bar

            if not bars:
                logger.warning(f"合约 {vt_symbol} 历史数据为空")

        logger.info(f"历史数据加载完成，共 {len(self.dts)} 个时间点")
        self.write_log(f"历史数据加载完成，共 {len(self.dts)} 根K线")

    def run_backtesting(self) -> None:
        """运行回测"""
        self.strategy.on_init()
        self.write_log("策略初始化完成")
        logger.info("策略初始化完成")

        dts = sorted(self.dts)
        self.write_log(f"开始回放历史数据，共 {len(dts)} 根K线...")
        logger.info(f"开始回放历史数据，共 {len(dts)} 根K线")

        # 预计算所有信号，避免每根K线重复计算（O(n²) → O(n)）
        # 注意：必须和回放循环使用相同的数据序列，保证索引对齐
        bars_data = []
        for dt in dts:
            for vt_symbol in self.vt_symbols:
                bar = self.history_data.get((dt, vt_symbol))
                if bar:
                    bars_data.append({
                        "date": bar.datetime.strftime("%Y-%m-%d %H:%M") if hasattr(bar.datetime, 'hour') else bar.datetime.strftime("%Y-%m-%d"),
                        "open": bar.open_price,
                        "high": bar.high_price,
                        "low": bar.low_price,
                        "close": bar.close_price,
                        "volume": bar.volume,
                        "turnover": bar.turnover,
                    })

        if not self.incremental_mode and hasattr(self.strategy, 'precompute_signals'):
            class_name = self.strategy._wrapped_cls.class_name if self.strategy._wrapped_cls else ""
            signal_period = get_signal_period(class_name)
            is_intraday_strategy = class_name in ("GridStrategy", "DualThrustStrategy")
            # 日内策略：直接在细颗粒度数据上生成信号
            if is_intraday_strategy or signal_period in ("tick", "1m", "5m"):
                self.strategy.precompute_signals(bars_data)
            elif self.interval != Interval.DAILY and class_name in ("BollingerStrategy", "AtrChannelStrategy"):
                # 布林带/ATR通道：日线指标 + 日内信号检测
                self._precompute_with_intraday_detection(bars_data, class_name)
            elif self.interval != Interval.DAILY:
                self._precompute_with_daily_signals(bars_data)
            else:
                self.strategy.precompute_signals(bars_data)
            # 预计算信号的数量 = 有数据的K线数量
            # on_bars 中只对有数据的K线递增 _bar_index
            self.strategy._precompute_total = len(bars_data)
        elif self.incremental_mode:
            self.write_log("增量模式：跳过信号预计算，策略逐根K线实时计算信号")
            logger.info("增量模式：跳过信号预计算，策略逐根K线实时计算信号")

        for idx, dt in enumerate(dts):
            self.new_bars(dt)
            # 每 20% 进度输出一次日志（避免日志过于密集）
            total = len(dts)
            if total > 50 and idx > 0 and idx % max(1, total // 5) == 0:
                pct = idx * 100 // total
                self.write_log(f"回测进度: {pct}% ({idx}/{total})")

        logger.info("历史数据回放结束")
        self.write_log("历史数据回放结束，开始计算统计指标...")

    def _precompute_with_daily_signals(self, bars_data: list[dict]) -> None:
        """非日线周期：信号基于日K线计算，映射到细颗粒度数据

        策略信号（如均线交叉）在日K线上计算才有意义，
        避免在1分钟等细颗粒度数据上频繁交叉导致过度交易。
        每日的信号只应用到该日第一根K线，其余置0。
        """
        from app.strategies.base import generate_signals

        # 加载日K线数据
        daily_bars_data = []
        for vt_symbol in self.vt_symbols:
            parts = vt_symbol.split(".")
            symbol = parts[0]
            from vnpy.trader.constant import Exchange
            exchange_str = parts[1] if len(parts) > 1 else "SSE"
            exchange = Exchange(exchange_str)

            bars = data_bridge.load_bars(
                symbol=symbol,
                exchange=exchange,
                interval=Interval.DAILY,
                start=self.start,
                end=self.end,
            )
            for bar in bars:
                daily_bars_data.append({
                    "date": bar.datetime.strftime("%Y-%m-%d"),
                    "open": bar.open_price,
                    "high": bar.high_price,
                    "low": bar.low_price,
                    "close": bar.close_price,
                    "volume": bar.volume,
                    "turnover": bar.turnover,
                })

        if not daily_bars_data:
            self.strategy.precompute_signals(bars_data)
            return

        # 在日K线上计算信号
        df_daily = pd.DataFrame(daily_bars_data)
        for col in ["open", "high", "low", "close", "volume", "turnover"]:
            if col in df_daily.columns:
                df_daily[col] = pd.to_numeric(df_daily[col], errors="coerce")
        if "date" in df_daily.columns:
            df_daily["date"] = pd.to_datetime(df_daily["date"])

        class_name = self.strategy._wrapped_cls.class_name if self.strategy._wrapped_cls else ""
        daily_signals = generate_signals(class_name, df_daily, self.strategy._wrapped_setting)

        # 构建日期→信号映射
        signal_map = {}
        for i, row in df_daily.iterrows():
            day_str = row["date"].strftime("%Y-%m-%d")
            signal_map[day_str] = int(daily_signals.iloc[i])

        # 映射到细颗粒度数据：每日只在第一根K线保留信号，其余置0
        mapped_signals = []
        seen_days = set()
        for bar_dict in bars_data:
            day_str = bar_dict["date"][:10]  # 取日期部分
            if day_str not in seen_days and day_str in signal_map:
                mapped_signals.append(signal_map[day_str])
                seen_days.add(day_str)
            else:
                mapped_signals.append(0)

        self.strategy._precomputed_signals = mapped_signals
        self.strategy._bar_index = 0
        logger.info(f"日K线信号映射完成，日K线 {len(daily_bars_data)} 根，细颗粒度 {len(bars_data)} 根")

    def _precompute_with_intraday_detection(self, bars_data: list[dict], class_name: str) -> None:
        """布林带/ATR通道：日线指标 + 日内信号检测

        指标值在日K线上计算（当日固定），信号在每根细颗粒度K线上检测。
        价格触及上下轨后回归时触发信号，日内可多次触发。
        """
        from app.strategies.base import generate_signals, bollinger, atr, sma

        # 加载日K线数据并计算指标
        daily_bars_data = []
        for vt_symbol in self.vt_symbols:
            parts = vt_symbol.split(".")
            symbol = parts[0]
            from vnpy.trader.constant import Exchange
            exchange_str = parts[1] if len(parts) > 1 else "SSE"
            exchange = Exchange(exchange_str)
            bars = data_bridge.load_bars(
                symbol=symbol, exchange=exchange,
                interval=Interval.DAILY, start=self.start, end=self.end,
            )
            for bar in bars:
                daily_bars_data.append({
                    "date": bar.datetime.strftime("%Y-%m-%d"),
                    "open": bar.open_price, "high": bar.high_price,
                    "low": bar.low_price, "close": bar.close_price,
                    "volume": bar.volume, "turnover": bar.turnover,
                })

        if not daily_bars_data:
            self.strategy.precompute_signals(bars_data)
            return

        df_daily = pd.DataFrame(daily_bars_data)
        for col in ["open", "high", "low", "close", "volume", "turnover"]:
            if col in df_daily.columns:
                df_daily[col] = pd.to_numeric(df_daily[col], errors="coerce")
        if "date" in df_daily.columns:
            df_daily["date"] = pd.to_datetime(df_daily["date"])

        setting = self.strategy._wrapped_setting
        close = df_daily["close"]
        high = df_daily["high"]
        low = df_daily["low"]

        # 计算日线指标
        daily_bands = {}  # date_str -> (upper, lower)
        if class_name == "BollingerStrategy":
            boll_window = setting.get("boll_window", 20)
            boll_dev = setting.get("boll_dev", 2.0)
            mid, upper, lower = bollinger(close, boll_window, boll_dev)
        elif class_name == "AtrChannelStrategy":
            atr_window = setting.get("atr_window", 14)
            atr_mult = setting.get("atr_mult", 2.0)
            ma_window = setting.get("ma_window", 20)
            price_ma = sma(close, ma_window)
            atr_val = atr(high, low, close, atr_window)
            upper = price_ma + atr_mult * atr_val
            lower = price_ma - atr_mult * atr_val
        else:
            upper = close
            lower = close

        for i in range(len(df_daily)):
            day_str = df_daily.iloc[i]["date"].strftime("%Y-%m-%d")
            daily_bands[day_str] = (float(upper.iloc[i]), float(lower.iloc[i]))

        # 在细颗粒度数据上检测日内信号
        mapped_signals = []
        prev_outside = None
        for bar_dict in bars_data:
            day_str = bar_dict["date"][:10]
            price = float(bar_dict["close"])
            bands = daily_bands.get(day_str)
            if not bands:
                mapped_signals.append(0)
                continue
            up, lo = bands
            signal = 0
            if prev_outside is not None:
                if prev_outside == "above" and price <= up:
                    signal = -1
                    prev_outside = None
                elif prev_outside == "below" and price >= lo:
                    signal = 1
                    prev_outside = None
                else:
                    if price > up:
                        prev_outside = "above"
                    elif price < lo:
                        prev_outside = "below"
                    else:
                        prev_outside = None
            else:
                if price > up:
                    prev_outside = "above"
                elif price < lo:
                    prev_outside = "below"
            mapped_signals.append(signal)

        self.strategy._precomputed_signals = mapped_signals
        self.strategy._bar_index = 0
        logger.info(f"日内信号检测完成，日K线 {len(daily_bars_data)} 根，细颗粒度 {len(bars_data)} 根")

    def new_bars(self, dt: datetime) -> None:
        """推送新 K 线"""
        self.datetime = dt

        bars: dict[str, BarData] = {}
        for vt_symbol in self.vt_symbols:
            last_bar = self.bars.get(vt_symbol)
            if last_bar and last_bar.close_price:
                self.pre_closes[vt_symbol] = last_bar.close_price

            bar = self.history_data.get((dt, vt_symbol))
            if bar:
                self.bars[vt_symbol] = bar
                bars[vt_symbol] = bar
            elif vt_symbol in self.bars:
                old_bar = self.bars[vt_symbol]
                fill_bar = BarData(
                    symbol=old_bar.symbol,
                    exchange=old_bar.exchange,
                    datetime=dt,
                    open_price=old_bar.close_price,
                    high_price=old_bar.close_price,
                    low_price=old_bar.close_price,
                    close_price=old_bar.close_price,
                    gateway_name=old_bar.gateway_name,
                )
                self.bars[vt_symbol] = fill_bar

        self.cross_order()
        self.strategy.on_bars(bars)
        self.update_daily_close(self.bars, dt)

    def cross_order(self) -> None:
        """撮合限价单

        回测撮合规则：
        - 信号在 bar[i] 收盘时产生，委托以 close_price 提交
        - 委托在 bar[i+1] 以 open_price 成交（标准回测实践）
        - 不做价格穿透检查，确保委托始终成交
        - 涨跌停检查保留（极端情况下不成交）
        - A股T+1：当日买入不可卖出
        """
        today = self.datetime.date() if self.datetime else None

        for order in list(self.active_limit_orders.values()):
            bar = self.bars.get(order.vt_symbol)
            if not bar:
                continue

            if order.status == Status.SUBMITTING:
                order.status = Status.NOTTRADED
                self.strategy.update_order(order)

            pre_close = self.pre_closes.get(order.vt_symbol, 0)
            limit_up = round_to(pre_close * 1.1, self.pricetick) if pre_close > 0 else float("inf")
            limit_down = round_to(pre_close * 0.9, self.pricetick) if pre_close > 0 else 0

            # 涨跌停检查：涨停板无法买入，跌停板无法卖出
            if order.direction == Direction.LONG and bar.open_price >= limit_up and limit_up < float("inf"):
                continue
            if order.direction == Direction.SHORT and bar.open_price <= limit_down and limit_down > 0:
                continue

            # T+1 检查：当日买入不可卖出
            if order.direction == Direction.SHORT and today is not None:
                buy_date = self._buy_dates.get(order.vt_symbol)
                if buy_date == today:
                    order.status = Status.REJECTED
                    self.limit_orders[order.vt_orderid] = order
                    self.active_limit_orders.pop(order.vt_orderid, None)
                    self.strategy.update_order(order)
                    self.write_log(f"T+1 限制: {order.vt_symbol} 今日买入不可卖出")
                    continue

            order.traded = order.volume
            order.status = Status.ALLTRADED
            self.strategy.update_order(order)
            self.active_limit_orders.pop(order.vt_orderid, None)

            self.trade_count += 1
            # 以下一根K线开盘价成交（标准回测实践）
            trade_price = bar.open_price

            trade = TradeData(
                symbol=order.symbol,
                exchange=order.exchange,
                orderid=order.orderid,
                tradeid=str(self.trade_count),
                direction=order.direction,
                offset=order.offset,
                price=trade_price,
                volume=order.volume,
                datetime=self.datetime,
                gateway_name=self.gateway_name,
            )

            trade_value = trade.price * trade.volume * self.size
            commission = max(trade_value * self.rate, 5)

            if trade.direction == Direction.LONG:
                self.cash -= trade_value
                # T+1 标记：记录买入成交日期
                if today is not None:
                    self._buy_dates[order.vt_symbol] = today
            else:
                self.cash += trade_value
                # 卖出印花税
                stamp_tax = trade_value * self.stamp_tax_rate
                commission += stamp_tax
                # T+1 清理：全部卖出后清除买入日期
                pos = self.strategy.pos_data.get(order.vt_symbol, 0)
                if pos - order.volume <= 0:
                    self._buy_dates.pop(order.vt_symbol, None)

            self.cash -= commission

            self.strategy.update_trade(trade)
            self.trades[trade.vt_tradeid] = trade

    def update_daily_close(self, bars: dict[str, BarData], dt: datetime) -> None:
        d = dt.date()
        close_prices = {}
        for bar in bars.values():
            close_prices[bar.vt_symbol] = bar.close_price if bar.close_price else self.pre_closes.get(bar.vt_symbol, 0)

        daily_result = self.daily_results.get(d)
        if daily_result:
            daily_result.update_close_prices(close_prices)
        else:
            self.daily_results[d] = DailyResult(d, close_prices)

    # ── 策略引擎接口 ──────────────────────────────────────────────────────

    def send_order(
        self, strategy, vt_symbol: str, direction: Direction,
        offset: Offset, price: float, volume: float,
    ) -> list[str]:
        price = round_to(price, self.pricetick)
        parts = vt_symbol.split(".")
        symbol = parts[0]
        exchange_str = parts[1] if len(parts) > 1 else "SSE"
        from vnpy.trader.constant import Exchange
        exchange = Exchange(exchange_str)

        self.limit_order_count += 1
        order = OrderData(
            symbol=symbol,
            exchange=exchange,
            orderid=str(self.limit_order_count),
            direction=direction,
            offset=offset,
            price=price,
            volume=volume,
            status=Status.SUBMITTING,
            datetime=self.datetime,
            gateway_name=self.gateway_name,
        )
        self.active_limit_orders[order.vt_orderid] = order
        self.limit_orders[order.vt_orderid] = order
        return [order.vt_orderid]

    def cancel_order(self, strategy, vt_orderid: str) -> None:
        if vt_orderid not in self.active_limit_orders:
            return
        order = self.active_limit_orders.pop(vt_orderid)
        order.status = Status.CANCELLED
        self.strategy.update_order(order)

    def write_log(self, msg: str, strategy=None) -> None:
        dt_str = str(self.datetime) if self.datetime else ""
        log_line = f"{dt_str} {msg}" if dt_str else msg
        logger.info(log_line)
        self._strategy_logs.append(log_line)
        self._push_log(log_line)

    def _push_log(self, msg: str) -> None:
        """通过 WebSocket 实时推送日志到前端

        回测在线程池中运行，需要获取主线程的事件循环来调度协程。
        使用 asyncio.run_coroutine_threadsafe 将协程安全地提交到主事件循环。
        """
        if not self.user_id:
            print("[DEBUG] _push_log skip: user_id empty")
            return
        try:
            from app.ws.manager import ws_manager
            # 使用在主线程中保存的事件循环引用
            loop = self._event_loop
            if loop is None:
                print("[DEBUG] _push_log skip: no event loop")
                return
            if loop.is_running():
                asyncio.run_coroutine_threadsafe(
                    ws_manager.send_to_user(self.user_id, {
                        "type": "backtest_log",
                        "data": {"message": msg, "time": datetime.now().strftime("%H:%M:%S")},
                    }),
                    loop,
                )
                print(f"[DEBUG] _push_log sent: user={self.user_id} msg={msg[:80]}")
            else:
                print("[DEBUG] _push_log skip: event loop not running")
        except Exception as e:
            # WebSocket 推送失败不影响回测，但记录异常便于排查
            print(f"[DEBUG] _push_log error: {e}")

    def get_cash_available(self) -> float:
        return self.cash

    def get_holding_value(self) -> float:
        holding_value = 0
        for vt_symbol, pos in self.strategy.pos_data.items():
            bar = self.bars.get(vt_symbol)
            if bar and pos > 0:
                holding_value += bar.close_price * pos * self.size
        return holding_value

    # ── 统计计算 ──────────────────────────────────────────────────────────

    def calculate_result(self) -> dict:
        """计算逐日盯市盈亏"""
        if not self.trades:
            return {}

        for trade in self.trades.values():
            if not trade.datetime:
                continue
            d = trade.datetime.date()
            self.daily_results[d].add_trade(trade)

        pre_closes = {}
        start_poses = {}
        # 初始持仓：确保第一个 DailyResult 的 start_poses 包含初始持仓
        for vt_symbol, pos in self.initial_pos_data.items():
            if pos > 0:
                first_dt = sorted(self.dts)[0] if self.dts else None
                if first_dt:
                    first_bar = self.history_data.get((first_dt, vt_symbol))
                    if first_bar:
                        start_poses[vt_symbol] = pos
                        pre_closes[vt_symbol] = first_bar.close_price

        for daily_result in self.daily_results.values():
            daily_result.calculate_pnl(
                pre_closes, start_poses, self.size, self.rate, self.stamp_tax_rate
            )
            pre_closes = daily_result.close_prices
            start_poses = daily_result.end_poses

        return self.calculate_statistics()

    def calculate_statistics(self) -> dict:
        """计算策略统计指标"""
        if not self.daily_results:
            return {}

        results = sorted(self.daily_results.values(), key=lambda x: x.date)
        total_days = len(results)

        if total_days == 0:
            return {}

        # 构建日收益序列
        daily_pnls = []
        balance = self.capital
        max_balance = self.capital
        max_drawdown = 0.0

        equity_curve = []
        for r in results:
            balance += r.net_pnl
            if balance > max_balance:
                max_balance = balance
            drawdown = (max_balance - balance) / max_balance if max_balance > 0 else 0
            if drawdown > max_drawdown:
                max_drawdown = drawdown

            daily_return = r.net_pnl / (balance - r.net_pnl) if (balance - r.net_pnl) > 0 else 0
            daily_pnls.append(daily_return)
            equity_curve.append({
                "date": r.date.strftime("%Y-%m-%d"),
                "equity": round(balance, 2),
                "return": round((balance / self.capital - 1) * 100, 4),
                "drawdown": round(drawdown * 100, 2),
            })

        # 计算沪深300基准收益率曲线
        benchmark_curve = self._calc_benchmark_curve(results, equity_curve)
        if benchmark_curve:
            for i, item in enumerate(equity_curve):
                if i < len(benchmark_curve):
                    item["benchmark_return"] = benchmark_curve[i]

        total_return = (balance - self.capital) / self.capital
        days = (results[-1].date - results[0].date).days
        years = max(days / 365, 1 / 365)
        # 当 1+total_return < 0 时，分数次幂会产生复数，需特殊处理
        base = 1 + total_return
        if base > 0:
            annualized_return = base ** (1 / years) - 1
        else:
            annualized_return = -((-base) ** (1 / years) - 1)

        daily_returns = pd.Series(daily_pnls)
        rf_daily = 0.03 / 252

        if daily_returns.std() > 0:
            sharpe_ratio = (daily_returns.mean() - rf_daily) / daily_returns.std() * np.sqrt(252)
        else:
            sharpe_ratio = 0.0

        downside = daily_returns[daily_returns < 0]
        if len(downside) > 0 and downside.std() > 0:
            sortino_ratio = (daily_returns.mean() - rf_daily) / downside.std() * np.sqrt(252)
        else:
            sortino_ratio = sharpe_ratio * 1.2

        # 胜率
        sell_trades = [t for t in self.trades.values() if t.direction == Direction.SHORT]
        # 从 trades 计算盈亏
        trade_pnls = self._calculate_trade_pnls()
        win_trades = [p for p in trade_pnls if p > 0]
        win_rate = len(win_trades) / max(len(trade_pnls), 1)

        total_profit = sum(p for p in trade_pnls if p > 0)
        total_loss = abs(sum(p for p in trade_pnls if p < 0))
        profit_factor = total_profit / max(total_loss, 1)

        volatility = daily_returns.std() * np.sqrt(252) if len(daily_returns) > 0 else 0
        avg_trade_return = total_return / max(len(trade_pnls), 1)

        # 计算资金与持仓快照
        initial_position_value = 0.0
        initial_position_quantity = 0.0
        initial_cash = self.capital
        for vt_symbol, pos in self.initial_pos_data.items():
            if pos > 0:
                first_dt = sorted(self.dts)[0] if self.dts else None
                if first_dt:
                    first_bar = self.history_data.get((first_dt, vt_symbol))
                    if first_bar:
                        pos_val = pos * first_bar.close_price * self.size
                        initial_position_value += pos_val
                        initial_position_quantity += pos
                        initial_cash -= pos_val

        final_cash = self.cash
        final_position_value = 0.0
        final_position_quantity = 0.0
        for vt_symbol, pos in self.strategy.pos_data.items() if self.strategy and hasattr(self.strategy, 'pos_data') else []:
            if pos > 0:
                final_position_quantity += pos
                last_dt = sorted(self.dts)[-1] if self.dts else None
                if last_dt:
                    last_bar = self.history_data.get((last_dt, vt_symbol))
                    if last_bar:
                        final_position_value += pos * last_bar.close_price * self.size

        initial_total_assets = initial_cash + initial_position_value
        final_total_assets = final_cash + final_position_value
        total_profit = final_total_assets - initial_total_assets

        # 验算回测结果正确性
        verification = self._verify_result(
            results, balance, max_drawdown, total_profit,
            initial_total_assets, final_total_assets,
        )

        return {
            "total_return": round(total_return, 4),
            "annualized_return": round(annualized_return, 4),
            "max_drawdown": round(max_drawdown, 4),
            "sharpe_ratio": round(sharpe_ratio, 4),
            "sortino_ratio": round(sortino_ratio, 4),
            "win_rate": round(win_rate, 4),
            "profit_factor": round(profit_factor, 4),
            "total_trades": len(self.trades),
            "avg_trade_return": round(avg_trade_return, 4),
            "volatility": round(volatility, 4),
            "beta": 0.0,
            "alpha": 0.0,
            "daily_results": equity_curve,
            "trades": self._format_trades(),
            "intraday_results": [],
            "initial_cash": round(initial_cash, 2),
            "initial_position_value": round(initial_position_value, 2),
            "initial_position_quantity": round(initial_position_quantity, 2),
            "final_cash": round(final_cash, 2),
            "final_position_value": round(final_position_value, 2),
            "final_position_quantity": round(final_position_quantity, 2),
            "total_profit": round(total_profit, 2),
            "verification": verification,
        }

    def _calc_benchmark_curve(self, results: list, equity_curve: list) -> list[float]:
        """计算沪深300基准收益率曲线

        获取沪深300同期的日K线，计算每日累计收益率（百分比），
        与策略权益曲线对齐（按日期匹配）。

        Returns:
            与 equity_curve 长度相同的基准收益率列表（百分比），获取失败返回空列表
        """
        if not results:
            return []

        start_date = results[0].date.strftime("%Y-%m-%d")
        end_date = results[-1].date.strftime("%Y-%m-%d")

        benchmark_prices = _fetch_benchmark_prices(start_date, end_date, self.data_source)
        if not benchmark_prices:
            return []

        # 找到回测起始日之前的最近一个交易日作为基准起始价
        first_price = None
        for eq in equity_curve:
            if eq["date"] in benchmark_prices:
                first_price = benchmark_prices[eq["date"]]
                break

        if first_price is None or first_price <= 0:
            return []

        # 计算每日累计收益率
        benchmark_returns = []
        for eq in equity_curve:
            price = benchmark_prices.get(eq["date"])
            if price and price > 0:
                benchmark_returns.append(round((price / first_price - 1) * 100, 4))
            else:
                if benchmark_returns:
                    benchmark_returns.append(benchmark_returns[-1])
                else:
                    benchmark_returns.append(0.0)

        return benchmark_returns

    def _verify_result(
        self,
        daily_results: list,
        final_balance: float,
        reported_max_drawdown: float,
        reported_total_profit: float,
        initial_total_assets: float,
        final_total_assets: float,
    ) -> dict:
        """验算回测结果正确性

        5项验算：
        1. 资金守恒：cash 变化 + 持仓市值变化 = 总盈亏
        2. 逐日盈亏之和 = 总盈亏
        3. 权益曲线一致性：equity_curve 首尾差 = 总盈亏
        4. 最大回撤验算：从 equity_curve 重新计算
        5. 交易盈亏汇总一致性：逐笔 pnl 之和 ≈ 总盈亏
        """
        checks = {}
        tolerance = 1.0  # 允许1元误差（佣金计算精度）

        # 1. 资金守恒：final_total_assets - initial_total_assets = total_profit
        asset_profit = final_total_assets - initial_total_assets
        checks["capital_conservation"] = {
            "description": "资金守恒：总资产变化 = 总盈亏",
            "asset_profit": round(asset_profit, 2),
            "reported_profit": round(reported_total_profit, 2),
            "diff": round(abs(asset_profit - reported_total_profit), 2),
            "passed": abs(asset_profit - reported_total_profit) < tolerance,
        }

        # 2. 逐日盈亏之和 = 总盈亏
        sum_net_pnl = sum(r.net_pnl for r in daily_results)
        # net_pnl 累加得到的是 balance - capital
        pnl_sum_profit = sum_net_pnl  # 应等于 final_balance - capital
        checks["daily_pnl_sum"] = {
            "description": "逐日净盈亏之和 = 期末权益 - 初始资金",
            "sum_net_pnl": round(sum_net_pnl, 2),
            "expected": round(final_balance - self.capital, 2),
            "diff": round(abs(sum_net_pnl - (final_balance - self.capital)), 2),
            "passed": abs(sum_net_pnl - (final_balance - self.capital)) < tolerance,
        }

        # 3. 权益曲线一致性：equity_curve 首尾差 = total_profit
        # balance 是从 capital 开始累加 net_pnl 得到的
        # balance = capital + sum_net_pnl
        # 所以 balance - capital = sum_net_pnl，应等于 total_profit
        # 但 total_profit 是从持仓市值+现金计算的，可能有佣金精度差异
        equity_profit = final_balance - self.capital
        checks["equity_consistency"] = {
            "description": "权益曲线累计盈亏 = 总盈亏",
            "equity_profit": round(equity_profit, 2),
            "asset_profit": round(asset_profit, 2),
            "diff": round(abs(equity_profit - asset_profit), 2),
            "passed": abs(equity_profit - asset_profit) < tolerance,
        }

        # 4. 最大回撤验算：从 daily_results 重新计算
        recalculated_max_dd = 0.0
        peak = self.capital
        recal_balance = self.capital
        for r in daily_results:
            recal_balance += r.net_pnl
            if recal_balance > peak:
                peak = recal_balance
            dd = (peak - recal_balance) / peak if peak > 0 else 0
            if dd > recalculated_max_dd:
                recalculated_max_dd = dd
        checks["max_drawdown"] = {
            "description": "最大回撤验算：从逐日盈亏重新计算",
            "reported": round(reported_max_drawdown, 4),
            "recalculated": round(recalculated_max_dd, 4),
            "diff": round(abs(reported_max_drawdown - recalculated_max_dd), 4),
            "passed": abs(reported_max_drawdown - recalculated_max_dd) < 0.001,
        }

        # 5. 交易盈亏汇总一致性：逐笔 pnl 之和 ≈ 总盈亏
        trade_pnls = self._calculate_trade_pnls()
        sum_trade_pnl = sum(trade_pnls)
        # 逐笔 pnl 是卖出-买入的差价减佣金，不含持仓浮盈
        # 验算：逐笔 pnl + 持仓浮盈 ≈ 总盈亏
        holding_pnl = 0
        for vt_symbol, pos in self.strategy.pos_data.items() if self.strategy and hasattr(self.strategy, 'pos_data') else []:
            if pos > 0:
                last_dt = sorted(self.dts)[-1] if self.dts else None
                if last_dt:
                    last_bar = self.history_data.get((last_dt, vt_symbol))
                    if last_bar:
                        # 持仓浮盈 = (现价 - 平均成本) * 数量
                        # 平均成本摊入买入佣金（与 reported_profit 口径一致）
                        avg_cost = 0
                        total_vol = 0
                        for vt_sym, pos_qty in self.initial_pos_data.items():
                            if vt_sym == vt_symbol and pos_qty > 0:
                                first_dt = sorted(self.dts)[0] if self.dts else None
                                if first_dt:
                                    first_bar = self.history_data.get((first_dt, vt_sym))
                                    if first_bar:
                                        avg_cost = first_bar.close_price
                                        total_vol = pos_qty
                                        break  # 每个 vt_symbol 只有一个初始持仓项
                        for trade in self.trades.values():
                            if trade.vt_symbol == vt_symbol and trade.direction == Direction.LONG:
                                vol = trade.volume
                                # 摊入该笔买入佣金：成本 = (price*vol + 佣金) / vol
                                comm = max(trade.price * vol * self.rate, 5)
                                new_vol = total_vol + vol
                                if new_vol > 0:
                                    avg_cost = (avg_cost * total_vol + trade.price * vol + comm) / new_vol
                                total_vol = new_vol
                        if avg_cost > 0:
                            holding_pnl += (last_bar.close_price - avg_cost) * pos

        # tolerance 按佣金规模调宽：末尾持仓时 holding_pnl 与 reported 口径仍可能有
        # 印花税/小数精度差，按 capital 的 0.01% 或绝对2元取大
        trade_tolerance = max(tolerance * 2, self.capital * 0.0001)
        checks["trade_pnl_consistency"] = {
            "description": "交易盈亏 + 持仓浮盈 ≈ 总盈亏",
            "sum_trade_pnl": round(sum_trade_pnl, 2),
            "holding_pnl": round(holding_pnl, 2),
            "total": round(sum_trade_pnl + holding_pnl, 2),
            "reported_profit": round(reported_total_profit, 2),
            "diff": round(abs(sum_trade_pnl + holding_pnl - reported_total_profit), 2),
            "passed": abs(sum_trade_pnl + holding_pnl - reported_total_profit) < trade_tolerance,
        }

        # 总体判定
        all_passed = all(c["passed"] for c in checks.values())
        checks["overall"] = {
            "description": "所有验算项是否通过",
            "passed": all_passed,
            "failed_items": [k for k, c in checks.items() if not c["passed"]],
        }

        if not all_passed:
            self.verification_failed = True
            logger.warning(f"回测验算未通过: {checks['overall']['failed_items']}")

        return checks

    def _calculate_trade_pnls(self) -> list[float]:
        """计算每笔卖出交易的盈亏

        网格策略使用 LIFO（最近买入优先匹配），因为网格是配对交易，
        每格的卖出应匹配同一轮网格中最近的买入。
        其他策略使用 FIFO（最早买入优先匹配）。
        """
        pnls = []
        buy_trades = {}  # vt_symbol -> list of (price, volume)

        # 初始持仓视为虚拟买入（成本价 = 首日收盘价）
        for vt_symbol, pos in self.initial_pos_data.items():
            if pos > 0:
                first_dt = sorted(self.dts)[0] if self.dts else None
                if first_dt:
                    first_bar = self.history_data.get((first_dt, vt_symbol))
                    if first_bar:
                        buy_trades.setdefault(vt_symbol, []).append((first_bar.close_price, pos))

        is_grid = self.strategy and hasattr(self.strategy, '_grid_mode') and self.strategy._grid_mode

        for trade in sorted(self.trades.values(), key=lambda t: int(t.tradeid)):
            vt_symbol = trade.vt_symbol
            if trade.direction == Direction.LONG:
                buy_trades.setdefault(vt_symbol, []).append((trade.price, trade.volume))
            elif trade.direction == Direction.SHORT:
                sell_volume = trade.volume
                sell_price = trade.price
                remaining = sell_volume
                pnl = 0
                buys = buy_trades.get(vt_symbol, [])
                while remaining > 0 and buys:
                    # 网格策略 LIFO（从末尾取），其他策略 FIFO（从头部取）
                    idx = -1 if is_grid else 0
                    buy_price, buy_vol = buys[idx]
                    matched = min(remaining, buy_vol)
                    pnl += (sell_price - buy_price) * matched
                    commission = max(matched * sell_price * self.rate, 5) + max(matched * buy_price * self.rate, 5)
                    stamp_tax = matched * sell_price * self.stamp_tax_rate
                    pnl -= commission + stamp_tax
                    remaining -= matched
                    if matched >= buy_vol:
                        buys.pop(idx)
                    else:
                        if idx == -1:
                            buys[idx] = (buy_price, buy_vol - matched)
                        else:
                            buys[idx] = (buy_price, buy_vol - matched)
                if pnl != 0:
                    pnls.append(pnl)
        return pnls

    def _format_trades(self) -> list[dict]:
        """格式化交易记录（含逐笔盈亏）

        网格策略使用 LIFO（最近买入优先匹配），其他策略使用 FIFO。
        """
        # 先计算每笔卖出的盈亏，映射到 tradeid
        trade_pnl_map: dict[str, float] = {}
        buy_trades: dict[str, list[tuple[str, float, float]]] = {}  # vt_symbol -> [(tradeid, price, volume)]

        # 初始持仓视为虚拟买入（成本价 = 首日收盘价），tradeid = "0"
        for vt_symbol, pos in self.initial_pos_data.items():
            if pos > 0:
                first_dt = sorted(self.dts)[0] if self.dts else None
                if first_dt:
                    first_bar = self.history_data.get((first_dt, vt_symbol))
                    if first_bar:
                        buy_trades.setdefault(vt_symbol, []).append(("0", first_bar.close_price, pos))

        is_grid = self.strategy and hasattr(self.strategy, '_grid_mode') and self.strategy._grid_mode

        for trade in sorted(self.trades.values(), key=lambda t: int(t.tradeid)):
            vt_symbol = trade.vt_symbol
            if trade.direction == Direction.LONG:
                buy_trades.setdefault(vt_symbol, []).append((trade.tradeid, trade.price, trade.volume))
            elif trade.direction == Direction.SHORT:
                sell_volume = trade.volume
                sell_price = trade.price
                remaining = sell_volume
                pnl = 0.0
                buys = buy_trades.get(vt_symbol, [])
                while remaining > 0 and buys:
                    # 网格策略 LIFO（从末尾取），其他策略 FIFO（从头部取）
                    idx = -1 if is_grid else 0
                    buy_tradeid, buy_price, buy_vol = buys[idx]
                    matched = min(remaining, buy_vol)
                    pnl += (sell_price - buy_price) * matched
                    commission = max(matched * sell_price * self.rate, 5) + max(matched * buy_price * self.rate, 5)
                    stamp_tax = matched * sell_price * self.stamp_tax_rate
                    pnl -= commission + stamp_tax
                    remaining -= matched
                    if matched >= buy_vol:
                        buys.pop(idx)
                    else:
                        buys[idx] = (buy_tradeid, buy_price, buy_vol - matched)
                trade_pnl_map[trade.tradeid] = round(pnl, 2)

        result = []
        for trade in sorted(self.trades.values(), key=lambda t: int(t.tradeid)):
            side = "buy" if trade.direction == Direction.LONG else "sell"
            result.append({
                "date": trade.datetime.strftime("%Y-%m-%d %H:%M") if trade.datetime and hasattr(trade.datetime, 'hour') and trade.datetime.hour > 0 else (trade.datetime.strftime("%Y-%m-%d") if trade.datetime else ""),
                "symbol": trade.vt_symbol.split(".")[0],
                "side": side,
                "price": round(trade.price, 2),
                "quantity": int(trade.volume),
                "commission": round(max(trade.price * trade.volume * self.rate, 5), 2),
                "pnl": trade_pnl_map.get(trade.tradeid, 0),
            })
        return result


class DailyResult:
    """逐日盯市盈亏"""

    def __init__(self, result_date: date, close_prices: dict[str, float]) -> None:
        self.date = result_date
        self.close_prices = close_prices
        self.pre_closes: dict[str, float] = {}
        self.start_poses: dict[str, float] = {}
        self.end_poses: dict[str, float] = {}

        self.trades: list[TradeData] = []
        self.trade_count: int = 0
        self.turnover: float = 0
        self.commission: float = 0
        self.trading_pnl: float = 0
        self.holding_pnl: float = 0
        self.total_pnl: float = 0
        self.net_pnl: float = 0

    def add_trade(self, trade: TradeData) -> None:
        self.trades.append(trade)

    def calculate_pnl(
        self,
        pre_closes: dict[str, float],
        start_poses: dict[str, float],
        size: float,
        rate: float,
        stamp_tax_rate: float,
    ) -> None:
        self.pre_closes = pre_closes
        self.start_poses = start_poses
        self.end_poses = dict(start_poses)

        # 持仓盈亏：昨日持仓 × (今日收盘 - 昨日收盘) × 合约乘数
        self.holding_pnl = 0
        for vt_symbol, pos in start_poses.items():
            pre_close = pre_closes.get(vt_symbol, 0)
            close = self.close_prices.get(vt_symbol, 0)
            if pos != 0 and pre_close > 0:
                self.holding_pnl += pos * (close - pre_close) * size

        self.trade_count = len(self.trades)
        for trade in self.trades:
            if trade.direction == Direction.LONG:
                pos_change = trade.volume
            else:
                pos_change = -trade.volume

            self.end_poses[trade.vt_symbol] = self.end_poses.get(trade.vt_symbol, 0) + pos_change

            turnover = trade.volume * size * trade.price
            self.trading_pnl += pos_change * (self.close_prices.get(trade.vt_symbol, 0) - trade.price) * size
            self.turnover += turnover
            # 佣金与印花税分别计算（与 cross_order 口径一致）：
            # 佣金有5元最低，印花税卖出全额收不取最低
            trade_commission = max(turnover * rate, 5)
            if trade.direction == Direction.SHORT:
                trade_commission += turnover * stamp_tax_rate
            self.commission += trade_commission

        self.total_pnl = self.trading_pnl + self.holding_pnl
        self.net_pnl = self.total_pnl - self.commission

    def update_close_prices(self, close_prices: dict[str, float]) -> None:
        self.close_prices.update(close_prices)


# ── 对外接口 ──────────────────────────────────────────────────────────────

def run_vnpy_backtest(
    class_name: str,
    symbol: str,
    start_date: str,
    end_date: str,
    capital: float,
    setting: dict,
    interval: str = "d",
    period: str = "daily",
    commission_rate: float = 0.0003,
    stamp_tax_rate: float = 0.001,
    initial_position: int = 0,
    data_source: str | None = None,
    user_id: str | None = None,
    event_loop: asyncio.AbstractEventLoop | None = None,
    incremental_mode: bool = True,
) -> dict:
    """使用 vnpy CTA 回测引擎运行回测

    Args:
        event_loop: 主线程的 asyncio 事件循环引用，用于 WebSocket 实时日志推送。
                    在通过 run_in_executor 调用时由调用方传入。
    """

    print(f"[DEBUG] run_vnpy_backtest started: class_name={class_name}, user_id={user_id}, loop={event_loop}")

    from app.core.strategy_adapter import resolve_strategy_class

    # 解析策略类（支持内置和自定义策略的动态编译）
    raw_cls = resolve_strategy_class(class_name)
    if not raw_cls:
        raise ValueError(f"未知策略: {class_name}")

    # 获取 vnpy 适配器
    strategy_cls = VNPY_STRATEGY_MAP.get(class_name)
    if not strategy_cls:
        raise ValueError(f"策略适配器创建失败: {class_name}")

    exchange = data_bridge.to_exchange(symbol)
    vt_symbol = data_bridge.to_vt_symbol(symbol)

    # 周期映射
    period_to_interval = {
        "daily": Interval.DAILY,
        "1m": Interval.MINUTE,
        "5m": Interval.MINUTE,
        "15m": Interval.MINUTE,
        "30m": Interval.MINUTE,
        "1h": Interval.MINUTE,
        "weekly": Interval.WEEKLY,
    }
    vt_interval = period_to_interval.get(period, Interval.DAILY)

    start = datetime.strptime(start_date, "%Y-%m-%d")
    end = datetime.strptime(end_date, "%Y-%m-%d")

    engine = CtaBacktestingEngine(data_source=data_source, user_id=user_id)
    engine._event_loop = event_loop  # 保存主线程事件循环引用，供 WebSocket 实时推送使用
    engine.incremental_mode = incremental_mode
    engine.set_parameters(
        vt_symbols=[vt_symbol],
        interval=vt_interval,
        start=start,
        end=end,
        rate=commission_rate,
        stamp_tax_rate=stamp_tax_rate,
        size=1,
        pricetick=0.01,
        capital=capital,
    )
    engine.add_strategy(strategy_cls, setting)

    # 将策略代码中的 logger.info() 输出重定向到引擎的 _strategy_logs
    # 这样策略代码中的日志会被捕获并返回给前端
    import logging as _logging_mod

    class _BacktestLogHandler(_logging_mod.Handler):
        """将 Python logging 输出重定向到回测引擎的策略日志列表 + WebSocket 实时推送"""
        def __init__(self, target_list: list[str], push_fn):
            super().__init__()
            self._target = target_list
            self._push_fn = push_fn

        def emit(self, record: _logging_mod.LogRecord) -> None:
            try:
                msg = self.format(record)
                print(f"[DEBUG] strategy log captured: {msg[:120]}")
                self._target.append(msg)
                self._push_fn(msg)
            except Exception as e:
                print(f"[DEBUG] strategy log handler error: {e}")

    _strategy_log_handler = _BacktestLogHandler(engine._strategy_logs, engine._push_log)
    _strategy_log_handler.setFormatter(_logging_mod.Formatter("[%(name)s] %(message)s"))

    # 绑定到 root logger 并过滤，捕获 strategy / __main__ 等策略相关 logger
    # 这样无论 AI 代码使用注入的 logger 还是 import logging 自建 logger 都能收集
    _root_logger = _logging_mod.getLogger()
    _strategy_log_handler.addFilter(
        lambda r: r.name in ("strategy", "__main__") or "strategy" in r.name.lower()
    )
    _root_logger.addHandler(_strategy_log_handler)
    print(f"[DEBUG] backtest log handler bound to root logger, user_id={user_id}")

    engine.load_data()

    # 设置初始持仓：从初始资金中扣除持仓市值
    if initial_position > 0 and engine.dts:
        first_dt = sorted(engine.dts)[0]
        first_bar = engine.history_data.get((first_dt, vt_symbol))
        if first_bar:
            first_price = first_bar.close_price
            position_value = initial_position * first_price
            engine.cash = capital - position_value
            engine.strategy.pos_data[vt_symbol] = initial_position
            engine.initial_pos_data[vt_symbol] = initial_position
            # 将初始持仓数量注入到策略参数中，供 generate_signals() 使用
            engine.strategy._wrapped_setting["initial_position"] = initial_position

    if len(engine.dts) < 30:
        raise ValueError(f"数据量不足（仅 {len(engine.dts)} 根K线），请扩大日期范围")

    engine.run_backtesting()

    # 回测完成，移除策略日志转发 handler（避免重复添加）
    _root_logger.removeHandler(_strategy_log_handler)

    result = engine.calculate_result()
    engine.write_log("统计指标计算完成")

    if not result:
        return {
            "total_return": 0, "annualized_return": 0, "max_drawdown": 0,
            "sharpe_ratio": 0, "sortino_ratio": 0, "win_rate": 0,
            "profit_factor": 0, "total_trades": 0, "avg_trade_return": 0,
            "volatility": 0, "beta": 0, "alpha": 0,
            "daily_results": [], "trades": [], "intraday_results": [],
            "strategy_logs": engine._strategy_logs,
        }

    # 补充日K线数据到 daily_results（供前端K线图展示）
    df_daily = data_bridge.load_bars_df(symbol, start_date, end_date, "daily", data_source=data_source)
    if not df_daily.empty:
        result = _merge_daily_klines(result, df_daily, capital, data_source=data_source)

    # 非日线周期：生成日内细颗粒度数据（供前端双击日K线查看详情）
    if period != "daily":
        result["intraday_results"] = _build_intraday_results(
            engine, symbol, result["trades"]
        )

    # 附带策略日志（回测期间 write_log 的输出）
    result["strategy_logs"] = engine._strategy_logs

    return result


def _merge_daily_klines(result: dict, df_daily: pd.DataFrame, capital: float, data_source: str | None = None) -> dict:
    """将日K线数据合并到回测结果的 daily_results 中"""
    equity_map = {e["date"]: e for e in result["daily_results"]}

    # 获取沪深300基准数据，覆盖K线日期范围
    benchmark_prices = {}
    if not df_daily.empty:
        start = df_daily["date"].min().strftime("%Y-%m-%d")
        end = df_daily["date"].max().strftime("%Y-%m-%d")
        try:
            benchmark_prices = _fetch_benchmark_prices(start, end, data_source)
        except Exception:
            pass

    # 计算基准收益率：以第一个有价格的日期为基准
    first_bm_price = None
    if benchmark_prices:
        for _, row in df_daily.iterrows():
            date_str = row["date"].strftime("%Y-%m-%d")
            if date_str in benchmark_prices:
                first_bm_price = benchmark_prices[date_str]
                break

    merged = []
    for _, row in df_daily.iterrows():
        date_str = row["date"].strftime("%Y-%m-%d")
        eq_info = equity_map.get(date_str)
        # 计算基准收益率
        bm_return = None
        if benchmark_prices and first_bm_price and first_bm_price > 0:
            price = benchmark_prices.get(date_str)
            if price and price > 0:
                bm_return = round((price / first_bm_price - 1) * 100, 4)
            elif merged:
                bm_return = merged[-1].get("benchmark_return")

        if eq_info:
            merged.append({
                "date": date_str,
                "open": round(float(row["open"]), 2),
                "high": round(float(row["high"]), 2),
                "low": round(float(row["low"]), 2),
                "close": round(float(row["close"]), 2),
                "volume": round(float(row["volume"]), 0),
                "equity": eq_info["equity"],
                "return": eq_info["return"],
                "drawdown": eq_info["drawdown"],
                "benchmark_return": bm_return if bm_return is not None else eq_info.get("benchmark_return"),
            })
        else:
            equity = merged[-1]["equity"] if merged else capital
            ret = round((equity / capital - 1) * 100, 4)
            dd = merged[-1]["drawdown"] if merged else 0
            merged.append({
                "date": date_str,
                "open": round(float(row["open"]), 2),
                "high": round(float(row["high"]), 2),
                "low": round(float(row["low"]), 2),
                "close": round(float(row["close"]), 2),
                "volume": round(float(row["volume"]), 0),
                "equity": equity,
                "return": ret,
                "drawdown": dd,
                "benchmark_return": bm_return,
            })

    result["daily_results"] = merged
    return result


def _build_intraday_results(
    engine: CtaBacktestingEngine, symbol: str, trades: list[dict]
) -> list[dict]:
    """构建日内细颗粒度数据（供前端双击日K线查看详情）"""
    intraday_results = []

    # 从历史数据中按日分组
    day_bars: dict[str, list[dict]] = {}
    dts = sorted(engine.dts)
    for dt in dts:
        for vt_symbol in engine.vt_symbols:
            bar = engine.history_data.get((dt, vt_symbol))
            if bar:
                day_str = dt.strftime("%Y-%m-%d")
                if hasattr(dt, 'hour'):
                    time_str = dt.strftime("%Y-%m-%d %H:%M")
                else:
                    time_str = dt.strftime("%Y-%m-%d")
                day_bars.setdefault(day_str, []).append({
                    "time": time_str,
                    "open": round(bar.open_price, 2),
                    "high": round(bar.high_price, 2),
                    "low": round(bar.low_price, 2),
                    "close": round(bar.close_price, 2),
                    "volume": round(bar.volume, 0),
                })

    # 按日匹配交易
    for day_str, bars in day_bars.items():
        day_trades = []
        first_bar_time = bars[0]["time"] if bars else day_str
        for t in trades:
            t_date = t["date"]
            t_day = t_date[:10] if len(t_date) >= 10 else t_date
            if t_day == day_str:
                trade_time = t_date if len(t_date) > 10 else first_bar_time
                day_trades.append({
                    "time": trade_time,
                    "side": t["side"],
                    "price": t["price"],
                    "quantity": t["quantity"],
                    "pnl": t.get("pnl", 0),
                })
        intraday_results.append({
            "date": day_str,
            "bars": bars,
            "trades": day_trades,
        })

    return intraday_results

"""
vnpy 策略实例运行引擎

基于 vnpy MainEngine + SimulatedStockGateway/XtpGateway
管理模拟/实盘策略实例的启动、停止、行情订阅、信号驱动。
替代原有 strategy_runner.py，提供相同的对外接口。
"""

import asyncio
import logging
import random
from datetime import date, datetime, timedelta
from typing import Optional

import pandas as pd

from vnpy.event import EventEngine
from vnpy.trader.constant import Direction, Exchange, Interval
from vnpy.trader.engine import MainEngine
from vnpy.trader.event import EVENT_TICK, EVENT_TRADE, EVENT_ORDER
from vnpy.trader.object import TickData, TradeData, OrderData, SubscribeRequest

from app.core.vnpy_sim_gateway import SimulatedStockGateway
from app.core.vnpy_live_gateway import vnpy_live_gateway
from app.core.live_gateway import live_gateway
from app.core.data_bridge import data_bridge
from app.core.risk_manager import risk_manager
from app.core.strategy_adapter import VNPY_STRATEGY_MAP, resolve_strategy_class
from app.strategies.base import STRATEGY_MAP, get_signal_period
from app.services.market_service import market_service
from app.services.trading_calendar_service import trading_calendar
from app.ws.manager import ws_manager
from app.database import SessionLocal
from app.models import Order

logger = logging.getLogger(__name__)

# ── A 股模拟交易费用常量 ─────────────────────────────────────────────────────
SIM_COMMISSION_RATE = 0.0003      # 佣金费率万三
SIM_MIN_COMMISSION = 5.0          # 最低佣金 5 元
SIM_STAMP_TAX_RATE = 0.001        # 印花税千一（仅卖出）


class VnpyStrategyRunner:
    """基于 vnpy 的策略实例运行器"""

    def __init__(self):
        self._event_engine: Optional[EventEngine] = None
        self._main_engine: Optional[MainEngine] = None
        self._sim_gateway: Optional[SimulatedStockGateway] = None

        # 实例管理
        self._instances: dict[str, dict] = {}  # instance_id -> config
        self._tasks: dict[str, asyncio.Task] = {}  # instance_id -> asyncio task
        self._strategies: dict[str, object] = {}  # instance_id -> CtaSignalAdapter instance

        # 实时行情缓存
        self._current_prices: dict[str, float] = {}
        self._current_ticks: dict[str, dict] = {}
        self._sub_seqs: dict[str, int] = {}

        # 策略日志
        self._logs: dict[str, list] = {}

        # 日K线缓存
        self._daily_bars: dict[str, list] = {}
        self._hist_close_prices: dict[str, float] = {}

        # 模拟账户缓存（兼容现有接口）
        self._sim_accounts: dict[str, dict] = {}  # account_id -> {balance, available, ...}
        self._sim_positions: dict[str, dict] = {}  # account_id -> {vt_symbol: {volume, avg_price, ...}}
        self._sim_buy_dates: dict[str, dict[str, date]] = {}  # account_id -> {symbol: buy_date}  T+1
        self._account_locks: dict[str, asyncio.Lock] = {}  # account_id -> Lock（防并发竞争）

        # 信号记录（验算用）
        self._signal_records: dict[str, list[dict]] = {}  # instance_id -> [{date, signal, indicators}]

    def _ensure_engine(self) -> None:
        """确保 vnpy MainEngine 已初始化，复用 engine_manager 的单例"""
        if self._main_engine:
            return

        from app.core.engine import engine_manager

        if engine_manager.available:
            self._main_engine = engine_manager.get_engine()
            self._event_engine = engine_manager._event_engine
            if self._main_engine:
                logger.info("vnpy策略运行器复用 engine_manager 的 MainEngine")
                return

        # engine_manager 不可用时，自行创建（仅用于模拟网关）
        self._event_engine = EventEngine()
        self._main_engine = MainEngine(self._event_engine)
        self._main_engine.add_gateway(SimulatedStockGateway)
        self._event_engine.start()
        logger.info("vnpy策略运行器独立 MainEngine 已启动")

    def register(self, instance_id: str, symbol: str, strategy_id: str,
                 account_id: str, mode: str = "simulation",
                 initial_equity: float = 1000000,
                 class_name: str = "", params: dict = None,
                 auto_trade_enabled: bool | None = None,
                 confirm_required: bool | None = None) -> None:
        """注册策略实例

        auto_trade_enabled / confirm_required:
        - None: 按模式取默认值（simulation→True/False, live→False/True）
        - 显式传值: 使用传入值
        """
        self._ensure_engine()
        params = params or {}

        # 按模式设置默认值
        if auto_trade_enabled is None:
            auto_trade_enabled = True if mode == "simulation" else False
        if confirm_required is None:
            confirm_required = False if mode == "simulation" else True

        self._instances[instance_id] = {
            "symbol": symbol,
            "strategy_id": strategy_id,
            "account_id": account_id,
            "mode": mode,
            "initial_equity": initial_equity,
            "class_name": class_name,
            "params": params,
            "auto_trade_enabled": auto_trade_enabled,
            "confirm_required": confirm_required,
        }

        # 创建策略实例（支持内置策略和用户自定义策略的动态编译）
        strategy_cls = resolve_strategy_class(class_name)
        if strategy_cls:
            self._strategies[instance_id] = strategy_cls(params)
        else:
            logger.warning(f"未知策略类 {class_name}，实例 {instance_id} 将不产生信号")
            self._strategies[instance_id] = None

        # 初始化模拟账户
        if mode == "simulation":
            sim_account_id = f"sim-{instance_id}"
            # 先设置默认值，再尝试从数据库恢复
            self._sim_accounts[sim_account_id] = {
                "balance": initial_equity,
                "available": initial_equity,
                "initial_capital": initial_equity,
            }
            self._sim_positions[sim_account_id] = {}
            self._sim_buy_dates.setdefault(sim_account_id, {})
            # 从数据库恢复已有的模拟账户数据
            self.load_sim_account_from_db(instance_id)

            # 连接模拟网关
            if self._sim_gateway:
                self._sim_gateway.connect({"capital": str(initial_equity)})

        # 从数据库加载历史日志
        self._load_logs_from_db(instance_id)

        # 尝试从数据库加载持久化状态（网格策略等）
        self._load_strategy_state(instance_id)

    def unregister(self, instance_id: str) -> None:
        """注销策略实例"""
        self.stop(instance_id)
        config = self._instances.pop(instance_id, None)
        self._strategies.pop(instance_id, None)
        self._logs.pop(instance_id, None)
        self._daily_bars.pop(instance_id, None)
        self._signal_records.pop(instance_id, None)

        if config:
            symbol = config["symbol"]
            self._maybe_unsubscribe(symbol)

            # 清理模拟账户
            if config.get("mode") == "simulation":
                sim_account_id = f"sim-{instance_id}"
                self._sim_accounts.pop(sim_account_id, None)
                self._sim_positions.pop(sim_account_id, None)
                self._sim_buy_dates.pop(sim_account_id, None)

    def start(self, instance_id: str) -> bool:
        """启动策略实例"""
        if instance_id not in self._instances:
            return False
        if instance_id in self._tasks and not self._tasks[instance_id].done():
            return False

        config = self._instances[instance_id]
        symbol = config["symbol"]
        mode = config.get("mode", "simulation")

        if mode == "live" and not live_gateway.is_connected:
            logger.error(f"实盘网关未连接，无法启动实例 {instance_id}")
            return False

        # 订阅实时行情
        self._subscribe(symbol)

        # 初始化策略的日K线数据
        self._init_daily_bars(instance_id, symbol)

        self._tasks[instance_id] = asyncio.create_task(
            self._run_loop(instance_id, config)
        )
        logger.info(f"策略实例已启动: {instance_id}, symbol={symbol}, mode={mode}")
        return True

    def stop(self, instance_id: str) -> bool:
        """停止策略实例"""
        task = self._tasks.get(instance_id)
        if task and not task.done():
            task.cancel()
            # 保存模拟账户数据到数据库
            config = self._instances.get(instance_id, {})
            if config.get("mode") == "simulation":
                self.save_sim_account_to_db(instance_id)
            # 保存策略状态到数据库
            self._save_strategy_state(instance_id)
            logger.info(f"策略实例已停止: {instance_id}")
            return True
        return False

    def is_running(self, instance_id: str) -> bool:
        task = self._tasks.get(instance_id)
        return task is not None and not task.done()

    # ── 价格获取 ──────────────────────────────────────────────────────────

    def _get_current_price(self, symbol: str) -> float:
        tick_price = self._current_prices.get(symbol, 0)
        if tick_price > 0:
            return tick_price
        return self._hist_close_prices.get(symbol, 0)

    # ── 行情订阅 ──────────────────────────────────────────────────

    def _subscribe(self, symbol: str) -> None:
        if symbol in self._sub_seqs:
            return

        xt_symbol = self._normalize_symbol(symbol)
        seq = market_service.subscribe_quote(
            xt_symbol, period="tick", callback=self._on_tick
        )
        if seq is not None:
            self._sub_seqs[symbol] = seq
            logger.info(f"已订阅行情: {xt_symbol}")
        else:
            logger.warning(f"订阅行情失败: {xt_symbol}，将在运行循环中通过 HTTP 获取数据")

        # 订阅后主动获取一次完整 tick 数据，确保 pre_close 有值
        if market_service.is_available() and symbol not in self._current_ticks:
            tick_data = market_service.get_full_tick(xt_symbol)
            if tick_data:
                pre_close = float(tick_data.get("lastClose", 0))
                if pre_close > 0:
                    self._current_ticks[symbol] = {
                        "symbol": symbol,
                        "last_price": float(tick_data.get("lastPrice", 0)),
                        "pre_close": pre_close,
                    }

    def _maybe_unsubscribe(self, symbol: str) -> None:
        for inst_id, config in self._instances.items():
            if config["symbol"] == symbol and self.is_running(inst_id):
                return

        seq = self._sub_seqs.pop(symbol, None)
        if seq is not None:
            market_service.unsubscribe_quote(seq)
            self._current_prices.pop(symbol, None)
            self._current_ticks.pop(symbol, None)

    def _on_tick(self, data: dict) -> None:
        symbol_raw = data.get("stock", "")
        symbol = symbol_raw.split(".")[0] if "." in symbol_raw else symbol_raw

        last_price = data.get("lastPrice", 0)
        if last_price > 0:
            self._current_prices[symbol] = float(last_price)

        # 保留之前的 pre_close（WebSocket tick 可能不含 lastClose）
        new_pre_close = float(data.get("lastClose", 0))
        old_tick = self._current_ticks.get(symbol)
        if new_pre_close <= 0 and old_tick:
            new_pre_close = old_tick.get("pre_close", 0)

        self._current_ticks[symbol] = {
            "symbol": symbol,
            "last_price": float(last_price),
            "open_price": float(data.get("open", 0)),
            "high_price": float(data.get("high", 0)),
            "low_price": float(data.get("low", 0)),
            "pre_close": new_pre_close,
            "volume": float(data.get("volume", 0)),
            "amount": float(data.get("amount", 0)),
            "bid_price_1": float(data.get("bidPrice", [0])[0]) if data.get("bidPrice") else 0,
            "bid_volume_1": float(data.get("bidVol", [0])[0]) if data.get("bidVol") else 0,
            "ask_price_1": float(data.get("askPrice", [0])[0]) if data.get("askPrice") else 0,
            "ask_volume_1": float(data.get("askVol", [0])[0]) if data.get("askVol") else 0,
            "datetime": data.get("timetag", ""),
        }

        # 注入到 vnpy 模拟网关
        if self._sim_gateway and last_price > 0:
            exchange = data_bridge.to_exchange(symbol)
            vt_symbol = f"{symbol}.{exchange.value}"
            self._sim_gateway.inject_bar_as_tick(
                vt_symbol=vt_symbol,
                open_price=float(data.get("open", last_price)),
                high_price=float(data.get("high", last_price)),
                low_price=float(data.get("low", last_price)),
                close_price=float(last_price),
                volume=float(data.get("volume", 0)),
                datetime_val=datetime.now(),
                exchange=exchange,
                pre_close=float(data.get("lastClose", 0)),
            )

    def _normalize_symbol(self, symbol: str) -> str:
        return data_bridge.to_xt_symbol(symbol)

    # ── 策略初始化 ──────────────────────────────────────────────────────────

    def _init_daily_bars(self, instance_id: str, symbol: str) -> None:
        strategy = self._strategies.get(instance_id)
        if not strategy:
            return

        try:
            end = datetime.now()
            start = end - timedelta(days=120)
            df = data_bridge.load_bars_df(
                symbol, start.strftime("%Y-%m-%d"), end.strftime("%Y-%m-%d"), "daily"
            )

            if df.empty:
                logger.warning(f"无法获取 {symbol} 日K线数据")
                return

            bars = []
            for _, row in df.iterrows():
                bars.append({
                    "date": row["date"].strftime("%Y-%m-%d"),
                    "open": float(row["open"]),
                    "high": float(row["high"]),
                    "low": float(row["low"]),
                    "close": float(row["close"]),
                    "volume": float(row["volume"]),
                    "turnover": float(row["turnover"]),
                })

            self._daily_bars[instance_id] = bars
            last_bar = bars[-1]
            self._hist_close_prices[symbol] = last_bar["close"]

            strategy.reset()
            for bar in bars:
                strategy.on_bar(bar)

            # 信号检测不再依赖 _prev_signal，基于最后两根 bar 的信号变化
            # 因此无需初始化 _prev_signal

            logger.info(f"策略 {instance_id} 已加载 {len(bars)} 根日K线，最新收盘: {last_bar['close']}")
        except Exception as e:
            logger.warning(f"加载 {symbol} 日K线数据失败: {e}")

    # ── 策略运行循环 ──────────────────────────────────────────────────────

    async def _run_loop(self, instance_id: str, config: dict) -> None:
        """策略运行循环 — 全部使用真实行情数据"""
        symbol = config["symbol"]
        mode = config.get("mode", "simulation")
        account_id = self._get_account_id(instance_id)
        strategy = self._strategies.get(instance_id)
        class_name = config.get("class_name", "")
        is_grid = (class_name == "GridStrategy")
        initial_equity = config.get("initial_equity", 1000000)

        position = 0
        avg_cost = 0.0
        last_bar_date = None
        tick_count = 0
        tick_count_save = 0

        # 从模拟账户恢复持仓状态
        if mode == "simulation":
            sim_pos = self._sim_positions.get(account_id, {}).get(symbol, {})
            if sim_pos and sim_pos.get("quantity", 0) > 0:
                position = sim_pos["quantity"]
                avg_cost = sim_pos["avg_cost"]
                logger.info(f"实例 {instance_id} 恢复持仓: {symbol} {position}@{avg_cost:.2f}")

        xt_available = market_service.is_available()
        await self._log_and_push(instance_id, "signal",
            f"策略启动，等待行情数据..." + ("" if xt_available else "（行情服务不可用，使用模拟价格波动）"), 0, 0)

        try:
            while True:
                # 优先从实时 tick 缓存获取价格
                current_price = self._get_current_price(symbol)

                # 如果没有实时 tick，从 stock_data HTTP API 获取最新行情
                if current_price <= 0:
                    xt_symbol = data_bridge.to_xt_symbol(symbol)
                    tick_data = market_service.get_full_tick(xt_symbol)
                    if tick_data and tick_data.get("lastPrice", 0) > 0:
                        current_price = float(tick_data["lastPrice"])
                        self._current_prices[symbol] = current_price
                        # 同步更新 tick 缓存
                        self._current_ticks[symbol] = {
                            "symbol": symbol,
                            "last_price": current_price,
                            "open_price": float(tick_data.get("open", 0)),
                            "high_price": float(tick_data.get("high", 0)),
                            "low_price": float(tick_data.get("low", 0)),
                            "pre_close": float(tick_data.get("lastClose", 0)),
                            "volume": float(tick_data.get("volume", 0)),
                            "amount": float(tick_data.get("amount", 0)),
                            "bid_price_1": float(tick_data.get("bidPrice", [0])[0]) if tick_data.get("bidPrice") else 0,
                            "bid_volume_1": float(tick_data.get("bidVol", [0])[0]) if tick_data.get("bidVol") else 0,
                            "ask_price_1": float(tick_data.get("askPrice", [0])[0]) if tick_data.get("askPrice") else 0,
                            "ask_volume_1": float(tick_data.get("askVol", [0])[0]) if tick_data.get("askVol") else 0,
                            "datetime": tick_data.get("timetag", ""),
                        }

                if current_price <= 0 or strategy is None:
                    await asyncio.sleep(5)
                    await self._push_account_update(instance_id)
                    continue

                # 当行情服务不可用时，模拟价格波动以产生交易信号
                if not xt_available:
                    fluctuation = random.uniform(-0.01, 0.01)
                    current_price = current_price * (1 + fluctuation)
                    self._current_prices[symbol] = current_price

                tick_count += 1
                today = datetime.now().strftime("%Y-%m-%d")
                signal_period = get_signal_period(class_name)

                # 非交易日不产生信号（模拟和实盘均适用）
                if not trading_calendar.is_trading_day():
                    await asyncio.sleep(5)
                    await self._push_account_update(instance_id)
                    continue

                # 非交易时间不产生信号（9:30-11:30, 13:00-14:57）
                if not trading_calendar.is_trading_time():
                    # 非交易时间：只更新持仓盈亏，不检测信号
                    self._update_position_prices(instance_id, symbol)
                    if mode == "simulation":
                        self.save_sim_account_to_db(instance_id)
                    await asyncio.sleep(5)
                    await self._push_account_update(instance_id)
                    continue

                # 日线策略
                if signal_period in ("daily", "1d"):
                    # 新交易日：喂一根完整的日K线
                    if last_bar_date != today:
                        tick = self._current_ticks.get(symbol)
                        bar = {
                            "date": today,
                            "open": tick.get("open_price", current_price) if tick else current_price,
                            "high": tick.get("high_price", current_price) if tick else current_price,
                            "low": tick.get("low_price", current_price) if tick else current_price,
                            "close": current_price,
                            "volume": tick.get("volume", 0) if tick else 0,
                            "turnover": tick.get("amount", 0) if tick else 0,
                        }
                        strategy.on_bar(bar)
                        last_bar_date = today
                        await self._log_and_push(instance_id, "signal",
                            f"新交易日 {today}，当前价: {current_price:.2f}", current_price, 0)
                    else:
                        # 盘中：更新当日K线的 close/high/low
                        if strategy._bars and len(strategy._bars) > 0:
                            last_bar = strategy._bars[-1]
                            last_bar["high"] = max(last_bar["high"], current_price)
                            last_bar["low"] = min(last_bar["low"], current_price)
                            last_bar["close"] = current_price

                    # 每30秒检查一次信号（tick_count % 6 ≈ 每6次循环=30秒）
                    if tick_count % 6 == 0:
                        signal, signal_reason = self._check_signal(strategy, instance_id)
                        if signal != 0:
                            await self._log_and_push(instance_id, "signal",
                                f"检测到信号: {'买入' if signal == 1 else '卖出'}，价格: {current_price:.2f} | {signal_reason}",
                                current_price, 0)
                            await self._execute_signal(
                                instance_id, symbol, account_id,
                                signal, current_price, config,
                                is_grid, position, avg_cost,
                                initial_equity, mode, signal_reason,
                            )
                            self._save_strategy_state(instance_id)
                            stats = await self.get_account_stats(instance_id)
                            if stats and stats["positions"]:
                                pos = stats["positions"][0]
                                position = pos["quantity"]
                                avg_cost = pos["avg_cost"]

                # tick / 分钟级策略
                elif signal_period in ("tick", "5m", "1m"):
                    bar = {
                        "date": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
                        "open": current_price, "high": current_price,
                        "low": current_price, "close": current_price,
                        "volume": 0, "turnover": 0,
                    }
                    strategy.on_bar(bar)
                    # 限制 bars 数量，避免内存无限增长
                    if len(strategy._bars) > 500:
                        strategy._bars = strategy._bars[-200:]
                    signal, signal_reason = self._check_signal(strategy, instance_id)

                    if signal != 0:
                        await self._log_and_push(instance_id, "signal",
                            f"检测到信号: {'买入' if signal == 1 else '卖出'}，价格: {current_price:.2f} | {signal_reason}",
                            current_price, 0)
                        await self._execute_signal(
                            instance_id, symbol, account_id,
                            signal, current_price, config,
                            is_grid, position, avg_cost,
                            initial_equity, mode, signal_reason,
                        )
                        self._save_strategy_state(instance_id)
                        stats = await self.get_account_stats(instance_id)
                        if stats and stats["positions"]:
                            pos = stats["positions"][0]
                            position = pos["quantity"]
                            avg_cost = pos["avg_cost"]

                # 更新持仓盈亏
                self._update_position_prices(instance_id, symbol)

                # 定期保存模拟账户数据到数据库（每 60 秒）
                if mode == "simulation":
                    tick_count_save += 1
                    if tick_count_save % 12 == 0:
                        self.save_sim_account_to_db(instance_id)

                await asyncio.sleep(5)
                await self._push_account_update(instance_id)

        except asyncio.CancelledError:
            logger.info(f"策略实例运行已取消: {instance_id}")
            # 更新 DB 状态为 stopped（后端重启时任务被取消）
            await self._update_instance_status(instance_id, "stopped")
        except Exception as e:
            logger.error(f"策略实例运行异常: {instance_id}, {e}", exc_info=True)
            await ws_manager.broadcast({
                "type": "strategy_error",
                "data": {
                    "instance_id": instance_id,
                    "message": f"策略运行异常: {str(e)}",
                    "time": datetime.now().strftime("%H:%M:%S"),
                }
            })
            # 更新 DB 状态为 stopped
            await self._update_instance_status(instance_id, "stopped")

    async def _update_instance_status(self, instance_id: str, status: str) -> None:
        """更新 TradingInstance 的状态到数据库"""
        from app.database import SessionLocal
        from app.models.models import TradingInstance

        db = SessionLocal()
        try:
            inst = db.query(TradingInstance).filter(TradingInstance.id == instance_id).first()
            if inst:
                inst.status = status
                db.commit()
        except Exception as e:
            logger.error(f"更新实例状态失败: {e}")
        finally:
            db.close()

    async def _execute_live_signal_sim(
        self, instance_id: str, symbol: str, account_id: str,
        signal: int, current_price: float, config: dict,
        is_grid: bool, position: int, avg_cost: float,
        signal_reason: str = "",
    ) -> None:
        """实盘信号执行（模拟成交版）

        查 AutoTradeConfig → auto_trade_enabled 直接模拟成交，
        否则建 Signal 待确认记录。成交走 _update_sim_account_buy/sell。
        """
        from app.database import SessionLocal
        from app.models.models import Signal, TradingInstance, AutoTradeConfig, Order

        side = "buy" if signal > 0 else "sell"
        grid_qty = config.get("params", {}).get("grid_quantity") or config.get("params", {}).get("trading_volume") or 100
        quantity = grid_qty if is_grid else (abs(position) if signal < 0 and position > 0 else grid_qty)

        db = SessionLocal()
        try:
            inst = db.query(TradingInstance).filter(TradingInstance.id == instance_id).first()
            user_id = inst.user_id if inst else ""
            auto_config = db.query(AutoTradeConfig).filter(
                AutoTradeConfig.account_id == account_id,
            ).first()
            auto_trade_enabled = auto_config.auto_trade_enabled if auto_config else False
            confirm_required = auto_config.confirm_required if auto_config else True

            # 风控检查
            passed, reason = risk_manager.check_order(
                account_id, symbol, side, quantity, current_price,
            )
            if not passed:
                await self._log_and_push(instance_id, "risk", f"风控拒绝: {reason}", current_price, quantity)
                return

            if auto_trade_enabled and not confirm_required:
                # T+1 和涨跌停校验
                passed, reason = self._check_t1_and_limit(account_id, symbol, side, current_price)
                if not passed:
                    await self._log_and_push(instance_id, "risk", f"交易拒绝: {reason}", current_price, quantity)
                    return

                # 自动模拟成交（加锁保护）
                async with self._get_account_lock(account_id):
                    sim_account = self._sim_accounts.get(account_id)
                    if not sim_account:
                        await self._log_and_push(instance_id, "error", "模拟账户不存在", current_price, 0)
                        return

                    if signal > 0:
                        cost = quantity * current_price
                        commission = max(cost * SIM_COMMISSION_RATE, SIM_MIN_COMMISSION)
                        if sim_account["available"] < cost + commission:
                            await self._log_and_push(instance_id, "risk",
                                f"资金不足: 可用 {sim_account['available']:.2f}, 需要 {cost + commission:.2f}",
                                current_price, quantity)
                            return
                        self._update_sim_account_buy(account_id, symbol, quantity, current_price)
                        pnl = 0
                    else:
                        positions = self._sim_positions.get(account_id, {})
                        pos = positions.get(symbol)
                        if not pos or pos["quantity"] < quantity:
                            await self._log_and_push(instance_id, "risk", "持仓不足", current_price, quantity)
                            return
                        pnl = (current_price - avg_cost) * quantity
                        self._update_sim_account_sell(account_id, symbol, quantity, current_price, avg_cost)

                # 落 Order 表
                import uuid
                order_id = str(uuid.uuid4())
                db.add(Order(
                    id=order_id, user_id=user_id, account_id=account_id,
                    symbol=symbol, side=side, type="market",
                    quantity=quantity, price=current_price, status="filled",
                    filled_quantity=quantity, filled_price=current_price,
                    source="signal_auto_sim", gateway_order_id=order_id,
                ))
                db.commit()
                self.save_sim_account_to_db(instance_id)

                await self._log_and_push(instance_id, side,
                    f"自动模拟成交 {side} {symbol} {quantity}@{current_price:.2f} | {signal_reason}",
                    current_price, quantity, pnl)
                await ws_manager.broadcast({
                    "type": "strategy_trade",
                    "data": {
                        "instance_id": instance_id, "side": side,
                        "price": current_price, "quantity": quantity,
                        "pnl": pnl, "time": datetime.now().strftime("%H:%M:%S"),
                    }
                })
            else:
                # 创建待确认信号（保留原逻辑）
                sig = Signal(
                    user_id=user_id, instance_id=instance_id, account_id=account_id,
                    symbol=symbol, side=side, price=current_price, quantity=quantity,
                    status="pending", strategy_id=config.get("strategy_id", ""),
                    reason=signal_reason,
                )
                db.add(sig)
                db.commit()
                db.refresh(sig)
                await ws_manager.broadcast({
                    "type": "strategy_signal",
                    "data": {
                        "instance_id": instance_id, "signal_id": sig.id,
                        "symbol": symbol, "side": side,
                        "price": current_price, "quantity": quantity,
                        "time": datetime.now().strftime("%H:%M:%S"),
                    }
                })
                await self._log_and_push(instance_id, "signal",
                    f"信号待确认: {side} {symbol} {quantity}股 @ {current_price:.2f}", current_price, 0)
        except Exception as e:
            logger.error(f"实盘模拟信号执行失败: {e}")
        finally:
            db.close()

    async def _execute_sim_signal_confirm(
        self, instance_id: str, symbol: str, account_id: str,
        signal: int, current_price: float, config: dict,
        is_grid: bool, position: int, avg_cost: float,
        signal_reason: str = "",
    ) -> None:
        """模拟盘信号确认模式：创建 Signal 记录，等待用户确认后成交

        当 auto_trade_enabled=False 或 confirm_required=True 时走此路径。
        """
        from app.database import SessionLocal
        from app.models.models import Signal, TradingInstance

        side = "buy" if signal > 0 else "sell"
        grid_qty = config.get("params", {}).get("grid_quantity") or config.get("params", {}).get("trading_volume") or 100
        quantity = grid_qty if is_grid else (abs(position) if signal < 0 and position > 0 else grid_qty)

        # 非网格策略买入时，计算建议数量
        if not is_grid and signal > 0 and position == 0:
            sim_account = self._sim_accounts.get(account_id, {})
            available = sim_account.get("available", 0)
            buy_amount = available * 0.9
            shares_100 = int(buy_amount / (current_price * 100)) * 100
            quantity = shares_100 if shares_100 > 0 else int(buy_amount / current_price)
            if quantity <= 0:
                await self._log_and_push(instance_id, "risk",
                    f"资金不足，无法生成买入信号", current_price, 0)
                return
        elif not is_grid and signal < 0 and position > 0:
            quantity = position

        db = SessionLocal()
        try:
            inst = db.query(TradingInstance).filter(TradingInstance.id == instance_id).first()
            user_id = inst.user_id if inst else ""

            sig = Signal(
                user_id=user_id, instance_id=instance_id, account_id=account_id,
                symbol=symbol, side=side, price=current_price, quantity=quantity,
                status="pending", strategy_id=config.get("strategy_id", ""),
                reason=signal_reason,
            )
            db.add(sig)
            db.commit()
            db.refresh(sig)

            await self._log_and_push(instance_id, "signal",
                f"信号待确认: {side} {symbol} {quantity}@{current_price:.2f} | {signal_reason}",
                current_price, quantity)

            await ws_manager.broadcast({
                "type": "strategy_signal",
                "data": {
                    "id": sig.id,
                    "instance_id": instance_id,
                    "account_id": account_id,
                    "symbol": symbol,
                    "name": "",
                    "side": side,
                    "price": current_price,
                    "quantity": quantity,
                    "status": "pending",
                    "strategy_id": config.get("strategy_id", ""),
                    "reason": signal_reason,
                    "created_at": sig.created_at.isoformat() + "Z" if sig.created_at else None,
                    "updated_at": sig.updated_at.isoformat() + "Z" if sig.updated_at else None,
                }
            })
        except Exception as e:
            logger.error(f"模拟盘信号创建失败: {e}")
        finally:
            db.close()

    async def confirm_sim_signal(self, instance_id: str, signal_id: str) -> dict:
        """确认模拟盘信号 → 执行模拟成交

        Returns:
            {"success": bool, "message": str}
        """
        from app.database import SessionLocal
        from app.models.models import Signal, Order

        account_id = self._get_account_id(instance_id)
        db = SessionLocal()
        try:
            sig = db.query(Signal).filter(Signal.id == signal_id).first()
            if not sig:
                return {"success": False, "message": "信号不存在"}
            if sig.status != "pending":
                return {"success": False, "message": f"信号状态为 {sig.status}，无法确认"}

            side = sig.side
            symbol = sig.symbol
            quantity = sig.quantity
            price = float(sig.price)

            # T+1 和涨跌停校验
            async with self._get_account_lock(account_id):
                passed, reason = self._check_t1_and_limit(account_id, symbol, side, price)
                if not passed:
                    sig.status = "rejected"
                    db.commit()
                    return {"success": False, "message": reason}

                if side == "buy":
                    sim_account = self._sim_accounts.get(account_id)
                    if not sim_account:
                        sig.status = "rejected"
                        db.commit()
                        return {"success": False, "message": "模拟账户不存在"}
                    cost = quantity * price
                    commission = max(cost * SIM_COMMISSION_RATE, SIM_MIN_COMMISSION)
                    if sim_account["available"] < cost + commission:
                        sig.status = "rejected"
                        db.commit()
                        return {"success": False, "message": f"资金不足：可用 {sim_account['available']:.2f}，需要 {cost + commission:.2f}"}
                    self._update_sim_account_buy(account_id, symbol, quantity, price)
                    pnl = 0
                elif side == "sell":
                    positions = self._sim_positions.get(account_id, {})
                    pos = positions.get(symbol)
                    if not pos or pos["quantity"] < quantity:
                        avail = pos["quantity"] if pos else 0
                        sig.status = "rejected"
                        db.commit()
                        return {"success": False, "message": f"持仓不足：可用 {avail}，需要 {quantity}"}
                    avg_cost = pos["avg_cost"]
                    self._update_sim_account_sell(account_id, symbol, quantity, price, avg_cost)
                    pnl = (price - avg_cost) * quantity
                else:
                    sig.status = "rejected"
                    db.commit()
                    return {"success": False, "message": f"不支持的方向: {side}"}

            # 更新信号状态
            sig.status = "executed"
            db.commit()

            # 落 Order 表
            import uuid
            order_id = str(uuid.uuid4())
            user_id = sig.user_id
            db.add(Order(
                id=order_id, user_id=user_id, account_id=account_id,
                symbol=symbol, side=side, type="market",
                quantity=quantity, price=price, status="filled",
                filled_quantity=quantity, filled_price=price,
                source="signal_confirmed_sim", gateway_order_id=order_id,
                signal_id=signal_id,
            ))
            db.commit()

            # 保存模拟账户数据
            self.save_sim_account_to_db(instance_id)

            # 推送通知
            await self._log_and_push(instance_id, side,
                f"信号确认成交: {side} {symbol} {quantity}@{price:.2f}",
                price, quantity, pnl)
            await ws_manager.broadcast({
                "type": "strategy_trade",
                "data": {
                    "instance_id": instance_id,
                    "side": side,
                    "price": price,
                    "quantity": quantity,
                    "pnl": pnl,
                    "time": datetime.now().strftime("%H:%M:%S"),
                }
            })

            return {"success": True, "message": "信号已确认成交"}

        except Exception as e:
            logger.error(f"确认模拟信号失败: {e}")
            return {"success": False, "message": str(e)}
        finally:
            db.close()

    async def reject_sim_signal(self, signal_id: str) -> dict:
        """拒绝模拟盘信号"""
        from app.database import SessionLocal
        from app.models.models import Signal

        db = SessionLocal()
        try:
            sig = db.query(Signal).filter(Signal.id == signal_id).first()
            if not sig:
                return {"success": False, "message": "信号不存在"}
            if sig.status != "pending":
                return {"success": False, "message": f"信号状态为 {sig.status}，无法拒绝"}

            sig.status = "rejected"
            db.commit()
            return {"success": True, "message": "信号已拒绝"}
        except Exception as e:
            logger.error(f"拒绝模拟信号失败: {e}")
            return {"success": False, "message": str(e)}
        finally:
            db.close()

    def _get_account_id(self, instance_id: str) -> str:
        # live 与 simulation 统一用模拟账户 sim-{instance_id}
        # （实盘下单改为模拟成交，不再用券商 account_id）
        return f"sim-{instance_id}"

    def _get_account_lock(self, account_id: str) -> asyncio.Lock:
        """获取账户级别的异步锁（防并发竞争）"""
        if account_id not in self._account_locks:
            self._account_locks[account_id] = asyncio.Lock()
        return self._account_locks[account_id]

    def _check_t1_and_limit(self, account_id: str, symbol: str,
                            side: str, price: float) -> tuple[bool, str]:
        """T+1 和涨跌停校验，返回 (passed, reason)"""
        today = date.today()

        # T+1: 当日买入不可卖出
        if side == "sell":
            buy_dates = self._sim_buy_dates.get(account_id, {})
            buy_date = buy_dates.get(symbol)
            if buy_date and buy_date == today:
                return False, f"T+1限制: {symbol} 今日买入不可卖出"

        # 涨跌停: 需要昨收价
        tick = self._current_ticks.get(symbol)
        pre_close = tick.get("pre_close", 0) if tick else 0
        if pre_close <= 0:
            return True, ""  # 无昨收价数据，跳过涨跌停检查

        limit_up = round(pre_close * 1.1, 2)
        limit_down = round(pre_close * 0.9, 2)

        if side == "buy" and price >= limit_up:
            return False, f"涨停不可买入: {symbol} 价格{price:.2f}>={limit_up:.2f}"
        if side == "sell" and price <= limit_down:
            return False, f"跌停不可卖出: {symbol} 价格{price:.2f}<={limit_down:.2f}"

        return True, ""

    def _check_signal(self, strategy, instance_id: str = "") -> tuple[int, str]:
        """检查策略信号（基于最后两根 bar 的信号变化检测）

        Args:
            strategy: 策略实例
            instance_id: 实例ID，用于记录信号到 _signal_records

        Returns:
            (signal, reason): signal=1/-1/0, reason=信号生成逻辑描述
        """
        try:
            df = pd.DataFrame(strategy._bars)
            for col in ["open", "high", "low", "close", "volume", "turnover"]:
                if col in df.columns:
                    df[col] = pd.to_numeric(df[col], errors="coerce")
            if "date" in df.columns:
                df["date"] = pd.to_datetime(df["date"], format="mixed")
            signals = strategy.generate_signals(df, strategy.setting)
            if isinstance(signals, tuple):
                signals = signals[0]

            if signals is None or len(signals) < 2:
                return 0, ""

            # 取最后两根 bar 的信号值
            current_signal = int(signals.iloc[-1])
            prev_bar_signal = int(signals.iloc[-2])

            # 构建信号路径描述
            class_name = getattr(strategy, 'class_name', type(strategy).__name__)
            last_bar = strategy._bars[-1] if strategy._bars else {}
            prev_bar = strategy._bars[-2] if len(strategy._bars) >= 2 else {}
            last_close = float(last_bar.get("close", 0))
            prev_close = float(prev_bar.get("close", 0))
            last_date = last_bar.get("date", "")
            prev_date = prev_bar.get("date", "")

            # 生成策略指标详情
            indicator_detail = self._describe_strategy_indicators(strategy, df)

            # 记录当前bar的信号值（用于验算）
            if instance_id:
                records = self._signal_records.setdefault(instance_id, [])
                records.append({
                    "date": str(last_date),
                    "signal": current_signal,
                    "prev_signal": prev_bar_signal,
                    "close": last_close,
                    "indicators": indicator_detail,
                })

            if current_signal != prev_bar_signal:
                state_map = {0: "空仓", 1: "买入/持仓", -1: "卖出/做空"}
                reason = (
                    f"[{class_name}] 信号状态转换: "
                    f"{state_map.get(prev_bar_signal, prev_bar_signal)} → {state_map.get(current_signal, current_signal)} | "
                    f"前一根bar[{prev_date}] close={prev_close:.2f} signal={prev_bar_signal} → "
                    f"当前bar[{last_date}] close={last_close:.2f} signal={current_signal} | "
                    f"{indicator_detail}"
                )
                return current_signal, reason
            return 0, ""
        except Exception as e:
            logger.warning(f"信号计算异常: {e}")
            return 0, ""

    def _describe_strategy_indicators(self, strategy, df: pd.DataFrame) -> str:
        """根据策略类型生成指标值描述"""
        from app.strategies.base import (
            sma, ema, rsi as calc_rsi, macd as calc_macd,
            bollinger as calc_bollinger, atr as calc_atr,
            donchian, kdj as calc_kdj, cci as calc_cci,
        )
        class_name = getattr(strategy, 'class_name', type(strategy).__name__)
        setting = strategy.setting
        close = df["close"]
        high = df["high"]
        low = df["low"]

        try:
            if class_name == "DoubleMaStrategy":
                fw = setting.get("fast_window", 10)
                sw = setting.get("slow_window", 20)
                fast = sma(close, fw)
                slow = sma(close, sw)
                return f"MA{fw}={fast.iloc[-1]:.2f}, MA{sw}={slow.iloc[-1]:.2f}, 金叉/死叉"

            elif class_name == "MacdStrategy":
                fp = setting.get("fast_period", 12)
                sp = setting.get("slow_period", 26)
                sigp = setting.get("signal_period", 9)
                dif, dea, hist = calc_macd(close, fp, sp, sigp)
                return f"DIF={dif.iloc[-1]:.4f}, DEA={dea.iloc[-1]:.4f}, HIST={hist.iloc[-1]:.4f}, DIF/DEA金叉/死叉"

            elif class_name == "BollingerStrategy":
                bw = setting.get("boll_window", 20)
                bd = setting.get("boll_dev", 2.0)
                mid, upper, lower = calc_bollinger(close, bw, bd)
                return f"中轨={mid.iloc[-1]:.2f}, 上轨={upper.iloc[-1]:.2f}, 下轨={lower.iloc[-1]:.2f}, 价格触及轨道"

            elif class_name == "RsiStrategy":
                rw = setting.get("rsi_window", 14)
                rob = setting.get("rsi_overbought", 70)
                ros = setting.get("rsi_oversold", 30)
                rsi_val = calc_rsi(close, rw)
                return f"RSI{rw}={rsi_val.iloc[-1]:.2f}, 超买={rob}, 超卖={ros}, 穿越阈值"

            elif class_name == "TurtleStrategy":
                ew = setting.get("entry_window", 20)
                xw = setting.get("exit_window", 10)
                entry_up, entry_down = donchian(high, low, ew)
                exit_up, exit_down = donchian(high, low, xw)
                return f"入场通道: 上={entry_up.iloc[-1]:.2f} 下={entry_down.iloc[-1]:.2f}, 出场通道: 下={exit_down.iloc[-1]:.2f}, 突破"

            elif class_name == "KdjStrategy":
                kw = setting.get("kdj_window", 9)
                ks = setting.get("k_smooth", 3)
                ds = setting.get("d_smooth", 3)
                k, d, j = calc_kdj(high, low, close, kw, ks, ds)
                return f"K={k.iloc[-1]:.2f}, D={d.iloc[-1]:.2f}, J={j.iloc[-1]:.2f}, K/D金叉死叉+超买超卖区"

            elif class_name == "CciStrategy":
                cw = setting.get("cci_window", 14)
                cob = setting.get("cci_overbought", 100)
                cos_ = setting.get("cci_oversold", -100)
                cci_val = calc_cci(high, low, close, cw)
                return f"CCI{cw}={cci_val.iloc[-1]:.2f}, 超买={cob}, 超卖={cos_}, 穿越阈值"

            elif class_name == "TripleMaStrategy":
                fw = setting.get("fast_window", 5)
                mw = setting.get("mid_window", 20)
                sw = setting.get("slow_window", 60)
                fast = sma(close, fw)
                mid = sma(close, mw)
                slow = sma(close, sw)
                return f"MA{fw}={fast.iloc[-1]:.2f}, MA{mw}={mid.iloc[-1]:.2f}, MA{sw}={slow.iloc[-1]:.2f}, 多头/空头排列"

            elif class_name == "EmaCrossStrategy":
                fw = setting.get("fast_window", 12)
                sw = setting.get("slow_window", 26)
                fast = ema(close, fw)
                slow = ema(close, sw)
                return f"EMA{fw}={fast.iloc[-1]:.2f}, EMA{sw}={slow.iloc[-1]:.2f}, 金叉/死叉"

            elif class_name == "VolumeMaStrategy":
                mw = setting.get("ma_window", 20)
                vw = setting.get("vol_window", 20)
                vr = setting.get("vol_ratio", 1.5)
                price_ma = sma(close, mw)
                vol_ma = sma(df["volume"], vw)
                return f"价格MA{mw}={price_ma.iloc[-1]:.2f}, 量MA{vw}={vol_ma.iloc[-1]:.0f}, 量比阈值={vr}, 放量突破/破位"

            elif class_name == "MomentumStrategy":
                momw = setting.get("mom_window", 10)
                momt = setting.get("mom_threshold", 0.03)
                maw = setting.get("ma_window", 20)
                momentum = close / close.shift(momw) - 1
                price_ma = sma(close, maw)
                return f"动量{momw}期={momentum.iloc[-1]:.4f}, 阈值=±{momt}, 价格MA{maw}={price_ma.iloc[-1]:.2f}, 穿越阈值+趋势确认"

            elif class_name == "AtrChannelStrategy":
                aw = setting.get("atr_window", 14)
                am = setting.get("atr_mult", 2.0)
                maw = setting.get("ma_window", 20)
                price_ma = sma(close, maw)
                atr_val = calc_atr(high, low, close, aw)
                upper = price_ma + am * atr_val
                lower = price_ma - am * atr_val
                return f"中轨={price_ma.iloc[-1]:.2f}, 上轨={upper.iloc[-1]:.2f}, 下轨={lower.iloc[-1]:.2f}, ATR{aw}={atr_val.iloc[-1]:.2f}, 价格从通道外回到通道内"

            elif class_name == "DualThrustStrategy":
                nw = setting.get("n_window", 4)
                ku = setting.get("k_up", 0.5)
                kd = setting.get("k_down", 0.5)
                hh = high.rolling(window=nw, min_periods=nw).max()
                hc = close.rolling(window=nw, min_periods=nw).max()
                lc = close.rolling(window=nw, min_periods=nw).min()
                ll = low.rolling(window=nw, min_periods=nw).min()
                range_val = pd.concat([hh - lc, hc - ll], axis=1).max(axis=1)
                upper_bound = close.shift(1) + ku * range_val.shift(1)
                lower_bound = close.shift(1) - kd * range_val.shift(1)
                return f"上界={upper_bound.iloc[-1]:.2f}, 下界={lower_bound.iloc[-1]:.2f}, N={nw}, K上={ku}/下={kd}, 价格从带外回到带内"

            elif class_name == "GridStrategy":
                gs = setting.get("grid_size") or setting.get("grid_step") or 0.02
                gq = setting.get("grid_quantity") or setting.get("trading_volume") or 100
                return f"网格间距={gs}, 每层数量={gq}, 价格穿越网格线"

            return f"策略: {class_name}"
        except Exception:
            return f"策略: {class_name}"

    # ── 信号验算 ──────────────────────────────────────────────────────────

    def verify_signals(self, instance_id: str) -> dict:
        """验算策略信号正确性

        用当前积累的K线数据批量重算信号，与增量信号记录逐条对比。

        Returns:
            {
                "total_bars": K线数量,
                "total_signal_checks": 信号检查次数,
                "batch_signals": 批量重算的信号序列摘要,
                "incremental_signals": 增量记录的信号序列摘要,
                "signal_mismatches": 信号不一致列表,
                "trade_mismatches": 交易逻辑不一致列表,
                "indicator_snapshots": 指标快照列表,
                "passed": 是否全部通过,
            }
        """
        strategy = self._strategies.get(instance_id)
        config = self._instances.get(instance_id)

        if not strategy or not config:
            return {"error": "实例未注册", "passed": False}

        bars = strategy._bars
        if len(bars) < 2:
            return {"error": "K线数据不足（至少需要2根）", "passed": False}

        # 1. 构造 DataFrame 并批量重算信号
        df = pd.DataFrame(bars)
        for col in ["open", "high", "low", "close", "volume", "turnover"]:
            if col in df.columns:
                df[col] = pd.to_numeric(df[col], errors="coerce")
        if "date" in df.columns:
            df["date"] = pd.to_datetime(df["date"], format="mixed")

        batch_result = strategy.generate_signals(df, strategy.setting)
        if isinstance(batch_result, tuple):
            batch_signals = batch_result[0]
        else:
            batch_signals = batch_result

        batch_signal_list = [int(s) for s in batch_signals] if batch_signals is not None else []

        # 2. 获取增量信号记录
        signal_records = self._signal_records.get(instance_id, [])

        # 3. 信号一致性对比
        # 增量记录是每次 _check_signal 调用时记录的，记录的是当前bar的信号值
        # 批量信号是每根bar的信号值
        # 对比方式：增量记录中的信号值应与批量信号中对应位置的信号值一致
        signal_mismatches = []
        if signal_records:
            # 增量记录的 index 对应 _check_signal 调用时 _bars 的长度
            # 每次 _check_signal 调用时，_bars 已有 N 根，记录的是 signals[N-1]
            # 所以增量记录第 i 条对应 batch_signals 的第 (bars_count_at_check_i - 1) 根
            # 但增量记录没有保存 bars_count，需要用另一种方式对比：
            # 对比增量记录中所有非零信号（实际触发的交易信号）与批量信号中的对应位置
            for rec in signal_records:
                if rec["signal"] != rec["prev_signal"] and rec["signal"] != 0:
                    # 这是一个实际触发的信号转换点
                    # 在批量信号中找到对应日期
                    rec_date = rec["date"]
                    # 查找批量信号中同日期的信号
                    for j, bar in enumerate(bars):
                        if str(bar.get("date", "")) == rec_date and j < len(batch_signal_list):
                            batch_sig = batch_signal_list[j]
                            if batch_sig != rec["signal"]:
                                signal_mismatches.append({
                                    "date": rec_date,
                                    "incremental_signal": rec["signal"],
                                    "batch_signal": batch_sig,
                                    "close": rec["close"],
                                })
                            break

        # 4. 交易逻辑合理性检查
        # 普通策略：买入后不应再买入，卖出后不应再卖出
        # 网格策略：信号值表示穿越层数，不做此检查
        class_name = config.get("class_name", "")
        is_grid = (class_name == "GridStrategy")
        trade_mismatches = []

        if not is_grid and batch_signal_list:
            prev_nonzero = 0
            for i, sig in enumerate(batch_signal_list):
                if sig != 0:
                    if sig == prev_nonzero:
                        trade_mismatches.append({
                            "index": i,
                            "date": str(bars[i].get("date", "")) if i < len(bars) else "",
                            "signal": sig,
                            "issue": f"连续同号信号（{sig}），前一次信号也是{prev_nonzero}",
                        })
                    prev_nonzero = sig

        # 5. 指标快照（批量重算时每个信号点的指标值）
        indicator_snapshots = []
        if batch_signal_list:
            for i, sig in enumerate(batch_signal_list):
                if sig != 0 and i < len(bars):
                    # 取该信号点的指标描述
                    sub_df = df.iloc[:i+1]
                    try:
                        indicator_detail = self._describe_strategy_indicators(strategy, sub_df)
                    except Exception:
                        indicator_detail = ""
                    indicator_snapshots.append({
                        "index": i,
                        "date": str(bars[i].get("date", "")),
                        "signal": sig,
                        "close": float(bars[i].get("close", 0)),
                        "indicators": indicator_detail,
                    })

        # 6. 汇总结果
        passed = len(signal_mismatches) == 0 and len(trade_mismatches) == 0

        return {
            "total_bars": len(bars),
            "total_signal_checks": len(signal_records),
            "batch_signal_summary": {
                "total": len(batch_signal_list),
                "buy_signals": sum(1 for s in batch_signal_list if s > 0),
                "sell_signals": sum(1 for s in batch_signal_list if s < 0),
                "hold_signals": sum(1 for s in batch_signal_list if s == 0),
            },
            "signal_mismatches": signal_mismatches[:20],
            "trade_mismatches": trade_mismatches[:20],
            "indicator_snapshots": indicator_snapshots[:50],
            "passed": passed,
        }

    async def _execute_signal(
        self, instance_id: str, symbol: str, account_id: str,
        signal: int, current_price: float, config: dict,
        is_grid: bool, position: int, avg_cost: float,
        initial_equity: float, mode: str, signal_reason: str = "",
    ) -> None:
        """根据信号执行交易"""
        # 实盘模式：创建 Signal 记录，根据 AutoTradeConfig 决定自动下单或等待确认
        if mode == "live":
            # 实盘下单改为模拟成交：查 AutoTradeConfig 决定自动模拟成交 or 建 Signal 待确认
            await self._execute_live_signal_sim(
                instance_id, symbol, account_id, signal,
                current_price, config, is_grid, position, avg_cost,
                signal_reason,
            )
            return

        # 模拟模式：查 AutoTradeConfig 决定自动成交 or 建 Signal 待确认
        if mode == "simulation":
            auto_trade_enabled = config.get("auto_trade_enabled", True)
            confirm_required = config.get("confirm_required", False)
            if not auto_trade_enabled or confirm_required:
                await self._execute_sim_signal_confirm(
                    instance_id, symbol, account_id, signal,
                    current_price, config, is_grid, position, avg_cost,
                    signal_reason,
                )
                return

        grid_qty = config.get("params", {}).get("grid_quantity") or config.get("params", {}).get("trading_volume") or 100

        try:
            if is_grid:
                if signal == 1:
                    cost = grid_qty * current_price
                    commission = max(cost * SIM_COMMISSION_RATE, SIM_MIN_COMMISSION)

                    if mode == "live":
                        passed, reason = risk_manager.check_order(
                            account_id, symbol, "buy", grid_qty, current_price,
                        )
                        if not passed:
                            await self._log_and_push(instance_id, "risk", f"风控拒绝: {reason}", current_price, grid_qty)
                            return

                    if mode == "simulation":
                        async with self._get_account_lock(account_id):
                            # 模拟模式：T+1 和涨跌停校验
                            passed, reason = self._check_t1_and_limit(account_id, symbol, "buy", current_price)
                            if not passed:
                                await self._log_and_push(instance_id, "risk", f"交易拒绝: {reason}", current_price, grid_qty)
                                return
                            # 直接更新模拟账户
                            sim_account = self._sim_accounts.get(account_id)
                            if sim_account and sim_account["available"] >= cost + commission:
                                self._update_sim_account_buy(account_id, symbol, grid_qty, current_price)
                                await self._log_and_push(instance_id, "buy",
                                    f"网格买入 {symbol} {grid_qty}@{current_price:.2f}",
                                    current_price, grid_qty)
                                await ws_manager.broadcast({
                                    "type": "strategy_trade",
                                    "data": {
                                        "instance_id": instance_id,
                                        "side": "buy",
                                        "price": current_price,
                                        "quantity": grid_qty,
                                        "pnl": 0,
                                        "time": datetime.now().strftime("%H:%M:%S"),
                                    }
                                })
                            else:
                                avail = sim_account["available"] if sim_account else 0
                                await self._log_and_push(instance_id, "risk",
                                    f"资金不足: 可用 {avail:.2f}, 需要 {cost + commission:.2f}", current_price, grid_qty)
                    else:
                        # 实盘：通过 live_gateway 下单
                        vt_orderid = await self._place_order_via_vnpy(
                            mode, account_id, symbol, "buy", grid_qty, current_price, "market"
                        )
                        if vt_orderid:
                            risk_manager.record_order(account_id)
                            await self._log_and_push(instance_id, "buy",
                                f"网格买入 {symbol} {grid_qty}@{current_price:.2f}",
                                current_price, grid_qty)

                elif signal == -1 and position > 0:
                    sell_qty = min(grid_qty, position)

                    if mode == "live":
                        passed, reason = risk_manager.check_order(
                            account_id, symbol, "sell", sell_qty, current_price,
                        )
                        if not passed:
                            await self._log_and_push(instance_id, "risk", f"风控拒绝: {reason}", current_price, sell_qty)
                            return

                    if mode == "simulation":
                        async with self._get_account_lock(account_id):
                            # 模拟模式：T+1 和涨跌停校验
                            passed, reason = self._check_t1_and_limit(account_id, symbol, "sell", current_price)
                            if not passed:
                                await self._log_and_push(instance_id, "risk", f"交易拒绝: {reason}", current_price, sell_qty)
                                return
                            # 直接更新模拟账户
                            pnl = (current_price - avg_cost) * sell_qty
                            self._update_sim_account_sell(account_id, symbol, sell_qty, current_price, avg_cost)
                            await self._log_and_push(instance_id, "sell",
                                f"网格卖出 {symbol} {sell_qty}@{current_price:.2f}, 盈亏: {pnl:.2f}",
                                current_price, sell_qty, pnl)
                            await ws_manager.broadcast({
                                "type": "strategy_trade",
                                "data": {
                                    "instance_id": instance_id,
                                    "side": "sell",
                                    "price": current_price,
                                    "quantity": sell_qty,
                                    "pnl": pnl,
                                    "time": datetime.now().strftime("%H:%M:%S"),
                                }
                            })
                    else:
                        # 实盘：通过 live_gateway 下单
                        vt_orderid = await self._place_order_via_vnpy(
                            mode, account_id, symbol, "sell", sell_qty, current_price, "market"
                        )
                        if vt_orderid:
                            pnl = (current_price - avg_cost) * sell_qty
                            risk_manager.record_order(account_id)
                            risk_manager.record_loss(account_id, pnl)
                            await self._log_and_push(instance_id, "sell",
                                f"网格卖出 {symbol} {sell_qty}@{current_price:.2f}, 盈亏: {pnl:.2f}",
                                current_price, sell_qty, pnl)

            else:
                # 非网格策略
                if mode == "simulation":
                    sim_account = self._sim_accounts.get(account_id, {})
                    available = sim_account.get("available", 0)
                else:
                    try:
                        account_data = await live_gateway.get_account()
                        available = float(account_data.get("available_cash", 0))
                    except Exception:
                        available = 0

                if signal == 1 and position == 0:
                    buy_amount = available * 0.9
                    shares_100 = int(buy_amount / (current_price * 100)) * 100
                    shares = shares_100 if shares_100 > 0 else int(buy_amount / current_price)
                    if shares <= 0:
                        return

                    if mode == "live":
                        passed, reason = risk_manager.check_order(
                            account_id, symbol, "buy", shares, current_price,
                        )
                        if not passed:
                            await self._log_and_push(instance_id, "risk", f"风控拒绝: {reason}", current_price, shares)
                            return

                    if mode == "simulation":
                        async with self._get_account_lock(account_id):
                            # 模拟模式：T+1 和涨跌停校验
                            passed, reason = self._check_t1_and_limit(account_id, symbol, "buy", current_price)
                            if not passed:
                                await self._log_and_push(instance_id, "risk", f"交易拒绝: {reason}", current_price, shares)
                                return
                            # 资金充足性校验（佣金可能使 cost + commission > available）
                            cost = shares * current_price
                            commission = max(cost * SIM_COMMISSION_RATE, SIM_MIN_COMMISSION)
                            if available < cost + commission:
                                # 降档：减少到可用资金能买的最大整手
                                shares_100 = int((available - SIM_MIN_COMMISSION) / (current_price * 100)) * 100
                                shares = shares_100 if shares_100 > 0 else int((available - SIM_MIN_COMMISSION) / current_price)
                                if shares <= 0:
                                    await self._log_and_push(instance_id, "risk",
                                        f"资金不足: 可用 {available:.2f}", current_price, 0)
                                    return
                            # 直接更新模拟账户
                            self._update_sim_account_buy(account_id, symbol, shares, current_price)
                            await self._log_and_push(instance_id, "buy",
                                f"买入 {symbol} {shares}@{current_price:.2f}",
                                current_price, shares)
                            await ws_manager.broadcast({
                                "type": "strategy_trade",
                                "data": {
                                    "instance_id": instance_id,
                                    "side": "buy",
                                    "price": current_price,
                                    "quantity": shares,
                                    "pnl": 0,
                                    "time": datetime.now().strftime("%H:%M:%S"),
                                }
                            })
                    else:
                        vt_orderid = await self._place_order_via_vnpy(
                            mode, account_id, symbol, "buy", shares, current_price, "market"
                        )
                        if vt_orderid:
                            risk_manager.record_order(account_id)
                            await self._log_and_push(instance_id, "buy",
                                f"买入 {symbol} {shares}@{current_price:.2f}",
                                current_price, shares)

                elif signal == -1 and position > 0:
                    if mode == "live":
                        passed, reason = risk_manager.check_order(
                            account_id, symbol, "sell", position, current_price,
                        )
                        if not passed:
                            await self._log_and_push(instance_id, "risk", f"风控拒绝: {reason}", current_price, position)
                            return

                    if mode == "simulation":
                        async with self._get_account_lock(account_id):
                            # 模拟模式：T+1 和涨跌停校验
                            passed, reason = self._check_t1_and_limit(account_id, symbol, "sell", current_price)
                            if not passed:
                                await self._log_and_push(instance_id, "risk", f"交易拒绝: {reason}", current_price, position)
                                return
                            # 直接更新模拟账户
                            pnl = (current_price - avg_cost) * position
                            self._update_sim_account_sell(account_id, symbol, position, current_price, avg_cost)
                            await self._log_and_push(instance_id, "sell",
                                f"卖出 {symbol} {position}@{current_price:.2f}, 盈亏: {pnl:.2f}",
                                current_price, position, pnl)
                            await ws_manager.broadcast({
                                "type": "strategy_trade",
                                "data": {
                                    "instance_id": instance_id,
                                    "side": "sell",
                                    "price": current_price,
                                    "quantity": position,
                                    "pnl": pnl,
                                    "time": datetime.now().strftime("%H:%M:%S"),
                                }
                            })
                    else:
                        vt_orderid = await self._place_order_via_vnpy(
                            mode, account_id, symbol, "sell", position, current_price, "market"
                        )
                        if vt_orderid:
                            pnl = (current_price - avg_cost) * position
                            risk_manager.record_order(account_id)
                            risk_manager.record_loss(account_id, pnl)
                            await self._log_and_push(instance_id, "sell",
                                f"卖出 {symbol} {position}@{current_price:.2f}, 盈亏: {pnl:.2f}",
                                current_price, position, pnl)

            # 模拟模式：保存账户数据到 DB
            if mode == "simulation":
                self.save_sim_account_to_db(instance_id)

        except RuntimeError as e:
            # 实盘下单失败：暂停策略并通知前端
            logger.error(f"实例 {instance_id} 下单失败，暂停策略: {e}")
            self.stop(instance_id)
            await self._log_and_push(instance_id, "error",
                f"下单失败，策略已暂停: {e}", current_price, 0)
            await ws_manager.broadcast({
                "type": "strategy_error",
                "data": {
                    "instance_id": instance_id,
                    "message": f"下单失败，策略已暂停: {e}",
                    "time": datetime.now().strftime("%H:%M:%S"),
                }
            })
            # 更新 DB 状态
            await self._update_instance_status(instance_id, "stopped")

    async def _place_order_via_vnpy(
        self, mode: str, account_id: str, symbol: str,
        side: str, quantity: int, price: float, order_type: str,
    ) -> Optional[str]:
        """下单：实盘走 live_gateway（stock_trade API），模拟走 vnpy SimulatedStockGateway
        实盘下单失败时抛异常，由调用方暂停策略并通知前端
        """
        if mode == "live":
            if not live_gateway.is_connected:
                raise RuntimeError("交易网关未连接")
            try:
                result = await live_gateway.place_order(
                    symbol=symbol, side=side, quantity=quantity,
                    price=price, order_type=order_type,
                )
                order_id = result.get("order_id", "")
                if order_id:
                    logger.info(f"实盘下单成功: {side} {symbol} {quantity}@{price}, order_id={order_id}")
                    return order_id
                else:
                    raise RuntimeError(f"实盘下单返回无 order_id: {result}")
            except RuntimeError:
                raise
            except Exception as e:
                raise RuntimeError(f"实盘下单异常: {e}") from e
        else:
            # 模拟模式：直接通过 SimulatedStockGateway
            exchange = data_bridge.to_exchange(symbol)
            if self._sim_gateway:
                from vnpy.trader.constant import Direction, Offset, OrderType as VnpyOrderType
                from vnpy.trader.object import OrderRequest

                direction = Direction.LONG if side == "buy" else Direction.SHORT
                offset = Offset.OPEN if side == "buy" else Offset.CLOSE
                vnpy_order_type = VnpyOrderType.MARKET if order_type == "market" else VnpyOrderType.LIMIT

                req = OrderRequest(
                    symbol=symbol,
                    exchange=exchange,
                    direction=direction,
                    type=vnpy_order_type,
                    volume=quantity,
                    price=price,
                    offset=offset,
                )
                return self._sim_gateway.send_order(req)
        return None

    # ── 模拟账户更新 ──────────────────────────────────────────────────────

    def _update_sim_account_buy(self, account_id: str, symbol: str,
                                 quantity: int, price: float) -> None:
        """更新模拟账户买入"""
        account = self._sim_accounts.get(account_id)
        if not account:
            return

        cost = quantity * price
        commission = max(cost * SIM_COMMISSION_RATE, SIM_MIN_COMMISSION)
        account["balance"] -= (cost + commission)
        account["available"] -= (cost + commission)

        positions = self._sim_positions.setdefault(account_id, {})
        pos = positions.get(symbol, {"quantity": 0, "avg_cost": 0, "current_price": 0, "market_value": 0})
        total_cost = pos["avg_cost"] * pos["quantity"] + price * quantity
        pos["quantity"] += quantity
        pos["avg_cost"] = total_cost / pos["quantity"] if pos["quantity"] > 0 else 0
        pos["current_price"] = price
        pos["market_value"] = pos["quantity"] * price
        positions[symbol] = pos

        # T+1 标记
        buy_dates = self._sim_buy_dates.setdefault(account_id, {})
        buy_dates[symbol] = date.today()

    def _update_sim_account_sell(self, account_id: str, symbol: str,
                                  quantity: int, price: float, avg_cost: float) -> None:
        """更新模拟账户卖出"""
        account = self._sim_accounts.get(account_id)
        if not account:
            return

        revenue = quantity * price
        commission = max(revenue * SIM_COMMISSION_RATE, SIM_MIN_COMMISSION)
        stamp_tax = revenue * SIM_STAMP_TAX_RATE
        account["balance"] += (revenue - commission - stamp_tax)
        account["available"] += (revenue - commission - stamp_tax)

        positions = self._sim_positions.get(account_id, {})
        pos = positions.get(symbol, {"quantity": 0, "avg_cost": 0, "current_price": 0, "market_value": 0})
        pos["quantity"] -= quantity
        if pos["quantity"] <= 0:
            pos["quantity"] = 0
            pos["avg_cost"] = 0
            # 清仓时清除 T+1 标记
            buy_dates = self._sim_buy_dates.get(account_id, {})
            buy_dates.pop(symbol, None)
        pos["current_price"] = price
        pos["market_value"] = pos["quantity"] * price
        positions[symbol] = pos

    def _update_position_prices(self, instance_id: str, symbol: str) -> None:
        """更新持仓的实时价格（遍历该账户所有持仓 symbol）"""
        config = self._instances.get(instance_id)
        if not config:
            return

        mode = config.get("mode", "simulation")
        account_id = self._get_account_id(instance_id)

        if mode == "simulation":
            positions = self._sim_positions.get(account_id, {})
            for sym, pos in positions.items():
                sym_price = self._get_current_price(sym)
                if sym_price > 0 and pos["quantity"] > 0:
                    pos["current_price"] = sym_price
                    pos["market_value"] = pos["quantity"] * sym_price

    # ── 策略状态持久化 ──────────────────────────────────────────────────────

    def _load_strategy_state(self, instance_id: str) -> None:
        """从数据库加载策略持久化状态（网格策略等）"""
        strategy = self._strategies.get(instance_id)
        if not strategy or not hasattr(strategy, 'load_state'):
            return

        from app.database import SessionLocal
        from app.models.models import StrategyState

        db = SessionLocal()
        try:
            state_record = db.query(StrategyState).filter(
                StrategyState.strategy_name == instance_id,
            ).first()
            if state_record:
                data = {
                    "grid_states_json": state_record.grid_states_json,
                    "signal_state": state_record.signal_state,
                    "buy_date": state_record.buy_date,
                    "bar_index": state_record.bar_index,
                    "prev_price": float(state_record.prev_price),
                }
                strategy.load_state(data)
                logger.info(f"策略状态已从数据库恢复: {instance_id}")
        except Exception as e:
            logger.warning(f"加载策略状态失败: {e}")
        finally:
            db.close()

    def _save_strategy_state(self, instance_id: str) -> None:
        """保存策略状态到数据库"""
        strategy = self._strategies.get(instance_id)
        if not strategy or not hasattr(strategy, 'save_state'):
            return

        from app.database import SessionLocal
        from app.models.models import StrategyState

        db = SessionLocal()
        try:
            state_dict = strategy.save_state()
            strategy_name = state_dict.get("strategy_name", instance_id)

            state_record = db.query(StrategyState).filter(
                StrategyState.strategy_name == strategy_name,
            ).first()

            if state_record:
                state_record.grid_states_json = state_dict.get("grid_states_json", "{}")
                state_record.signal_state = state_dict.get("signal_state", 0)
                state_record.buy_date = state_dict.get("buy_date")
                state_record.bar_index = state_dict.get("bar_index", 0)
                state_record.prev_price = state_dict.get("prev_price", 0)
                state_record.class_name = state_dict.get("class_name", "")
                state_record.vt_symbol = state_dict.get("vt_symbol", "")
            else:
                state_record = StrategyState(
                    strategy_name=strategy_name,
                    class_name=state_dict.get("class_name", ""),
                    vt_symbol=state_dict.get("vt_symbol", ""),
                    grid_states_json=state_dict.get("grid_states_json", "{}"),
                    signal_state=state_dict.get("signal_state", 0),
                    buy_date=state_dict.get("buy_date"),
                    bar_index=state_dict.get("bar_index", 0),
                    prev_price=state_dict.get("prev_price", 0),
                )
                db.add(state_record)

            db.commit()
            logger.info(f"策略状态已保存到数据库: {strategy_name}")
        except Exception as e:
            logger.warning(f"保存策略状态失败: {e}")
        finally:
            db.close()

    # ── 模拟账户持久化 ──────────────────────────────────────────────────────

    def save_sim_account_to_db(self, instance_id: str) -> None:
        """将模拟账户数据保存到数据库"""
        from app.database import SessionLocal
        from app.models.models import TradingInstance

        account_id = self._get_account_id(instance_id)
        account = self._sim_accounts.get(account_id)
        positions = self._sim_positions.get(account_id, {})

        if not account:
            return

        # 序列化持仓（只保存有数量的持仓）
        saved_positions = {}
        for sym, pos in positions.items():
            if pos["quantity"] > 0:
                saved_positions[sym] = {
                    "quantity": pos["quantity"],
                    "avg_cost": pos["avg_cost"],
                    "current_price": pos.get("current_price", pos["avg_cost"]),
                    "market_value": pos.get("market_value", 0),
                }

        data = {
            "balance": account["balance"],
            "available": account["available"],
            "initial_capital": account.get("initial_capital", account["balance"]),
            "positions": saved_positions,
            "buy_dates": {
                sym: dt.isoformat()
                for sym, dt in self._sim_buy_dates.get(account_id, {}).items()
            },
        }

        db = SessionLocal()
        try:
            inst = db.query(TradingInstance).filter(TradingInstance.id == instance_id).first()
            if inst:
                inst.sim_account_data = data
                inst.current_equity = account["balance"] + sum(
                    p.get("market_value", 0) for p in saved_positions.values()
                )
                db.commit()
        except Exception as e:
            logger.error(f"保存模拟账户数据失败: {e}")
        finally:
            db.close()

    def load_sim_account_from_db(self, instance_id: str) -> None:
        """从数据库恢复模拟账户数据"""
        from app.database import SessionLocal
        from app.models.models import TradingInstance

        account_id = self._get_account_id(instance_id)

        db = SessionLocal()
        try:
            inst = db.query(TradingInstance).filter(TradingInstance.id == instance_id).first()
            if not inst or not inst.sim_account_data:
                return

            data = inst.sim_account_data
            if isinstance(data, str):
                import json
                data = json.loads(data)

            # 恢复账户余额
            self._sim_accounts[account_id] = {
                "balance": data["balance"],
                "available": data["available"],
                "initial_capital": data.get("initial_capital", data["balance"]),
            }

            # 恢复持仓
            saved_positions = data.get("positions", {})
            positions = {}
            for sym, pos_data in saved_positions.items():
                positions[sym] = {
                    "quantity": pos_data["quantity"],
                    "avg_cost": pos_data["avg_cost"],
                    "current_price": pos_data.get("current_price", pos_data["avg_cost"]),
                    "market_value": pos_data.get("market_value", 0),
                }
            self._sim_positions[account_id] = positions

            # 恢复 T+1 买入日期
            saved_buy_dates = data.get("buy_dates", {})
            buy_dates = {}
            for sym, dt_str in saved_buy_dates.items():
                try:
                    buy_dates[sym] = date.fromisoformat(dt_str)
                except (ValueError, TypeError):
                    pass
            self._sim_buy_dates[account_id] = buy_dates

            logger.info(f"已恢复模拟账户数据: {instance_id}, balance={data['balance']}, positions={len(saved_positions)}")
        except Exception as e:
            logger.error(f"恢复模拟账户数据失败: {e}")
        finally:
            db.close()

    # ── 日志和推送 ────────────────────────────────────────────────────────

    async def _log_and_push(self, instance_id: str, side: str, message: str,
                            price: float, quantity: int, pnl: float = 0) -> None:
        time_str = datetime.now().strftime("%H:%M:%S")
        log_entry = {
            "time": time_str, "side": side, "message": message,
            "price": price, "quantity": quantity, "pnl": pnl,
        }
        self._logs.setdefault(instance_id, []).append(log_entry)

        # 持久化到数据库
        self._persist_log(instance_id, side, message, price, quantity, pnl)

        await ws_manager.broadcast({
            "type": "strategy_log",
            "data": {
                "instance_id": instance_id, "message": message,
                "time": time_str, "side": side,
                "price": price, "quantity": quantity, "pnl": pnl,
            }
        })

        if side in ("buy", "sell"):
            await ws_manager.broadcast({
                "type": "strategy_trade",
                "data": {
                    "instance_id": instance_id, "side": side,
                    "price": price, "quantity": quantity,
                    "pnl": pnl, "time": time_str,
                }
            })

    def _persist_log(self, instance_id: str, side: str, message: str,
                     price: float, quantity: int, pnl: float) -> None:
        """将日志写入数据库"""
        from app.database import SessionLocal
        from app.models.models import StrategyLog

        db = SessionLocal()
        try:
            log = StrategyLog(
                instance_id=instance_id,
                side=side,
                message=message,
                price=price,
                quantity=quantity,
                pnl=pnl,
            )
            db.add(log)
            db.commit()
        except Exception as e:
            logger.warning(f"持久化日志失败: {e}")
        finally:
            db.close()

    def _load_logs_from_db(self, instance_id: str) -> None:
        """从数据库加载历史日志"""
        from app.database import SessionLocal
        from app.models.models import StrategyLog

        db = SessionLocal()
        try:
            # 加载最近500条日志
            records = db.query(StrategyLog).filter(
                StrategyLog.instance_id == instance_id,
            ).order_by(StrategyLog.created_at.desc()).limit(500).all()

            # 按时间正序排列
            records = list(reversed(records))

            logs = []
            for r in records:
                logs.append({
                    "time": r.created_at.strftime("%H:%M:%S") if r.created_at else "",
                    "side": r.side,
                    "message": r.message,
                    "price": float(r.price),
                    "quantity": r.quantity,
                    "pnl": float(r.pnl),
                })

            self._logs[instance_id] = logs
            logger.info(f"已从数据库加载 {len(logs)} 条历史日志: {instance_id}")
        except Exception as e:
            logger.warning(f"加载历史日志失败: {e}")
        finally:
            db.close()

    async def _push_account_update(self, instance_id: str) -> None:
        stats = await self.get_account_stats(instance_id)
        if not stats:
            return

        config = self._instances.get(instance_id)
        symbol = config.get("symbol", "") if config else ""
        current_price = self._get_current_price(symbol)
        tick = self._current_ticks.get(symbol)
        pre_close = tick.get("pre_close", 0) if tick else 0

        # 如果 pre_close 为 0，尝试从 HTTP API 补获
        if pre_close <= 0 and market_service.is_available():
            xt_symbol = data_bridge.to_xt_symbol(symbol)
            tick_data = market_service.get_full_tick(xt_symbol)
            if tick_data:
                pre_close = float(tick_data.get("lastClose", 0))
                if pre_close > 0 and symbol not in self._current_ticks:
                    self._current_ticks[symbol] = {"symbol": symbol, "pre_close": pre_close}

        await ws_manager.broadcast({
            "type": "strategy_account",
            "data": {
                "instance_id": instance_id,
                "balance": stats["balance"],
                "available": stats["available"],
                "market_value": stats["market_value"],
                "total_assets": stats["total_assets"],
                "profit": stats["profit"],
                "profit_rate": stats["profit_rate"],
                "daily_profit": sum(p.get("daily_profit", 0) for p in stats["positions"]),
                "positions": stats["positions"],
                "current_price": current_price,
                "pre_close": pre_close,
                "change_rate": (current_price - pre_close) / pre_close if pre_close > 0 else 0,
            }
        })

    # ── 查询接口 ──────────────────────────────────────────────────────────

    async def get_account_stats(self, instance_id: str) -> Optional[dict]:
        config = self._instances.get(instance_id)
        if not config:
            return None

        mode = config.get("mode", "simulation")
        account_id = self._get_account_id(instance_id)

        # 模拟模式：先刷新持仓实时价格
        if mode == "simulation":
            symbol = config["symbol"]
            current_price = self._get_current_price(symbol)
            if current_price > 0:
                positions = self._sim_positions.get(account_id, {})
                for sym, pos in positions.items():
                    if pos["quantity"] > 0:
                        pos["current_price"] = current_price
                        pos["market_value"] = pos["quantity"] * current_price

        if mode == "live":
            return await self._get_live_account_stats(account_id)
        else:
            return self._get_sim_account_stats(account_id)

    def _get_sim_account_stats(self, account_id: str) -> Optional[dict]:
        account = self._sim_accounts.get(account_id)
        if not account:
            return None

        positions = []
        positions_map = self._sim_positions.get(account_id, {})
        for symbol, pos in positions_map.items():
            if pos["quantity"] > 0:
                market_value = pos["quantity"] * pos.get("current_price", pos["avg_cost"])
                profit = market_value - pos["avg_cost"] * pos["quantity"]
                profit_rate = (profit / (pos["avg_cost"] * pos["quantity"])) if pos["avg_cost"] > 0 and pos["quantity"] > 0 else 0

                # 今日盈亏 = (current_price - pre_close) * quantity
                current_price = pos.get("current_price", pos["avg_cost"])
                tick = self._current_ticks.get(symbol)
                pre_close = tick.get("pre_close", 0) if tick else 0
                daily_profit = round((current_price - pre_close) * pos["quantity"], 2) if pre_close > 0 else 0

                positions.append({
                    "symbol": symbol,
                    "name": "",
                    "quantity": pos["quantity"],
                    "avg_cost": pos["avg_cost"],
                    "current_price": current_price,
                    "market_value": market_value,
                    "profit": profit,
                    "profit_rate": profit_rate,
                    "daily_profit": daily_profit,
                })

        market_value = sum(p["market_value"] for p in positions)
        total_assets = account["balance"] + market_value
        initial = account.get("initial_capital", account["balance"])
        profit = total_assets - initial
        profit_rate = profit / initial if initial > 0 else 0

        return {
            "balance": account["balance"],
            "available": account["available"],
            "market_value": market_value,
            "total_assets": total_assets,
            "profit": profit,
            "profit_rate": profit_rate,
            "positions": positions,
            "orders_count": 0,
        }

    async def _get_live_account_stats(self, account_id: str) -> Optional[dict]:
        """实盘账户统计 — 通过 live_gateway（stock_trade API）获取"""
        try:
            account_data = await live_gateway.get_account()
            positions_data = await live_gateway.get_positions()
        except Exception as e:
            logger.warning(f"获取实盘账户数据失败: {e}")
            return None

        if not account_data:
            return None

        # 从实例配置获取初始权益
        initial_equity = 0
        for inst_id, cfg in self._instances.items():
            if cfg.get("mode") == "live" and cfg.get("account_id") == account_id:
                initial_equity = cfg.get("initial_equity", 0)
                break

        total_assets = float(account_data.get("total_assets", 0))
        profit = total_assets - initial_equity if initial_equity > 0 else 0
        profit_rate = profit / initial_equity if initial_equity > 0 else 0

        positions = []
        for pos in positions_data:
            positions.append({
                "symbol": pos.get("symbol", ""),
                "name": pos.get("name", ""),
                "quantity": pos.get("volume", pos.get("quantity", 0)),
                "avg_cost": pos.get("cost_price", pos.get("avg_cost", 0)),
                "current_price": pos.get("current_price", 0),
                "market_value": pos.get("market_value", 0),
                "profit": pos.get("pnl", pos.get("profit", 0)),
                "profit_rate": pos.get("pnl_pct", pos.get("profit_rate", 0)) / 100 if pos.get("pnl_pct") else pos.get("profit_rate", 0),
            })

        return {
            "balance": float(account_data.get("cash", account_data.get("balance", 0))),
            "available": float(account_data.get("available_cash", account_data.get("available", 0))),
            "market_value": float(account_data.get("market_value", 0)),
            "total_assets": total_assets,
            "profit": profit,
            "profit_rate": profit_rate,
            "positions": positions,
            "orders_count": 0,
        }

    def get_realtime_data(self, instance_id: str) -> Optional[dict]:
        config = self._instances.get(instance_id)
        if not config:
            return None

        symbol = config["symbol"]
        current_price = self._get_current_price(symbol)
        tick = self._current_ticks.get(symbol)
        pre_close = tick.get("pre_close", 0) if tick else 0

        # 如果 pre_close 为 0，尝试从 HTTP API 补获
        if pre_close <= 0 and market_service.is_available():
            xt_symbol = data_bridge.to_xt_symbol(symbol)
            tick_data = market_service.get_full_tick(xt_symbol)
            if tick_data:
                pre_close = float(tick_data.get("lastClose", 0))
                if pre_close > 0:
                    if symbol not in self._current_ticks:
                        self._current_ticks[symbol] = {"symbol": symbol, "pre_close": pre_close}
                    else:
                        self._current_ticks[symbol]["pre_close"] = pre_close

        return {
            "symbol": symbol,
            "current_price": current_price,
            "pre_close": pre_close,
            "change": current_price - pre_close,
            "change_rate": (current_price - pre_close) / pre_close if pre_close > 0 else 0,
            "tick": tick,
        }

    def get_logs(self, instance_id: str) -> list:
        return self._logs.get(instance_id, [])

    def shutdown(self) -> None:
        """关闭引擎"""
        from app.core.engine import engine_manager

        # 只关闭自己独立创建的引擎，不关闭 engine_manager 的共享引擎
        if self._main_engine and self._main_engine is not engine_manager._main_engine:
            self._main_engine.close()
            if self._event_engine:
                self._event_engine.stop()
        self._main_engine = None
        self._event_engine = None
        logger.info("vnpy 策略运行器已关闭")


# 全局单例
vnpy_strategy_runner = VnpyStrategyRunner()

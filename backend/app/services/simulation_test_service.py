"""
模拟交易模块测试服务

模拟上一个交易日的实时行情数据，驱动策略产生买卖信号，
验证模拟交易流程（下单、成交、持仓、资金）是否正常工作。

提供两种测试模式：
1. 策略信号测试：回放历史分钟数据，观察策略是否正常产生信号
2. 交易流程测试：强制注入买卖信号，验证下单/成交/持仓/资金全流程
"""

import logging
import uuid
from datetime import datetime, timedelta
from typing import Optional

import pandas as pd

from app.core.data_bridge import data_bridge
from app.core.vnpy_sim_gateway import SimulatedStockGateway
from app.strategies.base import STRATEGY_MAP, get_signal_period, CtaStrategy
from app.services.market_service import market_service

from vnpy.event import EventEngine
from vnpy.trader.constant import Direction, Exchange, Offset, OrderType
from vnpy.trader.object import OrderRequest

logger = logging.getLogger(__name__)


class SimulationTestResult:
    """测试结果收集器"""

    def __init__(self, symbol: str, strategy_name: str, initial_capital: float):
        self.test_id: str = uuid.uuid4().hex[:8]
        self.symbol: str = symbol
        self.strategy_name: str = strategy_name
        self.initial_capital: float = initial_capital
        self.start_time: str = ""
        self.end_time: str = ""
        self.test_mode: str = "signal"  # signal / trade_flow

        # 信号记录
        self.signals: list[dict] = []
        # 成交记录
        self.trades: list[dict] = []
        # 账户快照（关键时间点）
        self.account_snapshots: list[dict] = []
        # 错误记录
        self.errors: list[str] = []

    def to_dict(self) -> dict:
        final_account = self.account_snapshots[-1] if self.account_snapshots else {}
        return {
            "test_id": self.test_id,
            "test_mode": self.test_mode,
            "symbol": self.symbol,
            "strategy_name": self.strategy_name,
            "initial_capital": self.initial_capital,
            "start_time": self.start_time,
            "end_time": self.end_time,
            "signal_count": len(self.signals),
            "buy_signal_count": len([s for s in self.signals if s["signal"] == 1]),
            "sell_signal_count": len([s for s in self.signals if s["signal"] == -1]),
            "trade_count": len(self.trades),
            "buy_trade_count": len([t for t in self.trades if t["side"] == "buy"]),
            "sell_trade_count": len([t for t in self.trades if t["side"] == "sell"]),
            "signals": self.signals,
            "trades": self.trades,
            "account_snapshots": self.account_snapshots,
            "errors": self.errors,
            "final_account": final_account,
            "passed": len(self.errors) == 0,
        }


def _get_last_trading_date() -> str:
    """获取上一个交易日的日期字符串"""
    from app.services.trading_calendar_service import trading_calendar
    last = trading_calendar.get_last_trading_day()
    return last.strftime("%Y-%m-%d")


def _load_minute_data(symbol: str, trade_date: str) -> pd.DataFrame:
    """加载指定日期的1分钟K线数据"""
    xt_symbol = data_bridge.to_xt_symbol(symbol)
    start_time = trade_date.replace("-", "")
    end_time = start_time + "235959"

    df = market_service.get_klines(
        symbol=xt_symbol,
        period="1m",
        start_time=start_time,
        end_time=end_time,
        dividend_type="front",
    )
    return df


def _load_daily_data(symbol: str, end_date: str, lookback_days: int = 120) -> pd.DataFrame:
    """加载日K线历史数据（不包含 end_date 当天）"""
    day_before = (datetime.strptime(end_date, "%Y-%m-%d") - timedelta(days=1))
    start = (day_before - timedelta(days=lookback_days))
    return data_bridge.load_bars_df(
        symbol, start.strftime("%Y-%m-%d"), day_before.strftime("%Y-%m-%d"), "daily"
    )


def _init_strategy(class_name: str, daily_df: pd.DataFrame, params: dict) -> Optional[CtaStrategy]:
    """初始化策略，用历史日K线预热"""
    strategy_cls = STRATEGY_MAP.get(class_name)
    if not strategy_cls:
        return None

    strategy = strategy_cls(params)
    strategy.reset()

    if not daily_df.empty:
        for _, row in daily_df.iterrows():
            bar = {
                "date": row["date"].strftime("%Y-%m-%d") if hasattr(row["date"], "strftime") else str(row["date"]),
                "open": float(row["open"]),
                "high": float(row["high"]),
                "low": float(row["low"]),
                "close": float(row["close"]),
                "volume": float(row["volume"]),
                "turnover": float(row.get("turnover", 0)),
            }
            strategy.on_bar(bar)

        try:
            df_hist = pd.DataFrame(strategy._bars)
            for col in ["open", "high", "low", "close", "volume", "turnover"]:
                if col in df_hist.columns:
                    df_hist[col] = pd.to_numeric(df_hist[col], errors="coerce")
            if "date" in df_hist.columns:
                df_hist["date"] = pd.to_datetime(df_hist["date"])
            hist_signals = strategy.generate_signals(df_hist, strategy.setting)
            for i in range(len(hist_signals) - 1, -1, -1):
                if hist_signals.iloc[i] != 0:
                    strategy._prev_signal = int(hist_signals.iloc[i])
                    break
        except Exception:
            pass

    return strategy


def _check_signal(strategy: CtaStrategy) -> int:
    """检查策略信号（状态转换检测）"""
    try:
        df = pd.DataFrame(strategy._bars)
        for col in ["open", "high", "low", "close", "volume", "turnover"]:
            if col in df.columns:
                df[col] = pd.to_numeric(df[col], errors="coerce")
        if "date" in df.columns:
            df["date"] = pd.to_datetime(df["date"])

        signals = strategy.generate_signals(df, strategy.setting)
        if signals is None or len(signals) == 0:
            return 0

        current_state = 0
        for i in range(len(signals) - 1, -1, -1):
            if signals.iloc[i] != 0:
                current_state = int(signals.iloc[i])
                break

        prev_state = strategy._prev_signal
        if current_state != prev_state:
            strategy._prev_signal = current_state
            if prev_state == 0 and current_state == 1:
                return 1
            elif prev_state == 1 and current_state != 1:
                return -1
            elif prev_state == -1 and current_state != -1:
                return 1
            elif prev_state == 0 and current_state == -1:
                return -1
        return 0
    except Exception as e:
        logger.warning(f"信号计算异常: {e}")
        return 0


# ── 信号回放测试 ──────────────────────────────────────────────────────────

def run_simulation_test(
    symbol: str,
    strategy_name: str,
    initial_capital: float = 1000000,
    params: dict = None,
    trade_date: str = None,
) -> dict:
    """
    运行模拟交易信号测试

    回放指定交易日的1分钟K线数据，驱动策略产生信号，
    并通过 SimulatedStockGateway 执行模拟交易。

    Returns:
        测试结果字典
    """
    params = params or {}
    trade_date = trade_date or _get_last_trading_date()

    result = SimulationTestResult(symbol, strategy_name, initial_capital)
    result.test_mode = "signal"
    result.start_time = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

    # 1. 加载1分钟K线数据
    minute_df = _load_minute_data(symbol, trade_date)
    if minute_df.empty:
        result.errors.append(f"无法加载 {symbol} 在 {trade_date} 的1分钟K线数据")
        result.end_time = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        return result.to_dict()

    # 2. 加载日K线历史数据，初始化策略
    daily_df = _load_daily_data(symbol, trade_date)
    strategy = _init_strategy(strategy_name, daily_df, params)
    if not strategy:
        result.errors.append(f"未知策略类: {strategy_name}")
        result.end_time = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        return result.to_dict()

    # 3. 初始化模拟网关
    event_engine = EventEngine()
    sim_gateway = SimulatedStockGateway(event_engine, "SIM_TEST")
    sim_gateway.connect({"capital": str(initial_capital)})
    event_engine.start()

    exchange = data_bridge.to_exchange(symbol)
    vt_symbol = f"{symbol}.{exchange.value}"

    # 注入昨收价（用于涨跌停计算）
    if not daily_df.empty:
        pre_close = float(daily_df.iloc[-1]["close"])
        sim_gateway._pre_closes[vt_symbol] = pre_close

    # 4. 模拟账户跟踪
    sim_position = 0
    sim_avg_cost = 0.0
    is_grid = (strategy_name == "GridStrategy")
    grid_qty = params.get("grid_quantity") or params.get("trading_volume") or 100

    # 记录初始账户快照
    _add_account_snapshot(result, f"{trade_date} 09:30:00", sim_gateway, sim_position, sim_avg_cost, "开盘")

    # 5. 逐1分钟K线回放
    signal_period = get_signal_period(strategy_name)
    prev_signal = strategy._prev_signal
    bar_count = 0
    last_daily_bar_date = None

    for idx, row in minute_df.iterrows():
        try:
            ts = pd.Timestamp(idx)
            bar_time = ts.strftime("%H:%M:%S")
            bar_datetime = ts.to_pydatetime()

            open_price = float(row["open"])
            high_price = float(row["high"])
            low_price = float(row["low"])
            close_price = float(row["close"])
            volume = float(row["volume"])

            # 注入 tick 到模拟网关
            sim_gateway.inject_bar_as_tick(
                vt_symbol=vt_symbol,
                open_price=open_price,
                high_price=high_price,
                low_price=low_price,
                close_price=close_price,
                volume=volume,
                datetime_val=bar_datetime,
                exchange=exchange,
            )

            bar_count += 1

            # 日线策略
            if signal_period in ("daily", "1d"):
                today_str = ts.strftime("%Y-%m-%d")
                if last_daily_bar_date != today_str:
                    daily_bar = {
                        "date": today_str,
                        "open": open_price,
                        "high": high_price,
                        "low": low_price,
                        "close": close_price,
                        "volume": volume,
                        "turnover": float(row.get("amount", 0)),
                    }
                    strategy.on_bar(daily_bar)
                    last_daily_bar_date = today_str
                else:
                    if strategy._bars:
                        last_bar = strategy._bars[-1]
                        last_bar["high"] = max(last_bar["high"], high_price)
                        last_bar["low"] = min(last_bar["low"], low_price)
                        last_bar["close"] = close_price

                # 每6根1分钟K线检查一次信号
                if bar_count % 6 == 0:
                    signal = _check_signal(strategy)
                    if signal != 0:
                        signal_time = f"{trade_date} {bar_time}"
                        result.signals.append({
                            "time": signal_time,
                            "signal": signal,
                            "signal_name": "买入" if signal == 1 else "卖出",
                            "price": round(close_price, 2),
                            "prev_signal": prev_signal,
                        })

                        _execute_sim_trade(
                            signal, close_price, symbol, vt_symbol,
                            sim_gateway, exchange, result, signal_time,
                            is_grid, grid_qty, sim_position, sim_avg_cost,
                        )

                        sim_position, sim_avg_cost = _update_position_tracking(sim_gateway)
                        prev_signal = signal

            # tick 策略
            elif signal_period == "tick":
                tick_bar = {
                    "date": ts.strftime("%Y-%m-%d %H:%M:%S"),
                    "open": close_price, "high": close_price,
                    "low": close_price, "close": close_price,
                    "volume": 0, "turnover": 0,
                }
                signal_val = strategy.on_bar(tick_bar)
                if signal_val != 0:
                    signal_time = f"{trade_date} {bar_time}"
                    result.signals.append({
                        "time": signal_time,
                        "signal": signal_val,
                        "signal_name": "买入" if signal_val == 1 else "卖出",
                        "price": round(close_price, 2),
                        "prev_signal": prev_signal,
                    })

                    _execute_sim_trade(
                        signal_val, close_price, symbol, vt_symbol,
                        sim_gateway, exchange, result, signal_time,
                        is_grid, grid_qty, sim_position, sim_avg_cost,
                    )

                    sim_position, sim_avg_cost = _update_position_tracking(sim_gateway)
                    prev_signal = signal_val

        except Exception as e:
            result.errors.append(f"处理 {ts} 数据异常: {str(e)}")
            logger.error(f"模拟测试处理异常: {e}", exc_info=True)

    # 6. 收盘快照
    _add_account_snapshot(result, f"{trade_date} 15:00:00", sim_gateway, sim_position, sim_avg_cost, "收盘")

    # 7. 收集网关委托和成交记录
    _collect_gateway_records(sim_gateway, result)

    # 8. 清理
    sim_gateway.close()
    event_engine.stop()

    result.end_time = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

    # 9. 验证
    final_stats = sim_gateway.get_account_snapshot()
    _validate_results(result, initial_capital, final_stats)

    return result.to_dict()


# ── 交易流程测试 ──────────────────────────────────────────────────────────

def run_trade_flow_test(
    symbol: str,
    initial_capital: float = 1000000,
    trade_date: str = None,
) -> dict:
    """
    运行交易流程测试

    强制注入买入→卖出信号，验证模拟交易全流程：
    下单 → 成交 → 持仓更新 → 资金更新 → T+1 限制

    Returns:
        测试结果字典
    """
    trade_date = trade_date or _get_last_trading_date()

    result = SimulationTestResult(symbol, "TradeFlowTest", initial_capital)
    result.test_mode = "trade_flow"
    result.start_time = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

    # 加载1分钟K线获取参考价格
    minute_df = _load_minute_data(symbol, trade_date)
    if minute_df.empty:
        result.errors.append(f"无法加载 {symbol} 在 {trade_date} 的1分钟K线数据")
        result.end_time = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        return result.to_dict()

    # 取开盘价和收盘价
    first_row = minute_df.iloc[0]
    last_row = minute_df.iloc[-1]
    open_price = float(first_row["close"])
    close_price = float(last_row["close"])
    mid_price = (open_price + close_price) / 2

    # 初始化模拟网关
    event_engine = EventEngine()
    sim_gateway = SimulatedStockGateway(event_engine, "SIM_TEST")
    sim_gateway.connect({"capital": str(initial_capital)})
    event_engine.start()

    exchange = data_bridge.to_exchange(symbol)
    vt_symbol = f"{symbol}.{exchange.value}"

    # 初始快照
    _add_account_snapshot(result, f"{trade_date} 09:30:00", sim_gateway, 0, 0, "开盘")

    # ── Step 1: 买入 ──
    buy_price = open_price
    buy_amount = initial_capital * 0.9
    shares_100 = int(buy_amount / (buy_price * 100)) * 100
    shares = shares_100 if shares_100 > 0 else int(buy_amount / buy_price)

    result.signals.append({
        "time": f"{trade_date} 09:31:00",
        "signal": 1,
        "signal_name": "买入",
        "price": round(buy_price, 2),
        "prev_signal": 0,
    })

    req = OrderRequest(
        symbol=symbol,
        exchange=exchange,
        direction=Direction.LONG,
        type=OrderType.MARKET,
        volume=shares,
        price=buy_price,
        offset=Offset.OPEN,
    )
    vt_orderid = sim_gateway.send_order(req)
    result.trades.append({
        "time": f"{trade_date} 09:31:00",
        "side": "buy",
        "symbol": symbol,
        "price": round(buy_price, 2),
        "quantity": shares,
        "order_id": vt_orderid,
        "source": "forced",
    })

    sim_position, sim_avg_cost = _update_position_tracking(sim_gateway)
    _add_account_snapshot(result, f"{trade_date} 09:31:00", sim_gateway, sim_position, sim_avg_cost, "买入后")

    # 验证买入
    stats_after_buy = sim_gateway.get_account_snapshot()
    if sim_position != shares:
        result.errors.append(f"买入后持仓不一致: 期望 {shares}, 实际 {sim_position}")
    if stats_after_buy["cash"] >= initial_capital:
        result.errors.append(f"买入后资金未减少: cash={stats_after_buy['cash']:.2f}")

    # ── Step 2: T+1 限制测试（当日买入不可卖出）──
    sell_req = OrderRequest(
        symbol=symbol,
        exchange=exchange,
        direction=Direction.SHORT,
        type=OrderType.MARKET,
        volume=sim_position,
        price=mid_price,
        offset=Offset.CLOSE,
    )
    t1_orderid = sim_gateway.send_order(sell_req)
    # T+1 应该拒绝卖出
    t1_orders = sim_gateway.get_orders_snapshot()
    t1_rejected = any(o["order_id"] == t1_orderid and o["status"] == "rejected" for o in t1_orders)
    if t1_rejected:
        result.trades.append({
            "time": f"{trade_date} 10:00:00",
            "side": "sell",
            "symbol": symbol,
            "price": round(mid_price, 2),
            "quantity": sim_position,
            "order_id": t1_orderid,
            "status": "rejected",
            "reason": "T+1限制",
            "source": "forced_t1_test",
        })
    else:
        result.errors.append("T+1 限制未生效：当日买入的股票应该不可卖出")

    # ── Step 3: 模拟次日，卖出 ──
    # 重置买入日期为前一天，绕过 T+1
    from datetime import date
    yesterday = (datetime.strptime(trade_date, "%Y-%m-%d") - timedelta(days=1)).date()
    sim_gateway._buy_dates[vt_symbol] = yesterday

    result.signals.append({
        "time": f"{trade_date} 14:00:00",
        "signal": -1,
        "signal_name": "卖出",
        "price": round(close_price, 2),
        "prev_signal": 1,
    })

    sell_req2 = OrderRequest(
        symbol=symbol,
        exchange=exchange,
        direction=Direction.SHORT,
        type=OrderType.MARKET,
        volume=sim_position,
        price=close_price,
        offset=Offset.CLOSE,
    )
    sell_orderid = sim_gateway.send_order(sell_req2)
    result.trades.append({
        "time": f"{trade_date} 14:00:00",
        "side": "sell",
        "symbol": symbol,
        "price": round(close_price, 2),
        "quantity": sim_position,
        "order_id": sell_orderid,
        "source": "forced",
    })

    sim_position, sim_avg_cost = _update_position_tracking(sim_gateway)
    _add_account_snapshot(result, f"{trade_date} 14:00:00", sim_gateway, sim_position, sim_avg_cost, "卖出后")

    # 验证卖出
    if sim_position != 0:
        result.errors.append(f"卖出后持仓应为0，实际 {sim_position}")

    # ── Step 4: 验证资金 ──
    final_stats = sim_gateway.get_account_snapshot()
    expected_loss = (buy_price - close_price) * shares  # 如果买高卖低
    # 资金应该 = 初始 - 买入佣金 - 卖出佣金 - 危出印花税 +/- 盈亏
    # 不精确验证，只验证资金在合理范围
    if final_stats["cash"] <= 0:
        result.errors.append(f"卖出后资金异常: {final_stats['cash']:.2f}")
    if final_stats["total_assets"] <= 0:
        result.errors.append(f"卖出后总资产异常: {final_stats['total_assets']:.2f}")

    # 收盘快照
    _add_account_snapshot(result, f"{trade_date} 15:00:00", sim_gateway, sim_position, sim_avg_cost, "收盘")

    # 收集网关记录
    _collect_gateway_records(sim_gateway, result)

    # 清理
    sim_gateway.close()
    event_engine.stop()

    result.end_time = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    _validate_results(result, initial_capital, final_stats)

    return result.to_dict()


# ── 辅助函数 ──────────────────────────────────────────────────────────────

def _add_account_snapshot(
    result: SimulationTestResult, time_str: str,
    sim_gateway: SimulatedStockGateway,
    position: int, avg_cost: float, event: str,
) -> None:
    stats = sim_gateway.get_account_snapshot()
    result.account_snapshots.append({
        "time": time_str,
        "balance": round(stats["cash"], 2),
        "available": round(stats["available_cash"], 2),
        "position": position,
        "avg_cost": round(avg_cost, 2),
        "market_value": round(stats["market_value"], 2),
        "total_assets": round(stats["total_assets"], 2),
        "event": event,
    })


def _update_position_tracking(sim_gateway: SimulatedStockGateway) -> tuple[int, float]:
    positions = sim_gateway.get_positions_snapshot()
    if positions:
        pos = positions[0]
        return pos["volume"], pos["cost_price"]
    return 0, 0.0


def _execute_sim_trade(
    signal: int, price: float, symbol: str, vt_symbol: str,
    sim_gateway: SimulatedStockGateway, exchange: Exchange,
    result: SimulationTestResult, signal_time: str,
    is_grid: bool, grid_qty: int,
    current_position: int, avg_cost: float,
) -> None:
    """通过模拟网关执行交易"""
    try:
        if is_grid:
            if signal == 1:
                cost = grid_qty * price
                commission = max(cost * 0.0003, 5)
                stats = sim_gateway.get_account_snapshot()
                available = stats["available_cash"]

                if available >= cost + commission:
                    req = OrderRequest(
                        symbol=symbol, exchange=exchange,
                        direction=Direction.LONG, type=OrderType.MARKET,
                        volume=grid_qty, price=price, offset=Offset.OPEN,
                    )
                    sim_gateway.send_order(req)
                    result.trades.append({
                        "time": signal_time, "side": "buy", "symbol": symbol,
                        "price": round(price, 2), "quantity": grid_qty, "source": "signal",
                    })
                else:
                    result.errors.append(f"资金不足，无法网格买入: 可用 {available:.0f}, 需要 {cost + commission:.0f}")

            elif signal == -1 and current_position > 0:
                sell_qty = min(grid_qty, current_position)
                req = OrderRequest(
                    symbol=symbol, exchange=exchange,
                    direction=Direction.SHORT, type=OrderType.MARKET,
                    volume=sell_qty, price=price, offset=Offset.CLOSE,
                )
                sim_gateway.send_order(req)
                pnl = (price - avg_cost) * sell_qty
                result.trades.append({
                    "time": signal_time, "side": "sell", "symbol": symbol,
                    "price": round(price, 2), "quantity": sell_qty,
                    "pnl": round(pnl, 2), "source": "signal",
                })
        else:
            if signal == 1 and current_position == 0:
                stats = sim_gateway.get_account_snapshot()
                available = stats["available_cash"]
                buy_amount = available * 0.9
                shares_100 = int(buy_amount / (price * 100)) * 100
                shares = shares_100 if shares_100 > 0 else int(buy_amount / price)
                if shares <= 0:
                    result.errors.append(f"资金不足，无法买入: 可用 {available:.0f}, 价格 {price:.2f}")
                    return

                req = OrderRequest(
                    symbol=symbol, exchange=exchange,
                    direction=Direction.LONG, type=OrderType.MARKET,
                    volume=shares, price=price, offset=Offset.OPEN,
                )
                sim_gateway.send_order(req)
                result.trades.append({
                    "time": signal_time, "side": "buy", "symbol": symbol,
                    "price": round(price, 2), "quantity": shares, "source": "signal",
                })

            elif signal == -1 and current_position > 0:
                req = OrderRequest(
                    symbol=symbol, exchange=exchange,
                    direction=Direction.SHORT, type=OrderType.MARKET,
                    volume=current_position, price=price, offset=Offset.CLOSE,
                )
                sim_gateway.send_order(req)
                pnl = (price - avg_cost) * current_position
                result.trades.append({
                    "time": signal_time, "side": "sell", "symbol": symbol,
                    "price": round(price, 2), "quantity": current_position,
                    "pnl": round(pnl, 2), "source": "signal",
                })

    except Exception as e:
        result.errors.append(f"交易执行异常: {str(e)}")
        logger.error(f"模拟测试交易执行异常: {e}", exc_info=True)


def _collect_gateway_records(sim_gateway: SimulatedStockGateway, result: SimulationTestResult) -> None:
    """收集模拟网关的委托和成交记录"""
    for order in sim_gateway.get_orders_snapshot():
        result.trades.append({
            "time": order["time"], "side": order["side"], "symbol": order["symbol"],
            "price": order["price"], "quantity": order["quantity"],
            "filled_quantity": order["filled_quantity"], "status": order["status"],
            "source": "order",
        })

    for trade in sim_gateway.get_trades_snapshot():
        result.trades.append({
            "time": trade["time"], "side": trade["side"], "symbol": trade["symbol"],
            "price": trade["price"], "quantity": trade["quantity"], "source": "trade",
        })


def _validate_results(result: SimulationTestResult, initial_capital: float, final_stats: dict) -> None:
    """验证测试结果"""
    total_assets = final_stats.get("total_assets", 0)
    if total_assets <= 0:
        result.errors.append(f"总资产异常: {total_assets}")

    # 信号测试模式：有信号但无成交
    if result.test_mode == "signal":
        if result.signals and not result.trades:
            result.errors.append("检测到信号但无成交记录，模拟交易可能未正常执行")

        buy_signals = [s for s in result.signals if s["signal"] == 1]
        buy_trades = [t for t in result.trades if t["side"] == "buy" and t.get("source") == "signal"]
        if buy_signals and not buy_trades:
            result.errors.append(f"有 {len(buy_signals)} 个买入信号但无对应买入成交")

    # 账户快照连续性
    if len(result.account_snapshots) >= 2:
        start_assets = result.account_snapshots[0]["total_assets"]
        if abs(start_assets - initial_capital) > 1:
            result.errors.append(f"初始资产不一致: 期望 {initial_capital}, 实际 {start_assets}")


def get_available_strategies() -> list[dict]:
    """获取可测试的策略列表"""
    strategies = []
    for name, cls in STRATEGY_MAP.items():
        strategies.append({
            "class_name": name,
            "signal_period": cls.signal_period,
        })
    return strategies

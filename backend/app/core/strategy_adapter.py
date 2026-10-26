"""
vnpy CTA 策略适配器

将现有 CtaStrategy 子类（信号生成型：generate_signals → 1/-1/0）
适配为 vnpy 交易型策略，通过状态转换检测调用 buy/sell。
"""

import logging
import json
from abc import ABCMeta
from collections import defaultdict
from datetime import date
from typing import TYPE_CHECKING

import pandas as pd

try:
    from vnpy.trader.object import BarData, TradeData, OrderData
    from vnpy.trader.constant import Direction, Offset
    VNPY_AVAILABLE = True
except ImportError:
    VNPY_AVAILABLE = False
    BarData = None
    TradeData = None
    OrderData = None

    class _StubEnum:
        def __init__(self, *_, **__):
            pass
        def __getattr__(self, name):
            return name
    Direction = _StubEnum()
    Offset = _StubEnum()

from app.strategies.base import STRATEGY_MAP, CtaStrategy

logger = logging.getLogger(__name__)


class CtaSignalAdapter(metaclass=ABCMeta):
    """
    将 CtaStrategy 的信号输出适配为 vnpy 交易行为。

    策略通过 generate_signals() 产生信号序列（1=买入, -1=卖出, 0=持有），
    适配器通过状态转换检测将信号映射为实际的 buy/sell 操作。

    支持两种模式：
    - 普通策略：一次只持一个仓位，90%资金买入
    - 网格策略：支持多次加减仓
    """

    def __init__(
        self,
        strategy_engine,
        strategy_name: str,
        vt_symbols: list[str],
        setting: dict,
    ) -> None:
        self.strategy_engine = strategy_engine
        self.strategy_name = strategy_name
        self.vt_symbols = vt_symbols

        # 持仓数据
        self.pos_data: dict[str, float] = defaultdict(float)
        self.target_data: dict[str, float] = defaultdict(float)

        # 委托缓存
        self.orders: dict[str, OrderData] = {}
        self.active_orderids: set[str] = set()

        # 信号状态跟踪
        self._signal_state: int = 0  # 0=空仓, 1=多头, -1=空头
        self._bars_buffer: list[dict] = []
        self._buy_date: date | None = None  # T+1 跟踪

        # 预计算信号缓存（回测优化）
        self._precomputed_signals: list[int] | None = None
        self._bar_index: int = 0

        # 策略参数
        self._wrapped_cls: type[CtaStrategy] | None = None
        self._wrapped_setting: dict = {}
        self._grid_mode: bool = False
        self._grid_qty: int = 100

        # 网格状态持久化
        self._grid_states: dict[int, int] = {}  # level → EMPTY(0)/HOLDING(1)
        self._prev_price: float = 0  # 上一根K线收盘价

        # 设置参数
        for k, v in setting.items():
            if hasattr(self, k):
                setattr(self, k, v)

        self._wrapped_setting = setting

    def on_init(self) -> None:
        """策略初始化"""
        if self._wrapped_cls:
            logger.info(f"策略初始化: {self.strategy_name}, wrapped={self._wrapped_cls.class_name}")

    def precompute_signals(self, bars_data: list[dict]) -> None:
        """预计算所有信号（回测时调用一次，避免 O(n²) 重复计算）

        Args:
            bars_data: 所有K线数据列表
        """
        if not self._wrapped_cls or not bars_data:
            return

        df = pd.DataFrame(bars_data)
        for col in ["open", "high", "low", "close", "volume", "turnover"]:
            if col in df.columns:
                df[col] = pd.to_numeric(df[col], errors="coerce")
        if "date" in df.columns:
            df["date"] = pd.to_datetime(df["date"])

        signals = self._wrapped_cls.generate_signals(df, self._wrapped_setting)
        # GridStrategy 返回 (signals, grid_states) 元组
        if isinstance(signals, tuple):
            signals, grid_states = signals
            if self._grid_mode and grid_states:
                self._grid_states = grid_states
        if signals is not None and len(signals) > 0:
            # 信号值兼容性处理：
            # - NaN → 0（缺失数据填充）
            # - bool True → 1, False → 0
            # - float → int
            signals = signals.fillna(0).astype(int)
            self._precomputed_signals = [int(s) for s in signals]
        else:
            self._precomputed_signals = [0] * len(bars_data)

        self._bar_index = 0
        buy_count = sum(1 for s in self._precomputed_signals if s == 1)
        sell_count = sum(1 for s in self._precomputed_signals if s == -1)
        hold_count = sum(1 for s in self._precomputed_signals if s == 0)
        logger.info(
            f"策略信号预计算完成，共 {len(self._precomputed_signals)} 根K线 | "
            f"买入={buy_count} 卖出={sell_count} 持有={hold_count}"
        )

    def on_bars(self, bars: dict[str, BarData]) -> None:
        """收到 K 线 → 查找信号 → 状态转换 → 交易"""
        if not self._wrapped_cls or not bars:
            return

        # 取第一个 symbol 的 bar（单标的策略）
        vt_symbol = self.vt_symbols[0]
        bar = bars.get(vt_symbol)
        if not bar:
            return

        # 转换 BarData → dict 格式
        bar_dict = {
            "date": bar.datetime.strftime("%Y-%m-%d %H:%M") if hasattr(bar.datetime, 'hour') and bar.datetime.hour > 0 else bar.datetime.strftime("%Y-%m-%d"),
            "open": bar.open_price,
            "high": bar.high_price,
            "low": bar.low_price,
            "close": bar.close_price,
            "volume": bar.volume,
            "turnover": bar.turnover,
        }
        self._bars_buffer.append(bar_dict)

        # 跟踪上一根K线价格（用于持久化恢复）
        if self._prev_price == 0:
            self._prev_price = bar.close_price

        # 使用预计算信号（O(1)）或回退到实时计算
        if self._precomputed_signals is not None:
            idx = self._bar_index
            if idx < len(self._precomputed_signals):
                last_signal = self._precomputed_signals[idx]
                self._bar_index += 1
            else:
                last_signal = 0
        else:
            # 实盘模式：增量计算
            last_signal = self._compute_signal_realtime()

        # 信号含义：1=买入, -1=卖出, 0=持有（维持上一状态）
        # A股持仓状态：0=空仓, 1=持仓（不支持做空）
        # 注意：_signal_state 基于 pos_data（实际持仓）而非乐观估计，
        # 因为 vnpy 引擎的订单可能因价格跳空而无法成交
        vt_symbol_pos = self.vt_symbols[0]
        has_position = self.pos_data[vt_symbol_pos] > 0
        current_state = 1 if has_position else 0
        current_date = bar.datetime.date()

        # 信号日志：记录每根K线的信号值和持仓状态
        if last_signal != 0:
            signal_name = {1: "买入", -1: "卖出"}.get(last_signal, f"未知({last_signal})")
            self.write_log(
                f"信号触发: {signal_name} | 日期={current_date} "
                f"价格={bar.close_price:.2f} 持仓={'有' if has_position else '无'}"
            )

        if self._grid_mode:
            # 网格模式：信号是增量操作，直接执行
            # 信号值表示穿越的网格层数：1=买入1格, 3=买入3格, -2=卖出2格
            if last_signal > 0:
                for _ in range(last_signal):
                    self._handle_grid_signal(1, 0, bar, vt_symbol)
            elif last_signal < 0 and has_position:
                for _ in range(abs(last_signal)):
                    self._handle_grid_signal(-1, 1, bar, vt_symbol)
        else:
            # 普通模式：信号是目标状态，需要状态转换才执行
            # 信号1=应该持仓，信号-1=应该空仓
            if last_signal != 0 and last_signal != current_state:
                if last_signal == 1 and current_state == 0:
                    # 买入信号 + 空仓 → 买入开仓
                    self._signal_state = 1
                    self._handle_normal_signal(1, 0, bar, vt_symbol, current_date)
                elif last_signal == -1 and current_state == 1:
                    # 卖出信号 + 持仓 → 卖出平仓
                    self._signal_state = 0
                    self._handle_normal_signal(-1, 1, bar, vt_symbol, current_date)

    def _compute_signal_realtime(self) -> int:
        """实盘模式：增量计算当前K线信号"""
        buf_len = len(self._bars_buffer)
        if buf_len < 2:
            return 0

        df = pd.DataFrame(self._bars_buffer)
        for col in ["open", "high", "low", "close", "volume", "turnover"]:
            if col in df.columns:
                df[col] = pd.to_numeric(df[col], errors="coerce")
        if "date" in df.columns:
            df["date"] = pd.to_datetime(df["date"])

        result = self._wrapped_cls.generate_signals(df, self._wrapped_setting)
        # GridStrategy 返回 (signals, grid_states) 元组
        if isinstance(result, tuple):
            signals, grid_states = result
            if self._grid_mode and grid_states:
                self._grid_states = grid_states
        else:
            signals = result

        if signals is None or len(signals) == 0:
            return 0

        # 信号值兼容性处理：NaN→0, bool→int, float→int
        last_val = signals.iloc[-1]
        if pd.isna(last_val):
            return 0
        return int(last_val)

    def _is_limit_up(self, bar: BarData, vt_symbol: str) -> bool:
        """判断是否涨停（当前价 >= 昨收 * 1.1）"""
        pre_close = getattr(bar, 'pre_close', None)
        if pre_close and pre_close > 0:
            limit_up = round(pre_close * 1.1, 2)
            return bar.close_price >= limit_up
        return False

    def _is_limit_down(self, bar: BarData, vt_symbol: str) -> bool:
        """判断是否跌停（当前价 <= 昨收 * 0.9）"""
        pre_close = getattr(bar, 'pre_close', None)
        if pre_close and pre_close > 0:
            limit_down = round(pre_close * 0.9, 2)
            return bar.close_price <= limit_down
        return False

    def _handle_normal_signal(
        self, current_state: int, prev_state: int,
        bar: BarData, vt_symbol: str, current_date: date,
    ) -> None:
        """普通策略信号处理（一次只持一个仓位）

        信号含义：1=买入开仓, -1=卖出平仓
        持仓状态：0=空仓, 1=持仓（A股不支持做空）
        """
        if prev_state == 0 and current_state == 1:
            # 空仓→买入（涨停买不进）
            if self._is_limit_up(bar, vt_symbol):
                self.write_log(f"涨停买不进: {vt_symbol} close={bar.close_price:.2f}")
                return
            available = self.strategy_engine.get_cash_available()
            buy_amount = available * 0.9
            shares_100 = int(buy_amount / (bar.close_price * 100)) * 100
            shares = shares_100 if shares_100 > 0 else int(buy_amount / bar.close_price)
            if shares > 0:
                self.buy(vt_symbol, bar.close_price, shares)
                self._buy_date = current_date

        elif prev_state == 1 and current_state == -1:
            # 持仓→卖出（T+1 检查 + 跌停卖不出）
            pos = self.pos_data[vt_symbol]
            if pos > 0 and self._buy_date != current_date:
                if self._is_limit_down(bar, vt_symbol):
                    self.write_log(f"跌停卖不出: {vt_symbol} close={bar.close_price:.2f}")
                    return
                self.sell(vt_symbol, bar.close_price, pos)
                self._buy_date = None

    def _handle_grid_signal(
        self, current_state: int, prev_state: int,
        bar: BarData, vt_symbol: str,
    ) -> None:
        """网格策略信号处理（支持多次加减仓）"""
        grid_qty = self._grid_qty

        if current_state == 1:
            # 买入一个网格仓位
            cost = grid_qty * bar.close_price
            commission = max(cost * 0.0003, 5)
            available = self.strategy_engine.get_cash_available()
            if available >= cost + commission:
                self.buy(vt_symbol, bar.close_price, grid_qty)
                self._buy_date = bar.datetime.date()

        elif current_state == -1:
            pos = self.pos_data[vt_symbol]
            if pos > 0 and self._buy_date != bar.datetime.date():
                sell_qty = min(grid_qty, pos)
                self.sell(vt_symbol, bar.close_price, sell_qty)

    def on_trade(self, trade: TradeData) -> None:
        """成交回调 → 更新持仓跟踪"""
        if trade.direction == Direction.LONG:
            self.pos_data[trade.vt_symbol] += trade.volume
        else:
            self.pos_data[trade.vt_symbol] -= trade.volume

    # ── 状态持久化 ──────────────────────────────────────────────────────────

    def save_state(self) -> dict:
        """序列化当前状态为字典，用于持久化"""
        return {
            "strategy_name": self.strategy_name,
            "class_name": self._wrapped_cls.class_name if self._wrapped_cls else "",
            "vt_symbol": self.vt_symbols[0] if self.vt_symbols else "",
            "grid_states_json": json.dumps(
                {str(k): v for k, v in self._grid_states.items()},
                ensure_ascii=False,
            ),
            "signal_state": self._signal_state,
            "buy_date": self._buy_date.isoformat() if self._buy_date else None,
            "bar_index": self._bar_index,
            "prev_price": self._prev_price,
        }

    def load_state(self, data: dict) -> None:
        """从字典恢复状态"""
        if not data:
            return

        # 恢复网格层状态
        grid_states_json = data.get("grid_states_json", "{}")
        if grid_states_json:
            try:
                raw = json.loads(grid_states_json)
                self._grid_states = {int(k): v for k, v in raw.items()}
            except (json.JSONDecodeError, ValueError):
                self._grid_states = {}

        # 恢复信号状态
        self._signal_state = data.get("signal_state", 0)

        # 恢复 T+1 日期
        buy_date_str = data.get("buy_date")
        if buy_date_str:
            try:
                self._buy_date = date.fromisoformat(buy_date_str)
            except ValueError:
                self._buy_date = None

        # 恢复预计算索引
        self._bar_index = data.get("bar_index", 0)

        # 恢复上一根K线价格
        self._prev_price = data.get("prev_price", 0)

        logger.info(
            f"策略状态已恢复: {self.strategy_name}, "
            f"grid_states={len(self._grid_states)}层, "
            f"signal_state={self._signal_state}, "
            f"prev_price={self._prev_price}"
        )

    def update_trade(self, trade: TradeData) -> None:
        """vnpy 回测引擎调用"""
        self.on_trade(trade)

    def update_order(self, order: OrderData) -> None:
        """委托更新"""
        self.orders[order.vt_orderid] = order
        if not order.is_active() and order.vt_orderid in self.active_orderids:
            self.active_orderids.remove(order.vt_orderid)

    # ── 交易接口 ──────────────────────────────────────────────────────────

    def buy(self, vt_symbol: str, price: float, volume: float) -> list[str]:
        """买入开仓"""
        return self.send_order(vt_symbol, Direction.LONG, Offset.OPEN, price, volume)

    def sell(self, vt_symbol: str, price: float, volume: float) -> list[str]:
        """卖出平仓"""
        return self.send_order(vt_symbol, Direction.SHORT, Offset.CLOSE, price, volume)

    def send_order(
        self, vt_symbol: str, direction: Direction,
        offset: Offset, price: float, volume: float,
    ) -> list[str]:
        """发送委托"""
        vt_orderids = self.strategy_engine.send_order(
            self, vt_symbol, direction, offset, price, volume,
        )
        for vt_orderid in vt_orderids:
            self.active_orderids.add(vt_orderid)
        return vt_orderids

    def cancel_order(self, vt_orderid: str) -> None:
        """撤单"""
        self.strategy_engine.cancel_order(self, vt_orderid)

    def cancel_all(self) -> None:
        """撤销所有活跃委托"""
        for vt_orderid in list(self.active_orderids):
            self.cancel_order(vt_orderid)

    def get_pos(self, vt_symbol: str) -> float:
        return self.pos_data[vt_symbol]

    def get_cash_available(self) -> float:
        return self.strategy_engine.get_cash_available()

    def get_holding_value(self) -> float:
        holding_value = 0
        for vt_symbol, pos in self.pos_data.items():
            if pos > 0:
                bars = self.strategy_engine.bars
                bar = bars.get(vt_symbol)
                if bar:
                    holding_value += bar.close_price * pos
        return holding_value

    def get_portfolio_value(self) -> float:
        return self.get_cash_available() + self.get_holding_value()

    def write_log(self, msg: str) -> None:
        """输出日志"""
        self.strategy_engine.write_log(msg, self)


# ── 适配器工厂 ──────────────────────────────────────────────────────────────

def create_adapter(strategy_cls: type[CtaStrategy], grid_mode: bool = False) -> type:
    """将 CtaStrategy 子类包装为 CtaSignalAdapter 子类"""

    class AdaptedStrategy(CtaSignalAdapter):
        pass

    AdaptedStrategy.__name__ = f"Vnpy_{strategy_cls.class_name}"
    AdaptedStrategy.__qualname__ = f"Vnpy_{strategy_cls.class_name}"

    # 在 __init__ 中自动设置 wrapped_cls 和 grid_mode
    original_init = AdaptedStrategy.__init__

    def patched_init(self, strategy_engine, strategy_name, vt_symbols, setting):
        original_init(self, strategy_engine, strategy_name, vt_symbols, setting)
        self._wrapped_cls = strategy_cls
        self._grid_mode = grid_mode
        self._grid_qty = setting.get("grid_quantity") or setting.get("trading_volume") or 100

    AdaptedStrategy.__init__ = patched_init
    return AdaptedStrategy


# ── 策略注册表 ──────────────────────────────────────────────────────────────

VNPY_STRATEGY_MAP: dict[str, type] = {}

if VNPY_AVAILABLE:
    for cls_name, cls in STRATEGY_MAP.items():
        VNPY_STRATEGY_MAP[cls_name] = create_adapter(cls, grid_mode=(cls_name == "GridStrategy"))


# ── 动态编译与策略解析 ──────────────────────────────────────────────────────

def resolve_strategy_class(class_name: str) -> type[CtaStrategy] | None:
    """解析策略类，支持内置策略和用户自定义策略（动态编译）

    查找顺序：
    1. STRATEGY_MAP（内置策略）
    2. STRATEGY_MAP 缓存（已编译过的自定义策略）
    3. 从数据库加载 Strategy.code，exec() 动态编译

    编译成功后自动注册到 STRATEGY_MAP 和 VNPY_STRATEGY_MAP 缓存。

    Args:
        class_name: 策略类名，如 "DoubleMaStrategy" 或 "CustomStrategy_1719xxx"

    Returns:
        CtaStrategy 子类，找不到返回 None
    """
    # 1. 内置策略 / 已缓存的自定义策略
    strategy_cls = STRATEGY_MAP.get(class_name)
    if strategy_cls:
        return strategy_cls

    # 2. 从数据库加载自定义策略代码并动态编译
    try:
        from app.database import get_db
        from app.models import Strategy as StrategyModel

        db = next(get_db())
        try:
            s = db.query(StrategyModel).filter(StrategyModel.class_name == class_name).first()
        finally:
            db.close()

        if not s or not s.code:
            logger.warning(f"未找到策略 {class_name} 的代码")
            return None

        # 构建公共沙箱命名空间（与 test_code / run_vnpy_backtest 一致）
        from app.core.strategy_sandbox import build_strategy_ns
        exec_ns = build_strategy_ns()

        exec(s.code, exec_ns)

        # 3. 自动发现 CtaStrategy 子类
        user_strategy_cls = None
        for name, obj in exec_ns.items():
            if isinstance(obj, type) and issubclass(obj, CtaStrategy) and obj is not CtaStrategy:
                user_strategy_cls = obj
                break

        # 4. 未找到子类时，尝试发现 generate_signals 函数并包装
        if not user_strategy_cls:
            generate_signals_fn = exec_ns.get("generate_signals")
            if not generate_signals_fn:
                logger.error(f"自定义策略 {class_name} 代码中未找到 CtaStrategy 子类或 generate_signals 函数")
                return None

            class CustomStrategy(CtaStrategy):
                @classmethod
                def generate_signals(cls, df: pd.DataFrame, setting: dict) -> pd.Series:
                    return generate_signals_fn(df, setting)

            CustomStrategy.class_name = class_name
            CustomStrategy.__name__ = class_name
            user_strategy_cls = CustomStrategy

        # 5. 注册到缓存（STRATEGY_MAP + VNPY_STRATEGY_MAP）
        STRATEGY_MAP[class_name] = user_strategy_cls
        VNPY_STRATEGY_MAP[class_name] = create_adapter(
            user_strategy_cls,
            grid_mode=(class_name == "GridStrategy"),
        )
        logger.info(f"自定义策略 {class_name} 动态编译成功并已缓存")

        return user_strategy_cls

    except Exception as e:
        logger.error(f"动态编译策略 {class_name} 失败: {e}", exc_info=True)
        return None

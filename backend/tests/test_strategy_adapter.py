"""
适配器层测试 — CtaSignalAdapter

不走引擎，用最小 stub engine，直接注入 _precomputed_signals 绕过 generate_signals，
验证信号 → 委托映射、pos_data 跟踪、T+1 标记、网格模式、连续信号不重复。
"""

import pytest
from datetime import datetime, date

vnpy = pytest.importorskip("vnpy")
from vnpy.trader.constant import Exchange, Direction, Offset, Status
from vnpy.trader.object import BarData, TradeData

from app.core.strategy_adapter import VNPY_STRATEGY_MAP
from app.strategies.base import DoubleMaStrategy, GridStrategy
from tests.conftest import make_bar

VTSYM = "600000.SSE"
SYMBOL = "600000"
EXCHANGE = Exchange.SSE


class StubEngine:
    """最小 stub：记录 send_order 调用，并模拟立即成交以更新 pos_data"""

    def __init__(self, capital: float = 1_000_000.0):
        self.cash = capital
        self.orders = []  # 记录所有 send_order 调用
        self._orderid = 0

    def get_cash_available(self) -> float:
        return self.cash

    def write_log(self, msg: str, strategy=None) -> None:
        pass

    def send_order(self, strategy, vt_symbol, direction, offset, price, volume):
        """记录委托 + 模拟立即成交（更新 adapter.pos_data）"""
        self._orderid += 1
        vt_orderid = f"{vt_symbol}.{self._orderid}"
        self.orders.append({
            "vt_orderid": vt_orderid,
            "direction": direction,
            "offset": offset,
            "price": price,
            "volume": volume,
        })
        # 模拟立即成交：回调 adapter.on_trade
        trade = TradeData(
            symbol=SYMBOL, exchange=EXCHANGE, orderid=str(self._orderid),
            tradeid=str(self._orderid), direction=direction, offset=offset,
            price=price, volume=volume, datetime=datetime(2024, 1, 2),
            gateway_name="STUB",
        )
        strategy.on_trade(trade)
        return [vt_orderid]

    def cancel_order(self, strategy, vt_orderid):
        pass


def _make_adapter(strategy_name: str = "DoubleMaStrategy",
                  capital: float = 1_000_000.0):
    """构造 adapter + stub engine，注入空预计算信号"""
    engine = StubEngine(capital=capital)
    strategy_cls = VNPY_STRATEGY_MAP[strategy_name]
    adapter = strategy_cls(engine, strategy_name, [VTSYM],
                           {"fast_window": 5, "slow_window": 20})
    adapter.on_init()
    return adapter, engine


def _push_bar(adapter, dt: datetime, close: float, open_price: float = None,
              high: float = None, low: float = None):
    """喂一根 bar 给 on_bars"""
    open_price = close if open_price is None else open_price
    high = close if high is None else high
    low = close if low is None else low
    bar = make_bar(SYMBOL, EXCHANGE, dt, open_price, high, low, close)
    adapter.on_bars({VTSYM: bar})


# ── 普通模式：信号 → 委托映射 ────────────────────────────────────────────

class TestNormalSignalMapping:
    def test_buy_signal_empty_position_triggers_long_order(self):
        adapter, engine = _make_adapter()
        adapter._precomputed_signals = [1]  # 注入买入信号
        _push_bar(adapter, datetime(2024, 1, 2), close=10.0)

        assert len(engine.orders) == 1
        assert engine.orders[0]["direction"] == Direction.LONG
        assert engine.orders[0]["offset"] == Offset.OPEN
        # 90% 资金买 10 元：900000/10=90000 股，取 100 整数倍=90000
        assert engine.orders[0]["volume"] > 0
        assert adapter.pos_data[VTSYM] == engine.orders[0]["volume"]
        assert adapter._buy_date == date(2024, 1, 2)

    def test_sell_signal_with_position_triggers_short_order(self):
        adapter, engine = _make_adapter()
        adapter._precomputed_signals = [-1, -1]
        # 先建仓
        adapter.pos_data[VTSYM] = 1000
        adapter._buy_date = date(2024, 1, 1)  # 昨日买，避开 T+1
        _push_bar(adapter, datetime(2024, 1, 2), close=10.0)

        assert len(engine.orders) == 1
        assert engine.orders[0]["direction"] == Direction.SHORT
        assert engine.orders[0]["offset"] == Offset.CLOSE
        assert engine.orders[0]["volume"] == 1000
        assert adapter.pos_data[VTSYM] == 0
        assert adapter._buy_date is None

    def test_hold_signal_no_order(self):
        adapter, engine = _make_adapter()
        adapter._precomputed_signals = [0]
        _push_bar(adapter, datetime(2024, 1, 2), close=10.0)
        assert len(engine.orders) == 0

    def test_consecutive_buy_signals_no_duplicate(self):
        """连续两个买入信号：第二个不应重复买入（已持仓）"""
        adapter, engine = _make_adapter()
        adapter._precomputed_signals = [1, 1]
        _push_bar(adapter, datetime(2024, 1, 2), close=10.0)
        _push_bar(adapter, datetime(2024, 1, 3), close=10.5)

        assert len(engine.orders) == 1  # 只买一次

    def test_buy_then_hold_then_sell(self):
        """买 → 持有 → 卖完整循环"""
        adapter, engine = _make_adapter()
        adapter._precomputed_signals = [1, 0, -1]
        _push_bar(adapter, datetime(2024, 1, 2), close=10.0)  # 买
        shares = adapter.pos_data[VTSYM]
        assert shares > 0
        _push_bar(adapter, datetime(2024, 1, 3), close=10.5)  # 持有，无新单
        assert len(engine.orders) == 1
        _push_bar(adapter, datetime(2024, 1, 4), close=11.0)  # 卖
        assert len(engine.orders) == 2
        assert engine.orders[1]["direction"] == Direction.SHORT
        assert adapter.pos_data[VTSYM] == 0


# ── 网格模式 ────────────────────────────────────────────────────────────

class TestGridMode:
    def _make_grid_adapter(self, capital=1_000_000.0):
        engine = StubEngine(capital=capital)
        strategy_cls = VNPY_STRATEGY_MAP["GridStrategy"]
        adapter = strategy_cls(engine, "GridStrategy", [VTSYM],
                               {"grid_size": 0.02, "grid_quantity": 100})
        adapter.on_init()
        return adapter, engine

    def test_grid_signal_value_three_triggers_three_buys(self):
        """信号值 3 → 3 笔 LONG 委托，各 100 股"""
        adapter, engine = self._make_grid_adapter()
        adapter._precomputed_signals = [3]
        _push_bar(adapter, datetime(2024, 1, 2), close=10.0)

        assert len(engine.orders) == 3
        for o in engine.orders:
            assert o["direction"] == Direction.LONG
            assert o["volume"] == 100
        assert adapter.pos_data[VTSYM] == 300

    def test_grid_sell_signal_triggers_sells(self):
        """信号值 -2 且有持仓 → 2 笔 SHORT 委托"""
        adapter, engine = self._make_grid_adapter()
        adapter._precomputed_signals = [-2]
        adapter.pos_data[VTSYM] = 300
        adapter._buy_date = date(2024, 1, 1)  # 避开 T+1
        _push_bar(adapter, datetime(2024, 1, 2), close=10.0)

        assert len(engine.orders) == 2
        for o in engine.orders:
            assert o["direction"] == Direction.SHORT
            assert o["volume"] == 100
        assert adapter.pos_data[VTSYM] == 100  # 300 - 200

    def test_grid_sell_no_position_skipped(self):
        """无持仓时卖出信号不触发"""
        adapter, engine = self._make_grid_adapter()
        adapter._precomputed_signals = [-2]
        _push_bar(adapter, datetime(2024, 1, 2), close=10.0)
        assert len(engine.orders) == 0


# ── T+1 标记 ────────────────────────────────────────────────────────────

class TestAdapterTPlusOne:
    def test_sell_on_same_day_buy_blocked(self):
        """当日买入当日卖出：adapter 不发卖单（T+1）"""
        adapter, engine = _make_adapter()
        adapter._precomputed_signals = [1, -1]
        _push_bar(adapter, datetime(2024, 1, 2), close=10.0)  # 买，_buy_date=1/2
        assert len(engine.orders) == 1
        # 同日再推一根 bar 触发卖出信号 → 应被 T+1 拦截
        _push_bar(adapter, datetime(2024, 1, 2, 10, 30), close=10.5)
        assert len(engine.orders) == 1  # 没有新卖单

"""
撮合层单元测试 — CtaBacktestingEngine.cross_order

直接构造引擎 + 手动塞 engine.bars / pre_closes / active_limit_orders / _buy_dates，
然后调用 cross_order()，验证：
- next-bar open 成交价
- 涨跌停拒单
- T+1 拒单与清理
- 佣金 min5 / 印花税 / 大额佣金取比例
- cash 增减精确

不依赖真实行情，零网络。
"""

import pytest
from datetime import datetime, date, timedelta

vnpy = pytest.importorskip("vnpy")
from vnpy.trader.constant import Exchange, Direction, Offset, Status
from vnpy.trader.object import OrderData

from app.services.vnpy_backtest_service import CtaBacktestingEngine
from app.core.strategy_adapter import VNPY_STRATEGY_MAP
from tests.conftest import make_bar

VTSYM = "600000.SSE"
SYMBOL = "600000"
EXCHANGE = Exchange.SSE


def _make_engine(capital: float = 1_000_000.0) -> CtaBacktestingEngine:
    """构造一个最小可撮合的引擎实例（已 set_parameters + 绑定 DoubleMaStrategy 适配器）"""
    engine = CtaBacktestingEngine()
    engine.set_parameters(
        vt_symbols=[VTSYM],
        interval=None,  # cross_order 不依赖 interval
        start=datetime(2024, 1, 2),
        end=datetime(2024, 1, 31),
        rate=0.0003,
        stamp_tax_rate=0.001,
        size=1,
        pricetick=0.01,
        capital=capital,
    )
    # 绑定适配器：cross_order 会调 strategy.update_order / update_trade / pos_data
    strategy_cls = VNPY_STRATEGY_MAP["DoubleMaStrategy"]
    engine.add_strategy(strategy_cls, {"fast_window": 5, "slow_window": 20})
    # on_init 不会触发信号计算（无数据），安全
    engine.strategy.on_init()
    return engine


def _make_order(engine: CtaBacktestingEngine, direction: Direction,
                offset: Offset, price: float, volume: float,
                orderid: str = "1") -> OrderData:
    """构造一张订单并塞进 active_limit_orders（模拟 send_order 的结果）"""
    order = OrderData(
        symbol=SYMBOL,
        exchange=EXCHANGE,
        orderid=orderid,
        direction=direction,
        offset=offset,
        price=price,
        volume=volume,
        status=Status.SUBMITTING,
        datetime=engine.datetime,
        gateway_name=engine.gateway_name,
    )
    engine.active_limit_orders[order.vt_orderid] = order
    engine.limit_orders[order.vt_orderid] = order
    return order


def _set_bar(engine: CtaBacktestingEngine, dt: datetime, open_price: float,
             high_price: float = None, low_price: float = None,
             close_price: float = None) -> None:
    """设置当前 bar（cross_order 从 engine.bars[vtsym] 取价）"""
    high_price = open_price if high_price is None else high_price
    low_price = open_price if low_price is None else low_price
    close_price = open_price if close_price is None else close_price
    bar = make_bar(SYMBOL, EXCHANGE, dt, open_price, high_price, low_price, close_price)
    engine.bars[VTSYM] = bar
    engine.datetime = dt


# ── next-bar open 成交价 ────────────────────────────────────────────────

class TestNextOpenFillPrice:
    def test_buy_fills_at_next_bar_open(self):
        """信号在 bar[i] 收盘产生，委托在 bar[i+1] 以 open_price 成交"""
        engine = _make_engine()
        _set_bar(engine, datetime(2024, 1, 2), open_price=100.0)
        # 委托以 bar[i] 收盘价 100 提交
        _make_order(engine, Direction.LONG, Offset.OPEN, price=100.0, volume=100)
        cash_before = engine.cash

        # 下一根 bar，开盘 105
        _set_bar(engine, datetime(2024, 1, 3), open_price=105.0)
        engine.cross_order()

        trades = list(engine.trades.values())
        assert len(trades) == 1
        assert trades[0].price == 105.0  # 不是 100
        assert trades[0].direction == Direction.LONG
        assert engine.strategy.pos_data[VTSYM] == 100
        # cash 减少 = 成交额 + 佣金（100*105=10500，佣金 max(10500*0.0003,5)=5）
        assert abs((cash_before - engine.cash) - (10500.0 + 5.0)) < 1e-6


# ── 涨跌停拒单 ──────────────────────────────────────────────────────────

class TestLimitUpDownRejection:
    def test_buy_rejected_at_limit_up(self):
        """涨停板（open >= pre_close*1.1）买单不成交"""
        engine = _make_engine()
        engine.pre_closes[VTSYM] = 100.0  # limit_up = 110.0
        _set_bar(engine, datetime(2024, 1, 3), open_price=110.0)
        _make_order(engine, Direction.LONG, Offset.OPEN, price=110.0, volume=100)
        cash_before = engine.cash

        engine.cross_order()

        assert len(engine.trades) == 0
        assert len(engine.active_limit_orders) == 1  # 仍挂单
        assert abs(engine.cash - cash_before) < 1e-9  # cash 不变

    def test_buy_fills_just_below_limit_up(self):
        """开盘 109.99 < 110.0，未涨停，正常成交"""
        engine = _make_engine()
        engine.pre_closes[VTSYM] = 100.0
        _set_bar(engine, datetime(2024, 1, 3), open_price=109.99)
        _make_order(engine, Direction.LONG, Offset.OPEN, price=109.99, volume=100)

        engine.cross_order()
        assert len(engine.trades) == 1

    def test_sell_rejected_at_limit_down(self):
        """跌停板（open <= pre_close*0.9）卖单不成交"""
        engine = _make_engine()
        engine.pre_closes[VTSYM] = 100.0  # limit_down = 90.0
        # 卖单需先有持仓且非 T+1：买入日期设为昨日
        engine._buy_dates[VTSYM] = date(2024, 1, 2)
        engine.strategy.pos_data[VTSYM] = 100
        _set_bar(engine, datetime(2024, 1, 3), open_price=90.0)
        _make_order(engine, Direction.SHORT, Offset.CLOSE, price=90.0, volume=100)
        cash_before = engine.cash

        engine.cross_order()

        assert len(engine.trades) == 0
        assert len(engine.active_limit_orders) == 1
        assert abs(engine.cash - cash_before) < 1e-9

    def test_sell_fills_just_above_limit_down(self):
        """开盘 90.01 > 90.0，未跌停，正常成交"""
        engine = _make_engine()
        engine.pre_closes[VTSYM] = 100.0
        engine._buy_dates[VTSYM] = date(2024, 1, 2)
        engine.strategy.pos_data[VTSYM] = 100
        _set_bar(engine, datetime(2024, 1, 3), open_price=90.01)
        _make_order(engine, Direction.SHORT, Offset.CLOSE, price=90.01, volume=100)

        engine.cross_order()
        assert len(engine.trades) == 1


# ── T+1 拒单与清理 ──────────────────────────────────────────────────────

class TestTPlusOne:
    def test_sell_rejected_on_same_day_buy(self):
        """当日买入的股票当日不可卖出 → REJECTED"""
        engine = _make_engine()
        today = date(2024, 1, 5)
        engine._buy_dates[VTSYM] = today  # 今日买入
        engine.strategy.pos_data[VTSYM] = 100
        _set_bar(engine, datetime(2024, 1, 5), open_price=100.0)
        # pre_close 设为 99 避免触发跌停
        engine.pre_closes[VTSYM] = 99.0
        order = _make_order(engine, Direction.SHORT, Offset.CLOSE, price=100.0, volume=100)
        cash_before = engine.cash

        engine.cross_order()

        assert len(engine.trades) == 0
        assert order.status == Status.REJECTED
        assert order.vt_orderid not in engine.active_limit_orders
        assert abs(engine.cash - cash_before) < 1e-9

    def test_sell_allowed_after_buy_date(self):
        """昨日买入，今日可卖 → 正常成交"""
        engine = _make_engine()
        yesterday = date(2024, 1, 4)
        engine._buy_dates[VTSYM] = yesterday
        engine.strategy.pos_data[VTSYM] = 100
        _set_bar(engine, datetime(2024, 1, 5), open_price=100.0)
        engine.pre_closes[VTSYM] = 99.0
        _make_order(engine, Direction.SHORT, Offset.CLOSE, price=100.0, volume=100)

        engine.cross_order()
        assert len(engine.trades) == 1

    def test_buy_date_recorded_after_buy_fill(self):
        """买单成交后，_buy_dates 记录当日（T+1 标记）"""
        engine = _make_engine()
        _set_bar(engine, datetime(2024, 1, 5), open_price=100.0)
        engine.pre_closes[VTSYM] = 99.0
        _make_order(engine, Direction.LONG, Offset.OPEN, price=100.0, volume=100)

        engine.cross_order()
        assert engine._buy_dates.get(VTSYM) == date(2024, 1, 5)

    def test_buy_date_cleared_after_full_sell(self):
        """全部卖出后，_buy_dates 清除"""
        engine = _make_engine()
        engine._buy_dates[VTSYM] = date(2024, 1, 4)  # 昨日买
        engine.strategy.pos_data[VTSYM] = 100
        _set_bar(engine, datetime(2024, 1, 5), open_price=100.0)
        engine.pre_closes[VTSYM] = 99.0
        _make_order(engine, Direction.SHORT, Offset.CLOSE, price=100.0, volume=100)

        engine.cross_order()
        assert VTSYM not in engine._buy_dates
        assert engine.strategy.pos_data[VTSYM] == 0


# ── 佣金 / 印花税 ───────────────────────────────────────────────────────

class TestCommissionAndTax:
    def test_small_trade_commission_floor_5(self):
        """小额交易佣金取下限 5 元（trade_value*0.0003 < 5）"""
        engine = _make_engine()
        _set_bar(engine, datetime(2024, 1, 3), open_price=10.0)
        engine.pre_closes[VTSYM] = 9.9
        _make_order(engine, Direction.LONG, Offset.OPEN, price=10.0, volume=100)
        cash_before = engine.cash

        engine.cross_order()
        # trade_value = 100*10 = 1000, 1000*0.0003=0.3 < 5 → commission=5
        assert abs((cash_before - engine.cash) - (1000.0 + 5.0)) < 1e-6

    def test_large_trade_commission_proportional(self):
        """大额交易佣金取比例（trade_value*0.0003 > 5）"""
        engine = _make_engine()
        _set_bar(engine, datetime(2024, 1, 3), open_price=10.0)
        engine.pre_closes[VTSYM] = 9.9
        _make_order(engine, Direction.LONG, Offset.OPEN, price=10.0, volume=10000)
        cash_before = engine.cash

        engine.cross_order()
        # trade_value = 10000*10 = 100000, 100000*0.0003=30 > 5 → commission=30
        assert abs((cash_before - engine.cash) - (100000.0 + 30.0)) < 1e-6

    def test_sell_stamp_tax(self):
        """卖出收印花税 trade_value*0.001，且含佣金"""
        engine = _make_engine()
        engine._buy_dates[VTSYM] = date(2024, 1, 2)
        engine.strategy.pos_data[VTSYM] = 100
        _set_bar(engine, datetime(2024, 1, 3), open_price=10.0)
        engine.pre_closes[VTSYM] = 9.9
        _make_order(engine, Direction.SHORT, Offset.CLOSE, price=10.0, volume=100)
        cash_before = engine.cash

        engine.cross_order()
        # trade_value = 1000, commission = max(0.3,5)=5, stamp_tax = 1000*0.001=1
        # cash 增加 = 1000 - 5 - 1 = 994
        assert abs((engine.cash - cash_before) - (1000.0 - 5.0 - 1.0)) < 1e-6

    def test_sell_large_stamp_tax(self):
        """大额卖出：佣金取比例 + 印花税"""
        engine = _make_engine()
        engine._buy_dates[VTSYM] = date(2024, 1, 2)
        engine.strategy.pos_data[VTSYM] = 10000
        _set_bar(engine, datetime(2024, 1, 3), open_price=10.0)
        engine.pre_closes[VTSYM] = 9.9
        _make_order(engine, Direction.SHORT, Offset.CLOSE, price=10.0, volume=10000)
        cash_before = engine.cash

        engine.cross_order()
        # trade_value=100000, commission=30, stamp_tax=100, cash += 100000-30-100=99870
        assert abs((engine.cash - cash_before) - (100000.0 - 30.0 - 100.0)) < 1e-6

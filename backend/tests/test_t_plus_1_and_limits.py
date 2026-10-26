"""
T+1 与涨跌停双路径保护测试

A 股涨跌停/T+1 保护有两条独立路径，本文件分别测试：

路径1（回测引擎 cross_order，回测中真正生效）:
    app/services/vnpy_backtest_service.py:449-533 cross_order()
    - new_bars() 把前一根 bar.close_price 存入 self.pre_closes[vt_symbol]
    - 撮合时 limit_up = round_to(pre_close*1.1, pricetick), limit_down = pre_close*0.9
    - 涨停（bar.open_price >= limit_up）买不进 → 委托不成交留待下根
    - 跌停（bar.open_price <= limit_down）卖不出 → 委托不成交留待下根
    - T+1：order.direction==SHORT and _buy_dates[vt]==today → REJECTED
    - 成交价 = bar.open_price（信号 bar[i] 收盘产生 → 委托 bar[i+1] 开盘成交）

路径2（适配器 _is_limit_up/_is_limit_down，实盘 live gateway 路径生效）:
    app/core/strategy_adapter.py:252-266
    - getattr(bar, 'pre_close', None) 读取昨收
    - vnpy BarData 构造函数无 pre_close 字段，回测引擎 new_bars 也不设置它
    - 因此回测中 getattr 永远返回 None → 适配器涨跌停检查在回测中是 dead code
    - 实盘 live gateway 路径 tick 数据带 pre_close，适配器会读到
    - 本路径通过 setattr(bar, 'pre_close', ...) 动态注入昨收验证适配器逻辑本身正确
"""

import pytest
from datetime import datetime

vnpy = pytest.importorskip("vnpy")
from vnpy.trader.constant import Exchange, Interval, Direction, Offset, Status
from vnpy.trader.object import BarData

from app.services.vnpy_backtest_service import CtaBacktestingEngine
from app.core.strategy_adapter import CtaSignalAdapter, VNPY_STRATEGY_MAP
from tests.conftest import _make_df, df_to_bars, make_bar_with_pre_close

VTSYM = "600000.SSE"


# ── 路径1：引擎层 cross_order 涨跌停/T+1 保护 ─────────────────────────────


def _make_engine(df, capital=1_000_000.0, pricetick=0.01):
    """构造引擎并注入历史数据，未跑回测（留给测试控制信号注入）"""
    bars = df_to_bars(df, symbol="600000", exchange=Exchange.SSE, interval=Interval.DAILY)
    engine = CtaBacktestingEngine()
    engine.set_parameters(
        vt_symbols=[VTSYM], interval=Interval.DAILY,
        start=datetime(2024, 1, 2), end=datetime(2026, 12, 31),
        rate=0.0003, stamp_tax_rate=0.001, size=1,
        pricetick=pricetick, capital=capital,
    )
    engine.add_strategy(VNPY_STRATEGY_MAP["DoubleMaStrategy"], {"fast_window": 5, "slow_window": 20})
    for bar in bars:
        engine.dts.add(bar.datetime)
        engine.history_data[(bar.datetime, VTSYM)] = bar
    return engine


def _inject_signals(engine, signals):
    """注入预计算信号，绕过引擎 precompute_signals 覆盖

    run_backtesting 会调 strategy.precompute_signals(bars_data) 覆盖 _precomputed_signals，
    这里 monkeypatch 掉 precompute_signals 让它直接设置我们想要的信号序列。
    signals[i] 对应第 i 根 K 线的信号（1=买, -1=卖, 0=持有）。
    """
    def _fake_precompute(self, bars_data):
        self._precomputed_signals = list(signals)
        self._bar_index = 0
        self._precompute_total = len(bars_data)
    engine.strategy.precompute_signals = lambda bars_data: _fake_precompute(engine.strategy, bars_data)


class TestEngineLimitProtection:
    """回测引擎 cross_order() 涨跌停/T+1 保护（回测中真正生效的路径）"""

    def test_limit_up_blocks_buy(self):
        """涨停买不进：bar[i] close=10 信号买入，bar[i+1] 开盘 11(=10*1.1 涨停) → 买委托不成交

        构造：D1 close=10（成为 D2 的昨收），D2 open=11.0 close=11.0（11=10*1.1 涨停价）。
        信号：D1=买入 → 委托在 D2 开盘撮合，bar.open_price=11.0 >= limit_up=11.0 → continue 不成交。
        后续给一段正常行情让订单有机会在再下根成交，确认全程无买入成交（订单持续挂起直到行情松动）。
        """
        # 5 根 bar：D1 close=10，D2 一字涨停 11，D3-D5 继续涨停（持续买不进）
        dates = ["2024-01-02", "2024-01-03", "2024-01-04", "2024-01-05", "2024-01-08"]
        closes = [10.0, 11.0, 12.1, 13.31, 14.641]
        opens = [10.0, 11.0, 12.1, 13.31, 14.641]  # 一字涨停：open=close=前收*1.1
        highs = [10.01, 11.0, 12.1, 13.31, 14.641]
        lows = [9.99, 11.0, 12.1, 13.31, 14.641]
        df = _make_df(dates, closes, opens, highs, lows)
        engine = _make_engine(df)
        # D1 买入信号，其余持有
        _inject_signals(engine, [1, 0, 0, 0, 0])
        engine.strategy.on_init()
        engine.run_backtesting()
        engine.calculate_result()

        # 无任何买入成交（D2-D5 全涨停，买委托一直挂起）
        buy_trades = [t for t in engine.trades.values() if t.direction == Direction.LONG]
        assert len(buy_trades) == 0, (
            f"涨停应买不进，却出现买入成交: {[(t.datetime, t.price) for t in buy_trades]}"
        )
        # 订单应仍挂起（NOTTRADED），未被 REJECTED
        pending = [o for o in engine.limit_orders.values()
                   if o.direction == Direction.LONG and o.status == Status.NOTTRADED]
        assert len(pending) >= 1, "涨停买委托应挂起为 NOTTRADED"

    def test_limit_down_blocks_sell(self):
        """跌停卖不出：持仓中 bar[i] close=10 信号卖出，bar[i+1] 开盘 9(=10*0.9 跌停) → 卖委托不成交

        构造：D1 close=10 买信号，D2 正常开盘成交买入建仓，D3 close=10 卖信号，
        D4-D6 连续一字跌停（每日 open=close=前收*0.9，9.0/8.1/7.29）→ 卖委托全程不成交。
        连续跌停保证：每根 bar 的 open 都触及当日 limit_down（=前收*0.9），
        引擎 cross_order 的 `bar.open_price <= limit_down` 持续命中，卖委托一直挂起。
        （若后续行情松动，挂起的卖委托会在松动当日成交——这是引擎正确行为，故需连续跌停确保全程不成交。）
        """
        dates = ["2024-01-02", "2024-01-03", "2024-01-04", "2024-01-05", "2024-01-08", "2024-01-09"]
        closes = [10.0, 10.1, 10.0, 9.0, 8.1, 7.29]
        opens = [10.0, 10.1, 10.1, 9.0, 8.1, 7.29]  # D4-D6 一字跌停
        highs = [10.01, 10.2, 10.1, 9.0, 8.1, 7.29]
        lows = [9.99, 10.0, 9.9, 9.0, 8.1, 7.29]
        df = _make_df(dates, closes, opens, highs, lows)
        engine = _make_engine(df)
        # D1 买入，D3 卖出，其余持有
        _inject_signals(engine, [1, 0, -1, 0, 0, 0])
        engine.strategy.on_init()
        engine.run_backtesting()
        engine.calculate_result()

        # 应有买入成交（D2 正常开盘）
        buy_trades = [t for t in engine.trades.values() if t.direction == Direction.LONG]
        assert len(buy_trades) == 1, f"应有一笔买入成交，实际 {len(buy_trades)}"
        # 无卖出成交（D4-D6 连续跌停，卖委托全程挂起）
        sell_trades = [t for t in engine.trades.values() if t.direction == Direction.SHORT]
        assert len(sell_trades) == 0, (
            f"跌停应卖不出，却出现卖出成交: {[(t.datetime, t.price) for t in sell_trades]}"
        )
        # 卖委托应挂起为 NOTTRADED
        pending = [o for o in engine.limit_orders.values()
                   if o.direction == Direction.SHORT and o.status == Status.NOTTRADED]
        assert len(pending) >= 1, "跌停卖委托应挂起为 NOTTRADED"

    def test_t_plus_1_blocks_same_day_sell(self):
        """T+1：买入成交当日不可卖出（引擎 _buy_dates==today → REJECTED）

        引擎 cross_order 的 T+1 拦截发生在：卖委托撮合时 _buy_dates[vt]==today。
        正常信号流程下卖委托总比买入晚一根 bar 成交（today 不同），不会触发拦截。
        所以这里直接用 send_order 在同一根 bar 同时挂买单和卖单：
        - D1: 买单撮合成交（_buy_dates=D1），同日再 send_order 一个卖单
        - D2: 卖单撮合，today=D2 != _buy_dates=D1 → 不拦（这是允许的次日卖出，作为对照不出现）
        要触发拦截：买单在 D1 成交（_buy_dates=D1），卖单在 D1 当日也进入 cross_order 撮合。
        即同日既买单成交又卖单撮合 → 卖单 REJECTED。

        实现：手动驱动 new_bars 之前用 send_order 挂好买单，跑 new_bars(D1) 让买单成交并
        设置 _buy_dates=D1，紧接着再 send_order 卖单，跑 new_bars(D2) 时卖单撮合
        today=D2 != D1 不拦。要测真正拦截需 today==D1：即在 D1 买单成交后、
        同日（engine.datetime 仍为 D1）让卖单也进入 cross_order。

        由于 cross_order 在 new_bars 开头调用且依赖 self.datetime，最直接的拦截复现：
        构造两根 bar，D1 买单成交（_buy_dates=D1.date），然后手动让 engine.datetime 仍为 D1
        时把卖单加入 active_limit_orders 再调一次 cross_order，验 _buy_dates==today REJECTED。
        """
        dates = ["2024-01-02", "2024-01-03"]
        closes = [10.0, 10.5]
        opens = [10.0, 10.5]
        df = _make_df(dates, closes, opens)
        engine = _make_engine(df)
        engine.strategy.on_init()

        # === D1：手动挂买单，跑 new_bars 让其成交，建立 _buy_dates=D1 ===
        d1 = datetime(2024, 1, 2)
        # 先 new_bars(D1) 会 cross_order（无挂单）+ on_bars（策略无信号因为没 run_backtesting）
        # 但我们要手动挂单：在 new_bars 之前 send_order
        engine.send_order(engine.strategy, VTSYM, Direction.LONG, Offset.OPEN, 10.0, 100)
        engine.new_bars(d1)
        # 买单应以 D1 open=10.0 成交，_buy_dates[D1]=2024-01-02
        buy_trades = [t for t in engine.trades.values() if t.direction == Direction.LONG]
        assert len(buy_trades) == 1, f"D1 应有买单成交，实际 {len(buy_trades)}"
        assert engine._buy_dates.get(VTSYM) == d1.date(), (
            f"_buy_dates 应为 {d1.date()}，实际 {engine._buy_dates.get(VTSYM)}"
        )

        # === 同日（engine.datetime 仍为 D1）挂卖单，再调 cross_order 验 T+1 拦截 ===
        # 卖单以 D1 的 bar 撮合，today=D1.date()==_buy_dates → REJECTED
        engine.send_order(engine.strategy, VTSYM, Direction.SHORT, Offset.CLOSE, 10.0, 100)
        engine.cross_order()

        # 卖单应被 REJECTED
        sell_orders = [o for o in engine.limit_orders.values()
                       if o.direction == Direction.SHORT]
        assert len(sell_orders) == 1, "应有一个卖单记录"
        assert sell_orders[0].status == Status.REJECTED, (
            f"T+1 应拦截卖单（REJECTED），实际 status={sell_orders[0].status}"
        )
        # 不应有卖出成交
        sell_trades = [t for t in engine.trades.values() if t.direction == Direction.SHORT]
        assert len(sell_trades) == 0, "T+1 拦截下不应有卖出成交"

    def test_t_plus_1_and_limit_down_independent(self):
        """T+1 与跌停是 cross_order 两个独立检查：T+1 看 _buy_dates==today，跌停看 open_price<=limit_down。

        第一部分（T+1 触发，跌停不触发）：
            D1 买单成交（_buy_dates=D1），同日（engine.datetime 仍为 D1）挂卖单再调 cross_order，
            today=D1==_buy_dates → REJECTED。此时 D1 为首根 bar 无 pre_close，limit_down=0，
            跌停分支不命中——证明 REJECTED 来自 T+1 而非跌停。
        第二部分（跌停触发，T+1 不触发）：
            D1 买单成交（_buy_dates=D1），D2 一字跌停（open=close=9.0，D1.close=10.0 → limit_down=9.0），
            卖单在 D2 撮合：bar.open_price=9.0 <= limit_down=9.0 → continue 不成交（NOTTRADED 挂起）；
            而 today=D2 != _buy_dates=D1，T+1 分支不命中——证明挂起来自跌停而非 T+1。
        两条分支各自独立生效。
        """
        dates = ["2024-01-02", "2024-01-03"]
        closes = [10.0, 9.0]
        opens = [10.0, 9.0]
        df = _make_df(dates, closes, opens)
        engine = _make_engine(df)
        engine.strategy.on_init()

        # === 第一部分：T+1 触发（同日卖） ===
        d1 = datetime(2024, 1, 2)
        engine.send_order(engine.strategy, VTSYM, Direction.LONG, Offset.OPEN, 10.0, 100)
        engine.new_bars(d1)
        # 买单成交，_buy_dates=D1
        buy_trades = [t for t in engine.trades.values() if t.direction == Direction.LONG]
        assert len(buy_trades) == 1, f"D1 应有买单成交，实际 {len(buy_trades)}"
        assert engine._buy_dates.get(VTSYM) == d1.date()

        # 同日挂卖单再 cross_order：T+1 命中 → REJECTED
        engine.send_order(engine.strategy, VTSYM, Direction.SHORT, Offset.CLOSE, 10.0, 100)
        engine.cross_order()
        sell_orders = [o for o in engine.limit_orders.values()
                       if o.direction == Direction.SHORT]
        assert len(sell_orders) == 1, "应有一个卖单记录"
        assert sell_orders[0].status == Status.REJECTED, (
            f"T+1 应拦截卖单（REJECTED），实际 status={sell_orders[0].status}"
        )
        sell_trades_p1 = [t for t in engine.trades.values() if t.direction == Direction.SHORT]
        assert len(sell_trades_p1) == 0, "T+1 拦截下不应有卖出成交"

        # === 第二部分：跌停触发，T+1 不触发（次日卖，但当日跌停） ===
        # 重新建仓：D1 再买一笔（_buy_dates 仍为 D1），D2 一字跌停挂卖
        d2 = datetime(2024, 1, 3)
        # 先清空第一部分遗留的 REJECTED 卖单与买单，避免干扰
        for o in list(engine.limit_orders.values()):
            engine.limit_orders.pop(o.vt_orderid, None)
        engine.active_limit_orders.clear()
        # 重新挂买单并在 D1 成交（_buy_dates=D1）
        engine.send_order(engine.strategy, VTSYM, Direction.LONG, Offset.OPEN, 10.0, 100)
        engine.new_bars(d1)
        assert engine._buy_dates.get(VTSYM) == d1.date()

        # D2 挂卖单：new_bars(D2) 会先设置 pre_closes[VTSYM]=D1.close=10.0
        # 再 cross_order：limit_down=round_to(10*0.9,0.01)=9.0，bar.open_price=9.0<=9.0 → 跌停分支命中 continue
        # today=D2 != _buy_dates=D1 → T+1 分支不命中
        engine.send_order(engine.strategy, VTSYM, Direction.SHORT, Offset.CLOSE, 9.0, 100)
        engine.new_bars(d2)

        sell_orders_p2 = [o for o in engine.limit_orders.values()
                          if o.direction == Direction.SHORT]
        assert len(sell_orders_p2) == 1, "D2 应有一个卖单记录"
        # 跌停分支把卖单留为 NOTTRADED 挂起（未被 T+1 REJECTED）
        assert sell_orders_p2[0].status == Status.NOTTRADED, (
            f"跌停应使卖单挂起为 NOTTRADED，实际 status={sell_orders_p2[0].status} "
            f"（若为 REJECTED 说明 T+1 误触发，today 应 != _buy_dates）"
        )
        # 不应有卖出成交
        sell_trades_p2 = [t for t in engine.trades.values() if t.direction == Direction.SHORT]
        assert len(sell_trades_p2) == 0, "跌停下卖单不应成交"


# ── 路径2：适配器层 _is_limit_up/_is_limit_down（实盘 live gateway 路径） ──


def _make_adapter_instance():
    """构造 CtaSignalAdapter 实例（ABC，用 __new__ 绕过抽象方法依赖）

    _is_limit_up/_is_limit_down 不依赖任何抽象方法或实例状态，纯逻辑方法。
    """
    return CtaSignalAdapter.__new__(CtaSignalAdapter)


class TestAdapterLimitProtection:
    """适配器 _is_limit_up/_is_limit_down 逻辑（实盘 live gateway 路径，回测中是 dead code）

    回测中是 dead code 的原因：
    - vnpy BarData 构造函数无 pre_close 字段
    - 回测引擎 new_bars() 也不给 bar 设置 pre_close 动态属性
    - 适配器 _is_limit_up 用 getattr(bar, 'pre_close', None) 永远拿到 None → 返回 False
    所以回测路径下适配器的涨跌停检查从不生效，真正拦涨跌停的是引擎 cross_order。
    本类通过 setattr(bar, 'pre_close', ...) 动态注入昨收，验证适配器逻辑本身在
    实盘 live gateway 路径（tick 带 pre_close）下是否正确。
    """

    def test_is_limit_up_true_at_10pct(self):
        """pre_close=10, close=11.0 → 涨停（10*1.1=11.0）"""
        adapter = _make_adapter_instance()
        bar = make_bar_with_pre_close(
            "600000", Exchange.SSE, datetime(2024, 1, 2),
            open_price=11, high_price=11, low_price=11,
            close_price=11.0, pre_close=10.0,
        )
        assert adapter._is_limit_up(bar, VTSYM) is True

    def test_is_limit_up_false_below_10pct(self):
        """pre_close=10, close=10.5 → 非涨停（10*1.1=11.0, 10.5<11.0）"""
        adapter = _make_adapter_instance()
        bar = make_bar_with_pre_close(
            "600000", Exchange.SSE, datetime(2024, 1, 2),
            open_price=10.5, high_price=10.6, low_price=10.4,
            close_price=10.5, pre_close=10.0,
        )
        assert adapter._is_limit_up(bar, VTSYM) is False

    def test_is_limit_down_true_at_10pct(self):
        """pre_close=10, close=9.0 → 跌停（10*0.9=9.0）"""
        adapter = _make_adapter_instance()
        bar = make_bar_with_pre_close(
            "600000", Exchange.SSE, datetime(2024, 1, 2),
            open_price=9, high_price=9, low_price=9,
            close_price=9.0, pre_close=10.0,
        )
        assert adapter._is_limit_down(bar, VTSYM) is True

    def test_is_limit_down_false_above_10pct(self):
        """pre_close=10, close=9.5 → 非跌停（10*0.9=9.0, 9.5>9.0）"""
        adapter = _make_adapter_instance()
        bar = make_bar_with_pre_close(
            "600000", Exchange.SSE, datetime(2024, 1, 2),
            open_price=9.5, high_price=9.6, low_price=9.4,
            close_price=9.5, pre_close=10.0,
        )
        assert adapter._is_limit_down(bar, VTSYM) is False

    def test_no_pre_close_returns_false(self):
        """bar 无 pre_close 属性 → _is_limit_up/_is_limit_down 都返回 False（不误拦）

        这是回测路径下适配器涨跌停检查沦为 dead code 的根因：
        BarData 构造函数无 pre_close 字段，getattr 返回 None。
        """
        adapter = _make_adapter_instance()
        bar = BarData(
            gateway_name="T", symbol="600000", exchange=Exchange.SSE,
            datetime=datetime(2024, 1, 2), interval=Interval.DAILY,
            open_price=11, high_price=11, low_price=11, close_price=11,
            volume=1000, turnover=0,
        )
        assert not hasattr(bar, "pre_close"), "BarData 构造后不应有 pre_close 属性"
        assert adapter._is_limit_up(bar, VTSYM) is False
        assert adapter._is_limit_down(bar, VTSYM) is False

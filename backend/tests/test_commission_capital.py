"""佣金 / 印花税 / 资金守恒精确对拍 + 整手回退行为记录

引擎机制（app/services/vnpy_backtest_service.py cross_order line 449-533）：
- 信号在 bar[i] 收盘产生，委托以 close_price 提交，在 bar[i+1] 以 **open_price** 成交。
- 买入：cash -= trade_value；佣金 = max(trade_value*rate, 5)。
- 卖出：cash += trade_value；佣金 + 印花税 stamp_tax = trade_value*stamp_tax_rate。
- T+1：买入当日不可卖。

适配器 _handle_normal_signal（app/core/strategy_adapter.py:268-298）：
- buy_amount = available_cash * 0.9
- shares_100 = int(buy_amount/(price*100))*100   # 整手分支
- shares = shares_100 if shares_100>0 else int(buy_amount/price)   # 零股回退分支
"""

import pytest
from datetime import datetime

vnpy = pytest.importorskip("vnpy")
from vnpy.trader.constant import Exchange, Interval, Direction, Offset, Status

from app.services.vnpy_backtest_service import CtaBacktestingEngine
from app.core.strategy_adapter import VNPY_STRATEGY_MAP
from tests.conftest import _make_df, df_to_bars

VTSYM = "600000.SSE"


# ── 工厂（参考 tests/test_t_plus_1_and_limits.py） ──────────────────────────


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


def _run(engine):
    """on_init + run_backtesting + calculate_result，返回 stats"""
    engine.strategy.on_init()
    engine.run_backtesting()
    stats = engine.calculate_result()
    return stats


# ── 测试类1：佣金 / 印花税精确对拍 ─────────────────────────────────────────


class TestCommissionPrecision:
    """佣金 max(trade_value*0.0003, 5) 与印花税（卖端 trade_value*0.001）精确对拍

    成交价控制：信号 bar[i] 委托，bar[i+1].open_price 成交。
    所以要让"买入@10"成交，构造 bar[i] 产生买信号，bar[i+1].open=10.0。
    """

    def test_buy_sell_commission_and_stamp_tax(self):
        """买100股@10 + 卖100股@10（同价零盈亏）：总盈亏 = -(买佣5 + 卖佣5 + 印花税1) = -11

        构造 3 根 bar：
          D1 close=10 买信号 → 委托 D2 open=10 成交买入 100 股
          D2 close=10 卖信号 → 委托 D3 open=10 成交卖出 100 股
          D3 收尾
        买100股@10：trade_value=1000，comm=max(1000*0.0003,5)=5
        卖100股@10：trade_value=1000，comm=max(1000*0.0003,5)=5，stamp=1000*0.001=1
        零盈亏（同价买卖，无价差）→ 总盈亏应 = -(5+5+1) = -11

        capital 控制：买100股需 buy_amount∈[1000,2000)（shares_100=int(buy_amount/1000)*100=100）。
        buy_amount=available*0.9，取 capital=1200 → buy_amount=1080 → shares_100=100。
        """
        dates = ["2024-01-02", "2024-01-03", "2024-01-04"]
        closes = [10.0, 10.0, 10.0]
        opens = [10.0, 10.0, 10.0]
        highs = [10.01, 10.01, 10.01]
        lows = [9.99, 9.99, 9.99]
        df = _make_df(dates, closes, opens, highs, lows)
        # capital=1200: buy_amount=1080, shares_100=int(1080/1000)*100=100 股
        engine = _make_engine(df, capital=1200.0)
        # D1 买入，D2 卖出，D3 持有
        _inject_signals(engine, [1, -1, 0])
        stats = _run(engine)

        # 应有 1 笔买入 + 1 笔卖出，各 100 股 @10
        buys = [t for t in engine.trades.values() if t.direction == Direction.LONG]
        sells = [t for t in engine.trades.values() if t.direction == Direction.SHORT]
        assert len(buys) == 1, f"应有一笔买入，实际 {len(buys)}"
        assert len(sells) == 1, f"应有一笔卖出，实际 {len(sells)}"
        assert buys[0].price == 10.0 and buys[0].volume == 100
        assert sells[0].price == 10.0 and sells[0].volume == 100

        # 总盈亏应 ≈ -11（同价零盈亏，仅扣佣金+印花税）
        total_profit = stats["total_profit"]
        assert abs(total_profit - (-11.0)) < 0.01, (
            f"零盈亏场景总盈亏应为 -11（买佣5+卖佣5+印花税1），实际 {total_profit}"
        )

    def test_stamp_tax_only_on_sell(self):
        """印花税只在卖出端收，买入不收

        只买不卖，验证现金减少 = 买入成本 + 买入佣金（无印花税）。
        买100股@10：trade_value=1000，comm=max(1000*0.0003,5)=5，无印花税。
        末尾持仓 = 100 股@10（D3.close=10），持仓市值=1000。
        final_total_assets = final_cash + 1000。
        total_profit = final_total_assets - initial_total_assets
                    = (capital - 1000 - 5) + 1000 - capital = -5（仅买入佣金，无印花税）

        capital=1200: buy_amount=1080, shares_100=int(1080/1000)*100=100 股。
        """
        dates = ["2024-01-02", "2024-01-03", "2024-01-04"]
        closes = [10.0, 10.0, 10.0]
        opens = [10.0, 10.0, 10.0]
        highs = [10.01, 10.01, 10.01]
        lows = [9.99, 9.99, 9.99]
        df = _make_df(dates, closes, opens, highs, lows)
        engine = _make_engine(df, capital=1200.0)
        # 仅 D1 买入，不卖
        _inject_signals(engine, [1, 0, 0])
        stats = _run(engine)

        buys = [t for t in engine.trades.values() if t.direction == Direction.LONG]
        sells = [t for t in engine.trades.values() if t.direction == Direction.SHORT]
        assert len(buys) == 1 and len(sells) == 0, "应只买不卖"

        # 末尾持仓 100 股@10（D3.close=10），持仓市值=1000
        # total_profit = -5（仅买入佣金5，无印花税）
        total_profit = stats["total_profit"]
        assert abs(total_profit - (-5.0)) < 0.01, (
            f"只买不卖应仅扣买入佣金5（无印花税），总盈亏应为 -5，实际 {total_profit}"
        )


# ── 测试类2：资金守恒（验算5项） ───────────────────────────────────────────


class TestCapitalConservation:
    """资金守恒：引擎内建 5 项验算在完整买卖配对场景下应全过"""

    def test_verification_passes_on_full_cycle(self):
        """完整买卖配对（末尾空仓）→ 5 项验算应全过（BUG1修复后：印花税不再被5元最低吞掉）

        构造 3 根 bar，D1 买、D2 卖、D3 收尾，同价@10。
        末尾空仓（已卖出），第5项 trade_pnl_consistency 的 holding_pnl=0，
        不触发"末尾持仓误报"缺陷（Task7 修复的缺陷在末尾持仓场景）。
        """
        dates = ["2024-01-02", "2024-01-03", "2024-01-04"]
        closes = [10.0, 10.0, 10.0]
        opens = [10.0, 10.0, 10.0]
        highs = [10.01, 10.01, 10.01]
        lows = [9.99, 9.99, 9.99]
        df = _make_df(dates, closes, opens, highs, lows)
        engine = _make_engine(df, capital=1200.0)
        _inject_signals(engine, [1, -1, 0])
        stats = _run(engine)

        v = stats["verification"]
        # 末尾空仓场景：5 项应全过
        for key in ("capital_conservation", "daily_pnl_sum", "equity_consistency",
                    "max_drawdown", "trade_pnl_consistency"):
            assert v[key]["passed"] is True, f"{key}未过: {v[key]}"
        assert v["overall"]["passed"] is True
        assert engine.verification_failed is False


# ── 测试类3：整手回退分支行为记录（先测试再定是否BUG） ────────────────────


class TestHundredSharesRounding:
    """整手回退分支行为记录

    适配器 _handle_normal_signal（app/core/strategy_adapter.py:284-285）：
        shares_100 = int(buy_amount/(price*100))*100
        shares = shares_100 if shares_100 > 0 else int(buy_amount/price)

    当资金不够买100股时（buy_amount < price*100），shares_100==0，
    回退到 int(buy_amount/price) 买**零股**（不满100股的碎股）。
    本类如实记录此行为，不预设对错——是否应改为"资金不足100股就不买"由后续决定。
    """

    def test_insufficient_cash_for_100_shares_behavior(self):
        """资金只够买 99 股时，记录适配器实际买入股数

        构造：price=10，capital=1100。
        available_cash = 1100（初始无持仓）。
        buy_amount = 1100 * 0.9 = 990。
        100股需 trade_value = 100*10 = 1000，buy_amount=990 < 1000 → shares_100=0
        回退 shares = int(990/10) = 99 股（零股）。
        实际成交：99股@10，trade_value=990，comm=max(990*0.0003,5)=5。
        预期：买入 99 股（零股），不是 0 股，也不是 100 股。

        本测试如实记录：适配器在资金不足100股时买入零股（99股）。
        若后续判定此为BUG（A股不允许零股），改适配器后此断言需更新。
        """
        dates = ["2024-01-02", "2024-01-03", "2024-01-04"]
        closes = [10.0, 10.0, 10.0]
        opens = [10.0, 10.0, 10.0]
        highs = [10.01, 10.01, 10.01]
        lows = [9.99, 9.99, 9.99]
        df = _make_df(dates, closes, opens, highs, lows)
        # capital=1100: buy_amount=990 < 1000(100股成本) → shares_100=0 → 回退 99 股
        engine = _make_engine(df, capital=1100.0)
        _inject_signals(engine, [1, 0, 0])
        _run(engine)

        buys = [t for t in engine.trades.values() if t.direction == Direction.LONG]
        assert len(buys) == 1, f"应有一笔买入成交，实际 {len(buys)}"

        # 如实记录：买入了 99 股零股（不是 0，不是 100）
        assert buys[0].volume == 99, (
            f"整手回退分支：buy_amount=990, price=10, 预期回退买 99 股零股，"
            f"实际买 {buys[0].volume} 股。若此值变化说明适配器整手逻辑已改。"
        )
        # 成交价 = bar[i+1].open = 10.0
        assert buys[0].price == 10.0

    def test_zero_buy_when_cash_below_one_share(self):
        """资金连1股都买不起时，记录适配器实际行为

        构造：price=10，capital=10。
        available=10, buy_amount=10*0.9=9, price=10。
        shares_100 = int(9/1000)*100 = 0
        回退 shares = int(9/10) = 0 股。
        shares==0 → 适配器 if shares > 0 不成立，不调 buy()，无成交。
        预期：无买入成交（0 股）。
        """
        dates = ["2024-01-02", "2024-01-03", "2024-01-04"]
        closes = [10.0, 10.0, 10.0]
        opens = [10.0, 10.0, 10.0]
        highs = [10.01, 10.01, 10.01]
        lows = [9.99, 9.99, 9.99]
        df = _make_df(dates, closes, opens, highs, lows)
        engine = _make_engine(df, capital=10.0)
        _inject_signals(engine, [1, 0, 0])
        _run(engine)

        buys = [t for t in engine.trades.values() if t.direction == Direction.LONG]
        # 资金连1股都买不起 → 不下单 → 无成交
        assert len(buys) == 0, (
            f"buy_amount=9, price=10, int(9/10)=0 股，预期不下单无成交，"
            f"实际有 {len(buys)} 笔买入"
        )

    def test_exact_100_shares_boundary(self):
        """边界：buy_amount 恰好够 100 股时走整手分支（非回退）

        构造：price=10，capital 使得 buy_amount = 1000（恰够100股）。
        available*0.9 = 1000 → available = 1111.11...
        shares_100 = int(1000/1000)*100 = 100（整手分支，>0）
        shares = 100。
        预期：买入 100 股（走整手分支，非回退）。
        """
        dates = ["2024-01-02", "2024-01-03", "2024-01-04"]
        closes = [10.0, 10.0, 10.0]
        opens = [10.0, 10.0, 10.0]
        highs = [10.01, 10.01, 10.01]
        lows = [9.99, 9.99, 9.99]
        df = _make_df(dates, closes, opens, highs, lows)
        # available*0.9=1000 → available≈1111.12，取 capital=1112 留余量
        # 但要触发整手分支需 shares_100>0：int(buy_amount/1000)*100 >= 100
        #   → buy_amount >= 1000 → available >= 1111.12
        engine = _make_engine(df, capital=1112.0)
        _inject_signals(engine, [1, 0, 0])
        _run(engine)

        buys = [t for t in engine.trades.values() if t.direction == Direction.LONG]
        assert len(buys) == 1, f"应有一笔买入成交，实际 {len(buys)}"
        # 整手分支：buy_amount=1112*0.9=1000.8, shares_100=int(1000.8/1000)*100=100
        assert buys[0].volume == 100, (
            f"边界 buy_amount≈1000.8 走整手分支应买 100 股，实际 {buys[0].volume}"
        )

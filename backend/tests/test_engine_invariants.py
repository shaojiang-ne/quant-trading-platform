"""
全程不变式测试 — 每根 bar 后断言 cash>=0、持仓>=0

通过 monkeypatch 包裹 engine.new_bars，在原方法之后插入断言。
这能抓"仓位计算错""佣金漏扣""资金穿仓"等隐蔽 bug —— 引擎自带的
_verify_result 只看终点，不变式看全程。
"""

import pytest
from datetime import datetime, date, timedelta

vnpy = pytest.importorskip("vnpy")
import numpy as np
from vnpy.trader.constant import Exchange, Interval

from app.services.vnpy_backtest_service import CtaBacktestingEngine
from app.core.strategy_adapter import VNPY_STRATEGY_MAP
from tests.conftest import _make_df, df_to_bars, make_crossover_data

VTSYM = "600000.SSE"
CAPITAL = 1_000_000.0


def _run_with_invariants(df, strategy_name="DoubleMaStrategy",
                         setting=None, capital=CAPITAL):
    """注入数据 + 包裹 new_bars 跑回测，返回 (engine, stats, violations)"""
    setting = setting or {"fast_window": 5, "slow_window": 20}
    bars = df_to_bars(df, symbol="600000", exchange=Exchange.SSE, interval=Interval.DAILY)
    engine = CtaBacktestingEngine()
    engine.set_parameters(
        vt_symbols=[VTSYM], interval=Interval.DAILY,
        start=datetime(2024, 1, 2), end=datetime(2024, 12, 31),
        rate=0.0003, stamp_tax_rate=0.001, size=1, pricetick=0.01, capital=capital,
    )
    engine.add_strategy(VNPY_STRATEGY_MAP[strategy_name], setting)
    for bar in bars:
        engine.dts.add(bar.datetime)
        engine.history_data[(bar.datetime, VTSYM)] = bar
    engine.strategy.on_init()

    violations = []
    original_new_bars = engine.new_bars

    def wrapped_new_bars(dt):
        original_new_bars(dt)
        # bar 末快照：撮合 + on_bars + update_daily_close 都已跑完
        if engine.cash < -1e-6:
            violations.append((dt, "cash<0", round(engine.cash, 4)))
        if engine.strategy and hasattr(engine.strategy, "pos_data"):
            for vtsym, pos in engine.strategy.pos_data.items():
                if pos < -1e-6:
                    violations.append((dt, f"pos<0 {vtsym}", pos))

    engine.new_bars = wrapped_new_bars
    engine.run_backtesting()
    stats = engine.calculate_result()
    return engine, stats, violations


@pytest.fixture
def trend_up_data():
    n = 100
    closes = [100 + i * 0.5 for i in range(n)]
    dates = [(date(2024, 1, 2) + timedelta(days=i)).strftime("%Y-%m-%d") for i in range(n)]
    return _make_df(dates, closes)


@pytest.fixture
def oscillation_long_data():
    """较长震荡行情，产生多轮买卖"""
    n = 300
    t = np.linspace(0, 8 * np.pi, n)
    closes = (100 + 15 * np.sin(t)).tolist()
    dates = [(date(2024, 1, 2) + timedelta(days=i)).strftime("%Y-%m-%d") for i in range(n)]
    return _make_df(dates, closes)


class TestInvariants:
    def test_trend_up_no_violations(self, trend_up_data):
        engine, stats, violations = _run_with_invariants(trend_up_data)
        assert violations == [], f"不变式违反: {violations}"

    def test_oscillation_no_violations(self, oscillation_long_data):
        engine, stats, violations = _run_with_invariants(oscillation_long_data)
        assert violations == [], f"不变式违反: {violations}"

    def test_crossover_no_violations(self):
        df = make_crossover_data(5, 20, n=120)
        engine, stats, violations = _run_with_invariants(df)
        assert violations == [], f"不变式违反: {violations}"

    def test_random_walk_no_violations(self):
        np.random.seed(42)
        n = 500
        rets = np.random.normal(0, 0.02, n)
        closes = [100.0]
        for r in rets[1:]:
            closes.append(closes[-1] * (1 + r))
        dates = [(date(2024, 1, 2) + timedelta(days=i)).strftime("%Y-%m-%d") for i in range(n)]
        df = _make_df(dates, closes)
        engine, stats, violations = _run_with_invariants(df)
        assert violations == [], f"不变式违反: {violations}"

    def test_cash_never_negative_full_run(self, trend_up_data):
        """全程现金不穿仓（含手续费扣除后）"""
        engine, stats, violations = _run_with_invariants(trend_up_data)
        cash_violations = [v for v in violations if v[1] == "cash<0"]
        assert cash_violations == []
        # 终点也断言一次
        assert engine.cash >= -1e-6

    def test_verification_passed_when_no_violations(self, trend_up_data):
        """无不变式违反时，引擎验算也应通过（末尾空仓或完整配对）"""
        engine, stats, violations = _run_with_invariants(trend_up_data)
        if stats:  # 有交易才验
            # 前4项必须通过
            v = stats["verification"]
            for key in ("capital_conservation", "daily_pnl_sum", "equity_consistency", "max_drawdown"):
                assert v[key]["passed"] is True, f"{key}: {v[key]}"

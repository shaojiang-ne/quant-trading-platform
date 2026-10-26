"""
回测层未来函数测试

截断区间跑 vs 全量跑，前半段交易必须完全一致。
（信号层未来函数已在 test_strategies_stability.py 测过；这里测回测引擎层 ——
 引擎有没有在 mid 之后偷看数据来改 mid 之前的成交。）

预计算模式与增量模式都跑：两模式在 NaN 边界行为可能不同，不一致是产品 bug。
"""

import pytest
from datetime import datetime, date, timedelta

vnpy = pytest.importorskip("vnpy")
import numpy as np
from vnpy.trader.constant import Exchange, Interval

from app.services.vnpy_backtest_service import CtaBacktestingEngine
from app.core.strategy_adapter import VNPY_STRATEGY_MAP
from tests.conftest import _make_df, df_to_bars

VTSYM = "600000.SSE"
SETTING = {"fast_window": 5, "slow_window": 20}


def _random_walk_df(n=1000, seed=42):
    np.random.seed(seed)
    rets = np.random.normal(0, 0.015, n)
    closes = [100.0]
    for r in rets[1:]:
        closes.append(closes[-1] * (1 + r))
    dates = [(date(2024, 1, 2) + timedelta(days=i)).strftime("%Y-%m-%d") for i in range(n)]
    return _make_df(dates, closes)


def _run(df, incremental: bool):
    bars = df_to_bars(df, symbol="600000", exchange=Exchange.SSE, interval=Interval.DAILY)
    engine = CtaBacktestingEngine()
    engine.incremental_mode = incremental
    engine.set_parameters(
        vt_symbols=[VTSYM], interval=Interval.DAILY,
        start=datetime(2024, 1, 2), end=datetime(2026, 12, 31),
        rate=0.0003, stamp_tax_rate=0.001, size=1, pricetick=0.01, capital=1_000_000.0,
    )
    engine.add_strategy(VNPY_STRATEGY_MAP["DoubleMaStrategy"], SETTING)
    for bar in bars:
        engine.dts.add(bar.datetime)
        engine.history_data[(bar.datetime, VTSYM)] = bar
    engine.strategy.on_init()
    engine.run_backtesting()
    engine.calculate_result()
    return sorted(engine.trades.values(), key=lambda t: t.vt_tradeid)


def _compare_trades(half_trades, full_trades):
    """断言 half 中每笔与 full 同 tradeid 的交易 (datetime,direction,price,volume) 完全相等"""
    full_by_id = {t.vt_tradeid: t for t in full_trades}
    mismatches = []
    for t in half_trades:
        ft = full_by_id.get(t.vt_tradeid)
        if ft is None:
            mismatches.append((t.vt_tradeid, "not in full"))
            continue
        if (t.datetime, t.direction, t.price, t.volume) != \
           (ft.datetime, ft.direction, ft.price, ft.volume):
            mismatches.append((t.vt_tradeid,
                               f"half={(t.datetime, t.direction, t.price, t.volume)} "
                               f"full={(ft.datetime, ft.direction, ft.price, ft.volume)}"))
    return mismatches


class TestNoLookAheadPrecompute:
    """预计算模式：无未来函数"""

    def test_first_half_matches_full(self):
        df = _random_walk_df(1000)
        full = _run(df, incremental=False)
        half = _run(df.iloc[:500], incremental=False)
        assert len(half) > 0, "前半段应有交易"
        mismatches = _compare_trades(half, full)
        assert mismatches == [], f"前半段交易与全量不一致（未来函数）: {mismatches[:3]}"


class TestNoLookAheadIncremental:
    """增量模式：无未来函数"""

    def test_first_half_matches_full(self):
        df = _random_walk_df(1000)
        full = _run(df, incremental=True)
        half = _run(df.iloc[:500], incremental=True)
        assert len(half) > 0
        mismatches = _compare_trades(half, full)
        assert mismatches == [], f"前半段交易与全量不一致（未来函数）: {mismatches[:3]}"


class TestModeConsistency:
    """预计算 vs 增量：交易笔数与每笔内容应一致"""

    def test_both_modes_same_trades(self):
        df = _random_walk_df(1000)
        pre = _run(df, incremental=False)
        inc = _run(df, incremental=True)
        assert len(pre) == len(inc), (
            f"两模式交易笔数不一致: precompute={len(pre)}, incremental={len(inc)}"
        )
        # 按 tradeid 配对比较
        pre_by_id = {t.vt_tradeid: t for t in pre}
        mismatches = []
        for t in inc:
            pt = pre_by_id.get(t.vt_tradeid)
            if pt is None:
                mismatches.append((t.vt_tradeid, "not in precompute"))
            elif (t.datetime, t.direction, t.price, t.volume) != \
                 (pt.datetime, pt.direction, pt.price, pt.volume):
                mismatches.append((t.vt_tradeid, "content differs"))
        assert mismatches == [], f"两模式交易内容不一致: {mismatches[:3]}"

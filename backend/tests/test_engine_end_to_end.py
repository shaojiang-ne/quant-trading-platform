"""
引擎全链路测试 — CtaBacktestingEngine 端到端

注入合成日K → run_backtesting → calculate_result → 验证统计字段语义正确 +
verification 5 项验算（完整买卖配对场景下应全过）。

不依赖真实行情，零网络。
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


def _inject_and_run(df, strategy_name="DoubleMaStrategy", setting=None,
                    capital=1_000_000.0, incremental=False):
    """注入 DataFrame → 跑回测 → 返回 (engine, stats)"""
    setting = setting or {"fast_window": 5, "slow_window": 20}
    bars = df_to_bars(df, symbol="600000", exchange=Exchange.SSE, interval=Interval.DAILY)
    engine = CtaBacktestingEngine()
    engine.incremental_mode = incremental
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
    engine.run_backtesting()
    stats = engine.calculate_result()
    return engine, stats


def _full_cycle_data(n=120, seed=0):
    """先跌→涨→跌，必然产生金叉+死叉，末尾空仓（完整买卖配对）"""
    np.random.seed(seed)
    down = [100 - i * 0.3 for i in range(40)]
    up = [down[-1] + i * 0.4 for i in range(40)]
    down2 = [up[-1] - i * 0.5 for i in range(40)]
    closes = down + up + down2
    dates = [(date(2024, 1, 2) + timedelta(days=i)).strftime("%Y-%m-%d") for i in range(n)]
    return _make_df(dates, closes)


# ── 完整买卖配对场景 ────────────────────────────────────────────────────

class TestFullCycleEndToEnd:
    def test_stats_fields_semantics(self):
        """统计字段语义正确"""
        df = _full_cycle_data()
        engine, stats = _inject_and_run(df)
        assert stats, "有交易时 calculate_result 不应返回空"
        assert stats["total_trades"] > 0
        assert stats["total_trades"] % 2 == 0  # 买卖配对
        assert 0.0 <= stats["win_rate"] <= 1.0
        assert stats["max_drawdown"] >= 0.0
        assert len(stats["daily_results"]) <= len(df)
        # 首日 equity == 初始资金
        assert abs(stats["daily_results"][0]["equity"] - 1_000_000) < 1e-6
        assert stats["daily_results"][0]["return"] == 0.0

    def test_final_assets_consistency(self):
        """final_cash + final_position_value ≈ capital + total_profit（容差 1 元）"""
        df = _full_cycle_data()
        engine, stats = _inject_and_run(df, capital=1_000_000.0)
        total_assets = stats["final_cash"] + stats["final_position_value"]
        assert abs(total_assets - (1_000_000.0 + stats["total_profit"])) < 1.0

    def test_trades_structure(self):
        """trades 每项字段完整，side ∈ {buy,sell}"""
        df = _full_cycle_data()
        engine, stats = _inject_and_run(df)
        assert stats["trades"]
        for t in stats["trades"]:
            assert "date" in t and "symbol" in t and "side" in t
            assert "price" in t and "quantity" in t
            assert t["side"] in ("buy", "sell")
            assert t["price"] > 0 and t["quantity"] > 0

    def test_verification_all_passed(self):
        """完整买卖配对（末尾空仓）→ verification 5 项全过"""
        df = _full_cycle_data()
        engine, stats = _inject_and_run(df)
        v = stats["verification"]
        for key in ("capital_conservation", "daily_pnl_sum", "equity_consistency",
                    "max_drawdown", "trade_pnl_consistency"):
            assert v[key]["passed"] is True, f"{key} 未通过: {v[key]}"
        assert v["overall"]["passed"] is True
        assert v["overall"]["failed_items"] == []
        assert engine.verification_failed is False

    def test_no_position_at_end(self):
        """完整配对数据末尾应空仓（holding=0）"""
        df = _full_cycle_data()
        engine, stats = _inject_and_run(df)
        assert stats["final_position_quantity"] == 0
        assert stats["final_position_value"] == 0.0


# ── 无信号场景 ──────────────────────────────────────────────────────────

class TestNoSignalScenario:
    def test_constant_price_no_trades(self):
        """价格不变 → 无信号 → 无交易"""
        df = _make_df([(date(2024, 1, 2) + timedelta(days=i)).strftime("%Y-%m-%d")
                       for i in range(60)], [100.0] * 60)
        engine, stats = _inject_and_run(df)
        # 无交易时 calculate_result 返回 {}（引擎对无交易的处理）
        assert stats == {} or stats.get("total_trades", 0) == 0
        assert engine.verification_failed is False


# ── 单边持仓场景（末尾有持仓，验算第5项已知行为）──────────────────────────

class TestOpenPositionScenario:
    def test_first_four_checks_pass_with_open_position(self):
        """末尾有持仓时，前4项验算应通过（trade_pnl_consistency 第5项有已知缺陷，另测）"""
        # crossover 80 根：只金叉不死叉，末尾持仓
        df = make_crossover_data(5, 20, n=80)
        engine, stats = _inject_and_run(df)
        assert stats, "应有交易（买入）"
        assert stats["total_trades"] >= 1
        v = stats["verification"]
        # 前4项必须通过
        for key in ("capital_conservation", "daily_pnl_sum", "equity_consistency", "max_drawdown"):
            assert v[key]["passed"] is True, f"{key} 应通过: {v[key]}"


# ── 增量 vs 预计算模式一致性 ─────────────────────────────────────────────

class TestIncrementalVsPrecompute:
    def test_both_modes_produce_same_trade_count(self):
        """增量模式与预计算模式交易次数应一致"""
        df = _full_cycle_data()
        _, stats_inc = _inject_and_run(df, incremental=True)
        _, stats_pre = _inject_and_run(df, incremental=False)
        assert stats_inc["total_trades"] == stats_pre["total_trades"]
        assert stats_inc["total_return"] == stats_pre["total_return"]

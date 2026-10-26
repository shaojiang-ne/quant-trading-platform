"""
验算器测试 — _verify_result + verification_failed 属性

引擎内建 5 项验算（资金守恒/逐日盈亏求和/权益曲线一致/最大回撤重算/逐笔盈亏汇总）。
测试：
- 正常（完整买卖配对）→ 5 项全过，verification_failed=False
- 破坏数据（删 trade / 改 price）→ 对应项变红，verification_failed=True
- 已知缺陷：末尾有持仓时 trade_pnl_consistency 会误报（持仓浮盈未扣佣金），如实记录
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


def _full_cycle_data(n=120, seed=0):
    np.random.seed(seed)
    down = [100 - i * 0.3 for i in range(40)]
    up = [down[-1] + i * 0.4 for i in range(40)]
    down2 = [up[-1] - i * 0.5 for i in range(40)]
    closes = down + up + down2
    dates = [(date(2024, 1, 2) + timedelta(days=i)).strftime("%Y-%m-%d") for i in range(n)]
    return _make_df(dates, closes)


def _run_to_backtest(df, capital=1_000_000.0):
    """跑到 run_backtesting 为止，不调 calculate_result（留待破坏 trades 后再算）"""
    bars = df_to_bars(df, symbol="600000", exchange=Exchange.SSE, interval=Interval.DAILY)
    engine = CtaBacktestingEngine()
    engine.set_parameters(
        vt_symbols=[VTSYM], interval=Interval.DAILY,
        start=datetime(2024, 1, 2), end=datetime(2024, 12, 31),
        rate=0.0003, stamp_tax_rate=0.001, size=1, pricetick=0.01, capital=capital,
    )
    engine.add_strategy(VNPY_STRATEGY_MAP["DoubleMaStrategy"], {"fast_window": 5, "slow_window": 20})
    for bar in bars:
        engine.dts.add(bar.datetime)
        engine.history_data[(bar.datetime, VTSYM)] = bar
    engine.strategy.on_init()
    engine.run_backtesting()
    return engine


def _run_engine(df, capital=1_000_000.0):
    """完整跑：run_backtesting + calculate_result"""
    engine = _run_to_backtest(df, capital)
    stats = engine.calculate_result()
    return engine, stats


class TestNormalPasses:
    def test_all_five_checks_pass(self):
        """完整买卖配对（末尾空仓）→ 5 项验算全过"""
        engine, stats = _run_engine(_full_cycle_data())
        v = stats["verification"]
        for key in ("capital_conservation", "daily_pnl_sum", "equity_consistency",
                    "max_drawdown", "trade_pnl_consistency"):
            assert v[key]["passed"] is True, f"{key} 未通过: {v[key]}"
        assert v["overall"]["passed"] is True
        assert v["overall"]["failed_items"] == []
        assert engine.verification_failed is False


class TestTamperingDetected:
    def test_delete_trade_detected(self):
        """删一笔 trade → 验算失败 + verification_failed=True"""
        engine = _run_to_backtest(_full_cycle_data())
        # 在 calculate_result 之前删一笔 trade
        tid = list(engine.trades.keys())[0]
        del engine.trades[tid]
        stats = engine.calculate_result()

        v = stats["verification"]
        assert v["overall"]["passed"] is False
        assert engine.verification_failed is True
        # 至少 equity_consistency / trade_pnl_consistency 之一应检出
        assert "equity_consistency" in v["overall"]["failed_items"] or \
               "trade_pnl_consistency" in v["overall"]["failed_items"]

    def test_modify_trade_price_detected(self):
        """改一笔 trade.price → 验算失败"""
        engine = _run_to_backtest(_full_cycle_data())
        tid = list(engine.trades.keys())[0]
        original_price = engine.trades[tid].price
        engine.trades[tid].price = original_price * 2  # 篡改成交价
        stats = engine.calculate_result()

        v = stats["verification"]
        assert v["overall"]["passed"] is False
        assert engine.verification_failed is True
        assert "equity_consistency" in v["overall"]["failed_items"] or \
               "trade_pnl_consistency" in v["overall"]["failed_items"]


class TestKnownLimitation:
    """末尾持仓时 trade_pnl_consistency 修复后应通过

    原缺陷：holding_pnl 用成交价当成本(未扣佣金)，reported_profit 扣过佣金，
    两者差一笔佣金，tolerance*2=2.0 扛不住大额佣金 → 误报。
    修复：holding_pnl 的 avg_cost 摊入买入佣金，tolerance 按佣金规模调宽。
    """

    def test_open_position_trade_pnl_consistency_passes_after_fix(self):
        """末尾有持仓(只买未卖) → 5项验算全过(含第5项)"""
        df = make_crossover_data(5, 20, n=80)
        engine, stats = _run_engine(df)
        v = stats["verification"]
        for key in ("capital_conservation", "daily_pnl_sum", "equity_consistency",
                    "max_drawdown", "trade_pnl_consistency"):
            assert v[key]["passed"] is True, f"{key} 应通过: {v[key]}"
        assert v["overall"]["passed"] is True
        assert engine.verification_failed is False

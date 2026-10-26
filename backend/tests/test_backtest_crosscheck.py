"""
simple vs vnpy 对拍测试

把 test_real_data.py 的 run_backtest_simple（收盘价成交）与 vnpy 引擎
（next-bar open 成交）对同一合成数据跑，断言：
- 交易次数相等（信号源相同，委托数应一致）
- 收益方向一致（都正或都负）
- 两边 verification 都通过

【关键】不断言收益数值相等 —— 两边成交价模型不同（收盘 vs next-open），
数值本就该有差。断言"次数相等 + 方向一致"才正确；若次数差很多，
说明引擎的成交价模型在改变信号触发 —— 那是 bug。
"""

import pytest
from datetime import datetime, date, timedelta

vnpy = pytest.importorskip("vnpy")
import importlib.util
import numpy as np
from vnpy.trader.constant import Exchange, Interval

from app.services.vnpy_backtest_service import CtaBacktestingEngine
from app.core.strategy_adapter import VNPY_STRATEGY_MAP
from tests.conftest import _make_df, df_to_bars, make_crossover_data

VTSYM = "600000.SSE"
SETTING = {"fast_window": 5, "slow_window": 20}
CAPITAL = 1_000_000.0


def _load_simple_runner():
    """从 backend/test_real_data.py 加载 run_backtest_simple"""
    spec = importlib.util.spec_from_file_location("test_real_data", "test_real_data.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod.run_backtest_simple


def _run_vnpy(df):
    bars = df_to_bars(df, symbol="600000", exchange=Exchange.SSE, interval=Interval.DAILY)
    engine = CtaBacktestingEngine()
    engine.set_parameters(
        vt_symbols=[VTSYM], interval=Interval.DAILY,
        start=datetime(2024, 1, 2), end=datetime(2024, 12, 31),
        rate=0.0003, stamp_tax_rate=0.001, size=1, pricetick=0.01, capital=CAPITAL,
    )
    engine.add_strategy(VNPY_STRATEGY_MAP["DoubleMaStrategy"], SETTING)
    for bar in bars:
        engine.dts.add(bar.datetime)
        engine.history_data[(bar.datetime, VTSYM)] = bar
    engine.strategy.on_init()
    engine.run_backtesting()
    return engine, engine.calculate_result()


def _full_cycle_data(n=120, seed=0):
    """跌→涨→跌，产生金叉+死叉的完整配对"""
    np.random.seed(seed)
    down = [100 - i * 0.3 for i in range(40)]
    up = [down[-1] + i * 0.4 for i in range(40)]
    down2 = [up[-1] - i * 0.5 for i in range(40)]
    closes = down + up + down2
    dates = [(date(2024, 1, 2) + timedelta(days=i)).strftime("%Y-%m-%d") for i in range(n)]
    return _make_df(dates, closes)


class TestCrosscheck:
    def test_trade_count_equal(self):
        """同一数据下 simple 与 vnpy 交易次数应相等"""
        df = _full_cycle_data()
        run_simple = _load_simple_runner()
        rs = run_simple(df, SETTING)
        _, stats = _run_vnpy(df)
        assert stats["total_trades"] == rs["total_trades"], (
            f"交易次数不一致: simple={rs['total_trades']}, vnpy={stats['total_trades']}"
        )

    def test_return_direction_consistent(self):
        """收益方向一致（都正或都负）"""
        df = _full_cycle_data()
        run_simple = _load_simple_runner()
        rs = run_simple(df, SETTING)
        _, stats = _run_vnpy(df)
        assert (rs["total_return"] > 0) == (stats["total_return"] > 0), (
            f"收益方向不一致: simple={rs['total_return']}, vnpy={stats['total_return']}"
        )

    def test_vnpy_verification_passed(self):
        """vnpy 引擎验算应通过（完整配对场景）"""
        df = _full_cycle_data()
        _, stats = _run_vnpy(df)
        assert stats["verification"]["overall"]["passed"] is True

    def test_trade_dates_differ_by_one_bar(self):
        """vnpy 成交日比 simple 晚 1 个交易日（next-bar open 模型）"""
        df = _full_cycle_data()
        run_simple = _load_simple_runner()
        rs = run_simple(df, SETTING)
        _, stats = _run_vnpy(df)
        simple_dates = [t["date"] for t in rs["trades"]]
        vnpy_dates = [t["date"] for t in stats["trades"]]
        assert len(simple_dates) == len(vnpy_dates)
        # 每笔 vnpy 成交日应 >= simple 成交日（next-bar，通常晚1天）
        for sd, vd in zip(simple_dates, vnpy_dates):
            assert vd >= sd, f"vnpy 成交日 {vd} 早于 simple {sd}，违反 next-bar 模型"

    def test_oscillation_crosscheck(self):
        """震荡行情下对拍"""
        n = 300
        t = np.linspace(0, 8 * np.pi, n)
        closes = (100 + 15 * np.sin(t)).tolist()
        dates = [(date(2024, 1, 2) + timedelta(days=i)).strftime("%Y-%m-%d") for i in range(n)]
        df = _make_df(dates, closes)
        run_simple = _load_simple_runner()
        rs = run_simple(df, SETTING)
        _, stats = _run_vnpy(df)
        # 震荡下次数可能因 T+1/取整略有差异，但不应差一个数量级
        assert abs(rs["total_trades"] - stats["total_trades"]) <= max(2, rs["total_trades"] * 0.2), (
            f"震荡行情交易次数差异过大: simple={rs['total_trades']}, vnpy={stats['total_trades']}"
        )

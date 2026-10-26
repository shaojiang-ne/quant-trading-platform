"""
稳定性测试

验证策略在长序列、重复计算、信号范围等方面的稳定性。
"""

import numpy as np
import pandas as pd
import pytest

from app.strategies.base import (
    DoubleMaStrategy, MacdStrategy, BollingerStrategy, RsiStrategy,
    TurtleStrategy, KdjStrategy, CciStrategy, TripleMaStrategy,
    EmaCrossStrategy, VolumeMaStrategy, MomentumStrategy,
    AtrChannelStrategy, DualThrustStrategy, GridStrategy,
)

STANDARD_STRATEGIES = [
    DoubleMaStrategy, MacdStrategy, BollingerStrategy, RsiStrategy,
    TurtleStrategy, KdjStrategy, CciStrategy, TripleMaStrategy,
    EmaCrossStrategy, VolumeMaStrategy, MomentumStrategy,
    AtrChannelStrategy, DualThrustStrategy,
]

DEFAULT_SETTINGS = {
    "DoubleMaStrategy": {"fast_window": 5, "slow_window": 20},
    "MacdStrategy": {"fast_period": 12, "slow_period": 26, "signal_period": 9},
    "BollingerStrategy": {"boll_window": 20, "boll_dev": 2.0},
    "RsiStrategy": {"rsi_window": 14, "rsi_overbought": 70, "rsi_oversold": 30},
    "TurtleStrategy": {"entry_window": 20, "exit_window": 10},
    "KdjStrategy": {"kdj_window": 9, "k_smooth": 3, "d_smooth": 3},
    "CciStrategy": {"cci_window": 14, "cci_overbought": 100, "cci_oversold": -100},
    "TripleMaStrategy": {"fast_window": 5, "mid_window": 20, "slow_window": 60},
    "EmaCrossStrategy": {"fast_window": 12, "slow_window": 26},
    "VolumeMaStrategy": {"ma_window": 20, "vol_window": 20, "vol_ratio": 1.5},
    "MomentumStrategy": {"mom_window": 10, "mom_threshold": 0.03, "ma_window": 20},
    "AtrChannelStrategy": {"atr_window": 14, "atr_mult": 2.0, "ma_window": 20},
    "DualThrustStrategy": {"n_window": 4, "k_up": 0.5, "k_down": 0.5},
    "GridStrategy": {"grid_size": 0.02, "grid_quantity": 100, "initial_position": 0},
}


def _make_df(closes: list[float], volumes: list[float] = None) -> pd.DataFrame:
    from tests.conftest import _make_df
    from datetime import date, timedelta
    n = len(closes)
    dates = [(date(2024, 1, 2) + timedelta(days=i)).strftime("%Y-%m-%d") for i in range(n)]
    return _make_df(dates, closes, volumes=volumes)


def _make_random_data(n: int = 1000, seed: int = 42) -> pd.DataFrame:
    np.random.seed(seed)
    returns = np.random.normal(0, 0.015, n)
    closes = [100.0]
    for r in returns[1:]:
        closes.append(closes[-1] * (1 + r))
    volumes = [10000 + abs(np.random.normal(0, 3000)) for _ in range(n)]
    return _make_df(closes, volumes=volumes)


# ── 长序列不崩溃 ──────────────────────────────────────────────────────

class TestLongSequence:
    @pytest.mark.parametrize("strategy_cls", STANDARD_STRATEGIES)
    def test_1000_bars_no_crash(self, strategy_cls):
        name = strategy_cls.__name__
        setting = DEFAULT_SETTINGS[name]
        df = _make_random_data(1000)
        result = strategy_cls.generate_signals(df, setting)
        if isinstance(result, tuple):
            result = result[0]
        assert len(result) == 1000

    def test_grid_1000_bars_no_crash(self):
        df = _make_random_data(1000)
        signals, grid_states = GridStrategy.generate_signals(
            df, DEFAULT_SETTINGS["GridStrategy"]
        )
        assert len(signals) == 1000


# ── 信号值范围 ────────────────────────────────────────────────────────

class TestSignalRange:
    @pytest.mark.parametrize("strategy_cls", STANDARD_STRATEGIES)
    def test_signal_values_in_valid_range(self, strategy_cls):
        """标准策略信号值必须 ∈ {-1, 0, 1}"""
        name = strategy_cls.__name__
        setting = DEFAULT_SETTINGS[name]
        df = _make_random_data(500)
        result = strategy_cls.generate_signals(df, setting)
        if isinstance(result, tuple):
            result = result[0]
        valid = result.dropna()
        assert set(valid.unique()).issubset({-1, 0, 1}), \
            f"{name} 信号值超出范围: {sorted(valid.unique())}"

    def test_grid_signal_values_are_integers(self):
        """Grid策略信号值应为整数"""
        df = _make_random_data(500)
        signals, _ = GridStrategy.generate_signals(
            df, DEFAULT_SETTINGS["GridStrategy"]
        )
        valid = signals.dropna()
        # Grid信号值可以是任意整数（穿越层数），但不应是浮点
        assert all(float(v).is_integer() for v in valid), \
            "Grid策略信号值应为整数"


# ── 无未来函数 ────────────────────────────────────────────────────────

class TestNoLookAhead:
    @pytest.mark.parametrize("strategy_cls", STANDARD_STRATEGIES)
    def test_no_future_data_leak(self, strategy_cls):
        """用前N根bar计算的信号，与用全部数据计算的前N个信号一致"""
        name = strategy_cls.__name__
        setting = DEFAULT_SETTINGS[name]
        df = _make_random_data(200)

        # 全量计算
        full_result = strategy_cls.generate_signals(df, setting)
        if isinstance(full_result, tuple):
            full_result = full_result[0]

        # 用前100根bar计算
        df_partial = df.iloc[:100].reset_index(drop=True)
        partial_result = strategy_cls.generate_signals(df_partial, setting)
        if isinstance(partial_result, tuple):
            partial_result = partial_result[0]

        # 前100个信号必须一致
        for i in range(100):
            full_val = full_result.iloc[i]
            partial_val = partial_result.iloc[i]
            # NaN 视为相等
            if pd.isna(full_val) and pd.isna(partial_val):
                continue
            assert full_val == partial_val, \
                f"{name} bar[{i}] 存在未来函数: full={full_val}, partial={partial_val}"

    def test_grid_no_future_data_leak(self):
        df = _make_random_data(200)
        setting = DEFAULT_SETTINGS["GridStrategy"]

        full_signals, _ = GridStrategy.generate_signals(df, setting)
        df_partial = df.iloc[:100].reset_index(drop=True)
        partial_signals, _ = GridStrategy.generate_signals(df_partial, setting)

        for i in range(100):
            full_val = full_signals.iloc[i]
            partial_val = partial_signals.iloc[i]
            if pd.isna(full_val) and pd.isna(partial_val):
                continue
            assert full_val == partial_val, \
                f"Grid bar[{i}] 存在未来函数: full={full_val}, partial={partial_val}"


# ── 幂等性 ────────────────────────────────────────────────────────────

class TestIdempotency:
    @pytest.mark.parametrize("strategy_cls", STANDARD_STRATEGIES)
    def test_repeated_calculation_identical(self, strategy_cls):
        """对同一份数据调用两次 generate_signals，结果完全一致"""
        name = strategy_cls.__name__
        setting = DEFAULT_SETTINGS[name]
        df = _make_random_data(200)

        result1 = strategy_cls.generate_signals(df, setting)
        result2 = strategy_cls.generate_signals(df, setting)

        if isinstance(result1, tuple):
            result1 = result1[0]
        if isinstance(result2, tuple):
            result2 = result2[0]

        pd.testing.assert_series_equal(result1, result2)

    def test_grid_repeated_calculation_identical(self):
        df = _make_random_data(200)
        setting = DEFAULT_SETTINGS["GridStrategy"]

        signals1, states1 = GridStrategy.generate_signals(df, setting)
        signals2, states2 = GridStrategy.generate_signals(df, setting)

        pd.testing.assert_series_equal(signals1, signals2)


# ── 不同随机种子 ──────────────────────────────────────────────────────

class TestDifferentSeeds:
    @pytest.mark.parametrize("strategy_cls", STANDARD_STRATEGIES)
    def test_different_seed_no_crash(self, strategy_cls):
        """不同随机种子下策略不应崩溃"""
        name = strategy_cls.__name__
        setting = DEFAULT_SETTINGS[name]
        for seed in [0, 1, 123, 999]:
            df = _make_random_data(300, seed=seed)
            result = strategy_cls.generate_signals(df, setting)
            if isinstance(result, tuple):
                result = result[0]
            assert len(result) == 300, f"{name} seed={seed} 结果长度异常"

    def test_grid_different_seed_no_crash(self):
        setting = DEFAULT_SETTINGS["GridStrategy"]
        for seed in [0, 1, 123, 999]:
            df = _make_random_data(300, seed=seed)
            signals, _ = GridStrategy.generate_signals(df, setting)
            assert len(signals) == 300, f"Grid seed={seed} 结果长度异常"

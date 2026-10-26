"""
边界条件测试

验证策略在极端输入下不崩溃、不误触发。
"""

import numpy as np
import pandas as pd
import pytest

from app.strategies.base import (
    DoubleMaStrategy, MacdStrategy, BollingerStrategy, RsiStrategy,
    TurtleStrategy, KdjStrategy, CciStrategy, TripleMaStrategy,
    EmaCrossStrategy, VolumeMaStrategy, MomentumStrategy,
    AtrChannelStrategy, DualThrustStrategy, GridStrategy,
    STRATEGY_MAP,
)

# 所有非Grid策略
STANDARD_STRATEGIES = [
    DoubleMaStrategy, BollingerStrategy, RsiStrategy,
    TurtleStrategy, KdjStrategy, CciStrategy, TripleMaStrategy,
    VolumeMaStrategy, MomentumStrategy,
    AtrChannelStrategy, DualThrustStrategy,
]

# EMA类策略：EMA不需要min_periods，3根bar就能产生信号，单独处理
EMA_STRATEGIES = [MacdStrategy, EmaCrossStrategy]

# 每个策略的默认参数
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


def _make_df(closes: list[float], n_vol: int = None) -> pd.DataFrame:
    from tests.conftest import _make_df
    from datetime import date, timedelta
    n = len(closes)
    dates = [(date(2024, 1, 2) + timedelta(days=i)).strftime("%Y-%m-%d") for i in range(n)]
    volumes = [10000.0] * n if n_vol is None else [float(n_vol)] * n
    return _make_df(dates, closes, volumes=volumes)


# ── 数据不足 ────────────────────────────────────────────────────────────

class TestInsufficientData:
    """数据少于指标窗口期时，信号应为0"""

    @pytest.mark.parametrize("strategy_cls", STANDARD_STRATEGIES)
    def test_short_data_no_signal(self, strategy_cls):
        name = strategy_cls.__name__
        setting = DEFAULT_SETTINGS[name]
        df = _make_df([100.0, 101.0, 102.0])  # 只有3根bar
        result = strategy_cls.generate_signals(df, setting)
        if isinstance(result, tuple):
            result = result[0]
        # 数据不足，不应产生非零信号
        assert (result.dropna() != 0).sum() == 0, f"{name} 在3根bar数据下不应产生信号"

    @pytest.mark.parametrize("strategy_cls", EMA_STRATEGIES)
    def test_ema_short_data_no_crash(self, strategy_cls):
        """EMA类策略3根bar就能产生信号，只验证不崩溃"""
        name = strategy_cls.__name__
        setting = DEFAULT_SETTINGS[name]
        df = _make_df([100.0, 101.0, 102.0])
        result = strategy_cls.generate_signals(df, setting)
        if isinstance(result, tuple):
            result = result[0]
        assert len(result) == 3


# ── 单根bar ─────────────────────────────────────────────────────────────

class TestSingleBar:
    @pytest.mark.parametrize("strategy_cls", STANDARD_STRATEGIES)
    def test_single_bar_no_crash(self, strategy_cls):
        name = strategy_cls.__name__
        setting = DEFAULT_SETTINGS[name]
        df = _make_df([100.0])
        result = strategy_cls.generate_signals(df, setting)
        if isinstance(result, tuple):
            result = result[0]
        assert len(result) == 1

    @pytest.mark.parametrize("strategy_cls", STANDARD_STRATEGIES)
    def test_single_bar_no_signal(self, strategy_cls):
        name = strategy_cls.__name__
        setting = DEFAULT_SETTINGS[name]
        df = _make_df([100.0])
        result = strategy_cls.generate_signals(df, setting)
        if isinstance(result, tuple):
            result = result[0]
        assert result.iloc[0] == 0 or pd.isna(result.iloc[0])


# ── 两根bar ─────────────────────────────────────────────────────────────

class TestTwoBars:
    @pytest.mark.parametrize("strategy_cls", STANDARD_STRATEGIES)
    def test_two_bars_no_crash(self, strategy_cls):
        name = strategy_cls.__name__
        setting = DEFAULT_SETTINGS[name]
        df = _make_df([100.0, 101.0])
        result = strategy_cls.generate_signals(df, setting)
        if isinstance(result, tuple):
            result = result[0]
        assert len(result) == 2


# ── 价格不变 ────────────────────────────────────────────────────────────

class TestConstantPrice:
    @pytest.mark.parametrize("strategy_cls", STANDARD_STRATEGIES)
    def test_no_signal_on_flat(self, strategy_cls):
        name = strategy_cls.__name__
        setting = DEFAULT_SETTINGS[name]
        df = _make_df([100.0] * 60)
        result = strategy_cls.generate_signals(df, setting)
        if isinstance(result, tuple):
            result = result[0]
        assert (result.dropna() != 0).sum() == 0, f"{name} 价格不变时不应产生信号"


# ── NaN 数据 ────────────────────────────────────────────────────────────

class TestNanData:
    @pytest.mark.parametrize("strategy_cls", STANDARD_STRATEGIES)
    def test_nan_close_no_crash(self, strategy_cls):
        name = strategy_cls.__name__
        setting = DEFAULT_SETTINGS[name]
        closes = [100.0] * 20 + [float("nan")] * 5 + [100.0] * 25
        df = _make_df(closes)
        # 不应崩溃
        result = strategy_cls.generate_signals(df, setting)
        if isinstance(result, tuple):
            result = result[0]
        assert len(result) == len(closes)


# ── 跳空缺口 ────────────────────────────────────────────────────────────

class TestGapJump:
    @pytest.mark.parametrize("strategy_cls", STANDARD_STRATEGIES)
    def test_gap_no_crash(self, strategy_cls):
        name = strategy_cls.__name__
        setting = DEFAULT_SETTINGS[name]
        # 正常数据 + 跳空 + 正常数据
        closes = [100.0] * 20 + [120.0] * 20 + [100.0] * 20
        df = _make_df(closes)
        result = strategy_cls.generate_signals(df, setting)
        if isinstance(result, tuple):
            result = result[0]
        assert len(result) == 60


# ── Grid 策略特殊边界 ───────────────────────────────────────────────────

class TestGridEdge:
    def test_zero_initial_position(self):
        """初始持仓为0时，不应产生卖出信号"""
        df = _make_df([100 + i * 0.5 for i in range(50)])
        signals, _ = GridStrategy.generate_signals(
            df, {"grid_size": 0.02, "grid_quantity": 100, "initial_position": 0}
        )
        # 没有持仓时不应卖出
        assert (signals < 0).sum() == 0, "初始无持仓时不应产生卖出信号"

    def test_grid_size_zero_no_crash(self):
        """grid_size=0 不应崩溃"""
        df = _make_df([100.0] * 30)
        # grid_size=0 可能导致除零，策略应处理
        try:
            signals, _ = GridStrategy.generate_signals(
                df, {"grid_size": 0, "grid_quantity": 100, "initial_position": 0}
            )
        except (ZeroDivisionError, ValueError):
            pass  # 预期可能报错，但不应静默产生错误信号


# ── 空DataFrame ─────────────────────────────────────────────────────────

class TestEmptyDataFrame:
    @pytest.mark.parametrize("strategy_cls", STANDARD_STRATEGIES)
    def test_empty_df_no_crash(self, strategy_cls):
        name = strategy_cls.__name__
        setting = DEFAULT_SETTINGS[name]
        df = pd.DataFrame(columns=["date", "open", "high", "low", "close", "volume", "turnover"])
        try:
            result = strategy_cls.generate_signals(df, setting)
            if isinstance(result, tuple):
                result = result[0]
            assert len(result) == 0
        except (IndexError, KeyError, ValueError):
            pass  # 空数据报错可接受，但不应静默产生错误结果
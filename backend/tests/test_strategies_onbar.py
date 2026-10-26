"""
批量/增量一致性测试

验证 generate_signals() 批量计算和 on_bar() 逐根增量计算产生完全一致的信号序列。
这是最关键的测试，之前出过 bug（增量模式与批量模式不一致）。
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


def _run_onbar(strategy_cls, df: pd.DataFrame, setting: dict):
    """用 on_bar 逐根增量计算信号序列"""
    strategy = strategy_cls(setting)
    signals = []
    for _, row in df.iterrows():
        bar = row.to_dict()
        if hasattr(bar["date"], "strftime"):
            bar["date"] = bar["date"].strftime("%Y-%m-%d")
        else:
            bar["date"] = str(bar["date"])[:10]
        sig = strategy.on_bar(bar)
        signals.append(sig)
    return signals


def _get_batch_signals(strategy_cls, df: pd.DataFrame, setting: dict):
    """用 generate_signals 批量计算信号序列"""
    result = strategy_cls.generate_signals(df, setting)
    if isinstance(result, tuple):
        return result[0]
    return result


def _make_test_data(n: int = 200, seed: int = 42):
    """构造测试用K线数据"""
    from tests.conftest import _make_df
    from datetime import date, timedelta
    np.random.seed(seed)
    returns = np.random.normal(0, 0.015, n)
    closes = [100.0]
    for r in returns[1:]:
        closes.append(closes[-1] * (1 + r))
    dates = [(date(2024, 1, 2) + timedelta(days=i)).strftime("%Y-%m-%d") for i in range(n)]
    volumes = [10000 + abs(np.random.normal(0, 3000)) for _ in range(n)]
    return _make_df(dates, closes, volumes=volumes)


# ── 逐策略测试 ──────────────────────────────────────────────────────────

class TestDoubleMaOnBar:
    def test_consistency(self):
        df = _make_test_data(200)
        setting = {"fast_window": 5, "slow_window": 20}
        batch = _get_batch_signals(DoubleMaStrategy, df, setting)
        incremental = _run_onbar(DoubleMaStrategy, df, setting)
        for i in range(len(df)):
            assert incremental[i] == int(batch.iloc[i]), \
                f"DoubleMa bar[{i}] 不一致: on_bar={incremental[i]}, batch={int(batch.iloc[i])}"


class TestMacdOnBar:
    def test_consistency(self):
        df = _make_test_data(200)
        setting = {"fast_period": 12, "slow_period": 26, "signal_period": 9}
        batch = _get_batch_signals(MacdStrategy, df, setting)
        incremental = _run_onbar(MacdStrategy, df, setting)
        for i in range(len(df)):
            assert incremental[i] == int(batch.iloc[i]), \
                f"MACD bar[{i}] 不一致: on_bar={incremental[i]}, batch={int(batch.iloc[i])}"


class TestBollingerOnBar:
    def test_consistency(self):
        df = _make_test_data(200)
        setting = {"boll_window": 20, "boll_dev": 2.0}
        batch = _get_batch_signals(BollingerStrategy, df, setting)
        incremental = _run_onbar(BollingerStrategy, df, setting)
        for i in range(len(df)):
            assert incremental[i] == int(batch.iloc[i]), \
                f"Bollinger bar[{i}] 不一致: on_bar={incremental[i]}, batch={int(batch.iloc[i])}"


class TestRsiOnBar:
    def test_consistency(self):
        df = _make_test_data(200)
        setting = {"rsi_window": 14, "rsi_overbought": 70, "rsi_oversold": 30}
        batch = _get_batch_signals(RsiStrategy, df, setting)
        incremental = _run_onbar(RsiStrategy, df, setting)
        for i in range(len(df)):
            assert incremental[i] == int(batch.iloc[i]), \
                f"RSI bar[{i}] 不一致: on_bar={incremental[i]}, batch={int(batch.iloc[i])}"


class TestTurtleOnBar:
    def test_consistency(self):
        df = _make_test_data(200)
        setting = {"entry_window": 20, "exit_window": 10}
        batch = _get_batch_signals(TurtleStrategy, df, setting)
        incremental = _run_onbar(TurtleStrategy, df, setting)
        for i in range(len(df)):
            assert incremental[i] == int(batch.iloc[i]), \
                f"Turtle bar[{i}] 不一致: on_bar={incremental[i]}, batch={int(batch.iloc[i])}"


class TestKdjOnBar:
    def test_consistency(self):
        df = _make_test_data(200)
        setting = {"kdj_window": 9, "k_smooth": 3, "d_smooth": 3}
        batch = _get_batch_signals(KdjStrategy, df, setting)
        incremental = _run_onbar(KdjStrategy, df, setting)
        for i in range(len(df)):
            assert incremental[i] == int(batch.iloc[i]), \
                f"KDJ bar[{i}] 不一致: on_bar={incremental[i]}, batch={int(batch.iloc[i])}"


class TestCciOnBar:
    def test_consistency(self):
        df = _make_test_data(200)
        setting = {"cci_window": 14, "cci_overbought": 100, "cci_oversold": -100}
        batch = _get_batch_signals(CciStrategy, df, setting)
        incremental = _run_onbar(CciStrategy, df, setting)
        for i in range(len(df)):
            assert incremental[i] == int(batch.iloc[i]), \
                f"CCI bar[{i}] 不一致: on_bar={incremental[i]}, batch={int(batch.iloc[i])}"


class TestTripleMaOnBar:
    def test_consistency(self):
        df = _make_test_data(200)
        setting = {"fast_window": 5, "mid_window": 20, "slow_window": 60}
        batch = _get_batch_signals(TripleMaStrategy, df, setting)
        incremental = _run_onbar(TripleMaStrategy, df, setting)
        for i in range(len(df)):
            assert incremental[i] == int(batch.iloc[i]), \
                f"TripleMa bar[{i}] 不一致: on_bar={incremental[i]}, batch={int(batch.iloc[i])}"


class TestEmaCrossOnBar:
    def test_consistency(self):
        df = _make_test_data(200)
        setting = {"fast_window": 12, "slow_window": 26}
        batch = _get_batch_signals(EmaCrossStrategy, df, setting)
        incremental = _run_onbar(EmaCrossStrategy, df, setting)
        for i in range(len(df)):
            assert incremental[i] == int(batch.iloc[i]), \
                f"EmaCross bar[{i}] 不一致: on_bar={incremental[i]}, batch={int(batch.iloc[i])}"


class TestVolumeMaOnBar:
    def test_consistency(self):
        df = _make_test_data(200)
        setting = {"ma_window": 20, "vol_window": 20, "vol_ratio": 1.5}
        batch = _get_batch_signals(VolumeMaStrategy, df, setting)
        incremental = _run_onbar(VolumeMaStrategy, df, setting)
        for i in range(len(df)):
            assert incremental[i] == int(batch.iloc[i]), \
                f"VolumeMa bar[{i}] 不一致: on_bar={incremental[i]}, batch={int(batch.iloc[i])}"


class TestMomentumOnBar:
    def test_consistency(self):
        df = _make_test_data(200)
        setting = {"mom_window": 10, "mom_threshold": 0.03, "ma_window": 20}
        batch = _get_batch_signals(MomentumStrategy, df, setting)
        incremental = _run_onbar(MomentumStrategy, df, setting)
        for i in range(len(df)):
            assert incremental[i] == int(batch.iloc[i]), \
                f"Momentum bar[{i}] 不一致: on_bar={incremental[i]}, batch={int(batch.iloc[i])}"


class TestAtrChannelOnBar:
    def test_consistency(self):
        df = _make_test_data(200)
        setting = {"atr_window": 14, "atr_mult": 2.0, "ma_window": 20}
        batch = _get_batch_signals(AtrChannelStrategy, df, setting)
        incremental = _run_onbar(AtrChannelStrategy, df, setting)
        for i in range(len(df)):
            assert incremental[i] == int(batch.iloc[i]), \
                f"AtrChannel bar[{i}] 不一致: on_bar={incremental[i]}, batch={int(batch.iloc[i])}"


class TestDualThrustOnBar:
    def test_consistency(self):
        df = _make_test_data(200)
        setting = {"n_window": 4, "k_up": 0.5, "k_down": 0.5}
        batch = _get_batch_signals(DualThrustStrategy, df, setting)
        incremental = _run_onbar(DualThrustStrategy, df, setting)
        for i in range(len(df)):
            assert incremental[i] == int(batch.iloc[i]), \
                f"DualThrust bar[{i}] 不一致: on_bar={incremental[i]}, batch={int(batch.iloc[i])}"


class TestGridOnBar:
    def test_consistency(self):
        df = _make_test_data(200)
        setting = {"grid_size": 0.02, "grid_quantity": 100, "initial_position": 0}
        batch_result = GridStrategy.generate_signals(df, setting)
        batch = batch_result[0] if isinstance(batch_result, tuple) else batch_result
        incremental = _run_onbar(GridStrategy, df, setting)
        for i in range(len(df)):
            assert incremental[i] == int(batch.iloc[i]), \
                f"Grid bar[{i}] 不一致: on_bar={incremental[i]}, batch={int(batch.iloc[i])}"
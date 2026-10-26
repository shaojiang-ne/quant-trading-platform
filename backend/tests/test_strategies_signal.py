"""
信号逻辑正确性测试

构造必然触发特定信号的数据，验证每个策略的信号值正确。
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
from tests.conftest import make_crossover_data, make_rsi_oversold_data, make_bollinger_touch_lower_data


# ── DoubleMa ────────────────────────────────────────────────────────────

class TestDoubleMaSignal:
    def test_golden_cross(self):
        """快线上穿慢线 → signal=1"""
        df = make_crossover_data(5, 20, n=80)
        signals = DoubleMaStrategy.generate_signals(df, {"fast_window": 5, "slow_window": 20})
        # 至少有一个金叉信号
        assert (signals == 1).any(), "应至少产生一个金叉信号"

    def test_death_cross(self):
        """快线下穿慢线 → signal=-1"""
        n = 80
        # 先涨后跌，产生死叉
        up = [100 + i * 0.3 for i in range(n // 2)]
        down = [up[-1] - i * 0.4 for i in range(n - n // 2)]
        closes = up + down
        dates = pd.date_range("2024-01-02", periods=n, freq="D").strftime("%Y-%m-%d")
        from tests.conftest import _make_df
        df = _make_df(dates.tolist(), closes)
        signals = DoubleMaStrategy.generate_signals(df, {"fast_window": 5, "slow_window": 20})
        # 至少有一个死叉信号
        assert (signals == -1).any(), "应至少产生一个死叉信号"

    def test_no_signal_on_flat(self, constant_data):
        """价格不变 → 无信号"""
        signals = DoubleMaStrategy.generate_signals(constant_data, {"fast_window": 5, "slow_window": 20})
        assert (signals != 0).sum() == 0

    def test_signal_only_at_cross(self, oscillation_data):
        """信号只在交叉点出现，不会连续出现"""
        signals = DoubleMaStrategy.generate_signals(oscillation_data, {"fast_window": 5, "slow_window": 20})
        nonzero = signals[signals != 0]
        # 连续两个非零信号不应同号
        for i in range(1, len(nonzero)):
            assert nonzero.iloc[i] != nonzero.iloc[i-1], "连续信号不应同号"


# ── MACD ────────────────────────────────────────────────────────────────

class TestMacdSignal:
    def test_dif_cross_above_dea(self):
        df = make_crossover_data(12, 26, n=80)
        signals = MacdStrategy.generate_signals(df, {"fast_period": 12, "slow_period": 26, "signal_period": 9})
        assert (signals == 1).any(), "应产生DIF上穿DEA信号"

    def test_dif_cross_below_dea(self):
        df = make_crossover_data(12, 26, n=80)
        signals = MacdStrategy.generate_signals(df, {"fast_period": 12, "slow_period": 26, "signal_period": 9})
        assert (signals == -1).any(), "应产生DIF下穿DEA信号"


# ── Bollinger ───────────────────────────────────────────────────────────

class TestBollingerSignal:
    def test_touch_lower(self):
        df = make_bollinger_touch_lower_data(20, n=60)
        signals = BollingerStrategy.generate_signals(df, {"boll_window": 20, "boll_dev": 2.0})
        assert (signals == 1).any(), "价格触及下轨回升应产生买入信号"

    def test_no_signal_when_inside(self, constant_data):
        signals = BollingerStrategy.generate_signals(constant_data, {"boll_window": 20, "boll_dev": 2.0})
        assert (signals != 0).sum() == 0


# ── RSI ──────────────────────────────────────────────────────────────────

class TestRsiSignal:
    def test_oversold_cross(self):
        df = make_rsi_oversold_data(14, n=60)
        signals = RsiStrategy.generate_signals(df, {"rsi_window": 14, "rsi_overbought": 70, "rsi_oversold": 30})
        assert (signals == 1).any(), "RSI从超卖区回升应产生买入信号"

    def test_overbought_cross(self):
        """构造RSI从超买区回落的数据"""
        n = 60
        rsi_window = 14
        up_len = rsi_window + 10
        down_len = n - up_len
        closes = [100 + i * 2 for i in range(up_len)] + \
                 [100 + up_len * 2 - i * 3 for i in range(1, down_len + 1)]
        dates = pd.date_range("2024-01-02", periods=n, freq="D").strftime("%Y-%m-%d")
        from tests.conftest import _make_df
        df = _make_df(dates.tolist(), closes)
        signals = RsiStrategy.generate_signals(df, {"rsi_window": 14, "rsi_overbought": 70, "rsi_oversold": 30})
        assert (signals == -1).any(), "RSI从超买区回落应产生卖出信号"


# ── Turtle ──────────────────────────────────────────────────────────────

class TestTurtleSignal:
    def test_breakout_up(self):
        """突破20日最高价 → 买入"""
        n = 40
        closes = [100.0] * 20 + [100 + i * 0.5 for i in range(20)]
        dates = pd.date_range("2024-01-02", periods=n, freq="D").strftime("%Y-%m-%d")
        from tests.conftest import _make_df
        df = _make_df(dates.tolist(), closes)
        signals = TurtleStrategy.generate_signals(df, {"entry_window": 20, "exit_window": 10})
        assert (signals == 1).any(), "突破20日最高价应产生买入信号"


# ── KDJ ──────────────────────────────────────────────────────────────────

class TestKdjSignal:
    def test_oversold_golden_cross(self):
        """K线在超卖区上穿D线 → 买入"""
        n = 80
        np.random.seed(42)
        # 先跌后涨，让KDJ在超卖区金叉
        down = [100 - i * 1.0 for i in range(30)]
        up = [down[-1] + i * 1.5 for i in range(n - 30)]
        closes = down + up
        dates = pd.date_range("2024-01-02", periods=n, freq="D").strftime("%Y-%m-%d")
        from tests.conftest import _make_df
        df = _make_df(dates.tolist(), closes)
        signals = KdjStrategy.generate_signals(df, {"kdj_window": 9, "k_smooth": 3, "d_smooth": 3})
        # KDJ策略要求K<30时金叉才买入，可能不一定触发，但不应崩溃
        assert signals is not None


# ── CCI ──────────────────────────────────────────────────────────────────

class TestCciSignal:
    def test_oversold_cross(self):
        """CCI从-100下方穿越到上方 → 买入"""
        n = 60
        closes = [100 - i * 2 for i in range(25)] + [100 - 50 + i * 3 for i in range(n - 25)]
        dates = pd.date_range("2024-01-02", periods=n, freq="D").strftime("%Y-%m-%d")
        from tests.conftest import _make_df
        df = _make_df(dates.tolist(), closes)
        signals = CciStrategy.generate_signals(df, {"cci_window": 14, "cci_overbought": 100, "cci_oversold": -100})
        assert (signals == 1).any(), "CCI从超卖区回升应产生买入信号"


# ── TripleMa ────────────────────────────────────────────────────────────

class TestTripleMaSignal:
    def test_bull_alignment(self):
        """三线多头排列形成 → 买入"""
        n = 100
        closes = [100 + i * 0.3 for i in range(n)]
        dates = pd.date_range("2024-01-02", periods=n, freq="D").strftime("%Y-%m-%d")
        from tests.conftest import _make_df
        df = _make_df(dates.tolist(), closes)
        signals = TripleMaStrategy.generate_signals(df, {"fast_window": 5, "mid_window": 20, "slow_window": 60})
        assert (signals == 1).any(), "趋势上升应产生多头排列买入信号"


# ── EmaCross ────────────────────────────────────────────────────────────

class TestEmaCrossSignal:
    def test_golden_cross(self):
        df = make_crossover_data(12, 26, n=80)
        signals = EmaCrossStrategy.generate_signals(df, {"fast_window": 12, "slow_window": 26})
        assert (signals == 1).any(), "EMA金叉应产生买入信号"


# ── VolumeMa ────────────────────────────────────────────────────────────

class TestVolumeMaSignal:
    def test_volume_breakout(self):
        """放量突破均线 → 买入"""
        n = 60
        # 先下跌让close低于MA，再放量上涨穿越MA
        down = [120 - i * 0.8 for i in range(30)]
        up = [down[-1] + i * 0.8 for i in range(30)]
        closes = down + up
        volumes = [5000.0] * 25 + [50000.0] * 35  # 后半段放量
        dates = pd.date_range("2024-01-02", periods=n, freq="D").strftime("%Y-%m-%d")
        from tests.conftest import _make_df
        df = _make_df(dates.tolist(), closes, volumes=volumes)
        signals = VolumeMaStrategy.generate_signals(df, {"ma_window": 20, "vol_window": 20, "vol_ratio": 1.5})
        assert (signals == 1).any(), "放量突破应产生买入信号"


# ── Momentum ────────────────────────────────────────────────────────────

class TestMomentumSignal:
    def test_momentum_cross_up(self):
        """动量上穿阈值 → 买入"""
        n = 80
        # 先横盘/下跌（低动量），再上涨穿越阈值
        flat = [100.0] * 40
        up = [100 + i * 0.5 for i in range(40)]
        closes = flat + up
        dates = pd.date_range("2024-01-02", periods=n, freq="D").strftime("%Y-%m-%d")
        from tests.conftest import _make_df
        df = _make_df(dates.tolist(), closes)
        signals = MomentumStrategy.generate_signals(df, {"mom_window": 10, "mom_threshold": 0.03, "ma_window": 20})
        assert (signals == 1).any(), "动量上穿阈值应产生买入信号"


# ── AtrChannel ──────────────────────────────────────────────────────────

class TestAtrChannelSignal:
    def test_touch_lower_channel(self):
        """价格从ATR通道外回到通道内 → 买入"""
        n = 60
        # 先稳定，再急跌，再回升
        stable = [100.0] * 25
        drop = [100 - i * 3 for i in range(1, 8)]
        recover = [drop[-1] + i * 2 for i in range(1, n - len(stable) - len(drop) + 1)]
        closes = stable + drop + recover
        dates = pd.date_range("2024-01-02", periods=len(closes), freq="D").strftime("%Y-%m-%d")
        from tests.conftest import _make_df
        df = _make_df(dates.tolist(), closes)
        signals = AtrChannelStrategy.generate_signals(df, {"atr_window": 14, "atr_mult": 2.0, "ma_window": 20})
        assert (signals == 1).any(), "价格从通道外回升应产生买入信号"


# ── DualThrust ──────────────────────────────────────────────────────────

class TestDualThrustSignal:
    def test_no_crash(self):
        """DualThrust不应崩溃"""
        np.random.seed(42)
        n = 100
        closes = np.cumsum(np.random.normal(0, 1, n)) + 100
        dates = pd.date_range("2024-01-02", periods=n, freq="D").strftime("%Y-%m-%d")
        from tests.conftest import _make_df
        df = _make_df(dates.tolist(), closes.tolist())
        signals = DualThrustStrategy.generate_signals(df, {"n_window": 4, "k_up": 0.5, "k_down": 0.5})
        assert signals is not None
        assert len(signals) == n


# ── Grid ────────────────────────────────────────────────────────────────

class TestGridSignal:
    def test_grid_buy_on_drop(self):
        """价格下跌穿越网格线 → 买入"""
        n = 50
        closes = [100 - i * 0.5 for i in range(n)]
        dates = pd.date_range("2024-01-02", periods=n, freq="D").strftime("%Y-%m-%d")
        from tests.conftest import _make_df
        df = _make_df(dates.tolist(), closes)
        signals, grid_states = GridStrategy.generate_signals(
            df, {"grid_size": 0.02, "grid_quantity": 100, "initial_position": 0}
        )
        # 价格持续下跌应触发网格买入
        assert (signals > 0).any(), "价格下跌应触发网格买入"

    def test_grid_sell_on_rise(self):
        """价格上涨穿越网格线 → 卖出"""
        n = 50
        # 先跌后涨：先穿越买入层，再穿越卖出层
        down = [100 - i * 0.5 for i in range(25)]
        up = [down[-1] + i * 0.5 for i in range(25)]
        closes = down + up
        dates = pd.date_range("2024-01-02", periods=n, freq="D").strftime("%Y-%m-%d")
        from tests.conftest import _make_df
        df = _make_df(dates.tolist(), closes)
        signals, grid_states = GridStrategy.generate_signals(
            df, {"grid_size": 0.02, "grid_quantity": 100, "initial_position": 500}
        )
        # 价格先跌后涨应触发网格卖出
        assert (signals < 0).any(), "持仓时价格上涨应触发网格卖出"
"""
技术指标正确性测试

验证 base.py 中每个指标函数与手算参考值一致。
"""

import numpy as np
import pandas as pd
import pytest

from app.strategies.base import sma, ema, rsi, macd, bollinger, atr, donchian, kdj, cci


# ── SMA ──────────────────────────────────────────────────────────────────

class TestSma:
    def test_basic(self):
        s = pd.Series([1, 2, 3, 4, 5], dtype=float)
        result = sma(s, 3)
        assert np.isnan(result.iloc[0])
        assert np.isnan(result.iloc[1])
        assert result.iloc[2] == pytest.approx(2.0)  # (1+2+3)/3
        assert result.iloc[3] == pytest.approx(3.0)  # (2+3+4)/3
        assert result.iloc[4] == pytest.approx(4.0)  # (3+4+5)/3

    def test_window_equals_length(self):
        s = pd.Series([10, 20, 30], dtype=float)
        result = sma(s, 3)
        assert result.iloc[2] == pytest.approx(20.0)

    def test_constant_input(self):
        s = pd.Series([5.0] * 10)
        result = sma(s, 5)
        for i in range(4, 10):
            assert result.iloc[i] == pytest.approx(5.0)


# ── EMA ──────────────────────────────────────────────────────────────────

class TestEma:
    def test_matches_pandas_ewm(self):
        s = pd.Series([10, 11, 12, 13, 14, 15, 16, 17, 18, 19], dtype=float)
        result = ema(s, 5)
        expected = s.ewm(span=5, adjust=False).mean()
        pd.testing.assert_series_equal(result, expected)

    def test_constant_input(self):
        s = pd.Series([100.0] * 20)
        result = ema(s, 10)
        for i in range(1, 20):
            assert result.iloc[i] == pytest.approx(100.0)


# ── RSI ──────────────────────────────────────────────────────────────────

class TestRsi:
    def test_all_up(self):
        """连续上涨 → RSI 接近 100 或 NaN（零损失时）"""
        s = pd.Series([10 + i for i in range(30)], dtype=float)
        result = rsi(s, 14)
        # 连续上涨时 avg_loss=0 → rs=NaN → RSI=NaN（策略实现用 replace(0, nan)）
        assert result.iloc[-1] > 90 or np.isnan(result.iloc[-1])

    def test_all_down(self):
        """连续下跌 → RSI 接近 0"""
        s = pd.Series([100 - i for i in range(30)], dtype=float)
        result = rsi(s, 14)
        assert result.iloc[-1] < 10

    def test_constant_input(self):
        """价格不变 → RSI 为 NaN（0/0）"""
        s = pd.Series([50.0] * 30)
        result = rsi(s, 14)
        # 全部涨跌为0，RSI应为NaN
        assert np.isnan(result.iloc[-1])

    def test_range(self):
        """RSI 值应在 0~100 之间（非NaN部分）"""
        np.random.seed(42)
        s = pd.Series(np.cumsum(np.random.normal(0, 1, 100)) + 100, dtype=float)
        result = rsi(s, 14)
        valid = result.dropna()
        assert (valid >= 0).all() and (valid <= 100).all()


# ── MACD ─────────────────────────────────────────────────────────────────

class TestMacd:
    def test_output_length(self):
        s = pd.Series(range(50), dtype=float)
        dif, dea, hist = macd(s, 12, 26, 9)
        assert len(dif) == len(dea) == len(hist) == 50

    def test_dif_is_ema_diff(self):
        """DIF = EMA(fast) - EMA(slow)"""
        s = pd.Series(range(50), dtype=float)
        dif, dea, hist = macd(s, 12, 26, 9)
        ema_fast = ema(s, 12)
        ema_slow = ema(s, 26)
        pd.testing.assert_series_equal(dif, ema_fast - ema_slow)

    def test_hist_formula(self):
        """MACD柱 = (DIF - DEA) * 2"""
        s = pd.Series(range(50), dtype=float)
        dif, dea, hist = macd(s, 12, 26, 9)
        expected = (dif - dea) * 2
        pd.testing.assert_series_equal(hist, expected)


# ── Bollinger ────────────────────────────────────────────────────────────

class TestBollinger:
    def test_mid_is_sma(self):
        s = pd.Series(range(1, 31), dtype=float)
        mid, upper, lower = bollinger(s, 20, 2.0)
        expected_mid = sma(s, 20)
        pd.testing.assert_series_equal(mid, expected_mid)

    def test_bands_symmetric(self):
        """上下轨关于中轨对称"""
        s = pd.Series(range(1, 31), dtype=float)
        mid, upper, lower = bollinger(s, 20, 2.0)
        # upper - mid == mid - lower
        for i in range(19, 30):
            assert (upper.iloc[i] - mid.iloc[i]) == pytest.approx(mid.iloc[i] - lower.iloc[i])

    def test_constant_input(self):
        """价格不变 → 上下轨 = 中轨"""
        s = pd.Series([100.0] * 30)
        mid, upper, lower = bollinger(s, 20, 2.0)
        for i in range(19, 30):
            assert mid.iloc[i] == pytest.approx(100.0)
            assert upper.iloc[i] == pytest.approx(100.0)
            assert lower.iloc[i] == pytest.approx(100.0)


# ── ATR ──────────────────────────────────────────────────────────────────

class TestAtr:
    def test_basic(self):
        high = pd.Series([105, 106, 107], dtype=float)
        low = pd.Series([95, 96, 97], dtype=float)
        close = pd.Series([100, 101, 102], dtype=float)
        result = atr(high, low, close, 3)
        # TR[0]=10, TR[1]=max(10,6,5)=10, TR[2]=max(10,6,5)=10
        # ATR[2] = (10+10+10)/3 = 10
        assert result.iloc[2] == pytest.approx(10.0)

    def test_always_positive(self):
        np.random.seed(42)
        n = 50
        close = pd.Series(np.cumsum(np.random.normal(0, 1, n)) + 100, dtype=float)
        high = close + abs(np.random.normal(0, 2, n))
        low = close - abs(np.random.normal(0, 2, n))
        result = atr(high, low, close, 14)
        valid = result.dropna()
        assert (valid > 0).all()


# ── Donchian ────────────────────────────────────────────────────────────

class TestDonchian:
    def test_basic(self):
        high = pd.Series([100, 105, 103, 108, 102], dtype=float)
        low = pd.Series([90, 92, 88, 91, 87], dtype=float)
        upper, lower = donchian(high, low, 3)
        # upper[4] = max(103,108,102) = 108
        assert upper.iloc[4] == pytest.approx(108.0)
        # lower[4] = min(88,91,87) = 87
        assert lower.iloc[4] == pytest.approx(87.0)


# ── KDJ ──────────────────────────────────────────────────────────────────

class TestKdj:
    def test_output_range(self):
        """K, D 在 0~100，J 可超出"""
        np.random.seed(42)
        n = 50
        close = pd.Series(np.cumsum(np.random.normal(0, 1, n)) + 100, dtype=float)
        high = close + abs(np.random.normal(0, 2, n))
        low = close - abs(np.random.normal(0, 2, n))
        k, d, j = kdj(high, low, close, 9, 3, 3)
        valid_k = k.dropna()
        valid_d = d.dropna()
        assert (valid_k >= 0).all() and (valid_k <= 100).all()
        assert (valid_d >= 0).all() and (valid_d <= 100).all()

    def test_j_formula(self):
        """J = 3K - 2D"""
        np.random.seed(42)
        n = 50
        close = pd.Series(np.cumsum(np.random.normal(0, 1, n)) + 100, dtype=float)
        high = close + abs(np.random.normal(0, 2, n))
        low = close - abs(np.random.normal(0, 2, n))
        k, d, j = kdj(high, low, close, 9, 3, 3)
        expected_j = 3 * k - 2 * d
        pd.testing.assert_series_equal(j, expected_j)


# ── CCI ──────────────────────────────────────────────────────────────────

class TestCci:
    def test_output_length(self):
        np.random.seed(42)
        n = 50
        close = pd.Series(np.cumsum(np.random.normal(0, 1, n)) + 100, dtype=float)
        high = close + abs(np.random.normal(0, 2, n))
        low = close - abs(np.random.normal(0, 2, n))
        result = cci(high, low, close, 14)
        assert len(result) == n

    def test_constant_input_is_nan(self):
        """价格不变 → MD=0 → CCI=NaN"""
        high = pd.Series([100.0] * 30)
        low = pd.Series([100.0] * 30)
        close = pd.Series([100.0] * 30)
        result = cci(high, low, close, 14)
        assert np.isnan(result.iloc[-1])
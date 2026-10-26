"""技术分析服务单元测试"""
import sys
import os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

import pandas as pd
import numpy as np
import pytest

from app.services.technical_analysis_service import TechnicalAnalysisService


def _make_df(n: int = 120, start_price: float = 20.0, trend: str = "up") -> pd.DataFrame:
    """构造模拟K线数据"""
    dates = pd.date_range("2025-01-01", periods=n, freq="B")
    if trend == "up":
        closes = start_price + np.arange(n) * 0.1
    elif trend == "down":
        closes = start_price - np.arange(n) * 0.1
    elif trend == "flat":
        closes = np.full(n, start_price)
    else:
        np.random.seed(42)
        closes = start_price + np.cumsum(np.random.randn(n) * 0.3)

    highs = closes + 0.2
    lows = closes - 0.2
    opens = closes - 0.05
    volumes = np.random.randint(100000, 500000, n).astype(float)

    return pd.DataFrame({
        "date": dates,
        "open": opens,
        "high": highs,
        "low": lows,
        "close": closes,
        "volume": volumes,
    })


svc = TechnicalAnalysisService()


# ── 趋势指标 ──────────────────────────────────────────────────────────────

def test_ma_calculation():
    """MA5/MA10/MA20/MA60 正确计算"""
    df = _make_df(120, trend="up")
    result = svc._calc_trend_indicators(df)
    assert "ma5" in result
    assert "ma10" in result
    assert "ma20" in result
    assert "ma60" in result
    assert result["ma5"] > result["ma20"]

def test_ma_alignment_bullish():
    df = _make_df(120, trend="up")
    result = svc._calc_trend_indicators(df)
    assert "多头排列" in result["ma_alignment"]

def test_ma_alignment_bearish():
    df = _make_df(120, trend="down")
    result = svc._calc_trend_indicators(df)
    assert "空头排列" in result["ma_alignment"]

def test_macd_calculation():
    df = _make_df(120, trend="up")
    result = svc._calc_trend_indicators(df)
    assert "dif" in result
    assert "dea" in result
    assert "hist" in result
    assert result["dif"] > 0

def test_macd_cross():
    df = _make_df(120, trend="up")
    result = svc._calc_trend_indicators(df)
    assert "macd_signal" in result
    assert result["macd_signal"] in ("金叉", "死叉", "金叉状态", "死叉状态")

def test_trend_judgment():
    df = _make_df(120, trend="up")
    result = svc._calc_trend_indicators(df)
    assert result["trend"] in ("上升", "下降", "震荡")

# ── 震荡指标 ──────────────────────────────────────────────────────────────

def test_rsi_calculation():
    df = _make_df(120, trend="up")
    result = svc._calc_oscillation_indicators(df)
    assert "rsi6" in result
    assert "rsi14" in result
    assert 0 <= result["rsi6"] <= 100
    assert 0 <= result["rsi14"] <= 100

def test_rsi_overbought():
    df = _make_df(120, trend="up")
    result = svc._calc_oscillation_indicators(df)
    assert result["rsi14_status"] in ("超买", "偏强", "中性", "偏弱", "超卖")

def test_kdj_calculation():
    df = _make_df(120, trend="up")
    result = svc._calc_oscillation_indicators(df)
    assert "k" in result
    assert "d" in result
    assert "j" in result
    assert "kdj_signal" in result

def test_cci_calculation():
    df = _make_df(120, trend="up")
    result = svc._calc_oscillation_indicators(df)
    assert "cci" in result
    assert "cci_status" in result

# ── 波动/通道指标 ──────────────────────────────────────────────────────

def test_bollinger_calculation():
    df = _make_df(120, trend="up")
    result = svc._calc_volatility_indicators(df)
    assert "boll_upper" in result
    assert "boll_mid" in result
    assert "boll_lower" in result
    assert result["boll_upper"] > result["boll_mid"] > result["boll_lower"]

def test_boll_position():
    df = _make_df(120, trend="up")
    result = svc._calc_volatility_indicators(df)
    assert "boll_position" in result
    assert result["boll_position"] in ("上轨外", "上轨与中轨间", "中轨与下轨间", "下轨外")

def test_atr_calculation():
    df = _make_df(120, trend="up")
    result = svc._calc_volatility_indicators(df)
    assert "atr" in result
    assert result["atr"] > 0

def test_donchian_calculation():
    df = _make_df(120, trend="up")
    result = svc._calc_volatility_indicators(df)
    assert "donch_upper" in result
    assert "donch_lower" in result
    assert result["donch_upper"] >= result["donch_lower"]

# ── K线形态 ──────────────────────────────────────────────────────────────

def test_hammer_pattern():
    df = _make_df(10, start_price=20.0, trend="down")
    i = len(df) - 1
    df.loc[i, "open"] = 19.0
    df.loc[i, "high"] = 19.2
    df.loc[i, "low"] = 17.0
    df.loc[i, "close"] = 19.0
    patterns = svc._detect_patterns(df)
    assert any(p["name"] == "锤子线" for p in patterns)

def test_doji_pattern():
    df = _make_df(10, start_price=20.0, trend="flat")
    i = len(df) - 1
    df.loc[i, "open"] = 20.0
    df.loc[i, "high"] = 20.5
    df.loc[i, "low"] = 19.5
    df.loc[i, "close"] = 20.02
    patterns = svc._detect_patterns(df)
    assert any(p["name"] == "十字星" for p in patterns)

def test_bullish_engulfing():
    df = _make_df(10, start_price=20.0, trend="down")
    i = len(df) - 1
    prev = i - 1
    df.loc[prev, "open"] = 20.0
    df.loc[prev, "close"] = 19.0
    df.loc[i, "open"] = 18.5
    df.loc[i, "close"] = 20.5
    df.loc[i, "high"] = 20.6
    df.loc[i, "low"] = 18.4
    patterns = svc._detect_patterns(df)
    assert any(p["name"] == "看涨吞没" for p in patterns)

def test_bearish_engulfing():
    df = _make_df(10, start_price=20.0, trend="up")
    i = len(df) - 1
    prev = i - 1
    df.loc[prev, "open"] = 19.0
    df.loc[prev, "close"] = 20.0
    df.loc[i, "open"] = 20.5
    df.loc[i, "close"] = 18.5
    df.loc[i, "high"] = 20.6
    df.loc[i, "low"] = 18.4
    patterns = svc._detect_patterns(df)
    assert any(p["name"] == "看跌吞没" for p in patterns)

def test_patterns_only_recent_5():
    df = _make_df(120, trend="up")
    patterns = svc._detect_patterns(df)
    for p in patterns:
        assert p["days_ago"] <= 5

# ── 支撑阻力 ──────────────────────────────────────────────────────────────

def test_support_resistance():
    df = _make_df(120, trend="up")
    result = svc._calc_support_resistance(df)
    assert "support" in result
    assert "resistance" in result
    assert len(result["support"]) > 0
    assert len(result["resistance"]) > 0

# ── 成交量分析 ──────────────────────────────────────────────────────────

def test_volume_ratio():
    df = _make_df(120, trend="up")
    result = svc._calc_volume_analysis(df)
    assert "volume_ratio" in result
    assert result["volume_ratio"] > 0
    assert "volume_status" in result

def test_volume_price_relation():
    df = _make_df(120, trend="up")
    result = svc._calc_volume_analysis(df)
    assert "vp_relation" in result

def test_volume_divergence():
    df = _make_df(120, trend="up")
    result = svc._calc_volume_analysis(df)
    assert "vp_divergence" in result

# ── 文本摘要生成 ──────────────────────────────────────────────────────

def test_generate_summary():
    df = _make_df(120, trend="up")
    trend_r = svc._calc_trend_indicators(df)
    osc_r = svc._calc_oscillation_indicators(df)
    vol_r = svc._calc_volatility_indicators(df)
    patterns_r = svc._detect_patterns(df)
    sr_r = svc._calc_support_resistance(df)
    va_r = svc._calc_volume_analysis(df)
    summary = svc._generate_summary(trend_r, osc_r, vol_r, patterns_r, sr_r, va_r)
    assert "趋势指标" in summary
    assert "震荡指标" in summary
    assert "波动" in summary
    assert "成交量" in summary

# ── 顶层 analyze 方法 ──────────────────────────────────────────────────

def test_analyze_returns_dict():
    df = _make_df(120, trend="up")
    result = svc.analyze(df)
    assert "analysis" in result
    assert "signals" in result
    assert isinstance(result["analysis"], str)
    assert isinstance(result["signals"], dict)

def test_analyze_signals_structure():
    df = _make_df(120, trend="up")
    result = svc.analyze(df)
    s = result["signals"]
    for key in ("trend", "ma_alignment", "macd_signal", "rsi_status", "kdj_signal",
                "boll_position", "volume_status", "patterns", "support_levels", "resistance_levels"):
        assert key in s, f"Missing key: {key}"

def test_analyze_insufficient_data():
    df = _make_df(10, trend="up")
    result = svc.analyze(df)
    assert "analysis" in result
    assert result["analysis"] != ""

def test_analyze_empty_df():
    df = pd.DataFrame(columns=["date", "open", "high", "low", "close", "volume"])
    result = svc.analyze(df)
    assert "analysis" in result
    assert "无法" in result["analysis"] or "不足" in result["analysis"]

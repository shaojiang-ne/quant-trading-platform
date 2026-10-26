# 技术分析模块 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 在 AI 分析助手中新增「技术分析」快捷场景，后端计算技术指标/K线形态/支撑阻力/成交量，结构化文本注入 LLM 做深度解读。

**Architecture:** 后端新增 `TechnicalAnalysisService`，复用 `strategies/base.py` 的 9 个指标函数 + 新增 K线形态识别/支撑阻力/成交量分析。前端在 `AIAssistant.tsx` 的 `quickScenarios` 数组中新增场景按钮。走现有 research-chat 的「先取数再分析」模式。

**Tech Stack:** Python/FastAPI (后端), React/TypeScript (前端), pandas (指标计算), lightweight-charts (已有K线组件，本次不改动)

---

## File Structure

| File | Action | Responsibility |
|------|--------|---------------|
| `app/services/technical_analysis_service.py` | Create | 技术指标计算、K线形态识别、支撑阻力、成交量分析、文本摘要生成 |
| `app/api/research.py` | Modify | 新增 `/research/technical-analysis` GET 路由 |
| `frontend/src/api/research.ts` | Modify | 新增 `technicalAnalysis` API 方法 |
| `frontend/src/pages/AIAssistant.tsx` | Modify | 新增「技术分析」场景按钮 |
| `tests/test_technical_analysis.py` | Create | 单元测试：指标计算、形态识别、支撑阻力、成交量、降级逻辑、API |

---

### Task 1: Create TechnicalAnalysisService — 趋势指标 + 震荡指标

**Files:**
- Create: `app/services/technical_analysis_service.py`
- Create: `tests/test_technical_analysis.py`

- [ ] **Step 1: Write failing tests for trend indicators**

```python
# tests/test_technical_analysis.py
"""技术分析服务单元测试"""
import pandas as pd
import numpy as np
import pytest

from app.services.technical_analysis_service import TechnicalAnalysisService


def _make_df(n: int = 120, start_price: float = 20.0, trend: str = "up") -> pd.DataFrame:
    """构造模拟K线数据

    Args:
        n: K线根数
        start_price: 起始价格
        trend: "up" 每日涨0.1, "down" 每日跌0.1, "flat" 不涨不跌, "random" 随机
    """
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
    # 上升趋势中 MA5 > MA20
    assert result["ma5"] > result["ma20"]


def test_ma_alignment_bullish():
    """上升趋势 → 多头排列"""
    df = _make_df(120, trend="up")
    result = svc._calc_trend_indicators(df)
    assert "多头排列" in result["ma_alignment"]


def test_ma_alignment_bearish():
    """下降趋势 → 空头排列"""
    df = _make_df(120, trend="down")
    result = svc._calc_trend_indicators(df)
    assert "空头排列" in result["ma_alignment"]


def test_macd_calculation():
    """MACD 正确计算，含金叉/死叉判断"""
    df = _make_df(120, trend="up")
    result = svc._calc_trend_indicators(df)
    assert "dif" in result
    assert "dea" in result
    assert "hist" in result
    assert result["dif"] > 0  # 上升趋势 DIF 在零轴上方


def test_macd_cross():
    """MACD 金叉/死叉信号判断"""
    df = _make_df(120, trend="up")
    result = svc._calc_trend_indicators(df)
    assert "macd_signal" in result
    assert result["macd_signal"] in ("金叉", "死叉", "金叉状态", "死叉状态")


def test_trend_judgment():
    """综合趋势判断"""
    df = _make_df(120, trend="up")
    result = svc._calc_trend_indicators(df)
    assert result["trend"] in ("上升", "下降", "震荡")


# ── 震荡指标 ──────────────────────────────────────────────────────────────

def test_rsi_calculation():
    """RSI(6) 和 RSI(14) 正确计算"""
    df = _make_df(120, trend="up")
    result = svc._calc_oscillation_indicators(df)
    assert "rsi6" in result
    assert "rsi14" in result
    assert 0 <= result["rsi6"] <= 100
    assert 0 <= result["rsi14"] <= 100


def test_rsi_overbought():
    """上升趋势 RSI 偏强或超买"""
    df = _make_df(120, trend="up")
    result = svc._calc_oscillation_indicators(df)
    assert result["rsi14_status"] in ("超买", "偏强", "中性", "偏弱", "超卖")


def test_kdj_calculation():
    """KDJ 正确计算"""
    df = _make_df(120, trend="up")
    result = svc._calc_oscillation_indicators(df)
    assert "k" in result
    assert "d" in result
    assert "j" in result
    assert "kdj_signal" in result


def test_cci_calculation():
    """CCI 正确计算"""
    df = _make_df(120, trend="up")
    result = svc._calc_oscillation_indicators(df)
    assert "cci" in result
    assert "cci_status" in result
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd D:/MyProj/stock/backend && python -m pytest tests/test_technical_analysis.py -v --no-header -q 2>&1 | head -30`
Expected: ImportError — `TechnicalAnalysisService` does not exist

- [ ] **Step 3: Implement TechnicalAnalysisService — trend + oscillation indicators**

```python
# app/services/technical_analysis_service.py
"""个股技术分析服务

复用 strategies/base.py 的 9 个指标函数，新增 K线形态识别、支撑阻力、成交量分析。
结果以结构化文本摘要注入 LLM system 提示词。
"""

import logging
from datetime import datetime, timedelta

import numpy as np
import pandas as pd

from app.strategies.base import sma, ema, rsi, macd, bollinger, atr, donchian, kdj, cci

logger = logging.getLogger(__name__)


class TechnicalAnalysisService:
    """个股技术分析服务"""

    # ── 趋势类指标 ──────────────────────────────────────────────────────

    def _calc_trend_indicators(self, df: pd.DataFrame) -> dict:
        """计算 MA/MACD/趋势判断"""
        close = df["close"]
        result = {}

        # MA
        for w in (5, 10, 20, 60):
            if len(close) >= w:
                result[f"ma{w}"] = round(float(sma(close, w).iloc[-1]), 2)
            else:
                result[f"ma{w}"] = None

        # 均线排列判断
        ma_vals = [result.get(f"ma{w}") for w in (5, 10, 20, 60)]
        if all(v is not None for v in ma_vals):
            if ma_vals[0] > ma_vals[1] > ma_vals[2] > ma_vals[3]:
                result["ma_alignment"] = "多头排列(MA5>MA10>MA20>MA60)"
            elif ma_vals[0] < ma_vals[1] < ma_vals[2] < ma_vals[3]:
                result["ma_alignment"] = "空头排列(MA5<MA10<MA20<MA60)"
            else:
                result["ma_alignment"] = "均线纠缠"
        else:
            result["ma_alignment"] = "数据不足"

        # MACD
        if len(close) >= 35:
            dif, dea, hist = macd(close, 12, 26, 9)
            result["dif"] = round(float(dif.iloc[-1]), 4)
            result["dea"] = round(float(dea.iloc[-1]), 4)
            result["hist"] = round(float(hist.iloc[-1]), 4)
            # 金叉/死叉
            if dif.iloc[-1] > dea.iloc[-1]:
                result["macd_signal"] = "金叉状态" if dif.iloc[-2] <= dea.iloc[-2] else "金叉"
            else:
                result["macd_signal"] = "死叉状态" if dif.iloc[-2] >= dea.iloc[-2] else "死叉"
            # 零轴位置
            result["dif_position"] = "零轴上方" if result["dif"] > 0 else "零轴下方"
        else:
            result["dif"] = result["dea"] = result["hist"] = None
            result["macd_signal"] = "数据不足"
            result["dif_position"] = ""

        # 趋势判断
        trend_votes = {"上升": 0, "下降": 0, "震荡": 0}
        if result["ma_alignment"].startswith("多头"):
            trend_votes["上升"] += 2
        elif result["ma_alignment"].startswith("空头"):
            trend_votes["下降"] += 2
        else:
            trend_votes["震荡"] += 1

        if result.get("dif") is not None:
            if result["dif"] > 0 and "金叉" in result["macd_signal"]:
                trend_votes["上升"] += 1
            elif result["dif"] < 0 and "死叉" in result["macd_signal"]:
                trend_votes["下降"] += 1
            else:
                trend_votes["震荡"] += 1

        result["trend"] = max(trend_votes, key=trend_votes.get)
        return result

    # ── 震荡类指标 ──────────────────────────────────────────────────────

    def _calc_oscillation_indicators(self, df: pd.DataFrame) -> dict:
        """计算 RSI/KDJ/CCI"""
        close = df["close"]
        high = df["high"]
        low = df["low"]
        result = {}

        # RSI
        for w, label in ((6, "rsi6"), (14, "rsi14")):
            if len(close) >= w + 1:
                val = float(rsi(close, w).iloc[-1])
                result[label] = round(val, 1)
                if np.isnan(val):
                    result[f"{label}_status"] = "数据不足"
                elif val > 80:
                    result[f"{label}_status"] = "超买"
                elif val > 60:
                    result[f"{label}_status"] = "偏强"
                elif val > 40:
                    result[f"{label}_status"] = "中性"
                elif val > 20:
                    result[f"{label}_status"] = "偏弱"
                else:
                    result[f"{label}_status"] = "超卖"
            else:
                result[label] = None
                result[f"{label}_status"] = "数据不足"

        # KDJ
        if len(close) >= 12:
            k, d, j = kdj(high, low, close, 9, 3, 3)
            result["k"] = round(float(k.iloc[-1]), 1)
            result["d"] = round(float(d.iloc[-1]), 1)
            result["j"] = round(float(j.iloc[-1]), 1)
            if k.iloc[-1] > d.iloc[-1]:
                result["kdj_signal"] = "金叉" if k.iloc[-2] <= d.iloc[-2] else "金叉状态"
            else:
                result["kdj_signal"] = "死叉" if k.iloc[-2] >= d.iloc[-2] else "死叉状态"
        else:
            result["k"] = result["d"] = result["j"] = None
            result["kdj_signal"] = "数据不足"

        # CCI
        if len(close) >= 15:
            val = float(cci(high, low, close, 14).iloc[-1])
            result["cci"] = round(val, 1)
            if val > 200:
                result["cci_status"] = "异常偏高"
            elif val > 100:
                result["cci_status"] = "偏强"
            elif val > -100:
                result["cci_status"] = "中性"
            elif val > -200:
                result["cci_status"] = "偏弱"
            else:
                result["cci_status"] = "异常偏低"
        else:
            result["cci"] = None
            result["cci_status"] = "数据不足"

        return result


technical_analysis_service = TechnicalAnalysisService()
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `cd D:/MyProj/stock/backend && python -m pytest tests/test_technical_analysis.py -v --no-header -q 2>&1 | head -40`
Expected: All 9 tests PASS

- [ ] **Step 5: Commit**

```bash
cd D:/MyProj/stock/backend
git add app/services/technical_analysis_service.py tests/test_technical_analysis.py
git commit -m "feat: add TechnicalAnalysisService — trend + oscillation indicators"
```

---

### Task 2: Add volatility/channel indicators + K线形态识别 + 支撑阻力 + 成交量分析

**Files:**
- Modify: `app/services/technical_analysis_service.py`
- Modify: `tests/test_technical_analysis.py`

- [ ] **Step 1: Write failing tests for volatility, patterns, support/resistance, volume**

```python
# Append to tests/test_technical_analysis.py

# ── 波动/通道指标 ──────────────────────────────────────────────────────

def test_bollinger_calculation():
    """布林带正确计算"""
    df = _make_df(120, trend="up")
    result = svc._calc_volatility_indicators(df)
    assert "boll_upper" in result
    assert "boll_mid" in result
    assert "boll_lower" in result
    assert result["boll_upper"] > result["boll_mid"] > result["boll_lower"]


def test_boll_position():
    """布林带价格位置判断"""
    df = _make_df(120, trend="up")
    result = svc._calc_volatility_indicators(df)
    assert "boll_position" in result
    assert result["boll_position"] in ("上轨外", "上轨与中轨间", "中轨附近", "中轨与下轨间", "下轨外")


def test_atr_calculation():
    """ATR 正确计算"""
    df = _make_df(120, trend="up")
    result = svc._calc_volatility_indicators(df)
    assert "atr" in result
    assert result["atr"] > 0


def test_donchian_calculation():
    """唐奇安通道正确计算"""
    df = _make_df(120, trend="up")
    result = svc._calc_volatility_indicators(df)
    assert "donch_upper" in result
    assert "donch_lower" in result
    assert result["donch_upper"] >= result["donch_lower"]


# ── K线形态 ──────────────────────────────────────────────────────────────

def test_hammer_pattern():
    """锤子线识别"""
    # 构造锤子线：大下影线，小实体，几乎无上影线，出现在下跌后
    df = _make_df(10, start_price=20.0, trend="down")
    # 替换最后一根为锤子线
    i = len(df) - 1
    df.loc[i, "open"] = 19.0
    df.loc[i, "high"] = 19.2
    df.loc[i, "low"] = 17.0    # 大下影线
    df.loc[i, "close"] = 19.0  # 小实体（阳线）
    patterns = svc._detect_patterns(df)
    assert any(p["name"] == "锤子线" for p in patterns)


def test_doji_pattern():
    """十字星识别"""
    df = _make_df(10, start_price=20.0, trend="flat")
    i = len(df) - 1
    df.loc[i, "open"] = 20.0
    df.loc[i, "high"] = 20.5
    df.loc[i, "low"] = 19.5
    df.loc[i, "close"] = 20.02  # 实体极小
    patterns = svc._detect_patterns(df)
    assert any(p["name"] == "十字星" for p in patterns)


def test_bullish_engulfing():
    """看涨吞没识别"""
    df = _make_df(10, start_price=20.0, trend="down")
    i = len(df) - 1
    prev = i - 1
    # 前一根：阴线
    df.loc[prev, "open"] = 20.0
    df.loc[prev, "close"] = 19.0
    # 当日：阳线吞没
    df.loc[i, "open"] = 18.5
    df.loc[i, "close"] = 20.5
    df.loc[i, "high"] = 20.6
    df.loc[i, "low"] = 18.4
    patterns = svc._detect_patterns(df)
    assert any(p["name"] == "看涨吞没" for p in patterns)


def test_bearish_engulfing():
    """看跌吞没识别"""
    df = _make_df(10, start_price=20.0, trend="up")
    i = len(df) - 1
    prev = i - 1
    # 前一根：阳线
    df.loc[prev, "open"] = 19.0
    df.loc[prev, "close"] = 20.0
    # 当日：阴线吞没
    df.loc[i, "open"] = 20.5
    df.loc[i, "close"] = 18.5
    df.loc[i, "high"] = 20.6
    df.loc[i, "low"] = 18.4
    patterns = svc._detect_patterns(df)
    assert any(p["name"] == "看跌吞没" for p in patterns)


def test_patterns_only_recent_5():
    """只检测最近5根K线"""
    df = _make_df(120, trend="up")
    patterns = svc._detect_patterns(df)
    for p in patterns:
        assert p["days_ago"] <= 5


# ── 支撑阻力 ──────────────────────────────────────────────────────────────

def test_support_resistance():
    """支撑阻力位计算"""
    df = _make_df(120, trend="up")
    result = svc._calc_support_resistance(df)
    assert "support" in result
    assert "resistance" in result
    assert len(result["support"]) > 0
    assert len(result["resistance"]) > 0


# ── 成交量分析 ──────────────────────────────────────────────────────────

def test_volume_ratio():
    """量比计算"""
    df = _make_df(120, trend="up")
    result = svc._calc_volume_analysis(df)
    assert "volume_ratio" in result
    assert result["volume_ratio"] > 0
    assert "volume_status" in result


def test_volume_price_relation():
    """量价关系判断"""
    df = _make_df(120, trend="up")
    result = svc._calc_volume_analysis(df)
    assert "vp_relation" in result


def test_volume_divergence():
    """量价背离检测"""
    df = _make_df(120, trend="up")
    result = svc._calc_volume_analysis(df)
    assert "vp_divergence" in result
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd D:/MyProj/stock/backend && python -m pytest tests/test_technical_analysis.py -v --no-header -q -k "bollinger or atr or donchian or hammer or doji or engulfing or support_resistance or volume_ratio or volume_price or volume_divergence" 2>&1 | head -30`
Expected: FAIL — methods do not exist

- [ ] **Step 3: Implement volatility indicators, K线形态, 支撑阻力, 成交量**

Add the following methods to `TechnicalAnalysisService` in `app/services/technical_analysis_service.py`, before the module-level singleton line:

```python
    # ── 波动/通道类指标 ──────────────────────────────────────────────

    def _calc_volatility_indicators(self, df: pd.DataFrame) -> dict:
        """计算布林带/ATR/唐奇安通道"""
        close = df["close"]
        high = df["high"]
        low = df["low"]
        result = {}

        # 布林带
        if len(close) >= 20:
            mid, upper, lower = bollinger(close, 20, 2.0)
            result["boll_upper"] = round(float(upper.iloc[-1]), 2)
            result["boll_mid"] = round(float(mid.iloc[-1]), 2)
            result["boll_lower"] = round(float(lower.iloc[-1]), 2)
            # 带宽判断
            bw = (result["boll_upper"] - result["boll_lower"]) / result["boll_mid"]
            bw_prev = float((upper.iloc[-2] - lower.iloc[-2]) / mid.iloc[-2]) if len(close) > 20 else bw
            result["boll_width"] = "收窄" if bw < bw_prev else "扩张"
            # 价格位置
            price = float(close.iloc[-1])
            if price > result["boll_upper"]:
                result["boll_position"] = "上轨外"
            elif price > result["boll_mid"]:
                result["boll_position"] = "上轨与中轨间"
            elif price > result["boll_lower"]:
                result["boll_position"] = "中轨与下轨间"
            else:
                result["boll_position"] = "下轨外"
        else:
            result["boll_upper"] = result["boll_mid"] = result["boll_lower"] = None
            result["boll_width"] = ""
            result["boll_position"] = "数据不足"

        # ATR
        if len(close) >= 15:
            atr_val = atr(high, low, close, 14)
            result["atr"] = round(float(atr_val.iloc[-1]), 2)
            atr_ma5 = float(atr_val.tail(5).mean())
            result["atr_level"] = "偏高" if result["atr"] > atr_ma5 * 1.2 else ("偏低" if result["atr"] < atr_ma5 * 0.8 else "正常")
        else:
            result["atr"] = None
            result["atr_level"] = "数据不足"

        # 唐奇安通道
        if len(close) >= 20:
            d_upper, d_lower = donchian(high, low, 20)
            result["donch_upper"] = round(float(d_upper.iloc[-1]), 2)
            result["donch_lower"] = round(float(d_lower.iloc[-1]), 2)
            price = float(close.iloc[-1])
            if price > result["donch_upper"]:
                result["donch_break"] = "向上突破上轨"
            elif price < result["donch_lower"]:
                result["donch_break"] = "向下突破下轨"
            else:
                result["donch_break"] = "通道内"
        else:
            result["donch_upper"] = result["donch_lower"] = None
            result["donch_break"] = "数据不足"

        return result

    # ── K线形态识别 ──────────────────────────────────────────────────

    def _detect_patterns(self, df: pd.DataFrame) -> list[dict]:
        """识别最近5根K线的形态"""
        patterns = []
        n = len(df)
        start = max(0, n - 5)

        # 判断前期趋势：前5-10根K线的涨跌
        lookback_start = max(0, n - 15)
        recent_trend = "neutral"
        if n > lookback_start + 3:
            prev_close = df["close"].iloc[lookback_start:n-5]
            if len(prev_close) >= 3:
                if prev_close.iloc[-1] > prev_close.iloc[0] * 1.02:
                    recent_trend = "up"
                elif prev_close.iloc[-1] < prev_close.iloc[0] * 0.98:
                    recent_trend = "down"

        for i in range(start, n):
            o = float(df["open"].iloc[i])
            h = float(df["high"].iloc[i])
            l = float(df["low"].iloc[i])
            c = float(df["close"].iloc[i])
            body = abs(c - o)
            total_range = h - l
            if total_range == 0:
                continue
            upper_shadow = h - max(o, c)
            lower_shadow = min(o, c) - l

            days_ago = n - 1 - i

            # 十字星
            if body < total_range * 0.1:
                patterns.append({"name": "十字星", "signal": "中性/反转", "days_ago": days_ago})
                continue

            # 锤子线：下影线 > 实体*2, 上影线 < 实体*0.3
            if lower_shadow > body * 2 and upper_shadow < body * 0.3 and recent_trend == "down":
                patterns.append({"name": "锤子线", "signal": "看涨", "days_ago": days_ago})

            # 倒锤子：上影线 > 实体*2, 下影线 < 实体*0.3
            if upper_shadow > body * 2 and lower_shadow < body * 0.3 and recent_trend == "down":
                patterns.append({"name": "倒锤子", "signal": "看涨", "days_ago": days_ago})

            # 吞没形态：需要前一根K线
            if i > 0:
                prev_o = float(df["open"].iloc[i - 1])
                prev_c = float(df["close"].iloc[i - 1])
                prev_body_top = max(prev_o, prev_c)
                prev_body_bottom = min(prev_o, prev_c)
                curr_body_top = max(o, c)
                curr_body_bottom = min(o, c)

                # 看涨吞没：前阴后阳，当日实体包住前日
                if prev_c < prev_o and c > o and curr_body_bottom <= prev_body_bottom and curr_body_top >= prev_body_top and recent_trend == "down":
                    patterns.append({"name": "看涨吞没", "signal": "看涨", "days_ago": days_ago})

                # 看跌吞没：前阳后阴，当日实体包住前日
                if prev_c > prev_o and c < o and curr_body_bottom <= prev_body_bottom and curr_body_top >= prev_body_top and recent_trend == "up":
                    patterns.append({"name": "看跌吞没", "signal": "看跌", "days_ago": days_ago})

                # 刺透形态：前阴后阳，开盘低于前日低点，收盘在前日实体上半部
                if prev_c < prev_o and c > o:
                    prev_mid = (prev_o + prev_c) / 2
                    if o < min(prev_o, prev_c) and c > prev_mid and recent_trend == "down":
                        patterns.append({"name": "刺透形态", "signal": "看涨", "days_ago": days_ago})

        return patterns

    # ── 支撑阻力位 ──────────────────────────────────────────────────

    def _calc_support_resistance(self, df: pd.DataFrame) -> dict:
        """计算支撑阻力位"""
        close = df["close"]
        result = {"support": [], "resistance": []}
        price = float(close.iloc[-1])

        # MA20/MA60 支撑/阻力
        for w in (20, 60):
            if len(close) >= w:
                ma_val = round(float(sma(close, w).iloc[-1]), 2)
                if ma_val < price:
                    result["support"].append({"price": ma_val, "source": f"MA{w}"})
                else:
                    result["resistance"].append({"price": ma_val, "source": f"MA{w}"})

        # 布林带支撑/阻力
        if len(close) >= 20:
            mid, upper, lower = bollinger(close, 20, 2.0)
            boll_lower = round(float(lower.iloc[-1]), 2)
            boll_upper = round(float(upper.iloc[-1]), 2)
            result["support"].append({"price": boll_lower, "source": "布林下轨"})
            result["resistance"].append({"price": boll_upper, "source": "布林上轨"})

        # 近60日最高/最低
        tail = df.tail(60)
        high_60 = round(float(tail["high"].max()), 2)
        low_60 = round(float(tail["low"].min()), 2)
        if high_60 > price:
            result["resistance"].append({"price": high_60, "source": "60日最高"})
        if low_60 < price:
            result["support"].append({"price": low_60, "source": "60日最低"})

        # 密集成交区：按价格分10档，找成交量最大的2个区间
        tail_df = df.tail(60)
        price_min = float(tail_df["low"].min())
        price_max = float(tail_df["high"].max())
        if price_max > price_min:
            step = (price_max - price_min) / 10
            volume_by_bucket = {}
            for _, row in tail_df.iterrows():
                mid_price = (float(row["high"]) + float(row["low"])) / 2
                bucket = int((mid_price - price_min) / step)
                bucket = min(bucket, 9)
                volume_by_bucket[bucket] = volume_by_bucket.get(bucket, 0) + float(row["volume"])
            if volume_by_bucket:
                sorted_buckets = sorted(volume_by_bucket.items(), key=lambda x: x[1], reverse=True)
                for bucket_idx, _ in sorted_buckets[:2]:
                    bucket_mid = round(price_min + (bucket_idx + 0.5) * step, 2)
                    if bucket_mid < price:
                        result["support"].append({"price": bucket_mid, "source": "密集成交区"})
                    else:
                        result["resistance"].append({"price": bucket_mid, "source": "密集成交区"})

        # 排序
        result["support"].sort(key=lambda x: x["price"], reverse=True)
        result["resistance"].sort(key=lambda x: x["price"])

        return result

    # ── 成交量分析 ──────────────────────────────────────────────────

    def _calc_volume_analysis(self, df: pd.DataFrame) -> dict:
        """分析量比、量价关系、量价背离"""
        close = df["close"]
        volume = df["volume"]
        result = {}

        # 量比
        if len(volume) >= 6:
            vol_ma5 = float(volume.iloc[-6:-1].mean())
            vol_today = float(volume.iloc[-1])
            result["volume_ratio"] = round(vol_today / vol_ma5, 2) if vol_ma5 > 0 else 0
            if result["volume_ratio"] > 2.0:
                result["volume_status"] = "明显放量"
            elif result["volume_ratio"] > 1.5:
                result["volume_status"] = "温和放量"
            elif result["volume_ratio"] > 0.7:
                result["volume_status"] = "正常"
            else:
                result["volume_status"] = "缩量"
        else:
            result["volume_ratio"] = None
            result["volume_status"] = "数据不足"

        # 量价关系（近5日）
        if len(close) >= 6:
            recent_close = close.iloc[-5:]
            recent_vol = volume.iloc[-5:]
            up_days = (recent_close.diff() > 0).sum()
            vol_up_on_price_up = sum(
                1 for i in range(1, len(recent_close))
                if recent_close.iloc[i] > recent_close.iloc[i-1] and recent_vol.iloc[i] > recent_vol.iloc[i-1]
            )
            down_days = (recent_close.diff() < 0).sum()
            vol_down_on_price_down = sum(
                1 for i in range(1, len(recent_close))
                if recent_close.iloc[i] < recent_close.iloc[i-1] and recent_vol.iloc[i] < recent_vol.iloc[i-1]
            )

            if up_days > 0 and vol_up_on_price_up / up_days >= 0.5:
                result["vp_relation"] = "量价配合(上涨放量)"
            elif down_days > 0 and vol_down_on_price_down / down_days >= 0.5:
                result["vp_relation"] = "量价配合(下跌缩量)"
            else:
                result["vp_relation"] = "量价背离迹象"
        else:
            result["vp_relation"] = "数据不足"

        # 量价背离
        if len(close) >= 6:
            recent_close = close.iloc[-5:]
            recent_vol = volume.iloc[-5:]
            price_trend_up = recent_close.iloc[-1] > recent_close.iloc[0]
            vol_trend_up = recent_vol.iloc[-1] > recent_vol.iloc[0]
            if price_trend_up and not vol_trend_up:
                result["vp_divergence"] = "顶背离迹象(价涨量缩)"
            elif not price_trend_up and vol_trend_up:
                result["vp_divergence"] = "底背离迹象(价跌量增)"
            else:
                result["vp_divergence"] = "无"
        else:
            result["vp_divergence"] = "数据不足"

        return result
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `cd D:/MyProj/stock/backend && python -m pytest tests/test_technical_analysis.py -v --no-header -q 2>&1 | head -50`
Expected: All tests PASS (now ~22 tests total)

- [ ] **Step 5: Commit**

```bash
cd D:/MyProj/stock/backend
git add app/services/technical_analysis_service.py tests/test_technical_analysis.py
git commit -m "feat: add volatility, pattern, support/resistance, volume analysis to TechnicalAnalysisService"
```

---

### Task 3: Add text summary generation and top-level `analyze` method

**Files:**
- Modify: `app/services/technical_analysis_service.py`
- Modify: `tests/test_technical_analysis.py`

- [ ] **Step 1: Write failing tests for text summary and analyze method**

```python
# Append to tests/test_technical_analysis.py

# ── 文本摘要生成 ──────────────────────────────────────────────────────

def test_generate_summary():
    """generate_summary 返回非空文本摘要"""
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
    """analyze 返回包含 analysis + signals 的完整字典"""
    df = _make_df(120, trend="up")
    result = svc.analyze(df)
    assert "analysis" in result
    assert "signals" in result
    assert isinstance(result["analysis"], str)
    assert isinstance(result["signals"], dict)


def test_analyze_signals_structure():
    """signals 包含所有必要字段"""
    df = _make_df(120, trend="up")
    result = svc.analyze(df)
    s = result["signals"]
    for key in ("trend", "ma_alignment", "macd_signal", "rsi_status", "kdj_signal",
                "boll_position", "volume_status", "patterns", "support_levels", "resistance_levels"):
        assert key in s, f"Missing key: {key}"


def test_analyze_insufficient_data():
    """数据不足时降级，不抛异常"""
    df = _make_df(10, trend="up")
    result = svc.analyze(df)
    assert "analysis" in result
    assert result["analysis"] != ""


def test_analyze_empty_df():
    """空 DataFrame 不抛异常"""
    df = pd.DataFrame(columns=["date", "open", "high", "low", "close", "volume"])
    result = svc.analyze(df)
    assert "analysis" in result
    assert "无法" in result["analysis"] or "不足" in result["analysis"]
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd D:/MyProj/stock/backend && python -m pytest tests/test_technical_analysis.py -v --no-header -q -k "generate_summary or analyze" 2>&1 | head -20`
Expected: FAIL — methods do not exist

- [ ] **Step 3: Implement `_generate_summary` and `analyze` methods**

Add these methods to `TechnicalAnalysisService` in `app/services/technical_analysis_service.py`, before the module-level singleton line:

```python
    # ── 文本摘要生成 ──────────────────────────────────────────────────

    def _generate_summary(
        self,
        trend: dict,
        osc: dict,
        vol: dict,
        patterns: list[dict],
        sr: dict,
        va: dict,
    ) -> str:
        """将各类指标汇总为结构化文本摘要"""
        lines = ["## 技术指标分析"]

        # 趋势
        lines.append("### 趋势指标")
        ma_parts = []
        for w in (5, 10, 20, 60):
            v = trend.get(f"ma{w}")
            ma_parts.append(f"MA{w}: {v:.2f}" if v is not None else f"MA{w}: --")
        lines.append("- " + ", ".join(ma_parts))
        lines.append(f"- 均线排列: {trend.get('ma_alignment', '--')}")
        macd_parts = []
        for k, label in (("dif", "DIF"), ("dea", "DEA"), ("hist", "HIST")):
            v = trend.get(k)
            macd_parts.append(f"{label}={v:.4f}" if v is not None else f"{label}=--")
        macd_str = ", ".join(macd_parts)
        macd_signal = trend.get("macd_signal", "--")
        dif_pos = trend.get("dif_position", "")
        if dif_pos:
            macd_str += f", {macd_signal}, DIF在{dif_pos}"
        lines.append(f"- MACD: {macd_str}")
        lines.append(f"- 趋势判断: {trend.get('trend', '--')}")

        # 震荡
        lines.append("### 震荡指标")
        rsi6 = osc.get("rsi6")
        rsi6s = osc.get("rsi6_status", "")
        rsi14 = osc.get("rsi14")
        rsi14s = osc.get("rsi14_status", "")
        lines.append(f"- RSI(6): {rsi6:.1f} [{rsi6s}]" if rsi6 is not None else "- RSI(6): --")
        lines.append(f"- RSI(14): {rsi14:.1f} [{rsi14s}]" if rsi14 is not None else "- RSI(14): --")
        k, d, j = osc.get("k"), osc.get("d"), osc.get("j")
        kdj_sig = osc.get("kdj_signal", "")
        if k is not None:
            lines.append(f"- KDJ: K={k:.1f}, D={d:.1f}, J={j:.1f}, {kdj_sig}")
        else:
            lines.append("- KDJ: --")
        cci_val = osc.get("cci")
        cci_status = osc.get("cci_status", "")
        lines.append(f"- CCI(14): {cci_val:.1f} [{cci_status}]" if cci_val is not None else "- CCI(14): --")

        # 波动/通道
        lines.append("### 波动/通道")
        b_u, b_m, b_l = vol.get("boll_upper"), vol.get("boll_mid"), vol.get("boll_lower")
        b_pos = vol.get("boll_position", "")
        b_width = vol.get("boll_width", "")
        if b_u is not None:
            lines.append(f"- 布林带: 上轨{b_u:.2f}, 中轨{b_m:.2f}, 下轨{b_l:.2f}, 价格在{b_pos}, 带宽{b_width}")
        else:
            lines.append("- 布林带: 数据不足")
        atr_val = vol.get("atr")
        atr_level = vol.get("atr_level", "")
        lines.append(f"- ATR(14): {atr_val:.2f}, 波动率{atr_level}" if atr_val is not None else "- ATR(14): 数据不足")
        d_u, d_l = vol.get("donch_upper"), vol.get("donch_lower")
        d_break = vol.get("donch_break", "")
        if d_u is not None:
            lines.append(f"- 唐奇安通道: 上轨{d_u:.2f}, 下轨{d_l:.2f}, {d_break}")
        else:
            lines.append("- 唐奇安通道: 数据不足")

        # K线形态
        lines.append("### K线形态")
        if patterns:
            pat_strs = [f"{p['name']}({p['signal']}, {p['days_ago']}日前)" for p in patterns]
            lines.append(f"- 最近5日形态: [{', '.join(pat_strs)}]")
        else:
            lines.append("- 最近5日形态: 无明显形态")

        # 支撑阻力
        sup_strs = [f"{s['price']:.2f}({s['source']})" for s in sr.get("support", [])]
        res_strs = [f"{r['price']:.2f}({r['source']})" for r in sr.get("resistance", [])]
        lines.append(f"- 支撑位: {', '.join(sup_strs) or '无'}")
        lines.append(f"- 阻力位: {', '.join(res_strs) or '无'}")

        # 成交量
        lines.append("### 成交量")
        vr = va.get("volume_ratio")
        vs = va.get("volume_status", "")
        lines.append(f"- 量比: {vr:.2f} [{vs}]" if vr is not None else "- 量比: 数据不足")
        lines.append(f"- 近5日量价关系: {va.get('vp_relation', '--')}")
        lines.append(f"- 量价背离: {va.get('vp_divergence', '--')}")

        return "\n".join(lines)

    # ── 顶层分析方法 ──────────────────────────────────────────────────

    def analyze(self, df: pd.DataFrame) -> dict:
        """对个股进行完整技术分析

        Args:
            df: K线数据 DataFrame，需含 date/open/high/low/close/volume 列

        Returns:
            dict: {"analysis": str, "signals": dict}
        """
        if df is None or df.empty or len(df) < 5:
            return {
                "analysis": "无法获取K线数据或数据不足（少于5根），无法进行技术分析",
                "signals": None,
            }

        try:
            trend_r = self._calc_trend_indicators(df)
        except Exception as e:
            logger.warning(f"趋势指标计算失败: {e}")
            trend_r = {"trend": "计算失败", "ma_alignment": "计算失败", "macd_signal": "计算失败", "dif_position": ""}

        try:
            osc_r = self._calc_oscillation_indicators(df)
        except Exception as e:
            logger.warning(f"震荡指标计算失败: {e}")
            osc_r = {"rsi6": None, "rsi6_status": "计算失败", "rsi14": None, "rsi14_status": "计算失败",
                     "k": None, "d": None, "j": None, "kdj_signal": "计算失败", "cci": None, "cci_status": "计算失败"}

        try:
            vol_r = self._calc_volatility_indicators(df)
        except Exception as e:
            logger.warning(f"波动指标计算失败: {e}")
            vol_r = {"boll_upper": None, "boll_mid": None, "boll_lower": None, "boll_position": "计算失败",
                     "boll_width": "", "atr": None, "atr_level": "计算失败",
                     "donch_upper": None, "donch_lower": None, "donch_break": "计算失败"}

        try:
            patterns_r = self._detect_patterns(df)
        except Exception as e:
            logger.warning(f"K线形态识别失败: {e}")
            patterns_r = []

        try:
            sr_r = self._calc_support_resistance(df)
        except Exception as e:
            logger.warning(f"支撑阻力计算失败: {e}")
            sr_r = {"support": [], "resistance": []}

        try:
            va_r = self._calc_volume_analysis(df)
        except Exception as e:
            logger.warning(f"成交量分析失败: {e}")
            va_r = {"volume_ratio": None, "volume_status": "计算失败", "vp_relation": "计算失败", "vp_divergence": "计算失败"}

        # 生成文本摘要
        analysis = self._generate_summary(trend_r, osc_r, vol_r, patterns_r, sr_r, va_r)

        # 数据不足提示
        if len(df) < 60:
            analysis = "⚠️ 数据不足（少于60根K线），部分指标不可用\n\n" + analysis

        # 结构化信号
        patterns_list = [f"{p['name']}({p['days_ago']}日前)" for p in patterns_r]
        support_prices = [s["price"] for s in sr_r.get("support", [])]
        resistance_prices = [r["price"] for r in sr_r.get("resistance", [])]

        signals = {
            "trend": trend_r.get("trend", "--"),
            "ma_alignment": trend_r.get("ma_alignment", "--"),
            "macd_signal": trend_r.get("macd_signal", "--"),
            "rsi_status": osc_r.get("rsi14_status", "--"),
            "kdj_signal": osc_r.get("kdj_signal", "--"),
            "boll_position": vol_r.get("boll_position", "--"),
            "volume_status": va_r.get("volume_status", "--"),
            "patterns": patterns_list,
            "support_levels": support_prices,
            "resistance_levels": resistance_prices,
        }

        return {"analysis": analysis, "signals": signals}
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `cd D:/MyProj/stock/backend && python -m pytest tests/test_technical_analysis.py -v --no-header -q 2>&1 | head -50`
Expected: All tests PASS (now ~26 tests total)

- [ ] **Step 5: Commit**

```bash
cd D:/MyProj/stock/backend
git add app/services/technical_analysis_service.py tests/test_technical_analysis.py
git commit -m "feat: add summary generation and top-level analyze method to TechnicalAnalysisService"
```

---

### Task 4: Add API route and integrate with research endpoint

**Files:**
- Modify: `app/api/research.py`
- Modify: `tests/test_technical_analysis.py`

- [ ] **Step 1: Write failing test for API endpoint**

```python
# Append to tests/test_technical_analysis.py

# ── API 端点测试 ──────────────────────────────────────────────────────

def test_api_technical_analysis(client):
    """GET /research/technical-analysis 返回正确格式"""
    response = client.get("/research/technical-analysis?code=600519")
    assert response.status_code == 200
    data = response.json()
    assert "code" in data
    assert "analysis" in data
    assert "signals" in data
    assert "latest_price" in data


def test_api_technical_analysis_missing_code(client):
    """缺少 code 参数返回 422"""
    response = client.get("/research/technical-analysis")
    assert response.status_code == 422
```

Note: If no `client` fixture exists, add this conftest at the top of the test file:

```python
import sys
import os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

import pytest
from fastapi.testclient import TestClient

@pytest.fixture
def client():
    from app.main import app
    return TestClient(app)
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd D:/MyProj/stock/backend && python -m pytest tests/test_technical_analysis.py -v --no-header -q -k "api_" 2>&1 | head -20`
Expected: FAIL — route does not exist

- [ ] **Step 3: Add the API route**

Add to `app/api/research.py` — import the service and add the endpoint:

At the top of `research.py`, add import after the existing import:

```python
from app.services.technical_analysis_service import technical_analysis_service
```

At the end of the file (after the `get_northbound` function), add:

```python
@router.get("/technical-analysis")
def get_technical_analysis(code: str = Query(..., description="股票代码")):
    """个股技术分析：趋势/震荡/波动指标 + K线形态 + 支撑阻力 + 成交量"""
    from app.core.data_bridge import data_bridge
    from datetime import datetime, timedelta

    end_date = datetime.now().strftime("%Y-%m-%d")
    start_date = (datetime.now() - timedelta(days=180)).strftime("%Y-%m-%d")

    stock_name = ""
    latest_price = 0.0
    try:
        # 尝试获取股票名称
        info = stock_research_service.eastmoney_stock_info(code)
        stock_name = info.get("name", "")
    except Exception:
        pass

    try:
        df = data_bridge.load_bars_df(code, start_date, end_date, period="1d")
        if df is not None and not df.empty:
            latest_price = float(df["close"].iloc[-1])
            # 腾讯行情获取名称（兜底）
            if not stock_name:
                try:
                    q = stock_research_service.tencent_quote([code])
                    stock_name = q.get(code, {}).get("name", "")
                except Exception:
                    pass
            result = technical_analysis_service.analyze(df)
        else:
            result = {
                "analysis": "无法获取K线数据",
                "signals": None,
            }
    except Exception as e:
        logger.error(f"技术分析数据获取失败: {e}")
        result = {
            "analysis": f"获取行情数据失败: {e}",
            "signals": None,
        }

    return {
        "code": code,
        "stock_name": stock_name,
        "latest_price": latest_price,
        "analysis": result["analysis"],
        "signals": result["signals"],
    }
```

Also add `logger` import if not already present in `research.py`:

```python
import logging
logger = logging.getLogger(__name__)
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `cd D:/MyProj/stock/backend && python -m pytest tests/test_technical_analysis.py -v --no-header -q -k "api_" 2>&1 | head -20`
Expected: PASS (may need to skip if data_bridge unavailable in test env — that's acceptable, the core logic is tested in Tasks 1-3)

Note: API tests that require real data sources may need to be marked with `@pytest.mark.skip(reason="requires live data source")` if running in an environment without market data access.

- [ ] **Step 5: Commit**

```bash
cd D:/MyProj/stock/backend
git add app/api/research.py tests/test_technical_analysis.py
git commit -m "feat: add /research/technical-analysis API endpoint"
```

---

### Task 5: Add frontend API method and scenario button

**Files:**
- Modify: `frontend/src/api/research.ts`
- Modify: `frontend/src/pages/AIAssistant.tsx`

- [ ] **Step 1: Add API method to research.ts**

In `frontend/src/api/research.ts`, add before the closing `};`:

```typescript
  // 技术分析
  technicalAnalysis: (code: string) => api.get<Record<string, any>>(`/research/technical-analysis?code=${code}`),
```

This goes right after the `northbound` method (line 70), before the closing `};` on line 71.

- [ ] **Step 2: Add scenario button to AIAssistant.tsx**

In `frontend/src/pages/AIAssistant.tsx`:

1. Add `Activity` to the lucide-react import (line 4-31). Add it to the import list:

```typescript
  Activity,
```

2. Add the new scenario to the `quickScenarios` array. Insert it after the `批量对比` scenario (around line 253), before the closing `];`:

```typescript
  {
    icon: Activity, label: '技术分析', color: 'bg-pink-50 text-pink-600 border-pink-200',
    prompt: '帮我分析一下 688017 的技术面',
    fetchData: async (code) => {
      const d = await researchApi.technicalAnalysis(code);
      return { summary: d.analysis || '技术分析数据获取失败' };
    },
  },
```

- [ ] **Step 3: Verify the frontend compiles**

Run: `cd D:/MyProj/stock/frontend && npx tsc --noEmit 2>&1 | head -20`
Expected: No type errors related to the new code

- [ ] **Step 4: Commit**

```bash
cd D:/MyProj/stock
git add frontend/src/api/research.ts frontend/src/pages/AIAssistant.tsx
git commit -m "feat: add technical analysis scenario to AI Assistant"
```

---

### Task 6: End-to-end smoke test

**Files:** None (manual verification)

- [ ] **Step 1: Start backend and verify API endpoint**

Run: `cd D:/MyProj/stock/backend && python -c "from app.services.technical_analysis_service import technical_analysis_service; import pandas as pd; import numpy as np; n=120; c=20+np.arange(n)*0.1; df=pd.DataFrame({'date':pd.date_range('2025-01-01',periods=n,freq='B'),'open':c-0.05,'high':c+0.2,'low':c-0.2,'close':c,'volume':np.random.randint(100000,500000,n).astype(float)}); r=technical_analysis_service.analyze(df); print(r['analysis'][:200]); print('---SIGNALS---'); print(r['signals'])"`

Expected: Prints the structured text summary and signals dict without errors.

- [ ] **Step 2: Commit any final fixes**

If any issues found during smoke test, fix and commit.

---

## Self-Review Checklist

**1. Spec coverage:**
- ✅ Trend indicators (MA/MACD/trend judgment) → Task 1
- ✅ Oscillation indicators (RSI/KDJ/CCI) → Task 1
- ✅ Volatility/channel (Bollinger/ATR/Donchian) → Task 2
- ✅ K线形态 (6 patterns) → Task 2
- ✅ Support/resistance → Task 2
- ✅ Volume analysis → Task 2
- ✅ Text summary generation → Task 3
- ✅ API route → Task 4
- ✅ Frontend scenario button → Task 5
- ✅ Error handling (insufficient data, calculation failure) → Task 3
- ✅ Testing → Tasks 1-4

**2. Placeholder scan:** No TBD/TODO/implement later found. All steps contain actual code.

**3. Type consistency:**
- `analyze()` returns `{"analysis": str, "signals": dict}` — consistent across Task 3, Task 4, and Task 5
- `signals` dict keys match between `_generate_summary` and `analyze` — verified
- Frontend `fetchData` uses `d.analysis` matching the API response field name — verified
- `technical_analysis_service` singleton name consistent between service file and API route import — verified

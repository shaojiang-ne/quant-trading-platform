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
                result["macd_signal"] = "金叉" if dif.iloc[-2] <= dea.iloc[-2] else "金叉状态"
            else:
                result["macd_signal"] = "死叉" if dif.iloc[-2] >= dea.iloc[-2] else "死叉状态"
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
                # 当 avg_loss=0 时 RSI 为 NaN（纯上涨），视为 100
                if np.isnan(val):
                    val = 100.0
                result[label] = round(val, 1)
                if val > 80:
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
            bw = (result["boll_upper"] - result["boll_lower"]) / result["boll_mid"]
            bw_prev = float((upper.iloc[-2] - lower.iloc[-2]) / mid.iloc[-2]) if len(close) > 20 else bw
            result["boll_width"] = "收窄" if bw < bw_prev else "扩张"
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

        # 判断前期趋势
        lookback_start = max(0, n - 15)
        recent_trend = "neutral"
        if n > lookback_start + 3:
            prev_close = df["close"].iloc[lookback_start:n-5]
            if len(prev_close) >= 3:
                pct_change = (prev_close.iloc[-1] - prev_close.iloc[0]) / prev_close.iloc[0]
                if pct_change > 0.005:
                    recent_trend = "up"
                elif pct_change < -0.005:
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

            # 十字星（仅当上下影线较均匀时才判定为十字星，
            # 若下影线远大于上影线则优先判锤子线，上影线远大于下影线则优先判倒锤子）
            is_doji = body < total_range * 0.1
            shadow_asymmetry = abs(lower_shadow - upper_shadow) / total_range if total_range > 0 else 0

            if is_doji and shadow_asymmetry < 0.5:
                patterns.append({"name": "十字星", "signal": "中性/反转", "days_ago": days_ago})
                continue

            # 锤子线（允许十字星型锤子：open≈close 但下影线很长）
            if lower_shadow > max(body * 2, total_range * 0.4) and upper_shadow < max(body * 0.3, total_range * 0.1) and recent_trend == "down":
                patterns.append({"name": "锤子线", "signal": "看涨", "days_ago": days_ago})

            # 倒锤子
            elif upper_shadow > max(body * 2, total_range * 0.4) and lower_shadow < max(body * 0.3, total_range * 0.1) and recent_trend == "down":
                patterns.append({"name": "倒锤子", "signal": "看涨", "days_ago": days_ago})

            # 十字星型但影线不对称，已跳过上面的 doji 检查，不再单独分类

            # 吞没/刺透形态（与锤子线/倒锤子互斥，避免同根K线重复识别）
            elif i > 0:
                prev_o = float(df["open"].iloc[i - 1])
                prev_c = float(df["close"].iloc[i - 1])
                prev_body_top = max(prev_o, prev_c)
                prev_body_bottom = min(prev_o, prev_c)
                curr_body_top = max(o, c)
                curr_body_bottom = min(o, c)

                # 看涨吞没
                if prev_c < prev_o and c > o and curr_body_bottom <= prev_body_bottom and curr_body_top >= prev_body_top and recent_trend == "down":
                    patterns.append({"name": "看涨吞没", "signal": "看涨", "days_ago": days_ago})

                # 看跌吞没
                elif prev_c > prev_o and c < o and curr_body_bottom <= prev_body_bottom and curr_body_top >= prev_body_top and recent_trend == "up":
                    patterns.append({"name": "看跌吞没", "signal": "看跌", "days_ago": days_ago})

                # 刺透形态
                elif prev_c < prev_o and c > o:
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

        # MA20/MA60
        for w in (20, 60):
            if len(close) >= w:
                ma_val = round(float(sma(close, w).iloc[-1]), 2)
                if ma_val < price:
                    result["support"].append({"price": ma_val, "source": f"MA{w}"})
                else:
                    result["resistance"].append({"price": ma_val, "source": f"MA{w}"})

        # 布林带
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

        # 密集成交区
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
        """对个股进行完整技术分析"""
        if df is None or df.empty or len(df) < 5:
            return {
                "analysis": "无法获取K线数据或数据不足（少于5根），无法进行技术分析",
                "signals": None,
            }

        try:
            trend_r = self._calc_trend_indicators(df)
        except Exception as e:
            logger.warning(f"趋势指标计算失败: {e}")
            trend_r = {"trend": "计算失败", "ma_alignment": "计算失败", "macd_signal": "计算失败", "dif_position": "", "ma5": None, "ma10": None, "ma20": None, "ma60": None, "dif": None, "dea": None, "hist": None}

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

        analysis = self._generate_summary(trend_r, osc_r, vol_r, patterns_r, sr_r, va_r)

        if len(df) < 60:
            analysis = "⚠️ 数据不足（少于60根K线），部分指标不可用\n\n" + analysis

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


technical_analysis_service = TechnicalAnalysisService()

import logging

import numpy as np
import pandas as pd
from strategies.base import BaseStrategy

logger = logging.getLogger(__name__)


class FourDimensionStrategy(BaseStrategy):
    """四维擒龙：放量+MACD金叉+MACD零轴上方+均线多头+近期新高附近
    至少命中3个条件
    """
    name = "four_dimension"
    description = "四维擒龙"

    def __init__(self, params: dict | None = None):
        super().__init__(params)
        p = self.params
        self.min_conditions = p.get("min_conditions", 4)
        self.volume_ratio = p.get("volume_ratio", 2.0)
        self.macd_fast = p.get("macd_fast", 12)
        self.macd_slow = p.get("macd_slow", 26)
        self.macd_signal = p.get("macd_signal", 9)
        self.near_high_days = p.get("near_high_days", 20)
        self.near_high_pct = p.get("near_high_pct", 5)

    # 信号条件（事件型，必须至少命中一个）
    SIGNAL_CONDITIONS = {"放量", "MACD金叉"}

    def scan(self, pool: pd.DataFrame, data, **kwargs) -> list[dict]:
        codes = pool["code"].tolist()
        quotes_map = {c: data.get_daily_quote(c, 60) for c in codes}

        hits = []
        for _, row in pool.iterrows():
            code = row["code"]
            df = quotes_map.get(code)
            if df is None or df.empty or len(df) < 30:
                continue
            try:
                conditions = self._check_conditions(df, code)
                has_signal = bool(set(conditions) & self.SIGNAL_CONDITIONS)
                if has_signal and len(conditions) >= self.min_conditions:
                    hits.append({
                        "code": code,
                        "name": row.get("name", ""),
                        "industry": row.get("industry", ""),
                        "conditions": conditions,
                    })
            except Exception as e:
                logger.debug(f"{code} 四维擒龙计算失败: {e}")
        return hits

    def _check_conditions(self, df: pd.DataFrame, code: str) -> list[str]:
        close = df["close"].values
        high = df["high"].values
        volume = df["volume"].values
        n = len(close)

        conditions = []

        # 1. 放量（最新成交量 > 前5日均量×volume_ratio）
        if n >= 6:
            today_vol = volume[-1]
            avg_vol_5 = np.mean(volume[-6:-1])
            if avg_vol_5 > 0 and today_vol > avg_vol_5 * self.volume_ratio:
                conditions.append("放量")

        # 2. MACD金叉（DIF上穿DEA）
        dif, dea, _ = self.calc_macd(close, self.macd_fast, self.macd_slow, self.macd_signal)
        if dif is not None and dea is not None and len(dif) >= 2 and len(dea) >= 2:
            if dif[-2] <= dea[-2] and dif[-1] > dea[-1]:
                conditions.append("MACD金叉")
            # 3. MACD零轴上方（DIF>0）
            if not np.isnan(dif[-1]) and dif[-1] > 0:
                conditions.append("MACD零轴上方")

        # 4. 均线多头（5日>10日>20日）
        if n >= 20:
            ma5 = np.mean(close[-5:])
            ma10 = np.mean(close[-10:])
            ma20 = np.mean(close[-20:])
            if ma5 > ma10 > ma20:
                conditions.append("均线多头")

        # 5. 近期新高附近（现价接近近N日最高价，距最高价<near_high_pct%）
        if n >= self.near_high_days and close[-1] > 0:
            recent_high = np.max(high[-self.near_high_days:])
            space = (recent_high - close[-1]) / close[-1] * 100
            if space < self.near_high_pct:
                conditions.append("近期新高附近")

        return conditions

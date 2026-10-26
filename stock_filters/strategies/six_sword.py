import logging

import numpy as np
import pandas as pd
from strategies.base import BaseStrategy

logger = logging.getLogger(__name__)


class SixSwordStrategy(BaseStrategy):
    """六脉神剑：放量+MACD金叉+KDJ金叉+RSI适中+站上5日线+5日均量放大
    至少命中min_conditions个条件
    """
    name = "six_sword"
    description = "六脉神剑"

    def __init__(self, params: dict | None = None):
        super().__init__(params)
        p = self.params
        self.min_conditions = p.get("min_conditions", 5)
        self.rsi_period = p.get("rsi_period", 14)
        self.rsi_upper = p.get("rsi_upper", 70)
        self.kdj_period = p.get("kdj_period", 9)
        self.kdj_k_smooth = p.get("kdj_k_smooth", 3)
        self.kdj_d_smooth = p.get("kdj_d_smooth", 3)
        self.macd_fast = p.get("macd_fast", 12)
        self.macd_slow = p.get("macd_slow", 26)
        self.macd_signal = p.get("macd_signal", 9)
        self.volume_ratio = p.get("volume_ratio", 1.5)

    # 信号条件（事件型，必须至少命中一个）
    SIGNAL_CONDITIONS = {"放量", "MACD金叉", "KDJ金叉"}

    def scan(self, pool: pd.DataFrame, data, **kwargs) -> list[dict]:
        codes = pool["code"].tolist()
        quotes_map = {c: data.get_daily_quote(c, 60) for c in codes}

        hits = []
        for _, row in pool.iterrows():
            code = row["code"]
            df = quotes_map.get(code)
            if df is None or df.empty or len(df) < 21:
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
                logger.debug(f"{code} 六脉神剑计算失败: {e}")
        return hits

    def _check_conditions(self, df: pd.DataFrame, code: str) -> list[str]:
        close = df["close"].values
        high = df["high"].values
        low = df["low"].values
        volume = df["volume"].values
        n = len(close)

        conditions = []

        # 1. 放量（最新成交量 > 前5日均量×volume_ratio）
        if n >= 6:
            today_vol = volume[-1]
            avg_vol_5 = np.mean(volume[-6:-1])
            if avg_vol_5 > 0 and today_vol > avg_vol_5 * self.volume_ratio:
                conditions.append("放量")

        # 2. MACD金叉
        macd_line, signal_line, _ = self.calc_macd(close, self.macd_fast, self.macd_slow, self.macd_signal)
        if macd_line is not None and len(macd_line) >= 2 and len(signal_line) >= 2:
            if macd_line[-2] <= signal_line[-2] and macd_line[-1] > signal_line[-1]:
                conditions.append("MACD金叉")

        # 3. KDJ金叉
        k, d, _ = self.calc_kdj(high, low, close, self.kdj_period, self.kdj_k_smooth, self.kdj_d_smooth)
        if n >= 2:
            if k[-2] <= d[-2] and k[-1] > d[-1]:
                conditions.append("KDJ金叉")

        # 4. RSI < rsi_upper（使用递推SMA方式，与通达信一致）
        rsi = self.calc_rsi_sma(close, self.rsi_period)
        if len(rsi) > 0 and rsi[-1] < self.rsi_upper:
            conditions.append(f"RSI<{self.rsi_upper}")

        # 5. 站上5日线
        if n >= 5:
            ma5 = np.mean(close[-5:])
            if close[-1] > ma5:
                conditions.append("站上5日线")

        # 6. 5日均量放大（近5日均量 > 前5日均量×1.2）
        if n >= 10:
            vol_recent = np.mean(volume[-5:])
            vol_prev = np.mean(volume[-10:-5])
            if vol_prev > 0 and vol_recent > vol_prev * 1.2:
                conditions.append("5日均量放大")

        return conditions

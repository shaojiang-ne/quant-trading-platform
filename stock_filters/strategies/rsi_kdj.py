import logging

import numpy as np
import pandas as pd
from strategies.base import BaseStrategy

logger = logging.getLogger(__name__)


class RsiKdjStrategy(BaseStrategy):
    """RSI+KDJ共振：近N日RSI曾超卖+KDJ低位金叉+当日涨幅达标+放量
    所有条件必须同时满足
    """
    name = "rsi_kdj"
    description = "RSI+KDJ共振"

    def __init__(self, params: dict | None = None):
        super().__init__(params)
        p = self.params
        self.rsi_period = p.get("rsi_period", 6)
        self.rsi_upper = p.get("rsi_upper", 40)
        self.rsi_lookback = p.get("rsi_lookback", 5)  # 近N日内RSI曾低于阈值
        self.kdj_period = p.get("kdj_period", 9)
        self.kdj_k_smooth = p.get("kdj_k_smooth", 3)
        self.kdj_d_smooth = p.get("kdj_d_smooth", 3)
        self.kdj_j_upper = p.get("kdj_j_upper", 50)
        self.change_min = p.get("change_min", p.get("yesterday_change_min", 1.0))
        self.change_max = p.get("change_max", p.get("yesterday_change_max", 3.5))
        self.volume_ratio = p.get("volume_ratio", 1.5)

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
                if all(conditions.values()):
                    hits.append({
                        "code": code,
                        "name": row.get("name", ""),
                        "industry": row.get("industry", ""),
                        "conditions": [k for k, v in conditions.items() if v],
                    })
            except Exception as e:
                logger.debug(f"{code} RSI+KDJ共振计算失败: {e}")
        return hits

    def _check_conditions(self, df: pd.DataFrame, code: str) -> dict[str, bool]:
        close = df["close"].values
        high = df["high"].values
        low = df["low"].values
        volume = df["volume"].values
        n = len(close)

        conditions = {}

        # 1. 当日涨幅达标（最新K线涨幅在min~max之间）
        if n >= 2 and close[-2] > 0:
            change_pct = (close[-1] / close[-2] - 1) * 100
            conditions["涨幅达标"] = (
                self.change_min <= change_pct <= self.change_max
            )
        else:
            conditions["涨幅达标"] = False

        # 2. 放量（最新成交量 > 前5日均量×volume_ratio）
        if n >= 6:
            today_vol = volume[-1]
            avg_vol_5 = np.mean(volume[-6:-1])
            conditions["放量"] = avg_vol_5 > 0 and today_vol > avg_vol_5 * self.volume_ratio
        else:
            conditions["放量"] = False

        # 3. 近N日内RSI曾超卖（近rsi_lookback天内RSI最低值 < rsi_upper）
        rsi = self.calc_rsi_sma(close, self.rsi_period)
        if len(rsi) >= self.rsi_lookback:
            rsi_low = np.min(rsi[-self.rsi_lookback:])
            conditions["近期RSI超卖"] = rsi_low < self.rsi_upper
        else:
            conditions["近期RSI超卖"] = False

        # 4. KDJ低位金叉 (K上穿D 且 J<=kdj_j_upper)
        k, d, j = self.calc_kdj(high, low, close, self.kdj_period, self.kdj_k_smooth, self.kdj_d_smooth)
        conditions["KDJ低位金叉"] = (
            n >= 2 and k[-2] <= d[-2] and k[-1] > d[-1] and j[-1] <= self.kdj_j_upper
        )

        return conditions

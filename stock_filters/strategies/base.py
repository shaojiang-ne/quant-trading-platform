from abc import ABC, abstractmethod

import numpy as np
import pandas as pd
from data.interface import DataSourceInterface


class BaseStrategy(ABC):
    name: str
    description: str
    params: dict = {}

    def __init__(self, params: dict | None = None):
        if params:
            self.params = params

    @abstractmethod
    def scan(self, pool: pd.DataFrame, data: DataSourceInterface, **kwargs) -> list[dict]:
        """扫描股票池，返回命中结果
        返回: [{"code": "000001", "name": "平安银行", "reason": "...", "details": {...}}]
        """

    # ==================== 公共技术指标计算 ====================

    @staticmethod
    def calc_ema(data: np.ndarray, period: int) -> np.ndarray | None:
        """计算EMA，初始值使用第一个有效窗口的SMA，跳过前导NaN"""
        # 找到第一个有效（非NaN）位置
        first_valid = 0
        while first_valid < len(data) and np.isnan(data[first_valid]):
            first_valid += 1
        valid_data = data[first_valid:]
        if len(valid_data) < period:
            return None

        ema = np.empty(len(data))
        ema[:first_valid] = np.nan
        ema[first_valid:first_valid + period - 1] = np.nan
        ema[first_valid + period - 1] = np.mean(valid_data[:period])
        multiplier = 2 / (period + 1)
        for i in range(period, len(valid_data)):
            ema[first_valid + i] = valid_data[i] * multiplier + ema[first_valid + i - 1] * (1 - multiplier)
        return ema

    def calc_macd(self, close: np.ndarray, fast: int = 12, slow: int = 26, signal: int = 9):
        """计算MACD (DIF, DEA, MACD柱)"""
        if len(close) < slow:
            return None, None, None

        ema_fast = self.calc_ema(close, fast)
        ema_slow = self.calc_ema(close, slow)

        if ema_fast is None or ema_slow is None:
            return None, None, None

        dif = ema_fast - ema_slow
        dea = self.calc_ema(dif, signal)
        if dea is None:
            return dif, None, None

        macd = 2 * (dif - dea)
        return dif, dea, macd

    @staticmethod
    def calc_rsi_sma(close: np.ndarray, period: int) -> np.ndarray:
        """SMA递推方式计算RSI，与通达信SMA(MAX(C-REF(C,1),0),N,1)/SMA(ABS(C-REF(C,1)),N,1)*100一致"""
        delta = np.diff(close)
        gain = np.where(delta > 0, delta, 0.0)
        loss = np.abs(delta)

        n = len(gain)
        if n < period:
            return np.array([50.0])

        avg_gain = np.empty(n - period + 1)
        avg_loss = np.empty(n - period + 1)

        avg_gain[0] = np.mean(gain[:period])
        avg_loss[0] = np.mean(loss[:period])

        for i in range(1, len(avg_gain)):
            avg_gain[i] = (gain[period - 1 + i] + (period - 1) * avg_gain[i - 1]) / period
            avg_loss[i] = (loss[period - 1 + i] + (period - 1) * avg_loss[i - 1]) / period

        rsi = 100 * avg_gain / (avg_gain + avg_loss + 1e-10)
        return rsi

    @staticmethod
    def calc_kdj(high: np.ndarray, low: np.ndarray, close: np.ndarray,
                 period: int = 9, k_smooth: int = 3, d_smooth: int = 3):
        """SMA方式计算KDJ，与通达信一致"""
        n = len(close)
        k = np.full(n, 50.0)
        d = np.full(n, 50.0)
        j = np.full(n, 50.0)

        for i in range(period - 1, n):
            low_min = np.min(low[i - period + 1:i + 1])
            high_max = np.max(high[i - period + 1:i + 1])
            rsv = (close[i] - low_min) / (high_max - low_min + 1e-10) * 100

            k[i] = (rsv + (k_smooth - 1) * k[i - 1]) / k_smooth
            d[i] = (k[i] + (d_smooth - 1) * d[i - 1]) / d_smooth
            j[i] = 3 * k[i] - 2 * d[i]

        return k, d, j

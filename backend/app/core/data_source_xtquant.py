"""
Xtquant 数据源

封装现有 market_service（stock_data 微服务），作为数据源接口实现。
"""

import logging

import pandas as pd

from app.core.data_source import DataSourceProvider
from app.services.market_service import market_service

logger = logging.getLogger(__name__)

# stock_data 周期映射
_PERIOD_MAP = {
    "1m": "1m", "5m": "5m", "15m": "15m", "30m": "30m",
    "60m": "60m", "1h": "1h", "1d": "1d", "1w": "1w",
}


class XtquantDataSource(DataSourceProvider):

    def get_klines(
        self,
        symbol: str,
        period: str,
        start: str,
        end: str,
        dividend_type: str = "front",
    ) -> pd.DataFrame:
        xt_period = _PERIOD_MAP.get(period)
        if not xt_period:
            logger.error(f"xtquant 不支持周期: {period}")
            return pd.DataFrame()

        # stock_data 需要的时间格式 YYYYMMDD
        start_fmt = start.replace("-", "")
        end_fmt = end.replace("-", "")

        df = market_service.get_klines(
            symbol=symbol,
            period=xt_period,
            start_time=start_fmt,
            end_time=end_fmt,
            dividend_type=dividend_type,
        )

        if df.empty:
            return pd.DataFrame()

        return self._normalize(df)

    def get_index_klines(
        self,
        index_code: str,
        period: str,
        start: str,
        end: str,
    ) -> pd.DataFrame:
        xt_period = _PERIOD_MAP.get(period, "1d")

        start_fmt = start.replace("-", "")
        end_fmt = end.replace("-", "")

        df = market_service.get_klines(
            symbol=index_code,
            period=xt_period,
            start_time=start_fmt,
            end_time=end_fmt,
            dividend_type="none",
        )

        if df.empty:
            return pd.DataFrame()

        return self._normalize(df)

    def _normalize(self, df: pd.DataFrame) -> pd.DataFrame:
        """将 stock_data 返回的 DataFrame 统一为标准格式"""
        if df.empty:
            return pd.DataFrame()

        # stock_data 返回的 df 已经有 open/high/low/close/volume/amount 列
        # 但 index 是日期字符串，需要转为 Timestamp
        df = df.reset_index()
        df = df.rename(columns={"date": "date"})

        # index 列名可能为 "date" 或其他
        date_col = None
        for col in df.columns:
            if col.lower() in ("date", "datetime", "trade_time"):
                date_col = col
                break

        if date_col is None:
            # 尝试使用第一列作为日期
            date_col = df.columns[0]

        df["date"] = pd.to_datetime(df[date_col], errors="coerce")

        for col in ["open", "high", "low", "close", "volume", "amount"]:
            if col in df.columns:
                df[col] = pd.to_numeric(df[col], errors="coerce").fillna(0)
            else:
                df[col] = 0.0

        df = df.dropna(subset=["date"])
        df = df.sort_values("date").reset_index(drop=True)
        return df[["date", "open", "high", "low", "close", "volume", "amount"]]

    def is_available(self) -> bool:
        return market_service.is_available()

    def get_name(self) -> str:
        return "xtquant"
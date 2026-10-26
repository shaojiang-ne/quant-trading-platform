"""
Baostock 数据源

使用 baostock 获取 A 股和指数K线数据，完全免费开源。
分钟线仅支持 5m/15m/30m/60m，不支持 1m。
"""

import logging
from datetime import datetime
from typing import Optional

import pandas as pd

from app.core.data_source import DataSourceProvider

logger = logging.getLogger(__name__)

# baostock 周期映射
_PERIOD_MAP = {
    "5m": "5", "15m": "15", "30m": "30",
    "60m": "60", "1h": "60", "1d": "d", "1w": "w",
}

# 复权方式映射
_ADJUST_MAP = {
    "front": "2",
    "back": "1",
    "none": "3",
}

# 日线字段
_DAILY_FIELDS = "date,open,high,low,close,volume,amount"
# 分钟线字段
_MIN_FIELDS = "date,time,open,high,low,close,volume,amount"


def _to_bs_symbol(symbol: str) -> str:
    """600519.SH → sh.600519, 000001.SZ → sz.000001"""
    parts = symbol.split(".")
    if len(parts) == 2:
        code, suffix = parts
        return f"{suffix.lower()}.{code}"
    return symbol


class BaostockDataSource(DataSourceProvider):

    def __init__(self):
        self._logged_in = False

    def _ensure_login(self):
        """确保 baostock 已登录"""
        if self._logged_in:
            return
        try:
            import baostock as bs
            lg = bs.login()
            if lg.error_code != "0":
                logger.error(f"baostock 登录失败: {lg.error_msg}")
                return
            self._logged_in = True
        except ImportError:
            logger.error("baostock 未安装，请运行: pip install baostock")

    def _logout(self):
        """登出 baostock"""
        if self._logged_in:
            try:
                import baostock as bs
                bs.logout()
            except Exception:
                pass
            self._logged_in = False

    def get_klines(
        self,
        symbol: str,
        period: str,
        start: str,
        end: str,
        dividend_type: str = "front",
    ) -> pd.DataFrame:
        if period == "1m":
            logger.error("baostock 不支持 1m 分钟线")
            return pd.DataFrame()

        bs_period = _PERIOD_MAP.get(period)
        if not bs_period:
            logger.error(f"baostock 不支持周期: {period}")
            return pd.DataFrame()

        bs_symbol = _to_bs_symbol(symbol)
        adjust = _ADJUST_MAP.get(dividend_type, "2")

        if _is_index_code(symbol):
            return self.get_index_klines(symbol, period, start, end)

        self._ensure_login()
        try:
            import baostock as bs
        except ImportError:
            return pd.DataFrame()

        is_daily = period in ("1d", "1w")
        fields = _DAILY_FIELDS if is_daily else _MIN_FIELDS

        try:
            rs = bs.query_history_k_data_plus(
                bs_symbol, fields,
                start_date=start, end_date=end,
                frequency=bs_period, adjustflag=adjust,
            )
        except Exception as e:
            logger.error(f"baostock 获取K线失败 {symbol} {period}: {e}")
            return pd.DataFrame()

        if rs is None:
            return pd.DataFrame()
        rows = []
        while rs.error_code == "0" and rs.next():
            rows.append(rs.get_row_data())

        if not rows:
            return pd.DataFrame()

        df = pd.DataFrame(rows, columns=fields.split(","))
        return self._normalize(df, is_daily=is_daily)

    def get_index_klines(
        self,
        index_code: str,
        period: str,
        start: str,
        end: str,
    ) -> pd.DataFrame:
        bs_period = _PERIOD_MAP.get(period, "d")
        bs_symbol = _to_bs_symbol(index_code)

        self._ensure_login()
        try:
            import baostock as bs
        except ImportError:
            return pd.DataFrame()

        is_daily = period in ("1d", "1w")
        fields = _DAILY_FIELDS if is_daily else _MIN_FIELDS

        try:
            rs = bs.query_history_k_data_plus(
                bs_symbol, fields,
                start_date=start, end_date=end,
                frequency=bs_period,
            )
        except Exception as e:
            logger.error(f"baostock 获取指数K线失败 {index_code} {period}: {e}")
            return pd.DataFrame()

        if rs is None:
            return pd.DataFrame()
        rows = []
        while rs.error_code == "0" and rs.next():
            rows.append(rs.get_row_data())

        if not rows:
            return pd.DataFrame()

        df = pd.DataFrame(rows, columns=fields.split(","))
        return self._normalize(df, is_daily=is_daily)

    def _normalize(self, df: pd.DataFrame, is_daily: bool) -> pd.DataFrame:
        """将 baostock 返回的 DataFrame 统一为标准格式"""
        if df.empty:
            return pd.DataFrame()

        # 分钟线有 time 列，格式为 YYYYMMDDHHMMSSfff，直接解析
        if not is_daily and "time" in df.columns:
            df["date"] = pd.to_datetime(
                df["time"].astype(str).str[:14],
                format="%Y%m%d%H%M%S",
                errors="coerce",
            )
            df = df.drop(columns=["time"])

        df["date"] = pd.to_datetime(df["date"], errors="coerce")

        for col in ["open", "high", "low", "close", "volume", "amount"]:
            if col in df.columns:
                df[col] = pd.to_numeric(df[col], errors="coerce").fillna(0)
            else:
                df[col] = 0.0

        df = df.dropna(subset=["date"])
        df = df.sort_values("date").reset_index(drop=True)
        return df[["date", "open", "high", "low", "close", "volume", "amount"]]

    def is_available(self) -> bool:
        try:
            import baostock  # noqa: F401
            return True
        except ImportError:
            return False

    def get_name(self) -> str:
        return "baostock"


def _is_index_code(symbol: str) -> bool:
    """判断是否为指数代码"""
    parts = symbol.split(".")
    code = parts[0]
    suffix = parts[1] if len(parts) > 1 else ""
    return (suffix == "SH" and code.startswith("000")) or \
           (suffix == "SZ" and code.startswith("399"))

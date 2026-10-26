"""
Efinance 数据源

使用 efinance 获取 A 股和指数K线数据，数据来自东方财富。
比 akshare 更轻量、更稳定，可作为 akshare 的备选。
"""

import logging
import threading
import time
import random

import pandas as pd

from app.core.data_source import DataSourceProvider

logger = logging.getLogger(__name__)

# efinance 周期映射
_PERIOD_MAP = {
    "1m": "1", "5m": "5", "15m": "15", "30m": "30",
    "60m": "60", "1h": "60", "1d": "101", "1w": "102",
}

# 复权映射：klt_type 101=不复权, 102=前复权
_ADJUST_MAP = {
    "front": "102",
    "back": "101",  # efinance 不直接支持后复权，用前复权替代
    "none": "101",
}


def _strip_suffix(symbol: str) -> str:
    """600519.SH → 600519"""
    return symbol.split(".")[0] if "." in symbol else symbol


def _is_index(symbol: str) -> bool:
    """判断是否为指数"""
    parts = symbol.split(".")
    code = parts[0]
    suffix = parts[1] if len(parts) > 1 else ""
    return (suffix == "SH" and code.startswith("000")) or \
           (suffix == "SZ" and code.startswith("399"))


class EfinanceDataSource(DataSourceProvider):
    _last_call_time: float = 0
    _call_lock = threading.Lock()
    _MIN_CALL_INTERVAL: float = 1.5

    @classmethod
    def _rate_limit(cls):
        """东财请求限流：调用间隔 ≥1.5s + 随机抖动 0-0.5s"""
        with cls._call_lock:
            now = time.time()
            elapsed = now - cls._last_call_time
            min_interval = cls._MIN_CALL_INTERVAL + random.uniform(0, 0.5)
            if elapsed < min_interval:
                time.sleep(min_interval - elapsed)
            cls._last_call_time = time.time()

    def get_klines(
        self,
        symbol: str,
        period: str,
        start: str,
        end: str,
        dividend_type: str = "front",
    ) -> pd.DataFrame:
        self._rate_limit()
        if _is_index(symbol):
            return self.get_index_klines(symbol, period, start, end)

        try:
            import efinance as ef
        except ImportError:
            logger.error("efinance 未安装，请运行: pip install efinance")
            return pd.DataFrame()

        klt = _PERIOD_MAP.get(period)
        if not klt:
            logger.error(f"efinance 不支持周期: {period}")
            return pd.DataFrame()

        fqt = _ADJUST_MAP.get(dividend_type, "102")
        code = _strip_suffix(symbol)

        try:
            if period in ("1d", "1w"):
                df = ef.stock.get_quote_history(
                    code, klt=klt, fqt=fqt,
                    beg=start.replace("-", ""), end=end.replace("-", ""),
                )
            else:
                df = ef.stock.get_quote_history(
                    code, klt=klt, fqt=fqt,
                    beg=start.replace("-", ""), end=end.replace("-", ""),
                )
        except Exception as e:
            logger.error(f"efinance 获取K线失败 {symbol} {period}: {e}")
            return pd.DataFrame()

        if df is None or df.empty:
            return pd.DataFrame()

        return self._normalize(df)

    def get_index_klines(
        self,
        index_code: str,
        period: str,
        start: str,
        end: str,
    ) -> pd.DataFrame:
        self._rate_limit()
        try:
            import efinance as ef
        except ImportError:
            logger.error("efinance 未安装，请运行: pip install efinance")
            return pd.DataFrame()

        klt = _PERIOD_MAP.get(period, "101")
        code = _strip_suffix(index_code)

        try:
            df = ef.stock.get_quote_history(
                code, klt=klt, fqt="101",
                beg=start.replace("-", ""), end=end.replace("-", ""),
            )
        except Exception as e:
            logger.error(f"efinance 获取指数K线失败 {index_code} {period}: {e}")
            return pd.DataFrame()

        if df is None or df.empty:
            return pd.DataFrame()

        return self._normalize(df)

    def _normalize(self, df: pd.DataFrame) -> pd.DataFrame:
        """将 efinance 返回的 DataFrame 统一为标准格式"""
        if df.empty:
            return pd.DataFrame()

        col_map = {}
        for col in df.columns:
            cl = str(col).lower().strip()
            if cl in ("日期", "date", "day", "时间", "time"):
                col_map[col] = "date"
            elif cl in ("开盘", "open", "开盘价"):
                col_map[col] = "open"
            elif cl in ("最高", "high", "最高价"):
                col_map[col] = "high"
            elif cl in ("最低", "low", "最低价"):
                col_map[col] = "low"
            elif cl in ("收盘", "close", "收盘价"):
                col_map[col] = "close"
            elif cl in ("成交量", "volume"):
                col_map[col] = "volume"
            elif cl in ("成交额", "amount", "成交额(元)"):
                col_map[col] = "amount"

        df = df.rename(columns=col_map)

        if "date" not in df.columns:
            return pd.DataFrame()

        df["date"] = pd.to_datetime(df["date"], errors="coerce")

        for col in ["open", "high", "low", "close", "volume", "amount"]:
            if col in df.columns:
                df[col] = pd.to_numeric(df[col], errors="coerce")
            else:
                df[col] = 0.0

        df = df.dropna(subset=["date"])
        df = df.sort_values("date").reset_index(drop=True)
        return df[["date", "open", "high", "low", "close", "volume", "amount"]]

    def is_available(self) -> bool:
        try:
            import efinance  # noqa: F401
            return True
        except ImportError:
            return False

    def get_name(self) -> str:
        return "efinance"
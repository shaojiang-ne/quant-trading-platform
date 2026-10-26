"""
通达信数据源

通过 mootdx 的 TCP 二进制协议（端口 7709）获取 A 股和指数K线数据。
永不封IP，是分钟线回测的首选数据源。
"""

import logging
from typing import Optional

import pandas as pd

from app.core.data_source import DataSourceProvider

logger = logging.getLogger(__name__)

# mootdx 周期字符串映射
_PERIOD_MAP = {
    "1m": "1m", "5m": "5m", "15m": "15m", "30m": "30m",
    "60m": "1h", "1h": "1h", "1d": "day", "1w": "week", "1mon": "mon",
}

# 交易所后缀 → mootdx 的 market 参数值
_MARKET_MAP = {
    "SH": 1,
    "SZ": 0,
    "BJ": 2,
}

# mootdx 每次最多返回 800 条
_MAX_OFFSET = 800


def _parse_symbol(symbol: str) -> tuple[str, int]:
    """将 600519.SH 格式解析为 (纯代码, market)

    Returns:
        (code, market): e.g. ("600519", 1)
    """
    parts = symbol.split(".")
    if len(parts) == 2:
        code, suffix = parts[0], parts[1].upper()
        market = _MARKET_MAP.get(suffix, 1)
        return code, market
    # 无后缀时根据代码判断
    code = symbol
    if code.startswith("6") or code.startswith("9"):
        return code, 1  # SH
    if code.startswith("8") or code.startswith("4"):
        return code, 2  # BJ
    return code, 0  # SZ


def _is_index(symbol: str) -> bool:
    """判断是否为指数代码"""
    parts = symbol.split(".")
    code = parts[0]
    suffix = parts[1] if len(parts) > 1 else ""
    return (suffix == "SH" and code.startswith("000")) or \
           (suffix == "SZ" and code.startswith("399"))


class MootdxDataSource(DataSourceProvider):
    """通达信数据源（TCP 二进制协议，永不封IP）"""

    def __init__(self):
        self._client = None
        self._available: Optional[bool] = None

    def _get_client(self):
        """获取或创建 mootdx 连接（带重连）"""
        if self._client is not None:
            try:
                if not self._client.closed:
                    return self._client
            except Exception:
                pass

        try:
            from mootdx.quotes import Quotes
            client = Quotes.factory(market='std', multithread=False, heartbeat=False)
            if client is not None:
                self._client = client
                self._available = True
                return client
        except Exception as e:
            logger.warning(f"mootdx 连接失败: {e}")

        # 回退：尝试直接用 bestip 探测
        try:
            from mootdx.quotes import Quotes
            from mootdx.server import Bestip
            bestip = Bestip()
            bestip.run()
            client = Quotes.factory(market='std', multithread=False, heartbeat=False)
            if client is not None:
                self._client = client
                self._available = True
                return client
        except Exception as e:
            logger.warning(f"mootdx bestip 回退连接也失败: {e}")

        self._available = False
        return None

    def get_klines(
        self,
        symbol: str,
        period: str,
        start: str,
        end: str,
        dividend_type: str = "front",
    ) -> pd.DataFrame:
        """获取个股K线数据"""
        mootdx_period = _PERIOD_MAP.get(period)
        if not mootdx_period:
            logger.error(f"mootdx 不支持周期: {period}")
            return pd.DataFrame()

        if _is_index(symbol):
            return self.get_index_klines(symbol, period, start, end)

        code, market = _parse_symbol(symbol)
        client = self._get_client()
        if client is None:
            return pd.DataFrame()

        try:
            # 分页获取数据，直到覆盖日期范围
            all_dfs = []
            start_pos = 0
            while True:
                df = client.bars(
                    symbol=code,
                    frequency=mootdx_period,
                    start=start_pos,
                    offset=_MAX_OFFSET,
                )
                if df is None or df.empty:
                    break

                all_dfs.append(df)

                # 检查最早的数据是否已经早于 start 日期
                if len(df) < _MAX_OFFSET:
                    break
                first_dt = df.index[0]
                start_ts = pd.Timestamp(start)
                if first_dt <= start_ts:
                    break

                start_pos += _MAX_OFFSET

            if not all_dfs:
                return pd.DataFrame()

            df = pd.concat(all_dfs)
            df = df[~df.index.duplicated(keep='first')]
            return self._normalize(df, start, end)

        except Exception as e:
            logger.error(f"mootdx 获取K线失败 {symbol} {period}: {e}")
            self._client = None  # 标记需要重连
            return pd.DataFrame()

    def get_index_klines(
        self,
        index_code: str,
        period: str,
        start: str,
        end: str,
    ) -> pd.DataFrame:
        """获取指数K线数据"""
        mootdx_period = _PERIOD_MAP.get(period, "day")
        code, market = _parse_symbol(index_code)
        client = self._get_client()
        if client is None:
            return pd.DataFrame()

        try:
            all_dfs = []
            start_pos = 0
            while True:
                df = client.index_bars(
                    symbol=code,
                    frequency=mootdx_period,
                    start=start_pos,
                    offset=_MAX_OFFSET,
                )
                if df is None or df.empty:
                    break

                all_dfs.append(df)

                if len(df) < _MAX_OFFSET:
                    break
                first_dt = df.index[0]
                start_ts = pd.Timestamp(start)
                if first_dt <= start_ts:
                    break

                start_pos += _MAX_OFFSET

            if not all_dfs:
                return pd.DataFrame()

            df = pd.concat(all_dfs)
            df = df[~df.index.duplicated(keep='first')]
            return self._normalize(df, start, end)

        except Exception as e:
            logger.error(f"mootdx 获取指数K线失败 {index_code} {period}: {e}")
            self._client = None
            return pd.DataFrame()

    def _normalize(self, df: pd.DataFrame, start: str, end: str) -> pd.DataFrame:
        """将 mootdx 返回的 DataFrame 统一为标准格式"""
        if df.empty:
            return pd.DataFrame()

        # mootdx 返回的列: open, close, high, low, vol, amount, ..., datetime, volume
        result = pd.DataFrame({
            "date": df.index,
            "open": pd.to_numeric(df["open"], errors="coerce"),
            "high": pd.to_numeric(df["high"], errors="coerce"),
            "low": pd.to_numeric(df["low"], errors="coerce"),
            "close": pd.to_numeric(df["close"], errors="coerce"),
            "volume": pd.to_numeric(df.get("volume", df.get("vol", 0)), errors="coerce").fillna(0),
            "amount": pd.to_numeric(df.get("amount", 0), errors="coerce").fillna(0),
        })

        # 日期过滤
        start_ts = pd.Timestamp(start)
        end_ts = pd.Timestamp(end)
        result = result[(result["date"] >= start_ts) & (result["date"] <= end_ts)]

        result = result.dropna(subset=["date"])
        result = result.sort_values("date").reset_index(drop=True)
        return result[["date", "open", "high", "low", "close", "volume", "amount"]]

    def is_available(self) -> bool:
        """检查 mootdx 是否可用"""
        if self._available is not None:
            # 如果之前成功过，尝试复用
            if self._available and self._client is not None:
                try:
                    if not self._client.closed:
                        return True
                except Exception:
                    pass

        client = self._get_client()
        return client is not None

    def get_name(self) -> str:
        return "mootdx"

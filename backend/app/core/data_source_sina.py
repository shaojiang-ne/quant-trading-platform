"""
新浪财经数据源

通过新浪财经 HTTP 接口获取 A 股和指数K线数据。
无独立 Python SDK，需自行封装 HTTP 请求。

主接口: https://money.finance.sina.com.cn/quotes_service/api/json_v2.php/CN_MarketData.getKLineData
备选接口: https://quotes.sina.cn/cn/api/jsonp_v2.php/=/CN_MarketDataService.getKLineData
"""

import json
import logging
from typing import Optional

import pandas as pd
import requests
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry

from app.core.data_source import DataSourceProvider

logger = logging.getLogger(__name__)

# 新浪周期映射：scale 参数（分钟数，240=日线）
_PERIOD_MAP = {
    "1m": "1", "5m": "5", "15m": "15", "30m": "30",
    "60m": "60", "1h": "60", "1d": "240", "1w": "1200",
}

# 新浪股票代码前缀
_PREFIX_MAP = {
    "SH": "sh",
    "SZ": "sz",
    "BJ": "bj",
}


def _to_sina_symbol(symbol: str) -> str:
    """600519.SH → sh600519, 000001.SZ → sz000001"""
    parts = symbol.split(".")
    if len(parts) == 2:
        code, suffix = parts
        prefix = _PREFIX_MAP.get(suffix.upper(), "sh")
        return f"{prefix}{code}"
    code = symbol
    if code.startswith("6") or code.startswith("9"):
        return f"sh{code}"
    return f"sz{code}"


def _is_index(symbol: str) -> bool:
    """判断是否为指数"""
    parts = symbol.split(".")
    code = parts[0]
    suffix = parts[1] if len(parts) > 1 else ""
    return (suffix == "SH" and code.startswith("000")) or \
           (suffix == "SZ" and code.startswith("399"))


class SinaDataSource(DataSourceProvider):

    # 主接口（返回纯 JSON）
    _PRIMARY_URL = "https://money.finance.sina.com.cn/quotes_service/api/json_v2.php/CN_MarketData.getKLineData"
    # 备选接口（返回 JSONP）
    _FALLBACK_URL = "https://quotes.sina.cn/cn/api/jsonp_v2.php/=/CN_MarketDataService.getKLineData"

    def __init__(self):
        self._session = requests.Session()
        self._session.headers.update({
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
            "Referer": "https://finance.sina.com.cn",
        })
        # 显式挂载连接池（与 main.py 全局 Session 参数一致），避免端口耗尽
        retry = Retry(total=2, backoff_factor=0.5, status_forcelist=[502, 503, 504])
        adapter = HTTPAdapter(pool_connections=20, pool_maxsize=10, max_retries=retry)
        self._session.mount("https://", adapter)
        self._session.mount("http://", adapter)

    def get_klines(
        self,
        symbol: str,
        period: str,
        start: str,
        end: str,
        dividend_type: str = "front",
    ) -> pd.DataFrame:
        sina_symbol = _to_sina_symbol(symbol)
        scale = _PERIOD_MAP.get(period)
        if not scale:
            logger.error(f"新浪财经不支持周期: {period}")
            return pd.DataFrame()

        datalen = 8000 if period in ("1d", "1w") else 5000
        params = {
            "symbol": sina_symbol,
            "scale": scale,
            "ma": "no",
            "datalen": datalen,
        }

        # 先尝试主接口
        df = self._fetch(self._PRIMARY_URL, params, is_jsonp=False)
        if df.empty:
            # 再尝试备选接口
            df = self._fetch(self._FALLBACK_URL, params, is_jsonp=True)

        if df.empty:
            return pd.DataFrame()

        # 按日期范围过滤
        start_ts = pd.Timestamp(start)
        end_ts = pd.Timestamp(end)
        df = df[(df["date"] >= start_ts) & (df["date"] <= end_ts)]
        df = df.reset_index(drop=True)
        return df

    def get_index_klines(
        self,
        index_code: str,
        period: str,
        start: str,
        end: str,
    ) -> pd.DataFrame:
        return self.get_klines(index_code, period, start, end, dividend_type="none")

    def _fetch(self, url: str, params: dict, is_jsonp: bool) -> pd.DataFrame:
        """发起请求并解析响应"""
        try:
            resp = self._session.get(url, params=params, timeout=15)
            resp.raise_for_status()
        except Exception as e:
            logger.debug(f"新浪财经请求失败 ({url}): {e}")
            return pd.DataFrame()

        text = resp.text.strip()
        if not text or "error" in text.lower():
            return pd.DataFrame()

        if is_jsonp:
            return self._parse_jsonp(text)
        else:
            return self._parse_json(text)

    def _parse_json(self, text: str) -> pd.DataFrame:
        """解析纯 JSON 响应"""
        try:
            records = json.loads(text)
        except json.JSONDecodeError:
            logger.debug(f"新浪财经 JSON 解析失败: {text[:200]}")
            return pd.DataFrame()

        if not isinstance(records, list) or not records:
            return pd.DataFrame()

        df = pd.DataFrame(records)
        return self._normalize(df)

    def _parse_jsonp(self, text: str) -> pd.DataFrame:
        """解析 JSONP 响应"""
        json_str = text
        if "=" in json_str:
            json_str = json_str.split("=", 1)[1]
        if json_str.startswith("("):
            json_str = json_str[1:]
        if json_str.endswith(")"):
            json_str = json_str[:-1]
        if json_str.endswith(";"):
            json_str = json_str[:-1]

        try:
            records = json.loads(json_str)
        except json.JSONDecodeError:
            logger.debug(f"新浪财经 JSONP 解析失败: {text[:200]}")
            return pd.DataFrame()

        if isinstance(records, dict):
            records = records.get("data", [])
        if not isinstance(records, list) or not records:
            return pd.DataFrame()

        df = pd.DataFrame(records)
        return self._normalize(df)

    def _normalize(self, df: pd.DataFrame) -> pd.DataFrame:
        """将新浪返回的 DataFrame 统一为标准格式"""
        if df.empty:
            return pd.DataFrame()

        col_map = {}
        for col in df.columns:
            cl = str(col).lower().strip()
            if cl in ("day", "date", "d"):
                col_map[col] = "date"
            elif cl in ("open", "o"):
                col_map[col] = "open"
            elif cl in ("high", "h"):
                col_map[col] = "high"
            elif cl in ("low", "l"):
                col_map[col] = "low"
            elif cl in ("close", "c"):
                col_map[col] = "close"
            elif cl in ("volume", "v"):
                col_map[col] = "volume"
            elif "amount" in cl or "turnover" in cl:
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

        # 如果没有 amount 列，用 close * volume 估算
        if "amount" not in df.columns or df["amount"].sum() == 0:
            df["amount"] = df["close"] * df["volume"]

        df = df.dropna(subset=["date"])
        df = df.sort_values("date").reset_index(drop=True)
        return df[["date", "open", "high", "low", "close", "volume", "amount"]]

    def is_available(self) -> bool:
        try:
            resp = self._session.get(
                self._PRIMARY_URL,
                params={"symbol": "sh600519", "scale": "240", "ma": "no", "datalen": "1"},
                timeout=10,
            )
            return resp.status_code == 200 and "[" in resp.text
        except Exception:
            return False

    def get_name(self) -> str:
        return "sina"
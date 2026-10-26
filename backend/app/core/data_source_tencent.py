"""
腾讯财经数据源

通过腾讯财经 HTTP 接口获取 A 股和指数K线数据。
无独立 Python SDK，需自行封装 HTTP 请求。

接口: https://web.ifzq.gtimg.cn/appstock/app/fqkline/get

注意: 腾讯 fqkline 接口仅支持日线和周线，不支持分钟线。
"""

import logging
import json

import pandas as pd
import requests
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry

from app.core.data_source import DataSourceProvider

logger = logging.getLogger(__name__)

# 腾讯周期映射 (注意: fqkline 接口仅支持 day/week，分钟线不可用)
_PERIOD_MAP = {
    "1d": "day", "1w": "week",
    # 分钟线接口不支持，保留映射但会返回空数据
    "1m": "m1", "5m": "m5", "15m": "m15", "30m": "m30", "60m": "h60", "1h": "h60",
}

# 复权类型: qfq=前复权, hfq=后复权, ''=不复权
_ADJUST_MAP = {
    "front": "qfq",
    "back": "hfq",
    "none": "",
}


def _to_tencent_symbol(symbol: str) -> str:
    """600519.SH → sh600519, 000001.SZ → sz000001"""
    parts = symbol.split(".")
    if len(parts) == 2:
        code, suffix = parts
        prefix = suffix.lower()
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


class TencentDataSource(DataSourceProvider):

    def __init__(self):
        self._session = requests.Session()
        self._session.headers.update({
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
            "Referer": "https://gu.qq.com",
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
        qq_symbol = _to_tencent_symbol(symbol)
        klt = _PERIOD_MAP.get(period)
        if not klt:
            logger.error(f"腾讯财经不支持周期: {period}")
            return pd.DataFrame()

        fqt = _ADJUST_MAP.get(dividend_type, "qfq")

        url = "https://web.ifzq.gtimg.cn/appstock/app/fqkline/get"
        # 腾讯接口最大 count 为 1000，超出会返回 param error
        params = {
            "param": f"{qq_symbol},{klt},,,1000,{fqt}",
        }

        try:
            resp = self._session.get(url, params=params, timeout=15)
            resp.raise_for_status()
        except Exception as e:
            logger.error(f"腾讯财经请求失败 {symbol} {period}: {e}")
            return pd.DataFrame()

        df = self._parse_response(resp.text, qq_symbol, klt, fqt)
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

    def _parse_response(self, text: str, symbol: str, klt: str, fqt: str) -> pd.DataFrame:
        """解析腾讯财经响应"""
        json_str = text.strip()

        # 去掉 JSONP 包裹（如果有）
        if "(" in json_str and ")" in json_str:
            start_idx = json_str.index("(")
            end_idx = json_str.rindex(")")
            json_str = json_str[start_idx + 1:end_idx]

        try:
            data = json.loads(json_str)
        except json.JSONDecodeError:
            logger.error(f"腾讯财经 JSON 解析失败: {text[:200]}")
            return pd.DataFrame()

        # 检查错误
        if isinstance(data, dict) and data.get("code") == -1:
            logger.error(f"腾讯财经接口错误: {data.get('msg', 'unknown')}")
            return pd.DataFrame()

        # 数据路径: data -> {symbol} -> {klt_key: [[date, open, close, high, low, volume], ...]}
        sub_data = data.get("data", {})
        if not sub_data or not isinstance(sub_data, dict):
            return pd.DataFrame()

        stock_data = sub_data.get(symbol, sub_data.get(list(sub_data.keys())[0] if sub_data else "", {}))
        if not stock_data or not isinstance(stock_data, dict):
            return pd.DataFrame()

        # 尝试不同的 key 格式: qfqday, day, qfqm5, m5 等
        records = None
        for key in [fqt + klt, klt]:
            if key in stock_data and isinstance(stock_data[key], list):
                records = stock_data[key]
                break

        # 如果都没找到，取第一个 list 类型的值
        if records is None:
            for key, val in stock_data.items():
                if isinstance(val, list) and len(val) > 0:
                    records = val
                    break

        if not records:
            return pd.DataFrame()

        # 腾讯数据格式: [date, open, close, high, low, volume] 或 dict
        rows = []
        for item in records:
            if isinstance(item, (list, tuple)) and len(item) >= 6:
                rows.append({
                    "date": item[0],
                    "open": item[1],
                    "close": item[2],
                    "high": item[3],
                    "low": item[4],
                    "volume": item[5],
                    "amount": item[6] if len(item) > 6 else 0,
                })
            elif isinstance(item, dict):
                rows.append(item)

        if not rows:
            return pd.DataFrame()

        df = pd.DataFrame(rows)
        return self._normalize(df)

    def _normalize(self, df: pd.DataFrame) -> pd.DataFrame:
        """将腾讯返回的 DataFrame 统一为标准格式"""
        if df.empty:
            return pd.DataFrame()

        col_map = {}
        for col in df.columns:
            cl = str(col).lower().strip()
            if cl in ("date", "day", "d"):
                col_map[col] = "date"
            elif cl in ("open", "o"):
                col_map[col] = "open"
            elif cl in ("high", "h"):
                col_map[col] = "high"
            elif cl in ("low", "l"):
                col_map[col] = "low"
            elif cl in ("close", "c"):
                col_map[col] = "close"
            elif cl in ("volume", "v", "vol"):
                col_map[col] = "volume"
            elif cl in ("amount", "turnover"):
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
                "https://web.ifzq.gtimg.cn/appstock/app/fqkline/get",
                params={"param": "sh600519,day,,,1,qfq"},
                timeout=10,
            )
            return resp.status_code == 200
        except Exception:
            return False

    def get_name(self) -> str:
        return "tencent"

    # ── 实时快照（qt.gtimg.cn）─────────────────────────────────────────────
    # 逻辑与 stock_research_service.tencent_quote 一致，字段对齐 _fetch_pool_quotes 产出的 quote 结构。

    @staticmethod
    def _code_to_qq(code: str) -> str:
        """6 位裸码 → 腾讯快照前缀（sh600519 / sz000001 / bj830xxx）。"""
        c = code.strip()
        if c.startswith(("6", "9")):
            return f"sh{c}"
        if c.startswith(("8", "4")):
            return f"bj{c}"
        return f"sz{c}"

    def get_snapshot(self, codes: list[str]) -> dict[str, dict]:
        """批量实时快照。返回 {code: {name, price, change_pct, turnover_pct,
        pe_ttm, pb, float_mcap_yi, vol_ratio, amount_wan}}。"""
        if not codes:
            return {}
        prefixed = [self._code_to_qq(c) for c in codes]
        url = "https://qt.gtimg.cn/q=" + ",".join(prefixed)
        try:
            resp = self._session.get(url, timeout=10)
            resp.encoding = "gbk"
            data = resp.text
        except Exception as e:
            logger.error(f"腾讯快照请求失败: {e}")
            return {}

        result: dict[str, dict] = {}
        for line in data.strip().split(";"):
            line = line.strip()
            if not line or "=" not in line or '"' not in line:
                continue
            key = line.split("=")[0].split("_")[-1]
            vals = line.split('"')[1].split("~")
            if len(vals) < 53:
                continue
            code = key[2:]  # 去掉 sh/sz/bj 前缀得到 6 位裸码
            try:
                result[code] = {
                    "name": vals[1],
                    "price": float(vals[3]) if vals[3] else 0,
                    "change_pct": float(vals[32]) if vals[32] else 0,
                    "turnover_pct": float(vals[38]) if vals[38] else 0,
                    "pe_ttm": float(vals[39]) if vals[39] else 0,
                    "pb": float(vals[46]) if vals[46] else 0,
                    "float_mcap_yi": float(vals[45]) if vals[45] else 0,
                    "vol_ratio": float(vals[49]) if vals[49] else 0,
                    "amount_wan": float(vals[37]) if vals[37] else 0,
                }
            except (ValueError, IndexError):
                continue
        return result
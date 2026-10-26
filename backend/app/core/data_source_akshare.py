"""
Akshare 数据源

使用 akshare 获取 A 股和指数K线数据，完全免费开源。
"""

import logging
import threading
import time
import random
from datetime import datetime

import pandas as pd

from app.core.data_source import DataSourceProvider

logger = logging.getLogger(__name__)

# akshare 周期映射
_PERIOD_MAP = {
    "1m": "1", "5m": "5", "15m": "15", "30m": "30",
    "60m": "60", "1h": "60", "1d": "daily", "1w": "weekly",
}

# 复权方式映射
_ADJUST_MAP = {
    "front": "hfq",
    "back": "qfq",
    "none": "",
}


def _strip_suffix(symbol: str) -> str:
    """600519.SH → 600519"""
    return symbol.split(".")[0] if "." in symbol else symbol


def _is_sh_index(symbol: str) -> bool:
    """判断是否为上证指数代码（000xxx.SH）"""
    parts = symbol.split(".")
    code = parts[0]
    suffix = parts[1] if len(parts) > 1 else ""
    return suffix == "SH" and code.startswith("000")


def _is_sz_index(symbol: str) -> bool:
    """判断是否为深证指数代码（399xxx.SZ）"""
    parts = symbol.split(".")
    code = parts[0]
    suffix = parts[1] if len(parts) > 1 else ""
    return suffix == "SZ" and code.startswith("399")


def _is_index(symbol: str) -> bool:
    """判断是否为指数"""
    return _is_sh_index(symbol) or _is_sz_index(symbol)


class AkshareDataSource(DataSourceProvider):
    _last_call_time: float = 0
    _call_lock = threading.Lock()
    _MIN_CALL_INTERVAL: float = 1.5  # 秒，含抖动

    # 全市场 spot_em 缓存（类级，跨所有 AkshareDataSource 实例共享）：
    # stock_zh_a_spot_em() 每次分页拉 5000+ 只 = 55+ HTTP 请求，多路径
    # （AkshareMarketBackend 轮询 / auto 降级回退 / 自选股刷新 / 选股）共用
    # 一份缓存，TTL 内只拉一次，避免 TCP 连接被多路径重复触发而爆炸。
    _spot_cache_df = None
    _spot_cache_ts: float = 0.0
    _spot_cache_lock = threading.Lock()
    _SPOT_CACHE_TTL: float = 15.0  # 秒

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

    @classmethod
    def _get_spot_df(cls):
        """获取全市场 spot_em DataFrame（带 TTL 缓存 + 互斥锁）。

        多路径（AkshareMarketBackend 轮询 / auto 降级回退 / 任何 get_snapshot
        调用）共享同一份缓存，TTL 内只拉一次 stock_zh_a_spot_em()。
        double-check locking 防并发拉取；拉取失败做负面缓存（更新 ts 不更新 df，
        返回旧缓存）避免短时间内频繁重试。
        """
        now = time.time()
        if cls._spot_cache_df is not None and (now - cls._spot_cache_ts) < cls._SPOT_CACHE_TTL:
            return cls._spot_cache_df
        with cls._spot_cache_lock:
            now = time.time()
            if cls._spot_cache_df is not None and (now - cls._spot_cache_ts) < cls._SPOT_CACHE_TTL:
                return cls._spot_cache_df
            cls._rate_limit()
            try:
                import akshare as ak
            except ImportError:
                logger.error("akshare 未安装")
                cls._spot_cache_ts = time.time()
                return cls._spot_cache_df
            try:
                df = ak.stock_zh_a_spot_em()
            except Exception as e:
                logger.error(f"akshare 获取快照失败: {e}")
                cls._spot_cache_ts = time.time()  # 负面缓存：短期不重试
                return cls._spot_cache_df
            if df is not None and not df.empty:
                cls._spot_cache_df = df
            cls._spot_cache_ts = time.time()
            return cls._spot_cache_df

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
            import akshare as ak
        except ImportError:
            logger.error("akshare 未安装，请运行: pip install akshare")
            return pd.DataFrame()

        ak_period = _PERIOD_MAP.get(period)
        if not ak_period:
            logger.error(f"akshare 不支持周期: {period}")
            return pd.DataFrame()

        ak_adjust = _ADJUST_MAP.get(dividend_type, "hfq")
        code = _strip_suffix(symbol)

        start_fmt = start.replace("-", "")
        end_fmt = end.replace("-", "")

        try:
            if period in ("1d", "1w"):
                df = ak.stock_zh_a_hist(
                    symbol=code, period=ak_period,
                    start_date=start_fmt, end_date=end_fmt,
                    adjust=ak_adjust,
                )
            else:
                df = ak.stock_zh_a_hist_min_em(
                    symbol=code, period=ak_period,
                    start_date=start_fmt, end_date=end_fmt,
                    adjust=ak_adjust,
                )
        except Exception as e:
            logger.error(f"akshare 获取K线失败 {symbol} {period}: {e}")
            return pd.DataFrame()

        if df.empty:
            return pd.DataFrame()

        return self._normalize(df, is_daily=period in ("1d", "1w"))

    def get_index_klines(
        self,
        index_code: str,
        period: str,
        start: str,
        end: str,
    ) -> pd.DataFrame:
        self._rate_limit()
        try:
            import akshare as ak
        except ImportError:
            logger.error("akshare 未安装，请运行: pip install akshare")
            return pd.DataFrame()

        ak_period = _PERIOD_MAP.get(period, "daily")
        code = _strip_suffix(index_code)

        start_fmt = start.replace("-", "")
        end_fmt = end.replace("-", "")

        try:
            if period in ("1d", "1w"):
                df = ak.index_zh_a_hist(
                    symbol=code, period=ak_period,
                    start_date=start_fmt, end_date=end_fmt,
                )
            else:
                df = ak.index_zh_a_hist_min_em(
                    symbol=code, period=ak_period,
                    start_date=start_fmt, end_date=end_fmt,
                )
        except Exception as e:
            logger.error(f"akshare 获取指数K线失败 {index_code} {period}: {e}")
            return pd.DataFrame()

        if df.empty:
            return pd.DataFrame()

        return self._normalize(df, is_daily=period in ("1d", "1w"))

    def _normalize(self, df: pd.DataFrame, is_daily: bool) -> pd.DataFrame:
        """将 akshare 返回的 DataFrame 统一为标准格式"""
        col_map = {}
        for col in df.columns:
            cl = col.lower().strip()
            if cl in ("日期", "时间", "date", "day", "time"):
                col_map[col] = "date"
            elif cl in ("开盘", "open"):
                col_map[col] = "open"
            elif cl in ("最高", "high"):
                col_map[col] = "high"
            elif cl in ("最低", "low"):
                col_map[col] = "low"
            elif cl in ("收盘", "close"):
                col_map[col] = "close"
            elif cl in ("成交量", "volume"):
                col_map[col] = "volume"
            elif cl in ("成交额", "amount", "turnover"):
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
            import akshare  # noqa: F401
            return True
        except ImportError:
            return False

    def get_name(self) -> str:
        return "akshare"

    # ── 实时快照 / 指数成分股（东财接口）─────────────────────────────────────

    def get_index_constituents(self, index_code: str) -> list[dict]:
        """获取指数成分股。index_code 如 "000300"（沪深300）。
        返回 [{code, name}]，code 为 6 位裸码。"""
        self._rate_limit()
        try:
            import akshare as ak
        except ImportError:
            logger.error("akshare 未安装")
            return []
        # 兼容 "000300" / "000300.SH" 两种输入
        code = _strip_suffix(index_code)
        try:
            df = ak.index_stock_cons_csindex(symbol=code)
        except Exception as e:
            logger.error(f"akshare 获取成分股失败 {index_code}: {e}")
            return []
        if df is None or df.empty:
            return []
        # 列名中文，优先匹配「成分券代码/名称」（避免命中「指数代码/名称」），兜底用列序
        cols = list(df.columns)
        code_col = (
            next((c for c in cols if "成分券代码" in str(c)), None)
            or next((c for c in cols if "代码" in str(c) and "指数" not in str(c)), None)
            or (cols[4] if len(cols) > 4 else None)
        )
        name_col = (
            next((c for c in cols if "成分券名称" in str(c)), None)
            or next((c for c in cols if "名称" in str(c) and "指数" not in str(c)), None)
            or (cols[5] if len(cols) > 5 else None)
        )
        if code_col is None or name_col is None:
            return []
        out = []
        for _, row in df.iterrows():
            c = str(row[code_col]).strip()
            n = str(row[name_col]).strip()
            if c and len(c) == 6 and c.isdigit():
                out.append({"code": c, "name": n})
        return out

    def get_snapshot(self, codes: list[str]) -> dict[str, dict]:
        """批量实时快照（东财全市场 spot_em，按 codes 过滤）。
        返回 {code: {name, price, change_pct, turnover_pct, pe_ttm, pb,
        float_mcap_yi, vol_ratio, amount_wan}}。

        全市场 DataFrame 走类级 TTL 缓存（_get_spot_df），15s 内多调用方复用，
        避免 stock_zh_a_spot_em() 的 55+ HTTP 请求被多路径重复触发。"""
        if not codes:
            return {}
        df = self._get_spot_df()
        if df is None or df.empty:
            return {}

        wanted = set(codes)
        # 按中文列名映射到标准字段（spot_em 列名为中文）
        col_map = {c: str(c) for c in df.columns}
        def col(*keywords):
            for c in df.columns:
                cs = str(c)
                if all(k in cs for k in keywords):
                    return c
            return None
        code_col = col("代码")
        name_col = col("名称")
        price_col = col("最新价")
        chg_col = col("涨跌幅")
        turnover_col = col("换手率")
        pe_col = col("市盈率", "动态")
        pb_col = col("市净率")
        float_mcap_col = col("流通市值")
        vol_ratio_col = col("量比")
        amount_col = col("成交额")

        result: dict[str, dict] = {}
        for _, row in df.iterrows():
            c = str(row[code_col]).strip() if code_col else ""
            if c not in wanted:
                continue
            def _f(colname):
                try:
                    v = row[colname]
                    return float(v) if v is not None and str(v) != "nan" else 0
                except Exception:
                    return 0
            result[c] = {
                "name": str(row[name_col]) if name_col else c,
                "price": _f(price_col) if price_col else 0,
                "change_pct": _f(chg_col) if chg_col else 0,
                "turnover_pct": _f(turnover_col) if turnover_col else 0,
                "pe_ttm": _f(pe_col) if pe_col else 0,
                "pb": _f(pb_col) if pb_col else 0,
                # spot_em 市值/成交额单位为元，转亿/万
                "float_mcap_yi": _f(float_mcap_col) / 1e8 if float_mcap_col else 0,
                "vol_ratio": _f(vol_ratio_col) if vol_ratio_col else 0,
                "amount_wan": _f(amount_col) / 1e4 if amount_col else 0,
            }
        return result

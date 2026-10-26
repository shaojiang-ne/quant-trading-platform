"""
分级自动降级数据源

按优先级依次尝试多个数据源，首个成功即返回。
自动跳过不可用的数据源，并记录降级事件供调试。
分钟线和日线使用不同的优先级链。
"""

import logging
from datetime import datetime
from typing import Optional

import pandas as pd

from app.core.data_source import DataSourceProvider

logger = logging.getLogger(__name__)

# 分钟线周期集合
_MINUTE_PERIODS = {"1m", "5m", "15m", "30m", "1h", "60m"}

# 分钟线数据源优先级（只尝试支持分钟线的源）
_MINUTE_SOURCE_ORDER = ["mootdx", "xtquant", "akshare"]

# 日线数据源优先级
_DAILY_SOURCE_ORDER = ["tencent", "mootdx", "baostock", "sina", "akshare"]

# 指数数据源优先级
_INDEX_SOURCE_ORDER = ["tencent", "mootdx", "baostock", "akshare"]


class FallbackDataSource(DataSourceProvider):
    """分级自动降级数据源"""

    def __init__(self, sources: dict[str, DataSourceProvider]):
        """
        Args:
            sources: 数据源名称到实例的映射，e.g. {"mootdx": MootdxDataSource(), ...}
        """
        self._sources = sources
        self._fallback_log: list[dict] = []

    def _get_ordered_sources(self, period: str, is_index: bool = False) -> list[tuple[str, DataSourceProvider]]:
        """根据周期和是否为指数，返回有序的数据源列表"""
        if period in _MINUTE_PERIODS:
            order = _MINUTE_SOURCE_ORDER
        elif is_index:
            order = _INDEX_SOURCE_ORDER
        else:
            order = _DAILY_SOURCE_ORDER

        result = []
        for name in order:
            source = self._sources.get(name)
            if source is not None:
                result.append((name, source))
        return result

    def get_klines(
        self,
        symbol: str,
        period: str,
        start: str,
        end: str,
        dividend_type: str = "front",
    ) -> pd.DataFrame:
        is_index = self._is_index(symbol)
        ordered = self._get_ordered_sources(period, is_index)

        last_error = None
        for name, source in ordered:
            if not source.is_available():
                logger.debug(f"[fallback] 跳过不可用数据源: {name}")
                continue
            try:
                df = source.get_klines(symbol, period, start, end, dividend_type)
                if df is not None and not df.empty:
                    logger.info(f"[fallback] {symbol} {period}: 使用 {name} 获取 {len(df)} 条数据")
                    return df
            except Exception as e:
                last_error = e
                self._log_fallback(name, symbol, period, str(e))
                continue

        logger.warning(f"[fallback] 所有数据源均失败: {symbol} {period}, 最后错误: {last_error}")
        return pd.DataFrame()

    def get_index_klines(
        self,
        index_code: str,
        period: str,
        start: str,
        end: str,
    ) -> pd.DataFrame:
        ordered = self._get_ordered_sources(period, is_index=True)

        last_error = None
        for name, source in ordered:
            if not source.is_available():
                continue
            try:
                df = source.get_index_klines(index_code, period, start, end)
                if df is not None and not df.empty:
                    logger.info(f"[fallback] {index_code} {period}(指数): 使用 {name} 获取 {len(df)} 条数据")
                    return df
            except Exception as e:
                last_error = e
                self._log_fallback(name, index_code, period, str(e))
                continue

        logger.warning(f"[fallback] 所有数据源均失败(指数): {index_code} {period}, 最后错误: {last_error}")
        return pd.DataFrame()

    def get_snapshot(self, codes: list[str]) -> dict[str, dict]:
        """实时快照降级：按日线优先级链逐个试，首个非空返回。"""
        ordered = self._get_ordered_sources("1d")
        for name, source in ordered:
            if not source.is_available():
                continue
            try:
                snap = source.get_snapshot(codes)
                if snap:
                    logger.info(f"[fallback] 快照: 使用 {name} 取 {len(snap)} 只")
                    return snap
            except Exception as e:
                self._log_fallback(name, ",".join(codes[:3]), "snapshot", str(e))
                continue
        logger.warning(f"[fallback] 所有数据源快照均失败: {len(codes)} 只")
        return {}

    def get_index_constituents(self, index_code: str) -> list[dict]:
        """指数成分股降级：按链逐个试，首个非空返回。"""
        ordered = self._get_ordered_sources("1d")
        for name, source in ordered:
            if not source.is_available():
                continue
            try:
                cons = source.get_index_constituents(index_code)
                if cons:
                    logger.info(f"[fallback] 成分股 {index_code}: 使用 {name} 取 {len(cons)} 只")
                    return cons
            except Exception as e:
                self._log_fallback(name, index_code, "cons", str(e))
                continue
        logger.warning(f"[fallback] 所有数据源成分股均失败: {index_code}")
        return []

    def is_available(self) -> bool:
        """至少有一个数据源可用即为可用"""
        return any(s.is_available() for s in self._sources.values())

    def get_name(self) -> str:
        available = [n for n, s in self._sources.items() if s.is_available()]
        return f"auto({'+'.join(available)})"

    def get_fallback_log(self) -> list[dict]:
        """返回降级日志"""
        return self._fallback_log

    def _log_fallback(self, source_name: str, symbol: str, period: str, error: str):
        """记录降级事件"""
        entry = {
            "timestamp": datetime.now().isoformat(),
            "source": source_name,
            "symbol": symbol,
            "period": period,
            "error": error,
        }
        self._fallback_log.append(entry)
        logger.debug(f"[fallback] {source_name} 失败 ({symbol} {period}): {error}")

    @staticmethod
    def _is_index(symbol: str) -> bool:
        """判断是否为指数代码"""
        parts = symbol.split(".")
        code = parts[0]
        suffix = parts[1] if len(parts) > 1 else ""
        return (suffix == "SH" and code.startswith("000")) or \
               (suffix == "SZ" and code.startswith("399"))

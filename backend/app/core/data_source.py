"""
数据源抽象接口

所有数据源（akshare / baostock / xtquant）实现此接口，
供回测引擎和 data_bridge 统一调用。
"""

import logging
from abc import ABC, abstractmethod

import pandas as pd

logger = logging.getLogger(__name__)


class DataSourceProvider(ABC):
    """数据源抽象基类"""

    @abstractmethod
    def get_klines(
        self,
        symbol: str,
        period: str,
        start: str,
        end: str,
        dividend_type: str = "front",
    ) -> pd.DataFrame:
        """获取个股K线数据

        Args:
            symbol: 股票代码，统一格式 600519.SH / 000001.SZ
            period: 周期 1m/5m/15m/30m/1h/1d/1w
            start: 开始日期 YYYY-MM-DD
            end: 结束日期 YYYY-MM-DD
            dividend_type: 复权方式 front/back/none

        Returns:
            DataFrame with columns: date, open, high, low, close, volume, amount
            date 为 pd.Timestamp，按时间升序排列
        """
        pass

    @abstractmethod
    def get_index_klines(
        self,
        index_code: str,
        period: str,
        start: str,
        end: str,
    ) -> pd.DataFrame:
        """获取指数K线数据（如沪深300）

        Args:
            index_code: 指数代码，如 000300.SH
            period: 周期 1d/1w
            start: 开始日期 YYYY-MM-DD
            end: 结束日期 YYYY-MM-DD

        Returns:
            DataFrame with columns: date, open, high, low, close, volume, amount
        """
        pass

    @abstractmethod
    def is_available(self) -> bool:
        """检查数据源是否可用"""
        pass

    @abstractmethod
    def get_name(self) -> str:
        """返回数据源名称"""
        pass

    # ── 可选能力：实时快照 / 指数成分股 ──────────────────────────────────────
    # 以下两个方法带默认空返回，未实现的 provider 沿用默认即可，
    # 由 FallbackDataSource 按链跳过，不影响 K线等核心能力。

    def get_snapshot(self, codes: list[str]) -> dict[str, dict]:
        """批量实时快照。

        Args:
            codes: 6 位裸码列表，如 ["600519", "000001"]

        Returns:
            {code: quote}，quote 字段与 tencent_quote 对齐：
            name / price / change_pct / turnover_pct / pe_ttm / pb /
            float_mcap_yi / vol_ratio / amount_wan。
            不支持快照的源返回空 dict（由 FallbackDataSource 跳过）。
        """
        return {}

    def get_index_constituents(self, index_code: str) -> list[dict]:
        """获取指数成分股（如沪深300）。

        Args:
            index_code: 指数代码，如 "000300"（沪深300）

        Returns:
            [{code, name}]，code 为 6 位裸码。
            不支持成分股的源返回空 list（由 FallbackDataSource 跳过）。
        """
        return []

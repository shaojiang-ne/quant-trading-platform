from abc import ABC, abstractmethod
import pandas as pd


class DataSourceInterface(ABC):
    """数据源抽象接口"""

    @abstractmethod
    def get_stock_list(self) -> pd.DataFrame:
        """获取全市场股票列表
        返回: code, name, industry, list_date, is_st
        """

    @abstractmethod
    def get_stock_basic(self, code: str) -> pd.DataFrame:
        """获取个股基本面数据
        返回: code, market_cap, pe, pb, total_shares, float_shares
        """

    @abstractmethod
    def get_daily_quote(self, code: str, days: int = 60) -> pd.DataFrame:
        """获取日K线数据
        返回: date, open, high, low, close, volume, amount, turnover
        """

    @abstractmethod
    def get_realtime_quote(self, codes: list[str]) -> pd.DataFrame:
        """获取实时行情（盘中用）
        返回: code, name, price, change_pct, volume, amount
        """

    @abstractmethod
    def get_money_flow(self, code: str, days: int = 10) -> pd.DataFrame:
        """获取资金流向数据
        返回: date, net_inflow, main_inflow, main_outflow
        """

    @abstractmethod
    def is_trading_day(self) -> bool:
        """判断今天是否为交易日"""

    @abstractmethod
    def is_trading_time(self) -> bool:
        """判断当前是否在交易时间（9:30-11:30, 13:00-15:00）"""

    def get_industry_map(self) -> dict[str, str]:
        """批量获取全市场 code->industry 映射（可选实现）"""
        return {}

    def batch_get_daily_quotes(self, codes: list[str], days: int = 60) -> dict[str, pd.DataFrame]:
        """批量获取多只股票的日K线（可选实现，默认串行）"""
        result = {}
        for code in codes:
            result[code] = self.get_daily_quote(code, days)
        return result

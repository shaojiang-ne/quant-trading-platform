import datetime

import numpy as np
import pandas as pd
from data.interface import DataSourceInterface


class TestDataSource(DataSourceInterface):
    """测试用轻量数据源，不依赖外部API"""

    def get_stock_list(self) -> pd.DataFrame:
        return pd.DataFrame({
            "code": ["000001", "000002", "600036", "601318", "688001", "300001"],
            "name": ["平安银行", "万科A", "招商银行", "中国平安", "华兴源创", "特锐德"],
            "industry": ["银行", "房地产", "银行", "保险", "半导体", "电气设备"],
            "list_date": ["1991-04-03", "1991-01-29", "2002-04-09", "2007-03-01", "2019-06-14", "2009-10-30"],
            "is_st": [False, False, False, False, False, False],
            "market_cap": [2000.0, 800.0, 3000.0, 5000.0, 100.0, 200.0],
            "amount": [5e8, 3e8, 8e8, 6e8, 1e8, 2e8],
            "pe": [6.5, 8.2, 5.8, 10.3, 45.0, 22.0],
            "pb": [0.8, 1.2, 1.0, 2.1, 3.5, 1.8],
        })

    def get_stock_basic(self, code: str) -> pd.DataFrame:
        return pd.DataFrame({
            "code": [code],
            "market_cap": [np.random.uniform(30, 500)],
            "pe": [np.random.uniform(5, 50)],
            "pb": [np.random.uniform(0.5, 5)],
            "total_shares": [np.random.uniform(1e9, 5e10)],
            "float_shares": [np.random.uniform(5e8, 3e10)],
            "industry": ["银行"],
            "list_date": ["2000-01-01"],
            "eps": [np.random.uniform(0.5, 3.0)],
            "eps_yoy": [np.random.uniform(-10, 30)],
            "revenue": [np.random.uniform(50, 500)],
            "net_profit": [np.random.uniform(5, 100)],
            "profit_yoy": [np.random.uniform(-20, 40)],
            "revenue_yoy": [np.random.uniform(-10, 30)],
            "total_assets": [np.random.uniform(100, 5000)],
            "report_date": ["2025-12-31"],
        })

    def get_daily_quote(self, code: str, days: int = 60) -> pd.DataFrame:
        dates = pd.bdate_range(end=datetime.date.today(), periods=days)
        base_price = 20.0
        close = base_price * np.linspace(1, 1.3, days)
        volume = np.full(days, 5000000.0)
        volume[-1] = 15000000.0
        close[-1] = close[-2] * 1.05
        return pd.DataFrame({
            "date": dates,
            "open": close * 0.995,
            "high": close * 1.02,
            "low": close * 0.985,
            "close": close,
            "volume": volume,
            "amount": volume * close,
            "turnover": np.full(days, 1.5),
        })

    def get_realtime_quote(self, codes: list[str]) -> pd.DataFrame:
        return pd.DataFrame({
            "code": codes,
            "name": [f"股票{c}" for c in codes],
            "price": np.random.uniform(10, 100, len(codes)),
            "change_pct": np.random.uniform(-5, 5, len(codes)),
            "volume": np.random.uniform(1e6, 1e8, len(codes)),
            "amount": np.random.uniform(1e7, 1e9, len(codes)),
        })

    def get_money_flow(self, code: str, days: int = 10) -> pd.DataFrame:
        dates = pd.bdate_range(end=datetime.date.today(), periods=days)
        return pd.DataFrame({
            "date": dates,
            "net_inflow": np.random.uniform(-1e8, 1e8, days),
            "main_inflow": np.random.uniform(0, 5e7, days),
            "main_outflow": np.random.uniform(0, 5e7, days),
        })

    def is_trading_day(self) -> bool:
        return datetime.date.today().weekday() < 5

    def is_trading_time(self) -> bool:
        now = datetime.datetime.now().time()
        morning = datetime.time(9, 30) <= now <= datetime.time(11, 30)
        afternoon = datetime.time(13, 0) <= now <= datetime.time(15, 0)
        return morning or afternoon

    def get_industry_map(self) -> dict[str, str]:
        return {
            "000001": "银行",
            "000002": "房地产",
            "600036": "银行",
            "601318": "保险",
            "688001": "半导体",
            "300001": "电气设备",
        }
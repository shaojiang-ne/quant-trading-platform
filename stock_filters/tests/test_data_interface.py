import pandas as pd
import pytest
from data.test_source import TestDataSource


@pytest.fixture
def ds():
    return TestDataSource()


def test_get_stock_list_returns_dataframe(ds):
    result = ds.get_stock_list()
    assert isinstance(result, pd.DataFrame)
    required = {"code", "name", "industry", "list_date", "is_st"}
    assert required.issubset(set(result.columns))
    assert len(result) > 0


def test_get_stock_basic_returns_dataframe(ds):
    result = ds.get_stock_basic("000001")
    assert isinstance(result, pd.DataFrame)
    required = {"code", "market_cap", "pe", "pb", "total_shares", "float_shares"}
    assert required.issubset(set(result.columns))


def test_get_daily_quote_returns_dataframe(ds):
    result = ds.get_daily_quote("000001", days=60)
    assert isinstance(result, pd.DataFrame)
    required = {"date", "open", "high", "low", "close", "volume", "amount", "turnover"}
    assert required.issubset(set(result.columns))
    assert len(result) == 60


def test_get_realtime_quote_returns_dataframe(ds):
    result = ds.get_realtime_quote(["000001", "600036"])
    assert isinstance(result, pd.DataFrame)
    required = {"code", "name", "price", "change_pct", "volume", "amount"}
    assert required.issubset(set(result.columns))
    assert len(result) == 2


def test_get_money_flow_returns_dataframe(ds):
    result = ds.get_money_flow("000001", days=10)
    assert isinstance(result, pd.DataFrame)
    required = {"date", "net_inflow", "main_inflow", "main_outflow"}
    assert required.issubset(set(result.columns))
    assert len(result) == 10


def test_is_trading_day_returns_bool(ds):
    result = ds.is_trading_day()
    assert isinstance(result, bool)


def test_is_trading_time_returns_bool(ds):
    result = ds.is_trading_time()
    assert isinstance(result, bool)

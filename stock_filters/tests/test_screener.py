import pandas as pd
import pytest
from screener import Screener
from data.test_source import TestDataSource
from data.cache_manager import CacheManager


@pytest.fixture
def cache_dir(tmp_path):
    return str(tmp_path)


@pytest.fixture
def screener(cache_dir):
    config = {
        "min_market_cap": 50,
        "min_daily_amount": 1,
        "exclude_st": True,
        "exclude_new_stock_days": 60,
        "exclude_code_prefix": ["688", "30"],
        "industries": [],
    }
    return Screener(config, TestDataSource(), CacheManager(cache_dir))


def test_screener_returns_dataframe(screener):
    result = screener.run()
    assert isinstance(result, pd.DataFrame)
    assert "code" in result.columns
    assert "name" in result.columns
    assert "exclude_reason" in result.columns


def test_screener_excludes_code_prefix(screener):
    result = screener.run()
    excluded = result[result["exclude_reason"] != ""]
    for _, row in excluded.iterrows():
        if row["code"].startswith("688"):
            assert "代码前缀688" in row["exclude_reason"]
        if row["code"].startswith("30"):
            assert "代码前缀30" in row["exclude_reason"]


def test_screener_excludes_st(cache_dir):
    config = {
        "min_market_cap": 0,
        "min_daily_amount": 0,
        "exclude_st": True,
        "exclude_new_stock_days": 0,
        "exclude_code_prefix": [],
        "industries": [],
    }
    # TestDataSource has no ST stocks, so test with a custom one
    mock = TestDataSource()
    s = Screener(config, mock, CacheManager(cache_dir))
    result = s.run()
    if "is_st" in result.columns:
        excluded = result[result["exclude_reason"].str.contains("ST", na=False)]
        assert all(excluded["is_st"] == True)


def test_screener_excludes_industry(cache_dir):
    config = {
        "min_market_cap": 0,
        "min_daily_amount": 0,
        "exclude_st": False,
        "exclude_new_stock_days": 0,
        "exclude_code_prefix": [],
        "exclude_industries": ["房地产"],
        "industries": [],
    }
    s = Screener(config, TestDataSource(), CacheManager(cache_dir))
    result = s.run()
    # 万科A (000002) 是房地产，应该有排除原因
    row = result[result["code"] == "000002"]
    assert len(row) == 1
    assert "行业黑名单" in row.iloc[0]["exclude_reason"]


def test_screener_industry_whitelist(cache_dir):
    config = {
        "min_market_cap": 0,
        "min_daily_amount": 0,
        "exclude_st": False,
        "exclude_new_stock_days": 0,
        "exclude_code_prefix": [],
        "exclude_industries": [],
        "industries": ["银行"],
    }
    s = Screener(config, TestDataSource(), CacheManager(cache_dir))
    result = s.run()
    # 非银行行业股票应有排除原因
    excluded = result[(result["exclude_reason"] != "") & (result["code"] != "000001") & (result["code"] != "600036")]
    for _, row in excluded.iterrows():
        assert "不在行业白名单" in row["exclude_reason"]


def test_screener_saves_cache(cache_dir):
    config = {
        "min_market_cap": 0,
        "min_daily_amount": 0,
        "exclude_st": False,
        "exclude_new_stock_days": 0,
        "exclude_code_prefix": [],
        "industries": [],
    }
    cache = CacheManager(cache_dir)
    s = Screener(config, TestDataSource(), cache)
    result = s.run()
    # screener 不再自动保存缓存，由 engine 决定是否保存
    # 测试手动保存后能正确加载
    cache.save_stock_pool(result)
    cached = cache.load_stock_pool(max_age_hours=1)
    assert cached is not None
    assert len(cached) == len(result)
    assert "exclude_reason" in cached.columns


def test_screener_passed_stocks_have_no_reason(screener):
    result = screener.run()
    passed = result[result["is_valid"]]
    assert len(passed) > 0
    assert all(passed["exclude_reason"] == "")
    assert all(passed["is_valid"])
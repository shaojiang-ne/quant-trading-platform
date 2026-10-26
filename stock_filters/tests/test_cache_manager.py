import pandas as pd
import pytest
import time
from data.cache_manager import CacheManager


@pytest.fixture
def cache(tmp_path):
    return CacheManager(str(tmp_path))


def test_save_and_load_stock_pool(cache):
    pool = pd.DataFrame({
        "code": ["000001", "600036"],
        "name": ["平安银行", "招商银行"],
        "industry": ["银行", "银行"],
    })
    cache.save_stock_pool(pool)
    loaded = cache.load_stock_pool(max_age_hours=1)
    assert loaded is not None
    assert len(loaded) == 2
    assert loaded["code"].tolist() == ["000001", "600036"]


def test_stock_pool_cache_expiry(cache):
    pool = pd.DataFrame({"code": ["000001"], "name": ["平安银行"]})
    cache.save_stock_pool(pool)
    # Manually set saved_at to past
    cache._save_meta("stock_pool", {"saved_at": time.time() - 3600 * 25})
    loaded = cache.load_stock_pool(max_age_hours=24)
    assert loaded is None


def test_save_and_load_industry_map(cache):
    mapping = {"000001": "银行", "000002": "房地产"}
    cache.save_industry_map(mapping)
    loaded = cache.load_industry_map(max_age_days=7)
    assert loaded is not None
    assert loaded["000001"] == "银行"
    assert loaded["000002"] == "房地产"


def test_industry_map_cache_expiry(cache):
    mapping = {"000001": "银行"}
    cache.save_industry_map(mapping)
    cache._save_meta("industry_map", {"saved_at": time.time() - 86400 * 8})
    loaded = cache.load_industry_map(max_age_days=7)
    assert loaded is None


def test_load_nonexistent_returns_none(cache):
    assert cache.load_stock_pool() is None
    assert cache.load_industry_map() is None

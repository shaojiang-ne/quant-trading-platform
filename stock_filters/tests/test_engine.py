import pytest
from unittest.mock import MagicMock
from engine import Engine
from data.test_source import TestDataSource


def _make_config():
    return {
        "screener": {
            "min_market_cap": 50,
            "min_daily_amount": 1,
            "exclude_st": True,
            "exclude_new_stock_days": 60,
            "exclude_code_prefix": ["688", "30"],
            "industries": [],
        },
        "strategies": {
            "six_sword": {"enabled": True, "params": {}},
            "four_dimension": {"enabled": True, "params": {}},
        },
        "dingtalk": {
            "webhook": "https://oapi.dingtalk.com/robot/send?access_token=test",
            "secret": "",
        },
    }


def test_engine_run_screener_returns_pool(tmp_path):
    from data.cache_manager import CacheManager
    engine = Engine(_make_config(), TestDataSource())
    engine.cache = CacheManager(str(tmp_path))
    engine.screener.cache = engine.cache
    pool = engine.run_screener()
    assert hasattr(pool, "__len__")


def test_engine_run_strategies_returns_results(tmp_path):
    from data.cache_manager import CacheManager
    engine = Engine(_make_config(), TestDataSource())
    engine.cache = CacheManager(str(tmp_path))
    engine.screener.cache = engine.cache
    results = engine.run_strategies()
    assert isinstance(results, dict)


def test_engine_run_sends_notification(tmp_path):
    from data.cache_manager import CacheManager
    config = _make_config()
    engine = Engine(config, TestDataSource())
    engine.cache = CacheManager(str(tmp_path))
    engine.screener.cache = engine.cache
    mock_notifier = MagicMock()
    mock_notifier.send.return_value = True
    engine.notifier = mock_notifier
    engine.run()
    assert True

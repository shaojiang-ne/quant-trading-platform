import numpy as np
import pandas as pd
import pytest
from strategies.base import BaseStrategy
from strategies import discover_strategies
from strategies.rsi_kdj import RsiKdjStrategy
from data.test_source import TestDataSource


@pytest.fixture
def mock_data():
    return TestDataSource()


def test_base_strategy_is_abstract():
    with pytest.raises(TypeError):
        BaseStrategy()


def test_discover_strategies_returns_dict():
    result = discover_strategies()
    assert isinstance(result, dict)
    assert len(result) > 0


def test_discover_includes_six_sword():
    result = discover_strategies()
    assert "six_sword" in result


def test_discover_includes_four_dimension():
    result = discover_strategies()
    assert "four_dimension" in result


def test_six_sword_scan_returns_list(mock_data):
    from strategies.six_sword import SixSwordStrategy
    strategy = SixSwordStrategy()
    pool = mock_data.get_stock_list()
    result = strategy.scan(pool, mock_data)
    assert isinstance(result, list)
    for item in result:
        assert "code" in item
        assert "conditions" in item


def test_four_dimension_scan_returns_list(mock_data):
    from strategies.four_dimension import FourDimensionStrategy
    strategy = FourDimensionStrategy()
    pool = mock_data.get_stock_list()
    result = strategy.scan(pool, mock_data)
    assert isinstance(result, list)
    for item in result:
        assert "code" in item
        assert "conditions" in item


def test_discover_includes_rsi_kdj():
    result = discover_strategies()
    assert "rsi_kdj" in result


def test_rsi_kdj_scan_returns_list(mock_data):
    strategy = RsiKdjStrategy()
    pool = mock_data.get_stock_list()
    result = strategy.scan(pool, mock_data)
    assert isinstance(result, list)
    for item in result:
        assert "code" in item
        assert "conditions" in item
        assert len(item["conditions"]) == 4


def test_rsi_kdj_conditions_structure():
    strategy = RsiKdjStrategy()
    n = 30
    close = np.linspace(10, 12, n)
    close[-1] = close[-2] * 1.02
    high = close * 1.02
    low = close * 0.98
    volume = np.full(n, 1000000.0)
    volume[-5:] = volume[-5:] * 1.5
    df = pd.DataFrame({"close": close, "high": high, "low": low, "volume": volume})
    conditions = strategy._check_conditions(df, "000001")
    assert set(conditions.keys()) == {"涨幅达标", "放量", "近期RSI超卖", "KDJ低位金叉"}

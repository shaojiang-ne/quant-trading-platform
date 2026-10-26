"""
动态生成策略测试 — resolve_strategy_class

验证 AI/用户动态生成的策略代码：
- exec 编译后能解析、注册进 STRATEGY_MAP / VNPY_STRATEGY_MAP
- 生成代码能驱动回测跑通且验算通过
- 语义对拍：自定义策略信号序列 == 内置等价策略
- 异常代码（语法错误）→ 返回 None 不抛

teardown 清理 STRATEGY_MAP / VNPY_STRATEGY_MAP 注入的 key，避免全局污染。
"""

import pytest
from datetime import datetime, date, timedelta

vnpy = pytest.importorskip("vnpy")
import numpy as np
from vnpy.trader.constant import Exchange, Interval

from app.core import strategy_adapter as sa
from app.strategies.base import STRATEGY_MAP, DoubleMaStrategy
from app.core.strategy_adapter import VNPY_STRATEGY_MAP, resolve_strategy_class
from app.services.vnpy_backtest_service import CtaBacktestingEngine
from tests.conftest import _make_df, df_to_bars, make_crossover_data

VTSYM = "600000.SSE"
CUSTOM_NAME = "CustomStrategy_test"

# 等价于内置 DoubleMaStrategy 的 generate_signals 函数（走"发现函数并包装"路径）
VALID_CODE = '''
def generate_signals(df, setting):
    import pandas as pd
    signals = pd.Series(0, index=df.index)
    fast = setting.get("fast_window", 5)
    slow = setting.get("slow_window", 20)
    fma = df["close"].rolling(window=fast, min_periods=fast).mean()
    sma_ = df["close"].rolling(window=slow, min_periods=slow).mean()
    cross_over = (fma > sma_) & (fma.shift(1) <= sma_.shift(1))
    cross_below = (fma < sma_) & (fma.shift(1) >= sma_.shift(1))
    signals[cross_over] = 1
    signals[cross_below] = -1
    return signals
'''

SYNTAX_ERROR_CODE = "def generate_signals(df, setting:\n    pass  # 语法错误"


class _FakeStrategy:
    def __init__(self, code):
        self.code = code


class _FakeQuery:
    def __init__(self, code):
        self._s = _FakeStrategy(code)

    def filter(self, *args, **kwargs):
        return self

    def first(self):
        return self._s


class _FakeSession:
    def __init__(self, code):
        self._q = _FakeQuery(code)

    def query(self, *args, **kwargs):
        return self._q

    def close(self):
        pass


def _make_fake_get_db(code):
    def fake_get_db():
        yield _FakeSession(code)
    return fake_get_db


@pytest.fixture
def custom_strategy(monkeypatch):
    """注册一个自定义策略，测试后清理全局 MAP"""
    import app.database as dbmod
    monkeypatch.setattr(dbmod, "get_db", _make_fake_get_db(VALID_CODE))
    cls = resolve_strategy_class(CUSTOM_NAME)
    yield cls
    # teardown：清理全局污染
    STRATEGY_MAP.pop(CUSTOM_NAME, None)
    VNPY_STRATEGY_MAP.pop(CUSTOM_NAME, None)


class TestDynamicResolution:
    def test_resolved_and_registered(self, custom_strategy):
        assert custom_strategy is not None
        assert CUSTOM_NAME in STRATEGY_MAP
        assert CUSTOM_NAME in VNPY_STRATEGY_MAP

    def test_semantic_match_builtin(self, custom_strategy):
        """自定义策略信号序列 == 内置 DoubleMaStrategy"""
        df = make_crossover_data(5, 20, n=80)
        s_builtin = DoubleMaStrategy.generate_signals(df, {"fast_window": 5, "slow_window": 20})
        s_custom = custom_strategy.generate_signals(df, {"fast_window": 5, "slow_window": 20})
        assert s_builtin.equals(s_custom)

    def test_runs_in_backtest(self, custom_strategy):
        """自定义策略驱动回测能跑通且验算前4项通过"""
        df = make_crossover_data(5, 20, n=120)
        bars = df_to_bars(df, symbol="600000", exchange=Exchange.SSE, interval=Interval.DAILY)
        engine = CtaBacktestingEngine()
        engine.set_parameters(
            vt_symbols=[VTSYM], interval=Interval.DAILY,
            start=datetime(2024, 1, 2), end=datetime(2024, 12, 31),
            rate=0.0003, stamp_tax_rate=0.001, size=1, pricetick=0.01, capital=1_000_000.0,
        )
        engine.add_strategy(VNPY_STRATEGY_MAP[CUSTOM_NAME], {"fast_window": 5, "slow_window": 20})
        for bar in bars:
            engine.dts.add(bar.datetime)
            engine.history_data[(bar.datetime, VTSYM)] = bar
        engine.strategy.on_init()
        engine.run_backtesting()
        stats = engine.calculate_result()
        if stats and stats.get("total_trades", 0) > 0:
            v = stats["verification"]
            for key in ("capital_conservation", "daily_pnl_sum", "equity_consistency", "max_drawdown"):
                assert v[key]["passed"] is True, f"{key}: {v[key]}"


class TestInvalidCode:
    def test_syntax_error_returns_none(self, monkeypatch):
        """语法错误的代码 → 返回 None，不抛异常"""
        import app.database as dbmod
        monkeypatch.setattr(dbmod, "get_db", _make_fake_get_db(SYNTAX_ERROR_CODE))
        cls = resolve_strategy_class("CustomStrategy_syntax_err")
        assert cls is None
        # 不应残留注册
        assert "CustomStrategy_syntax_err" not in STRATEGY_MAP

    def test_unknown_strategy_returns_none(self, monkeypatch):
        """DB 里找不到的策略 → 返回 None"""
        class _EmptyQuery:
            def filter(self, *a, **k): return self
            def first(self): return None
        class _EmptySession:
            def query(self, *a, **k): return _EmptyQuery()
            def close(self): pass
        def empty_get_db():
            yield _EmptySession()
        import app.database as dbmod
        monkeypatch.setattr(dbmod, "get_db", empty_get_db)
        assert resolve_strategy_class("NonExistentStrategy_xyz") is None

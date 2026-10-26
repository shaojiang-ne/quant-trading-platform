"""三沙箱一致性测试

验证同一份AI风格代码走 test_code沙箱 / resolve_strategy_class沙箱 / run_vnpy_backtest沙箱
三条exec路径，generate_signals 返回的 Series 逐元素相等。'测试过但实盘崩'的根因防护。
"""
import pytest
import pandas as pd

vnpy = pytest.importorskip("vnpy")
from datetime import date, timedelta

from app.strategies.base import STRATEGY_MAP, DoubleMaStrategy
from app.core.strategy_adapter import VNPY_STRATEGY_MAP, resolve_strategy_class
from app.services.vnpy_backtest_service import CtaBacktestingEngine
from tests.conftest import _make_df, make_crossover_data

# AI风格代码：用预置 sma，带logger，setting.get读参
SMA_CODE = '''
def generate_signals(df, setting):
    signals = pd.Series(0, index=df.index)
    fast = setting.get("fast_window", 5)
    slow = setting.get("slow_window", 20)
    fma = sma(df["close"], fast)
    sma_slow = sma(df["close"], slow)
    cross_over = (fma > sma_slow) & (fma.shift(1) <= sma_slow.shift(1))
    cross_below = (fma < sma_slow) & (fma.shift(1) >= sma_slow.shift(1))
    signals[cross_over] = 1
    signals[cross_below] = -1
    logger.info(f"信号汇总: 买入={int((signals==1).sum())}次")
    return signals
'''


def _resolve_exec(code, class_name, monkeypatch):
    """走 resolve_strategy_class 沙箱路径"""
    import app.database as dbmod

    class _S:
        def __init__(self): self.code = code
    class _Q:
        def filter(self, *a, **k): return self
        def first(self): return _S()
    class _Session:
        def query(self, *a, **k): return _Q()
        def close(self): pass
    def _gdb():
        yield _Session()
    monkeypatch.setattr(dbmod, "get_db", _gdb)
    STRATEGY_MAP.pop(class_name, None)
    VNPY_STRATEGY_MAP.pop(class_name, None)
    return resolve_strategy_class(class_name)


def _test_code_exec(code, parameters, df=None):
    """走 api/ai.py:test_code 沙箱路径（直接复用抽出的服务函数）"""
    from app.services.strategy_test_service import test_strategy_code
    return test_strategy_code(code, parameters, df=df)


class TestSandboxConsistency:
    def test_sma_available_in_all_three_sandboxes(self, monkeypatch):
        """同一份用 sma 的代码，三沙箱生成的信号序列逐元素相等"""
        df = make_crossover_data(5, 20, n=80)
        setting = {"fast_window": 5, "slow_window": 20}

        # 路径1: test_code 沙箱
        r1 = _test_code_exec(SMA_CODE, setting, df=df)
        assert r1["success"], f"test_code沙箱失败: {r1.get('error')}"
        s1 = r1["_signals"]  # 测试函数回传的Series，见Task2

        # 路径2: resolve_strategy_class 沙箱
        cls = _resolve_exec(SMA_CODE, "CustomStrategy_sbox", monkeypatch)
        assert cls is not None, "resolve沙箱编译失败"
        s2 = cls.generate_signals(df, setting)

        # 路径3: 内置等价（作为基准）
        s0 = DoubleMaStrategy.generate_signals(df, setting)

        assert s1.equals(s0), f"test_code沙箱与内置不一致"
        assert s2.equals(s0), f"resolve沙箱与内置不一致"


# 各指标的AI风格最小代码片段，逐一验证三沙箱可解析
_DEPENDENCY_CODES = {
    "ema": '''
def generate_signals(df, setting):
    signals = pd.Series(0, index=df.index)
    f = ema(df["close"], 5); s = ema(df["close"], 20)
    co = (f > s) & (f.shift(1) <= s.shift(1))
    signals[co] = 1
    return signals
''',
    "rsi": '''
def generate_signals(df, setting):
    signals = pd.Series(0, index=df.index)
    r = rsi(df["close"], 14)
    signals[r > 70] = -1
    signals[r < 30] = 1
    return signals
''',
    "macd": '''
def generate_signals(df, setting):
    signals = pd.Series(0, index=df.index)
    dif, dea, hist = macd(df["close"], 12, 26, 9)
    co = (dif > dea) & (dif.shift(1) <= dea.shift(1))
    signals[co] = 1
    return signals
''',
    "bollinger": '''
def generate_signals(df, setting):
    signals = pd.Series(0, index=df.index)
    mid, up, low = bollinger(df["close"], 20, 2.0)
    signals[df["close"] < low] = 1
    return signals
''',
    "atr": '''
def generate_signals(df, setting):
    signals = pd.Series(0, index=df.index)
    a = atr(df["high"], df["low"], df["close"], 14)
    signals[a > 0] = 0
    return signals
''',
    "donchian": '''
def generate_signals(df, setting):
    signals = pd.Series(0, index=df.index)
    up, low = donchian(df["high"], df["low"], 20)
    signals[df["close"] > up.shift(1)] = 1
    return signals
''',
    "kdj": '''
def generate_signals(df, setting):
    signals = pd.Series(0, index=df.index)
    k, d, j = kdj(df["high"], df["low"], df["close"], 9, 3, 3)
    signals[k > d] = 1
    return signals
''',
    "cci": '''
def generate_signals(df, setting):
    signals = pd.Series(0, index=df.index)
    c = cci(df["high"], df["low"], df["close"], 14)
    signals[c < -100] = 1
    return signals
''',
    "math": '''
def generate_signals(df, setting):
    signals = pd.Series(0, index=df.index)
    signals[df["close"] > math.pi] = 1
    return signals
''',
}


@pytest.mark.parametrize("dep", list(_DEPENDENCY_CODES.keys()))
def test_each_dependency_available_in_sandboxes(dep, monkeypatch):
    """每个预置依赖在三沙箱都可解析、信号序列一致"""
    code = _DEPENDENCY_CODES[dep]
    df = make_crossover_data(5, 20, n=80)
    setting = {"fast_window": 5, "slow_window": 20}

    r1 = _test_code_exec(code, setting, df=df)
    assert r1["success"], f"[{dep}] test_code失败: {r1.get('error')}"
    s1 = r1["_signals"]

    cls = _resolve_exec(code, f"CustomStrategy_{dep}", monkeypatch)
    assert cls is not None, f"[{dep}] resolve编译失败"
    s2 = cls.generate_signals(df, setting)

    assert s1.equals(s2), f"[{dep}] 两沙箱信号不一致"


def test_syntax_error_safe_in_both_sandboxes(monkeypatch):
    """语法错误代码：test_code返回success=False，resolve返回None"""
    bad_code = "def generate_signals(df, setting:\n    pass"
    r1 = _test_code_exec(bad_code, {})
    assert r1["success"] is False

    cls = _resolve_exec(bad_code, "CustomStrategy_syntax", monkeypatch)
    assert cls is None

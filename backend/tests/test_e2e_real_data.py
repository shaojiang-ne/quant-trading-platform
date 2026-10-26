"""层2端到端集成测试 — 真实5年多股

预录3份AI风格策略代码 × 4只代表性个股 × 近5年真实K线
→ run_vnpy_backtest + 5项验算 + 无未来函数 + 预计算/增量一致
"""
import pytest

vnpy = pytest.importorskip("vnpy")
from app.services.vnpy_backtest_service import run_vnpy_backtest
from app.core.strategy_adapter import VNPY_STRATEGY_MAP
from app.strategies.base import STRATEGY_MAP
from app.core.strategy_adapter import resolve_strategy_class
from tests.conftest import load_real_bars

START = "2021-07-04"
END = "2026-07-04"
HALF_END = "2023-12-31"

SYMBOLS = ["600519", "000001", "300750", "002594"]

# 3份预录AI风格策略代码（不调LLM，字符串常量；用预置指标 + logger + setting.get）
STRATEGY_DOUBLE_MA = '''
def generate_signals(df, setting):
    signals = pd.Series(0, index=df.index)
    fast = setting.get("fast_window", 10)
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

STRATEGY_RSI = '''
def generate_signals(df, setting):
    signals = pd.Series(0, index=df.index)
    r = rsi(df["close"], setting.get("rsi_window", 14))
    oversold = (r > 30) & (r.shift(1) <= 30)
    overbought = (r < 70) & (r.shift(1) >= 70)
    signals[oversold] = 1
    signals[overbought] = -1
    return signals
'''

STRATEGY_BOLL = '''
def generate_signals(df, setting):
    signals = pd.Series(0, index=df.index)
    mid, up, low = bollinger(df["close"], setting.get("boll_window", 20), setting.get("boll_dev", 2.0))
    below = df["close"] < low
    above = df["close"] > up
    touch_lower = below.shift(1).fillna(False) & ~below
    touch_upper = above.shift(1).fillna(False) & ~above
    signals[touch_lower] = 1
    signals[touch_upper] = -1
    return signals
'''


def _register_custom(code: str, class_name: str) -> str:
    """注册自定义策略到 STRATEGY_MAP/VNPY_STRATEGY_MAP，走 resolve_strategy_class 沙箱路径。

    直接替换 app.database.get_db 模块属性（不经 monkeypatch，便于在 fixture 中调用），
    调用方负责清理（_unregister）。
    """
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

    _orig = getattr(dbmod, "get_db", None)
    dbmod.get_db = _gdb
    STRATEGY_MAP.pop(class_name, None)
    VNPY_STRATEGY_MAP.pop(class_name, None)
    cls = resolve_strategy_class(class_name)
    # 恢复 get_db
    if _orig is not None:
        dbmod.get_db = _orig
    assert cls is not None, f"注册策略 {class_name} 编译失败"
    return class_name


def _unregister(class_name: str) -> None:
    STRATEGY_MAP.pop(class_name, None)
    VNPY_STRATEGY_MAP.pop(class_name, None)


@pytest.fixture(scope="module")
def real_data():
    """加载4只个股5年真实数据，失败全模块skip"""
    loaded = {}
    for sym in SYMBOLS:
        res = load_real_bars(sym, START, END, period="1d")
        if res is None:
            pytest.skip(f"无法加载 {sym} 真实数据，跳过层2端到端")
        loaded[sym] = res
    return loaded


@pytest.fixture(scope="module")
def custom_strategies():
    """注册3个预录自定义策略（module级，整个模块共享）"""
    names = {
        "double_ma": _register_custom(STRATEGY_DOUBLE_MA, "E2eDoubleMa"),
        "rsi": _register_custom(STRATEGY_RSI, "E2eRsi"),
        "boll": _register_custom(STRATEGY_BOLL, "E2eBoll"),
    }
    yield names
    for cn in names.values():
        _unregister(cn)


def _run(class_name, symbol, setting, incremental=True, end=END):
    return run_vnpy_backtest(
        class_name=class_name, symbol=symbol,
        start_date=START, end_date=end,
        capital=1_000_000.0, setting=setting,
        period="daily", incremental_mode=incremental,
    )


def _assert_verification(stats, allow_open_position=False):
    """5项验算断言。

    allow_open_position=True：允许第5项(trade_pnl_consistency)因末尾持仓不通过
    （已知缺陷，见 MEMORY「验算第5项末尾持仓误报」），其余4项仍必须通过。
    """
    v = stats["verification"]
    for key in ("capital_conservation", "daily_pnl_sum", "equity_consistency", "max_drawdown"):
        assert v[key]["passed"] is True, f"{key}: {v[key]}"
    if not allow_open_position:
        # 末尾无持仓：5项全过且 overall 必为 True
        assert v["trade_pnl_consistency"]["passed"] is True, f"第5项: {v['trade_pnl_consistency']}"
        assert v["overall"]["passed"] is True, f"overall: {v['overall']}"
    else:
        # 末尾可能持仓：第5项允许失败，但失败原因必须只涉及 trade_pnl_consistency
        if not v["overall"]["passed"]:
            failed = v["overall"]["failed_items"]
            assert failed == ["trade_pnl_consistency"], (
                f"overall 失败项不止第5项: {failed}")


def _trade_key(t):
    """交易唯一键：date+side+price+quantity"""
    return (t["date"], t["side"], t["price"], t["quantity"])


@pytest.mark.parametrize("sym", SYMBOLS)
class TestE2eRealData:
    def test_double_ma(self, real_data, custom_strategies, sym):
        stats = _run(custom_strategies["double_ma"], sym,
                     {"fast_window": 10, "slow_window": 20})
        assert stats["total_trades"] > 0, f"{sym} 无交易产生"
        _assert_verification(stats)

    def test_rsi(self, real_data, custom_strategies, sym):
        stats = _run(custom_strategies["rsi"], sym, {"rsi_window": 14})
        # RSI 可能末尾持仓，允许第5项不通过
        _assert_verification(stats, allow_open_position=True)

    def test_boll(self, real_data, custom_strategies, sym):
        stats = _run(custom_strategies["boll"], sym,
                     {"boll_window": 20, "boll_dev": 2.0})
        _assert_verification(stats, allow_open_position=True)

    def test_no_lookahead(self, real_data, custom_strategies, sym):
        """截断前半段交易 ⊂ 全量交易（无未来函数）"""
        full = _run(custom_strategies["double_ma"], sym,
                    {"fast_window": 10, "slow_window": 20}, end=END)
        half = _run(custom_strategies["double_ma"], sym,
                    {"fast_window": 10, "slow_window": 20}, end=HALF_END)
        full_keys = {_trade_key(t) for t in full["trades"]}
        missing = [t for t in half["trades"] if _trade_key(t) not in full_keys]
        assert missing == [], f"{sym} 前半段交易不在全量中(未来函数): {missing[:3]}"

    def test_precompute_vs_incremental(self, real_data, custom_strategies, sym):
        """预计算 vs 增量：交易笔数一致"""
        pre = _run(custom_strategies["double_ma"], sym,
                   {"fast_window": 10, "slow_window": 20}, incremental=False)
        inc = _run(custom_strategies["double_ma"], sym,
                   {"fast_window": 10, "slow_window": 20}, incremental=True)
        assert pre["total_trades"] == inc["total_trades"], (
            f"{sym} 预计算({pre['total_trades']}) != 增量({inc['total_trades']})")

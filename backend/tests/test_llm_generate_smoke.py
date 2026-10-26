"""层3真实LLM冒烟测试（slow标记，CI跳过，本地手动）

验证"AI生成代码→自动测试→回测"链路在真实讯飞LLM下能跑通。
不验证LLM质量——LLM输出平庸只要能编译跑通验算过即通过。
LLM过载/网络错时 skip 不算失败。
"""
import pytest
import re

pytestmark = [pytest.mark.slow]


def _llm_configured():
    from app.config import settings
    return bool(getattr(settings, "LLM_API_KEY", None))


PROMPTS = [
    "双均线金叉买入死叉卖出策略",
    "RSI超卖买入超买卖出策略",
    "布林下轨触轨买入上轨卖出策略",
]


def _extract_code(text: str) -> str:
    """从LLM输出提取 ```python``` 代码块"""
    m = re.search(r"```python\n([\s\S]*?)```", text)
    if not m:
        m = re.search(r"```\n([\s\S]*?)```", text)
    return m.group(1) if m else ""


@pytest.mark.parametrize("idea", PROMPTS)
@pytest.mark.asyncio
async def test_llm_generate_then_test_then_backtest(idea):
    """真实调讯飞生成→test_code校验→回测验算前4项"""
    if not _llm_configured():
        pytest.skip("LLM_API_KEY 未配置，跳过LLM冒烟")

    from app.services.ai_service import ai_service, _is_transient_llm_error
    from app.services.strategy_test_service import test_strategy_code

    ai_service._ensure_client()
    if not ai_service.client:
        pytest.skip("AI客户端未初始化")

    # 调 generate_stream phase=generate，收集文本
    messages = [{"role": "user", "content": f"请生成策略：{idea}"}]
    chunks = []
    try:
        async for chunk in ai_service.generate_stream(messages, phase="generate"):
            if chunk.startswith('data: '):
                import json
                payload = json.loads(chunk[6:])
                if payload.get("type") == "text":
                    chunks.append(payload["content"])
                elif payload.get("type") == "error":
                    pytest.skip(f"LLM返回错误(可能过载): {payload.get('error','')[:80]}")
    except Exception as e:
        if _is_transient_llm_error(e):
            pytest.skip(f"讯飞过载/网络错，跳过: {str(e)[:80]}")
        raise

    text = "".join(chunks)
    code = _extract_code(text)
    if not code:
        pytest.skip(f"LLM未输出python代码块(输出: {text[:80]})")

    # test_code 校验
    result = test_strategy_code(code, {})
    if not result["success"]:
        pytest.skip(f"LLM生成代码test_code失败(预期,LLM质量问题): {result.get('error','')[:80]}")

    # 回测验算前4项
    from app.services.vnpy_backtest_service import CtaBacktestingEngine
    from app.core.strategy_adapter import resolve_strategy_class, VNPY_STRATEGY_MAP
    from app.strategies.base import STRATEGY_MAP
    import app.database as dbmod
    from tests.conftest import make_crossover_data, df_to_bars
    from datetime import datetime
    from vnpy.trader.constant import Exchange, Interval

    # 注册LLM生成的策略
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
    dbmod.get_db = _gdb
    cname = "LlmSmokeStrategy"
    STRATEGY_MAP.pop(cname, None)
    VNPY_STRATEGY_MAP.pop(cname, None)
    cls = resolve_strategy_class(cname)
    assert cls is not None, "LLM生成代码resolve失败"

    df = make_crossover_data(5, 20, n=120)
    bars = df_to_bars(df, symbol="600000")
    eng = CtaBacktestingEngine()
    eng.set_parameters(
        vt_symbols=["600000.SSE"], interval=Interval.DAILY,
        start=datetime(2024, 1, 2), end=datetime(2024, 12, 31),
        rate=0.0003, stamp_tax_rate=0.001, size=1, pricetick=0.01, capital=1_000_000.0,
    )
    eng.add_strategy(VNPY_STRATEGY_MAP[cname], {"fast_window": 5, "slow_window": 20})
    for bar in bars:
        eng.dts.add(bar.datetime)
        eng.history_data[(bar.datetime, "600000.SSE")] = bar
    eng.strategy.on_init()
    eng.run_backtesting()
    stats = eng.calculate_result()
    v = stats["verification"]
    for key in ("capital_conservation", "daily_pnl_sum", "equity_consistency", "max_drawdown"):
        assert v[key]["passed"] is True, f"{key}未过: {v[key]}"

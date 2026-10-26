"""选股规则程序校验 + 解释器单测。"""
import pytest
from app.services.agent_service import (
    validate_pick_rules, run_pick_program, PickRuleError,
)


async def _no_sleep(*_a, **_k):
    """跳过退避 sleep 的 awaitable mock。"""
    return None


def test_valid_rules_pass():
    rules = {
        "pool": "hs300",
        "filters": [{"field": "pe_ttm", "op": "<=", "value": 30}],
        "scoring": [{"field": "vol_ratio", "weight": 12, "direction": "high"}],
        "top_n": 6,
    }
    assert validate_pick_rules(rules) is True


def test_empty_rules_rejected():
    with pytest.raises(PickRuleError):
        validate_pick_rules([])


def test_unsupported_pool_rejected():
    rules = {"pool": "csi_a500", "filters": [], "scoring": [], "top_n": 6}
    with pytest.raises(PickRuleError):
        validate_pick_rules(rules)


def test_supported_pools_pass():
    for pool in ("hs300", "sse50", "star50"):
        assert validate_pick_rules({"pool": pool, "filters": [], "scoring": [], "top_n": 6}) is True


def test_bad_field_rejected():
    rules = {"pool": "hs300",
             "filters": [{"field": "unknown_field", "op": "<=", "value": 30}],
             "scoring": [], "top_n": 6}
    with pytest.raises(PickRuleError):
        validate_pick_rules(rules)


def test_bad_op_rejected():
    rules = {"pool": "hs300",
             "filters": [{"field": "pe_ttm", "op": "!=", "value": 30}],
             "scoring": [], "top_n": 6}
    with pytest.raises(PickRuleError):
        validate_pick_rules(rules)


def test_non_numeric_value_rejected():
    rules = {"pool": "hs300",
             "filters": [{"field": "pe_ttm", "op": "<=", "value": "abc"}],
             "scoring": [], "top_n": 6}
    with pytest.raises(PickRuleError):
        validate_pick_rules(rules)


def test_bad_direction_rejected():
    rules = {"pool": "hs300", "filters": [],
             "scoring": [{"field": "vol_ratio", "weight": 12, "direction": "up"}],
             "top_n": 6}
    with pytest.raises(PickRuleError):
        validate_pick_rules(rules)


def test_top_n_bounds():
    # 默认6(省略时)
    assert validate_pick_rules({"pool": "hs300", "filters": [], "scoring": []}) is True
    # 越界
    with pytest.raises(PickRuleError):
        validate_pick_rules({"pool": "hs300", "filters": [], "scoring": [], "top_n": 0})
    with pytest.raises(PickRuleError):
        validate_pick_rules({"pool": "hs300", "filters": [], "scoring": [], "top_n": 21})


def test_nan_value_rejected():
    rules = {"pool": "hs300",
             "filters": [{"field": "pe_ttm", "op": "<=", "value": "nan"}],
             "scoring": [], "top_n": 6}
    with pytest.raises(PickRuleError):
        validate_pick_rules(rules)


def test_inf_weight_rejected():
    rules = {"pool": "hs300", "filters": [],
             "scoring": [{"field": "vol_ratio", "weight": "inf", "direction": "high"}],
             "top_n": 6}
    with pytest.raises(PickRuleError):
        validate_pick_rules(rules)


def _q(code, name, pe, vol, turn, chg):
    """造一行行情快照。"""
    return {"code": code, "name": name, "price": 10.0, "change_pct": chg,
            "turnover_pct": turn, "pe_ttm": pe, "pb": 1.0,
            "float_mcap_yi": 100.0, "vol_ratio": vol, "amount_wan": 1000.0}


def test_filters_hard_filter():
    rules = {"pool": "hs300",
             "filters": [{"field": "pe_ttm", "op": "<=", "value": 20},
                         {"field": "pe_ttm", "op": ">", "value": 0}],
             "scoring": [], "top_n": 10}
    quotes = [_q("A", "A", 15, 2, 3, 1),   # PE15 通过
              _q("B", "B", 25, 2, 3, 1),   # PE25 被滤
              _q("C", "C", -5, 2, 3, 1)]   # PE负 被滤
    out = run_pick_program(rules, quotes)
    codes = [s[2]["code"] for s in out]
    assert codes == ["A"]


def test_scoring_high_direction():
    # 量比越高分越高
    rules = {"pool": "hs300", "filters": [],
             "scoring": [{"field": "vol_ratio", "weight": 10, "direction": "high"}],
             "top_n": 3}
    quotes = [_q("A", "A", 10, 1.0, 3, 1),
              _q("B", "B", 10, 3.0, 3, 1),
              _q("C", "C", 10, 2.0, 3, 1)]
    out = run_pick_program(rules, quotes)
    codes = [s[2]["code"] for s in out]
    assert codes == ["B", "C", "A"]  # 量比 3 > 2 > 1


def test_scoring_low_direction():
    # PE 越低分越高
    rules = {"pool": "hs300", "filters": [],
             "scoring": [{"field": "pe_ttm", "weight": 10, "direction": "low"}],
             "top_n": 3}
    quotes = [_q("A", "A", 30, 2, 3, 1),
              _q("B", "B", 10, 2, 3, 1),
              _q("C", "C", 20, 2, 3, 1)]
    out = run_pick_program(rules, quotes)
    codes = [s[2]["code"] for s in out]
    assert codes == ["B", "C", "A"]  # PE 10 < 20 < 30


def test_top_n_limit():
    rules = {"pool": "hs300", "filters": [], "scoring": [], "top_n": 2}
    quotes = [_q("A", "A", 10, 2, 3, 1), _q("B", "B", 10, 2, 3, 1),
              _q("C", "C", 10, 2, 3, 1)]
    out = run_pick_program(rules, quotes)
    assert len(out) == 2


def test_empty_rules_keeps_all():
    # 空 filters + 空 scoring → 全部保留，统一基准分
    rules = {"pool": "hs300", "filters": [], "scoring": [], "top_n": 6}
    quotes = [_q("A", "A", 10, 2, 3, 1), _q("B", "B", 10, 2, 3, 1)]
    out = run_pick_program(rules, quotes)
    assert len(out) == 2
    assert all(s[0] == 60 for s in out)  # 基准分


def test_missing_field_filtered():
    # 取不到字段值的股票在 filters 阶段被淘汰
    rules = {"pool": "hs300",
             "filters": [{"field": "pe_ttm", "op": ">", "value": 0}],
             "scoring": [], "top_n": 6}
    bad = _q("X", "X", 0, 2, 3, 1)
    bad["pe_ttm"] = None  # 模拟取不到
    quotes = [bad, _q("A", "A", 15, 2, 3, 1)]
    out = run_pick_program(rules, quotes)
    assert [s[2]["code"] for s in out] == ["A"]


def test_negative_weight_penalizes_top():
    """负权重 high 项会惩罚该字段最高的候选（锁定当前行为）。"""
    rules = {"pool": "hs300", "filters": [],
             "scoring": [{"field": "vol_ratio", "weight": -10, "direction": "high"}],
             "top_n": 3}
    quotes = [_q("A", "A", 10, 1.0, 3, 1),   # 量比最低 → norm=0 → 60
              _q("B", "B", 10, 3.0, 3, 1),   # 量比最高 → norm=1 → 60-10=50
              _q("C", "C", 10, 2.0, 3, 1)]   # norm=0.5 → 60-5=55
    out = run_pick_program(rules, quotes)
    codes = [s[2]["code"] for s in out]
    assert codes == ["A", "C", "B"]  # 分 60 > 55 > 50


def test_fetch_pool_quotes_uses_pool(monkeypatch):
    """_fetch_pool_quotes(pool) 按映射取对应指数成分股。"""
    from app.services import agent_service

    called = {}

    def fake_constituents(index_code):
        called["index_code"] = index_code
        return [{"code": "600000", "name": "浦发银行"}]

    def fake_quotes(codes, name_map=None):
        return {codes[0]: {"code": codes[0], "name": "浦发银行", "price": 10.0,
                           "change_pct": 1.0, "turnover_pct": 2.0, "pe_ttm": 5.0,
                           "pb": 0.5, "float_mcap_yi": 1000.0, "vol_ratio": 1.2,
                           "amount_wan": 5000.0}}

    # staticmethod 必需：否则 fake_constituents 会被绑定为实例方法，
    # Python 把实例当 self 传入 → fake_constituents(self, index_code) 参数数量不符，
    # 异常被 _fetch_index_pool 吞掉，mock 实际未生效（called 不会被设置）。
    monkeypatch.setattr(agent_service, "_get_auto_source",
                        lambda: type("S", (), {"get_index_constituents": staticmethod(fake_constituents),
                                                "get_snapshot": staticmethod(fake_quotes)})())
    monkeypatch.setattr(agent_service, "_fetch_quotes", fake_quotes)

    out = agent_service._fetch_pool_quotes("sse50")
    assert called["index_code"] == "000016"
    assert out[0]["code"] == "600000"


def test_fetch_pool_quotes_default_pool(monkeypatch):
    """不传 pool 默认 hs300（向后兼容现有调用）。"""
    from app.services import agent_service
    called = {}
    # staticmethod 必需：否则 fake_constituents 会被绑定为实例方法，
    # Python 把实例当 self 传入 → fake_constituents(self, index_code) 参数数量不符，
    # 异常被 _fetch_index_pool 吞掉，mock 实际未生效（called 不会被设置）。
    monkeypatch.setattr(agent_service, "_get_auto_source",
                        lambda: type("S", (), {
                            "get_index_constituents": staticmethod(lambda c: (called.__setitem__("c", c), [{"code": "600000", "name": "X"}])[1]),
                            "get_snapshot": staticmethod(lambda codes: {codes[0]: {"code": codes[0], "name": "X", "price": 1, "change_pct": 0, "turnover_pct": 0, "pe_ttm": 0, "pb": 0, "float_mcap_yi": 0, "vol_ratio": 0, "amount_wan": 0}}),
                        })())
    out = agent_service._fetch_pool_quotes()
    assert called["c"] == "000300"
    assert len(out) == 1


@pytest.mark.asyncio
async def test_execute_rejects_empty_rules():
    """draft（rules 空）执行被拒绝。"""
    from app.services import agent_service
    from app.models import PickStrategy
    strategy = PickStrategy(user_id="t", name="t", description="d",
                            optimized_description="d", rules=[], status="draft")
    with pytest.raises(PickRuleError):
        await agent_service.execute_pick_strategy(None, strategy, "t")


def test_hs300_screen_max_criteria_becomes_filter(monkeypatch):
    """hs300_screen 工具：pe_max 应转为 filter(op<=)，不奖励高 PE。"""
    from app.services import agent_service

    # 造行情：A 的 PE 超上限应被滤掉，B 在上限内保留
    quotes = [_q("A", "A", 40, 2, 3, 1),   # PE40 > 上限20 → 应被 filter 滤掉
              _q("B", "B", 15, 2, 3, 1)]   # PE15 ≤ 20 → 保留
    monkeypatch.setattr(agent_service, "_fetch_pool_quotes", lambda pool="hs300": quotes)

    out_json = agent_service.execute_pick_tool("hs300_screen", {"pe_max": 20, "top_n": 10})
    import json
    data = json.loads(out_json)
    codes = [r["code"] for r in data["results"]]
    assert "A" not in codes   # PE40 被滤
    assert "B" in codes       # PE15 保留


@pytest.mark.asyncio
async def test_think_and_optimize_uses_multi_round(monkeypatch):
    """多轮思考：每轮 _ai_json 被调用，最终取最后一轮产出。"""
    from app.services import agent_service
    calls = []

    async def fake_ai_json(system, user, temperature=0.3):
        calls.append(user)
        # 三轮分别返回不同初稿
        n = len(calls)
        return {"optimized": f"第{n}轮优化稿", "name": "测试"}

    monkeypatch.setattr(agent_service, "_ai_json", fake_ai_json)
    monkeypatch.setattr(agent_service.asyncio, "sleep", _no_sleep)
    out = await agent_service.think_and_optimize_strategy("低估值蓝筹")
    assert "第3轮优化稿" in out  # 默认3轮，取最后一轮
    assert len(calls) == 3


@pytest.mark.asyncio
async def test_think_degrades_on_llm_failure(monkeypatch):
    """LLM 全失败 → 退化返回原描述。"""
    from app.services import agent_service

    async def fake_ai_json(system, user, temperature=0.3):
        return None

    monkeypatch.setattr(agent_service, "_ai_json", fake_ai_json)
    monkeypatch.setattr(agent_service.asyncio, "sleep", _no_sleep)
    out = await agent_service.think_and_optimize_strategy("低估值蓝筹")
    assert out == "低估值蓝筹"


@pytest.mark.asyncio
async def test_compile_valid_rules(monkeypatch):
    """LLM 返回合法规则 → 校验通过返回。"""
    from app.services import agent_service

    async def fake_ai_json(system, user, temperature=0.3):
        return {"pool": "hs300",
                "filters": [{"field": "pe_ttm", "op": "<=", "value": 30}],
                "scoring": [{"field": "vol_ratio", "weight": 10, "direction": "high"}],
                "top_n": 6}

    monkeypatch.setattr(agent_service, "_ai_json", fake_ai_json)

    monkeypatch.setattr(agent_service.asyncio, "sleep", _no_sleep)

    rules = await agent_service.compile_pick_rules("低估值蓝筹，PE低于30")
    assert rules["pool"] == "hs300"
    assert validate_pick_rules(rules) is True


@pytest.mark.asyncio
async def test_compile_invalid_then_retry(monkeypatch):
    """LLM 先返回非法 pool，重试后合法 → 返回合法规则。"""
    from app.services import agent_service
    seq = [{"pool": "csi_a500", "filters": [], "scoring": [], "top_n": 6},  # 非法
           {"pool": "hs300", "filters": [], "scoring": [], "top_n": 6}]      # 合法

    async def fake_ai_json(system, user, temperature=0.3):
        return seq.pop(0)

    monkeypatch.setattr(agent_service, "_ai_json", fake_ai_json)

    monkeypatch.setattr(agent_service.asyncio, "sleep", _no_sleep)

    rules = await agent_service.compile_pick_rules("某策略")
    assert rules["pool"] == "hs300"


@pytest.mark.asyncio
async def test_compile_all_fail_returns_none(monkeypatch):
    """LLM 全失败 → 返回 None（confirm 端点据此保持 draft）。"""
    from app.services import agent_service

    async def fake_ai_json(system, user, temperature=0.3):
        return None

    monkeypatch.setattr(agent_service, "_ai_json", fake_ai_json)

    monkeypatch.setattr(agent_service.asyncio, "sleep", _no_sleep)

    rules = await agent_service.compile_pick_rules("某策略")
    assert rules is None


@pytest.mark.asyncio
async def test_execute_full_pipeline_with_mock_quotes(monkeypatch):
    """端到端(mock 行情):rules 程序经 execute_pick_strategy 跑通,产出 Top 结果并落库。
    不依赖网络/LLM。"""
    from app.services import agent_service
    from app.models import PickStrategy, PickResult

    # 伪造沪深300行情:PE/量比/换手各异
    fake_quotes = [
        _q("A", "A低PE高量比", 12, 3.0, 5.0, 2),   # PE12 通过(≤20,>0),量比高
        _q("B", "B中", 18, 1.8, 3.0, 1),            # PE18 通过
        _q("C", "C高PE", 35, 2.0, 3.0, 1),          # PE35 被滤(>20)
        _q("D", "D负PE", -5, 2.0, 3.0, 1),          # PE负 被滤(<=0)
        _q("E", "E低量比", 15, 0.5, 1.0, 0),        # PE15 通过,量比低
    ]
    monkeypatch.setattr(agent_service, "_fetch_pool_quotes", lambda pool="hs300": fake_quotes)

    # 伪造 db:用内存 Session 替代真实 MySQL
    from sqlalchemy.orm import Session
    from unittest.mock import MagicMock
    db = MagicMock(spec=Session)
    added = []
    db.add = lambda obj: added.append(obj)
    db.commit = lambda: None

    rules = {
        "pool": "hs300",
        "filters": [
            {"field": "pe_ttm", "op": "<=", "value": 20},
            {"field": "pe_ttm", "op": ">", "value": 0},
        ],
        "scoring": [
            {"field": "vol_ratio", "weight": 12, "direction": "high"},
            {"field": "turnover_pct", "weight": 6, "direction": "high"},
        ],
        "top_n": 6,
    }
    strategy = PickStrategy(user_id="t", name="t", description="d",
                            optimized_description="d", rules=rules, status="confirmed")

    results = await agent_service.execute_pick_strategy(db, strategy, "t")

    # 断言:C(PE35)和 D(PE负)被 filters 滤掉;A/B/E 保留并按分排序
    codes = [r.code for r in results]
    assert "C" not in codes
    assert "D" not in codes
    assert set(codes) == {"A", "B", "E"}
    # A 量比最高(3.0)、换手最高(5.0)→ 应排第一
    assert codes[0] == "A"
    # 落库:db.add 被调了 3 次(每只结果一次)
    assert len(added) == 3
    # PickResult 字段正确
    assert all(r.strategy_id == strategy.id for r in results)
    assert all(r.match_score is not None for r in results)

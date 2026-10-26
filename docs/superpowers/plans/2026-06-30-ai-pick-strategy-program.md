# AI 选股策略规则程序化 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 把 AI 选股从「执行时现解析+硬编码打分」改为「用户确认后把策略固化为结构化规则程序,执行时跑解释器」,候选股池支持沪深300/上证50/科创50多指数。

**Architecture:** 复用 `PickStrategy.rules`(JSON)承载规则程序(借鉴盯盘 `program_code`)。两阶段 AI(多轮纯文本思考 + 确认时编译规则,均带退避重试绕开讯飞 1105)。新增纯函数解释器 `run_pick_program`(filters 硬筛 + scoring 相对归一化加权)。执行时零 LLM 调用。

**Tech Stack:** Python 3 / FastAPI / SQLAlchemy / pytest / akshare(auto 数据源)/ 讯飞星火 LLM(OpenAI 兼容)。

**Spec:** `docs/superpowers/specs/2026-06-30-ai-pick-strategy-program-design.md`

---

## File Structure

| 文件 | 责任 | 动作 |
|---|---|---|
| `backend/app/services/agent_service.py` | 选股/思考/编译/执行主逻辑 | 改造 |
| `backend/app/api/agent.py` | 选股 REST 端点 | 改造(新增 confirm) |
| `backend/app/schemas/agent.py`(若存在,否则在 agent.py 内) | 请求体 schema | 改造(加 ConfirmRequest) |
| `backend/tests/test_pick_rules.py` | 规则校验 + 解释器单测 | 新建 |
| `backend/test_pick_pipeline.py` | 端到端脚本 | 同步改(造策略时填 rules) |

> 说明:本项目非 git 仓库(`Is a git repository: false`)。计划中「commit」步骤在此环境改为「**保存检查点**」——用 `git` 不可用时,以「跑通测试 + 文件已落盘」作为检查点,跳过 `git add/commit`。若用户后续 `git init`,再补提交。

---

## Task 1: 规则校验函数 `validate_pick_rules`

**Files:**
- Modify: `backend/app/services/agent_service.py`(新增函数 + 异常类,置于 `_json_from_ai` 之后、`optimize_pick_strategy` 之前)

- [ ] **Step 1: 写失败测试**

新建 `backend/tests/test_pick_rules.py`:

```python
"""选股规则程序校验 + 解释器单测。"""
import pytest
from app.services.agent_service import validate_pick_rules, PickRuleError


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
```

- [ ] **Step 2: 跑测试确认失败**

Run: `cd backend && python -m pytest tests/test_pick_rules.py -v`
Expected: FAIL —— `ImportError: cannot import name 'validate_pick_rules'` / `PickRuleError`

- [ ] **Step 3: 写最小实现**

在 `backend/app/services/agent_service.py`,`_json_from_ai` 函数之后(约 `agent_service.py:67`)插入:

```python
# ── 选股规则程序：校验与解释器 ────────────────────────────────────────────────

# 候选股池 → 指数代码（auto 数据源 get_index_constituents 的入参）
POOL_INDEX_MAP: dict[str, str] = {
    "hs300": "000300",   # 沪深300
    "sse50": "000016",   # 上证50
    "star50": "000688",  # 科创50
    # 后续扩展（需先验证 ak.index_stock_cons_csindex 支持）：
    # "csi_a50": ..., "csi_a100": ..., "csi_a500": ..., "csi100": ...
}

# 规则程序可引用的行情字段白名单（对齐 _fetch_pool_quotes 产出字段）
_RULE_FIELDS = {"pe_ttm", "pb", "vol_ratio", "turnover_pct",
                "change_pct", "float_mcap_yi", "amount_wan", "price"}
_RULE_OPS = {">", ">=", "<", "<=", "=="}
_RULE_DIRECTIONS = {"high", "low"}


class PickRuleError(Exception):
    """规则程序非法或不可执行。"""


def validate_pick_rules(rules) -> bool:
    """校验规则程序结构。合法返回 True；非法抛 PickRuleError。"""
    if not isinstance(rules, dict) or not rules:
        raise PickRuleError("规则为空，请先确认策略生成规则")

    pool = rules.get("pool")
    if pool not in POOL_INDEX_MAP:
        raise PickRuleError(
            f"不支持的股池: {pool}（当前支持 {', '.join(POOL_INDEX_MAP)}）"
        )

    filters = rules.get("filters", [])
    if not isinstance(filters, list):
        raise PickRuleError("filters 必须为列表")
    for f in filters:
        if not isinstance(f, dict):
            raise PickRuleError(f"filter 非对象: {f}")
        field = f.get("field")
        op = f.get("op")
        if field not in _RULE_FIELDS:
            raise PickRuleError(f"filter 字段不支持: {field}")
        if op not in _RULE_OPS:
            raise PickRuleError(f"filter op 不支持: {op}")
        try:
            float(f.get("value"))
        except (TypeError, ValueError):
            raise PickRuleError(f"filter value 非数字: {f.get('value')}")

    scoring = rules.get("scoring", [])
    if not isinstance(scoring, list):
        raise PickRuleError("scoring 必须为列表")
    for s in scoring:
        if not isinstance(s, dict):
            raise PickRuleError(f"scoring 项非对象: {s}")
        if s.get("field") not in _RULE_FIELDS:
            raise PickRuleError(f"scoring 字段不支持: {s.get('field')}")
        if s.get("direction") not in _RULE_DIRECTIONS:
            raise PickRuleError(f"scoring direction 不支持: {s.get('direction')}")
        try:
            float(s.get("weight"))
        except (TypeError, ValueError):
            raise PickRuleError(f"scoring weight 非数字: {s.get('weight')}")

    top_n = rules.get("top_n", 6)
    try:
        top_n = int(top_n)
    except (TypeError, ValueError):
        raise PickRuleError(f"top_n 非整数: {top_n}")
    if top_n < 1 or top_n > 20:
        raise PickRuleError(f"top_n 越界(1-20): {top_n}")

    return True
```

- [ ] **Step 4: 跑测试确认通过**

Run: `cd backend && python -m pytest tests/test_pick_rules.py -v`
Expected: 9 passed

- [ ] **Step 5: 检查点**

规则校验函数与异常类已落盘,9 个单测全绿。

---

## Task 2: 规则解释器 `run_pick_program`

**Files:**
- Modify: `backend/app/services/agent_service.py`(在 `validate_pick_rules` 之后插入)
- Test: `backend/tests/test_pick_rules.py`(追加)

- [ ] **Step 1: 写失败测试**

在 `backend/tests/test_pick_rules.py` 顶部 import 改为:

```python
from app.services.agent_service import (
    validate_pick_rules, run_pick_program, PickRuleError,
)
```

文件末尾追加:

```python
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
```

- [ ] **Step 2: 跑测试确认失败**

Run: `cd backend && python -m pytest tests/test_pick_rules.py -v`
Expected: FAIL —— `ImportError: cannot import name 'run_pick_program'`

- [ ] **Step 3: 写最小实现**

在 `backend/app/services/agent_service.py`,`validate_pick_rules` 之后插入:

```python
def _rule_field_value(quote: dict, field: str) -> Optional[float]:
    """从行情取规则字段值，无法取值返回 None。"""
    try:
        v = quote.get(field)
        return float(v) if v is not None else None
    except (TypeError, ValueError):
        return None


def run_pick_program(rules: dict, quotes: list[dict]) -> list[tuple[int, str, dict]]:
    """跑规则程序：filters 硬筛 → scoring 相对归一化加权 → 按 top_n 取。
    返回 [(score, reason, stock), ...] 已按分降序。
    """
    validate_pick_rules(rules)
    top_n = int(rules.get("top_n", 6))
    filters = rules.get("filters", [])
    scoring = rules.get("scoring", [])

    # 1. filters 硬筛
    candidates: list[dict] = []
    for q in quotes:
        keep = True
        for f in filters:
            v = _rule_field_value(q, f["field"])
            if v is None:
                keep = False
                break
            threshold = float(f["value"])
            op = f["op"]
            if op == ">" and not v > threshold: keep = False
            elif op == ">=" and not v >= threshold: keep = False
            elif op == "<" and not v < threshold: keep = False
            elif op == "<=" and not v <= threshold: keep = False
            elif op == "==" and not v == threshold: keep = False
            if not keep:
                break
        if keep:
            candidates.append(q)

    if not candidates:
        return []

    # 2. scoring 相对归一化加权（基准 60）
    scored: list[tuple[int, str, dict]] = []
    for q in candidates:
        score = 60
        reasons = []
        for s in scoring:
            field = s["field"]
            direction = s["direction"]
            weight = float(s["weight"])
            v = _rule_field_value(q, field)
            if v is None:
                continue
            vals = [_rule_field_value(c, field) for c in candidates]
            vals = [x for x in vals if x is not None]
            if not vals:
                continue
            lo, hi = min(vals), max(vals)
            if hi == lo:
                norm = 0.5  # 候选集内无差异
            elif direction == "high":
                norm = (v - lo) / (hi - lo)
            else:  # low
                norm = (hi - v) / (hi - lo)
            score += norm * weight
            reasons.append(f"{field}={v:.2f}")
        score = max(0, min(100, int(round(score))))
        reason = "；".join(reasons) if reasons else "符合策略基本条件"
        scored.append((score, reason, q))

    # 3. 排序 + top_n
    scored.sort(key=lambda x: x[0], reverse=True)
    return scored[:top_n]
```

- [ ] **Step 4: 跑测试确认通过**

Run: `cd backend && python -m pytest tests/test_pick_rules.py -v`
Expected: 15 passed(9 校验 + 6 解释器)

- [ ] **Step 5: 检查点**

解释器落盘,15 个单测全绿。

---

## Task 3: `_fetch_pool_quotes` 支持多指数 pool

**Files:**
- Modify: `backend/app/services/agent_service.py:123-165`(`_fetch_hs300_pool` / `_fetch_pool_quotes`)

- [ ] **Step 1: 写失败测试**

在 `backend/tests/test_pick_rules.py` 追加(用 monkeypatch 绕过真实取数):

```python
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

    monkeypatch.setattr(agent_service, "_get_auto_source",
                        lambda: type("S", (), {"get_index_constituents": fake_constituents,
                                                "get_snapshot": fake_quotes})())
    monkeypatch.setattr(agent_service, "_fetch_quotes", fake_quotes)

    out = agent_service._fetch_pool_quotes("sse50")
    assert called["index_code"] == "000016"
    assert out[0]["code"] == "600000"


def test_fetch_pool_quotes_default_pool(monkeypatch):
    """不传 pool 默认 hs300（向后兼容现有调用）。"""
    from app.services import agent_service
    called = {}
    monkeypatch.setattr(agent_service, "_get_auto_source",
                        lambda: type("S", (), {
                            "get_index_constituents": lambda c: (called.__setitem__("c", c), [{"code": "600000", "name": "X"}])[1],
                            "get_snapshot": lambda codes: {codes[0]: {"code": codes[0], "name": "X", "price": 1, "change_pct": 0, "turnover_pct": 0, "pe_ttm": 0, "pb": 0, "float_mcap_yi": 0, "vol_ratio": 0, "amount_wan": 0}},
                        })())
    out = agent_service._fetch_pool_quotes()
    assert called["c"] == "000300"
    assert len(out) == 1
```

- [ ] **Step 2: 跑测试确认失败**

Run: `cd backend && python -m pytest tests/test_pick_rules.py -v -k fetch_pool`
Expected: FAIL —— `TypeError: _fetch_pool_quotes() got an unexpected keyword argument 'pool'`

- [ ] **Step 3: 改实现**

将 `backend/app/services/agent_service.py:123-165` 的 `_fetch_hs300_pool` 与 `_fetch_pool_quotes` 改为:

```python
def _fetch_index_pool(pool: str) -> list[dict]:
    """从 auto 数据源取指定股池成分股，返回 [{code, name}]，code 为 6 位裸码。
    pool 见 POOL_INDEX_MAP。"""
    index_code = POOL_INDEX_MAP.get(pool)
    if not index_code:
        logger.warning(f"[选股] 未知股池: {pool}")
        return []
    try:
        cons = _get_auto_source().get_index_constituents(index_code)
    except Exception as e:
        logger.warning(f"[选股] 获取 {pool}({index_code}) 成分股失败: {e}")
        return []
    return cons or []


def _fetch_pool_quotes(pool: str = "hs300") -> list[dict]:
    """批量获取指定股池成分股的实时行情快照，返回标准化列表。"""
    pool_data = _fetch_index_pool(pool)
    if not pool_data:
        logger.warning(f"[选股] 股池 {pool} 成分股为空，无法选股")
        return []

    codes = [c["code"] for c in pool_data]
    name_map = {c["code"]: c.get("name", "") for c in pool_data}
    try:
        quotes = _fetch_quotes(codes, name_map)
    except Exception as e:
        logger.warning(f"[选股] 获取股票池行情失败: {e}")
        return []

    out = []
    for code in codes:
        q = quotes.get(code)
        if not q:
            continue
        out.append({
            "code": code,
            "name": q.get("name") or name_map.get(code, code),
            "price": q.get("price", 0),
            "change_pct": q.get("change_pct", 0),
            "turnover_pct": q.get("turnover_pct", 0),
            "pe_ttm": q.get("pe_ttm", 0),
            "pb": q.get("pb", 0),
            "float_mcap_yi": q.get("float_mcap_yi", 0),
            "vol_ratio": q.get("vol_ratio", 0),
            "amount_wan": q.get("amount_wan", 0),
        })
    return out
```

> 注:旧的 `_fetch_hs300_pool` 被 `_fetch_index_pool` 取代。检查文件内是否还有其它处引用 `_fetch_hs300_pool`(grep),若有(如 `execute_pick_tool` 的 `hs300_screen` 调 `_fetch_pool_quotes()`,默认 pool 即 hs300,无需改)同步更新。

- [ ] **Step 4: 跑测试确认通过**

Run: `cd backend && python -m pytest tests/test_pick_rules.py -v`
Expected: 17 passed

- [ ] **Step 5: 检查点**

多指数取数链路通,17 个单测全绿。

---

## Task 4: 改造 `execute_pick_strategy` 跑解释器 + 删 `_match_score`

**Files:**
- Modify: `backend/app/services/agent_service.py:213-264`(`execute_pick_strategy`)
- Modify: `backend/app/services/agent_service.py:168-210`(删 `_match_score`)

- [ ] **Step 1: 写失败测试**

在 `backend/tests/test_pick_rules.py` 追加:

```python
@pytest.mark.asyncio
async def test_execute_rejects_empty_rules():
    """draft（rules 空）执行被拒绝。"""
    from app.services import agent_service
    from app.models import PickStrategy
    strategy = PickStrategy(user_id="t", name="t", description="d",
                            optimized_description="d", rules=[], status="draft")
    with pytest.raises(PickRuleError):
        await agent_service.execute_pick_strategy(None, strategy, "t")
```

> 需 `pytest-asyncio`。若未装:`pip install pytest-asyncio`,并在 `backend/pytest.ini` 或 `conftest.py` 设 `asyncio_mode=auto`(若项目无 pytest.ini,新建 `backend/pytest.ini`:`[pytest]\nasyncio_mode = auto`)。

- [ ] **Step 2: 跑测试确认失败**

Run: `cd backend && python -m pytest tests/test_pick_rules.py::test_execute_rejects_empty_rules -v`
Expected: FAIL —— 当前 `execute_pick_strategy` 空 rules 会走 `_ai_json` 现解析,不抛 `PickRuleError`

- [ ] **Step 3: 改 `execute_pick_strategy`**

将 `backend/app/services/agent_service.py:213-264` 整个函数体改为:

```python
async def execute_pick_strategy(db: Session, strategy: PickStrategy, user_id: str) -> list[PickResult]:
    """执行选股：读已确认的规则程序 → 取股池行情 → 跑解释器 → 持久化 top 结果。
    执行时零 LLM 调用。rules 为空（draft 未确认）抛 PickRuleError。"""
    rules = strategy.rules or []
    validate_pick_rules(rules)  # 空/非法即抛 PickRuleError

    quotes = _fetch_pool_quotes(rules.get("pool", "hs300"))
    if not quotes:
        return []

    scored = run_pick_program(rules, quotes)

    results = []
    for score, reason, s in scored:
        pr = PickResult(
            strategy_id=strategy.id,
            user_id=user_id,
            code=s["code"],
            name=s["name"],
            price=s["price"],
            change_pct=s["change_pct"],
            match_score=score,
            match_reason=reason,
            added_to_watchlist=False,
            picked_at=datetime.utcnow(),
        )
        db.add(pr)
        results.append(pr)
    db.commit()
    return results
```

- [ ] **Step 4: 删 `_match_score`**

删除 `backend/app/services/agent_service.py:168-210` 整个 `_match_score` 函数(被 `run_pick_program` 取代)。删除前先 grep 确认仅 `execute_pick_strategy` 与 `execute_pick_tool` 的 `hs300_screen` 引用它——`hs300_screen` 改用 `run_pick_program`(见 Step 5)。

- [ ] **Step 5: `execute_pick_tool` 的 `hs300_screen` 改用解释器**

`backend/app/services/agent_service.py` 中 `execute_pick_tool` 的 `hs300_screen` 分支(约 `746-774`),把:

```python
            scored = []
            for q in quotes:
                score, reason = _match_score(q, criteria)
                scored.append((score, reason, q))
            scored.sort(key=lambda x: x[0], reverse=True)
```

改为:

```python
            screen_rules = {"pool": "hs300", "filters": [], "scoring": [],
                            "top_n": top_n}
            # 把 criteria 转为 scoring 项（兼容旧对话工具入参）
            for k, v in criteria.items():
                if k in _RULE_FIELDS and v is not None:
                    screen_rules["scoring"].append(
                        {"field": k, "weight": 5, "direction": "high"})
            scored = run_pick_program(screen_rules, quotes)
```

- [ ] **Step 6: 跑测试确认通过**

Run: `cd backend && python -m pytest tests/test_pick_rules.py -v`
Expected: 18 passed

- [ ] **Step 7: 检查点**

执行链路改为跑解释器,`_match_score` 已删,18 个单测全绿。

---

## Task 5: 多轮迭代思考 `think_and_optimize_strategy`

**Files:**
- Modify: `backend/app/services/agent_service.py:71-87`(改造 `optimize_pick_strategy`)

- [ ] **Step 1: 写失败测试**

在 `backend/tests/test_pick_rules.py` 追加:

```python
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
    out = await agent_service.think_and_optimize_strategy("低估值蓝筹")
    assert out == "低估值蓝筹"
```

- [ ] **Step 2: 跑测试确认失败**

Run: `cd backend && python -m pytest tests/test_pick_rules.py -v -k think`
Expected: FAIL —— `AttributeError: module ... has no attribute 'think_and_optimize_strategy'`

- [ ] **Step 3: 写实现**

将 `backend/app/services/agent_service.py:71-87` 的 `optimize_pick_strategy` 替换为:

```python
async def think_and_optimize_strategy(description: str, rounds: int = 3) -> str:
    """多轮迭代深度思考生成优化策略。每轮单轮纯文本 + 退避重试（绕开讯飞1105）。
    LLM 不可用/全失败 → 退化为返回原描述。"""
    if not description:
        return description

    current = description
    for i in range(rounds):
        if i == 0:
            user = f"用户选股想法：{description}\n\n请作为A股量化选股专家，理解意图并给出策略初稿与关键筛选维度。"
        else:
            user = f"上一轮策略稿：{current}\n\n请进一步细化量化阈值（如PE区间、量比、换手、市值），补充风险提示，收敛为更严谨可执行的策略描述。"
        result = await _ai_json_with_retry(
            system="你是A股量化选股专家。把策略想法优化为严谨、可执行的描述。只输出JSON：{\"optimized\": \"...\", \"name\": \"...\"}",
            user=user,
        )
        if result and result.get("optimized"):
            current = result["optimized"]
        # 某轮失败：用 current 继续下一轮（降级）
    return current


async def _ai_json_with_retry(system: str, user: str, temperature: float = 0.3) -> Optional[dict]:
    """_ai_json 套退避重试（4轮 0.8/1.6/3.2s），全失败返回 None。"""
    result = None
    for attempt in range(4):
        result = await _ai_json(system, user, temperature=temperature)
        if result is not None:
            break
        wait = 0.8 * (2 ** attempt)
        logger.warning(f"[AI思考] 调用失败，{wait:.1f}s 后重试({attempt+1}/3)")
        await asyncio.sleep(wait)
    return result


# 旧接口保留（向后兼容其它调用点），内部委托给多轮版
async def optimize_pick_strategy(description: str) -> str:
    """AI 优化选股策略描述（多轮迭代版）。"""
    return await think_and_optimize_strategy(description)
```

- [ ] **Step 4: 跑测试确认通过**

Run: `cd backend && python -m pytest tests/test_pick_rules.py -v -k think`
Expected: 2 passed

- [ ] **Step 5: 检查点**

多轮思考落盘,2 个新单测全绿,旧 `optimize_pick_strategy` 接口保留兼容。

---

## Task 6: 规则编译 `compile_pick_rules`

**Files:**
- Modify: `backend/app/services/agent_service.py`(新增 `compile_pick_rules`,置于 `think_and_optimize_strategy` 之后)

- [ ] **Step 1: 写失败测试**

在 `backend/tests/test_pick_rules.py` 追加:

```python
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
    monkeypatch.setattr(agent_service.asyncio, "sleep", lambda *_: None)  # 跳过退避等待
    rules = await agent_service.compile_pick_rules("某策略")
    assert rules["pool"] == "hs300"


@pytest.mark.asyncio
async def test_compile_all_fail_returns_none(monkeypatch):
    """LLM 全失败 → 返回 None（confirm 端点据此保持 draft）。"""
    from app.services import agent_service

    async def fake_ai_json(system, user, temperature=0.3):
        return None

    monkeypatch.setattr(agent_service, "_ai_json", fake_ai_json)
    rules = await agent_service.compile_pick_rules("某策略")
    assert rules is None
```

- [ ] **Step 2: 跑测试确认失败**

Run: `cd backend && python -m pytest tests/test_pick_rules.py -v -k compile`
Expected: FAIL —— `AttributeError: ... has no attribute 'compile_pick_rules'`

- [ ] **Step 3: 写实现**

在 `backend/app/services/agent_service.py`,`think_and_optimize_strategy` 之后插入:

```python
async def compile_pick_rules(optimized_description: str) -> Optional[dict]:
    """把已确认的优化策略描述编译为结构化规则程序 JSON。
    一次单轮纯文本 + 退避重试 + 严格校验。校验失败重试，全失败返回 None。"""
    catalog_fields = ", ".join(sorted(_RULE_FIELDS))
    pools = ", ".join(POOL_INDEX_MAP)
    system = (
        "你是选股规则编译器。把策略描述编译为结构化筛选规则程序。只输出JSON。"
        f"可用字段：{catalog_fields}。op∈ >,>=,<,<=,==。direction∈ high,low。"
        f"pool∈ {pools}。"
    )
    user = f"""策略描述：{optimized_description}

输出格式：
```json
{{
  "pool": "hs300",
  "filters": [{{"field": "字段", "op": "操作符", "value": 数字}}],
  "scoring": [{{"field": "字段", "weight": 数字, "direction": "high或low"}}],
  "top_n": 6
}}
```
filters 为硬筛条件（不满足淘汰）；scoring 为加权打分项（high=越高越好，low=越低越好）。不确定的字段省略。top_n 限 1-20。"""

    for attempt in range(4):
        result = await _ai_json(system, user, temperature=0.2)
        if result is None:
            wait = 0.8 * (2 ** attempt)
            logger.warning(f"[规则编译] LLM失败，{wait:.1f}s后重试({attempt+1}/3)")
            await asyncio.sleep(wait)
            continue
        try:
            validate_pick_rules(result)
            return result
        except PickRuleError as e:
            logger.warning(f"[规则编译] 校验失败({attempt+1}/4): {e}")
            wait = 0.8 * (2 ** attempt)
            await asyncio.sleep(wait)
    return None
```

- [ ] **Step 4: 跑测试确认通过**

Run: `cd backend && python -m pytest tests/test_pick_rules.py -v -k compile`
Expected: 3 passed

- [ ] **Step 5: 检查点**

规则编译落盘,3 个新单测全绿,非法规则不存(返回 None)。

---

## Task 7: confirm 端点 + execute 拒绝 draft + 编辑清空 rules

**Files:**
- Modify: `backend/app/api/agent.py`(新增 confirm 端点;改 execute、update)
- Modify: `backend/app/schemas/agent.py`(或 agent.py 内联)—— 加 `ConfirmRequest`(若无 body 可不加)

- [ ] **Step 1: 看 update/execute 现状确认改动点**

Run: `cd backend && grep -n "rules\|status\|PickStrategy" app/api/agent.py | head -40`
确认 `update_pick_strategy`(`agent.py:138-162`)、`execute_pick_strategy`(`agent.py:198-223`)、`create_pick_strategy`(`agent.py:114-135`)现状。

- [ ] **Step 2: 改 `create_pick_strategy` 用多轮思考**

`backend/app/api/agent.py:121`:

```python
    optimized = await agent_service.optimize_pick_strategy(req.description)
```

改为:

```python
    optimized = await agent_service.think_and_optimize_strategy(req.description)
```

- [ ] **Step 3: 改 `update_pick_strategy` 编辑即清空 rules**

`backend/app/api/agent.py:154-160` 改为:

```python
    if req.description is not None:
        strategy.description = req.description
        strategy.name = req.description[:8] if req.description else "未命名策略"
        # 编辑描述即清空旧规则、退回 draft（规则须与描述一致）
        strategy.rules = []
        strategy.status = "draft"
    if req.optimized_description is not None:
        strategy.optimized_description = req.optimized_description
        strategy.rules = []
        strategy.status = "draft"
```

- [ ] **Step 4: 新增 confirm 端点**

在 `backend/app/api/agent.py` 的 `update_pick_strategy` 之后、`delete_pick_strategy` 之前插入:

```python
@router.post("/pick/strategy/{strategy_id}/confirm")
async def confirm_pick_strategy(
    strategy_id: str,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """确认策略：AI 把优化描述编译为规则程序，校验通过后存 rules、status→confirmed。"""
    strategy = (
        db.query(PickStrategy)
        .filter(PickStrategy.id == strategy_id, PickStrategy.user_id == current_user.id)
        .first()
    )
    if not strategy:
        raise HTTPException(status_code=404, detail="策略不存在")

    rules = await agent_service.compile_pick_rules(
        strategy.optimized_description or strategy.description
    )
    if rules is None:
        raise HTTPException(status_code=503, detail="规则生成失败，请修改描述后重试")

    strategy.rules = rules
    strategy.status = "confirmed"
    db.commit()
    db.refresh(strategy)
    return {"strategy": strategy_to_dict(strategy)}
```

- [ ] **Step 5: 改 `execute_pick_strategy` 拒绝 draft**

`backend/app/api/agent.py:198-223` 的端点,在「清除旧结果」之前加校验。把 `agent.py:213-220`:

```python
    # 若策略仍为 draft，标记为 confirmed
    if strategy.status == "draft":
        strategy.status = "confirmed"
        db.commit()

    # 清除旧结果
    db.query(PickResult).filter(PickResult.strategy_id == strategy_id).delete()
    db.commit()
```

改为:

```python
    # 未确认（rules 空）拒绝执行，不再 fallback 现解析
    if not strategy.rules:
        raise HTTPException(status_code=422, detail="策略未确认，请先确认生成规则")

    # 清除旧结果
    db.query(PickResult).filter(PickResult.strategy_id == strategy_id).delete()
    db.commit()
```

- [ ] **Step 6: 跑全量单测 + import 校验**

Run: `cd backend && python -m pytest tests/test_pick_rules.py -v`
Expected: 18 passed(规则相关)

Run: `cd backend && python -c "from app.api.agent import confirm_pick_strategy; print('OK')"`
Expected: `OK`(端点可导入)

- [ ] **Step 7: 检查点**

confirm 端点落盘,execute 拒绝 draft,编辑清空 rules,单测全绿,端点可导入。

---

## Task 8: 同步端到端脚本 + 手测

**Files:**
- Modify: `backend/test_pick_pipeline.py:84-94`

- [ ] **Step 1: 改测试脚本造策略时填 rules**

`backend/test_pick_pipeline.py:84-94` 的临时策略,把:

```python
        strategy = PickStrategy(
            user_id="test-pipeline-user",
            name="测试策略",
            description=user_strategy,
            optimized_description=user_strategy,
            rules=[],
            status="confirmed",
        )
```

改为(填合法 rules 程序,符合新 execute 契约):

```python
        strategy = PickStrategy(
            user_id="test-pipeline-user",
            name="测试策略",
            description=user_strategy,
            optimized_description=user_strategy,
            rules={
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
            },
            status="confirmed",
        )
```

- [ ] **Step 2: 跑端到端脚本(需 LLM+MySQL+数据源)**

Run: `cd backend && python test_pick_pipeline.py`
Expected: 阶段4 打印非空选股结果(Top 6),`落库 PickResult 数` ≥1。

> 若 LLM 撞 1105 或数据源不可达,阶段1/2/3 可能失败——阶段4 不依赖 LLM(执行零 LLM),只要行情通就应出结果。若行情不通,跳过本步并在手测报告注明。

- [ ] **Step 3: 手测 confirm 端点(可选,需服务起来)**

启动后端,用真实 token:

Run: `curl -X POST http://localhost:8000/api/agent/pick/strategy -H "Authorization: Bearer <token>" -H "Content-Type: application/json" -d '{"description":"低估值蓝筹，PE低于20，量比大于1.5"}'`
→ 拿到 `strategy_id`。

Run: `curl -X POST http://localhost:8000/api/agent/pick/strategy/<id>/confirm -H "Authorization: Bearer <token>"`
Expected: 返回 `strategy.rules` 非空,`status=confirmed`。若 503,改描述重试。

Run: `curl -X POST http://localhost:8000/api/agent/pick/execute/<id> -H "Authorization: Bearer <token>"`
Expected: 返回 Top 6 结果。

- [ ] **Step 4: 检查点**

端到端脚本与新链路一致,confirm/execute 手测通过(或已记录环境不可用原因)。

---

## Self-Review

**1. Spec 覆盖:**
- §2 目标流程(5步):Task 5(思考)+Task 6(编译)+Task 7(confirm)+Task 4(执行)+ 现有 schedule/results。✅
- §3 数据模型/状态机:复用 rules(Task 1 校验)、pool 多指数(Task 3)、编辑清空/拒绝执行(Task 7)。✅
- §4 AI 两阶段:Task 5(多轮思考)+Task 6(编译+退避+校验),不走 function calling。✅
- §5 解释器:Task 2(run_pick_program)+Task 4(execute 改造、删 _match_score)。✅
- §6 API/错误:Task 7(confirm 503、execute 422、编辑清空)。✅
- §7 测试:Task 1-6 单测 + Task 8 端到端。✅
- §8 影响面:agent_service / agent.py / test_pick_pipeline 全覆盖。✅

**2. Placeholder 扫描:** 无 TBD/TODO 占位;后续指数在 `POOL_INDEX_MAP` 注释明确标为待验证。✅

**3. 类型一致性:** `validate_pick_rules`/`run_pick_program`/`compile_pick_rules`/`think_and_optimize_strategy`/`PickRuleError`/`POOL_INDEX_MAP`/`_RULE_FIELDS` 在各 Task 引用一致;`_fetch_pool_quotes(pool="hs300")` 签名 Task 3 定义、Task 4 调用一致。✅

## Execution Handoff

Plan complete and saved to `docs/superpowers/plans/2026-06-30-ai-pick-strategy-program.md`. Two execution options:

1. **Subagent-Driven (recommended)** - 我每个 Task 派一个全新 subagent 实现,任务间审查,迭代快。
2. **Inline Execution** - 在当前会话用 executing-plans 批量执行,带检查点审查。

你选哪种?

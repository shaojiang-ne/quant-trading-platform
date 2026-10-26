"""AI 智能体模块业务逻辑。

- 选股：AI 将策略描述解析为结构化筛选条件，结合沪深300成分股的实时行情做匹配打分
- 盯盘规则：AI 将自然语言盯盘描述解析为结构化规则（条件→动作）
- 行情：统一走 _fetch_quotes → auto 降级数据源（get_snapshot，腾讯快照优先、akshare 降级）
- 候选股池：沪深300成分股，走 auto 数据源 get_index_constituents("000300")
- 盯盘引擎：交易时段每分钟按规则 trigger 评估实时行情生成信号
"""
import asyncio
import json
import logging
import math
import re
from datetime import datetime
from typing import Optional

from sqlalchemy.orm import Session

from app.config import settings
from app.models import (
    PickStrategy, PickResult, WatchlistStockModel, MonitorRule, AgentSignal,
)
from app.services.ai_service import ai_service, _is_transient_llm_error
from app.ws.manager import ws_manager

logger = logging.getLogger(__name__)

# 代表性股票池已废弃：候选股池改为从 auto 数据源动态获取指数成分股
# （见 _fetch_index_pool → DataSourceProvider.get_index_constituents，pool→index_code 见 POOL_INDEX_MAP）。


def _json_from_ai(content: str) -> Optional[dict]:
    """从 AI 回复中提取 JSON 对象（支持 ```json 代码块或裸 JSON）"""
    if not content:
        return None
    m = re.search(r"```(?:json)?\s*([\s\S]*?)```", content)
    raw = m.group(1).strip() if m else content.strip()
    try:
        return json.loads(raw)
    except Exception:
        # 容错：截取第一个 { 到最后一个 }
        start, end = raw.find("{"), raw.rfind("}")
        if start != -1 and end != -1 and end > start:
            try:
                return json.loads(raw[start : end + 1])
            except Exception:
                return None
        return None


async def _ai_json(system: str, user: str, temperature: float = 0.3) -> Optional[dict]:
    """调用 LLM 并解析为 JSON。AI 未配置时返回 None。"""
    ai_service._ensure_client()
    if not ai_service.client:
        return None
    try:
        resp = await ai_service.client.chat.completions.create(
            model=settings.LLM_MODEL,
            messages=[
                {"role": "system", "content": system},
                {"role": "user", "content": user},
            ],
            temperature=temperature,
        )
        return _json_from_ai(resp.choices[0].message.content or "")
    except Exception as e:
        logger.warning(f"AI 调用失败: {e}")
        return None


# ── 选股规则程序：校验与解释器 ────────────────────────────────────────────────

# 候选股池 → 指数代码（auto 数据源 get_index_constituents 的入参）
POOL_INDEX_MAP: dict[str, str] = {
    "hs300": "000300",   # 沪深300
    "sse50": "000016",   # 上证50
    "star50": "000688",  # 科创50（注意与个股代码 000688 同码，由 akshare 按指数符号区分）
    # 后续扩展（需先验证 ak.index_stock_cons_csindex 支持）：
    # "csi_a50": ..., "csi_a100": ..., "csi_a500": ..., "csi100": ...
}

# 规则程序可引用的行情字段白名单（对齐 _fetch_pool_quotes 产出字段）
_RULE_FIELDS = {"pe_ttm", "pb", "vol_ratio", "turnover_pct",
                "change_pct", "float_mcap_yi", "amount_wan", "price"}
_RULE_OPS = {">", ">=", "<", "<=", "=="}
_RULE_DIRECTIONS = {"high", "low"}

# hs300_screen 工具入参准则名 → (规则字段, op) 显式映射。
# LLM 工具 schema 用简写准则名（pe_max / turnover_min / float_mcap_min_yi 等），
# 这里直接映射到 _RULE_FIELDS 中的真实字段及比较方向，保留「上限/下限」语义不反转。
_CRITERIA_TO_RULE = {
    "pe_max": ("pe_ttm", "<="),
    "vol_ratio_min": ("vol_ratio", ">="),
    "change_pct_min": ("change_pct", ">="),
    "change_pct_max": ("change_pct", "<="),
    "turnover_min": ("turnover_pct", ">="),
    "float_mcap_min_yi": ("float_mcap_yi", ">="),
}


class PickRuleError(Exception):
    """规则程序非法或不可执行。"""


class PickEmptyError(Exception):
    """规则有效但硬筛把全部候选淘汰（非数据源故障）。提示用户放宽条件。"""


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
            v = float(f.get("value"))
            if not math.isfinite(v):
                raise PickRuleError(f"filter value 非有限数: {f.get('value')}")
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
            w = float(s.get("weight"))
            if not math.isfinite(w):
                raise PickRuleError(f"scoring weight 非有限数: {s.get('weight')}")
        except (TypeError, ValueError):
            raise PickRuleError(f"scoring weight 非数字: {s.get('weight')}")

    top_n = rules.get("top_n", 6)
    try:
        tn = float(top_n)
        if not math.isfinite(tn):
            raise PickRuleError(f"top_n 非有限数: {top_n}")
        top_n = int(tn)
    except (TypeError, ValueError):
        raise PickRuleError(f"top_n 非整数: {top_n}")
    if top_n < 1 or top_n > 20:
        raise PickRuleError(f"top_n 越界(1-20): {top_n}")

    return True


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
    #    每个 scoring 项的 (lo, hi) 在候选集内恒定，预算一次（O(n·m) 而非 O(n²·m)）
    item_stats: list[tuple[dict, Optional[float], Optional[float]]] = []
    for s in scoring:
        vals = [x for x in (_rule_field_value(c, s["field"]) for c in candidates) if x is not None]
        if vals:
            item_stats.append((s, min(vals), max(vals)))
        else:
            item_stats.append((s, None, None))

    scored: list[tuple[int, str, dict]] = []
    for q in candidates:
        score = 60
        reasons = []
        for s, lo, hi in item_stats:
            if lo is None:
                continue
            v = _rule_field_value(q, s["field"])
            if v is None:
                continue
            weight = float(s["weight"])
            if hi == lo:
                norm = 0.5  # 候选集内无差异
            elif s["direction"] == "high":
                norm = (v - lo) / (hi - lo)
            else:  # low
                norm = (hi - v) / (hi - lo)
            score += norm * weight
            reasons.append(f"{s['field']}={v:.2f}")
        score = max(0, min(100, int(round(score))))
        reason = "；".join(reasons) if reasons else "符合策略基本条件"
        scored.append((score, reason, q))

    # 3. 排序 + top_n
    scored.sort(key=lambda x: x[0], reverse=True)
    return scored[:top_n]


# ── 选股策略优化 ──────────────────────────────────────────────────────────────

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
        if isinstance(result, dict) and result.get("optimized"):
            current = result["optimized"]
        # 某轮失败：用 current 继续下一轮（降级）
    return current


async def _ai_json_with_retry(system: str, user: str, temperature: float = 0.3) -> Optional[dict]:
    """_ai_json 套退避重试（最多4次尝试，间隔 0.8/1.6/3.2s），全失败返回 None。"""
    max_attempts = 4
    result = None
    for attempt in range(max_attempts):
        result = await _ai_json(system, user, temperature=temperature)
        if result is not None:
            break
        if attempt < max_attempts - 1:  # 最后一次失败后不再 sleep
            wait = 0.8 * (2 ** attempt)
            logger.warning(f"[AI思考] 调用失败，{wait:.1f}s 后重试({attempt+1}/{max_attempts-1})")
            await asyncio.sleep(wait)
    return result


# ── 选股策略优化（流式）──────────────────────────────────────────────────────

PICK_OPTIMIZE_SYSTEM_PROMPT = """你是一位 A 股量化选股专家。用户会描述一个选股想法，你需要把它优化为严谨、可执行的策略描述。

## 你的任务
把用户模糊的选股想法，细化为带明确量化阈值的策略描述，供后续编译为结构化筛选规则。

## 必须覆盖的维度（按用户意图取舍，不确定的不要编造）
- **股池**：沪深300 / 上证50 / 科创50 等主流指数成分股池
- **估值**：PE(TTM) / PB 的上下限区间
- **量能**：量比下限、换手率区间
- **涨跌幅**：当日涨跌幅上下限（如排除大跌股、或筛选强势股）
- **市值**：流通市值下限（亿元）
- **打分权重**：哪些维度作为加权打分项（越高越好 / 越低越好）

## 输出规范
- 用中文，结构化输出（标题 + 列表）
- 给出每个维度的**具体数值阈值**（如 PE≤30、量比≥1.5），不要只给方向
- 最后给出**风险提示**（1-2 句）
- **严禁**编造具体股票代码或名称
- **严禁**输出选股结果、筛选结果、个股名单——你只负责生成策略描述，不负责选股
- **严禁**调用任何工具或取数，纯文本作答

## 继续优化规则（重要）
- 当对话历史中已存在你此前输出的策略描述（assistant 消息）时，用户的新输入是**对该策略的增量优化需求**，而非全新策略。
- 你必须**以上一轮策略为基线**，保留仍适用的维度，合并/调整本次新需求涉及的维度，输出**完整且自洽**的最新策略描述。
- **严禁**丢弃历史中已有的维度而只输出本次新增条件；最终描述应同时覆盖历史维度与新需求。
"""


def _pick_optimize_user_prompt(description: str, has_history: bool) -> str:
    """构造当前轮用户消息。有未确认历史时引导 AI 在上一轮策略基础上继续优化，
    而非当成全新策略从零生成。"""
    if has_history:
        return (
            f"这是用户在上一轮策略基础上的新优化需求：{description}\n\n"
            "注意：上方对话历史中最后一条 assistant 消息就是你上一轮已经给出的策略描述，"
            "它就是本次优化的基线。请务必以它为基础，保留其中仍适用的全部维度"
            "（如股池、估值、市值、分红等），再合并本次新需求涉及的维度，"
            "输出一份完整、自洽、覆盖历史维度与新需求的最新策略描述。"
            "不要只输出本次新增的条件。"
        )
    return f"用户选股想法：{description}\n\n请优化为严谨可执行的策略描述。"


async def stream_pick_optimize(description: str, history: list | None = None):
    """流式输出选股策略优化描述（SSE）。

    单轮流式 + 讯飞 1105 退避重试（仅在本轮尚未向客户端输出任何内容时重试，
    避免半流式输出后重试导致内容重复）。复刻 ai_service.chat_stream_with_tools
    的重试骨架，但无 tools。AI 未配置时输出 error chunk。

    history：自上次确认以来的未确认多轮对话（[{role, content}, ...]），
    拼到 system 与当前用户输入之间，使"继续优化"基于上一轮未确认策略，
    而非把新输入当成全新策略。仅保留 role 为 user/assistant 且有内容的项。
    """
    ai_service._ensure_client()
    if not ai_service.client:
        yield 'data: {"type": "error", "error": "AI服务未配置，请在设置中配置LLM_API_KEY"}\n\n'
        return

    # 清洗历史：仅放行 user/assistant 且非空内容，防注入与脏数据
    history_messages: list[dict] = []
    if history:
        for item in history:
            if not isinstance(item, dict):
                continue
            role = item.get("role")
            content = item.get("content")
            if role in ("user", "assistant") and isinstance(content, str) and content.strip():
                history_messages.append({"role": role, "content": content})

    full_messages = [
        {"role": "system", "content": PICK_OPTIMIZE_SYSTEM_PROMPT},
        *history_messages,
        {"role": "user", "content": _pick_optimize_user_prompt(description, bool(history_messages))},
    ]
    MAX_LLM_RETRIES = 3  # 讯飞偶发 EngineInternalError:1105 过载，重试

    last_err: Exception | None = None
    for attempt in range(MAX_LLM_RETRIES + 1):
        content_buf = ""
        yielded_this_round = False
        try:
            response = await ai_service.client.chat.completions.create(
                model=settings.LLM_MODEL,
                messages=full_messages,
                stream=True,
                temperature=0.3,
            )
            async for chunk in response:
                delta = chunk.choices[0].delta
                if delta.content:
                    content_buf += delta.content
                    yielded_this_round = True
                    yield f'data: {json.dumps({"type": "text", "content": delta.content}, ensure_ascii=False)}\n\n'
            yield 'data: {"type": "done"}\n\n'
            return
        except Exception as e:
            last_err = e
            # 仅在本轮尚未输出任何内容时重试（已流式吐字则不能收回）
            if _is_transient_llm_error(e) and not yielded_this_round and attempt < MAX_LLM_RETRIES:
                wait = 0.8 * (2 ** attempt)  # 0.8s, 1.6s, 3.2s
                logger.warning(f"[选股优化] LLM 偶发错误，{wait:.1f}s 后重试({attempt+1}/{MAX_LLM_RETRIES}): {str(e)[:160]}")
                await asyncio.sleep(wait)
                continue
            # 非偶发错误 / 已输出 / 重试耗尽：若已输出则正常结束，否则报错
            if yielded_this_round:
                yield 'data: {"type": "done"}\n\n'
                return
            logger.error(f"[选股优化] 流式失败: {e}")
            yield f'data: {json.dumps({"type": "error", "error": f"AI服务调用失败: {e}"}, ensure_ascii=False)}\n\n'
            return


# 旧接口保留（向后兼容其它调用点），内部委托给多轮版
async def optimize_pick_strategy(description: str) -> str:
    """AI 优化选股策略描述（多轮迭代版）。"""
    return await think_and_optimize_strategy(description)


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
            if attempt < 3:
                wait = 0.8 * (2 ** attempt)
                logger.warning(f"[规则编译] LLM失败，{wait:.1f}s后重试({attempt+1}/3)")
                await asyncio.sleep(wait)
            continue
        try:
            validate_pick_rules(result)
            return result
        except PickRuleError as e:
            if attempt < 3:
                wait = 0.8 * (2 ** attempt)
                logger.warning(f"[规则编译] 校验失败({attempt+1}/4): {e}，{wait:.1f}s后重试")
                await asyncio.sleep(wait)
            else:
                logger.warning(f"[规则编译] 校验失败({attempt+1}/4): {e}")
    return None


# ── 选股执行 ──────────────────────────────────────────────────────────────────

def _get_auto_source():
    """获取 auto 降级数据源（mootdx→tencent→baostock→sina→akshare）。
    延迟导入避免循环依赖。"""
    from app.core.data_bridge import get_data_source
    return get_data_source("auto")


def _fetch_quotes(codes: list[str], name_map: dict[str, str] | None = None) -> dict[str, dict]:
    """统一行情获取入口：走 auto 降级数据源的实时快照（get_snapshot）。

    返回 dict[code -> quote]，quote 字段：
    name / price / change_pct / turnover_pct / pe_ttm / pb /
    float_mcap_yi / vol_ratio / amount_wan（与 tencent_quote 同构）。
    腾讯快照字段最全；akshare 快照作为降级。name_map 用于在快照无名称时回填。
    """
    name_map = name_map or {}
    if not codes:
        return {}
    try:
        quotes = _get_auto_source().get_snapshot(codes)
    except Exception as e:
        logger.warning(f"[行情] auto 快照取数异常: {e}")
        return {}
    # 快照无 name 时用 name_map 回填（自选股场景保证名称不丢失）
    for code, q in quotes.items():
        if not q.get("name") or q.get("name") == code:
            if name_map.get(code):
                q["name"] = name_map[code]
    return quotes


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


async def execute_pick_strategy(db: Session, strategy: PickStrategy, user_id: str) -> list[PickResult]:
    """执行选股：读已确认的规则程序 → 取股池行情 → 跑解释器 → 持久化 top 结果。
    执行时零 LLM 调用。rules 为空（draft 未确认）抛 PickRuleError。"""
    rules = strategy.rules or []
    validate_pick_rules(rules)  # 空/非法即抛 PickRuleError

    quotes = _fetch_pool_quotes(rules.get("pool", "hs300"))
    if not quotes:
        return []  # 数据源故障：端点报 503

    scored = run_pick_program(rules, quotes)

    if not scored:
        # quotes 非空但硬筛把全部候选淘汰——非数据源问题，提示用户放宽条件
        n_filters = len(rules.get("filters", []))
        raise PickEmptyError(
            f"股池 {len(quotes)} 只候选全部被硬筛条件淘汰（{n_filters} 条 filters）"
            "，请放宽硬筛阈值或将部分硬筛改为打分项后重试"
        )

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


# ── 盯盘规则解析 ──────────────────────────────────────────────────────────────

async def parse_monitor_rules(stock_code: str, description: str) -> tuple[list[dict], str]:
    """AI 将盯盘描述解析为结构化规则列表，返回 (rules, suggestion)。AI 不可用时回退单条规则。"""
    result = await _ai_json(
        system="你是盯盘规则解析器。将用户的盯盘策略描述解析为结构化规则。只输出 JSON。"
              "核心目标:每条规则都必须能被行情引擎自动判定,因此必须给出 trigger 或 target_price 之一(优先 trigger),"
              "不得输出两者皆空的纯语义规则。",
        user=f"""股票代码：{stock_code}
盯盘描述：{description}

按以下 JSON 格式输出：
```json
{{
  "rules": [
    {{
      "condition": "触发条件（如：放量突破20日均线）",
      "action": "buy / sell / alert",
      "target_price": 数字或null,
      "position_pct": 数字或null,
      "quantity": 数字或null,
      "advance_minutes": 数字,
      "trigger": {{
        "metric": "price / change_pct / vol_ratio / turnover_pct 之一（price=现价, change_pct=涨跌幅%, vol_ratio=量比, turnover_pct=换手率%）",
        "op": ">= 或 <= （条件满足方向：buy 用 <= 表示跌到买点、用 >= 表示突破买入；按语义选择）",
        "threshold": 数字
      }}
    }}
  ],
  "suggestion": "优化建议（1句话）"
}}

trigger 必须可由实时行情数值判定：尽可能把「突破/跌破/放量/涨跌到某值」翻译为 (metric, op, threshold)。target_price 是具体目标价（有则填，无则 null）。

【强制】每条规则必须至少有 trigger 或 target_price 之一,严禁两者皆空。引擎只能用实时行情数值判定,无法理解「突破均线/趋势走好/MACD金叉」等纯形态语义。
【trigger 优先】能用行情指标量化的,一律给 trigger(优于 target_price)。trigger 只支持:price(现价)/change_pct(涨跌幅%)/vol_ratio(量比)/turnover_pct(换手率%)。
【常见映射】放量突破→{{vol_ratio,>=,2}};跌破X元→{{price,<=,X}};涨到X元→{{price,>=,X}}并填 target_price=X;涨超X%→{{change_pct,>=,X}};换手超X%→{{turnover_pct,>=,X}}。
【拆分】多条件拆成多条,每条各有 trigger。如「放量且涨超3%」→ {{vol_ratio,>=,2}} 和 {{change_pct,>=,3}} 两条。
【阈值兜底】用户未给数值时用默认:放量=量比2、大涨=涨跌幅5%、活跃=换手率3%。无具体价格时 target_price 留 null,用 change_pct 兜底。
""",
    )

    if result and isinstance(result.get("rules"), list) and result["rules"]:
        rules = []
        for i, r in enumerate(result["rules"]):
            rules.append({
                "condition": r.get("condition", description),
                "action": r.get("action", "alert") if r.get("action") in ("buy", "sell", "alert") else "alert",
                "target_price": r.get("target_price"),
                "position_pct": r.get("position_pct"),
                "quantity": r.get("quantity"),
                "advance_minutes": int(r.get("advance_minutes", 5) or 5),
                "trigger": _normalize_trigger(r.get("trigger")),
            })
        suggestion = result.get("suggestion", "")
        return rules, suggestion

    # 回退：单条规则
    return [{
        "condition": description,
        "action": "alert",
        "target_price": None,
        "position_pct": None,
        "quantity": None,
        "advance_minutes": 5,
        "trigger": None,
    }], "AI 未配置，已按原始描述生成规则。"




# 盯盘引擎可评估的行情指标
_TRIGGER_METRICS = {"price", "change_pct", "vol_ratio", "turnover_pct"}
_TRIGGER_OPS = {">=", "<="}


def _normalize_trigger(trigger) -> Optional[dict]:
    """规整 AI 输出的 trigger 为 {metric, op, threshold}，非法则返回 None。"""
    if not isinstance(trigger, dict):
        return None
    metric = str(trigger.get("metric", "")).strip()
    op = str(trigger.get("op", "")).strip()
    if metric not in _TRIGGER_METRICS or op not in _TRIGGER_OPS:
        return None
    try:
        threshold = float(trigger.get("threshold"))
    except (TypeError, ValueError):
        return None
    return {"metric": metric, "op": op, "threshold": threshold}


def trigger_to_program_code(trigger: Optional[dict]) -> str:
    """把 trigger 规范序列化为 program_code 列存储的 JSON 字符串。"""
    if not trigger:
        return ""
    return json.dumps(trigger, ensure_ascii=False)


def parse_trigger(program_code: str) -> Optional[dict]:
    """从 program_code 列反序列化 trigger 规范。"""
    if not program_code:
        return None
    try:
        t = json.loads(program_code)
    except (ValueError, TypeError):
        return None
    return _normalize_trigger(t)

# ── 自选股行情刷新 ────────────────────────────────────────────────────────────

def refresh_watchlist_quotes(db: Session, user_id: str) -> None:
    """批量刷新用户自选股的实时行情快照"""
    stocks = db.query(WatchlistStockModel).filter(WatchlistStockModel.user_id == user_id).all()
    if not stocks:
        return
    codes = [s.code for s in stocks]
    # 用 DB 中已有的股票名作为 name_map，保证统一数据源路径下名称不丢失
    name_map = {s.code: s.name for s in stocks if s.name}
    try:
        quotes = _fetch_quotes(codes, name_map)
    except Exception as e:
        logger.warning(f"刷新自选股行情失败: {e}")
        return
    for s in stocks:
        q = quotes.get(s.code)
        if not q:
            continue
        s.price = q.get("price", 0) or 0
        s.change_pct = q.get("change_pct", 0) or 0
        # 成交额 amount_wan（万元）；统一数据源由 amount/10000 得到，腾讯为原生字段
        s.volume = q.get("amount_wan", 0) or 0
        s.turnover_rate = q.get("turnover_pct", 0) or 0  # 统一数据源下为 0
        s.float_market_cap = q.get("float_mcap_yi", 0) or 0  # 统一数据源下为 0
        if q.get("name") and q.get("name") != s.code:
            s.name = q["name"]
    db.commit()


# ── 定时选股调度 ──────────────────────────────────────────────────────────────

async def run_scheduled_pick_strategies() -> None:
    """扫描所有 schedule_enabled=true 且到达 schedule_time（HH:MM）的策略并执行选股。

    每个「分钟」至多触发一次：用全局集合记录当日已触发的 strategy_id，避免同一分钟内
    多次循环重复执行。仅在每个交易日的交易时段内触发（非交易日/非交易时段跳过）。
    """
    from app.database import SessionLocal
    from app.services.trading_calendar_service import trading_calendar

    # 仅在交易时段执行（避免非交易日/盘前盘后空跑）
    if not trading_calendar.is_trading_time():
        return

    now = datetime.now()
    hhmm = now.strftime("%H:%M")
    today_key = now.strftime("%Y-%m-%d")

    db = SessionLocal()
    try:
        strategies = (
            db.query(PickStrategy)
            .filter(
                PickStrategy.schedule_enabled.is_(True),
                PickStrategy.schedule_time == hhmm,
            )
            .all()
        )
        for strategy in strategies:
            fired_key = f"{today_key}:{strategy.id}"
            if fired_key in _SCHEDULE_FIRED:
                continue
            _SCHEDULE_FIRED.add(fired_key)
            try:
                await execute_pick_strategy(db, strategy, strategy.user_id)
                logger.info(f"[定时选股] 已执行策略 {strategy.id} ({strategy.name}) @ {hhmm}")
            except Exception as e:
                logger.warning(f"[定时选股] 执行策略 {strategy.id} 失败: {e}")

        # 清理昨日及更早的触发记录，防止集合无限增长
        stale = [k for k in _SCHEDULE_FIRED if not k.startswith(today_key)]
        for k in stale:
            _SCHEDULE_FIRED.discard(k)
    finally:
        db.close()


# 当日已触发的策略记录：{"YYYY-MM-DD:strategy_id"}，防止同一分钟重复执行
_SCHEDULE_FIRED: set[str] = set()


async def scheduled_pick_loop(stop_event: "asyncio.Event") -> None:
    """定时选股后台循环：每分钟检查一次到点的策略。挂在应用 lifespan 中。"""
    while not stop_event.is_set():
        try:
            await run_scheduled_pick_strategies()
        except Exception as e:
            logger.warning(f"[定时选股] 调度循环异常: {e}")
        # 每分钟唤醒一次（对齐到下一分钟边界附近即可，无需精确）
        try:
            await asyncio.wait_for(stop_event.wait(), timeout=60)
        except asyncio.TimeoutError:
            pass


# ── 盯盘引擎 ──────────────────────────────────────────────────────────────────

def evaluate_monitor_rules(db: Session) -> int:
    """周期评估所有 active 盯盘规则，行情触发条件时生成 pending 信号。返回生成信号数。

    触发判定优先级：
    1. trigger 规范（program_code 里的 {metric, op, threshold}）：按 metric 取行情值，
       op(>=/<=) threshold 判定。覆盖「量比≥2」「涨跌幅≥5%」「换手率≥3%」等指标型条件。
    2. target_price：买入规则现价≤目标价 / 卖出规则现价≥目标价（向后兼容无 trigger 的规则）。
    3. 两者皆无：跳过（无法自动判定）。
    每条规则至多保留一条 pending 信号，避免重复堆积。
    """
    rules = db.query(MonitorRule).filter(MonitorRule.active.is_(True)).all()
    if not rules:
        return 0

    # 批量取所有相关股票行情（统一数据源，含腾讯回退）
    codes = list({r.stock_code for r in rules})
    try:
        quotes = _fetch_quotes(codes)
    except Exception as e:
        logger.warning(f"[盯盘引擎] 获取行情失败: {e}")
        return 0

    generated = 0
    generated_signals: list = []
    for rule in rules:
        q = quotes.get(rule.stock_code)
        if not q:
            continue
        current_price = float(q.get("price", 0) or 0)
        if current_price <= 0:
            continue

        trigger = parse_trigger(rule.program_code or "")
        trigger_desc = ""
        if trigger:
            metric_val = _metric_value(q, trigger["metric"])
            if metric_val is None:
                continue
            threshold = trigger["threshold"]
            if trigger["op"] == ">=":
                triggered = metric_val >= threshold
            else:
                triggered = metric_val <= threshold
            trigger_desc = f"{trigger['metric']} {trigger['op']} {threshold}（当前 {metric_val:.2f}）"
            signal_target = rule.target_price if rule.target_price is not None else round(current_price * 1.03, 2)
        elif rule.target_price is not None:
            target = float(rule.target_price)
            triggered = (
                (rule.action == "buy" and current_price <= target)
                or (rule.action == "sell" and current_price >= target)
            )
            trigger_desc = f"现价{current_price} 触及目标{target}"
            signal_target = target
        else:
            continue  # 无明确阈值，无法自动判定

        if not triggered:
            continue

        # 该规则若已有 pending 信号则不重复生成
        existing = (
            db.query(AgentSignal)
            .filter(
                AgentSignal.rule_id == rule.id,
                AgentSignal.status == "pending",
            )
            .first()
        )
        if existing:
            continue

        stock = (
            db.query(WatchlistStockModel)
            .filter(
                WatchlistStockModel.user_id == rule.user_id,
                WatchlistStockModel.code == rule.stock_code,
            )
            .first()
        )
        sig = AgentSignal(
            user_id=rule.user_id,
            stock_code=rule.stock_code,
            stock_name=(stock.name if stock else q.get("name")) or rule.stock_code,
            type=rule.action if rule.action in ("buy", "sell", "alert") else "alert",
            rule_id=rule.id,
            rule_description=rule.condition,
            trigger_time=datetime.utcnow(),
            target_price=signal_target,
            suggested_quantity=rule.quantity or 100,
            suggested_position_pct=rule.position_pct or 0,
            advance_minutes=rule.advance_minutes,
            current_price=current_price,
            status="pending",
        )
        db.add(sig)
        generated_signals.append(sig)
        generated += 1
        logger.info(f"[盯盘引擎] {rule.stock_code} 触发 {rule.action} 信号 ({trigger_desc})")
    if generated:
        db.commit()
        _schedule_signal_push(generated_signals)
    return generated


def _schedule_signal_push(signals: list) -> None:
    """把生成的 AgentSignal 序列化后,经 WS 定向推送给各自的 user_id。

    在事件循环中安排为后台任务;若当前无运行中的循环(如同步单测直接调用),
    则跳过推送——真实运行环境(monitor_engine_loop 是 async)总有循环。
    """
    if not signals:
        return
    try:
        loop = asyncio.get_running_loop()
    except RuntimeError:
        return  # 无事件循环,跳过(单测里由测试自行 mock 验证)

    from app.api.agent import signal_to_dict

    async def _push():
        for sig in signals:
            try:
                await ws_manager.send_to_user(
                    sig.user_id,
                    {"type": "agent_signal", "data": signal_to_dict(sig)},
                )
            except Exception as e:
                logger.warning(f"[盯盘引擎] 推送信号给 {sig.user_id} 失败: {e}")

    loop.create_task(_push())


def _metric_value(quote: dict, metric: str) -> Optional[float]:
    """从行情字典中取指标值，统一映射为 float。无法取值返回 None。"""
    # quote 字段名与 tencent_quote 返回对齐（见 _fetch_pool_quotes）
    mapping = {
        "price": "price",
        "change_pct": "change_pct",
        "vol_ratio": "vol_ratio",
        "turnover_pct": "turnover_pct",
    }
    key = mapping.get(metric)
    if not key:
        return None
    try:
        return float(quote.get(key, 0) or 0)
    except (TypeError, ValueError):
        return None


async def monitor_engine_loop(stop_event: "asyncio.Event") -> None:
    """盯盘引擎后台循环：交易时段每分钟评估一次规则。挂在应用 lifespan 中。"""
    from app.database import SessionLocal
    from app.services.trading_calendar_service import trading_calendar

    while not stop_event.is_set():
        try:
            if trading_calendar.is_trading_time():
                db = SessionLocal()
                try:
                    evaluate_monitor_rules(db)
                finally:
                    db.close()
        except Exception as e:
            logger.warning(f"[盯盘引擎] 循环异常: {e}")
        try:
            await asyncio.wait_for(stop_event.wait(), timeout=60)
        except asyncio.TimeoutError:
            pass


# ── 选股对话工具（function calling）─────────────────────────────────────────────
# 暴露给 LLM 的数据/选股工具。执行器 execute_pick_tool 直接调用 stock_research_service
# 与本模块的无状态筛选函数（_fetch_pool_quotes / run_pick_program），不走 HTTP。
# 工具返回统一为 JSON 字符串，超长结果会被截断到合理长度，避免撑爆上下文。

def _truncate_json(obj, limit: int = 12000) -> str:
    """序列化为 JSON 字符串；超长则截断并附提示。"""
    try:
        text = json.dumps(obj, ensure_ascii=False, default=str)
    except Exception:
        text = str(obj)
    if len(text) > limit:
        text = text[:limit] + f"\n…（已截断，原始长度 {len(text)}）"
    return text


PICK_TOOLS: list[dict] = [
    {
        "type": "function",
        "function": {
            "name": "northbound_flow",
            "description": "获取沪深港通（北向资金）实时分钟级流入流出数据，用于判断北向资金当日净流入趋势。",
            "parameters": {"type": "object", "properties": {}, "required": []},
        },
    },
    {
        "type": "function",
        "function": {
            "name": "stock_quote",
            "description": "批量获取个股实时行情快照（价格、涨跌幅、PE/PB、换手率、量比、流通市值等）。codes 为 6 位裸代码列表。",
            "parameters": {
                "type": "object",
                "properties": {
                    "codes": {
                        "type": "array",
                        "items": {"type": "string"},
                        "description": "股票代码列表，如 [\"600519\", \"000858\"]",
                    }
                },
                "required": ["codes"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "stock_fund_flow",
            "description": "获取个股分钟级资金流向（主力/超大单/大单/中单/小单净流入），用于判断主力资金动向。",
            "parameters": {
                "type": "object",
                "properties": {"code": {"type": "string", "description": "6 位股票代码"}},
                "required": ["code"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "dragon_tiger",
            "description": "获取龙虎榜数据（当日上榜个股、净买入额）。不传参默认取最近交易日。",
            "parameters": {
                "type": "object",
                "properties": {
                    "trade_date": {"type": "string", "description": "交易日 YYYY-MM-DD，不传取当日"},
                    "min_net_buy": {"type": "number", "description": "最小净买入额（万元）过滤，可选"},
                },
                "required": [],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "industry_ranking",
            "description": "获取行业板块涨跌幅排名（按主力净流入/涨幅排序）。",
            "parameters": {
                "type": "object",
                "properties": {"top_n": {"type": "integer", "description": "返回前 N 个行业，默认 20"}},
                "required": [],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "hs300_screen",
            "description": "在沪深300成分股池中按条件筛选并打分，返回匹配度最高的个股。用于选股：传入估值/量能/涨跌幅/换手/市值等条件，得到候选名单。不传任何条件时返回沪深300实时快照概览。",
            "parameters": {
                "type": "object",
                "properties": {
                    "pe_max": {"type": "number", "description": "PE(TTM) 上限"},
                    "vol_ratio_min": {"type": "number", "description": "量比下限"},
                    "change_pct_min": {"type": "number", "description": "涨幅下限（%）"},
                    "change_pct_max": {"type": "number", "description": "涨幅上限（%）"},
                    "turnover_min": {"type": "number", "description": "换手率下限（%）"},
                    "float_mcap_min_yi": {"type": "number", "description": "流通市值下限（亿元）"},
                    "top_n": {"type": "integer", "description": "返回前 N 只，默认 10"},
                },
                "required": [],
            },
        },
    },
]


def execute_pick_tool(name: str, args: dict) -> str:
    """执行选股对话工具，返回 JSON 字符串。异常时返回 {"error": ...} 供模型降级。"""
    from app.services.stock_research_service import stock_research_service

    try:
        if name == "northbound_flow":
            data = stock_research_service.hsgt_realtime()
            return _truncate_json(data[-60:] if isinstance(data, list) else data)

        if name == "stock_quote":
            codes = args.get("codes") or []
            if not isinstance(codes, list) or not codes:
                return json.dumps({"error": "codes 必须为非空列表"}, ensure_ascii=False)
            return _truncate_json(stock_research_service.tencent_quote(codes))

        if name == "stock_fund_flow":
            code = args.get("code")
            if not code:
                return json.dumps({"error": "code 不能为空"}, ensure_ascii=False)
            return _truncate_json(stock_research_service.eastmoney_fund_flow_minute(code))

        if name == "dragon_tiger":
            return _truncate_json(
                stock_research_service.daily_dragon_tiger(
                    trade_date=args.get("trade_date"),
                    min_net_buy=args.get("min_net_buy"),
                )
            )

        if name == "industry_ranking":
            return _truncate_json(
                stock_research_service.industry_comparison(
                    top_n=args.get("top_n") or 20
                )
            )

        if name == "hs300_screen":
            criteria = {k: v for k, v in args.items() if k != "top_n" and v is not None}
            top_n = args.get("top_n") or 10
            quotes = _fetch_pool_quotes()
            if not quotes:
                return json.dumps({"error": "沪深300成分股行情获取失败"}, ensure_ascii=False)
            screen_rules = {"pool": "hs300", "filters": [], "scoring": [],
                            "top_n": top_n}
            # criteria 兼容旧对话工具入参（pe_max / vol_ratio_min / float_mcap_min_yi 等）：
            # _CRITERIA_TO_RULE 显式映射准则名 → (字段, op)，保留「上限/下限」语义不反转。
            # 未在映射表中的裸字段名 → scoring 项(direction=high)。
            for k, v in criteria.items():
                if v is None:
                    continue
                if k in _CRITERIA_TO_RULE:
                    field, op = _CRITERIA_TO_RULE[k]
                    screen_rules["filters"].append(
                        {"field": field, "op": op, "value": v})
                elif k in _RULE_FIELDS:
                    screen_rules["scoring"].append(
                        {"field": k, "weight": 5, "direction": "high"})
            scored = run_pick_program(screen_rules, quotes)
            top = scored[:top_n]
            result = [
                {
                    "code": s[2]["code"],
                    "name": s[2]["name"],
                    "price": s[2]["price"],
                    "change_pct": s[2]["change_pct"],
                    "pe_ttm": s[2]["pe_ttm"],
                    "pb": s[2]["pb"],
                    "turnover_pct": s[2]["turnover_pct"],
                    "vol_ratio": s[2]["vol_ratio"],
                    "float_mcap_yi": s[2]["float_mcap_yi"],
                    "match_score": s[0],
                    "match_reason": s[1],
                }
                for s in top
            ]
            return _truncate_json({"criteria": criteria, "results": result})

        return json.dumps({"error": f"未知工具: {name}"}, ensure_ascii=False)
    except Exception as e:
        logger.warning(f"[选股工具] 执行 {name} 失败: {e}")
        return json.dumps({"error": f"工具执行失败: {e}"}, ensure_ascii=False)


# ── 选股对话：先取数再分析（两步纯文本，绕开讯飞多轮 tool-call 1105）─────────────

def _pick_datasets_catalog() -> str:
    """把 PICK_TOOLS 转成供 LLM 选择的数据集清单文本。"""
    lines = []
    for t in PICK_TOOLS:
        fn = t["function"]
        params = fn.get("parameters", {}).get("properties", {})
        param_desc = ", ".join(f"{k}:{v.get('type','?')}" for k, v in params.items()) or "无"
        lines.append(f"- {fn['name']}：{fn['description']}（参数：{param_desc}）")
    return "\n".join(lines)


async def plan_and_fetch_data(user_question: str) -> list[dict]:
    """第一步：让 LLM 选数据集；第二步：取数。返回 [{name, args, data}]。

    用单轮纯文本请求（无 tools）让 LLM 理解自由表达后决定取哪些数据，
    再调 execute_pick_tool 取数。LLM 不可用或选数据失败时返回 []（降级为不取数直接分析）。
    """
    catalog = _pick_datasets_catalog()
    system = (
        "你是数据需求规划器。根据用户的选股/研究问题，从下列数据集中选择回答所需的数据集。"
        "只输出 JSON，格式 {\"datasets\":[{\"name\":\"工具名\",\"args\":{参数}}]}，"
        "不需要数据则返回 {\"datasets\":[]}。name 必须是下列之一，args 只包含该工具定义的参数。"
    )
    user = f"用户问题：{user_question}\n\n可选数据集：\n{catalog}"

    # 讯飞偶发 EngineInternalError:1105（HTTP 500），_ai_json 失败返回 None。
    # 退避重试若干次提高摇中成功率；仍失败则降级为不取数直接分析。
    result = None
    for attempt in range(4):
        result = await _ai_json(system, user, temperature=0.2)
        if result is not None:
            break
        if attempt < 3:  # 最后一次失败后不再 sleep
            wait = 0.8 * (2 ** attempt)  # 0.8s, 1.6s, 3.2s
            logger.warning(f"[选股取数] 选数据失败，{wait:.1f}s 后重试({attempt+1}/3)")
            await asyncio.sleep(wait)
    if not result:
        return []

    datasets = result.get("datasets") or []
    if not isinstance(datasets, list):
        return []

    blocks: list[dict] = []
    for item in datasets:
        if not isinstance(item, dict):
            continue
        name = item.get("name")
        args = item.get("args") or {}
        if not name or not isinstance(args, dict):
            continue
        if not any(t["function"]["name"] == name for t in PICK_TOOLS):
            logger.warning(f"[选股取数] LLM 选了未知数据集: {name}，跳过")
            continue
        logger.info(f"[选股取数] 取 {name}({args})")
        data = execute_pick_tool(name, args)
        blocks.append({"name": name, "args": args, "data": data})
    return blocks

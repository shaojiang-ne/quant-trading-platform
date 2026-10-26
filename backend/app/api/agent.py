"""AI 智能体模块 API 路由。

对应前端 frontend/src/api/agent.ts 的全部 /agent/* 端点。
响应字段名采用驼峰，与前端 types/agent.ts 对齐。
"""
import logging
from datetime import datetime, timedelta

from fastapi import APIRouter, Depends, HTTPException, Query
from fastapi.responses import StreamingResponse
from pydantic import BaseModel
from sqlalchemy.orm import Session

from app.database import get_db
from app.models import (
    User, PickStrategy, PickResult, WatchlistStockModel, MonitorRule, AgentSignal,
)
from app.schemas.agent import (
    CreatePickStrategyRequest, UpdatePickStrategyRequest, SchedulePickRequest,
    AddWatchlistRequest, ReorderWatchlistRequest,
    CreateMonitorRulesRequest, UpdateMonitorRuleRequest, UpdateSignalStatusRequest,
    BatchDeleteRequest,
)
from app.services import agent_service
from app.services.auth_service import get_current_user

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/agent", tags=["AI智能体"])


# ── ORM → 驼峰 dict 转换 ─────────────────────────────────────────────────────

def strategy_to_dict(s: PickStrategy) -> dict:
    return {
        "id": s.id,
        "name": s.name,
        "description": s.description,
        "optimizedDescription": s.optimized_description,
        "rules": s.rules or [],
        "status": s.status,
        "scheduleTime": s.schedule_time,
        "scheduleEnabled": s.schedule_enabled,
        "createdAt": s.created_at,
        "updatedAt": s.updated_at,
    }


def pick_result_to_dict(r: PickResult) -> dict:
    return {
        "id": r.id,
        "strategyId": r.strategy_id,
        "code": r.code,
        "name": r.name,
        "price": float(r.price or 0),
        "changePct": float(r.change_pct or 0),
        "matchScore": int(r.match_score or 0),
        "matchReason": r.match_reason,
        "addedToWatchlist": bool(r.added_to_watchlist),
        "pickedAt": r.picked_at,
    }


def watchlist_to_dict(w: WatchlistStockModel) -> dict:
    return {
        "id": w.id,
        "code": w.code,
        "name": w.name,
        "price": float(w.price or 0),
        "changePct": float(w.change_pct or 0),
        "volume": float(w.volume or 0),
        "turnoverRate": float(w.turnover_rate or 0),
        "floatMarketCap": float(w.float_market_cap or 0),
        "monitoringStatus": w.monitoring_status,
        "order": w.order,
        "addedAt": w.created_at,
    }


def monitor_rule_to_dict(r: MonitorRule) -> dict:
    return {
        "id": r.id,
        "stockCode": r.stock_code,
        "condition": r.condition,
        "action": r.action,
        "targetPrice": float(r.target_price) if r.target_price is not None else None,
        "quantity": r.quantity,
        "positionPct": float(r.position_pct) if r.position_pct is not None else None,
        "advanceMinutes": int(r.advance_minutes or 0),
        "trigger": agent_service.parse_trigger(r.program_code or ""),
        "active": bool(r.active),
        "createdAt": r.created_at,
    }


def signal_to_dict(s: AgentSignal) -> dict:
    return {
        "id": s.id,
        "stockCode": s.stock_code,
        "stockName": s.stock_name,
        "type": s.type,
        "ruleId": s.rule_id,
        "ruleDescription": s.rule_description,
        "triggerTime": s.trigger_time.isoformat() if s.trigger_time else None,
        "targetPrice": float(s.target_price or 0),
        "suggestedQuantity": int(s.suggested_quantity or 0),
        "suggestedPositionPct": float(s.suggested_position_pct or 0),
        "advanceMinutes": int(s.advance_minutes or 0),
        "currentPrice": float(s.current_price or 0),
        "status": s.status,
        "resolvedAt": s.resolved_at.isoformat() if s.resolved_at else None,
    }


# ── 选股策略 ──────────────────────────────────────────────────────────────────

@router.post("/pick/strategy")
async def create_pick_strategy(
    req: CreatePickStrategyRequest,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """创建/优化选股策略。AI 优化描述后持久化为 draft 策略。"""
    optimized = await agent_service.think_and_optimize_strategy(req.description)

    name = req.description[:8] if req.description else "未命名策略"
    strategy = PickStrategy(
        user_id=current_user.id,
        name=name,
        description=req.description,
        optimized_description=optimized,
        rules=[],
        status="draft",
    )
    db.add(strategy)
    db.commit()
    db.refresh(strategy)
    return {"strategy": strategy_to_dict(strategy), "optimized": optimized}


class OptimizeStreamRequest(BaseModel):
    description: str
    # 本轮之前已存在的未确认对话（自上次确认以来的多轮 user/assistant），
    # 供 AI 在上一轮未确认策略基础上继续优化，而非当成新策略。空则单轮。
    history: list[dict] = []


@router.post("/pick/optimize-stream")
async def optimize_pick_stream(
    req: OptimizeStreamRequest,
    current_user: User = Depends(get_current_user),
):
    """选股策略优化（SSE 流式）。

    流式输出策略优化描述供前端展示，不持久化。用户在前端"采纳"后才会调
    /agent/pick/strategy 创建 draft → /confirm 编译规则 → /execute 选股。
    纯文本 LLM 调用（无 tools），规避讯飞多轮 tool-call 1105。
    history 携带自上次确认以来的未确认多轮对话，使"继续优化"基于上一轮策略而非新建。
    """
    return StreamingResponse(
        agent_service.stream_pick_optimize(req.description, req.history),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",
        },
    )


@router.put("/pick/strategy/{strategy_id}")
def update_pick_strategy(
    strategy_id: str,
    req: UpdatePickStrategyRequest,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """编辑策略描述。清空旧规则、退回 draft 并暂停调度（规则须与描述一致，需重新确认）。"""
    strategy = (
        db.query(PickStrategy)
        .filter(PickStrategy.id == strategy_id, PickStrategy.user_id == current_user.id)
        .first()
    )
    if not strategy:
        raise HTTPException(status_code=404, detail="策略不存在")

    if req.description is not None:
        strategy.description = req.description
        # name 与创建时保持一致（取描述前 8 字）
        strategy.name = req.description[:8] if req.description else "未命名策略"
        # 编辑描述即清空旧规则、退回 draft 并暂停调度（规则须与描述一致，
        # 否则定时循环会反复在空 rules 的 draft 策略上执行失败）
        strategy.rules = []
        strategy.status = "draft"
        strategy.schedule_enabled = False
    if req.optimized_description is not None:
        strategy.optimized_description = req.optimized_description
        strategy.rules = []
        strategy.status = "draft"
        strategy.schedule_enabled = False
    db.commit()
    db.refresh(strategy)
    return strategy_to_dict(strategy)


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


@router.delete("/pick/strategy/{strategy_id}")
def delete_pick_strategy(
    strategy_id: str,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """删除策略。仅删策略行，保留其历史选股结果（PickResult）作为快照。"""
    strategy = (
        db.query(PickStrategy)
        .filter(PickStrategy.id == strategy_id, PickStrategy.user_id == current_user.id)
        .first()
    )
    if not strategy:
        raise HTTPException(status_code=404, detail="策略不存在")
    db.delete(strategy)
    db.commit()
    return None


@router.post("/pick/strategies/batch-delete")
def batch_delete_pick_strategies(
    req: BatchDeleteRequest,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """批量删除选股策略。仅删策略行，保留 PickResult 历史快照（同单删）。"""
    if not req.ids:
        raise HTTPException(status_code=400, detail="ids 不能为空")
    count = (
        db.query(PickStrategy)
        .filter(PickStrategy.id.in_(req.ids), PickStrategy.user_id == current_user.id)
        .delete(synchronize_session=False)
    )
    db.commit()
    return {"deleted": count}


@router.get("/pick/strategies")
def fetch_pick_strategies(
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    strategies = (
        db.query(PickStrategy)
        .filter(PickStrategy.user_id == current_user.id)
        .order_by(PickStrategy.created_at.desc())
        .all()
    )
    return [strategy_to_dict(s) for s in strategies]


@router.post("/pick/execute/{strategy_id}")
async def execute_pick_strategy(
    strategy_id: str,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """执行选股：先清除该策略旧结果，再重新筛选并持久化。"""
    strategy = (
        db.query(PickStrategy)
        .filter(PickStrategy.id == strategy_id, PickStrategy.user_id == current_user.id)
        .first()
    )
    if not strategy:
        raise HTTPException(status_code=404, detail="策略不存在")

    # 未确认（rules 空）拒绝执行，不再 fallback 现解析
    if not strategy.rules:
        raise HTTPException(status_code=422, detail="策略未确认，请先确认生成规则")

    try:
        results = await agent_service.execute_pick_strategy(db, strategy, current_user.id)
    except agent_service.PickRuleError as e:
        # 兜底：rules 非法（理论上 confirm 已校验）
        db.rollback()
        raise HTTPException(status_code=422, detail=f"策略规则不可执行: {e}")
    except agent_service.PickEmptyError as e:
        # 规则有效但硬筛筛光全部候选：提示放宽条件（非数据源故障）
        db.rollback()
        raise HTTPException(status_code=422, detail=f"筛选条件过严: {e}")

    if not results:
        # 取数为空（真数据源故障）：不删旧结果，返回 503 提示
        db.rollback()
        raise HTTPException(status_code=503, detail="行情数据获取失败，未生成选股结果，旧结果已保留")

    # 有新结果：清除旧结果（新结果已在 service 内 commit）
    # service 内 db.commit() 后，真实 Session 会在访问 r.id 时按需 reload 出 INSERT 生成的 id。
    # 若 id 仍为 None（如 mock db 未回填 id），退化为按 code 去重——只删 code 不在新结果里的旧记录。
    new_ids = [r.id for r in results if r.id is not None]
    if len(new_ids) == len(results):
        db.query(PickResult).filter(
            PickResult.strategy_id == strategy_id,
            PickResult.id.notin_(new_ids),
        ).delete(synchronize_session=False)
    else:
        new_codes = [r.code for r in results]
        db.query(PickResult).filter(
            PickResult.strategy_id == strategy_id,
            PickResult.code.notin_(new_codes),
        ).delete(synchronize_session=False)
    db.commit()
    return [pick_result_to_dict(r) for r in results]


@router.post("/pick/schedule")
def schedule_pick_strategy(
    req: SchedulePickRequest,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    strategy = (
        db.query(PickStrategy)
        .filter(PickStrategy.id == req.strategy_id, PickStrategy.user_id == current_user.id)
        .first()
    )
    if not strategy:
        raise HTTPException(status_code=404, detail="策略不存在")
    strategy.schedule_time = req.schedule_time
    strategy.schedule_enabled = req.enabled
    if req.enabled:
        strategy.status = "scheduled"
    elif strategy.status == "scheduled":
        # 关闭定时：回退为已确认策略，仍可手动重新执行
        strategy.status = "confirmed"
    db.commit()
    return None


@router.get("/pick/results/{strategy_id}")
def fetch_pick_results(
    strategy_id: str,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    results = (
        db.query(PickResult)
        .filter(PickResult.strategy_id == strategy_id, PickResult.user_id == current_user.id)
        .order_by(PickResult.match_score.desc())
        .all()
    )
    return [pick_result_to_dict(r) for r in results]


# ── 自选股 ────────────────────────────────────────────────────────────────────

@router.get("/watchlist")
def fetch_watchlist(
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    stocks = (
        db.query(WatchlistStockModel)
        .filter(WatchlistStockModel.user_id == current_user.id)
        .order_by(WatchlistStockModel.order.asc(), WatchlistStockModel.created_at.asc())
        .all()
    )
    # 拉取时顺带刷新行情（best-effort，失败不阻断）
    try:
        agent_service.refresh_watchlist_quotes(db, current_user.id)
        stocks = (
            db.query(WatchlistStockModel)
            .filter(WatchlistStockModel.user_id == current_user.id)
            .order_by(WatchlistStockModel.order.asc(), WatchlistStockModel.created_at.asc())
            .all()
        )
    except Exception as e:
        logger.warning(f"刷新自选股行情失败: {e}")
    return [watchlist_to_dict(w) for w in stocks]


@router.post("/watchlist")
async def add_to_watchlist(
    req: AddWatchlistRequest,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    existing = (
        db.query(WatchlistStockModel)
        .filter(
            WatchlistStockModel.user_id == current_user.id,
            WatchlistStockModel.code == req.code,
        )
        .first()
    )
    if existing:
        return watchlist_to_dict(existing)

    max_order = (
        db.query(WatchlistStockModel)
        .filter(WatchlistStockModel.user_id == current_user.id)
        .count()
    )
    stock = WatchlistStockModel(
        user_id=current_user.id,
        code=req.code,
        name=req.name,
        order=max_order,
        monitoring_status="none",
    )
    db.add(stock)
    db.commit()
    db.refresh(stock)

    # 立即取一次行情填充快照
    try:
        quotes = agent_service.stock_research_service.tencent_quote([req.code])
        q = quotes.get(req.code)
        if q:
            stock.price = q.get("price", 0) or 0
            stock.change_pct = q.get("change_pct", 0) or 0
            stock.volume = q.get("amount_wan", 0) or 0
            stock.turnover_rate = q.get("turnover_pct", 0) or 0
            stock.float_market_cap = q.get("float_mcap_yi", 0) or 0
            if q.get("name"):
                stock.name = q["name"]
            db.commit()
            db.refresh(stock)
    except Exception as e:
        logger.warning(f"获取新增自选股行情失败: {e}")

    return watchlist_to_dict(stock)


@router.delete("/watchlist/{stock_id}")
def remove_from_watchlist(
    stock_id: str,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    stock = (
        db.query(WatchlistStockModel)
        .filter(WatchlistStockModel.id == stock_id, WatchlistStockModel.user_id == current_user.id)
        .first()
    )
    if stock:
        db.delete(stock)
        db.commit()
    return None


@router.post("/watchlist/batch-delete")
def batch_remove_from_watchlist(
    req: BatchDeleteRequest,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """批量移除自选股。"""
    if not req.ids:
        raise HTTPException(status_code=400, detail="ids 不能为空")
    count = (
        db.query(WatchlistStockModel)
        .filter(WatchlistStockModel.id.in_(req.ids), WatchlistStockModel.user_id == current_user.id)
        .delete(synchronize_session=False)
    )
    db.commit()
    return {"deleted": count}
def reorder_watchlist(
    req: ReorderWatchlistRequest,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    for idx, sid in enumerate(req.ids):
        stock = (
            db.query(WatchlistStockModel)
            .filter(WatchlistStockModel.id == sid, WatchlistStockModel.user_id == current_user.id)
            .first()
        )
        if stock:
            stock.order = idx
    db.commit()
    return None


# ── 盯盘规则 ──────────────────────────────────────────────────────────────────

@router.post("/monitor/rules")
async def create_monitor_rules(
    req: CreateMonitorRulesRequest,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """AI 解析盯盘描述为结构化规则并持久化。"""
    rules_data, suggestion = await agent_service.parse_monitor_rules(
        req.stock_code, req.description
    )

    created = []
    for rd in rules_data:
        rule = MonitorRule(
            user_id=current_user.id,
            stock_code=req.stock_code,
            condition=rd["condition"],
            action=rd["action"],
            target_price=rd.get("target_price"),
            quantity=rd.get("quantity"),
            position_pct=rd.get("position_pct"),
            advance_minutes=rd.get("advance_minutes", 5),
            # trigger 规范（{metric,op,threshold}）序列化为 JSON 存入 program_code，
            # 供盯盘引擎周期评估行情时判定是否触发
            program_code=agent_service.trigger_to_program_code(rd.get("trigger")),
            active=True,
        )
        db.add(rule)
        created.append(rule)
    db.commit()
    for r in created:
        db.refresh(r)

    # 规则创建后，将该股自选状态置为 active（前端在「采纳规则」时调用此接口）
    stock = (
        db.query(WatchlistStockModel)
        .filter(
            WatchlistStockModel.user_id == current_user.id,
            WatchlistStockModel.code == req.stock_code,
        )
        .first()
    )
    if stock:
        stock.monitoring_status = "active"
        db.commit()

    # 信号由盯盘引擎在交易时段周期评估行情后真实生成，此处不再即时造演示信号。
    return {"rules": [monitor_rule_to_dict(r) for r in created], "suggestion": suggestion}


@router.get("/monitor/rules/{stock_code}")
def fetch_monitor_rules(
    stock_code: str,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    rules = (
        db.query(MonitorRule)
        .filter(MonitorRule.user_id == current_user.id, MonitorRule.stock_code == stock_code)
        .order_by(MonitorRule.created_at.desc())
        .all()
    )
    return [monitor_rule_to_dict(r) for r in rules]


@router.put("/monitor/rules/{rule_id}")
def update_monitor_rule(
    rule_id: str,
    req: UpdateMonitorRuleRequest,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    rule = (
        db.query(MonitorRule)
        .filter(MonitorRule.id == rule_id, MonitorRule.user_id == current_user.id)
        .first()
    )
    if not rule:
        raise HTTPException(status_code=404, detail="规则不存在")

    data = req.model_dump(exclude_unset=True)
    mapping = {
        "condition": "condition",
        "action": "action",
        "target_price": "target_price",
        "quantity": "quantity",
        "position_pct": "position_pct",
        "advance_minutes": "advance_minutes",
        "program_code": "program_code",
        "active": "active",
    }
    for k, v in data.items():
        if v is not None and k in mapping:
            setattr(rule, mapping[k], v)
    db.commit()
    db.refresh(rule)
    return monitor_rule_to_dict(rule)


@router.delete("/monitor/rules/{rule_id}")
def delete_monitor_rule(
    rule_id: str,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    rule = (
        db.query(MonitorRule)
        .filter(MonitorRule.id == rule_id, MonitorRule.user_id == current_user.id)
        .first()
    )
    if rule:
        db.delete(rule)
        db.commit()
    return None


@router.delete("/monitor/rules")
def cancel_all_monitor_rules(
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """取消全部盯盘：删除当前用户所有盯盘规则，并将所有已盯盘自选股状态重置为 none（股票保留）。"""
    db.query(MonitorRule).filter(MonitorRule.user_id == current_user.id).delete(
        synchronize_session=False
    )
    db.query(WatchlistStockModel).filter(
        WatchlistStockModel.user_id == current_user.id,
        WatchlistStockModel.monitoring_status == "active",
    ).update({WatchlistStockModel.monitoring_status: "none"}, synchronize_session=False)
    db.commit()
    return {"cleared": True}


@router.post("/monitor/rules/batch-delete")
def batch_delete_monitor_rules(
    req: BatchDeleteRequest,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """批量删除盯盘规则（按 id）。区别于 cancel_all：只删指定规则，不重置自选股状态。"""
    if not req.ids:
        raise HTTPException(status_code=400, detail="ids 不能为空")
    count = (
        db.query(MonitorRule)
        .filter(MonitorRule.id.in_(req.ids), MonitorRule.user_id == current_user.id)
        .delete(synchronize_session=False)
    )
    db.commit()
    return {"deleted": count}


# ── 盯盘信号 ──────────────────────────────────────────────────────────────────

@router.get("/monitor/signals")
def fetch_signals(
    date: str = Query(None, description="YYYY-MM-DD"),
    status: str = Query(None, description="按状态过滤(pending/resolved/ignored)"),
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    q = db.query(AgentSignal).filter(AgentSignal.user_id == current_user.id)
    if date:
        try:
            day = datetime.strptime(date, "%Y-%m-%d")
            nxt = day + timedelta(days=1)
            q = q.filter(AgentSignal.trigger_time >= day, AgentSignal.trigger_time < nxt)
        except ValueError:
            pass
    if status:
        q = q.filter(AgentSignal.status == status)
    signals = q.order_by(AgentSignal.trigger_time.desc()).all()
    return [signal_to_dict(s) for s in signals]


@router.put("/monitor/signals/{signal_id}")
def update_signal_status(
    signal_id: str,
    req: UpdateSignalStatusRequest,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    sig = (
        db.query(AgentSignal)
        .filter(AgentSignal.id == signal_id, AgentSignal.user_id == current_user.id)
        .first()
    )
    if not sig:
        raise HTTPException(status_code=404, detail="信号不存在")
    if req.status not in ("pending", "confirmed", "ignored", "expired"):
        raise HTTPException(status_code=400, detail="非法状态")
    sig.status = req.status
    if req.status in ("confirmed", "ignored", "expired"):
        sig.resolved_at = datetime.utcnow()
    db.commit()
    db.refresh(sig)
    return signal_to_dict(sig)


@router.post("/monitor/signals/batch-delete")
def batch_delete_signals(
    req: BatchDeleteRequest,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """批量删除盯盘信号记录。"""
    if not req.ids:
        raise HTTPException(status_code=400, detail="ids 不能为空")
    count = (
        db.query(AgentSignal)
        .filter(AgentSignal.id.in_(req.ids), AgentSignal.user_id == current_user.id)
        .delete(synchronize_session=False)
    )
    db.commit()
    return {"deleted": count}

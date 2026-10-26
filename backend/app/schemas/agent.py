"""AI 智能体模块的 Pydantic 模型。

响应字段名采用驼峰，与前端 types/agent.ts 严格对齐；
请求字段沿用前端发送的 snake_case。
"""
from datetime import datetime
from typing import Any, Optional

from pydantic import BaseModel, ConfigDict


# ── 选股策略 ──────────────────────────────────────────────────────────────────

class StrategyRule(BaseModel):
    id: str
    condition: str
    action: str
    params: dict[str, Any] = {}
    active: bool = True


class StockPickingStrategy(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    name: str = ""
    description: str = ""
    optimizedDescription: str = ""
    rules: list[StrategyRule] = []
    status: str = "draft"
    scheduleTime: Optional[str] = None
    scheduleEnabled: bool = False
    createdAt: datetime
    updatedAt: datetime


# ── 选股结果 ──────────────────────────────────────────────────────────────────

class StockPickResult(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    strategyId: str
    code: str
    name: str = ""
    price: float = 0
    changePct: float = 0
    matchScore: int = 0
    matchReason: str = ""
    addedToWatchlist: bool = False
    pickedAt: datetime


# ── 自选股 ────────────────────────────────────────────────────────────────────

class WatchlistStock(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    code: str
    name: str = ""
    price: float = 0
    changePct: float = 0
    volume: float = 0
    turnoverRate: float = 0
    floatMarketCap: float = 0
    monitoringStatus: str = "none"
    order: int = 0
    addedAt: datetime


# ── 盯盘规则 ──────────────────────────────────────────────────────────────────

class MonitoringRule(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    stockCode: str
    condition: str = ""
    action: str = "alert"
    targetPrice: Optional[float] = None
    quantity: Optional[int] = None
    positionPct: Optional[float] = None
    advanceMinutes: int = 5
    programCode: str = ""
    active: bool = True
    createdAt: datetime


# ── 盯盘信号 ──────────────────────────────────────────────────────────────────

class MonitoringSignal(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    stockCode: str
    stockName: str = ""
    type: str = "alert"
    ruleId: str = ""
    ruleDescription: str = ""
    triggerTime: datetime
    targetPrice: float = 0
    suggestedQuantity: int = 0
    suggestedPositionPct: float = 0
    advanceMinutes: int = 0
    currentPrice: float = 0
    status: str = "pending"
    resolvedAt: Optional[datetime] = None


# ── 请求体 ────────────────────────────────────────────────────────────────────

class CreatePickStrategyRequest(BaseModel):
    description: str


class UpdatePickStrategyRequest(BaseModel):
    description: Optional[str] = None
    optimized_description: Optional[str] = None


class SchedulePickRequest(BaseModel):
    strategy_id: str
    schedule_time: str
    enabled: bool


class AddWatchlistRequest(BaseModel):
    code: str
    name: str = ""


class ReorderWatchlistRequest(BaseModel):
    ids: list[str]


class CreateMonitorRulesRequest(BaseModel):
    stock_code: str
    description: str


class UpdateMonitorRuleRequest(BaseModel):
    condition: Optional[str] = None
    action: Optional[str] = None
    target_price: Optional[float] = None
    quantity: Optional[int] = None
    position_pct: Optional[float] = None
    advance_minutes: Optional[int] = None
    program_code: Optional[str] = None
    active: Optional[bool] = None


class UpdateSignalStatusRequest(BaseModel):
    status: str  # pending / confirmed / ignored / expired


class BatchDeleteRequest(BaseModel):
    """批量删除请求：传 id 列表。用于选股策略/自选股/盯盘规则/信号的批量删除。"""
    ids: list[str]

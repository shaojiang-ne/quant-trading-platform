from pydantic import BaseModel


# ── 自动交易配置 ──────────────────────────────────────────────────────────

class AutoTradeConfigBase(BaseModel):
    auto_trade_enabled: bool = False
    confirm_required: bool = True
    max_order_amount: float = 100000
    max_position_ratio: float = 0.3
    daily_loss_limit: float = 5000


class AutoTradeConfigCreate(AutoTradeConfigBase):
    account_id: str


class AutoTradeConfigResponse(AutoTradeConfigBase):
    id: str
    user_id: str
    account_id: str


# ── 信号 ────────────────────────────────────────────────────────────────

class SignalCreate(BaseModel):
    instance_id: str
    account_id: str
    symbol: str
    name: str = ""
    side: str  # buy / sell
    price: float = 0
    quantity: int = 0
    strategy_id: str = ""


class SignalResponse(BaseModel):
    id: str
    instance_id: str
    account_id: str
    symbol: str
    name: str
    side: str
    price: float
    quantity: int
    status: str
    strategy_id: str
    created_at: str


# ── 下单 ────────────────────────────────────────────────────────────────

class TradeOrderCreate(BaseModel):
    account_id: str
    symbol: str
    name: str = ""
    side: str  # buy / sell
    quantity: int
    price: float = 0
    order_type: str = "limit"  # limit / market


class TradeOrderResponse(BaseModel):
    id: str
    account_id: str
    symbol: str
    name: str
    side: str
    type: str
    quantity: float
    price: float | None
    status: str
    filled_quantity: float
    filled_price: float | None
    source: str = "manual"
    gateway_order_id: str | None = None
    created_at: str
    updated_at: str


# ── 成交 ────────────────────────────────────────────────────────────────

class TradeResponse(BaseModel):
    trade_id: str
    order_id: str
    symbol: str
    side: str
    price: float
    quantity: int
    time: str

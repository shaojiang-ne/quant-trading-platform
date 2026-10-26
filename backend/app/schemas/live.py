from pydantic import BaseModel


class GatewayConnectRequest(BaseModel):
    path: str = "http://localhost:8800"  # stock_trade 服务地址
    session_id: int = 0


class GatewayStatusResponse(BaseModel):
    connected: bool
    xttrader_available: bool
    account_id: str = ""


class RiskConfigBase(BaseModel):
    max_position_value: float = 0
    max_order_value: float = 0
    max_daily_loss: float = 0
    max_daily_orders: int = 0
    max_position_ratio: float = 0
    blocked_symbols: list[str] = []


class RiskConfigResponse(RiskConfigBase):
    account_id: str
    daily_orders: int = 0
    daily_loss: float = 0


class LiveAccountResponse(BaseModel):
    account_id: str
    total_assets: float
    cash: float
    available: float
    market_value: float
    frozen: float


class LivePositionResponse(BaseModel):
    symbol: str
    name: str
    quantity: int
    available: int
    avg_cost: float
    current_price: float
    market_value: float
    profit: float
    profit_rate: float


class LiveOrderResponse(BaseModel):
    order_id: str
    symbol: str
    side: str
    quantity: int
    price: float
    filled_quantity: int
    filled_price: float
    status: str
    order_type: str
    create_time: str = ""
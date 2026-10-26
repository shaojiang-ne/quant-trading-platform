from pydantic import BaseModel


# health
class HealthResponse(BaseModel):
    status: str
    connected: bool
    account_id: str | None = None
    error: str | None = None


# asset
class AssetResponse(BaseModel):
    account_id: str
    total_assets: float
    cash: float
    available: float
    market_value: float
    frozen: float


# positions
class PositionItem(BaseModel):
    symbol: str
    name: str
    quantity: int
    available: int
    avg_cost: float
    current_price: float
    market_value: float
    profit: float
    profit_rate: float


class PositionsResponse(BaseModel):
    account_id: str
    positions: list[PositionItem]


# orders
class OrderItem(BaseModel):
    order_id: str
    symbol: str
    name: str
    side: str
    quantity: int
    price: float
    filled_quantity: int
    filled_price: float
    status: str
    order_type: str
    create_time: str
    update_time: str


class OrdersResponse(BaseModel):
    account_id: str
    orders: list[OrderItem]


# trades
class TradeItem(BaseModel):
    trade_id: str
    order_id: str
    symbol: str
    side: str
    price: float
    quantity: int
    time: str


class TradesResponse(BaseModel):
    account_id: str
    trades: list[TradeItem]


# place order
class OrderResultResponse(BaseModel):
    order_id: str
    symbol: str
    side: str
    quantity: int
    price: float
    status: str
    message: str


# cancel order
class CancelResultResponse(BaseModel):
    order_id: str
    status: str
    message: str

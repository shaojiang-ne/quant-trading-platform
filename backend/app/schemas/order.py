from pydantic import BaseModel


class OrderCreate(BaseModel):
    account_id: str
    symbol: str
    name: str = ""
    side: str  # buy / sell
    type: str = "limit"  # market / limit
    quantity: float
    price: float | None = None


class OrderResponse(BaseModel):
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
    created_at: str
    updated_at: str

    model_config = {"from_attributes": True}


class PositionResponse(BaseModel):
    id: str
    account_id: str
    symbol: str
    name: str
    quantity: float
    avg_cost: float
    current_price: float
    market_value: float
    profit: float
    profit_rate: float
    update_time: str

    model_config = {"from_attributes": True}

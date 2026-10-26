from pydantic import BaseModel


class AccountCreate(BaseModel):
    name: str
    type: str  # real / virtual
    broker: str | None = None
    gateway_name: str = "SIMULATED"
    gateway_config: dict | None = None
    balance: float = 1000000
    commission_rate: float = 0.0003
    stamp_tax_rate: float = 0.001


class AccountUpdate(BaseModel):
    name: str | None = None
    broker: str | None = None
    gateway_config: dict | None = None


class AccountResponse(BaseModel):
    id: str
    name: str
    type: str
    broker: str | None
    gateway_name: str
    balance: float
    available: float
    frozen: float
    market_value: float
    profit: float
    profit_rate: float
    commission_rate: float
    stamp_tax_rate: float
    status: str
    created_at: str

    model_config = {"from_attributes": True}

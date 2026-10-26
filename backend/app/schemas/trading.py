from pydantic import BaseModel


class TradingInstanceCreate(BaseModel):
    name: str
    symbol: str
    strategy_id: str
    account_id: str | None = None  # 实盘模式由后端自动填充
    params: dict = {}
    mode: str = "simulation"  # simulation / live
    initial_equity: float | None = None
    auto_trade_enabled: bool | None = None   # None=按模式默认(simulation→True, live→False)
    confirm_required: bool | None = None     # None=按模式默认(simulation→False, live→True)


class SimOrderRequest(BaseModel):
    side: str  # buy / sell
    quantity: int
    price: float = 0  # 0 表示市价，使用实时价格


class TradingInstanceResponse(BaseModel):
    id: str
    name: str
    symbol: str
    strategy_id: str
    account_id: str
    params: dict
    mode: str
    status: str
    total_trades: int
    win_trades: int
    loss_trades: int
    total_profit: float
    current_equity: float
    max_drawdown: float
    position: dict | list = {}
    trades: list = []
    current_price: float = 0
    change_rate: float = 0
    auto_trade_enabled: bool = True
    confirm_required: bool = False
    created_at: str
    updated_at: str

    model_config = {"from_attributes": True}


class SignalResponse(BaseModel):
    id: str
    user_id: str
    instance_id: str
    account_id: str
    symbol: str
    name: str
    side: str
    price: float
    quantity: int
    status: str
    strategy_id: str
    reason: str | None = None
    created_at: str
    updated_at: str

    model_config = {"from_attributes": True}


class AutoTradeConfigResponse(BaseModel):
    id: str
    user_id: str
    account_id: str
    auto_trade_enabled: bool
    confirm_required: bool
    max_order_amount: float
    max_position_ratio: float
    daily_loss_limit: float
    created_at: str
    updated_at: str

    model_config = {"from_attributes": True}


class AutoTradeConfigUpdate(BaseModel):
    auto_trade_enabled: bool | None = None
    confirm_required: bool | None = None
    max_order_amount: float | None = None
    max_position_ratio: float | None = None
    daily_loss_limit: float | None = None


class TradingInstanceUpdate(BaseModel):
    name: str | None = None
    params: dict | None = None


class StrategyStateResponse(BaseModel):
    """策略实例运行状态"""
    strategy_name: str
    class_name: str
    vt_symbol: str
    grid_states_json: str = "{}"
    signal_state: int = 0
    buy_date: str | None = None
    bar_index: int = 0
    prev_price: float = 0
    updated_at: str = ""

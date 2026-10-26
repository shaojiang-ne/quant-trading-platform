from pydantic import BaseModel


class BatchDeleteRequest(BaseModel):
    ids: list[str]


class BacktestRunRequest(BaseModel):
    strategy_id: str
    symbol: str
    interval: str = "d"
    period: str = "daily"  # tick / 1m / 5m / daily
    start_date: str
    end_date: str
    initial_capital: float = 100000
    initial_position: int = 0  # 初始持仓数量（股），市值已包含在初始资金中
    params: dict = {}
    commission_rate: float = 0.0003
    stamp_tax_rate: float = 0.001
    data_source: str = ""  # 空=使用全局配置，否则覆盖: akshare/baostock/xtquant
    incremental_mode: bool = True  # True=逐条处理K线（不预计算信号），False=全量预计算信号


class BacktestResultResponse(BaseModel):
    id: str
    strategy_id: str
    symbol: str
    interval: str
    period: str = "daily"
    start_date: str
    end_date: str
    initial_capital: float
    initial_position: int = 0
    commission_rate: float = 0.0003
    stamp_tax_rate: float = 0.001
    params: dict
    status: str
    progress: int
    total_return: float
    annualized_return: float
    max_drawdown: float
    sharpe_ratio: float
    sortino_ratio: float
    win_rate: float
    profit_factor: float
    total_trades: int
    avg_trade_return: float
    volatility: float
    beta: float
    alpha: float
    daily_results: list
    intraday_results: list = []
    trades: list
    created_at: str
    updated_at: str = ""
    completed_at: str | None
    initial_cash: float = 0
    initial_position_value: float = 0
    initial_position_quantity: float = 0
    final_cash: float = 0
    final_position_value: float = 0
    final_position_quantity: float = 0
    total_profit: float = 0
    strategy_logs: list[str] = []

    model_config = {"from_attributes": True}


class BacktestResultListResponse(BaseModel):
    """列表视图用的精简响应，不含大JSON列（daily_results/trades/strategy_logs等），
    避免MySQL排序溢出 sort_buffer_size (1038 Out of sort memory)。"""
    id: str
    strategy_id: str
    symbol: str
    interval: str
    period: str = "daily"
    start_date: str
    end_date: str
    initial_capital: float
    initial_position: int = 0
    commission_rate: float = 0.0003
    stamp_tax_rate: float = 0.001
    params: dict
    status: str
    progress: int
    total_return: float
    annualized_return: float
    max_drawdown: float
    sharpe_ratio: float
    sortino_ratio: float
    win_rate: float
    profit_factor: float
    total_trades: int
    avg_trade_return: float
    volatility: float
    beta: float
    alpha: float
    daily_results: list = []       # 列表视图不加载，返回空
    intraday_results: list = []    # 列表视图不加载，返回空
    trades: list = []              # 列表视图不加载，返回空
    created_at: str
    updated_at: str = ""
    completed_at: str | None
    initial_cash: float = 0
    initial_position_value: float = 0
    initial_position_quantity: float = 0
    final_cash: float = 0
    final_position_value: float = 0
    final_position_quantity: float = 0
    total_profit: float = 0
    strategy_logs: list[str] = []  # 列表视图不加载，返回空

    model_config = {"from_attributes": True}

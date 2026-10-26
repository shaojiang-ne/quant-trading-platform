import uuid
from datetime import datetime

from sqlalchemy import String, Boolean, DateTime, ForeignKey, Text, JSON, Enum as SAEnum, Numeric, Integer, func
from sqlalchemy.dialects.sqlite import JSON as SQLiteJSON
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.database import Base


def gen_id():
    return str(uuid.uuid4())


def now():
    return datetime.utcnow()


class User(Base):
    __tablename__ = "users"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=gen_id)
    username: Mapped[str] = mapped_column(String(50), unique=True, index=True)
    email: Mapped[str] = mapped_column(String(100), unique=True, index=True)
    hashed_password: Mapped[str] = mapped_column(String(200))
    avatar: Mapped[str | None] = mapped_column(String(200), nullable=True)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=now)

    accounts: Mapped[list["Account"]] = relationship(back_populates="user", cascade="all, delete-orphan")
    strategies: Mapped[list["Strategy"]] = relationship(back_populates="user", cascade="all, delete-orphan")


class Account(Base):
    __tablename__ = "accounts"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=gen_id)
    user_id: Mapped[str] = mapped_column(String(36), ForeignKey("users.id"), index=True)
    name: Mapped[str] = mapped_column(String(100))
    type: Mapped[str] = mapped_column(String(10))  # real / virtual
    broker: Mapped[str | None] = mapped_column(String(100), nullable=True)
    gateway_name: Mapped[str] = mapped_column(String(50), default="SIMULATED")
    gateway_config: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    balance: Mapped[float] = mapped_column(Numeric(18, 2), default=0)
    available: Mapped[float] = mapped_column(Numeric(18, 2), default=0)
    frozen: Mapped[float] = mapped_column(Numeric(18, 2), default=0)
    market_value: Mapped[float] = mapped_column(Numeric(18, 2), default=0)
    profit: Mapped[float] = mapped_column(Numeric(18, 2), default=0)
    profit_rate: Mapped[float] = mapped_column(Numeric(10, 4), default=0)
    commission_rate: Mapped[float] = mapped_column(Numeric(10, 6), default=0.0003)
    stamp_tax_rate: Mapped[float] = mapped_column(Numeric(10, 6), default=0.001)
    status: Mapped[str] = mapped_column(String(20), default="active")
    created_at: Mapped[datetime] = mapped_column(DateTime, default=now)

    user: Mapped["User"] = relationship(back_populates="accounts")


class Strategy(Base):
    __tablename__ = "strategies"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=gen_id)
    user_id: Mapped[str] = mapped_column(String(36), ForeignKey("users.id"), index=True)
    name: Mapped[str] = mapped_column(String(100))
    description: Mapped[str] = mapped_column(Text, default="")
    category: Mapped[str] = mapped_column(String(50), default="")
    tags: Mapped[list] = mapped_column(JSON, default=list)
    difficulty: Mapped[str] = mapped_column(String(20), default="beginner")
    class_name: Mapped[str] = mapped_column(String(100), default="")
    code: Mapped[str] = mapped_column(Text, default="")
    algorithm: Mapped[str] = mapped_column(Text, default="")
    advantages: Mapped[list] = mapped_column(JSON, default=list)
    disadvantages: Mapped[list] = mapped_column(JSON, default=list)
    parameters: Mapped[dict] = mapped_column(JSON, default=dict)
    is_system: Mapped[bool] = mapped_column(Boolean, default=False)
    backtest_count: Mapped[int] = mapped_column(default=0)
    avg_return: Mapped[float] = mapped_column(Numeric(10, 4), default=0)
    author: Mapped[str] = mapped_column(String(50), default="")
    created_at: Mapped[datetime] = mapped_column(DateTime, default=now)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=now, onupdate=now)

    user: Mapped["User"] = relationship(back_populates="strategies")


class StrategyState(Base):
    """策略实例运行状态持久化（网格层状态等）"""
    __tablename__ = "strategy_states"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=gen_id)
    strategy_name: Mapped[str] = mapped_column(String(100), unique=True, index=True)
    class_name: Mapped[str] = mapped_column(String(50))
    vt_symbol: Mapped[str] = mapped_column(String(20))
    grid_states_json: Mapped[str] = mapped_column(Text, default="{}")
    signal_state: Mapped[int] = mapped_column(Integer, default=0)
    buy_date: Mapped[str | None] = mapped_column(String(20), nullable=True)
    bar_index: Mapped[int] = mapped_column(Integer, default=0)
    prev_price: Mapped[float] = mapped_column(Numeric(18, 4), default=0)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=func.now(), onupdate=func.now())


class BacktestResult(Base):
    __tablename__ = "backtest_results"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=gen_id)
    user_id: Mapped[str] = mapped_column(String(36), index=True)
    strategy_id: Mapped[str] = mapped_column(String(36), index=True)
    account_id: Mapped[str] = mapped_column(String(36), default="")
    symbol: Mapped[str] = mapped_column(String(50))
    interval: Mapped[str] = mapped_column(String(10), default="d")
    period: Mapped[str] = mapped_column(String(10), default="daily")  # daily / 5m / 1m
    start_date: Mapped[str] = mapped_column(String(20))
    end_date: Mapped[str] = mapped_column(String(20))
    initial_capital: Mapped[float] = mapped_column(Numeric(18, 2))
    initial_position: Mapped[int] = mapped_column(default=0)  # 初始持仓数量（股）
    commission_rate: Mapped[float] = mapped_column(Numeric(10, 6), default=0.0003)
    stamp_tax_rate: Mapped[float] = mapped_column(Numeric(10, 6), default=0.001)
    params: Mapped[dict] = mapped_column(JSON, default=dict)
    status: Mapped[str] = mapped_column(String(20), default="pending")  # pending/running/completed/failed
    progress: Mapped[int] = mapped_column(default=0)
    total_return: Mapped[float] = mapped_column(Numeric(10, 4), default=0)
    annualized_return: Mapped[float] = mapped_column(Numeric(10, 4), default=0)
    max_drawdown: Mapped[float] = mapped_column(Numeric(10, 4), default=0)
    sharpe_ratio: Mapped[float] = mapped_column(Numeric(10, 4), default=0)
    sortino_ratio: Mapped[float] = mapped_column(Numeric(10, 4), default=0)
    win_rate: Mapped[float] = mapped_column(Numeric(10, 4), default=0)
    profit_factor: Mapped[float] = mapped_column(Numeric(10, 4), default=0)
    total_trades: Mapped[int] = mapped_column(default=0)
    avg_trade_return: Mapped[float] = mapped_column(Numeric(10, 4), default=0)
    volatility: Mapped[float] = mapped_column(Numeric(10, 4), default=0)
    beta: Mapped[float] = mapped_column(Numeric(10, 4), default=0)
    alpha: Mapped[float] = mapped_column(Numeric(10, 4), default=0)
    daily_results: Mapped[list] = mapped_column(JSON, default=list)
    intraday_results: Mapped[list] = mapped_column(JSON, default=list)
    trades: Mapped[list] = mapped_column(JSON, default=list)
    initial_cash: Mapped[float] = mapped_column(Numeric(18, 2), default=0)
    initial_position_value: Mapped[float] = mapped_column(Numeric(18, 2), default=0)
    initial_position_quantity: Mapped[float] = mapped_column(Numeric(18, 2), default=0)
    final_cash: Mapped[float] = mapped_column(Numeric(18, 2), default=0)
    final_position_value: Mapped[float] = mapped_column(Numeric(18, 2), default=0)
    final_position_quantity: Mapped[float] = mapped_column(Numeric(18, 2), default=0)
    total_profit: Mapped[float] = mapped_column(Numeric(18, 2), default=0)
    strategy_logs: Mapped[list] = mapped_column(JSON, default=list)  # 回测期间策略日志
    created_at: Mapped[datetime] = mapped_column(DateTime, default=now)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=now, onupdate=now)
    completed_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)


class Order(Base):
    __tablename__ = "orders"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=gen_id)
    user_id: Mapped[str] = mapped_column(String(36), index=True)
    account_id: Mapped[str] = mapped_column(String(36), index=True)
    symbol: Mapped[str] = mapped_column(String(50))
    name: Mapped[str] = mapped_column(String(100), default="")
    side: Mapped[str] = mapped_column(String(10))  # buy / sell
    type: Mapped[str] = mapped_column(String(10), default="limit")  # market / limit / stop
    quantity: Mapped[float] = mapped_column(Numeric(18, 2))
    price: Mapped[float | None] = mapped_column(Numeric(18, 4), nullable=True)
    status: Mapped[str] = mapped_column(String(20), default="pending")
    filled_quantity: Mapped[float] = mapped_column(Numeric(18, 2), default=0)
    filled_price: Mapped[float | None] = mapped_column(Numeric(18, 4), nullable=True)
    source: Mapped[str] = mapped_column(String(20), default="manual")  # manual / auto / signal_confirmed
    signal_id: Mapped[str | None] = mapped_column(String(36), nullable=True)
    gateway_order_id: Mapped[str | None] = mapped_column(String(50), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=now)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=now, onupdate=now)


class Position(Base):
    __tablename__ = "positions"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=gen_id)
    account_id: Mapped[str] = mapped_column(String(36), index=True)
    symbol: Mapped[str] = mapped_column(String(50))
    name: Mapped[str] = mapped_column(String(100), default="")
    quantity: Mapped[float] = mapped_column(Numeric(18, 2), default=0)
    avg_cost: Mapped[float] = mapped_column(Numeric(18, 4), default=0)
    current_price: Mapped[float] = mapped_column(Numeric(18, 4), default=0)
    market_value: Mapped[float] = mapped_column(Numeric(18, 2), default=0)
    profit: Mapped[float] = mapped_column(Numeric(18, 2), default=0)
    profit_rate: Mapped[float] = mapped_column(Numeric(10, 4), default=0)
    update_time: Mapped[datetime] = mapped_column(DateTime, default=now)


class TradingInstance(Base):
    __tablename__ = "trading_instances"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=gen_id)
    user_id: Mapped[str] = mapped_column(String(36), index=True)
    name: Mapped[str] = mapped_column(String(100))
    symbol: Mapped[str] = mapped_column(String(50))
    strategy_id: Mapped[str] = mapped_column(String(36))
    account_id: Mapped[str] = mapped_column(String(36))
    params: Mapped[dict] = mapped_column(JSON, default=dict)
    mode: Mapped[str] = mapped_column(String(20), default="simulation")  # simulation / live
    status: Mapped[str] = mapped_column(String(20), default="stopped")  # running / stopped / paused
    total_trades: Mapped[int] = mapped_column(default=0)
    win_trades: Mapped[int] = mapped_column(default=0)
    loss_trades: Mapped[int] = mapped_column(default=0)
    total_profit: Mapped[float] = mapped_column(Numeric(18, 2), default=0)
    current_equity: Mapped[float] = mapped_column(Numeric(18, 2), default=0)
    max_drawdown: Mapped[float] = mapped_column(Numeric(10, 4), default=0)
    position: Mapped[dict] = mapped_column(JSON, default=lambda: {"quantity": 0, "avgCost": 0, "marketValue": 0})
    trades: Mapped[list] = mapped_column(JSON, default=list)
    sim_account_data: Mapped[dict | None] = mapped_column(JSON, nullable=True, default=None)  # 模拟账户快照（余额、持仓等）
    created_at: Mapped[datetime] = mapped_column(DateTime, default=now)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=now, onupdate=now)


class AutoTradeConfig(Base):
    __tablename__ = "auto_trade_configs"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=gen_id)
    user_id: Mapped[str] = mapped_column(String(36), index=True)
    account_id: Mapped[str] = mapped_column(String(36), index=True)
    auto_trade_enabled: Mapped[bool] = mapped_column(Boolean, default=False)
    confirm_required: Mapped[bool] = mapped_column(Boolean, default=True)
    max_order_amount: Mapped[float] = mapped_column(Numeric(18, 2), default=100000)
    max_position_ratio: Mapped[float] = mapped_column(Numeric(10, 4), default=0.3)
    daily_loss_limit: Mapped[float] = mapped_column(Numeric(18, 2), default=5000)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=now)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=now, onupdate=now)


class Signal(Base):
    __tablename__ = "signals"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=gen_id)
    user_id: Mapped[str] = mapped_column(String(36), index=True)
    instance_id: Mapped[str] = mapped_column(String(36), index=True)
    account_id: Mapped[str] = mapped_column(String(36), index=True)
    symbol: Mapped[str] = mapped_column(String(50))
    name: Mapped[str] = mapped_column(String(100), default="")
    side: Mapped[str] = mapped_column(String(10))  # buy / sell
    price: Mapped[float] = mapped_column(Numeric(18, 4), default=0)
    quantity: Mapped[int] = mapped_column(default=0)
    status: Mapped[str] = mapped_column(String(20), default="pending")  # pending / confirmed / rejected / executed / expired
    reason: Mapped[str | None] = mapped_column(Text, nullable=True, default=None)  # 信号产生路径与指标计算过程
    strategy_id: Mapped[str] = mapped_column(String(36), default="")
    created_at: Mapped[datetime] = mapped_column(DateTime, default=now)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=now, onupdate=now)


class StrategyLog(Base):
    __tablename__ = "strategy_logs"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=gen_id)
    instance_id: Mapped[str] = mapped_column(String(36), index=True)
    side: Mapped[str] = mapped_column(String(20))  # signal / buy / sell / risk / error
    message: Mapped[str] = mapped_column(Text)
    price: Mapped[float] = mapped_column(Numeric(18, 4), default=0)
    quantity: Mapped[int] = mapped_column(default=0)
    pnl: Mapped[float] = mapped_column(Numeric(18, 4), default=0)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=now, index=True)


# ── AI 智能体模块 ──────────────────────────────────────────────────────────────

class PickStrategy(Base):
    """AI 选股策略"""
    __tablename__ = "agent_pick_strategies"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=gen_id)
    user_id: Mapped[str] = mapped_column(String(36), ForeignKey("users.id"), index=True)
    name: Mapped[str] = mapped_column(String(100), default="")
    description: Mapped[str] = mapped_column(Text, default="")               # 原始用户描述
    optimized_description: Mapped[str] = mapped_column(Text, default="")     # AI 优化后描述
    rules: Mapped[dict | list] = mapped_column(JSON, default=list)           # 规则程序 JSON（dict）或 draft 时空 []
    status: Mapped[str] = mapped_column(String(20), default="draft")         # draft / confirmed / scheduled
    schedule_time: Mapped[str | None] = mapped_column(String(10), nullable=True)  # "09:15"
    schedule_enabled: Mapped[bool] = mapped_column(Boolean, default=False)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=now)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=now, onupdate=now)


class PickResult(Base):
    """选股结果"""
    __tablename__ = "agent_pick_results"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=gen_id)
    strategy_id: Mapped[str] = mapped_column(String(36), index=True)
    user_id: Mapped[str] = mapped_column(String(36), index=True)
    code: Mapped[str] = mapped_column(String(20))
    name: Mapped[str] = mapped_column(String(100), default="")
    price: Mapped[float] = mapped_column(Numeric(18, 4), default=0)
    change_pct: Mapped[float] = mapped_column(Numeric(10, 4), default=0)
    match_score: Mapped[int] = mapped_column(default=0)
    match_reason: Mapped[str] = mapped_column(Text, default="")
    added_to_watchlist: Mapped[bool] = mapped_column(Boolean, default=False)
    picked_at: Mapped[datetime] = mapped_column(DateTime, default=now)


class WatchlistStockModel(Base):
    """自选股"""
    __tablename__ = "agent_watchlist"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=gen_id)
    user_id: Mapped[str] = mapped_column(String(36), ForeignKey("users.id"), index=True)
    code: Mapped[str] = mapped_column(String(20), index=True)
    name: Mapped[str] = mapped_column(String(100), default="")
    # 行情快照（由 service 定时/按需刷新）
    price: Mapped[float] = mapped_column(Numeric(18, 4), default=0)
    change_pct: Mapped[float] = mapped_column(Numeric(10, 4), default=0)
    volume: Mapped[float] = mapped_column(Numeric(18, 2), default=0)
    turnover_rate: Mapped[float] = mapped_column(Numeric(10, 4), default=0)
    float_market_cap: Mapped[float] = mapped_column(Numeric(18, 2), default=0)
    monitoring_status: Mapped[str] = mapped_column(String(20), default="none")  # active / pending / none
    order: Mapped[int] = mapped_column(default=0)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=now)


class MonitorRule(Base):
    """盯盘规则"""
    __tablename__ = "agent_monitor_rules"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=gen_id)
    user_id: Mapped[str] = mapped_column(String(36), ForeignKey("users.id"), index=True)
    stock_code: Mapped[str] = mapped_column(String(20), index=True)
    condition: Mapped[str] = mapped_column(Text, default="")
    action: Mapped[str] = mapped_column(String(10), default="alert")  # buy / sell / alert
    target_price: Mapped[float | None] = mapped_column(Numeric(18, 4), nullable=True, default=None)
    quantity: Mapped[int | None] = mapped_column(nullable=True, default=None)
    position_pct: Mapped[float | None] = mapped_column(Numeric(10, 4), nullable=True, default=None)
    advance_minutes: Mapped[int] = mapped_column(default=5)
    program_code: Mapped[str] = mapped_column(Text, default="")
    active: Mapped[bool] = mapped_column(Boolean, default=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=now)


class AgentSignal(Base):
    """盯盘信号（智能体模块专用，与策略运行器的 Signal 表区分）"""
    __tablename__ = "agent_signals"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=gen_id)
    user_id: Mapped[str] = mapped_column(String(36), index=True)
    stock_code: Mapped[str] = mapped_column(String(20), index=True)
    stock_name: Mapped[str] = mapped_column(String(100), default="")
    type: Mapped[str] = mapped_column(String(10), default="alert")  # buy / sell / alert
    rule_id: Mapped[str] = mapped_column(String(36), default="")
    rule_description: Mapped[str] = mapped_column(Text, default="")
    trigger_time: Mapped[datetime] = mapped_column(DateTime, default=now, index=True)
    target_price: Mapped[float] = mapped_column(Numeric(18, 4), default=0)
    suggested_quantity: Mapped[int] = mapped_column(default=0)
    suggested_position_pct: Mapped[float] = mapped_column(Numeric(10, 4), default=0)
    advance_minutes: Mapped[int] = mapped_column(default=0)
    current_price: Mapped[float] = mapped_column(Numeric(18, 4), default=0)
    status: Mapped[str] = mapped_column(String(20), default="pending")  # pending / confirmed / ignored / expired
    resolved_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True, default=None)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=now)

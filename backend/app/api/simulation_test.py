from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel

from app.models import User
from app.services.auth_service import get_current_user
try:
    from app.services.simulation_test_service import (
        run_simulation_test,
        run_trade_flow_test,
        get_available_strategies,
    )
except ImportError:
    run_simulation_test = None
    run_trade_flow_test = None
    get_available_strategies = None

router = APIRouter(prefix="/simulation-test", tags=["模拟交易测试"])


class SimulationTestRequest(BaseModel):
    symbol: str
    strategy_name: str
    initial_capital: float = 1000000
    params: dict = {}
    trade_date: str = ""  # 留空则自动使用上一个交易日


class TradeFlowTestRequest(BaseModel):
    symbol: str = "600519"
    initial_capital: float = 1000000
    trade_date: str = ""  # 留空则自动使用上一个交易日


class SimulationTestResponse(BaseModel):
    test_id: str
    test_mode: str
    symbol: str
    strategy_name: str
    initial_capital: float
    start_time: str
    end_time: str
    signal_count: int
    buy_signal_count: int
    sell_signal_count: int
    trade_count: int
    buy_trade_count: int
    sell_trade_count: int
    signals: list
    trades: list
    account_snapshots: list
    errors: list
    final_account: dict
    passed: bool


@router.post("/signal", response_model=SimulationTestResponse)
def run_signal_test(req: SimulationTestRequest, current_user: User = Depends(get_current_user)):
    """
    策略信号测试

    回放上一交易日的1分钟K线数据，驱动策略产生买卖信号，
    通过 SimulatedStockGateway 执行模拟交易。
    """
    result = run_simulation_test(
        symbol=req.symbol,
        strategy_name=req.strategy_name,
        initial_capital=req.initial_capital,
        params=req.params,
        trade_date=req.trade_date or None,
    )
    return result


@router.post("/trade-flow", response_model=SimulationTestResponse)
def run_trade_flow(req: TradeFlowTestRequest, current_user: User = Depends(get_current_user)):
    """
    交易流程测试

    强制注入买入→卖出信号，验证模拟交易全流程：
    下单 → 成交 → 持仓更新 → 资金更新 → T+1 限制
    """
    result = run_trade_flow_test(
        symbol=req.symbol,
        initial_capital=req.initial_capital,
        trade_date=req.trade_date or None,
    )
    return result


@router.get("/strategies")
def list_testable_strategies(current_user: User = Depends(get_current_user)):
    """获取可测试的策略列表"""
    return {"strategies": get_available_strategies()}

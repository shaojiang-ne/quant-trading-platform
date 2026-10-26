"""
实盘交易 API 路由
"""
import json
import logging
from typing import Optional
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session
from pydantic import BaseModel

from app.core.broker_bridge import get_broker, get_available_brokers
from app.core.broker_provider import BrokerProvider
from app.database import get_db
from app.models import User, TradingInstance, Strategy, AutoTradeConfig, Signal, StrategyState, StrategyLog, Order
from app.schemas.trading import (
    TradingInstanceCreate, TradingInstanceResponse, TradingInstanceUpdate,
    SignalResponse, AutoTradeConfigResponse, AutoTradeConfigUpdate,
    StrategyStateResponse,
)
from app.services.auth_service import get_current_user
try:
    from app.services.vnpy_strategy_runner import vnpy_strategy_runner as strategy_runner
except ImportError:
    strategy_runner = None
from app.services.trade_sync_service import trade_sync_service
from app.core.risk_manager import risk_manager, RiskConfig

logger = logging.getLogger(__name__)


class PlaceOrderRequest(BaseModel):
    symbol: str
    side: str
    quantity: int
    price: float = 0
    order_type: str = "limit"


class ConnectRequest(BaseModel):
    broker: str = "qmt"
    # 通用账号密码
    userid: str = ""
    password: str = ""
    # XTP 连接参数（长江/中泰/东方/财通等 XTP 券商）
    td_address: str = ""
    md_address: str = ""
    broker_id: str = ""
    app_id: str = ""
    software_key: str = ""


router = APIRouter(prefix="/trading", tags=["trading"])

# 当前活跃券商
_active_broker: BrokerProvider | None = None


def _get_active_broker() -> BrokerProvider:
    """获取当前活跃券商（未选择时使用默认配置）"""
    global _active_broker
    if _active_broker is None:
        _active_broker = get_broker()
    return _active_broker


# ─── 券商列表 ───

@router.get("/brokers")
async def list_brokers():
    """获取可用券商列表"""
    return get_available_brokers()


# ─── 网关连接 ───

@router.post("/gateway/connect")
async def connect_gateway(req: ConnectRequest | None = None):
    """连接交易网关（支持选择券商）"""
    global _active_broker

    if req is None:
        req = ConnectRequest()

    broker = get_broker(req.broker)

    from app.config import settings

    # 根据券商类型组装连接参数
    kwargs = {}
    broker_name = req.broker.lower()

    if broker_name == "qmt":
        # QMT 通过 stock_trade 微服务，无需额外参数
        pass

    elif broker_name.startswith("xtp_") or broker_name in ("cjzq", "ztzq", "dfzq", "ctzq", "hxzq", "gszq", "ykzq"):
        # XTP 券商: 请求参数 > 配置文件
        kwargs = {
            "td_address": req.td_address or settings.XTP_TD_ADDRESS,
            "md_address": req.md_address or settings.XTP_MD_ADDRESS,
            "broker_id": req.broker_id or settings.XTP_BROKER_ID,
            "app_id": req.app_id or settings.XTP_APP_ID,
            "software_key": req.software_key or settings.XTP_SOFTWARE_KEY,
            "userid": req.userid,
            "password": req.password,
        }

    elif broker_name == "ht":
        kwargs = {
            "userid": req.userid or settings.HT_USERID,
            "password": req.password or settings.HT_PASSWORD,
        }

    elif broker_name == "ths":
        kwargs = {
            "userid": req.userid or settings.THS_USERID,
            "password": req.password or settings.THS_PASSWORD,
        }

    elif broker_name == "gtja":
        kwargs = {
            "userid": req.userid or settings.GTJA_USERID,
            "password": req.password or settings.GTJA_PASSWORD,
            "td_address": req.td_address or settings.GTJA_TD_ADDRESS,
        }

    elif broker_name == "hundsun":
        kwargs = {
            "userid": req.userid or settings.HUNDSUN_USERID,
            "password": req.password or settings.HUNDSUN_PASSWORD,
            "td_address": req.td_address or settings.HUNDSUN_TD_ADDRESS,
        }

    result = await broker.connect(**kwargs)
    if not result.success:
        raise HTTPException(status_code=400, detail=result.message)

    _active_broker = broker
    return {
        "success": result.success,
        "message": result.message,
        "account_id": result.account_id,
        "broker": broker.get_name(),
        "display_name": broker.get_display_name(),
    }


@router.post("/gateway/disconnect")
async def disconnect_gateway():
    """断开交易网关"""
    broker = _get_active_broker()
    await broker.disconnect()
    global _active_broker
    _active_broker = None
    return {"success": True, "message": "已断开连接"}


@router.get("/gateway/status")
async def gateway_status():
    """获取网关连接状态"""
    broker = _get_active_broker()
    return {
        "connected": broker.is_connected(),
        "broker": broker.get_name(),
        "display_name": broker.get_display_name(),
        "account_id": broker.account_id,
    }


# ─── 账户与持仓 ───

@router.get("/account")
async def get_account():
    """获取账户资金"""
    broker = _get_active_broker()
    if not broker.is_connected():
        raise HTTPException(status_code=400, detail="交易网关未连接")
    try:
        account = await broker.get_account()
        return {
            "account_id": account.account_id,
            "total_assets": account.total_assets,
            "cash": account.cash,
            "available": account.available,
            "market_value": account.market_value,
            "frozen": account.frozen_cash,
        }
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"获取账户信息失败: {str(e)}")


@router.get("/positions")
async def get_positions():
    """获取持仓（含今日盈亏）"""
    broker = _get_active_broker()
    if not broker.is_connected():
        raise HTTPException(status_code=400, detail="交易网关未连接")
    try:
        positions = await broker.get_positions()
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"获取持仓失败: {str(e)}")

    # 为每个持仓计算今日盈亏
    from app.services.market_service import market_service
    from app.core.data_bridge import data_bridge

    result = []
    for pos in positions:
        symbol = pos.symbol
        current_price = pos.current_price
        quantity = pos.volume

        pre_close = 0
        if symbol and market_service.is_available():
            xt_symbol = data_bridge.to_xt_symbol(symbol.split(".")[0] if "." in symbol else symbol)
            tick = market_service.get_full_tick(xt_symbol)
            if tick:
                pre_close = float(tick.get("lastClose", 0))

        daily_profit = round((current_price - pre_close) * quantity, 2) if pre_close > 0 and current_price > 0 else 0

        result.append({
            "symbol": pos.symbol,
            "name": pos.name,
            "quantity": pos.volume,
            "available": pos.available,
            "avg_cost": pos.cost_price,
            "current_price": pos.current_price,
            "market_value": pos.market_value,
            "profit": pos.profit_loss,
            "profit_rate": pos.profit_rate,
            "daily_profit": daily_profit,
        })

    return result


@router.get("/orders")
async def get_orders():
    """获取委托"""
    broker = _get_active_broker()
    if not broker.is_connected():
        raise HTTPException(status_code=400, detail="交易网关未连接")
    try:
        orders = await broker.get_orders()
        return [{
            "order_id": o.order_id,
            "symbol": o.symbol,
            "name": o.name,
            "side": o.direction,
            "quantity": o.volume,
            "price": o.price,
            "filled_quantity": o.filled_volume,
            "filled_price": o.filled_price,
            "status": o.status,
            "order_type": o.order_type,
            "create_time": o.order_time,
        } for o in orders]
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"获取委托失败: {str(e)}")


@router.get("/trades")
async def get_trades():
    """获取成交"""
    broker = _get_active_broker()
    if not broker.is_connected():
        raise HTTPException(status_code=400, detail="交易网关未连接")
    try:
        trades = await broker.get_trades()
        return [{
            "trade_id": t.trade_id,
            "order_id": t.order_id,
            "symbol": t.symbol,
            "name": t.name,
            "side": t.direction,
            "price": t.price,
            "quantity": t.volume,
            "time": t.trade_time,
        } for t in trades]
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"获取成交失败: {str(e)}")


# ─── 交易操作 ───

@router.post("/order")
async def place_order(req: PlaceOrderRequest, current_user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    """下单"""
    broker = _get_active_broker()
    if not broker.is_connected():
        raise HTTPException(status_code=400, detail="交易网关未连接")

    # A股整手校验（科创板 688xxx 允许1股，其余必须100股整数倍）
    normalized = _normalize_symbol(req.symbol)
    if not normalized.startswith("688") and req.quantity % 100 != 0:
        raise HTTPException(status_code=400, detail=f"A股下单数量必须为100的整数倍，当前: {req.quantity}")

    # 风控检查
    account_id = broker.account_id
    total_assets = 0
    current_position_value = 0
    try:
        account_data = await broker.get_account()
        total_assets = account_data.total_assets
        current_position_value = account_data.market_value
    except Exception:
        pass

    passed, reason = risk_manager.check_order(
        account_id, normalized, req.side, req.quantity, req.price,
        total_assets=total_assets, current_position_value=current_position_value,
    )
    if not passed:
        raise HTTPException(status_code=400, detail=f"风控拒绝: {reason}")

    try:
        result = await broker.place_order(
            symbol=normalized, direction=req.side,
            price=req.price, volume=req.quantity,
            order_type=req.order_type,
        )
        risk_manager.record_order(account_id)

        # 记录 Order 到 DB
        order_id = result.get("order_id", "")
        db_order = Order(
            user_id=current_user.id,
            account_id=account_id,
            symbol=normalized,
            side=req.side,
            type=req.order_type,
            quantity=req.quantity,
            price=req.price,
            status="submitted",
            source="manual",
            gateway_order_id=str(order_id),
        )
        db.add(db_order)
        db.commit()

        return result
    except Exception as e:
        logger.error(f"手动下单失败: {e}")
        raise HTTPException(status_code=500, detail=f"下单失败: {str(e)}")


@router.delete("/order/{order_id}")
async def cancel_order(order_id: str):
    """撤单"""
    broker = _get_active_broker()
    if not broker.is_connected():
        raise HTTPException(status_code=400, detail="交易网关未连接")
    try:
        return await broker.cancel_order(order_id)
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"撤单失败: {str(e)}")


# ─── 行情 ───

@router.get("/quote")
async def get_quote(symbol: str):
    """获取实时行情"""
    broker = _get_active_broker()
    try:
        return await broker.get_quote(symbol)
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"获取行情失败: {str(e)}")


# ─── 实盘策略实例 ───

def _to_instance_response(inst: TradingInstance) -> TradingInstanceResponse:
    """将 TradingInstance 转为响应（不含实时数据，避免 async）"""
    return TradingInstanceResponse(
        id=inst.id,
        name=inst.name,
        symbol=inst.symbol,
        strategy_id=inst.strategy_id,
        account_id=inst.account_id,
        params=inst.params if isinstance(inst.params, dict) else json.loads(inst.params or "{}"),
        mode=inst.mode,
        status=inst.status,
        total_trades=inst.total_trades,
        win_trades=inst.win_trades,
        loss_trades=inst.loss_trades,
        total_profit=float(inst.total_profit),
        current_equity=float(inst.current_equity),
        max_drawdown=float(inst.max_drawdown),
        position=inst.position if isinstance(inst.position, dict) else json.loads(inst.position or "{}"),
        trades=inst.trades if isinstance(inst.trades, list) else json.loads(inst.trades or "[]"),
        current_price=0,
        change_rate=0,
        created_at=inst.created_at.isoformat() + "Z" if inst.created_at else None,
        updated_at=inst.updated_at.isoformat() + "Z" if inst.updated_at else None,
    )


@router.get("/instances", response_model=list[TradingInstanceResponse])
async def list_instances(current_user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    """列出实盘策略实例"""
    instances = db.query(TradingInstance).filter(
        TradingInstance.user_id == current_user.id,
        TradingInstance.mode == "live",
    ).all()

    # 同步 DB 状态与实际运行状态
    needs_commit = False
    for inst in instances:
        if inst.status == "running" and not strategy_runner.is_running(inst.id):
            # 确保实例已注册到策略运行器
            if inst.id not in strategy_runner._instances:
                strategy = db.query(Strategy).filter(Strategy.id == inst.strategy_id).first()
                class_name = strategy.class_name if strategy else ""
                params = inst.params or (strategy.parameters if strategy else {})
                if isinstance(params, str):
                    params = json.loads(params)
                auto_config = db.query(AutoTradeConfig).filter(
                    AutoTradeConfig.user_id == current_user.id,
                    AutoTradeConfig.account_id == inst.account_id,
                ).first()
                strategy_runner.register(
                    instance_id=inst.id,
                    symbol=inst.symbol,
                    strategy_id=inst.strategy_id,
                    account_id=inst.account_id,
                    mode="live",
                    class_name=class_name,
                    params=params,
                    auto_trade_enabled=auto_config.auto_trade_enabled if auto_config else False,
                    confirm_required=auto_config.confirm_required if auto_config else True,
                )

            # 尝试重新启动（需要网关已连接）
            broker = _get_active_broker()
            if broker.is_connected() and strategy_runner.start(inst.id):
                logger.info(f"已恢复运行实盘实例: {inst.id} ({inst.name})")
            else:
                inst.status = "stopped"
                needs_commit = True
                logger.warning(f"恢复实盘实例失败，标记为 stopped: {inst.id} ({inst.name})")
    if needs_commit:
        db.commit()

    return [_to_instance_response(i) for i in instances]


@router.post("/instances", response_model=TradingInstanceResponse)
async def create_instance(req: TradingInstanceCreate, current_user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    """创建实盘策略实例"""
    broker = _get_active_broker()
    if not broker.is_connected():
        raise HTTPException(status_code=400, detail="交易网关未连接")

    account_id = broker.account_id

    # 获取策略的 class_name 和参数
    strategy = db.query(Strategy).filter(Strategy.id == req.strategy_id).first()
    if not strategy:
        raise HTTPException(status_code=400, detail=f"策略不存在: {req.strategy_id}")
    class_name = strategy.class_name if strategy else ""
    params = req.params or (strategy.parameters if strategy else {})
    if isinstance(params, str):
        params = json.loads(params)

    inst = TradingInstance(
        user_id=current_user.id,
        name=req.name,
        symbol=req.symbol,
        strategy_id=req.strategy_id,
        account_id=account_id,
        params=params,
        mode="live",
        current_equity=0,
    )
    db.add(inst)
    db.commit()
    db.refresh(inst)

    # 获取自动交易配置
    auto_config = db.query(AutoTradeConfig).filter(
        AutoTradeConfig.user_id == current_user.id,
        AutoTradeConfig.account_id == account_id,
    ).first()

    # 获取初始权益
    initial_equity = 0
    if broker.is_connected():
        try:
            account_data = await broker.get_account()
            initial_equity = account_data.total_assets
            if initial_equity <= 0:
                logger.warning(f"实盘账户总资产为0，initial_equity 将无法计算盈亏")
        except Exception as e:
            logger.warning(f"获取实盘账户数据失败: {e}")

    # 注册到策略运行器
    try:
        strategy_runner.register(
            instance_id=inst.id,
            symbol=req.symbol,
            strategy_id=req.strategy_id,
            account_id=account_id,
            mode="live",
            initial_equity=initial_equity,
            class_name=class_name,
            params=params,
            auto_trade_enabled=auto_config.auto_trade_enabled if auto_config else False,
            confirm_required=auto_config.confirm_required if auto_config else True,
        )
    except Exception as e:
        logger.error(f"注册策略运行器失败: {e}")
        # 注册失败时删除已创建的实例
        db.delete(inst)
        db.commit()
        raise HTTPException(status_code=500, detail=f"注册策略运行器失败: {str(e)}")

    return _to_instance_response(inst)


@router.post("/instances/{instance_id}/start", response_model=TradingInstanceResponse)
async def start_instance(instance_id: str, current_user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    """启动实盘策略实例"""
    broker = _get_active_broker()
    if not broker.is_connected():
        raise HTTPException(status_code=400, detail="交易网关未连接")

    inst = db.query(TradingInstance).filter(
        TradingInstance.id == instance_id,
        TradingInstance.user_id == current_user.id,
        TradingInstance.mode == "live",
    ).first()
    if not inst:
        raise HTTPException(status_code=404, detail="实例不存在")
    if inst.status == "running":
        raise HTTPException(status_code=400, detail="实例已在运行")

    # 确保已注册
    strategy = db.query(Strategy).filter(Strategy.id == inst.strategy_id).first()
    class_name = strategy.class_name if strategy else ""
    params = inst.params or (strategy.parameters if strategy else {})
    if isinstance(params, str):
        params = json.loads(params)

    if instance_id not in strategy_runner._instances:
        # 获取自动交易配置
        auto_config = db.query(AutoTradeConfig).filter(
            AutoTradeConfig.user_id == current_user.id,
            AutoTradeConfig.account_id == inst.account_id,
        ).first()

        strategy_runner.register(
            instance_id=inst.id,
            symbol=inst.symbol,
            strategy_id=inst.strategy_id,
            account_id=inst.account_id,
            mode="live",
            class_name=class_name,
            params=params,
            auto_trade_enabled=auto_config.auto_trade_enabled if auto_config else False,
            confirm_required=auto_config.confirm_required if auto_config else True,
        )

    success = strategy_runner.start(inst.id)
    if not success:
        raise HTTPException(status_code=500, detail="启动失败")

    inst.status = "running"
    db.commit()
    db.refresh(inst)
    return _to_instance_response(inst)


@router.post("/instances/{instance_id}/stop", response_model=TradingInstanceResponse)
def stop_instance(instance_id: str, current_user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    """停止实盘策略实例"""
    inst = db.query(TradingInstance).filter(
        TradingInstance.id == instance_id,
        TradingInstance.user_id == current_user.id,
        TradingInstance.mode == "live",
    ).first()
    if not inst:
        raise HTTPException(status_code=404, detail="实例不存在")

    strategy_runner.stop(inst.id)
    inst.status = "stopped"
    db.commit()
    db.refresh(inst)
    return _to_instance_response(inst)


@router.delete("/instances/{instance_id}")
def delete_instance(instance_id: str, current_user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    """删除实盘策略实例（自动停止运行中的实例）"""
    inst = db.query(TradingInstance).filter(
        TradingInstance.id == instance_id,
        TradingInstance.user_id == current_user.id,
        TradingInstance.mode == "live",
    ).first()
    if not inst:
        raise HTTPException(status_code=404, detail="实例不存在")

    # 自动停止运行中的实例
    if inst.status == "running":
        strategy_runner.stop(inst.id)
        inst.status = "stopped"

    strategy_runner.unregister(inst.id)
    db.delete(inst)
    db.commit()
    return {"message": "删除成功"}


@router.put("/instances/{instance_id}", response_model=TradingInstanceResponse)
def update_instance(
    instance_id: str,
    req: TradingInstanceUpdate,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """更新实盘策略实例（名称、参数）"""
    inst = db.query(TradingInstance).filter(
        TradingInstance.id == instance_id,
        TradingInstance.user_id == current_user.id,
        TradingInstance.mode == "live",
    ).first()
    if not inst:
        raise HTTPException(status_code=404, detail="实例不存在")

    if req.name is not None:
        inst.name = req.name
    if req.params is not None:
        inst.params = req.params
        # 同步更新策略运行器中的参数
        config = strategy_runner._instances.get(instance_id)
        if config:
            config["params"] = req.params

    db.commit()
    db.refresh(inst)
    return _to_instance_response(inst)


@router.get("/instances/{instance_id}/logs")
def get_instance_logs(instance_id: str, limit: int = 200, current_user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    """获取实盘策略实例日志（优先内存，回退数据库）"""
    # 优先从内存获取（运行中的实例）
    logs = strategy_runner.get_logs(instance_id)
    if logs:
        return {"instance_id": instance_id, "logs": logs[-limit:]}

    # 实例未运行时从数据库加载
    records = db.query(StrategyLog).filter(
        StrategyLog.instance_id == instance_id,
    ).order_by(StrategyLog.created_at.desc()).limit(limit).all()

    db_logs = []
    for r in reversed(records):
        db_logs.append({
            "time": r.created_at.strftime("%H:%M:%S") if r.created_at else "",
            "side": r.side,
            "message": r.message,
            "price": float(r.price),
            "quantity": r.quantity,
            "pnl": float(r.pnl),
        })

    return {"instance_id": instance_id, "logs": db_logs}


@router.post("/instances/{instance_id}/verify-signals")
def verify_instance_signals(instance_id: str, current_user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    """验算策略信号正确性

    用当前积累的K线数据批量重算信号，与增量信号记录逐条对比。
    返回信号一致性、交易逻辑合理性、指标快照等信息。
    """
    # 验证实例属于当前用户
    inst = db.query(TradingInstance).filter(
        TradingInstance.id == instance_id,
        TradingInstance.user_id == current_user.id,
    ).first()
    if not inst:
        raise HTTPException(status_code=404, detail="实例不存在")

    result = strategy_runner.verify_signals(instance_id)
    return result

@router.get("/signals", response_model=list[SignalResponse])
def list_signals(current_user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    """列出信号（默认返回 pending）"""
    signals = db.query(Signal).filter(
        Signal.user_id == current_user.id,
        Signal.status == "pending",
    ).order_by(Signal.created_at.desc()).all()
    return [_to_signal_response(s) for s in signals]


@router.get("/signals/history", response_model=list[SignalResponse])
def get_signal_history(
    instance_id: Optional[str] = None,
    limit: int = 50,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """信号历史（所有状态）"""
    query = db.query(Signal).filter(Signal.user_id == current_user.id)
    if instance_id:
        query = query.filter(Signal.instance_id == instance_id)
    signals = query.order_by(Signal.created_at.desc()).limit(limit).all()
    return [_to_signal_response(s) for s in signals]


@router.post("/signals/{signal_id}/confirm", response_model=SignalResponse)
async def confirm_signal(signal_id: str, current_user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    """确认信号 → 下单"""
    sig = db.query(Signal).filter(
        Signal.id == signal_id,
        Signal.user_id == current_user.id,
    ).first()
    if not sig:
        raise HTTPException(status_code=404, detail="信号不存在")
    if sig.status != "pending":
        raise HTTPException(status_code=400, detail=f"信号状态为 {sig.status}，无法确认")

    broker = _get_active_broker()
    if not broker.is_connected():
        raise HTTPException(status_code=400, detail="交易网关未连接")

    # 获取账户数据用于风控
    total_assets = 0
    current_position_value = 0
    try:
        account_data = await broker.get_account()
        total_assets = account_data.total_assets
        current_position_value = account_data.market_value
    except Exception:
        pass

    # 风控检查
    passed, reason = risk_manager.check_order(
        sig.account_id, sig.symbol, sig.side, sig.quantity, float(sig.price),
        total_assets=total_assets, current_position_value=current_position_value,
    )
    if not passed:
        sig.status = "rejected"
        db.commit()
        db.refresh(sig)
        raise HTTPException(status_code=400, detail=f"风控拒绝: {reason}")

    try:
        normalized = _normalize_symbol(sig.symbol)
        result = await broker.place_order(
                symbol=normalized,
                direction=sig.side,
                volume=sig.quantity,
                price=float(sig.price),
                order_type="limit",
            )
        sig.status = "executed"
        risk_manager.record_order(sig.account_id)

        # 记录 Order 到 DB
        order_id = result.get("order_id", "")
        db_order = Order(
            user_id=sig.user_id,
            account_id=sig.account_id,
            symbol=normalized,
            side=sig.side,
            type="limit",
            quantity=sig.quantity,
            price=float(sig.price),
            status="submitted",
            source="signal_confirmed",
            signal_id=sig.id,
            gateway_order_id=str(order_id),
        )
        db.add(db_order)
        db.commit()
        db.refresh(sig)
        return _to_signal_response(sig)
    except Exception as e:
        sig.status = "expired"
        db.commit()
        raise HTTPException(status_code=500, detail=f"下单失败: {str(e)}")


@router.post("/signals/{signal_id}/reject", response_model=SignalResponse)
def reject_signal(signal_id: str, current_user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    """拒绝信号"""
    sig = db.query(Signal).filter(
        Signal.id == signal_id,
        Signal.user_id == current_user.id,
    ).first()
    if not sig:
        raise HTTPException(status_code=404, detail="信号不存在")
    if sig.status != "pending":
        raise HTTPException(status_code=400, detail=f"信号状态为 {sig.status}，无法拒绝")

    sig.status = "rejected"
    db.commit()
    db.refresh(sig)
    return _to_signal_response(sig)


def _to_signal_response(sig: Signal) -> SignalResponse:
    return SignalResponse(
        id=sig.id,
        user_id=sig.user_id,
        instance_id=sig.instance_id,
        account_id=sig.account_id,
        symbol=sig.symbol,
        name=sig.name,
        side=sig.side,
        price=float(sig.price),
        quantity=sig.quantity,
        status=sig.status,
        strategy_id=sig.strategy_id,
        reason=sig.reason,
        created_at=sig.created_at.isoformat() + "Z" if sig.created_at else None,
        updated_at=sig.updated_at.isoformat() + "Z" if sig.updated_at else None,
    )


# ─── 自动交易配置 ───

@router.get("/auto-trade/config", response_model=AutoTradeConfigResponse)
def get_auto_trade_config(current_user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    """获取自动交易配置（从数据库）"""
    broker = _get_active_broker()
    account_id = broker.account_id
    config = db.query(AutoTradeConfig).filter(
        AutoTradeConfig.user_id == current_user.id,
        AutoTradeConfig.account_id == account_id,
    ).first()

    if not config:
        # 创建默认配置
        config = AutoTradeConfig(
            user_id=current_user.id,
            account_id=account_id,
            auto_trade_enabled=False,
            confirm_required=True,
            max_order_amount=100000,
            max_position_ratio=0.3,
            daily_loss_limit=5000,
        )
        db.add(config)
        db.commit()
        db.refresh(config)

    _sync_risk_config(config)
    return _to_auto_config_response(config)


@router.post("/auto-trade/config", response_model=AutoTradeConfigResponse)
def update_auto_trade_config(
    update: AutoTradeConfigUpdate,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """更新自动交易配置"""
    broker = _get_active_broker()
    account_id = broker.account_id
    config = db.query(AutoTradeConfig).filter(
        AutoTradeConfig.user_id == current_user.id,
        AutoTradeConfig.account_id == account_id,
    ).first()

    if not config:
        config = AutoTradeConfig(
            user_id=current_user.id,
            account_id=account_id,
        )
        db.add(config)
        db.commit()
        db.refresh(config)

    for field, value in update.model_dump(exclude_unset=True).items():
        setattr(config, field, value)

    db.commit()
    db.refresh(config)

    _sync_risk_config(config)
    return _to_auto_config_response(config)


def _to_auto_config_response(cfg: AutoTradeConfig) -> AutoTradeConfigResponse:
    return AutoTradeConfigResponse(
        id=cfg.id,
        user_id=cfg.user_id,
        account_id=cfg.account_id,
        auto_trade_enabled=cfg.auto_trade_enabled,
        confirm_required=cfg.confirm_required,
        max_order_amount=float(cfg.max_order_amount),
        max_position_ratio=float(cfg.max_position_ratio),
        daily_loss_limit=float(cfg.daily_loss_limit),
        created_at=cfg.created_at.isoformat() + "Z" if cfg.created_at else None,
        updated_at=cfg.updated_at.isoformat() + "Z" if cfg.updated_at else None,
    )


def _sync_risk_config(cfg: AutoTradeConfig) -> None:
    """将 AutoTradeConfig 同步到 risk_manager"""
    account_id = cfg.account_id
    risk_config = RiskConfig(
        max_order_value=float(cfg.max_order_amount),
        max_position_ratio=float(cfg.max_position_ratio),
        max_daily_loss=float(cfg.daily_loss_limit),
    )
    risk_manager.set_config(account_id, risk_config)
    logger.info(f"风控配置已同步: account={account_id}, max_order={cfg.max_order_amount}, max_ratio={cfg.max_position_ratio}, daily_loss={cfg.daily_loss_limit}")


# ─── 同步 ───

@router.post("/sync")
async def sync_trading_data():
    """手动触发同步"""
    try:
        await trade_sync_service.sync_all()
        return {"success": True, "message": "同步完成"}
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"同步失败: {str(e)}")


# ─── 策略状态 ───

@router.get("/strategy-state/{strategy_name}", response_model=StrategyStateResponse)
def get_strategy_state(strategy_name: str, current_user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    """查看策略实例运行状态"""
    state = db.query(StrategyState).filter(
        StrategyState.strategy_name == strategy_name,
    ).first()
    if not state:
        raise HTTPException(status_code=404, detail="策略状态不存在")
    return StrategyStateResponse(
        strategy_name=state.strategy_name,
        class_name=state.class_name,
        vt_symbol=state.vt_symbol,
        grid_states_json=state.grid_states_json,
        signal_state=state.signal_state,
        buy_date=state.buy_date,
        bar_index=state.bar_index,
        prev_price=float(state.prev_price),
        updated_at=state.updated_at.isoformat() + "Z" if state.updated_at else "",
    )


@router.delete("/strategy-state/{strategy_name}")
def reset_strategy_state(strategy_name: str, current_user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    """重置策略实例运行状态（删除持久化记录）"""
    state = db.query(StrategyState).filter(
        StrategyState.strategy_name == strategy_name,
    ).first()
    if not state:
        raise HTTPException(status_code=404, detail="策略状态不存在")
    db.delete(state)
    db.commit()
    return {"message": "策略状态已重置"}


# ─── 辅助 ───

def _normalize_symbol(symbol: str) -> str:
    """标准化股票代码：600519 → 600519.SH, 000001 → 000001.SZ"""
    if "." in symbol:
        return symbol
    code = symbol.strip()
    if code.startswith(("6",)):
        return f"{code}.SH"
    elif code.startswith(("0", "3")):
        return f"{code}.SZ"
    elif code.startswith(("8", "4")):
        return f"{code}.BJ"
    return code
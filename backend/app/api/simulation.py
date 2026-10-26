from datetime import datetime
import logging

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from app.database import get_db
from app.models import User, TradingInstance, Strategy, AutoTradeConfig, Signal
from app.schemas.trading import TradingInstanceCreate, TradingInstanceResponse, SimOrderRequest, AutoTradeConfigUpdate
from app.services.auth_service import get_current_user
try:
    from app.services.vnpy_strategy_runner import vnpy_strategy_runner as strategy_runner
except ImportError:
    strategy_runner = None
from app.services.market_service import market_service
from app.services.vnpy_strategy_runner import SIM_COMMISSION_RATE, SIM_MIN_COMMISSION
from app.ws.manager import ws_manager

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/simulation", tags=["模拟交易"])


def _flatten_params(raw_params: dict, instance_params: dict | None = None) -> dict:
    """将策略参数转为扁平格式 {key: value}，供策略运行器使用

    支持多种格式：
    - 自定义策略嵌套格式: {key: {value, type, label}}
    - 系统策略参数格式: {key: {default, type, name, ...}}
    - 扁平格式: {key: value}
    - 实例已保存的参数: 直接使用
    """
    if instance_params:
        return instance_params
    if not raw_params:
        return {}
    if isinstance(raw_params, str):
        import json
        raw_params = json.loads(raw_params)
    params = {}
    for k, v in raw_params.items():
        if isinstance(v, dict) and "value" in v:
            params[k] = v["value"]
        elif isinstance(v, dict) and "default" in v:
            params[k] = v["default"]
        else:
            params[k] = v
    return params


def _get_auto_trade_config(instance_id: str) -> tuple[bool, bool]:
    """从 strategy_runner._instances 获取 auto_trade 配置"""
    config = strategy_runner._instances.get(instance_id, {})
    return (
        config.get("auto_trade_enabled", True),
        config.get("confirm_required", False),
    )


async def to_response(inst: TradingInstance) -> TradingInstanceResponse:
    # 获取实时账户统计
    auto_trade_enabled, confirm_required = _get_auto_trade_config(inst.id)
    stats = await strategy_runner.get_account_stats(inst.id)
    if stats:
        # 获取实时行情
        rt = strategy_runner.get_realtime_data(inst.id)
        current_price = rt["current_price"] if rt else 0
        change_rate = rt["change_rate"] if rt else 0

        return TradingInstanceResponse(
            id=inst.id,
            name=inst.name,
            symbol=inst.symbol,
            strategy_id=inst.strategy_id,
            account_id=inst.account_id,
            params=inst.params,
            mode=inst.mode,
            status=inst.status,
            total_trades=inst.total_trades,
            win_trades=inst.win_trades,
            loss_trades=inst.loss_trades,
            total_profit=stats["profit"],
            current_equity=stats["total_assets"],
            max_drawdown=float(inst.max_drawdown),
            position=stats["positions"][0] if stats["positions"] else {"quantity": 0, "avg_cost": 0, "market_value": 0},
            trades=inst.trades or [],
            current_price=current_price,
            change_rate=change_rate,
            auto_trade_enabled=auto_trade_enabled,
            confirm_required=confirm_required,
            created_at=inst.created_at.isoformat(),
            updated_at=inst.updated_at.isoformat(),
        )

    return TradingInstanceResponse(
        id=inst.id,
        name=inst.name,
        symbol=inst.symbol,
        strategy_id=inst.strategy_id,
        account_id=inst.account_id,
        params=inst.params,
        mode=inst.mode,
        status=inst.status,
        total_trades=inst.total_trades,
        win_trades=inst.win_trades,
        loss_trades=inst.loss_trades,
        total_profit=float(inst.total_profit),
        current_equity=float(inst.current_equity),
        max_drawdown=float(inst.max_drawdown),
        position=inst.position,
        trades=inst.trades or [],
        current_price=0,
        change_rate=0,
        auto_trade_enabled=auto_trade_enabled,
        confirm_required=confirm_required,
        created_at=inst.created_at.isoformat(),
        updated_at=inst.updated_at.isoformat(),
    )


@router.get("/instances", response_model=list[TradingInstanceResponse])
async def list_instances(current_user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    instances = db.query(TradingInstance).filter(
        TradingInstance.user_id == current_user.id,
        TradingInstance.mode == "simulation",
    ).all()

    # 同步 DB 状态与实际运行状态
    # 如果 DB 记录 "running" 但实际不在运行（后端重启/异常退出），尝试恢复
    needs_commit = False
    for inst in instances:
        if inst.status == "running" and not strategy_runner.is_running(inst.id):
            # 确保实例已注册到策略运行器
            if inst.id not in strategy_runner._instances:
                strategy = db.query(Strategy).filter(Strategy.id == inst.strategy_id).first()
                class_name = strategy.class_name if strategy else ""
                params = _flatten_params(strategy.parameters if strategy else {}, inst.params)
                initial_equity = float(inst.current_equity) if inst.current_equity else 1000000
                # 读取 AutoTradeConfig
                account_id = strategy_runner._get_account_id(inst.id)
                auto_config = db.query(AutoTradeConfig).filter(
                    AutoTradeConfig.account_id == account_id,
                ).first()
                strategy_runner.register(
                    instance_id=inst.id,
                    symbol=inst.symbol,
                    strategy_id=inst.strategy_id,
                    account_id=inst.account_id,
                    mode="simulation",
                    initial_equity=initial_equity,
                    class_name=class_name,
                    params=params,
                    auto_trade_enabled=auto_config.auto_trade_enabled if auto_config else None,
                    confirm_required=auto_config.confirm_required if auto_config else None,
                )
                strategy_runner.load_sim_account_from_db(inst.id)

            # 尝试重新启动（async def 路由运行在 event loop 中，asyncio.create_task 可正常工作）
            if strategy_runner.start(inst.id):
                logger.info(f"已恢复运行实例: {inst.id} ({inst.name})")
            else:
                # 启动失败，标记为 stopped
                inst.status = "stopped"
                needs_commit = True
                logger.warning(f"恢复实例失败，标记为 stopped: {inst.id} ({inst.name})")
    if needs_commit:
        db.commit()

    return [await to_response(i) for i in instances]


@router.post("/instances", response_model=TradingInstanceResponse)
async def create_instance(req: TradingInstanceCreate, current_user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    # 获取初始资金
    if req.initial_equity is not None:
        initial_equity = req.initial_equity
    else:
        initial_equity = 1000000

    inst = TradingInstance(
        user_id=current_user.id,
        name=req.name,
        symbol=req.symbol,
        strategy_id=req.strategy_id,
        account_id=req.account_id,
        params=req.params,
        mode="simulation",
        current_equity=initial_equity,
    )
    db.add(inst)
    db.commit()
    db.refresh(inst)

    # 获取策略的 class_name 和参数
    strategy = db.query(Strategy).filter(Strategy.id == req.strategy_id).first()
    class_name = strategy.class_name if strategy else ""

    # 参数格式兼容：前端传入的 params 为扁平格式，
    # 自定义策略的 Strategy.parameters 为嵌套格式 {key: {value, type, label}}，
    # 使用 _flatten_params 统一转为扁平格式
    params = _flatten_params(strategy.parameters if strategy else {}, req.params or None)

    # 注册到策略运行器
    strategy_runner.register(
        instance_id=inst.id,
        symbol=req.symbol,
        strategy_id=req.strategy_id,
        account_id=req.account_id,
        mode="simulation",
        initial_equity=initial_equity,
        class_name=class_name,
        params=params,
        auto_trade_enabled=req.auto_trade_enabled,
        confirm_required=req.confirm_required,
    )

    return await to_response(inst)


@router.post("/instances/{instance_id}/start", response_model=TradingInstanceResponse)
async def start_instance(instance_id: str, current_user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    inst = db.query(TradingInstance).filter(
        TradingInstance.id == instance_id,
        TradingInstance.user_id == current_user.id,
        TradingInstance.mode == "simulation",
    ).first()
    if not inst:
        raise HTTPException(status_code=404, detail="实例不存在")
    if inst.status == "running":
        raise HTTPException(status_code=400, detail="实例已在运行")

    # 确保已注册（获取策略参数）
    strategy = db.query(Strategy).filter(Strategy.id == inst.strategy_id).first()
    class_name = strategy.class_name if strategy else ""
    params = _flatten_params(strategy.parameters if strategy else {}, inst.params)

    # 只在未注册时才注册（避免重复注册重置策略状态）
    if instance_id not in strategy_runner._instances:
        # 读取 AutoTradeConfig
        account_id = strategy_runner._get_account_id(instance_id)
        auto_config = db.query(AutoTradeConfig).filter(
            AutoTradeConfig.account_id == account_id,
        ).first()
        strategy_runner.register(
            instance_id=inst.id,
            symbol=inst.symbol,
            strategy_id=inst.strategy_id,
            account_id=inst.account_id,
            mode="simulation",
            class_name=class_name,
            params=params,
            auto_trade_enabled=auto_config.auto_trade_enabled if auto_config else None,
            confirm_required=auto_config.confirm_required if auto_config else None,
        )

    success = strategy_runner.start(inst.id)
    if not success:
        raise HTTPException(status_code=500, detail="启动失败")

    inst.status = "running"
    db.commit()
    db.refresh(inst)
    return await to_response(inst)


@router.post("/instances/{instance_id}/stop", response_model=TradingInstanceResponse)
async def stop_instance(instance_id: str, current_user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    inst = db.query(TradingInstance).filter(
        TradingInstance.id == instance_id,
        TradingInstance.user_id == current_user.id,
        TradingInstance.mode == "simulation",
    ).first()
    if not inst:
        raise HTTPException(status_code=404, detail="实例不存在")

    strategy_runner.stop(inst.id)
    inst.status = "stopped"
    db.commit()
    db.refresh(inst)
    return await to_response(inst)


@router.delete("/instances/{instance_id}")
def delete_instance(instance_id: str, current_user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    """删除模拟策略实例（自动停止运行中的实例）"""
    inst = db.query(TradingInstance).filter(
        TradingInstance.id == instance_id,
        TradingInstance.user_id == current_user.id,
        TradingInstance.mode == "simulation",
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


@router.get("/instances/{instance_id}/realtime")
def get_realtime(instance_id: str, current_user: User = Depends(get_current_user)):
    data = strategy_runner.get_realtime_data(instance_id)
    if not data:
        raise HTTPException(status_code=404, detail="实例不存在或无行情数据")
    return data


@router.get("/instances/{instance_id}/logs")
def get_logs(instance_id: str, current_user: User = Depends(get_current_user)):
    logs = strategy_runner.get_logs(instance_id)
    return {"instance_id": instance_id, "logs": logs}


@router.get("/instances/{instance_id}/debug")
async def get_debug_info(instance_id: str, current_user: User = Depends(get_current_user)):
    """获取策略实例的实时调试信息"""
    config = strategy_runner._instances.get(instance_id)
    if not config:
        raise HTTPException(status_code=404, detail="实例不存在")

    symbol = config["symbol"]
    strategy = strategy_runner._strategies.get(instance_id)
    class_name = config.get("class_name", "")

    # 价格信息
    current_price = strategy_runner._get_current_price(symbol)
    tick_price = strategy_runner._current_prices.get(symbol, 0)
    hist_price = strategy_runner._hist_close_prices.get(symbol, 0)
    tick = strategy_runner._current_ticks.get(symbol)

    # 策略状态
    strategy_info = {}
    if strategy:
        strategy_info = {
            "class_name": type(strategy).__name__,
            "bars_count": len(strategy._bars),
            "prev_signal": strategy._prev_signal,
            "setting": strategy.setting,
            "last_bar": strategy._bars[-1] if strategy._bars else None,
        }

    # 账户状态
    account_id = strategy_runner._get_account_id(instance_id)
    stats = await strategy_runner.get_account_stats(instance_id)

    # 运行状态
    is_running = strategy_runner.is_running(instance_id)

    return {
        "instance_id": instance_id,
        "symbol": symbol,
        "is_running": is_running,
        "mode": config.get("mode", "simulation"),
        "class_name": class_name,
        "current_price": current_price,
        "price_source": "realtime_tick" if tick_price > 0 else ("hist_close" if hist_price > 0 else "none"),
        "tick_price": tick_price,
        "hist_close_price": hist_price,
        "tick": tick,
        "strategy": strategy_info,
        "account_id": account_id,
        "account_stats": stats,
        "signal_period": "daily",
        "xt_available": market_service.is_available(),
    }


# ─── 模拟手动下单 ───

@router.post("/instances/{instance_id}/order")
async def place_sim_order(
    instance_id: str,
    req: SimOrderRequest,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """模拟手动下单"""
    inst = db.query(TradingInstance).filter(
        TradingInstance.id == instance_id,
        TradingInstance.user_id == current_user.id,
        TradingInstance.mode == "simulation",
    ).first()
    if not inst:
        raise HTTPException(status_code=404, detail="实例不存在")

    # 如果实例未注册到策略运行器（后端重启后内存清空），自动注册
    if instance_id not in strategy_runner._instances:
        strategy = db.query(Strategy).filter(Strategy.id == inst.strategy_id).first()
        class_name = strategy.class_name if strategy else ""
        params = _flatten_params(strategy.parameters if strategy else {}, inst.params)
        initial_equity = float(inst.current_equity) if inst.current_equity else 1000000
        account_id = strategy_runner._get_account_id(instance_id)
        auto_config = db.query(AutoTradeConfig).filter(
            AutoTradeConfig.account_id == account_id,
        ).first()
        strategy_runner.register(
            instance_id=inst.id,
            symbol=inst.symbol,
            strategy_id=inst.strategy_id,
            account_id=inst.account_id,
            mode="simulation",
            initial_equity=initial_equity,
            class_name=class_name,
            params=params,
            auto_trade_enabled=auto_config.auto_trade_enabled if auto_config else None,
            confirm_required=auto_config.confirm_required if auto_config else None,
        )

    config = strategy_runner._instances.get(instance_id)
    symbol = config["symbol"]
    account_id = strategy_runner._get_account_id(instance_id)

    # 获取成交价格
    if req.price > 0:
        trade_price = req.price
    else:
        trade_price = strategy_runner._get_current_price(symbol)
        if trade_price <= 0:
            raise HTTPException(status_code=400, detail="无法获取实时价格，请指定委托价格")

    side = req.side.lower()
    quantity = req.quantity

    # T+1 和涨跌停校验 + 加锁保护
    pnl = 0
    async with strategy_runner._get_account_lock(account_id):
        passed, reason = strategy_runner._check_t1_and_limit(account_id, symbol, side, trade_price)
        if not passed:
            raise HTTPException(status_code=400, detail=reason)

        if side == "buy":
            # 检查可用资金
            sim_account = strategy_runner._sim_accounts.get(account_id)
            if not sim_account:
                raise HTTPException(status_code=400, detail="模拟账户不存在")
            cost = quantity * trade_price
            commission = max(cost * SIM_COMMISSION_RATE, SIM_MIN_COMMISSION)
            if sim_account["available"] < cost + commission:
                raise HTTPException(status_code=400, detail=f"可用资金不足：可用 {sim_account['available']:.2f}，需要 {cost + commission:.2f}")

            strategy_runner._update_sim_account_buy(account_id, symbol, quantity, trade_price)

            # 推送交易通知
            await ws_manager.broadcast({
                "type": "strategy_trade",
                "data": {
                    "instance_id": instance_id,
                    "side": "buy",
                    "price": trade_price,
                    "quantity": quantity,
                    "pnl": 0,
                    "time": datetime.now().strftime("%H:%M:%S"),
                }
            })

        elif side == "sell":
            # 检查持仓
            positions = strategy_runner._sim_positions.get(account_id, {})
            pos = positions.get(symbol)
            if not pos or pos["quantity"] < quantity:
                available_qty = pos["quantity"] if pos else 0
                raise HTTPException(status_code=400, detail=f"持仓不足：可用 {available_qty} 股，需要 {quantity} 股")

            avg_cost = pos["avg_cost"]
            strategy_runner._update_sim_account_sell(account_id, symbol, quantity, trade_price, avg_cost)
            pnl = (trade_price - avg_cost) * quantity

            # 推送交易通知
            await ws_manager.broadcast({
                "type": "strategy_trade",
                "data": {
                    "instance_id": instance_id,
                    "side": "sell",
                    "price": trade_price,
                    "quantity": quantity,
                    "pnl": pnl,
                    "time": datetime.now().strftime("%H:%M:%S"),
                }
            })
        else:
            raise HTTPException(status_code=400, detail=f"不支持的方向: {side}")

    # 推送账户更新
    stats = await strategy_runner.get_account_stats(instance_id)
    if stats:
        await ws_manager.broadcast({
            "type": "strategy_account",
            "data": {
                "instance_id": instance_id,
                "balance": stats["balance"],
                "available": stats["available"],
                "market_value": stats["market_value"],
                "total_assets": stats["total_assets"],
                "profit": stats["profit"],
                "profit_rate": stats["profit_rate"],
                "positions": stats["positions"],
                "current_price": trade_price,
            }
        })

    # 保存模拟账户数据到数据库
    strategy_runner.save_sim_account_to_db(instance_id)

    return {
        "success": True,
        "side": side,
        "symbol": symbol,
        "quantity": quantity,
        "price": trade_price,
        "pnl": pnl,
    }


# ─── 自动交易配置 ──────────────────────────────────────────────────────────

@router.get("/instances/{instance_id}/auto-trade/config")
async def get_auto_trade_config(
    instance_id: str,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """获取模拟实例的自动交易配置"""
    inst = db.query(TradingInstance).filter(
        TradingInstance.id == instance_id,
        TradingInstance.user_id == current_user.id,
        TradingInstance.mode == "simulation",
    ).first()
    if not inst:
        raise HTTPException(status_code=404, detail="实例不存在")

    account_id = strategy_runner._get_account_id(instance_id)
    config = db.query(AutoTradeConfig).filter(
        AutoTradeConfig.account_id == account_id,
    ).first()

    if not config:
        # 从 strategy_runner 内存读取当前值，创建 DB 记录
        auto_trade_enabled, confirm_required = _get_auto_trade_config(instance_id)
        config = AutoTradeConfig(
            user_id=current_user.id,
            account_id=account_id,
            auto_trade_enabled=auto_trade_enabled,
            confirm_required=confirm_required,
        )
        db.add(config)
        db.commit()
        db.refresh(config)

    return {
        "id": config.id,
        "user_id": config.user_id,
        "account_id": config.account_id,
        "auto_trade_enabled": config.auto_trade_enabled,
        "confirm_required": config.confirm_required,
        "max_order_amount": float(config.max_order_amount),
        "max_position_ratio": float(config.max_position_ratio),
        "daily_loss_limit": float(config.daily_loss_limit),
        "created_at": config.created_at.isoformat() if config.created_at else None,
        "updated_at": config.updated_at.isoformat() if config.updated_at else None,
    }


@router.post("/instances/{instance_id}/auto-trade/config")
async def update_auto_trade_config(
    instance_id: str,
    update: AutoTradeConfigUpdate,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """更新模拟实例的自动交易配置"""
    from app.core.risk_manager import risk_manager, RiskConfig

    inst = db.query(TradingInstance).filter(
        TradingInstance.id == instance_id,
        TradingInstance.user_id == current_user.id,
        TradingInstance.mode == "simulation",
    ).first()
    if not inst:
        raise HTTPException(status_code=404, detail="实例不存在")

    account_id = strategy_runner._get_account_id(instance_id)
    config = db.query(AutoTradeConfig).filter(
        AutoTradeConfig.account_id == account_id,
    ).first()

    if not config:
        auto_trade_enabled, confirm_required = _get_auto_trade_config(instance_id)
        config = AutoTradeConfig(
            user_id=current_user.id,
            account_id=account_id,
            auto_trade_enabled=auto_trade_enabled,
            confirm_required=confirm_required,
        )
        db.add(config)
        db.commit()
        db.refresh(config)

    for field, value in update.model_dump(exclude_unset=True).items():
        setattr(config, field, value)
    db.commit()
    db.refresh(config)

    # 同步到 strategy_runner 内存
    runner_config = strategy_runner._instances.get(instance_id)
    if runner_config:
        runner_config["auto_trade_enabled"] = config.auto_trade_enabled
        runner_config["confirm_required"] = config.confirm_required

    # 同步风控配置
    risk_config = RiskConfig(
        max_order_value=float(config.max_order_amount),
        max_position_ratio=float(config.max_position_ratio),
        max_daily_loss=float(config.daily_loss_limit),
    )
    risk_manager.set_config(account_id, risk_config)

    return {
        "id": config.id,
        "user_id": config.user_id,
        "account_id": config.account_id,
        "auto_trade_enabled": config.auto_trade_enabled,
        "confirm_required": config.confirm_required,
        "max_order_amount": float(config.max_order_amount),
        "max_position_ratio": float(config.max_position_ratio),
        "daily_loss_limit": float(config.daily_loss_limit),
        "created_at": config.created_at.isoformat() if config.created_at else None,
        "updated_at": config.updated_at.isoformat() if config.updated_at else None,
    }


# ─── 信号管理 ──────────────────────────────────────────────────────────────

@router.get("/instances/{instance_id}/signals")
async def list_pending_signals(
    instance_id: str,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """列出模拟实例的待确认信号"""
    inst = db.query(TradingInstance).filter(
        TradingInstance.id == instance_id,
        TradingInstance.user_id == current_user.id,
        TradingInstance.mode == "simulation",
    ).first()
    if not inst:
        raise HTTPException(status_code=404, detail="实例不存在")

    signals = db.query(Signal).filter(
        Signal.instance_id == instance_id,
        Signal.status == "pending",
    ).order_by(Signal.created_at.desc()).all()

    return [_to_signal_response(s) for s in signals]


@router.get("/instances/{instance_id}/signals/history")
async def get_signal_history(
    instance_id: str,
    limit: int = 50,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """获取模拟实例的信号历史"""
    inst = db.query(TradingInstance).filter(
        TradingInstance.id == instance_id,
        TradingInstance.user_id == current_user.id,
        TradingInstance.mode == "simulation",
    ).first()
    if not inst:
        raise HTTPException(status_code=404, detail="实例不存在")

    signals = db.query(Signal).filter(
        Signal.instance_id == instance_id,
    ).order_by(Signal.created_at.desc()).limit(limit).all()

    return [_to_signal_response(s) for s in signals]


@router.post("/instances/{instance_id}/signals/{signal_id}/confirm")
async def confirm_signal(
    instance_id: str,
    signal_id: str,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """确认模拟信号 → 执行模拟成交"""
    inst = db.query(TradingInstance).filter(
        TradingInstance.id == instance_id,
        TradingInstance.user_id == current_user.id,
        TradingInstance.mode == "simulation",
    ).first()
    if not inst:
        raise HTTPException(status_code=404, detail="实例不存在")

    result = await strategy_runner.confirm_sim_signal(instance_id, signal_id)
    if not result["success"]:
        raise HTTPException(status_code=400, detail=result["message"])

    # 刷新实例数据
    stats = await strategy_runner.get_account_stats(instance_id)
    if stats:
        await ws_manager.broadcast({
            "type": "strategy_account",
            "data": {
                "instance_id": instance_id,
                "balance": stats["balance"],
                "available": stats["available"],
                "market_value": stats["market_value"],
                "total_assets": stats["total_assets"],
                "profit": stats["profit"],
                "profit_rate": stats["profit_rate"],
                "positions": stats["positions"],
            }
        })

    return result


@router.post("/instances/{instance_id}/signals/{signal_id}/reject")
async def reject_signal(
    instance_id: str,
    signal_id: str,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """拒绝模拟信号"""
    inst = db.query(TradingInstance).filter(
        TradingInstance.id == instance_id,
        TradingInstance.user_id == current_user.id,
        TradingInstance.mode == "simulation",
    ).first()
    if not inst:
        raise HTTPException(status_code=404, detail="实例不存在")

    result = await strategy_runner.reject_sim_signal(signal_id)
    if not result["success"]:
        raise HTTPException(status_code=400, detail=result["message"])

    return result


def _to_signal_response(sig) -> dict:
    """Signal 模型转响应字典"""
    return {
        "id": sig.id,
        "user_id": sig.user_id,
        "instance_id": sig.instance_id,
        "account_id": sig.account_id,
        "symbol": sig.symbol,
        "name": sig.name,
        "side": sig.side,
        "price": float(sig.price),
        "quantity": sig.quantity,
        "status": sig.status,
        "strategy_id": sig.strategy_id,
        "reason": sig.reason,
        "created_at": sig.created_at.isoformat() + "Z" if sig.created_at else None,
        "updated_at": sig.updated_at.isoformat() + "Z" if sig.updated_at else None,
    }

from datetime import datetime, timezone
import asyncio
from functools import partial
import logging

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session, load_only

from app.database import get_db
from app.models import User, BacktestResult, Strategy
from app.schemas.backtest import BacktestRunRequest, BacktestResultResponse, BacktestResultListResponse, BatchDeleteRequest
from app.services.auth_service import get_current_user
from app.config import settings

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/backtest", tags=["回测"])


def _get_default_source() -> str:
    return settings.DATA_SOURCE


def _format_dt(dt: datetime | None) -> str | None:
    if dt is None:
        return None
    return dt.replace(tzinfo=timezone.utc).isoformat().replace('+00:00', 'Z')


def to_response(r: BacktestResult) -> BacktestResultResponse:
    return BacktestResultResponse(
        id=r.id,
        strategy_id=r.strategy_id,
        symbol=r.symbol,
        interval=r.interval,
        period=r.period or "daily",
        start_date=r.start_date,
        end_date=r.end_date,
        initial_capital=float(r.initial_capital),
        initial_position=int(r.initial_position or 0),
        commission_rate=float(r.commission_rate or 0.0003),
        stamp_tax_rate=float(r.stamp_tax_rate or 0.001),
        params=r.params,
        status=r.status,
        progress=r.progress,
        total_return=float(r.total_return),
        annualized_return=float(r.annualized_return),
        max_drawdown=float(r.max_drawdown),
        sharpe_ratio=float(r.sharpe_ratio),
        sortino_ratio=float(r.sortino_ratio),
        win_rate=float(r.win_rate),
        profit_factor=float(r.profit_factor),
        total_trades=r.total_trades,
        avg_trade_return=float(r.avg_trade_return),
        volatility=float(r.volatility),
        beta=float(r.beta),
        alpha=float(r.alpha),
        daily_results=r.daily_results or [],
        intraday_results=r.intraday_results or [],
        trades=r.trades or [],
        initial_cash=float(r.initial_cash),
        initial_position_value=float(r.initial_position_value),
        initial_position_quantity=float(r.initial_position_quantity),
        final_cash=float(r.final_cash),
        final_position_value=float(r.final_position_value),
        final_position_quantity=float(r.final_position_quantity),
        total_profit=float(r.total_profit),
        created_at=_format_dt(r.created_at),
        updated_at=_format_dt(r.updated_at) if r.updated_at else _format_dt(r.created_at),
        completed_at=_format_dt(r.completed_at),
    )


@router.post("/run", response_model=BacktestResultResponse)
async def run_backtest(req: BacktestRunRequest, current_user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    strategy = db.query(Strategy).filter(Strategy.id == req.strategy_id).first()
    if not strategy:
        raise HTTPException(status_code=404, detail="策略不存在")

    result = BacktestResult(
        user_id=current_user.id,
        strategy_id=req.strategy_id,
        symbol=req.symbol,
        interval=req.interval,
        period=req.period,
        start_date=req.start_date,
        end_date=req.end_date,
        initial_capital=req.initial_capital,
        initial_position=req.initial_position,
        commission_rate=req.commission_rate,
        stamp_tax_rate=req.stamp_tax_rate,
        params=req.params,
        status="running",
        progress=0,
    )
    db.add(result)
    db.commit()
    db.refresh(result)

    # 使用 vnpy 回测引擎执行回测
    try:
        data_source = req.data_source if req.data_source else None

        # xtquant 数据源需要行情服务在线
        if data_source == "xtquant" or (not data_source and _get_default_source() == "xtquant"):
            from app.services.market_service import market_service
            market_health = market_service.check_health()
            logger.info(f"行情服务健康检查: {market_health}")
            if market_health.get("status") != "online":
                raise ValueError(f"行情服务不可用（{market_health.get('status')}），无法获取K线数据")

        from app.services.vnpy_backtest_service import run_vnpy_backtest as run_engine
        logger.info(f"开始回测: class_name={strategy.class_name}, symbol={req.symbol}, "
                     f"start_date={req.start_date}, end_date={req.end_date}, "
                     f"capital={req.initial_capital}, params={req.params}, "
                     f"interval={req.interval}, period={req.period}, "
                     f"data_source={data_source or 'default'}, incremental_mode={req.incremental_mode}")
        # 在线程池中运行回测引擎，使事件循环保持空闲以处理 WebSocket 实时日志推送
        # 传入主线程事件循环引用，供回测引擎通过 run_coroutine_threadsafe 推送日志
        loop = asyncio.get_running_loop()
        stats = await loop.run_in_executor(
            None,
            partial(
                run_engine,
                class_name=strategy.class_name,
                symbol=req.symbol,
                start_date=req.start_date,
                end_date=req.end_date,
                capital=req.initial_capital,
                setting=req.params,
                interval=req.interval,
                period=req.period,
                commission_rate=req.commission_rate,
                stamp_tax_rate=req.stamp_tax_rate,
                initial_position=req.initial_position,
                data_source=data_source,
                user_id=current_user.id,
                event_loop=loop,
                incremental_mode=req.incremental_mode,
            ),
        )
        logger.info(f"回测完成: total_return={stats.get('total_return')}, "
                     f"total_trades={stats.get('total_trades')}, "
                     f"sharpe_ratio={stats.get('sharpe_ratio')}")
    except ValueError as e:
        logger.warning(f"回测参数错误: {e}")
        result.status = "failed"
        db.commit()
        raise HTTPException(status_code=400, detail=str(e))
    except Exception as e:
        logger.error(f"回测执行失败: {e}", exc_info=True)
        result.status = "failed"
        db.commit()
        raise HTTPException(status_code=500, detail=f"回测执行失败: {str(e)}")

    for key, value in stats.items():
        setattr(result, key, value)
    result.status = "completed"
    result.progress = 100
    result.completed_at = datetime.utcnow()
    db.commit()
    db.refresh(result)

    return to_response(result)


@router.get("/results", response_model=list[BacktestResultListResponse])
def list_backtest_results(current_user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    # 排除4个大JSON列，避免MySQL ORDER BY时sort_buffer溢出(1038 Out of sort memory)
    results = (
        db.query(BacktestResult)
        .filter(BacktestResult.user_id == current_user.id)
        .options(
            load_only(
                BacktestResult.id,
                BacktestResult.user_id,
                BacktestResult.strategy_id,
                BacktestResult.account_id,
                BacktestResult.symbol,
                BacktestResult.interval,
                BacktestResult.period,
                BacktestResult.start_date,
                BacktestResult.end_date,
                BacktestResult.initial_capital,
                BacktestResult.initial_position,
                BacktestResult.commission_rate,
                BacktestResult.stamp_tax_rate,
                BacktestResult.params,
                BacktestResult.status,
                BacktestResult.progress,
                BacktestResult.total_return,
                BacktestResult.annualized_return,
                BacktestResult.max_drawdown,
                BacktestResult.sharpe_ratio,
                BacktestResult.sortino_ratio,
                BacktestResult.win_rate,
                BacktestResult.profit_factor,
                BacktestResult.total_trades,
                BacktestResult.avg_trade_return,
                BacktestResult.volatility,
                BacktestResult.beta,
                BacktestResult.alpha,
                BacktestResult.initial_cash,
                BacktestResult.initial_position_value,
                BacktestResult.initial_position_quantity,
                BacktestResult.final_cash,
                BacktestResult.final_position_value,
                BacktestResult.final_position_quantity,
                BacktestResult.total_profit,
                BacktestResult.created_at,
                BacktestResult.updated_at,
                BacktestResult.completed_at,
            )
        )
        .order_by(BacktestResult.updated_at.desc())
        .all()
    )
    # load_only排除了daily_results/intraday_results/trades/strategy_logs，
    # model_validate会触发延迟加载，所以手动构造响应，大JSON列用空默认值
    return [
        BacktestResultListResponse(
            id=r.id,
            strategy_id=r.strategy_id,
            symbol=r.symbol,
            interval=r.interval,
            period=r.period or "daily",
            start_date=r.start_date,
            end_date=r.end_date,
            initial_capital=float(r.initial_capital),
            initial_position=int(r.initial_position or 0),
            commission_rate=float(r.commission_rate or 0.0003),
            stamp_tax_rate=float(r.stamp_tax_rate or 0.001),
            params=r.params,
            status=r.status,
            progress=r.progress,
            total_return=float(r.total_return),
            annualized_return=float(r.annualized_return),
            max_drawdown=float(r.max_drawdown),
            sharpe_ratio=float(r.sharpe_ratio),
            sortino_ratio=float(r.sortino_ratio),
            win_rate=float(r.win_rate),
            profit_factor=float(r.profit_factor),
            total_trades=r.total_trades,
            avg_trade_return=float(r.avg_trade_return),
            volatility=float(r.volatility),
            beta=float(r.beta),
            alpha=float(r.alpha),
            daily_results=[],
            intraday_results=[],
            trades=[],
            created_at=_format_dt(r.created_at) or "",
            updated_at=_format_dt(r.updated_at) if r.updated_at else _format_dt(r.created_at) or "",
            completed_at=_format_dt(r.completed_at),
            initial_cash=float(r.initial_cash),
            initial_position_value=float(r.initial_position_value),
            initial_position_quantity=float(r.initial_position_quantity),
            final_cash=float(r.final_cash),
            final_position_value=float(r.final_position_value),
            final_position_quantity=float(r.final_position_quantity),
            total_profit=float(r.total_profit),
            strategy_logs=[],
        )
        for r in results
    ]


@router.get("/results/{result_id}", response_model=BacktestResultResponse)
def get_backtest_result(result_id: str, current_user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    r = db.query(BacktestResult).filter(BacktestResult.id == result_id, BacktestResult.user_id == current_user.id).first()
    if not r:
        raise HTTPException(status_code=404, detail="回测结果不存在")
    return to_response(r)


@router.delete("/results/{result_id}")
def delete_backtest_result(result_id: str, current_user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    r = db.query(BacktestResult).filter(BacktestResult.id == result_id, BacktestResult.user_id == current_user.id).first()
    if not r:
        raise HTTPException(status_code=404, detail="回测结果不存在")
    db.delete(r)
    db.commit()
    return {"message": "删除成功"}


@router.post("/results/batch-delete")
def batch_delete_backtest_results(req: BatchDeleteRequest, current_user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    if not req.ids:
        raise HTTPException(status_code=400, detail="未指定要删除的回测记录")
    results = db.query(BacktestResult).filter(
        BacktestResult.id.in_(req.ids),
        BacktestResult.user_id == current_user.id,
    ).all()
    if not results:
        raise HTTPException(status_code=404, detail="未找到可删除的回测记录")
    count = len(results)
    for r in results:
        db.delete(r)
    db.commit()
    return {"message": f"成功删除 {count} 条回测记录", "deleted_count": count}


@router.get("/data-sources")
def list_data_sources():
    """返回可用的数据源列表"""
    from app.core.data_bridge import get_available_sources
    return {
        "default": settings.DATA_SOURCE,
        "sources": get_available_sources(),
    }
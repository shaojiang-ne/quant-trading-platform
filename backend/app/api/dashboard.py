from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session
from sqlalchemy import func

from app.database import get_db
from app.models import User, TradingInstance, BacktestResult, Strategy, Order
from app.services.auth_service import get_current_user
try:
    from app.services.vnpy_strategy_runner import vnpy_strategy_runner as strategy_runner
except ImportError:
    strategy_runner = None
from app.services.market_service import market_service
from app.core.live_gateway import live_gateway
from app.core.data_bridge import data_bridge
from app.core.engine import engine_manager
import json
import logging
from datetime import date

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/dashboard", tags=["仪表盘"])


@router.get("/summary")
async def get_summary(current_user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    # === 模拟交易实例 ===
    sim_instances = db.query(TradingInstance).filter(
        TradingInstance.user_id == current_user.id,
        TradingInstance.mode == "simulation",
    ).all()

    sim_total_assets = 0
    sim_total_profit = 0
    sim_initial_total = 0
    sim_running = 0
    sim_instance_list = []

    for inst in sim_instances:
        stats = await strategy_runner.get_account_stats(inst.id)
        rt = strategy_runner.get_realtime_data(inst.id)

        if stats:
            total_assets = stats["total_assets"]
            profit = stats["profit"]
            initial = total_assets - profit
            sim_total_assets += total_assets
            sim_total_profit += profit
            sim_initial_total += initial

            instance_data = {
                "id": inst.id,
                "name": inst.name,
                "symbol": inst.symbol,
                "status": inst.status,
                "total_assets": total_assets,
                "profit": profit,
                "profit_rate": stats["profit_rate"],
                "current_price": rt["current_price"] if rt else 0,
                "change_rate": rt["change_rate"] if rt else 0,
                "position": stats["positions"][0] if stats["positions"] else None,
                "total_trades": inst.total_trades,
                "win_trades": inst.win_trades,
                "loss_trades": inst.loss_trades,
            }
        else:
            equity = float(inst.current_equity)
            profit = float(inst.total_profit)
            sim_total_assets += equity
            sim_total_profit += profit
            sim_initial_total += (equity - profit)

            instance_data = {
                "id": inst.id,
                "name": inst.name,
                "symbol": inst.symbol,
                "status": inst.status,
                "total_assets": equity,
                "profit": profit,
                "profit_rate": float(inst.current_equity - inst.total_profit) > 0
                    and profit / float(inst.current_equity - inst.total_profit) or 0,
                "current_price": 0,
                "change_rate": 0,
                "position": None,
                "total_trades": inst.total_trades,
                "win_trades": inst.win_trades,
                "loss_trades": inst.loss_trades,
            }

        if inst.status == "running":
            sim_running += 1
        sim_instance_list.append(instance_data)

    sim_profit_rate = sim_total_profit / sim_initial_total if sim_initial_total > 0 else 0

    # === 回测统计 ===
    bt_results = db.query(BacktestResult).filter(
        BacktestResult.user_id == current_user.id,
        BacktestResult.status == "completed",
    ).order_by(BacktestResult.created_at.desc()).all()

    bt_count = len(bt_results)
    bt_avg_return = 0
    bt_best_return = 0
    bt_recent = []

    if bt_count > 0:
        bt_avg_return = sum(float(r.total_return) for r in bt_results) / bt_count
        bt_best_return = max(float(r.total_return) for r in bt_results)

        for r in bt_results[:5]:
            strategy = db.query(Strategy).filter(Strategy.id == r.strategy_id).first()
            bt_recent.append({
                "id": r.id,
                "strategy_name": strategy.name if strategy else r.strategy_id,
                "symbol": r.symbol,
                "total_return": float(r.total_return),
                "sharpe_ratio": float(r.sharpe_ratio),
                "max_drawdown": float(r.max_drawdown),
                "win_rate": float(r.win_rate),
                "created_at": r.created_at.isoformat(),
            })

    # === 账户概览 ===
    account_cards = []

    # 实盘账户
    if live_gateway.is_connected:
        try:
            account_data = await live_gateway.get_account()
            positions_data = await live_gateway.get_positions()
            positions_list = positions_data if isinstance(positions_data, list) else positions_data.get("positions", [])

            total_assets = float(account_data.get("total_assets", 0))
            market_value = float(account_data.get("market_value", 0))
            cash = float(account_data.get("cash", 0))

            # 总盈亏：持仓 profit 求和（持仓市值 - 持仓成本）
            total_profit = 0
            for pos in (positions_list if isinstance(positions_list, list) else []):
                total_profit += float(pos.get("profit", 0))
            total_profit_rate = total_profit / (total_assets - total_profit) if (total_assets - total_profit) > 0 else 0

            # 当日盈亏：复用 trading.py /positions 的计算逻辑
            # daily_profit = sum((current_price - pre_close) * quantity) for each position
            daily_profit = 0
            if isinstance(positions_list, list) and market_service.is_available():
                for pos in positions_list:
                    symbol = pos.get("symbol", "")
                    current_price = float(pos.get("current_price", 0))
                    quantity = int(pos.get("quantity", pos.get("volume", 0)))
                    pre_close = 0
                    if symbol:
                        xt_symbol = data_bridge.to_xt_symbol(symbol.split(".")[0] if "." in symbol else symbol)
                        tick = market_service.get_full_tick(xt_symbol)
                        if tick:
                            pre_close = float(tick.get("lastClose", 0))
                    if pre_close > 0 and current_price > 0:
                        pos_daily = round((current_price - pre_close) * quantity, 2)
                        daily_profit += pos_daily
            daily_profit_rate = daily_profit / total_assets if total_assets > 0 else 0

            # 交易次数：从后端 Order 表统计（不从 QMT 请求）
            today_str = date.today().isoformat()
            total_trades = db.query(Order).filter(
                Order.account_id == live_gateway.account_id,
                Order.status.in_(["submitted", "filled", "partial"]),
            ).count()
            daily_trades = db.query(Order).filter(
                Order.account_id == live_gateway.account_id,
                Order.status.in_(["submitted", "filled", "partial"]),
                Order.created_at >= today_str,
            ).count()

            logger.info(f"实盘账户: total_assets={total_assets}, market_value={market_value}, "
                        f"total_profit(持仓盈亏)={total_profit:.2f}, daily_profit={daily_profit:.2f}, "
                        f"total_trades={total_trades}, daily_trades={daily_trades}, "
                        f"positions_count={len(positions_list) if isinstance(positions_list, list) else 0}")

            account_cards.append({
                "type": "real",
                "name": "实盘账户",
                "account_id": live_gateway.account_id,
                "total_assets": total_assets,
                "market_value": market_value,
                "total_profit": total_profit,
                "total_profit_rate": total_profit_rate,
                "daily_profit": daily_profit,
                "daily_profit_rate": daily_profit_rate,
                "total_trades": total_trades,
                "daily_trades": daily_trades,
            })
        except Exception as e:
            logger.warning(f"获取实盘账户数据失败: {e}")

    # 模拟账户：每个实例一个卡片
    today_str = date.today().isoformat()
    for inst in sim_instances:
        stats = await strategy_runner.get_account_stats(inst.id)
        # 统计交易次数
        trades_list = inst.trades if isinstance(inst.trades, list) else json.loads(inst.trades or "[]")
        total_trades = len(trades_list)
        daily_trades = sum(1 for t in trades_list if isinstance(t, dict) and str(t.get("date", t.get("open_date", "")))[:10] == today_str)

        if stats:
            total_assets = stats.get("total_assets", 0)
            # 当日盈亏：从持仓的 daily_profit 汇总（_get_sim_account_stats 已计算）
            daily_profit = sum(pos.get("daily_profit", 0) for pos in stats.get("positions", []))
            # 当日涨跌幅：以昨日总资产为基准（total_assets - daily_profit）
            yesterday_assets = total_assets - daily_profit
            daily_profit_rate = daily_profit / yesterday_assets if yesterday_assets > 0 else 0

            account_cards.append({
                "type": "virtual",
                "name": inst.name,
                "account_id": inst.account_id,
                "total_assets": stats["total_assets"],
                "market_value": stats.get("market_value", 0),
                "total_profit": stats["profit"],
                "total_profit_rate": stats["profit_rate"],
                "daily_profit": daily_profit,
                "daily_profit_rate": daily_profit_rate,
                "total_trades": total_trades,
                "daily_trades": daily_trades,
            })
        else:
            equity = float(inst.current_equity)
            profit = float(inst.total_profit)
            initial = equity - profit if equity > profit else equity
            profit_rate = profit / initial if initial > 0 else 0
            account_cards.append({
                "type": "virtual",
                "name": inst.name,
                "account_id": inst.account_id,
                "total_assets": equity,
                "market_value": 0,
                "total_profit": profit,
                "total_profit_rate": profit_rate,
                "daily_profit": 0,
                "daily_profit_rate": 0,
                "total_trades": total_trades,
                "daily_trades": daily_trades,
            })

    # 实时探测服务健康状态
    market_health = market_service.check_health()
    trading_health = {"connected": live_gateway.is_connected, "account_id": live_gateway.account_id}
    if live_gateway.is_connected:
        try:
            health = await live_gateway.check_health()
            trading_health = {
                "connected": True,
                "account_id": live_gateway.account_id,
                "status": health.get("status", "unknown"),
                "error": health.get("error"),
            }
        except Exception as e:
            trading_health = {"connected": False, "error": str(e)}

    return {
        "services": {
            "market": market_health,
            "trading": trading_health,
        },
        "simulation": {
            "total_assets": sim_total_assets,
            "total_profit": sim_total_profit,
            "profit_rate": sim_profit_rate,
            "running_count": sim_running,
            "total_count": len(sim_instance_list),
            "instances": sim_instance_list,
        },
        "backtest": {
            "total_count": bt_count,
            "avg_return": bt_avg_return,
            "best_return": bt_best_return,
            "recent": bt_recent,
        },
        "accounts": account_cards,
    }

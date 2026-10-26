"""实盘信号→模拟成交链路全分支测试"""
import pytest

from app.services.vnpy_strategy_runner import vnpy_strategy_runner as runner
from app.database import SessionLocal
from app.models.models import AutoTradeConfig, Order, StrategyLog


def _setup_instance(instance_id: str, balance: float = 1_000_000):
    """注入 live instance + sim 账户 + AutoTradeConfig(auto, no confirm)"""
    account_id = f"sim-{instance_id}"
    runner._instances[instance_id] = {
        "mode": "live", "account_id": "broker-x",
        "symbol": "600519", "strategy_id": "s1",
        "initial_equity": balance, "class_name": "DoubleMaStrategy",
        "params": {}, "auto_trade_enabled": True, "confirm_required": False,
    }
    runner._sim_accounts[account_id] = {
        "balance": balance, "available": balance,
        "frozen": 0, "initial_capital": balance,
    }
    runner._sim_positions[account_id] = {}
    db = SessionLocal()
    try:
        db.query(AutoTradeConfig).filter(
            AutoTradeConfig.account_id == account_id).delete()
        db.add(AutoTradeConfig(account_id=account_id, user_id="test-user",
                              auto_trade_enabled=True, confirm_required=False))
        db.commit()
    finally:
        db.close()
    return account_id


def _teardown(instance_id: str, account_id: str):
    runner._instances.pop(instance_id, None)
    runner._sim_accounts.pop(account_id, None)
    runner._sim_positions.pop(account_id, None)
    db = SessionLocal()
    try:
        db.query(Order).filter(Order.account_id == account_id).delete()
        db.query(AutoTradeConfig).filter(
            AutoTradeConfig.account_id == account_id).delete()
        db.query(StrategyLog).filter(
            StrategyLog.instance_id == instance_id).delete()
        db.commit()
    finally:
        db.close()


@pytest.mark.asyncio
async def test_live_signal_buy_auto_fills():
    """signal=1 + auto + no confirm → 模拟成交 + Order source=signal_auto_sim"""
    iid = "inst-buy"; aid = _setup_instance(iid)
    try:
        await runner._execute_live_signal_sim(
            iid, "600519", aid, signal=1, current_price=1680.0,
            config=runner._instances[iid], is_grid=False,
            position=0, avg_cost=0, signal_reason="test")
        assert runner._sim_accounts[aid]["available"] < 1_000_000
        assert runner._sim_positions[aid]["600519"]["quantity"] > 0

        db = SessionLocal()
        try:
            order = db.query(Order).filter(Order.account_id == aid).first()
            assert order is not None
            assert order.source == "signal_auto_sim"
            assert order.status == "filled"
        finally:
            db.close()
    finally:
        _teardown(iid, aid)


@pytest.mark.asyncio
async def test_live_signal_sell_auto_fills():
    """先 buy 建仓，再 signal=-1 → 卖出回款，pnl 对账"""
    iid = "inst-sell"; aid = _setup_instance(iid)
    try:
        # 建仓
        runner._update_sim_account_buy(aid, "600519", 100, 1680.0)
        bal_after_buy = runner._sim_accounts[aid]["balance"]
        # 卖出信号
        await runner._execute_live_signal_sim(
            iid, "600519", aid, signal=-1, current_price=1750.0,
            config=runner._instances[iid], is_grid=False,
            position=100, avg_cost=1680.0, signal_reason="test")

        revenue = 100 * 1750.0
        commission = max(revenue * 0.0003, 5)
        stamp_tax = revenue * 0.001
        expected = bal_after_buy + revenue - commission - stamp_tax
        assert runner._sim_accounts[aid]["balance"] == pytest.approx(expected, abs=1e-2)
        assert runner._sim_positions[aid]["600519"]["quantity"] == 0
    finally:
        _teardown(iid, aid)


@pytest.mark.asyncio
async def test_live_signal_buy_insufficient_funds():
    """资金不足: 不动账户、不落 Order"""
    iid = "inst-nofund"; aid = _setup_instance(iid, balance=1000)
    try:
        await runner._execute_live_signal_sim(
            iid, "600519", aid, signal=1, current_price=1680.0,
            config=runner._instances[iid], is_grid=False,
            position=0, avg_cost=0, signal_reason="test")
        assert runner._sim_accounts[aid]["available"] == 1000  # 未变
        assert "600519" not in runner._sim_positions[aid]
        db = SessionLocal()
        try:
            assert db.query(Order).filter(Order.account_id == aid).count() == 0
        finally:
            db.close()
    finally:
        _teardown(iid, aid)


@pytest.mark.asyncio
async def test_live_signal_sell_insufficient_position():
    """无仓位 sell: 拒绝，不动账户"""
    iid = "inst-nopos"; aid = _setup_instance(iid)
    try:
        await runner._execute_live_signal_sim(
            iid, "600519", aid, signal=-1, current_price=1680.0,
            config=runner._instances[iid], is_grid=False,
            position=0, avg_cost=0, signal_reason="test")
        assert runner._sim_accounts[aid]["available"] == 1_000_000
        db = SessionLocal()
        try:
            assert db.query(Order).filter(Order.account_id == aid).count() == 0
        finally:
            db.close()
    finally:
        _teardown(iid, aid)


@pytest.mark.asyncio
async def test_live_signal_confirm_required_creates_pending():
    """confirm_required=True → 落 signals 表 pending，不动账户"""
    from app.models.models import Signal
    iid = "inst-confirm"; aid = _setup_instance(iid)
    # 覆盖 AutoTradeConfig 为 confirm_required=True
    db = SessionLocal()
    try:
        cfg = db.query(AutoTradeConfig).filter(
            AutoTradeConfig.account_id == aid).first()
        cfg.confirm_required = True
        db.commit()
    finally:
        db.close()
    try:
        await runner._execute_live_signal_sim(
            iid, "600519", aid, signal=1, current_price=1680.0,
            config=runner._instances[iid], is_grid=False,
            position=0, avg_cost=0, signal_reason="test")
        # 账户未动
        assert runner._sim_accounts[aid]["available"] == 1_000_000
        # 落 signals pending
        db = SessionLocal()
        try:
            sig = db.query(Signal).filter(Signal.account_id == aid).first()
            assert sig is not None
            assert sig.status == "pending"
            assert sig.side == "buy"
        finally:
            db.close()
    finally:
        # 追加清理 signals
        db = SessionLocal()
        try:
            db.query(Signal).filter(Signal.account_id == aid).delete()
            db.commit()
        finally:
            db.close()
        _teardown(iid, aid)


@pytest.mark.asyncio
async def test_live_signal_risk_manager_rejects():
    """risk_manager max_order_value 拒绝信号成交"""
    from app.core.risk_manager import risk_manager, RiskConfig
    iid = "inst-risk"; aid = _setup_instance(iid)
    risk_manager.set_config(aid, RiskConfig(max_order_value=10000))
    try:
        # 100*1680 = 168000 > 10000 → 风控拒
        await runner._execute_live_signal_sim(
            iid, "600519", aid, signal=1, current_price=1680.0,
            config=runner._instances[iid], is_grid=False,
            position=0, avg_cost=0, signal_reason="test")
        assert runner._sim_accounts[aid]["available"] == 1_000_000
        db = SessionLocal()
        try:
            assert db.query(Order).filter(Order.account_id == aid).count() == 0
        finally:
            db.close()
    finally:
        risk_manager.set_config(aid, RiskConfig())  # 清风控
        _teardown(iid, aid)


@pytest.mark.asyncio
async def test_sim_account_persistence_roundtrip():
    """save → load 往返: balance/available/positions 一致"""
    from app.models.models import TradingInstance
    iid = "inst-persist"; aid = _setup_instance(iid)
    try:
        runner._update_sim_account_buy(aid, "600519", 100, 1680.0)
        # 需 TradingInstance 行供 save_sim_account_to_db 写
        db = SessionLocal()
        try:
            db.query(TradingInstance).filter(
                TradingInstance.id == iid).delete()
            db.add(TradingInstance(
                id=iid, user_id="test-user", name="t", symbol="600519",
                strategy_id="s1", account_id="broker-x", mode="live"))
            db.commit()
        finally:
            db.close()

        runner.save_sim_account_to_db(iid)
        saved_balance = runner._sim_accounts[aid]["balance"]
        saved_qty = runner._sim_positions[aid]["600519"]["quantity"]

        # 清内存再 load
        runner._sim_accounts.pop(aid, None)
        runner._sim_positions.pop(aid, None)
        runner.load_sim_account_from_db(iid)

        assert runner._sim_accounts[aid]["balance"] == pytest.approx(saved_balance, abs=1e-2)
        assert runner._sim_positions[aid]["600519"]["quantity"] == saved_qty
    finally:
        db = SessionLocal()
        try:
            db.query(TradingInstance).filter(
                TradingInstance.id == iid).delete()
            db.commit()
        finally:
            db.close()
        _teardown(iid, aid)

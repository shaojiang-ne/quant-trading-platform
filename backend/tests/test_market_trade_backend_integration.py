"""live/simulation 账户统一 与 信号执行集成测试"""
import asyncio
from unittest.mock import patch

import pytest
from app.services.vnpy_strategy_runner import vnpy_strategy_runner as runner


def test_get_account_id_live_uses_sim_prefix():
    """live 模式 account_id 也用 sim-{instance_id} 前缀"""
    runner._instances["inst-live-1"] = {
        "mode": "live", "account_id": "broker-acct-123",
        "symbol": "600519", "strategy_id": "s1",
    }
    try:
        aid = runner._get_account_id("inst-live-1")
        assert aid == "sim-inst-live-1"
    finally:
        runner._instances.pop("inst-live-1", None)


def test_get_account_id_simulation_uses_sim_prefix():
    runner._instances["inst-sim-1"] = {
        "mode": "simulation", "account_id": "x",
        "symbol": "600519", "strategy_id": "s1",
    }
    try:
        assert runner._get_account_id("inst-sim-1") == "sim-inst-sim-1"
    finally:
        runner._instances.pop("inst-sim-1", None)


@pytest.mark.asyncio
async def test_subscribe_poll_updates_current_prices():
    """订阅 → 轮询一轮 → callback 被调用收到正确 tick"""
    from app.services.market_service import market_service

    received = []
    seq = market_service.subscribe_quote(
        "600519", callback=lambda t: received.append(t))

    fake_snap = {"600519": {"name": "贵州茅台", "price": 1680.0,
                            "change_pct": 1.0, "turnover_pct": 0.5,
                            "pe_ttm": 30, "pb": 10, "float_mcap_yi": 21000,
                            "vol_ratio": 1.1, "amount_wan": 50000}}

    # 今天可能非交易时间，patch is_trading_time=True 让 _poll_once 真正执行
    with patch("app.services.trading_calendar_service.trading_calendar.is_trading_time",
               return_value=True):
        with patch("app.core.market_backend.AkshareMarketBackend._fetch_snapshot",
                   return_value=fake_snap):
            await market_service._backend._poll_once()

    assert len(received) == 1
    assert received[0]["lastPrice"] == 1680.0
    market_service.unsubscribe_quote(seq)
    market_service.close()


@pytest.mark.asyncio
async def test_live_signal_executes_sim_trade():
    """live 模式 auto_trade 信号走模拟成交，账户变化"""
    from app.models.models import AutoTradeConfig
    from app.database import SessionLocal

    instance_id = "inst-test-live"
    account_id = f"sim-{instance_id}"
    runner._instances[instance_id] = {
        "mode": "live", "account_id": "broker-x",
        "symbol": "600519", "strategy_id": "s1",
        "initial_equity": 1000000, "class_name": "DoubleMaStrategy",
        "params": {}, "auto_trade_enabled": True, "confirm_required": False,
    }
    runner._sim_accounts[account_id] = {
        "balance": 1000000, "available": 1000000,
        "frozen": 0, "initial_capital": 1000000,
    }
    runner._sim_positions[account_id] = {}

    # 注入 AutoTradeConfig（auto_trade_enabled=True, confirm_required=False）
    db = SessionLocal()
    try:
        # 先清理可能残留的同 account_id 配置
        db.query(AutoTradeConfig).filter(
            AutoTradeConfig.account_id == account_id).delete()
        cfg = AutoTradeConfig(account_id=account_id, user_id="test-user",
                              auto_trade_enabled=True,
                              confirm_required=False)
        db.add(cfg)
        db.commit()
    finally:
        db.close()

    try:
        # 执行买入信号（非网格，position=0 → 按 90% 资金整手买）
        await runner._execute_live_signal_sim(
            instance_id, "600519", account_id, signal=1,
            current_price=1680.0, config=runner._instances[instance_id],
            is_grid=False, position=0, avg_cost=0,
            signal_reason="test",
        )
        # 账户可用资金应减少
        assert runner._sim_accounts[account_id]["available"] < 1000000
        assert runner._sim_positions[account_id]["600519"]["quantity"] > 0
    finally:
        # 清理
        runner._instances.pop(instance_id, None)
        runner._sim_accounts.pop(account_id, None)
        runner._sim_positions.pop(account_id, None)
        db = SessionLocal()
        try:
            db.query(AutoTradeConfig).filter(
                AutoTradeConfig.account_id == account_id).delete()
            db.commit()
        finally:
            db.close()

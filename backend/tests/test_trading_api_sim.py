"""/trading/order API 端到端测试（打桩 broker 转发 SimTradeBackend）"""
import pytest
from fastapi.testclient import TestClient

from app.main import app
from app.api import trading
from app.api.trading import get_broker
from app.core.trade_backend import SimTradeBackend
from app.core.broker_provider import BrokerProvider, BrokerAccount
from app.core.risk_manager import risk_manager, RiskConfig
from app.services.vnpy_strategy_runner import vnpy_strategy_runner as runner
from app.services.auth_service import get_current_user
from app.models.models import User, Order
from app.database import SessionLocal


class SimBrokerProvider(BrokerProvider):
    """把 BrokerProvider 接口转发到 SimTradeBackend"""
    def __init__(self, account_id: str):
        self._backend = SimTradeBackend(account_id=account_id)
        self._connected = True
        self._account_id = account_id

    def get_name(self): return "sim"
    def get_display_name(self): return "模拟成交"
    def is_available(self): return True
    def is_connected(self): return self._connected

    @property
    def account_id(self): return self._account_id

    async def connect(self, **kw):
        self._connected = True
        return {"success": True, "account_id": self._account_id}

    async def disconnect(self):
        self._connected = False

    async def get_account(self) -> BrokerAccount:
        acct = await self._backend.get_account()
        return BrokerAccount(
            total_assets=acct["total_assets"], cash=acct["cash"],
            available=acct["available_cash"], market_value=acct["market_value"],
            account_id=self._account_id)

    async def get_positions(self): return await self._backend.get_positions()
    async def get_orders(self): return await self._backend.get_orders()
    async def get_trades(self): return await self._backend.get_trades()

    async def place_order(self, symbol, direction, price, volume, order_type="limit"):
        return await self._backend.place_order(
            symbol, direction, volume, price=price, order_type=order_type)

    async def cancel_order(self, order_id):
        return await self._backend.cancel_order(order_id)


def _setup_account(account_id: str, balance: float = 1_000_000):
    runner._sim_accounts[account_id] = {
        "balance": balance, "available": balance,
        "frozen": 0, "initial_capital": balance}
    runner._sim_positions[account_id] = {}


@pytest.fixture
def api_client(monkeypatch):
    """打桩 broker + 跳过认证"""
    aid = "sim-api-client"
    _setup_account(aid)
    broker = SimBrokerProvider(aid)
    monkeypatch.setattr(trading, "get_broker", lambda name=None: broker)
    monkeypatch.setattr(trading, "_active_broker", broker)

    # 跳过 get_current_user：override 返回一个内存 User
    # User 模型 email / hashed_password 为非空列，构造时必须提供
    fake_user = User(
        id="test-user", username="tester",
        email="tester@example.com", hashed_password="x",
        is_active=True,
    )

    def _override():
        return fake_user
    app.dependency_overrides[get_current_user] = _override
    client = TestClient(app)
    yield client, aid, broker
    app.dependency_overrides.clear()
    runner._sim_accounts.pop(aid, None)
    runner._sim_positions.pop(aid, None)
    db = SessionLocal()
    try:
        db.query(Order).filter(Order.account_id == aid).delete()
        db.commit()
    finally:
        db.close()


def test_order_rejects_non_round_lot(api_client):
    """非 100 整数倍 → 400"""
    client, aid, _ = api_client
    resp = client.post("/api/trading/order", json={
        "symbol": "600519", "side": "buy", "quantity": 150, "price": 1680.0})
    assert resp.status_code == 400
    assert "100" in resp.json()["detail"]


def test_order_star_688_allows_non_round_lot(api_client):
    """科创板 688 非整手通过"""
    client, aid, _ = api_client
    _setup_account(aid)  # 确保资金充足
    resp = client.post("/api/trading/order", json={
        "symbol": "688981", "side": "buy", "quantity": 1, "price": 100.0})
    assert resp.status_code == 200
    assert resp.json()["success"] is True


def test_order_rejects_when_not_connected(api_client):
    """broker 未连接 → 400"""
    client, aid, broker = api_client
    broker._connected = False
    resp = client.post("/api/trading/order", json={
        "symbol": "600519", "side": "buy", "quantity": 100, "price": 1680.0})
    assert resp.status_code == 400
    assert "未连接" in resp.json()["detail"]


def test_order_success_records_to_db(api_client):
    """下单成功落 orders 表 source=manual status=submitted

    注意：SimTradeBackend.place_order 内部 _record_order 也会写一行 Order，
    其 id 即响应返回的 order_id，source=sim_live status=filled。
    API 端点另写一行 source=manual status=submitted，其 id 是新生成的 uuid，
    gateway_order_id 指向响应 order_id。故此处按 gateway_order_id + source=manual
    精确定位 API 写入的那一行。
    """
    client, aid, _ = api_client
    _setup_account(aid)
    resp = client.post("/api/trading/order", json={
        "symbol": "600519", "side": "buy", "quantity": 100, "price": 1680.0})
    assert resp.status_code == 200
    order_id = resp.json()["order_id"]
    db = SessionLocal()
    try:
        order = db.query(Order).filter(
            Order.gateway_order_id == order_id,
            Order.source == "manual",
        ).first()
        assert order is not None
        assert order.source == "manual"
        assert order.status == "submitted"
        # API 经 _normalize_symbol 把 600519 标准化为 600519.SH 后落库
        assert order.symbol == "600519.SH"
    finally:
        db.close()


def test_order_risk_manager_rejects(api_client, monkeypatch):
    """max_order_value 风控 → 400"""
    client, aid, _ = api_client
    _setup_account(aid)
    risk_manager.set_config(aid, RiskConfig(max_order_value=10000))
    try:
        resp = client.post("/api/trading/order", json={
            "symbol": "600519", "side": "buy", "quantity": 100, "price": 1680.0})
        assert resp.status_code == 400
        assert "风控" in resp.json()["detail"]
        # 不落库
        db = SessionLocal()
        try:
            assert db.query(Order).filter(Order.account_id == aid).count() == 0
        finally:
            db.close()
    finally:
        risk_manager.set_config(aid, RiskConfig())

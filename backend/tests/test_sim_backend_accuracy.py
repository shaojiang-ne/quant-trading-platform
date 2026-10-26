"""SimTradeBackend 单元精度对账测试"""
import pytest
from datetime import date, timedelta

from app.core.trade_backend import SimTradeBackend
from app.services.vnpy_strategy_runner import vnpy_strategy_runner as runner


@pytest.fixture(autouse=True)
def _cleanup_sim_acc_orders():
    """每个用例后清理 sim-acc-* 账户的 Order 行（place_order 的 _record_order 副作用）"""
    yield
    from app.database import SessionLocal
    from app.models.models import Order
    db = SessionLocal()
    try:
        db.query(Order).filter(Order.account_id.like('sim-acc-%')).delete()
        db.commit()
    except Exception:
        db.rollback()
    finally:
        db.close()


def _setup_sim_account(account_id: str, balance: float = 1_000_000):
    runner._sim_accounts[account_id] = {
        "balance": balance, "available": balance,
        "initial_capital": balance,
    }
    runner._sim_positions[account_id] = {}
    runner._sim_buy_dates.setdefault(account_id, {})
    return account_id


@pytest.mark.asyncio
async def test_buy_single_exact_deduction():
    """买入单笔: available/avg_cost/market_value 精确对账"""
    aid = _setup_sim_account("sim-acc-buy-single")
    try:
        backend = SimTradeBackend(account_id=aid)
        qty, price = 100, 1680.0
        result = await backend.place_order("600519", "buy", qty, price=price)
        assert result["success"] is True

        acct = runner._sim_accounts[aid]
        cost = qty * price
        commission = max(cost * 0.0003, 5)
        assert acct["available"] == pytest.approx(1_000_000 - cost - commission, abs=1e-2)
        assert acct["balance"] == pytest.approx(1_000_000 - cost - commission, abs=1e-2)

        pos = runner._sim_positions[aid]["600519"]
        assert pos["quantity"] == 100
        assert pos["avg_cost"] == pytest.approx(price, abs=1e-2)
        assert pos["market_value"] == pytest.approx(qty * price, abs=1e-2)
    finally:
        runner._sim_accounts.pop(aid, None)
        runner._sim_positions.pop(aid, None)
        runner._sim_buy_dates.pop(aid, None)


@pytest.mark.asyncio
async def test_buy_min_commission_5_yuan():
    """小额下单: cost*0.0003 < 5 时佣金取 5 元"""
    aid = _setup_sim_account("sim-acc-min-comm", balance=100_000)
    try:
        backend = SimTradeBackend(account_id=aid)
        # 100 股 * 10 元 = 1000 元，0.0003 = 0.3 < 5 → 佣金 5
        result = await backend.place_order("600000", "buy", 100, price=10.0)
        assert result["success"] is True

        acct = runner._sim_accounts[aid]
        cost = 100 * 10.0
        commission = 5  # max(0.3, 5)
        assert acct["available"] == pytest.approx(100_000 - cost - 5, abs=1e-2)
    finally:
        runner._sim_accounts.pop(aid, None)
        runner._sim_positions.pop(aid, None)
        runner._sim_buy_dates.pop(aid, None)


@pytest.mark.asyncio
async def test_buy_twice_weighted_avg_cost():
    """两次不同价买入: avg_cost 加权"""
    aid = _setup_sim_account("sim-acc-weighted", balance=1_000_000)
    try:
        backend = SimTradeBackend(account_id=aid)
        await backend.place_order("600519", "buy", 100, price=1680.0)
        await backend.place_order("600519", "buy", 200, price=1700.0)

        pos = runner._sim_positions[aid]["600519"]
        assert pos["quantity"] == 300
        expected_avg = (100 * 1680.0 + 200 * 1700.0) / 300
        assert pos["avg_cost"] == pytest.approx(expected_avg, abs=1e-2)

        # 资金扣两次，佣金各 max(cost*0.0003,5)
        c1 = max(100 * 1680.0 * 0.0003, 5)
        c2 = max(200 * 1700.0 * 0.0003, 5)
        expected_avail = 1_000_000 - 100 * 1680.0 - c1 - 200 * 1700.0 - c2
        assert runner._sim_accounts[aid]["available"] == pytest.approx(expected_avail, abs=1e-2)
    finally:
        runner._sim_accounts.pop(aid, None)
        runner._sim_positions.pop(aid, None)
        runner._sim_buy_dates.pop(aid, None)


@pytest.mark.asyncio
async def test_sell_single_exact_revenue():
    """卖出: balance += revenue - 佣金 - 印花税，持仓归零 avg_cost 归零"""
    aid = _setup_sim_account("sim-acc-sell", balance=1_000_000)
    try:
        backend = SimTradeBackend(account_id=aid)
        await backend.place_order("600519", "buy", 100, price=1680.0)
        balance_after_buy = runner._sim_accounts[aid]["balance"]

        # 模拟次日以绕过 T+1
        runner._sim_buy_dates[aid]["600519"] = date.today() - timedelta(days=1)

        result = await backend.place_order("600519", "sell", 100, price=1750.0)
        assert result["success"] is True

        revenue = 100 * 1750.0
        commission = max(revenue * 0.0003, 5)
        stamp_tax = revenue * 0.001
        expected_balance = balance_after_buy + revenue - commission - stamp_tax
        acct = runner._sim_accounts[aid]
        assert acct["balance"] == pytest.approx(expected_balance, abs=1e-2)
        assert acct["available"] == pytest.approx(expected_balance, abs=1e-2)

        pos = runner._sim_positions[aid]["600519"]
        assert pos["quantity"] == 0
        assert pos["avg_cost"] == 0
    finally:
        runner._sim_accounts.pop(aid, None)
        runner._sim_positions.pop(aid, None)
        runner._sim_buy_dates.pop(aid, None)


@pytest.mark.asyncio
async def test_sell_high_value_stamp_tax():
    """高价股平价买卖往返: 净亏 = 2*佣金 + 印花税；印花税独立可观测(>5)"""
    aid = _setup_sim_account("sim-acc-stamp", balance=5_000_000)
    try:
        backend = SimTradeBackend(account_id=aid)
        await backend.place_order("600519", "buy", 100, price=1680.0)
        # 模拟次日以绕过 T+1
        runner._sim_buy_dates[aid]["600519"] = date.today() - timedelta(days=1)
        await backend.place_order("600519", "sell", 100, price=1680.0)  # 平价卖出
        bal_sell = runner._sim_accounts[aid]["balance"]

        revenue = 100 * 1680.0
        commission = max(revenue * 0.0003, 5)  # 50.4（>5，比例佣金分支）
        stamp_tax = revenue * 0.001  # 168
        # 平价往返：买入扣 cost+佣金，卖出回 revenue-佣金-印花税
        # 平价时 revenue==cost，净亏 = 2*佣金 + 印花税
        assert bal_sell == pytest.approx(5_000_000 - 2 * commission - stamp_tax, abs=1e-2)
        # 印花税 > 5，确保没被最低佣金吞
        assert stamp_tax > 5
    finally:
        runner._sim_accounts.pop(aid, None)
        runner._sim_positions.pop(aid, None)
        runner._sim_buy_dates.pop(aid, None)


@pytest.mark.asyncio
async def test_get_account_total_assets_formula():
    """get_account: total_assets = balance + Σ market_value"""
    aid = _setup_sim_account("sim-acc-ta", balance=1_000_000)
    try:
        backend = SimTradeBackend(account_id=aid)
        await backend.place_order("600519", "buy", 100, price=1680.0)
        acct = await backend.get_account()
        pos = runner._sim_positions[aid]["600519"]
        assert acct["market_value"] == pytest.approx(pos["market_value"], abs=1e-2)
        assert acct["cash"] == pytest.approx(runner._sim_accounts[aid]["balance"], abs=1e-2)
        assert acct["total_assets"] == pytest.approx(
            acct["cash"] + acct["market_value"], abs=1e-2)
    finally:
        runner._sim_accounts.pop(aid, None)
        runner._sim_positions.pop(aid, None)
        runner._sim_buy_dates.pop(aid, None)


@pytest.mark.asyncio
async def test_get_positions_pnl_formula():
    """get_positions: pnl = (current_price - avg_cost) * quantity"""
    aid = _setup_sim_account("sim-acc-pnl", balance=1_000_000)
    try:
        backend = SimTradeBackend(account_id=aid)
        await backend.place_order("600519", "buy", 100, price=1680.0)
        # 改 current_price 模拟浮盈
        runner._sim_positions[aid]["600519"]["current_price"] = 1750.0
        runner._sim_positions[aid]["600519"]["market_value"] = 100 * 1750.0
        positions = await backend.get_positions()
        assert len(positions) == 1
        p = positions[0]
        assert p["symbol"] == "600519"
        assert p["pnl"] == pytest.approx((1750.0 - 1680.0) * 100, abs=1e-2)
    finally:
        runner._sim_accounts.pop(aid, None)
        runner._sim_positions.pop(aid, None)
        runner._sim_buy_dates.pop(aid, None)


@pytest.mark.asyncio
async def test_edge_price_zero_rejected():
    """price<=0 返回需指定价格"""
    aid = _setup_sim_account("sim-acc-edge0")
    try:
        backend = SimTradeBackend(account_id=aid)
        result = await backend.place_order("600519", "buy", 100, price=0)
        assert result["success"] is False
        assert "价格" in result["error"]
    finally:
        runner._sim_accounts.pop(aid, None)
        runner._sim_positions.pop(aid, None)
        runner._sim_buy_dates.pop(aid, None)


@pytest.mark.asyncio
async def test_edge_unknown_side_rejected():
    """未知 side 返回不支持"""
    aid = _setup_sim_account("sim-acc-edge-side")
    try:
        backend = SimTradeBackend(account_id=aid)
        result = await backend.place_order("600519", "hold", 100, price=10.0)
        assert result["success"] is False
        assert "不支持" in result["error"]
    finally:
        runner._sim_accounts.pop(aid, None)
        runner._sim_positions.pop(aid, None)
        runner._sim_buy_dates.pop(aid, None)


@pytest.mark.asyncio
async def test_cancel_order_unsupported():
    """模拟成交不支持撤单"""
    backend = SimTradeBackend(account_id="sim-acc-cancel")
    result = await backend.cancel_order("any-id")
    assert result["success"] is False
    assert "撤单" in result["error"]


@pytest.mark.asyncio
async def test_disconnect_clears_connected():
    backend = SimTradeBackend(account_id="sim-acc-disc")
    await backend.auto_connect()
    assert backend.is_connected is True
    await backend.disconnect()
    assert backend.is_connected is False


@pytest.mark.asyncio
async def test_order_recorded_to_db():
    """place_order 落 orders 表: source=sim_live status=filled"""
    from app.database import SessionLocal
    from app.models.models import Order
    aid = _setup_sim_account("sim-acc-db", balance=1_000_000)
    backend = SimTradeBackend(account_id=aid)
    result = await backend.place_order("600519", "buy", 100, price=1680.0)
    order_id = result["order_id"]
    try:
        db = SessionLocal()
        try:
            order = db.query(Order).filter(Order.id == order_id).first()
            assert order is not None
            assert order.account_id == aid
            assert order.symbol == "600519"
            assert order.side == "buy"
            assert order.source == "sim_live"
            assert order.status == "filled"
            assert order.filled_quantity == 100
            assert float(order.filled_price) == pytest.approx(1680.0, abs=1e-2)
        finally:
            db.close()
    finally:
        # 清理 DB 行
        db = SessionLocal()
        try:
            db.query(Order).filter(Order.account_id == aid).delete()
            db.commit()
        finally:
            db.close()
        runner._sim_accounts.pop(aid, None)
        runner._sim_positions.pop(aid, None)
        runner._sim_buy_dates.pop(aid, None)


@pytest.mark.asyncio
async def test_get_account_uninitialized_zero_structure():
    """未初始化账户 get_account 返回零结构不抛异常"""
    backend = SimTradeBackend(account_id="sim-acc-noinit")
    acct = await backend.get_account()
    assert acct["cash"] == 0
    assert acct["total_assets"] == 0
    assert acct["market_value"] == 0

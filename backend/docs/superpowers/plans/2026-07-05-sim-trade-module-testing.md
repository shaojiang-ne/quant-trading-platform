# 模拟交易模块完整测试 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 为模拟交易模块补齐 30+ 真实准确测试，覆盖 SimTradeBackend 单元精度 / 实盘信号链路 / LiveGateway 后端切换 / API 端到端四层。

**Architecture:** 三个独立测试文件按层拆分，复用现有 `_setup_sim_account`/instance 注入模式。金额用 `pytest.approx` 浮点近似，DB 走真实远程 MySQL 往返，行情用合成数据，每例独立 account_id + try/finally 清理。不改产品代码。

**Tech Stack:** pytest + pytest-asyncio (asyncio_mode=auto) + SQLAlchemy + fastapi.TestClient + httpx

**Spec:** `docs/superpowers/specs/2026-07-05-sim-trade-module-testing-design.md`

**前置环境:** venv (非 anaconda)，vnpy 4.3.0，远程 MySQL 可达。所有命令在 `backend/` 下用 `source venv/Scripts/activate && python -m pytest ...` 运行。

---

## 共用约定

### account_id 命名
- 文件1: `sim-acc-<测试名>` (纯内存，无 instance)
- 文件2: `sim-inst-<测试名>` (带 instance_id，`_get_account_id` 产出 `sim-inst-<测试名>`)
- 文件3: `sim-api-<测试名>` (打桩 broker 转发 SimTradeBackend)

### 清理铁律
每个用例 try/finally 必须清理：
```python
runner._sim_accounts.pop(account_id, None)
runner._sim_positions.pop(account_id, None)
runner._instances.pop(instance_id, None)
# DB 行清理：按 account_id 删 orders/signals/auto_trade_configs/trading_instances
```

### 财务断言
所有金额断言用 `pytest.approx(value, abs=1e-2)`。

---

## 文件结构

- Create: `tests/test_sim_backend_accuracy.py` — SimTradeBackend 单元精度层（Task 1-4）
- Create: `tests/test_live_signal_sim_full.py` — 实盘信号链路层（Task 5-8）
- Create: `tests/test_trading_api_sim.py` — API 端到端打桩层（Task 9-11）

---

## Task 1: 文件1骨架 + 买入精度对账

**Files:**
- Create: `tests/test_sim_backend_accuracy.py`

- [ ] **Step 1: 写失败测试**

```python
"""SimTradeBackend 单元精度对账测试"""
import pytest

from app.core.trade_backend import SimTradeBackend
from app.services.vnpy_strategy_runner import vnpy_strategy_runner as runner


def _setup_sim_account(account_id: str, balance: float = 1_000_000):
    runner._sim_accounts[account_id] = {
        "balance": balance, "available": balance,
        "frozen": 0, "initial_capital": balance,
    }
    runner._sim_positions[account_id] = {}
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
```

- [ ] **Step 2: 跑测试确认通过**

Run: `python -m pytest tests/test_sim_backend_accuracy.py::test_buy_single_exact_deduction -v`
Expected: PASS（产品代码已实现，验证精度对账成立）

- [ ] **Step 3: Commit**

```bash
git add tests/test_sim_backend_accuracy.py
git commit -m "test: SimTradeBackend 买入单笔精度对账"
```

---

## Task 2: 买入佣金最低5元 + 加权成本

**Files:**
- Modify: `tests/test_sim_backend_accuracy.py` (追加用例)

- [ ] **Step 1: 追加两个失败测试**

在文件末尾追加：

```python
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
```

- [ ] **Step 2: 跑测试确认通过**

Run: `python -m pytest tests/test_sim_backend_accuracy.py -v -k "min_commission or weighted"`
Expected: PASS

- [ ] **Step 3: Commit**

```bash
git add tests/test_sim_backend_accuracy.py
git commit -m "test: SimTradeBackend 最低佣金5元 + 加权平均成本"
```

---

## Task 3: 卖出精度对账（佣金+印花税）

**Files:**
- Modify: `tests/test_sim_backend_accuracy.py`

- [ ] **Step 1: 追加卖出对账测试**

```python
@pytest.mark.asyncio
async def test_sell_single_exact_revenue():
    """卖出: balance += revenue - 佣金 - 印花税，持仓归零 avg_cost 归零"""
    aid = _setup_sim_account("sim-acc-sell", balance=1_000_000)
    try:
        backend = SimTradeBackend(account_id=aid)
        await backend.place_order("600519", "buy", 100, price=1680.0)
        balance_after_buy = runner._sim_accounts[aid]["balance"]

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


@pytest.mark.asyncio
async def test_sell_high_value_stamp_tax():
    """高价股卖出: 印花税与佣金分别可观测（非被 5 元最低吞）"""
    aid = _setup_sim_account("sim-acc-stamp", balance=5_000_000)
    try:
        backend = SimTradeBackend(account_id=aid)
        await backend.place_order("600519", "buy", 100, price=1680.0)
        bal_buy = runner._sim_accounts[aid]["balance"]
        await backend.place_order("600519", "sell", 100, price=1680.0)  # 平价卖出
        bal_sell = runner._sim_accounts[aid]["balance"]

        revenue = 100 * 1680.0
        commission = max(revenue * 0.0003, 5)  # 50.4
        stamp_tax = revenue * 0.001  # 168
        # 两次佣金 + 印花税 = 净亏
        assert bal_sell == pytest.approx(bal_buy - commission - stamp_tax, abs=1e-2)
        # 印花税 > 5，确保没被最低佣金吞
        assert stamp_tax > 5
    finally:
        runner._sim_accounts.pop(aid, None)
        runner._sim_positions.pop(aid, None)
```

- [ ] **Step 2: 跑测试确认通过**

Run: `python -m pytest tests/test_sim_backend_accuracy.py -v -k "sell"`
Expected: PASS

- [ ] **Step 3: Commit**

```bash
git add tests/test_sim_backend_accuracy.py
git commit -m "test: SimTradeBackend 卖出佣金+印花税精度对账"
```

---

## Task 4: get_account/get_positions 公式 + 边缘 + Order落库

**Files:**
- Modify: `tests/test_sim_backend_accuracy.py`

- [ ] **Step 1: 追加公式验证 + 边缘 + 落库测试**

```python
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
```

- [ ] **Step 2: 跑文件1全部通过**

Run: `python -m pytest tests/test_sim_backend_accuracy.py -v`
Expected: 11 PASS

- [ ] **Step 3: Commit**

```bash
git add tests/test_sim_backend_accuracy.py
git commit -m "test: SimTradeBackend get_account/pnl公式 + 边缘 + Order落库"
```

---

## Task 5: 文件2骨架 + 信号 buy/sell 自动成交

**Files:**
- Create: `tests/test_live_signal_sim_full.py`

- [ ] **Step 1: 写 buy + sell 信号测试**

```python
"""实盘信号→模拟成交链路全分支测试"""
import pytest

from app.services.vnpy_strategy_runner import vnpy_strategy_runner as runner
from app.database import SessionLocal
from app.models.models import AutoTradeConfig, Order


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
```

- [ ] **Step 2: 跑测试确认通过**

Run: `python -m pytest tests/test_live_signal_sim_full.py -v`
Expected: 2 PASS

- [ ] **Step 3: Commit**

```bash
git add tests/test_live_signal_sim_full.py
git commit -m "test: 实盘信号 buy/sell 自动模拟成交链路"
```

---

## Task 6: 资金不足 + 持仓不足拒绝

**Files:**
- Modify: `tests/test_live_signal_sim_full.py`

- [ ] **Step 1: 追加拒绝测试**

```python
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
```

- [ ] **Step 2: 跑测试确认通过**

Run: `python -m pytest tests/test_live_signal_sim_full.py -v -k "insufficient"`
Expected: 2 PASS

- [ ] **Step 3: Commit**

```bash
git add tests/test_live_signal_sim_full.py
git commit -m "test: 实盘信号资金/持仓不足拒绝路径"
```

---

## Task 7: confirm_required 信号待确认

**Files:**
- Modify: `tests/test_live_signal_sim_full.py`

- [ ] **Step 1: 追加信号待确认测试**

```python
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
```

- [ ] **Step 2: 跑测试确认通过**

Run: `python -m pytest tests/test_live_signal_sim_full.py::test_live_signal_confirm_required_creates_pending -v`
Expected: PASS

- [ ] **Step 3: Commit**

```bash
git add tests/test_live_signal_sim_full.py
git commit -m "test: confirm_required 信号待确认落 signals 表"
```

---

## Task 8: 风控集成 + 持久化往返

**Files:**
- Modify: `tests/test_live_signal_sim_full.py`

- [ ] **Step 1: 追加风控 + 持久化测试**

```python
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
```

- [ ] **Step 2: 跑文件2全部通过**

Run: `python -m pytest tests/test_live_signal_sim_full.py -v`
Expected: 7 PASS

- [ ] **Step 3: Commit**

```bash
git add tests/test_live_signal_sim_full.py
git commit -m "test: 风控集成拒绝 + 模拟账户持久化往返"
```

---

## Task 9: 文件3骨架 + fake broker 桥接 SimTradeBackend

**Files:**
- Create: `tests/test_trading_api_sim.py`

- [ ] **Step 1: 写 fake broker + 整手校验测试**

```python
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
    fake_user = User(id="test-user", username="tester", is_active=True)

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
    resp = client.post("/api/v1/trading/order", json={
        "symbol": "600519", "side": "buy", "quantity": 150, "price": 1680.0})
    assert resp.status_code == 400
    assert "100" in resp.json()["detail"]


def test_order_star_688_allows_non_round_lot(api_client):
    """科创板 688 非整手通过"""
    client, aid, _ = api_client
    _setup_account(aid)  # 确保资金充足
    resp = client.post("/api/v1/trading/order", json={
        "symbol": "688981", "side": "buy", "quantity": 1, "price": 100.0})
    assert resp.status_code == 200
    assert resp.json()["success"] is True
```

- [ ] **Step 2: 跑测试确认通过**

Run: `python -m pytest tests/test_trading_api_sim.py -v`
Expected: 2 PASS

> 注意：若 688 用例因资金不足失败，确认 `_setup_account` 在用例内重新调用且 balance 够买 1 股*100元。

- [ ] **Step 3: Commit**

```bash
git add tests/test_trading_api_sim.py
git commit -m "test: /trading/order 整手校验 + 科创板（打桩 broker 走 sim）"
```

---

## Task 10: API 未连接拒单 + 下单成功落库

**Files:**
- Modify: `tests/test_trading_api_sim.py`

- [ ] **Step 1: 追加未连接 + 成功落库测试**

```python
def test_order_rejects_when_not_connected(api_client):
    """broker 未连接 → 400"""
    client, aid, broker = api_client
    broker._connected = False
    resp = client.post("/api/v1/trading/order", json={
        "symbol": "600519", "side": "buy", "quantity": 100, "price": 1680.0})
    assert resp.status_code == 400
    assert "未连接" in resp.json()["detail"]


def test_order_success_records_to_db(api_client):
    """下单成功落 orders 表 source=manual status=submitted"""
    client, aid, _ = api_client
    _setup_account(aid)
    resp = client.post("/api/v1/trading/order", json={
        "symbol": "600519", "side": "buy", "quantity": 100, "price": 1680.0})
    assert resp.status_code == 200
    order_id = resp.json()["order_id"]
    db = SessionLocal()
    try:
        order = db.query(Order).filter(Order.id == order_id).first()
        assert order is not None
        assert order.source == "manual"
        assert order.status == "submitted"
        assert order.symbol == "600519"
    finally:
        db.close()
```

- [ ] **Step 2: 跑测试确认通过**

Run: `python -m pytest tests/test_trading_api_sim.py -v`
Expected: 4 PASS

- [ ] **Step 3: Commit**

```bash
git add tests/test_trading_api_sim.py
git commit -m "test: /trading/order 未连接拒单 + 成功落库 source=manual"
```

---

## Task 11: API 风控拒绝 + 全量回归

**Files:**
- Modify: `tests/test_trading_api_sim.py`

- [ ] **Step 1: 追加风控拒绝测试**

```python
def test_order_risk_manager_rejects(api_client, monkeypatch):
    """max_order_value 风控 → 400"""
    client, aid, _ = api_client
    _setup_account(aid)
    risk_manager.set_config(aid, RiskConfig(max_order_value=10000))
    try:
        resp = client.post("/api/v1/trading/order", json={
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
```

- [ ] **Step 2: 跑文件3全部通过**

Run: `python -m pytest tests/test_trading_api_sim.py -v`
Expected: 5 PASS

- [ ] **Step 3: 全量回归**

Run: `python -m pytest tests/test_sim_backend_accuracy.py tests/test_live_signal_sim_full.py tests/test_trading_api_sim.py -v -m "not slow"`
Expected: 全部 PASS（约 23 用例）

- [ ] **Step 4: 确认未污染现有测试**

Run: `python -m pytest tests/test_sim_trade_backend.py tests/test_market_trade_backend_integration.py -v -m "not slow"`
Expected: 现有 15 用例仍全 PASS

- [ ] **Step 5: Commit**

```bash
git add tests/test_trading_api_sim.py
git commit -m "test: /trading/order 风控拒绝 + 全量回归

新增 23 用例覆盖 SimTradeBackend 单元精度/信号链路/API 端到端三层。
未改产品代码，broker_provider 路径缺口在报告中标注。

Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>"
```

---

## 自查清单

- [x] Spec 全部 4 层有对应 Task：单元精度(Task1-4) / 信号链路(Task5-8) / LiveGateway 切换(已由现有 test_sim_trade_backend.py 覆盖，不重复) / API 端到端(Task9-11)
- [x] 无占位符：每步含完整代码与命令
- [x] 类型/方法名一致：`_setup_sim_account`/`_setup_instance`/`_teardown`/`SimBrokerProvider` 全程同名
- [x] Order source 字面量已核对：`sim_live`/`signal_auto_sim`/`manual` 与产品代码一致
- [x] 清理铁律：每例 try/finally 清内存 + DB 行
- [x] 财务断言全用 `pytest.approx(abs=1e-2)`

## 风险与备注

- **LiveGateway 切换层**: 现有 `test_sim_trade_backend.py` 已覆盖 `TRADE_BACKEND` sim/stock_trade/未知值回退 + `account_id` 前缀，spec 第3层不重复造测试，回归时一并跑确认未破。
- **远程 MySQL**: 测试真实写库，若网络抖动可能偶发失败，重跑即可。Order/Signal/AutoTradeConfig/TradingInstance 行均按 account_id 清理。
- **`_execute_live_signal_sim` 内部 `risk_manager.check_order`**: 产品代码已调，Task 8 验证其生效。
- **broker_provider 路径缺口**: `/trading/order` 默认走 qmt broker，本次用打桩 `SimBrokerProvider` 转发到 `SimTradeBackend` 测 API 层逻辑。**不修产品代码**，缺口在最终报告标注。

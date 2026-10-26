"""SimTradeBackend / StockTradeBackend 单元测试"""
import pytest
from datetime import date, timedelta
from app.core.trade_backend import TradeBackend, StockTradeBackend, SimTradeBackend, SIM_COMMISSION_RATE, SIM_MIN_COMMISSION, SIM_STAMP_TAX_RATE


def test_trade_backend_is_abstract():
    with pytest.raises(TypeError):
        TradeBackend()


def test_stock_trade_backend_has_all_methods():
    backend = StockTradeBackend()
    for attr in ["is_connected", "auto_connect", "auto_connect_background",
                 "check_health", "get_account", "get_positions", "get_orders",
                 "get_trades", "place_order", "cancel_order", "get_quote", "disconnect"]:
        assert hasattr(backend, attr), f"缺少: {attr}"


def _get_runner():
    """延迟导入 runner，避免 vnpy 模块不可用时整文件无法加载"""
    from app.services.vnpy_strategy_runner import vnpy_strategy_runner as r
    return r


def _setup_sim_account(account_id="sim-test", balance=1000000):
    """在 vnpy_strategy_runner 里预置一个模拟账户"""
    runner = _get_runner()
    runner._sim_accounts[account_id] = {
        "balance": balance, "available": balance,
        "initial_capital": balance,
    }
    runner._sim_positions[account_id] = {}
    runner._sim_buy_dates.setdefault(account_id, {})
    return account_id


def _teardown_sim_account(account_id="sim-test"):
    """清理测试账户"""
    runner = _get_runner()
    runner._sim_accounts.pop(account_id, None)
    runner._sim_positions.pop(account_id, None)
    runner._sim_buy_dates.pop(account_id, None)
    runner._current_ticks.pop("600519", None)


@pytest.mark.asyncio
async def test_sim_backend_auto_connect_sets_connected():
    """auto_connect 直接置 connected=True，不连服务"""
    backend = SimTradeBackend()
    result = await backend.auto_connect()
    assert result["success"] is True
    assert backend.is_connected is True


@pytest.mark.asyncio
async def test_sim_backend_place_order_buy():
    """买入：账户扣款、持仓增加、返回 success"""
    account_id = _setup_sim_account()
    backend = SimTradeBackend(account_id=account_id)
    result = await backend.place_order("600519", "buy", 100, price=1680.0)
    assert result["success"] is True

    runner = _get_runner()
    acct = runner._sim_accounts[account_id]
    cost = 100 * 1680.0
    commission = max(cost * SIM_COMMISSION_RATE, SIM_MIN_COMMISSION)
    assert acct["available"] == 1000000 - cost - commission
    assert runner._sim_positions[account_id]["600519"]["quantity"] == 100
    _teardown_sim_account(account_id)


@pytest.mark.asyncio
async def test_sim_backend_place_order_insufficient_funds():
    """资金不足返回 success=False，不改账户"""
    account_id = _setup_sim_account(balance=1000)  # 不够买 100 股 1680
    backend = SimTradeBackend(account_id=account_id)
    result = await backend.place_order("600519", "buy", 100, price=1680.0)
    assert result["success"] is False
    assert "资金不足" in result["error"]

    runner = _get_runner()
    assert runner._sim_accounts[account_id]["available"] == 1000  # 未变
    _teardown_sim_account(account_id)


@pytest.mark.asyncio
async def test_sim_backend_place_order_sell_insufficient_position():
    """卖出持仓不足返回失败"""
    account_id = _setup_sim_account()
    backend = SimTradeBackend(account_id=account_id)
    result = await backend.place_order("600519", "sell", 100, price=1680.0)
    assert result["success"] is False
    assert "持仓不足" in result["error"]
    _teardown_sim_account(account_id)


@pytest.mark.asyncio
async def test_sim_backend_get_account_uninitialized():
    """未初始化账户返回空结构不抛异常"""
    backend = SimTradeBackend(account_id="sim-nonexist")
    acct = await backend.get_account()
    assert acct["cash"] == 0
    assert acct["total_assets"] == 0


@pytest.mark.asyncio
async def test_sim_backend_get_positions():
    """预置持仓后 get_positions 返回列表"""
    account_id = _setup_sim_account()
    runner = _get_runner()
    runner._update_sim_account_buy(account_id, "600519", 100, 1680.0)

    backend = SimTradeBackend(account_id=account_id)
    positions = await backend.get_positions()
    assert len(positions) == 1
    assert positions[0]["symbol"] == "600519"
    assert positions[0]["volume"] == 100
    _teardown_sim_account(account_id)


from app.core.live_gateway import LiveGateway, live_gateway
from app.config import settings


def test_live_gateway_delegates_to_sim_by_default():
    assert settings.TRADE_BACKEND == "sim"
    assert isinstance(live_gateway._backend, SimTradeBackend)


def test_live_gateway_unknown_backend_falls_back_to_sim(monkeypatch):
    monkeypatch.setattr(settings, "TRADE_BACKEND", "xxx")
    gw = LiveGateway()
    assert isinstance(gw._backend, SimTradeBackend)


def test_live_gateway_stock_trade_backend(monkeypatch):
    monkeypatch.setattr(settings, "TRADE_BACKEND", "stock_trade")
    gw = LiveGateway()
    from app.core.trade_backend import StockTradeBackend
    assert isinstance(gw._backend, StockTradeBackend)


# ── 新增测试：T+1、涨跌停、资金校验 ────────────────────────────────────────


class TestT1Check:
    """T+1 校验：当日买入不可卖出"""

    def test_t1_sell_rejected_same_day(self):
        """买入后同日卖出被拒绝"""
        account_id = _setup_sim_account()
        runner = _get_runner()
        try:
            runner._update_sim_account_buy(account_id, "600519", 100, 1680.0)
            passed, reason = runner._check_t1_and_limit(account_id, "600519", "sell", 1700.0)
            assert passed is False
            assert "T+1" in reason
        finally:
            _teardown_sim_account(account_id)

    def test_t1_sell_allowed_next_day(self):
        """买入次日可卖出（模拟：修改 buy_dates 为昨天）"""
        account_id = _setup_sim_account()
        runner = _get_runner()
        try:
            runner._update_sim_account_buy(account_id, "600519", 100, 1680.0)
            runner._sim_buy_dates[account_id]["600519"] = date.today() - timedelta(days=1)
            passed, reason = runner._check_t1_and_limit(account_id, "600519", "sell", 1700.0)
            assert passed is True
        finally:
            _teardown_sim_account(account_id)

    def test_t1_buy_not_affected(self):
        """T+1 不影响买入"""
        account_id = _setup_sim_account()
        runner = _get_runner()
        try:
            passed, reason = runner._check_t1_and_limit(account_id, "600519", "buy", 1680.0)
            assert passed is True
        finally:
            _teardown_sim_account(account_id)


class TestLimitUpDownCheck:
    """涨跌停校验"""

    def test_limit_up_buy_rejected(self):
        """涨停价买入被拒绝"""
        account_id = _setup_sim_account()
        runner = _get_runner()
        try:
            runner._current_ticks["600519"] = {"pre_close": 100.0, "last_price": 110.0}
            limit_up = round(100.0 * 1.1, 2)  # 110.0
            passed, reason = runner._check_t1_and_limit(account_id, "600519", "buy", limit_up)
            assert passed is False
            assert "涨停" in reason
        finally:
            _teardown_sim_account(account_id)

    def test_limit_down_sell_rejected(self):
        """跌停价卖出被拒绝"""
        account_id = _setup_sim_account()
        runner = _get_runner()
        try:
            runner._current_ticks["600519"] = {"pre_close": 100.0, "last_price": 90.0}
            limit_down = round(100.0 * 0.9, 2)  # 90.0
            passed, reason = runner._check_t1_and_limit(account_id, "600519", "sell", limit_down)
            assert passed is False
            assert "跌停" in reason
        finally:
            _teardown_sim_account(account_id)

    def test_normal_price_passes(self):
        """正常价格通过校验"""
        account_id = _setup_sim_account()
        runner = _get_runner()
        try:
            runner._current_ticks["600519"] = {"pre_close": 100.0, "last_price": 105.0}
            passed, reason = runner._check_t1_and_limit(account_id, "600519", "buy", 105.0)
            assert passed is True
            passed, reason = runner._check_t1_and_limit(account_id, "600519", "sell", 95.0)
            assert passed is True
        finally:
            _teardown_sim_account(account_id)

    def test_no_pre_close_skips_check(self):
        """无昨收价时跳过涨跌停校验"""
        account_id = _setup_sim_account()
        runner = _get_runner()
        try:
            runner._current_ticks.pop("600519", None)
            passed, reason = runner._check_t1_and_limit(account_id, "600519", "buy", 99999.0)
            assert passed is True
        finally:
            _teardown_sim_account(account_id)


class TestCommissionConstants:
    """验证佣金常量一致性"""

    def test_constants_values(self):
        assert SIM_COMMISSION_RATE == 0.0003
        assert SIM_MIN_COMMISSION == 5.0
        assert SIM_STAMP_TAX_RATE == 0.001

    def test_buy_deducts_commission(self):
        """买入扣佣金"""
        account_id = _setup_sim_account()
        runner = _get_runner()
        try:
            runner._update_sim_account_buy(account_id, "600519", 100, 1680.0)
            cost = 100 * 1680.0
            commission = max(cost * SIM_COMMISSION_RATE, SIM_MIN_COMMISSION)
            expected_balance = 1000000 - cost - commission
            assert runner._sim_accounts[account_id]["balance"] == expected_balance
        finally:
            _teardown_sim_account(account_id)

    def test_sell_deducts_commission_and_stamp_tax(self):
        """卖出扣佣金+印花税"""
        account_id = _setup_sim_account()
        runner = _get_runner()
        try:
            runner._update_sim_account_buy(account_id, "600519", 100, 1680.0)
            balance_after_buy = runner._sim_accounts[account_id]["balance"]

            # 模拟次日以允许卖出
            runner._sim_buy_dates[account_id]["600519"] = date.today() - timedelta(days=1)

            runner._update_sim_account_sell(account_id, "600519", 100, 1700.0, 1680.0)
            revenue = 100 * 1700.0
            commission = max(revenue * SIM_COMMISSION_RATE, SIM_MIN_COMMISSION)
            stamp_tax = revenue * SIM_STAMP_TAX_RATE
            expected_balance = balance_after_buy + revenue - commission - stamp_tax
            assert abs(runner._sim_accounts[account_id]["balance"] - expected_balance) < 0.01
        finally:
            _teardown_sim_account(account_id)


class TestBuyDatesTracking:
    """T+1 买入日期跟踪"""

    def test_buy_records_date(self):
        """买入记录日期"""
        account_id = _setup_sim_account()
        runner = _get_runner()
        try:
            runner._update_sim_account_buy(account_id, "600519", 100, 1680.0)
            assert account_id in runner._sim_buy_dates
            assert "600519" in runner._sim_buy_dates[account_id]
            assert runner._sim_buy_dates[account_id]["600519"] == date.today()
        finally:
            _teardown_sim_account(account_id)

    def test_clear_position_clears_buy_date(self):
        """清仓后清除买入日期"""
        account_id = _setup_sim_account()
        runner = _get_runner()
        try:
            runner._update_sim_account_buy(account_id, "600519", 100, 1680.0)
            runner._sim_buy_dates[account_id]["600519"] = date.today() - timedelta(days=1)
            runner._update_sim_account_sell(account_id, "600519", 100, 1700.0, 1680.0)
            assert "600519" not in runner._sim_buy_dates.get(account_id, {})
        finally:
            _teardown_sim_account(account_id)


class TestNoFrozenField:
    """验证 frozen 字段已移除"""

    def test_account_no_frozen_key(self):
        """新创建的账户不含 frozen 键"""
        account_id = _setup_sim_account()
        runner = _get_runner()
        try:
            assert "frozen" not in runner._sim_accounts[account_id]
        finally:
            _teardown_sim_account(account_id)

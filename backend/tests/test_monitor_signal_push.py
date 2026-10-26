"""盯盘引擎生成信号后经 WebSocket 定向推送给该信号所属用户。"""
import asyncio
from unittest.mock import AsyncMock, patch
from datetime import datetime

from app.services import agent_service
from app.services.agent_service import evaluate_monitor_rules, MonitorRule, AgentSignal


def _make_rule(stock_code="600519", action="buy", target_price=1600.0, user_id="u1"):
    return MonitorRule(
        id="r1",
        user_id=user_id,
        stock_code=stock_code,
        condition="跌破1600买入",
        action=action,
        target_price=target_price,
        quantity=100,
        position_pct=None,
        advance_minutes=0,
        program_code="",
        active=True,
        created_at=datetime.utcnow(),
    )


def test_signal_pushed_to_user_on_trigger(monkeypatch):
    """规则触发时,生成的信号经 ws_manager.send_to_user 推送给 rule.user_id。"""
    rule = _make_rule()
    quotes = {"600519": {"price": 1590.0, "name": "贵州茅台"}}

    class FakeQuery:
        def __init__(self, model):
            self.model = model
        def filter(self, *conds):
            return self
        def all(self):
            return [rule]
        def first(self):
            return None

    class FakeDb:
        def query(self, model):
            return FakeQuery(model)
        def add(self, obj):
            pass
        def commit(self):
            pass
        def close(self):
            pass

    monkeypatch.setattr(agent_service, "_fetch_quotes", lambda codes: quotes)

    with patch("app.services.agent_service.ws_manager") as mock_ws:
        mock_ws.send_to_user = AsyncMock()
        asyncio.run(_run_eval(FakeDb()))

        mock_ws.send_to_user.assert_called()
        call_args = mock_ws.send_to_user.call_args
        assert call_args.args[0] == "u1"
        msg = call_args.args[1]
        assert msg["type"] == "agent_signal"
        assert msg["data"]["stockCode"] == "600519"
        assert msg["data"]["status"] == "pending"


async def _run_eval(db):
    evaluate_monitor_rules(db)
    await asyncio.sleep(0)


def test_no_push_when_not_triggered(monkeypatch):
    """规则未触发时不推送。"""
    rule = _make_rule(target_price=1600.0)
    quotes = {"600519": {"price": 1700.0, "name": "贵州茅台"}}

    class FakeQuery:
        def __init__(self, model):
            self.model = model
        def filter(self, *conds):
            return self
        def all(self):
            return [rule]
        def first(self):
            return None

    class FakeDb:
        def query(self, model):
            return FakeQuery(model)
        def add(self, obj):
            pass
        def commit(self):
            pass
        def close(self):
            pass

    monkeypatch.setattr(agent_service, "_fetch_quotes", lambda codes: quotes)

    with patch("app.services.agent_service.ws_manager") as mock_ws:
        mock_ws.send_to_user = AsyncMock()
        evaluate_monitor_rules(FakeDb())
        mock_ws.send_to_user.assert_not_called()


def test_push_failure_does_not_propagate(monkeypatch):
    """send_to_user 抛异常时被吞掉,不传播到评估循环。"""
    rule = _make_rule()
    quotes = {"600519": {"price": 1590.0, "name": "贵州茅台"}}

    class FakeQuery:
        def __init__(self, model):
            self.model = model
        def filter(self, *conds):
            return self
        def all(self):
            return [rule]
        def first(self):
            return None

    class FakeDb:
        def query(self, model):
            return FakeQuery(model)
        def add(self, obj):
            pass
        def commit(self):
            pass
        def close(self):
            pass

    monkeypatch.setattr(agent_service, "_fetch_quotes", lambda codes: quotes)

    with patch("app.services.agent_service.ws_manager") as mock_ws:
        # send_to_user 抛异常,模拟 WS 推送失败
        mock_ws.send_to_user = AsyncMock(side_effect=RuntimeError("ws down"))
        # 应当不抛——异常被 _push 内的 try/except 吞掉
        asyncio.run(_run_eval(FakeDb()))
        mock_ws.send_to_user.assert_called()


def test_pushed_message_is_json_serializable(monkeypatch):
    """WS 推送的消息必须能被 json.dumps 序列化(不能含 datetime 等裸对象)。"""
    import json
    rule = _make_rule()
    quotes = {"600519": {"price": 1590.0, "name": "贵州茅台"}}

    class FakeQuery:
        def __init__(self, model):
            self.model = model
        def filter(self, *conds):
            return self
        def all(self):
            return [rule]
        def first(self):
            return None

    class FakeDb:
        def query(self, model):
            return FakeQuery(model)
        def add(self, obj):
            pass
        def commit(self):
            pass
        def close(self):
            pass

    monkeypatch.setattr(agent_service, "_fetch_quotes", lambda codes: quotes)

    captured = {}

    async def fake_send_to_user(user_id, message):
        captured["user_id"] = user_id
        captured["message"] = message
        # 真实序列化:验证 json.dumps 不抛 TypeError
        captured["serialized"] = json.dumps(message, ensure_ascii=False)

    with patch("app.services.agent_service.ws_manager") as mock_ws:
        mock_ws.send_to_user = fake_send_to_user
        asyncio.run(_run_eval(FakeDb()))

    assert captured.get("user_id") == "u1"
    assert captured.get("serialized") is not None  # json.dumps 成功未抛
    parsed = json.loads(captured["serialized"])
    assert parsed["data"]["stockCode"] == "600519"

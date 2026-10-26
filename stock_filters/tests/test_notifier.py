import pytest
from unittest.mock import MagicMock, patch
from notifier import DingTalkNotifier


@pytest.fixture
def notifier():
    config = {
        "webhook": "https://oapi.dingtalk.com/robot/send?access_token=test",
        "secret": "",
    }
    return DingTalkNotifier(config)


def test_format_message(notifier):
    results = {
        "六脉神剑": [
            {"code": "000001", "name": "平安银行", "price": 12.50, "change_pct": 3.21, "reason": "MACD金叉+放量1.8倍"},
        ],
        "四维擒龙": [
            {"code": "601318", "name": "中国平安", "price": 45.80, "change_pct": -1.05, "reason": "放量2.3倍+突破20日高点"},
        ],
    }
    msg = notifier.format_message(results, elapsed=5.3)
    assert "时间:" in msg
    assert "耗时:" in msg
    assert "5.3秒" in msg
    assert "六脉神剑" in msg
    assert "000001" in msg
    assert "12.50" in msg
    assert "+3.21%" in msg
    assert "四维擒龙" in msg
    assert "601318" in msg
    assert "45.80" in msg
    assert "-1.05%" in msg
    assert "共筛选出 2 只股票" in msg


def test_format_messages_splits_by_strategy(notifier):
    results = {
        "六脉神剑": [
            {"code": "000001", "name": "平安银行", "price": 12.50, "change_pct": 3.21},
        ],
        "四维擒龙": [
            {"code": "601318", "name": "中国平安", "price": 45.80, "change_pct": -1.05},
        ],
    }
    messages = notifier.format_messages(results, elapsed=5.3)
    # 1条摘要 + 2条策略 = 3条（无重点股票，因为无重叠）
    assert len(messages) == 3
    assert "六脉神剑:1只" in messages[0]
    assert "四维擒龙:1只" in messages[0]
    assert "5s" in messages[0]
    assert "000001" in messages[1]
    assert "601318" in messages[2]


def test_format_messages_focus_stocks(notifier):
    results = {
        "六脉神剑": [
            {"code": "000001", "name": "平安银行", "price": 12.50, "change_pct": 3.21},
            {"code": "601318", "name": "中国平安", "price": 45.80, "change_pct": -1.05},
        ],
        "四维擒龙": [
            {"code": "000001", "name": "平安银行", "price": 12.50, "change_pct": 3.21},
        ],
    }
    messages = notifier.format_messages(results, elapsed=5.0)
    # 1条摘要 + 2条策略 + 1条重点 = 4条
    assert len(messages) == 4
    focus_msg = messages[3]
    assert "重点股票" in focus_msg
    assert "000001" in focus_msg
    assert "六脉神剑+四维擒龙" in focus_msg


def test_format_messages_empty(notifier):
    messages = notifier.format_messages({})
    assert len(messages) == 1
    assert "未筛选出" in messages[0]


@patch("notifier.requests.post")
def test_send_success(mock_post, notifier):
    mock_post.return_value = MagicMock(status_code=200, json=lambda: {"errcode": 0})
    result = notifier.send("test message")
    assert result is True


@patch("notifier.requests.post")
def test_send_retry_on_failure(mock_post, notifier):
    mock_post.side_effect = [
        Exception("timeout"),
        Exception("timeout"),
        MagicMock(status_code=200, json=lambda: {"errcode": 0}),
    ]
    result = notifier.send("test message")
    assert result is True
    assert mock_post.call_count == 3

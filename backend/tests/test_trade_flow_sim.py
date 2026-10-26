"""
单日分钟对账测试 — run_trade_flow_test

run_trade_flow_test 是个内置的好对账测试：强制注入 买入→T+1拒单→卖出 全流程，
验证 下单→成交→持仓更新→资金更新→T+1 限制。
原版依赖真实分钟数据，这里用 monkeypatch 替换 _load_minute_data 为合成数据。

标记 @pytest.mark.slow：SimulatedStockGateway + EventEngine 启动较重，
CI 用 -m "not slow" 跳过。
"""

import pytest
import pandas as pd
from datetime import datetime, timedelta

vnpy = pytest.importorskip("vnpy")

from app.services import simulation_test_service as sim
from app.services.simulation_test_service import run_trade_flow_test

pytestmark = [pytest.mark.slow]


def _fake_minute_df(trade_date="2024-01-05", n=240, start_price=10.0, end_price=10.5):
    """合成 1 分钟 K 线 DataFrame（索引为 DatetimeIndex）"""
    idx = pd.date_range(f"{trade_date} 09:31", periods=n, freq="1min")
    closes = [start_price + i * (end_price - start_price) / (n - 1) for i in range(n)]
    return pd.DataFrame({
        "open": closes,
        "high": [c + 0.01 for c in closes],
        "low": [c - 0.01 for c in closes],
        "close": closes,
        "volume": [1000.0] * n,
    }, index=idx)


@pytest.fixture
def mock_minute_data(monkeypatch):
    monkeypatch.setattr(sim, "_load_minute_data",
                        lambda symbol, trade_date: _fake_minute_df(trade_date))
    monkeypatch.setattr(sim, "_get_last_trading_date", lambda: "2024-01-05")
    return _fake_minute_df("2024-01-05")


class TestTradeFlow:
    def test_passes_with_no_errors(self, mock_minute_data):
        result = run_trade_flow_test(symbol="600000", initial_capital=1_000_000,
                                     trade_date="2024-01-05")
        assert result["passed"] is True, f"测试未通过，错误: {result['errors']}"
        assert result["errors"] == []

    def test_buy_then_sell_trade_count(self, mock_minute_data):
        """至少 1 买 1 卖"""
        result = run_trade_flow_test(symbol="600000", initial_capital=1_000_000,
                                     trade_date="2024-01-05")
        assert result["buy_trade_count"] >= 1
        assert result["sell_trade_count"] >= 1

    def test_t1_rejection_recorded(self, mock_minute_data):
        """T+1 卖单应被拒绝（在 trades 或 errors 中体现）"""
        result = run_trade_flow_test(symbol="600000", initial_capital=1_000_000,
                                     trade_date="2024-01-05")
        # run_trade_flow_test 内部会把 T+1 拒单记进 trades(source=forced_t1_test) 或 errors
        t1_evidence = (
            any(t.get("reason") == "T+1限制" or t.get("status") == "rejected"
                for t in result["trades"])
            or any("T+1" in e for e in result["errors"])
        )
        # 要么 T+1 正确生效（rejected 记录），要么误放行（errors 报 T+1 未生效）—— 二者必有其一
        assert t1_evidence, "T+1 限制既未拒绝卖单也未报错，逻辑异常"

    def test_position_after_buy_positive(self, mock_minute_data):
        """买入后持仓快照 > 0"""
        result = run_trade_flow_test(symbol="600000", initial_capital=1_000_000,
                                     trade_date="2024-01-05")
        snaps = result["account_snapshots"]
        buy_snap = [s for s in snaps if s.get("event") == "买入后"]
        assert buy_snap, "缺少买入后快照"
        assert buy_snap[0]["position"] > 0

    def test_position_zero_after_sell(self, mock_minute_data):
        """卖出后持仓应为 0"""
        result = run_trade_flow_test(symbol="600000", initial_capital=1_000_000,
                                     trade_date="2024-01-05")
        snaps = result["account_snapshots"]
        sell_snap = [s for s in snaps if s.get("event") == "卖出后"]
        assert sell_snap, "缺少卖出后快照"
        assert sell_snap[0]["position"] == 0

    def test_final_assets_positive(self, mock_minute_data):
        """末尾总资产 > 0"""
        result = run_trade_flow_test(symbol="600000", initial_capital=1_000_000,
                                     trade_date="2024-01-05")
        final = result["final_account"]
        assert final.get("total_assets", 0) > 0
        assert final.get("balance", 0) > 0  # 卖出后现金为正

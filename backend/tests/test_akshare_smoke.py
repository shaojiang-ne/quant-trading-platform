"""akshare 真实接口冒烟测试（slow）

真实拉取 stock_zh_a_spot_em，验证字段齐全。
非交易时段也能跑（快照仍返回，价格可能为 0）。
"""
import asyncio
import pytest

pytestmark = [pytest.mark.slow]


def test_akshare_snapshot_real():
    """真实拉一次全市场快照，返回非空"""
    from app.core.data_source_akshare import AkshareDataSource
    snap = AkshareDataSource().get_snapshot(["600519", "000001"])
    assert "600519" in snap
    assert "name" in snap["600519"]


@pytest.mark.asyncio
async def test_akshare_backend_poll_real():
    """订阅 600519，跑 2 轮真实轮询，callback 被触发"""
    from app.core.market_backend import AkshareMarketBackend
    from app.services.trading_calendar_service import trading_calendar
    if not trading_calendar.is_trading_time():
        pytest.skip("非交易时间，跳过轮询冒烟测试")

    backend = AkshareMarketBackend()
    if not backend.is_available():
        pytest.skip("akshare 未安装")

    received = []
    backend.subscribe_quote("600519", callback=lambda t: received.append(t))

    # 跑 2 轮（每轮间隔 3 秒，但 _fetch_snapshot 内部限流 ≥1.5s，2 轮约 6-9 秒）
    await backend._poll_once()
    await asyncio.sleep(3.5)
    await backend._poll_once()

    backend.close()
    assert len(received) >= 1
    assert received[0]["stock"] == "600519"

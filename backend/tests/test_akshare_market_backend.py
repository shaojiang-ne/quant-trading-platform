"""AkshareMarketBackend / StockDataMarketBackend 单元测试"""
import pytest
from app.core.market_backend import MarketBackend, StockDataMarketBackend, AkshareMarketBackend


def test_market_backend_is_abstract():
    """MarketBackend 是抽象基类，不能直接实例化"""
    with pytest.raises(TypeError):
        MarketBackend()


def test_stock_data_backend_has_all_methods():
    """StockDataMarketBackend 实现了所有抽象方法"""
    backend = StockDataMarketBackend()
    for method in ["is_available", "check_health", "get_klines", "get_full_tick",
                   "get_stock_list", "get_stock_list_full", "get_instrument_detail",
                   "get_instruments_batch", "subscribe_quote", "unsubscribe_quote", "close"]:
        assert hasattr(backend, method), f"缺少方法: {method}"


def _fake_snapshot():
    """模拟 AkshareDataSource.get_snapshot 返回值"""
    return {
        "600519": {
            "name": "贵州茅台", "price": 1680.0, "change_pct": 1.2,
            "turnover_pct": 0.5, "pe_ttm": 30.0, "pb": 10.0,
            "float_mcap_yi": 21000.0, "vol_ratio": 1.1, "amount_wan": 50000.0,
        }
    }


def test_snapshot_to_tick_fields():
    """快照转 tick：字段完整，五档置空"""
    backend = AkshareMarketBackend()
    tick = backend._snapshot_to_tick("600519", _fake_snapshot()["600519"])
    assert tick["lastPrice"] == 1680.0
    assert tick["stock"] == "600519"
    assert tick["bidPrice"] == []
    assert tick["bidVol"] == []
    assert tick["askPrice"] == []
    assert tick["askVol"] == []


def test_snapshot_to_tick_none_fields_become_zero():
    """快照字段为 None 时转成 0（东财 null vs missing key 坑）"""
    backend = AkshareMarketBackend()
    snap = {"name": "X", "price": None, "change_pct": None,
            "turnover_pct": None, "pe_ttm": None, "pb": None,
            "float_mcap_yi": None, "vol_ratio": None, "amount_wan": None}
    tick = backend._snapshot_to_tick("000001", snap)
    assert tick["lastPrice"] == 0
    assert tick["volume"] == 0


def test_update_cache_and_get_full_tick():
    """快照写入缓存后，get_full_tick 能读出"""
    backend = AkshareMarketBackend()
    backend._update_cache({"600519": _fake_snapshot()["600519"]})
    tick = backend.get_full_tick("600519")
    assert tick is not None
    assert tick["lastPrice"] == 1680.0


def test_get_full_tick_miss_returns_none():
    """未缓存的 symbol 返回 None"""
    backend = AkshareMarketBackend()
    assert backend.get_full_tick("999999") is None


import asyncio
from unittest.mock import patch


@pytest.mark.asyncio
async def test_subscribe_dispatches_to_callback():
    """订阅后轮询一轮，callback 被调用且收到正确 tick"""
    backend = AkshareMarketBackend()
    received = []
    seq = backend.subscribe_quote("600519", callback=lambda tick: received.append(tick))

    # mock 轮询：直接调 _poll_once
    with patch("app.services.trading_calendar_service.trading_calendar.is_trading_time",
               return_value=True), \
         patch("app.core.market_backend.AkshareMarketBackend._fetch_snapshot",
               return_value=_fake_snapshot()):
        await backend._poll_once()

    assert len(received) == 1
    assert received[0]["stock"] == "600519"
    assert received[0]["lastPrice"] == 1680.0
    backend.close()


@pytest.mark.asyncio
async def test_poll_skips_non_subscribed_symbols():
    """只对订阅的 symbol 调 callback，未订阅的不调"""
    backend = AkshareMarketBackend()
    received = []
    backend.subscribe_quote("600519", callback=lambda t: received.append(t))

    with patch("app.services.trading_calendar_service.trading_calendar.is_trading_time",
               return_value=True), \
         patch("app.core.market_backend.AkshareMarketBackend._fetch_snapshot",
               return_value={"600519": _fake_snapshot()["600519"],
                             "000001": {"name": "X", "price": 10, "change_pct": 0,
                                        "turnover_pct": 0, "pe_ttm": 0, "pb": 0,
                                        "float_mcap_yi": 0, "vol_ratio": 0, "amount_wan": 0}}):
        await backend._poll_once()

    assert len(received) == 1  # 只 600519，不含 000001
    backend.close()


@pytest.mark.asyncio
async def test_poll_preserves_cache_on_exception():
    """轮询抛异常时保留旧缓存，不调 callback"""
    backend = AkshareMarketBackend()
    backend._update_cache({"600519": _fake_snapshot()["600519"]})
    received = []
    backend.subscribe_quote("600519", callback=lambda t: received.append(t))

    with patch("app.core.market_backend.AkshareMarketBackend._fetch_snapshot",
               side_effect=RuntimeError("akshare 挂了")):
        await backend._poll_once()

    # 缓存保留
    assert backend.get_full_tick("600519") is not None
    assert backend.get_full_tick("600519")["lastPrice"] == 1680.0
    # 异常时不调 callback
    assert len(received) == 0
    backend.close()


@pytest.mark.asyncio
async def test_poll_skips_when_not_trading_time():
    """非交易时间跳过请求"""
    backend = AkshareMarketBackend()
    fetch_called = []
    backend.subscribe_quote("600519", callback=lambda t: None)

    with patch("app.services.trading_calendar_service.trading_calendar.is_trading_time",
               return_value=False):
        with patch("app.core.market_backend.AkshareMarketBackend._fetch_snapshot",
                   side_effect=lambda *a: fetch_called.append(1) or {}):
            await backend._poll_once()

    assert len(fetch_called) == 0  # 非交易时间不拉
    backend.close()


from app.services.market_service import MarketService, market_service
from app.config import settings


def test_market_service_delegates_to_akshare_by_default():
    """默认配置下 market_service 委托给 AkshareMarketBackend"""
    assert settings.MARKET_BACKEND == "akshare"
    assert isinstance(market_service._backend, AkshareMarketBackend)


def test_market_service_unknown_backend_falls_back_to_akshare(monkeypatch):
    """未知后端值 fallback 到 akshare"""
    monkeypatch.setattr(settings, "MARKET_BACKEND", "xxx")
    svc = MarketService()
    assert isinstance(svc._backend, AkshareMarketBackend)


def test_market_service_stock_data_backend(monkeypatch):
    """stock_data 配置委托给 StockDataMarketBackend"""
    monkeypatch.setattr(settings, "MARKET_BACKEND", "stock_data")
    svc = MarketService()
    from app.core.market_backend import StockDataMarketBackend
    assert isinstance(svc._backend, StockDataMarketBackend)


# ── 回归修复：get_klines / get_stock_list 委托 data_bridge ─────────────────────

def test_akshare_backend_get_klines_delegates_to_data_bridge(monkeypatch):
    """get_klines 委托给 data_bridge，不抛 NotImplementedError"""
    backend = AkshareMarketBackend()

    # mock data_bridge.load_bars_df 返回一个有效 df
    import pandas as pd
    fake_df = pd.DataFrame({
        "date": pd.to_datetime(["2026-07-01", "2026-07-02"]),
        "open": [10.0, 11.0], "high": [11.0, 12.0], "low": [9.0, 10.0],
        "close": [10.5, 11.5], "volume": [1000, 2000], "turnover": [10000, 20000],
    })
    from app.core import data_bridge as db_module
    monkeypatch.setattr(db_module.data_bridge, "load_bars_df", lambda *a, **k: fake_df)

    df = backend.get_klines("600519", period="1d", start_time="20260701", end_time="20260702")
    assert not df.empty
    # market_service 契约：date 是 index，有 amount 列
    assert "open" in df.columns
    assert "amount" in df.columns  # turnover 被重命名为 amount


def test_akshare_backend_get_klines_empty_returns_empty_df(monkeypatch):
    """data_bridge 返回空时，get_klines 返回空 DataFrame 不抛异常"""
    import pandas as pd
    backend = AkshareMarketBackend()
    from app.core import data_bridge as db_module
    monkeypatch.setattr(db_module.data_bridge, "load_bars_df", lambda *a, **k: pd.DataFrame())
    df = backend.get_klines("999999", period="1d")
    assert df.empty


def test_akshare_backend_get_stock_list_full_returns_list():
    """get_stock_list_full 返回 list[dict]，含 symbol/name"""
    backend = AkshareMarketBackend()
    if not backend.is_available():
        import pytest
        pytest.skip("akshare 未安装")
    stocks = backend.get_stock_list_full("沪深A股")
    assert isinstance(stocks, list)
    # 网络受限（如沙箱代理拦截东财）时返回空列表属正常兜底，不视为代码缺陷
    if len(stocks) == 0:
        import pytest
        pytest.skip("akshare 网络不可达（spot_em 返回空）")
    assert "symbol" in stocks[0]
    assert "name" in stocks[0]

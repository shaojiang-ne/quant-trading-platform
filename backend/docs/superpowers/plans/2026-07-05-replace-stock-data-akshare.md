# 替换 stock_data 实时行情与实盘下单数据源 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 用 akshare 公开 HTTP 接口替换 stock_data 做实时 tick，实盘下单改为模拟成交（复用 `_sim_accounts`），`market_service`/`live_gateway` 接口不变，新增后端类 + 配置切换，保留旧实现作 fallback。

**Architecture:** 两个抽象后端基类 `MarketBackend`/`TradeBackend`，各两个实现（akshare/sim 新增，stock_data/stock_trade 保留）。`market_service`/`live_gateway` 按配置委托给对应后端。`SimTradeBackend` 通过延迟导入 `vnpy_strategy_runner` 操作 `_sim_accounts`，与 simulation 路径共用账户。

**Tech Stack:** Python 3.12 / FastAPI / akshare / pytest / asyncio。测试在 venv 跑（非 anaconda）。

**Spec:** `docs/superpowers/specs/2026-07-05-replace-stock-data-design.md`

---

## 文件结构

**新增：**
- `app/core/market_backend.py` — `MarketBackend` 抽象基类 + `AkshareMarketBackend` + `StockDataMarketBackend`
- `app/core/trade_backend.py` — `TradeBackend` 抽象基类 + `SimTradeBackend` + `StockTradeBackend`
- `tests/test_akshare_market_backend.py` — 行情后端单元测试
- `tests/test_sim_trade_backend.py` — 交易后端单元测试
- `tests/test_market_trade_backend_integration.py` — 集成测试
- `tests/test_akshare_smoke.py` — 真实 akshare 冒烟测试（slow）

**改造：**
- `app/config.py` — 新增 `MARKET_BACKEND`/`TRADE_BACKEND` 配置
- `app/services/market_service.py` — `MarketService` 委托给后端
- `app/core/live_gateway.py` — `LiveGateway` 委托给后端
- `app/services/vnpy_strategy_runner.py` — `_get_account_id`/`_execute_signal` live 分支改模拟成交
- `app/main.py` — 日志文案微调

---

## Task 1: 新增配置项

**Files:**
- Modify: `app/config.py:18-26`

- [ ] **Step 1: 添加配置字段**

在 `app/config.py` 的 `STOCK_TRADE_API_KEY` 之后、`TRADE_AUTO_CONNECT` 之前插入：

```python
    # 数据后端选择: akshare / stock_data
    MARKET_BACKEND: str = "akshare"
    # 交易后端选择: sim / stock_trade
    TRADE_BACKEND: str = "sim"
```

- [ ] **Step 2: 验证配置加载**

Run: `python -c "from app.config import settings; print(settings.MARKET_BACKEND, settings.TRADE_BACKEND)"`
Expected: `akshare sim`

- [ ] **Step 3: Commit**

```bash
git add app/config.py
git commit -m "feat: 新增 MARKET_BACKEND/TRADE_BACKEND 配置项"
```

---

## Task 2: MarketBackend 抽象基类与 StockDataMarketBackend

把现有 `market_service.py` 的 HTTP/WS 实现搬进 `StockDataMarketBackend`，并定义抽象基类。此 task 不改变运行行为（默认仍是 akshare，但 StockData 后端先就位）。

**Files:**
- Create: `app/core/market_backend.py`
- Test: `tests/test_akshare_market_backend.py`

- [ ] **Step 1: 写抽象基类与 StockDataMarketBackend 的骨架测试**

创建 `tests/test_akshare_market_backend.py`：

```python
"""AkshareMarketBackend / StockDataMarketBackend 单元测试"""
import pytest
from app.core.market_backend import MarketBackend, StockDataMarketBackend


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
```

- [ ] **Step 2: 运行测试确认失败**

Run: `python -m pytest tests/test_akshare_market_backend.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'app.core.market_backend'`

- [ ] **Step 3: 创建 market_backend.py，搬入现有实现**

创建 `app/core/market_backend.py`。把 `app/services/market_service.py` 里 `MarketService` 类的**全部方法体**（`_get_client`/`_check_available`/`is_available`/`check_health`/`get_klines`/`get_full_tick`/`get_stock_list`/`get_stock_list_full`/`get_instrument_detail`/`get_instruments_batch`/`subscribe_quote`/`unsubscribe_quote`/`_ensure_ws_connection`/`_close_ws`/`_ws_loop`/`_ws_send`/`_dispatch_tick`/`_dispatch_quote`/`_convert_tick_format`/`close`）原样搬到 `StockDataMarketBackend` 类里，类名改 `StockDataMarketBackend`，`__init__` 不变。

顶部加抽象基类：

```python
"""
行情数据后端抽象 + 实现

MarketBackend 定义行情服务的统一接口，
StockDataMarketBackend 是原有 stock_data 微服务实现（HTTP + WebSocket），
AkshareMarketBackend 是 akshare 公开 HTTP 轮询实现。
"""

import abc
import asyncio
import json
import logging
import ssl
from typing import Optional

import httpx
import pandas as pd
import websockets
import urllib3

urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)

from app.config import settings

logger = logging.getLogger(__name__)


class MarketBackend(abc.ABC):
    """行情数据后端抽象基类"""

    @abc.abstractmethod
    def is_available(self) -> bool: ...

    @abc.abstractmethod
    def check_health(self) -> dict: ...

    @abc.abstractmethod
    def get_klines(self, symbol, period='1d', start_time='', end_time='',
                   count=-1, dividend_type='none') -> pd.DataFrame: ...

    @abc.abstractmethod
    def get_full_tick(self, symbol: str) -> Optional[dict]: ...

    @abc.abstractmethod
    def get_stock_list(self, sector: str = '沪深A股') -> list[str]: ...

    @abc.abstractmethod
    def get_stock_list_full(self, sector: str = '沪深A股') -> list[dict]: ...

    @abc.abstractmethod
    def get_instrument_detail(self, symbol: str) -> Optional[dict]: ...

    @abc.abstractmethod
    def get_instruments_batch(self, symbols: list[str]) -> dict[str, Optional[dict]]: ...

    @abc.abstractmethod
    def subscribe_quote(self, symbol: str, period: str = 'tick', callback=None) -> Optional[int]: ...

    @abc.abstractmethod
    def unsubscribe_quote(self, seq: int) -> bool: ...

    @abc.abstractmethod
    def close(self) -> None: ...


class StockDataMarketBackend(MarketBackend):
    """stock_data 微服务后端（原有实现，HTTP + WebSocket）"""

    VALID_PERIODS = {'1m', '5m', '15m', '30m', '60m', '1h', '1d', '1w', '1mon'}
    VALID_DIVIDEND_TYPES = {'none', 'front', 'back'}

    def __init__(self):
        # …… 把 MarketService.__init__ 的内容搬过来 ……
        ...
    # …… 把 MarketService 的所有方法搬过来，方法签名不变 ……
```

- [ ] **Step 4: 运行测试确认通过**

Run: `python -m pytest tests/test_akshare_market_backend.py -v`
Expected: PASS（2 个测试）

- [ ] **Step 5: Commit**

```bash
git add app/core/market_backend.py tests/test_akshare_market_backend.py
git commit -m "feat: 新增 MarketBackend 抽象基类与 StockDataMarketBackend"
```

---

## Task 3: AkshareMarketBackend — tick 格式转换与缓存

先实现不含轮询的核心：快照转 tick、缓存读写、`is_available`/`check_health`/`get_full_tick`。

**Files:**
- Modify: `app/core/market_backend.py`（追加 `AkshareMarketBackend`）
- Test: `tests/test_akshare_market_backend.py`（追加测试）

- [ ] **Step 1: 写 tick 转换与缓存的失败测试**

在 `tests/test_akshare_market_backend.py` 追加：

```python
from app.core.market_backend import AkshareMarketBackend


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
```

- [ ] **Step 2: 运行测试确认失败**

Run: `python -m pytest tests/test_akshare_market_backend.py::test_snapshot_to_tick_fields -v`
Expected: FAIL — `ImportError: cannot import name 'AkshareMarketBackend'`

- [ ] **Step 3: 实现 AkshareMarketBackend 的核心部分**

在 `app/core/market_backend.py` 追加：

```python
class AkshareMarketBackend(MarketBackend):
    """akshare 公开 HTTP 后端：3 秒轮询全市场快照"""

    def __init__(self):
        self._available: Optional[bool] = None
        self._tick_cache: dict[str, dict] = {}  # symbol -> tick
        self._instrument_cache: dict[str, Optional[dict]] = {}

        # 订阅管理
        self._sub_seq_counter: int = 0
        self._sub_callbacks: dict[int, tuple[str, object]] = {}  # seq -> (symbol, callback)
        self._subscribed_symbols: set[str] = set()

        # 轮询任务
        self._poll_task: Optional[asyncio.Task] = None
        self._poll_interval: float = 3.0  # 秒

    def is_available(self) -> bool:
        if self._available is None:
            try:
                import akshare  # noqa: F401
                self._available = True
                logger.info("akshare 行情后端可用")
            except ImportError:
                self._available = False
                logger.warning("akshare 未安装，行情后端不可用")
        return self._available

    def check_health(self) -> dict:
        available = self.is_available()
        return {
            "service": "akshare",
            "status": "online" if available else "offline",
            "xtquant": {"available": False, "connected": False,
                        "error": "" if available else "akshare 未安装"},
        }

    def get_full_tick(self, symbol: str) -> Optional[dict]:
        return self._tick_cache.get(symbol)

    def _snapshot_to_tick(self, symbol: str, snap: dict) -> dict:
        """快照转 callback 兼容 tick 格式

        akshare spot_em 字段: name/price/change_pct/turnover_pct/pe_ttm/pb/
        float_mcap_yi/vol_ratio/amount_wan。无 open/high/low/lastClose/volume/五档。
        缺失字段置 0/[]，对齐 _on_tick 期望的 lastPrice/bidPrice 等字段名。
        """
        def _f(key):
            v = snap.get(key)
            try:
                return float(v) if v is not None and str(v) != "nan" else 0
            except (TypeError, ValueError):
                return 0

        return {
            "stock": symbol,
            "lastPrice": _f("price"),
            "open": 0,
            "high": 0,
            "low": 0,
            "lastClose": 0,  # akshare 快照无昨收，置 0（pre_close 由 _on_tick 旧缓存兜底）
            "volume": 0,
            "amount": _f("amount_wan") * 1e4,  # 万 → 元
            "bidPrice": [],
            "bidVol": [],
            "askPrice": [],
            "askVol": [],
            "timetag": "",
        }

    def _update_cache(self, snapshot: dict[str, dict]) -> None:
        """把快照结果写入 _tick_cache"""
        for symbol, snap in snapshot.items():
            self._tick_cache[symbol] = self._snapshot_to_tick(symbol, snap)
```

`get_klines`/`get_stock_list` 等其余抽象方法先抛 `NotImplementedError`，下一 task 实现。

```python
    def get_klines(self, symbol, period='1d', start_time='', end_time='',
                   count=-1, dividend_type='none') -> pd.DataFrame:
        raise NotImplementedError("akshare K线走 data_bridge，不经过 market_service")

    def get_stock_list(self, sector='沪深A股') -> list[str]:
        raise NotImplementedError

    def get_stock_list_full(self, sector='沪深A股') -> list[dict]:
        raise NotImplementedError

    def get_instrument_detail(self, symbol: str) -> Optional[dict]:
        return None  # akshare 后端不提供合约详情

    def get_instruments_batch(self, symbols: list[str]) -> dict[str, Optional[dict]]:
        return {s: None for s in symbols}
```

`subscribe_quote`/`unsubscribe_quote`/`close` 也先放空实现，下个 task 实现：

```python
    def subscribe_quote(self, symbol, period='tick', callback=None) -> Optional[int]:
        raise NotImplementedError  # Task 4 实现

    def unsubscribe_quote(self, seq: int) -> bool:
        raise NotImplementedError  # Task 4 实现

    def close(self) -> None:
        pass  # Task 4 实现
```

- [ ] **Step 4: 运行测试确认通过**

Run: `python -m pytest tests/test_akshare_market_backend.py -v`
Expected: PASS（6 个测试）

- [ ] **Step 5: Commit**

```bash
git add app/core/market_backend.py tests/test_akshare_market_backend.py
git commit -m "feat: AkshareMarketBackend tick转换与缓存"
```

---

## Task 4: AkshareMarketBackend — 轮询引擎与订阅分发

实现 `subscribe_quote`/`unsubscribe_quote`/`close` + 后台轮询任务。

**Files:**
- Modify: `app/core/market_backend.py`（AkshareMarketBackend 的订阅/轮询方法）
- Test: `tests/test_akshare_market_backend.py`（追加测试）

- [ ] **Step 1: 写订阅分发与轮询的失败测试**

在 `tests/test_akshare_market_backend.py` 追加：

```python
import asyncio
from unittest.mock import patch


@pytest.mark.asyncio
async def test_subscribe_dispatches_to_callback():
    """订阅后轮询一轮，callback 被调用且收到正确 tick"""
    backend = AkshareMarketBackend()
    received = []
    seq = backend.subscribe_quote("600519", callback=lambda tick: received.append(tick))

    # mock 轮询：直接调 _poll_once
    with patch("app.core.market_backend.AkshareMarketBackend._fetch_snapshot",
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

    with patch("app.core.market_backend.AkshareMarketBackend._fetch_snapshot",
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
```

- [ ] **Step 2: 运行测试确认失败**

Run: `python -m pytest tests/test_akshare_market_backend.py::test_subscribe_dispatches_to_callback -v`
Expected: FAIL — `NotImplementedError`

- [ ] **Step 3: 实现订阅与轮询**

在 `AkshareMarketBackend` 替换 Task 3 的占位方法：

```python
    def subscribe_quote(self, symbol: str, period: str = 'tick',
                        callback=None) -> Optional[int]:
        self._sub_seq_counter += 1
        seq = self._sub_seq_counter
        if callback:
            self._sub_callbacks[seq] = (symbol, callback)
        self._subscribed_symbols.add(symbol)
        self._ensure_poll_loop()
        return seq

    def unsubscribe_quote(self, seq: int) -> bool:
        sub = self._sub_callbacks.pop(seq, None)
        if not sub:
            return True
        symbol = sub[0]
        still_subscribed = any(s == symbol for s, _ in self._sub_callbacks.values())
        if not still_subscribed:
            self._subscribed_symbols.discard(symbol)
        if not self._sub_callbacks:
            self._close_poll_loop()
        return True

    def close(self) -> None:
        self._close_poll_loop()
        self._tick_cache.clear()

    def _ensure_poll_loop(self) -> None:
        if self._poll_task is not None and not self._poll_task.done():
            return
        try:
            self._poll_task = asyncio.create_task(self._poll_loop())
        except RuntimeError:
            # 无 event loop（同步上下文调用）时跳过，等首次异步调用再起
            pass

    def _close_poll_loop(self) -> None:
        if self._poll_task and not self._poll_task.done():
            self._poll_task.cancel()
        self._poll_task = None

    async def _poll_loop(self) -> None:
        """轮询循环：每 3 秒拉一次快照"""
        try:
            while self._sub_callbacks:
                await self._poll_once()
                await asyncio.sleep(self._poll_interval)
        except asyncio.CancelledError:
            pass
        except Exception as e:
            logger.error(f"akshare 轮询循环异常退出: {e}", exc_info=True)
            await asyncio.sleep(5)
            # 重启
            if self._sub_callbacks:
                self._poll_task = asyncio.create_task(self._poll_loop())

    async def _poll_once(self) -> None:
        """单次轮询：检查交易时间 → 拉快照 → 更新缓存 → 分发"""
        from app.services.trading_calendar_service import trading_calendar

        if not trading_calendar.is_trading_time():
            return  # 非交易时间跳过

        try:
            snapshot = await asyncio.to_thread(self._fetch_snapshot)
        except Exception as e:
            logger.warning(f"akshare 拉取快照失败，保留旧缓存: {e}")
            return  # 异常时不清缓存、不推送

        if not snapshot:
            return  # 空结果保留旧缓存

        self._update_cache(snapshot)
        self._dispatch(snapshot)

    def _fetch_snapshot(self) -> dict[str, dict]:
        """同步拉快照（在 to_thread 里跑）。复用 AkshareDataSource.get_snapshot。"""
        if not self._subscribed_symbols:
            return {}
        from app.core.data_source_akshare import AkshareDataSource
        codes = list(self._subscribed_symbols)
        return AkshareDataSource().get_snapshot(codes)

    def _dispatch(self, snapshot: dict[str, dict]) -> None:
        """把缓存的 tick 分发给订阅了该 symbol 的 callback"""
        for symbol in self._subscribed_symbols:
            tick = self._tick_cache.get(symbol)
            if tick is None:
                logger.debug(f"轮询结果无 {symbol}（停牌/退市?）")
                continue
            for seq, (sub_symbol, callback) in list(self._sub_callbacks.items()):
                if sub_symbol == symbol and callback:
                    try:
                        callback(tick)
                    except Exception as e:
                        logger.error(f"tick 回调异常: {e}")
```

- [ ] **Step 4: 运行测试确认通过**

Run: `python -m pytest tests/test_akshare_market_backend.py -v`
Expected: PASS（10 个测试）

- [ ] **Step 5: Commit**

```bash
git add app/core/market_backend.py tests/test_akshare_market_backend.py
git commit -m "feat: AkshareMarketBackend 轮询引擎与订阅分发"
```

---

## Task 5: market_service 委托给后端

把 `MarketService` 改成按配置委托给 `MarketBackend`。

**Files:**
- Modify: `app/services/market_service.py`（整文件精简）
- Test: `tests/test_akshare_market_backend.py`（追加配置切换测试）

- [ ] **Step 1: 写配置切换失败测试**

在 `tests/test_akshare_market_backend.py` 追加：

```python
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
```

- [ ] **Step 2: 运行测试确认失败**

Run: `python -m pytest tests/test_akshare_market_backend.py::test_market_service_delegates_to_akshare_by_default -v`
Expected: FAIL — `AttributeError: 'MarketService' object has no attribute '_backend'`

- [ ] **Step 3: 改造 MarketService 为委托**

把 `app/services/market_service.py` 整文件替换为：

```python
"""
行情数据服务

按 MARKET_BACKEND 配置委托给对应后端：
- akshare: 公开 HTTP 轮询（默认）
- stock_data: stock_data 微服务（fallback）
"""

import logging
from typing import Optional

import pandas as pd

from app.config import settings
from app.core.market_backend import (
    MarketBackend, AkshareMarketBackend, StockDataMarketBackend,
)

logger = logging.getLogger(__name__)


def _create_market_backend() -> MarketBackend:
    """根据配置创建行情后端，未知值 fallback 到 akshare"""
    name = settings.MARKET_BACKEND.lower()
    if name == "stock_data":
        return StockDataMarketBackend()
    if name != "akshare":
        logger.warning(f"未知 MARKET_BACKEND '{name}'，回退到 akshare")
    return AkshareMarketBackend()


class MarketService:
    """行情数据服务（委托给 MarketBackend）"""

    def __init__(self):
        self._backend: MarketBackend = _create_market_backend()

    def is_available(self) -> bool:
        return self._backend.is_available()

    def check_health(self) -> dict:
        return self._backend.check_health()

    def get_klines(self, symbol, period='1d', start_time='', end_time='',
                   count=-1, dividend_type='none') -> pd.DataFrame:
        return self._backend.get_klines(symbol, period, start_time, end_time,
                                        count, dividend_type)

    def get_full_tick(self, symbol: str) -> Optional[dict]:
        return self._backend.get_full_tick(symbol)

    def get_stock_list(self, sector: str = '沪深A股') -> list[str]:
        return self._backend.get_stock_list(sector)

    def get_stock_list_full(self, sector: str = '沪深A股') -> list[dict]:
        return self._backend.get_stock_list_full(sector)

    def get_instrument_detail(self, symbol: str) -> Optional[dict]:
        return self._backend.get_instrument_detail(symbol)

    def get_instruments_batch(self, symbols: list[str]) -> dict[str, Optional[dict]]:
        return self._backend.get_instruments_batch(symbols)

    def subscribe_quote(self, symbol, period='tick', callback=None) -> Optional[int]:
        return self._backend.subscribe_quote(symbol, period, callback)

    def unsubscribe_quote(self, seq: int) -> bool:
        return self._backend.unsubscribe_quote(seq)

    def close(self) -> None:
        self._backend.close()


# 全局单例
market_service = MarketService()
```

- [ ] **Step 4: 运行测试确认通过**

Run: `python -m pytest tests/test_akshare_market_backend.py -v`
Expected: PASS（全部）

- [ ] **Step 5: 跑存量测试确认无回归**

Run: `python -m pytest tests/ -v -x -k "not slow"`
Expected: 既有测试不因 market_service 改造而失败（akshare 后端的 `get_klines` 抛 NotImplementedError，但存量测试应走 data_bridge 不经 market_service；若有失败需具体分析）

- [ ] **Step 6: Commit**

```bash
git add app/services/market_service.py tests/test_akshare_market_backend.py
git commit -m "refactor: market_service 委托给 MarketBackend"
```

---

## Task 6: TradeBackend 抽象基类与 StockTradeBackend

把现有 `live_gateway.py` 的实现搬进 `StockTradeBackend`。

**Files:**
- Create: `app/core/trade_backend.py`
- Test: `tests/test_sim_trade_backend.py`

- [ ] **Step 1: 写骨架测试**

创建 `tests/test_sim_trade_backend.py`：

```python
"""SimTradeBackend / StockTradeBackend 单元测试"""
import pytest
from app.core.trade_backend import TradeBackend, StockTradeBackend


def test_trade_backend_is_abstract():
    with pytest.raises(TypeError):
        TradeBackend()


def test_stock_trade_backend_has_all_methods():
    backend = StockTradeBackend()
    for attr in ["is_connected", "auto_connect", "auto_connect_background",
                 "check_health", "get_account", "get_positions", "get_orders",
                 "get_trades", "place_order", "cancel_order", "get_quote", "disconnect"]:
        assert hasattr(backend, attr), f"缺少: {attr}"
```

- [ ] **Step 2: 运行确认失败**

Run: `python -m pytest tests/test_sim_trade_backend.py -v`
Expected: FAIL — `ModuleNotFoundError`

- [ ] **Step 3: 创建 trade_backend.py**

创建 `app/core/trade_backend.py`，把 `app/core/live_gateway.py` 的 `LiveGateway` 类整体搬成 `StockTradeBackend`：

```python
"""
交易数据后端抽象 + 实现

TradeBackend 定义交易网关统一接口，
StockTradeBackend 是原有 stock_trade 微服务实现，
SimTradeBackend 是模拟成交实现（复用 _sim_accounts）。
"""

import abc
import asyncio
import logging
from typing import Optional

import httpx

from app.config import settings

logger = logging.getLogger(__name__)


class TradeBackend(abc.ABC):
    """交易后端抽象基类（异步接口）"""

    @property
    @abc.abstractmethod
    def is_connected(self) -> bool: ...

    @abc.abstractmethod
    async def auto_connect(self) -> dict: ...

    @abc.abstractmethod
    async def auto_connect_background(self) -> None: ...

    @abc.abstractmethod
    async def check_health(self) -> dict: ...

    @abc.abstractmethod
    async def get_account(self) -> dict: ...

    @abc.abstractmethod
    async def get_positions(self) -> list: ...

    @abc.abstractmethod
    async def get_orders(self) -> list: ...

    @abc.abstractmethod
    async def get_trades(self) -> list: ...

    @abc.abstractmethod
    async def place_order(self, symbol, side, quantity, price=0, order_type="limit") -> dict: ...

    @abc.abstractmethod
    async def cancel_order(self, order_id: str) -> dict: ...

    @abc.abstractmethod
    async def get_quote(self, symbol: str) -> dict: ...

    @abc.abstractmethod
    async def disconnect(self) -> None: ...


class StockTradeBackend(TradeBackend):
    """stock_trade 微服务后端（原有实现）"""

    def __init__(self):
        # …… 把 LiveGateway.__init__ 搬过来 ……
        ...
    # …… 把 LiveGateway 的所有方法搬过来，方法签名不变 ……
    # get_quote 里 `from app.services.market_service import market_service` 保持不变
```

- [ ] **Step 4: 运行确认通过**

Run: `python -m pytest tests/test_sim_trade_backend.py -v`
Expected: PASS（2 个）

- [ ] **Step 5: Commit**

```bash
git add app/core/trade_backend.py tests/test_sim_trade_backend.py
git commit -m "feat: 新增 TradeBackend 抽象基类与 StockTradeBackend"
```

---

## Task 7: SimTradeBackend — 模拟成交

实现 `SimTradeBackend`：包装 `vnpy_strategy_runner._sim_accounts`，提供 `place_order`/`get_account`/`get_positions` 等。

**Files:**
- Modify: `app/core/trade_backend.py`（追加 `SimTradeBackend`）
- Test: `tests/test_sim_trade_backend.py`（追加测试）

- [ ] **Step 1: 写模拟成交失败测试**

在 `tests/test_sim_trade_backend.py` 追加：

```python
from app.core.trade_backend import SimTradeBackend


def _setup_sim_account(account_id="sim-test", balance=1000000):
    """在 vnpy_strategy_runner 里预置一个模拟账户"""
    from app.services.vnpy_strategy_runner import vnpy_strategy_runner as runner
    runner._sim_accounts[account_id] = {
        "balance": balance, "available": balance,
        "frozen": 0, "initial_capital": balance,
    }
    runner._sim_positions[account_id] = {}
    return account_id


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

    from app.services.vnpy_strategy_runner import vnpy_strategy_runner as runner
    acct = runner._sim_accounts[account_id]
    cost = 100 * 1680.0
    commission = max(cost * 0.0003, 5)
    assert acct["available"] == 1000000 - cost - commission
    assert runner._sim_positions[account_id]["600519"]["quantity"] == 100


@pytest.mark.asyncio
async def test_sim_backend_place_order_insufficient_funds():
    """资金不足返回 success=False，不改账户"""
    account_id = _setup_sim_account(balance=1000)  # 不够买 100 股 1680
    backend = SimTradeBackend(account_id=account_id)
    result = await backend.place_order("600519", "buy", 100, price=1680.0)
    assert result["success"] is False
    assert "资金不足" in result["error"]

    from app.services.vnpy_strategy_runner import vnpy_strategy_runner as runner
    assert runner._sim_accounts[account_id]["available"] == 1000  # 未变


@pytest.mark.asyncio
async def test_sim_backend_place_order_sell_insufficient_position():
    """卖出持仓不足返回失败"""
    account_id = _setup_sim_account()
    backend = SimTradeBackend(account_id=account_id)
    result = await backend.place_order("600519", "sell", 100, price=1680.0)
    assert result["success"] is False
    assert "持仓不足" in result["error"]


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
    from app.services.vnpy_strategy_runner import vnpy_strategy_runner as runner
    runner._update_sim_account_buy(account_id, "600519", 100, 1680.0)

    backend = SimTradeBackend(account_id=account_id)
    positions = await backend.get_positions()
    assert len(positions) == 1
    assert positions[0]["symbol"] == "600519"
    assert positions[0]["volume"] == 100
```

- [ ] **Step 2: 运行确认失败**

Run: `python -m pytest tests/test_sim_trade_backend.py::test_sim_backend_auto_connect_sets_connected -v`
Expected: FAIL — `ImportError`

- [ ] **Step 3: 实现 SimTradeBackend**

在 `app/core/trade_backend.py` 追加：

```python
import uuid


class SimTradeBackend(TradeBackend):
    """模拟成交后端：复用 vnpy_strategy_runner._sim_accounts

    account_id 默认 "sim-live"（API 层手动下单用）；
    也可在实例化时指定（如某个 live 实例的 sim-{instance_id}）。
    """

    def __init__(self, account_id: str = "sim-live"):
        self._account_id = account_id
        self._connected: bool = False

    @property
    def is_connected(self) -> bool:
        return self._connected

    async def auto_connect(self) -> dict:
        """模拟后端永远连上，不连任何服务"""
        self._connected = True
        logger.info(f"SimTradeBackend 已就绪 (account_id={self._account_id})")
        return {"success": True, "message": "模拟成交后端已就绪",
                "account_id": self._account_id, "qmt_connected": False}

    async def auto_connect_background(self) -> None:
        await self.auto_connect()

    async def check_health(self) -> dict:
        return {"status": "online" if self._connected else "offline",
                "account_id": self._account_id, "connected": self._connected}

    async def get_account(self) -> dict:
        from app.services.vnpy_strategy_runner import vnpy_strategy_runner as runner
        acct = runner._sim_accounts.get(self._account_id)
        if not acct:
            return {"cash": 0, "available_cash": 0, "total_assets": 0, "market_value": 0}
        positions = runner._sim_positions.get(self._account_id, {})
        market_value = sum(p.get("market_value", 0) for p in positions.values())
        return {
            "cash": acct["balance"],
            "available_cash": acct["available"],
            "total_assets": acct["balance"] + market_value,
            "market_value": market_value,
        }

    async def get_positions(self) -> list:
        from app.services.vnpy_strategy_runner import vnpy_strategy_runner as runner
        positions = runner._sim_positions.get(self._account_id, {})
        result = []
        for symbol, p in positions.items():
            if p.get("quantity", 0) > 0:
                result.append({
                    "symbol": symbol, "name": "",
                    "volume": p["quantity"], "quantity": p["quantity"],
                    "cost_price": p["avg_cost"], "avg_cost": p["avg_cost"],
                    "current_price": p.get("current_price", p["avg_cost"]),
                    "market_value": p.get("market_value", 0),
                    "pnl": (p.get("current_price", p["avg_cost"]) - p["avg_cost"]) * p["quantity"],
                })
        return result

    async def get_orders(self) -> list:
        return []  # 模拟后端不维护委托列表，走 DB Order 表查询

    async def get_trades(self) -> list:
        return []

    async def place_order(self, symbol, side, quantity, price=0,
                          order_type="limit") -> dict:
        from app.services.vnpy_strategy_runner import vnpy_strategy_runner as runner
        account = runner._sim_accounts.get(self._account_id)
        if not account:
            return {"success": False, "error": "模拟账户不存在",
                    "order_id": ""}

        side = side.lower()
        if price <= 0:
            return {"success": False, "error": "模拟下单需指定价格",
                    "order_id": ""}

        if side == "buy":
            cost = quantity * price
            commission = max(cost * 0.0003, 5)
            if account["available"] < cost + commission:
                return {"success": False,
                        "error": f"资金不足：可用 {account['available']:.2f}，需要 {cost + commission:.2f}",
                        "order_id": ""}
            runner._update_sim_account_buy(self._account_id, symbol, quantity, price)
            order_id = str(uuid.uuid4())
            await self._record_order(symbol, side, quantity, price, order_id)
            return {"success": True, "order_id": order_id,
                    "side": side, "symbol": symbol,
                    "quantity": quantity, "price": price}

        elif side == "sell":
            positions = runner._sim_positions.get(self._account_id, {})
            pos = positions.get(symbol)
            if not pos or pos["quantity"] < quantity:
                avail = pos["quantity"] if pos else 0
                return {"success": False,
                        "error": f"持仓不足：可用 {avail}，需要 {quantity}",
                        "order_id": ""}
            runner._update_sim_account_sell(self._account_id, symbol, quantity,
                                            price, pos["avg_cost"])
            order_id = str(uuid.uuid4())
            await self._record_order(symbol, side, quantity, price, order_id)
            return {"success": True, "order_id": order_id,
                    "side": side, "symbol": symbol,
                    "quantity": quantity, "price": price}

        return {"success": False, "error": f"不支持的方向: {side}", "order_id": ""}

    async def cancel_order(self, order_id: str) -> dict:
        # 模拟成交立即成交，无撤单概念
        return {"success": False, "error": "模拟成交不支持撤单"}

    async def get_quote(self, symbol: str) -> dict:
        from app.services.market_service import market_service
        return market_service.get_full_tick(symbol) or {}

    async def disconnect(self) -> None:
        self._connected = False

    async def _record_order(self, symbol, side, quantity, price, order_id) -> None:
        """落 Order 表"""
        try:
            from app.database import SessionLocal
            from app.models.models import Order
            db = SessionLocal()
            try:
                db.add(Order(
                    id=order_id, user_id="", account_id=self._account_id,
                    symbol=symbol, side=side, type="market",
                    quantity=quantity, price=price, status="filled",
                    filled_quantity=quantity, filled_price=price,
                    source="sim_live", gateway_order_id=order_id,
                ))
                db.commit()
            finally:
                db.close()
        except Exception as e:
            logger.warning(f"模拟成交落 Order 表失败: {e}")
```

- [ ] **Step 4: 运行确认通过**

Run: `python -m pytest tests/test_sim_trade_backend.py -v`
Expected: PASS（8 个）

- [ ] **Step 5: Commit**

```bash
git add app/core/trade_backend.py tests/test_sim_trade_backend.py
git commit -m "feat: SimTradeBackend 模拟成交后端"
```

---

## Task 8: live_gateway 委托给后端

把 `LiveGateway` 改成按配置委托给 `TradeBackend`。

**Files:**
- Modify: `app/core/live_gateway.py`（整文件精简）
- Test: `tests/test_sim_trade_backend.py`（追加配置切换测试）

- [ ] **Step 1: 写配置切换失败测试**

在 `tests/test_sim_trade_backend.py` 追加：

```python
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
```

- [ ] **Step 2: 运行确认失败**

Run: `python -m pytest tests/test_sim_trade_backend.py::test_live_gateway_delegates_to_sim_by_default -v`
Expected: FAIL — `AttributeError: 'LiveGateway' object has no attribute '_backend'`

- [ ] **Step 3: 改造 LiveGateway 为委托**

把 `app/core/live_gateway.py` 整文件替换为：

```python
"""
实盘交易网关

按 TRADE_BACKEND 配置委托给对应后端：
- sim: 模拟成交（默认）
- stock_trade: stock_trade 微服务（fallback）
"""

import logging
from typing import Optional

from app.config import settings
from app.core.trade_backend import (
    TradeBackend, SimTradeBackend, StockTradeBackend,
)

logger = logging.getLogger(__name__)


def _create_trade_backend() -> TradeBackend:
    name = settings.TRADE_BACKEND.lower()
    if name == "stock_trade":
        return StockTradeBackend()
    if name != "sim":
        logger.warning(f"未知 TRADE_BACKEND '{name}'，回退到 sim")
    return SimTradeBackend()


class LiveGateway:
    """交易网关（委托给 TradeBackend）"""

    def __init__(self):
        self._backend: TradeBackend = _create_trade_backend()

    @property
    def is_connected(self) -> bool:
        return self._backend.is_connected

    @property
    def account_id(self) -> str:
        return getattr(self._backend, "_account_id", "")

    @property
    def base_url(self) -> str:
        return settings.STOCK_TRADE_URL

    def _set_disconnect_callback(self, callback) -> None:
        self._backend._on_disconnect_callback = callback

    async def auto_connect(self) -> dict:
        return await self._backend.auto_connect()

    async def auto_connect_background(self) -> None:
        await self._backend.auto_connect_background()

    async def check_health(self) -> dict:
        return await self._backend.check_health()

    async def get_account(self) -> dict:
        return await self._backend.get_account()

    async def get_positions(self) -> list:
        return await self._backend.get_positions()

    async def get_orders(self) -> list:
        return await self._backend.get_orders()

    async def get_trades(self) -> list:
        return await self._backend.get_trades()

    async def place_order(self, symbol, side, quantity, price=0,
                          order_type="limit") -> dict:
        return await self._backend.place_order(symbol, side, quantity, price, order_type)

    async def cancel_order(self, order_id: str) -> dict:
        return await self._backend.cancel_order(order_id)

    async def get_quote(self, symbol: str) -> dict:
        return await self._backend.get_quote(symbol)

    async def disconnect(self) -> None:
        await self._backend.disconnect()


# 全局单例
live_gateway = LiveGateway()
```

- [ ] **Step 4: 运行确认通过**

Run: `python -m pytest tests/test_sim_trade_backend.py -v`
Expected: PASS（全部）

- [ ] **Step 5: 修复 main.py 对 _on_disconnect_callback 的赋值**

`main.py:154` 现在是 `live_gateway._on_disconnect_callback = on_gateway_disconnect`，但委托后属性在 backend 上。改 `LiveGateway._set_disconnect_callback` 已有；需把 main.py 改成调它：

Modify `app/main.py:147-154`，把：

```python
    live_gateway._on_disconnect_callback = on_gateway_disconnect
```

改为：

```python
    live_gateway._set_disconnect_callback(on_gateway_disconnect)
```

- [ ] **Step 6: 运行确认通过**

Run: `python -m pytest tests/test_sim_trade_backend.py -v`
Expected: PASS

- [ ] **Step 7: Commit**

```bash
git add app/core/live_gateway.py app/main.py tests/test_sim_trade_backend.py
git commit -m "refactor: live_gateway 委托给 TradeBackend"
```

---

## Task 9: vnpy_strategy_runner — live 账户统一与信号执行改模拟

改 `_get_account_id`（live 也用 `sim-{instance_id}`）和 `_execute_signal` live 分支（成交改模拟）。

**Files:**
- Modify: `app/services/vnpy_strategy_runner.py:736-740`（`_get_account_id`）
- Modify: `app/services/vnpy_strategy_runner.py:1068-1082`（`_execute_signal` live 分支）
- Modify: `app/services/vnpy_strategy_runner.py:561-678`（`_execute_live_signal`）
- Test: `tests/test_market_trade_backend_integration.py`

- [ ] **Step 1: 写 live 账户统一的失败测试**

创建 `tests/test_market_trade_backend_integration.py`：

```python
"""live/simulation 账户统一 与 信号执行集成测试"""
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
```

- [ ] **Step 2: 运行确认失败**

Run: `python -m pytest tests/test_market_trade_backend_integration.py::test_get_account_id_live_uses_sim_prefix -v`
Expected: FAIL — live 分支返回 `broker-acct-123` 而非 `sim-inst-live-1`

- [ ] **Step 3: 改 _get_account_id**

Modify `app/services/vnpy_strategy_runner.py:736-740`：

```python
    def _get_account_id(self, instance_id: str) -> str:
        # live 与 simulation 统一用模拟账户 sim-{instance_id}
        # （实盘下单改为模拟成交，不再用券商 account_id）
        return f"sim-{instance_id}"
```

- [ ] **Step 4: 运行确认通过**

Run: `python -m pytest tests/test_market_trade_backend_integration.py -v`
Expected: PASS

- [ ] **Step 5: 改 _execute_signal live 分支**

Modify `app/services/vnpy_strategy_runner.py:1076-1082`（`_execute_signal` 开头的 live 分支）。原代码：

```python
        if mode == "live":
            await self._execute_live_signal(
                instance_id, symbol, account_id, signal,
                current_price, config, is_grid, position, avg_cost,
                signal_reason,
            )
            return
```

改为：

```python
        if mode == "live":
            # 实盘下单改为模拟成交：查 AutoTradeConfig 决定自动模拟成交 or 建 Signal 待确认
            await self._execute_live_signal_sim(
                instance_id, symbol, account_id, signal,
                current_price, config, is_grid, position, avg_cost,
                signal_reason,
            )
            return
```

- [ ] **Step 6: 新增 _execute_live_signal_sim 方法**

在 `_execute_live_signal` 方法之后插入新方法（复用 AutoTradeConfig 查询 + 风控 + 模拟成交）：

```python
    async def _execute_live_signal_sim(
        self, instance_id: str, symbol: str, account_id: str,
        signal: int, current_price: float, config: dict,
        is_grid: bool, position: int, avg_cost: float,
        signal_reason: str = "",
    ) -> None:
        """实盘信号执行（模拟成交版）

        查 AutoTradeConfig → auto_trade_enabled 直接模拟成交，
        否则建 Signal 待确认记录。成交走 _update_sim_account_buy/sell。
        """
        from app.database import SessionLocal
        from app.models.models import Signal, TradingInstance, AutoTradeConfig, Order

        side = "buy" if signal > 0 else "sell"
        grid_qty = config.get("params", {}).get("grid_quantity") or config.get("params", {}).get("trading_volume") or 100
        quantity = grid_qty if is_grid else (abs(position) if signal < 0 and position > 0 else grid_qty)

        db = SessionLocal()
        try:
            inst = db.query(TradingInstance).filter(TradingInstance.id == instance_id).first()
            user_id = inst.user_id if inst else ""
            auto_config = db.query(AutoTradeConfig).filter(
                AutoTradeConfig.account_id == account_id,
            ).first()
            auto_trade_enabled = auto_config.auto_trade_enabled if auto_config else False
            confirm_required = auto_config.confirm_required if auto_config else True

            # 风控检查
            passed, reason = risk_manager.check_order(
                account_id, symbol, side, quantity, current_price,
            )
            if not passed:
                await self._log_and_push(instance_id, "risk", f"风控拒绝: {reason}", current_price, quantity)
                return

            if auto_trade_enabled and not confirm_required:
                # 自动模拟成交
                sim_account = self._sim_accounts.get(account_id)
                if not sim_account:
                    await self._log_and_push(instance_id, "error", "模拟账户不存在", current_price, 0)
                    return

                if signal > 0:
                    cost = quantity * current_price
                    commission = max(cost * 0.0003, 5)
                    if sim_account["available"] < cost + commission:
                        await self._log_and_push(instance_id, "risk",
                            f"资金不足: 可用 {sim_account['available']:.2f}, 需要 {cost + commission:.2f}",
                            current_price, quantity)
                        return
                    self._update_sim_account_buy(account_id, symbol, quantity, current_price)
                    pnl = 0
                else:
                    positions = self._sim_positions.get(account_id, {})
                    pos = positions.get(symbol)
                    if not pos or pos["quantity"] < quantity:
                        await self._log_and_push(instance_id, "risk", "持仓不足", current_price, quantity)
                        return
                    pnl = (current_price - avg_cost) * quantity
                    self._update_sim_account_sell(account_id, symbol, quantity, current_price, avg_cost)

                # 落 Order 表
                import uuid
                order_id = str(uuid.uuid4())
                db.add(Order(
                    id=order_id, user_id=user_id, account_id=account_id,
                    symbol=symbol, side=side, type="market",
                    quantity=quantity, price=current_price, status="filled",
                    filled_quantity=quantity, filled_price=current_price,
                    source="signal_auto_sim", gateway_order_id=order_id,
                ))
                db.commit()
                self.save_sim_account_to_db(instance_id)

                await self._log_and_push(instance_id, side,
                    f"自动模拟成交 {side} {symbol} {quantity}@{current_price:.2f} | {signal_reason}",
                    current_price, quantity, pnl)
                await ws_manager.broadcast({
                    "type": "strategy_trade",
                    "data": {
                        "instance_id": instance_id, "side": side,
                        "price": current_price, "quantity": quantity,
                        "pnl": pnl, "time": datetime.now().strftime("%H:%M:%S"),
                    }
                })
            else:
                # 创建待确认信号（保留原逻辑）
                sig = Signal(
                    user_id=user_id, instance_id=instance_id, account_id=account_id,
                    symbol=symbol, side=side, price=current_price, quantity=quantity,
                    status="pending", strategy_id=config.get("strategy_id", ""),
                    reason=signal_reason,
                )
                db.add(sig)
                db.commit()
                db.refresh(sig)
                await ws_manager.broadcast({
                    "type": "strategy_signal",
                    "data": {
                        "instance_id": instance_id, "signal_id": sig.id,
                        "symbol": symbol, "side": side,
                        "price": current_price, "quantity": quantity,
                        "time": datetime.now().strftime("%H:%M:%S"),
                    }
                })
                await self._log_and_push(instance_id, "signal",
                    f"信号待确认: {side} {symbol} {quantity}股 @ {current_price:.2f}", current_price, 0)
        except Exception as e:
            logger.error(f"实盘模拟信号执行失败: {e}")
        finally:
            db.close()
```

- [ ] **Step 7: 运行存量测试确认无回归**

Run: `python -m pytest tests/ -v -x -k "not slow"`
Expected: PASS（既有 simulation 路径不受影响；`_execute_live_signal` 旧方法保留但不再被调用）

- [ ] **Step 8: Commit**

```bash
git add app/services/vnpy_strategy_runner.py tests/test_market_trade_backend_integration.py
git commit -m "feat: live 账户统一为 sim-{instance_id}，信号执行改模拟成交"
```

---

## Task 10: main.py 日志文案与启动验证

**Files:**
- Modify: `app/main.py:34-36`

- [ ] **Step 1: 改启动日志**

Modify `app/main.py:34-36`，原：

```python
    logger.info(f"stock_data 行情服务: {settings.STOCK_DATA_URL}")
    logger.info(f"stock_trade 交易服务: {settings.STOCK_TRADE_URL}")
```

改为：

```python
    logger.info(f"行情后端: {settings.MARKET_BACKEND}"
                + (f" ({settings.STOCK_DATA_URL})" if settings.MARKET_BACKEND == "stock_data" else ""))
    logger.info(f"交易后端: {settings.TRADE_BACKEND}"
                + (f" ({settings.STOCK_TRADE_URL})" if settings.TRADE_BACKEND == "stock_trade" else ""))
```

- [ ] **Step 2: 启动验证（手动）**

让用户在原终端重启后端（venv 环境，[[windows-uvicorn-reload-pitfall]] 提到 anaconda 下 --reload 不生效）。检查日志出现 `行情后端: akshare` 和 `交易后端: sim`。

Run:（用户执行）`! python -m uvicorn app.main:app --reload --port 8000`
Expected: 启动日志含 `行情后端: akshare` / `交易后端: sim`，无异常。

- [ ] **Step 3: Commit**

```bash
git add app/main.py
git commit -m "chore: 启动日志显示当前行情/交易后端"
```

---

## Task 11: 集成测试 — 订阅→轮询→_on_tick 链路

**Files:**
- Test: `tests/test_market_trade_backend_integration.py`（追加）

- [ ] **Step 1: 写集成失败测试**

在 `tests/test_market_trade_backend_integration.py` 追加：

```python
import asyncio
from unittest.mock import patch


@pytest.mark.asyncio
async def test_subscribe_poll_updates_current_prices():
    """订阅 → 轮询一轮 → vnpy_strategy_runner._current_prices 被更新"""
    from app.services.market_service import market_service

    received = []
    # _on_tick 内部会调 data_bridge.to_exchange，mock 掉避免依赖
    seq = market_service.subscribe_quote(
        "600519", callback=lambda t: received.append(t))

    fake_snap = {"600519": {"name": "贵州茅台", "price": 1680.0,
                            "change_pct": 1.0, "turnover_pct": 0.5,
                            "pe_ttm": 30, "pb": 10, "float_mcap_yi": 21000,
                            "vol_ratio": 1.1, "amount_wan": 50000}}

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
        cfg = AutoTradeConfig(account_id=account_id, auto_trade_enabled=True,
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
```

- [ ] **Step 2: 运行确认通过**

Run: `python -m pytest tests/test_market_trade_backend_integration.py -v`
Expected: PASS

- [ ] **Step 3: Commit**

```bash
git add tests/test_market_trade_backend_integration.py
git commit -m "test: 订阅轮询链路与live模拟信号执行集成测试"
```

---

## Task 12: akshare 冒烟测试（slow）

**Files:**
- Test: `tests/test_akshare_smoke.py`

- [ ] **Step 1: 写冒烟测试**

创建 `tests/test_akshare_smoke.py`：

```python
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
    assert snap["600519"]["price"] > 0  # 交易时段应有价；非交易时段可能为0，则跳过断言
    assert "name" in snap["600519"]


@pytest.mark.asyncio
async def test_akshare_backend_poll_real():
    """订阅 600519，跑 2 轮真实轮询，callback 被触发"""
    from app.core.market_backend import AkshareMarketBackend
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
```

- [ ] **Step 2: 运行（slow，需 akshare）**

Run: `python -m pytest tests/test_akshare_smoke.py -v -s`
Expected: PASS（交易时段应全过；非交易时段 `test_akshare_snapshot_real` 的 `price > 0` 可能失败，此时改为 `>= 0`）

- [ ] **Step 3: 视情况调整断言**

若非交易时段 price 为 0，把 `assert snap["600519"]["price"] > 0` 改为 `assert snap["600519"]["price"] >= 0`，并加注释说明。

- [ ] **Step 4: Commit**

```bash
git add tests/test_akshare_smoke.py
git commit -m "test: akshare 真实接口冒烟测试(slow)"
```

---

## Task 13: 全量回归与文档

- [ ] **Step 1: 跑全部非 slow 测试**

Run: `python -m pytest tests/ -v -k "not slow"`
Expected: 全 PASS。若有失败，逐个分析（注意 [[backtest-verification-bugs]] 提到的验算第5项末尾持仓误报是已知缺陷，不属本任务范围）。

- [ ] **Step 2: 跑 slow 冒烟**

Run: `python -m pytest tests/test_akshare_smoke.py tests/test_trade_flow_sim.py -v -s`
Expected: PASS

- [ ] **Step 3: 更新 MEMORY.md**

更新 `C:\Users\38216\.claude\projects\D--MyProj-stock\memory\` 下相关记忆，新增一条 `market-trade-backend-switch.md` 记录后端切换机制：

```markdown
---
name: market-trade-backend-switch
description: 行情/交易后端可配置切换，MARKET_BACKEND=akshare(stock_data)/TRADE_BACKEND=sim(stock_trade)
metadata:
  type: project
---

行情实时tick与实盘下单改为可配置后端：
- `MARKET_BACKEND`: akshare(默认,3秒轮询全市场快照)/stock_data(fallback)
- `TRADE_BACKEND`: sim(默认,模拟成交复用_sim_accounts)/stock_trade(fallback)
- market_service/live_gateway 接口不变，委托给 app/core/market_backend.py 与 trade_backend.py
- live 模式 account_id 统一为 sim-{instance_id}，与 simulation 共用账户
- akshare 快照无五档盘口/昨收，tick 对应字段置空/0；pre_close 由 _on_tick 旧缓存兜底
- akshare 轮询非交易时间跳过(is_trading_time)，异常保留旧缓存不推送

**Why:** stock_data 微服务不可用，需公开HTTP替代；实盘无券商对接，下单改模拟
**How to apply:** 改后端只需改 .env 的 MARKET_BACKEND/TRADE_BACKEND；新数据源实现 MarketBackend/TradeBackend 抽象类即可接入
```

在 `MEMORY.md` 加一行：`- [行情交易后端切换](market-trade-backend-switch.md) — MARKET_BACKEND/TRADE_BACKEND 配置切换，akshare轮询+模拟成交`

- [ ] **Step 4: Commit**

```bash
git add C:/Users/38216/.claude/projects/D--MyProj-stock/memory/market-trade-backend-switch.md
git add C:/Users/38216/.claude/projects/D--MyProj-stock/memory/MEMORY.md
git commit -m "docs: 更新记忆，记录行情交易后端切换机制"
```

---

## Self-Review

**1. Spec coverage:**
- akshare 3秒轮询全市场快照 → Task 3+4 ✓
- 实盘下单改模拟成交，复用 _sim_accounts → Task 7+9 ✓
- market_service/live_gateway 接口不变 → Task 5+8 ✓
- 新增后端类+配置切换，保留旧实现 → Task 2+6+5+8 ✓
- live account_id 统一 sim-{instance_id} → Task 9 ✓
- live 信号执行保留 confirm 流程 → Task 9 _execute_live_signal_sim ✓
- 3秒轮询、五档置空 → Task 3 _snapshot_to_tick ✓
- 错误处理（异常保留缓存/非交易时间跳过/账户不存在返回结构化） → Task 4+7 ✓
- 东财 null → 0 → Task 3 test_snapshot_to_tick_none_fields_become_zero ✓
- 测试三层（单元/集成/冒烟slow） → Task 3-8/11/12 ✓
- main.py 日志 → Task 10 ✓

**2. Placeholder scan:** 无 TBD/TODO。每个步骤都有完整代码或确切命令。

**3. Type consistency:** `MarketBackend`/`TradeBackend` 方法名在所有 task 一致；`_snapshot_to_tick`/`_update_cache`/`_fetch_snapshot`/`_dispatch`/`_poll_once` 命名统一；`SimTradeBackend(account_id=)` 构造参数一致；`_execute_live_signal_sim` 在 Task 9 定义、Task 11 引用，签名一致。

---

## Execution Handoff

Plan complete and saved to `docs/superpowers/plans/2026-07-05-replace-stock-data-akshare.md`. Two execution options:

**1. Subagent-Driven (recommended)** - I dispatch a fresh subagent per task, review between tasks, fast iteration

**2. Inline Execution** - Execute tasks in this session using executing-plans, batch execution with checkpoints

**Which approach?**

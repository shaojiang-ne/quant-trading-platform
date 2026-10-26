# Stable Backtest Data Source Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Implement tiered data source with auto-fallback for stable backtest data, adding mootdx (TDX TCP protocol) as the primary source.

**Architecture:** New `MootdxDataSource` (TDX TCP, never IP-banned) + `FallbackDataSource` (tiered auto-fallback with period-aware routing) + rate limiting on Eastmoney sources (akshare/efinance). Default data source changes from `akshare` to `auto`.

**Tech Stack:** mootdx>=0.11, pandas, threading (rate limiting), existing DataSourceProvider interface

---

## File Structure

| File | Action | Responsibility |
|------|--------|---------------|
| `backend/app/core/data_source_mootdx.py` | Create | MootdxDataSource: TDX TCP protocol, supports 1m-1d klines |
| `backend/app/core/data_source_fallback.py` | Create | FallbackDataSource: tiered auto-fallback, period-aware routing |
| `backend/app/core/data_source_akshare.py` | Modify | Add call-interval rate limiting (≥1.5s + jitter) |
| `backend/app/core/data_source_efinance.py` | Modify | Add call-interval rate limiting (≥1.5s + jitter) |
| `backend/app/core/data_bridge.py` | Modify | Register mootdx + auto sources, add factory function |
| `backend/app/config.py` | Modify | DATA_SOURCE default: "akshare" → "auto" |
| `backend/requirements.txt` | Modify | Add mootdx>=0.10.0 |

---

### Task 1: Install mootdx and verify connectivity

**Files:**
- Modify: `backend/requirements.txt`

- [ ] **Step 1: Add mootdx to requirements.txt**

Add `mootdx>=0.10.0` to `backend/requirements.txt` after the existing dependencies. Place it near the `httpx` line since it's a network client.

- [ ] **Step 2: Install mootdx**

Run: `cd D:/MyProj/stock/backend && ./venv/Scripts/pip.exe install "mootdx>=0.10.0"`

- [ ] **Step 3: Verify mootdx can connect and fetch daily + 1m data**

Run:
```bash
cd D:/MyProj/stock/backend && ./venv/Scripts/python.exe -c "
from mootdx.quotes import Quotes
client = Quotes.factory(market='std', multithread=False, heartbeat=False)
assert client is not None, 'Failed to connect'

df = client.bars(symbol='600519', frequency='day', start=0, offset=5)
assert not df.empty, 'No daily data'
assert 'open' in df.columns and 'close' in df.columns, 'Missing columns'

df1m = client.bars(symbol='600519', frequency='1m', start=0, offset=5)
assert not df1m.empty, 'No 1m data'

df_idx = client.index_bars(symbol='000001', frequency='day', start=0, offset=5)
assert not df_idx.empty, 'No index data'

print('ALL CHECKS PASSED')
print(f'Daily columns: {list(df.columns)}')
print(f'1m columns: {list(df1m.columns)}')
print(f'Index columns: {list(df_idx.columns)}')
"
```
Expected: `ALL CHECKS PASSED`

- [ ] **Step 4: Commit**

```bash
git add backend/requirements.txt
git commit -m "feat: add mootdx dependency for stable backtest data source"
```

---

### Task 2: Create MootdxDataSource

**Files:**
- Create: `backend/app/core/data_source_mootdx.py`

Key mootdx API details discovered from source inspection:

- **Connection**: `Quotes.factory(market='std', multithread=False, heartbeat=False)` — returns `StdQuotes` client
- **Stock klines**: `client.bars(symbol='600519', frequency='1m', start=0, offset=800)` — symbol is pure code (no suffix)
- **Index klines**: `client.index_bars(symbol='000001', frequency='day', start=0, offset=800)`
- **Frequency string mapping** (mootdx resolves via `FREQUENCY.index()`):
  - `'1m'` → index 8, `'5m'` → index 0, `'15m'` → index 1, `'30m'` → index 2
  - `'1h'` → index 3, `'day'` → index 4, `'week'` → index 5, `'mon'` → index 6
- **Market constants**: SH=1, SZ=0, BJ=2 (from `mootdx.consts`)
- **Return DataFrame columns**: `open, close, high, low, vol, amount, year, month, day, hour, minute, datetime, volume`
- **Index is DatetimeIndex** based on `datetime` column
- **FQ adjust is broken** in mootdx 0.11.x with pandas 2.x (`fillna(method=...)` deprecated). We skip mootdx's built-in fq and handle it ourselves: fetch raw data and apply adjustment factor from xdxr data, OR just fetch without fq and accept the limitation. For backtest accuracy, we'll use `adjust=None` (no fq) by default and document this — the same approach the tencent/sina sources use.
- **Max offset**: 800 bars per request. For date-range queries, we paginate by incrementing `start`.
- **Date filtering**: mootdx `bars()` uses positional offset, not date ranges. We fetch paginated data and filter by date in post-processing.

- [ ] **Step 1: Create `data_source_mootdx.py`**

```python
"""
通达信数据源

通过 mootdx 的 TCP 二进制协议（端口 7709）获取 A 股和指数K线数据。
永不封IP，是分钟线回测的首选数据源。
"""

import logging
from typing import Optional

import pandas as pd

from app.core.data_source import DataSourceProvider

logger = logging.getLogger(__name__)

# mootdx 周期字符串映射（mootdx FREQUENCY 列表的索引值）
_PERIOD_MAP = {
    "1m": "1m", "5m": "5m", "15m": "15m", "30m": "30m",
    "60m": "1h", "1h": "1h", "1d": "day", "1w": "week", "1mon": "mon",
}

# 复权方式：mootdx 的 fq 功能在 pandas 2.x 下有兼容性问题
# 这里统一不复权，让调用方自行处理
_ADJUST_MAP = {
    "front": None,   # mootdx fq broken with pandas 2.x
    "back": None,
    "none": None,
}

# 交易所后缀 → mootdx 的 market 参数值
_MARKET_MAP = {
    "SH": 1,
    "SZ": 0,
    "BJ": 2,
}

# mootdx 每次最多返回 800 条
_MAX_OFFSET = 800


def _parse_symbol(symbol: str) -> tuple[str, int]:
    """将 600519.SH 格式解析为 (纯代码, market)

    Returns:
        (code, market): e.g. ("600519", 1)
    """
    parts = symbol.split(".")
    if len(parts) == 2:
        code, suffix = parts[0], parts[1].upper()
        market = _MARKET_MAP.get(suffix, 1)
        return code, market
    # 无后缀时根据代码判断
    code = symbol
    if code.startswith("6") or code.startswith("9"):
        return code, 1  # SH
    if code.startswith("8") or code.startswith("4"):
        return code, 2  # BJ
    return code, 0  # SZ


def _is_index(symbol: str) -> bool:
    """判断是否为指数代码"""
    parts = symbol.split(".")
    code = parts[0]
    suffix = parts[1] if len(parts) > 1 else ""
    return (suffix == "SH" and code.startswith("000")) or \
           (suffix == "SZ" and code.startswith("399"))


class MootdxDataSource(DataSourceProvider):
    """通达信数据源（TCP 二进制协议，永不封IP）"""

    def __init__(self):
        self._client = None
        self._available: Optional[bool] = None

    def _get_client(self):
        """获取或创建 mootdx 连接（带重连）"""
        if self._client is not None:
            try:
                if not self._client.closed:
                    return self._client
            except Exception:
                pass

        try:
            from mootdx.quotes import Quotes
            client = Quotes.factory(market='std', multithread=False, heartbeat=False)
            if client is not None:
                self._client = client
                self._available = True
                return client
        except Exception as e:
            logger.warning(f"mootdx 连接失败: {e}")

        # 回退：尝试直接用 bestip 探测
        try:
            from mootdx.quotes import Quotes
            from mootdx.server import Bestip
            bestip = Bestip()
            bestip.run()
            client = Quotes.factory(market='std', multithread=False, heartbeat=False)
            if client is not None:
                self._client = client
                self._available = True
                return client
        except Exception as e:
            logger.warning(f"mootdx bestip 回退连接也失败: {e}")

        self._available = False
        return None

    def get_klines(
        self,
        symbol: str,
        period: str,
        start: str,
        end: str,
        dividend_type: str = "front",
    ) -> pd.DataFrame:
        """获取个股K线数据"""
        mootdx_period = _PERIOD_MAP.get(period)
        if not mootdx_period:
            logger.error(f"mootdx 不支持周期: {period}")
            return pd.DataFrame()

        if _is_index(symbol):
            return self.get_index_klines(symbol, period, start, end)

        code, market = _parse_symbol(symbol)
        client = self._get_client()
        if client is None:
            return pd.DataFrame()

        try:
            # 分页获取数据，直到覆盖日期范围
            all_dfs = []
            start_pos = 0
            while True:
                df = client.bars(
                    symbol=code,
                    frequency=mootdx_period,
                    start=start_pos,
                    offset=_MAX_OFFSET,
                )
                if df is None or df.empty:
                    break

                all_dfs.append(df)

                # 检查最早的数据是否已经早于 start 日期
                if len(df) < _MAX_OFFSET:
                    break
                first_dt = df.index[0]
                start_ts = pd.Timestamp(start)
                if first_dt <= start_ts:
                    break

                start_pos += _MAX_OFFSET

            if not all_dfs:
                return pd.DataFrame()

            df = pd.concat(all_dfs)
            df = df[~df.index.duplicated(keep='first')]
            return self._normalize(df, start, end)

        except Exception as e:
            logger.error(f"mootdx 获取K线失败 {symbol} {period}: {e}")
            self._client = None  # 标记需要重连
            return pd.DataFrame()

    def get_index_klines(
        self,
        index_code: str,
        period: str,
        start: str,
        end: str,
    ) -> pd.DataFrame:
        """获取指数K线数据"""
        mootdx_period = _PERIOD_MAP.get(period, "day")
        code, market = _parse_symbol(index_code)
        client = self._get_client()
        if client is None:
            return pd.DataFrame()

        try:
            all_dfs = []
            start_pos = 0
            while True:
                df = client.index_bars(
                    symbol=code,
                    frequency=mootdx_period,
                    start=start_pos,
                    offset=_MAX_OFFSET,
                )
                if df is None or df.empty:
                    break

                all_dfs.append(df)

                if len(df) < _MAX_OFFSET:
                    break
                first_dt = df.index[0]
                start_ts = pd.Timestamp(start)
                if first_dt <= start_ts:
                    break

                start_pos += _MAX_OFFSET

            if not all_dfs:
                return pd.DataFrame()

            df = pd.concat(all_dfs)
            df = df[~df.index.duplicated(keep='first')]
            return self._normalize(df, start, end)

        except Exception as e:
            logger.error(f"mootdx 获取指数K线失败 {index_code} {period}: {e}")
            self._client = None
            return pd.DataFrame()

    def _normalize(self, df: pd.DataFrame, start: str, end: str) -> pd.DataFrame:
        """将 mootdx 返回的 DataFrame 统一为标准格式"""
        if df.empty:
            return pd.DataFrame()

        # mootdx 返回的列: open, close, high, low, vol, amount, ..., datetime, volume
        result = pd.DataFrame({
            "date": df.index,
            "open": pd.to_numeric(df["open"], errors="coerce"),
            "high": pd.to_numeric(df["high"], errors="coerce"),
            "low": pd.to_numeric(df["low"], errors="coerce"),
            "close": pd.to_numeric(df["close"], errors="coerce"),
            "volume": pd.to_numeric(df.get("volume", df.get("vol", 0)), errors="coerce").fillna(0),
            "amount": pd.to_numeric(df.get("amount", 0), errors="coerce").fillna(0),
        })

        # 日期过滤
        start_ts = pd.Timestamp(start)
        end_ts = pd.Timestamp(end)
        result = result[(result["date"] >= start_ts) & (result["date"] <= end_ts)]

        result = result.dropna(subset=["date"])
        result = result.sort_values("date").reset_index(drop=True)
        return result[["date", "open", "high", "low", "close", "volume", "amount"]]

    def is_available(self) -> bool:
        """检查 mootdx 是否可用"""
        if self._available is not None:
            # 如果之前成功过，尝试复用
            if self._available and self._client is not None:
                try:
                    if not self._client.closed:
                        return True
                except Exception:
                    pass

        client = self._get_client()
        return client is not None

    def get_name(self) -> str:
        return "mootdx"
```

- [ ] **Step 2: Verify MootdxDataSource can be imported and connects**

Run:
```bash
cd D:/MyProj/stock/backend && PYTHONIOENCODING=utf-8 ./venv/Scripts/python.exe -c "
from app.core.data_source_mootdx import MootdxDataSource
ds = MootdxDataSource()
print(f'Available: {ds.is_available()}')
print(f'Name: {ds.get_name()}')

# Test daily klines
df = ds.get_klines('600519.SH', '1d', '2026-06-01', '2026-06-27')
print(f'Daily klines: {len(df)} rows')
print(df.head(3))

# Test 1m klines
df1m = ds.get_klines('600519.SH', '1m', '2026-06-26', '2026-06-27')
print(f'1m klines: {len(df1m)} rows')
print(df1m.head(3))

# Test index klines
df_idx = ds.get_index_klines('000001.SH', '1d', '2026-06-01', '2026-06-27')
print(f'Index klines: {len(df_idx)} rows')
print(df_idx.head(3))

print('ALL CHECKS PASSED')
"
```
Expected: All queries return non-empty DataFrames with columns `[date, open, high, low, close, volume, amount]`

- [ ] **Step 3: Commit**

```bash
git add backend/app/core/data_source_mootdx.py
git commit -m "feat: add MootdxDataSource (TDX TCP protocol, never IP-banned)"
```

---

### Task 3: Create FallbackDataSource

**Files:**
- Create: `backend/app/core/data_source_fallback.py`

- [ ] **Step 1: Create `data_source_fallback.py`**

```python
"""
分级自动降级数据源

按优先级依次尝试多个数据源，首个成功即返回。
自动跳过不可用的数据源，并记录降级事件供调试。
分钟线和日线使用不同的优先级链。
"""

import logging
from datetime import datetime
from typing import Optional

import pandas as pd

from app.core.data_source import DataSourceProvider

logger = logging.getLogger(__name__)

# 分钟线周期集合
_MINUTE_PERIODS = {"1m", "5m", "15m", "30m", "1h", "60m"}

# 分钟线数据源优先级（只尝试支持分钟线的源）
_MINUTE_SOURCE_ORDER = ["mootdx", "xtquant", "akshare"]

# 日线数据源优先级
_DAILY_SOURCE_ORDER = ["tencent", "mootdx", "baostock", "sina", "akshare"]

# 指数数据源优先级
_INDEX_SOURCE_ORDER = ["tencent", "mootdx", "baostock", "akshare"]


class FallbackDataSource(DataSourceProvider):
    """分级自动降级数据源"""

    def __init__(self, sources: dict[str, DataSourceProvider]):
        """
        Args:
            sources: 数据源名称到实例的映射，e.g. {"mootdx": MootdxDataSource(), ...}
        """
        self._sources = sources
        self._fallback_log: list[dict] = []

    def _get_ordered_sources(self, period: str, is_index: bool = False) -> list[tuple[str, DataSourceProvider]]:
        """根据周期和是否为指数，返回有序的数据源列表"""
        if period in _MINUTE_PERIODS:
            order = _MINUTE_SOURCE_ORDER
        elif is_index:
            order = _INDEX_SOURCE_ORDER
        else:
            order = _DAILY_SOURCE_ORDER

        result = []
        for name in order:
            source = self._sources.get(name)
            if source is not None:
                result.append((name, source))
        return result

    def get_klines(
        self,
        symbol: str,
        period: str,
        start: str,
        end: str,
        dividend_type: str = "front",
    ) -> pd.DataFrame:
        is_index = self._is_index(symbol)
        ordered = self._get_ordered_sources(period, is_index)

        last_error = None
        for name, source in ordered:
            if not source.is_available():
                logger.debug(f"[fallback] 跳过不可用数据源: {name}")
                continue
            try:
                df = source.get_klines(symbol, period, start, end, dividend_type)
                if df is not None and not df.empty:
                    logger.info(f"[fallback] {symbol} {period}: 使用 {name} 获取 {len(df)} 条数据")
                    return df
            except Exception as e:
                last_error = e
                self._log_fallback(name, symbol, period, str(e))
                continue

        logger.warning(f"[fallback] 所有数据源均失败: {symbol} {period}, 最后错误: {last_error}")
        return pd.DataFrame()

    def get_index_klines(
        self,
        index_code: str,
        period: str,
        start: str,
        end: str,
    ) -> pd.DataFrame:
        ordered = self._get_ordered_sources(period, is_index=True)

        last_error = None
        for name, source in ordered:
            if not source.is_available():
                continue
            try:
                df = source.get_index_klines(index_code, period, start, end)
                if df is not None and not df.empty:
                    logger.info(f"[fallback] {index_code} {period}(指数): 使用 {name} 获取 {len(df)} 条数据")
                    return df
            except Exception as e:
                last_error = e
                self._log_fallback(name, index_code, period, str(e))
                continue

        logger.warning(f"[fallback] 所有数据源均失败(指数): {index_code} {period}, 最后错误: {last_error}")
        return pd.DataFrame()

    def is_available(self) -> bool:
        """至少有一个数据源可用即为可用"""
        return any(s.is_available() for s in self._sources.values())

    def get_name(self) -> str:
        available = [n for n, s in self._sources.items() if s.is_available()]
        return f"auto({'+'.join(available)})"

    def get_fallback_log(self) -> list[dict]:
        """返回降级日志"""
        return self._fallback_log

    def _log_fallback(self, source_name: str, symbol: str, period: str, error: str):
        """记录降级事件"""
        entry = {
            "timestamp": datetime.now().isoformat(),
            "source": source_name,
            "symbol": symbol,
            "period": period,
            "error": error,
        }
        self._fallback_log.append(entry)
        logger.debug(f"[fallback] {source_name} 失败 ({symbol} {period}): {error}")

    @staticmethod
    def _is_index(symbol: str) -> bool:
        """判断是否为指数代码"""
        parts = symbol.split(".")
        code = parts[0]
        suffix = parts[1] if len(parts) > 1 else ""
        return (suffix == "SH" and code.startswith("000")) or \
               (suffix == "SZ" and code.startswith("399"))
```

- [ ] **Step 2: Verify FallbackDataSource can be imported and works**

Run:
```bash
cd D:/MyProj/stock/backend && PYTHONIOENCODING=utf-8 ./venv/Scripts/python.exe -c "
from app.core.data_source_fallback import FallbackDataSource
from app.core.data_source_mootdx import MootdxDataSource
from app.core.data_source_tencent import TencentDataSource

# Build sources dict
sources = {
    'mootdx': MootdxDataSource(),
    'tencent': TencentDataSource(),
}

fb = FallbackDataSource(sources)
print(f'Available: {fb.is_available()}')
print(f'Name: {fb.get_name()}')

# Test daily klines (should use tencent first for daily)
df = fb.get_klines('600519.SH', '1d', '2026-06-01', '2026-06-27')
print(f'Daily klines: {len(df)} rows')

# Test 1m klines (should use mootdx for minute)
df1m = fb.get_klines('600519.SH', '1m', '2026-06-26', '2026-06-27')
print(f'1m klines: {len(df1m)} rows')

print('ALL CHECKS PASSED')
"
```
Expected: Both queries return non-empty DataFrames

- [ ] **Step 3: Commit**

```bash
git add backend/app/core/data_source_fallback.py
git commit -m "feat: add FallbackDataSource with tiered auto-fallback"
```

---

### Task 4: Add rate limiting to akshare and efinance

**Files:**
- Modify: `backend/app/core/data_source_akshare.py`
- Modify: `backend/app/core/data_source_efinance.py`

- [ ] **Step 1: Add rate limiting to AkshareDataSource**

Add `import time, random, threading` at the top of `data_source_akshare.py`, then add class-level rate limiting attributes and a `_rate_limit()` method, and call it at the start of `get_klines()` and `get_index_klines()`:

Add after the existing imports:
```python
import threading
import time
import random
```

Add to the `AkshareDataSource` class (after `class AkshareDataSource(DataSourceProvider):`):
```python
    _last_call_time: float = 0
    _call_lock = threading.Lock()
    _MIN_CALL_INTERVAL: float = 1.5  # 秒，含抖动

    @classmethod
    def _rate_limit(cls):
        """东财请求限流：调用间隔 ≥1.5s + 随机抖动 0-0.5s"""
        with cls._call_lock:
            now = time.time()
            elapsed = now - cls._last_call_time
            min_interval = cls._MIN_CALL_INTERVAL + random.uniform(0, 0.5)
            if elapsed < min_interval:
                time.sleep(min_interval - elapsed)
            cls._last_call_time = time.time()
```

Add `self._rate_limit()` as the first line inside `get_klines()` (before `if _is_index(symbol):`) and as the first line inside `get_index_klines()` (before `try:`).

- [ ] **Step 2: Add rate limiting to EfinanceDataSource**

Same pattern as akshare. Add imports:
```python
import threading
import time
import random
```

Add to the `EfinanceDataSource` class:
```python
    _last_call_time: float = 0
    _call_lock = threading.Lock()
    _MIN_CALL_INTERVAL: float = 1.5

    @classmethod
    def _rate_limit(cls):
        """东财请求限流：调用间隔 ≥1.5s + 随机抖动 0-0.5s"""
        with cls._call_lock:
            now = time.time()
            elapsed = now - cls._last_call_time
            min_interval = cls._MIN_CALL_INTERVAL + random.uniform(0, 0.5)
            if elapsed < min_interval:
                time.sleep(min_interval - elapsed)
            cls._last_call_time = time.time()
```

Add `self._rate_limit()` as the first line inside `get_klines()` (before `if _is_index(symbol):`) and as the first line inside `get_index_klines()` (before `try:`).

- [ ] **Step 3: Verify rate-limited sources still work**

Run:
```bash
cd D:/MyProj/stock/backend && PYTHONIOENCODING=utf-8 ./venv/Scripts/python.exe -c "
import time
from app.core.data_source_akshare import AkshareDataSource

ds = AkshareDataSource()
print(f'akshare available: {ds.is_available()}')

t0 = time.time()
df1 = ds.get_klines('600519.SH', '1d', '2026-06-01', '2026-06-27')
t1 = time.time()
df2 = ds.get_klines('000001.SZ', '1d', '2026-06-01', '2026-06-27')
t2 = time.time()

print(f'First call: {t1-t0:.2f}s, Second call: {t2-t1:.2f}s')
print(f'Should see ~1.5-2s delay between calls due to rate limiting')
print(f'600519: {len(df1)} rows, 000001: {len(df2)} rows')
"
```
Expected: Second call should take ~1.5-2s longer than the first due to rate limiting

- [ ] **Step 4: Commit**

```bash
git add backend/app/core/data_source_akshare.py backend/app/core/data_source_efinance.py
git commit -m "feat: add rate limiting to akshare/efinance (Eastmoney) data sources"
```

---

### Task 5: Register new sources in data_bridge and change default config

**Files:**
- Modify: `backend/app/core/data_bridge.py`
- Modify: `backend/app/config.py`

- [ ] **Step 1: Update data_bridge.py imports and registration**

At the top of `data_bridge.py`, add the new imports:
```python
from app.core.data_source_mootdx import MootdxDataSource
from app.core.data_source_fallback import FallbackDataSource
```

Update the `_DATA_SOURCES` dict to add `mootdx` and `auto`:
```python
_DATA_SOURCES: dict[str, type[DataSourceProvider]] = {
    "mootdx": MootdxDataSource,
    "akshare": AkshareDataSource,
    "efinance": EfinanceDataSource,
    "baostock": BaostockDataSource,
    "sina": SinaDataSource,
    "tencent": TencentDataSource,
    "xtquant": XtquantDataSource,
}
```

Add a factory function for the `auto` (fallback) source after `_DATA_SOURCES`:
```python
def _create_auto_source() -> FallbackDataSource:
    """创建分级降级复合数据源"""
    from app.core.data_source_mootdx import MootdxDataSource
    from app.core.data_source_tencent import TencentDataSource
    from app.core.data_source_baostock import BaostockDataSource
    from app.core.data_source_sina import SinaDataSource
    from app.core.data_source_akshare import AkshareDataSource
    from app.core.data_source_xtquant import XtquantDataSource
    from app.core.data_source_fallback import FallbackDataSource

    sources = {
        "mootdx": MootdxDataSource(),
        "tencent": TencentDataSource(),
        "baostock": BaostockDataSource(),
        "sina": SinaDataSource(),
        "akshare": AkshareDataSource(),
        "xtquant": XtquantDataSource(),
    }
    return FallbackDataSource(sources)
```

Update the `get_data_source()` function to handle the `"auto"` case specially:
```python
def get_data_source(name: str | None = None) -> DataSourceProvider:
    """获取数据源实例（带缓存）"""
    if name is None:
        from app.config import settings
        name = settings.DATA_SOURCE

    name = name.lower()

    # auto 数据源使用专用工厂
    if name == "auto":
        if "auto" not in _source_cache:
            _source_cache["auto"] = _create_auto_source()
        return _source_cache["auto"]

    if name not in _DATA_SOURCES:
        logger.warning(f"未知数据源 '{name}'，回退到 mootdx")
        name = "mootdx"

    if name not in _source_cache:
        _source_cache[name] = _DATA_SOURCES[name]()

    return _source_cache[name]
```

- [ ] **Step 2: Update config.py default DATA_SOURCE**

Change line 18 from:
```python
    DATA_SOURCE: str = "akshare"
```
to:
```python
    DATA_SOURCE: str = "auto"
```

Also update the comment on line 17 from:
```python
    # 数据源: akshare / baostock / xtquant
```
to:
```python
    # 数据源: auto / mootdx / akshare / baostock / xtquant / tencent / sina / efinance
```

- [ ] **Step 3: Verify the full integration works**

Run:
```bash
cd D:/MyProj/stock/backend && PYTHONIOENCODING=utf-8 ./venv/Scripts/python.exe -c "
from app.core.data_bridge import get_data_source, get_available_sources

# Test auto data source
auto = get_data_source('auto')
print(f'Auto source name: {auto.get_name()}')
print(f'Auto source available: {auto.is_available()}')

# Test daily klines via auto
df = auto.get_klines('600519.SH', '1d', '2026-06-01', '2026-06-27')
print(f'Daily via auto: {len(df)} rows')
print(df.head(3))

# Test 1m klines via auto
df1m = auto.get_klines('600519.SH', '1m', '2026-06-26', '2026-06-27')
print(f'1m via auto: {len(df1m)} rows')

# Test index klines via auto
df_idx = auto.get_index_klines('000001.SH', '1d', '2026-06-01', '2026-06-27')
print(f'Index via auto: {len(df_idx)} rows')

# Test available sources
sources = get_available_sources()
print(f'Available sources: {sources}')

# Test default data source
from app.config import settings
print(f'Default DATA_SOURCE: {settings.DATA_SOURCE}')

print('ALL INTEGRATION CHECKS PASSED')
"
```
Expected: `Default DATA_SOURCE: auto`, all queries return data

- [ ] **Step 4: Commit**

```bash
git add backend/app/core/data_bridge.py backend/app/config.py
git commit -m "feat: register mootdx + auto fallback source, change default to auto"
```

---

### Task 6: End-to-end backtest verification

**Files:**
- No new files (verification only)

- [ ] **Step 1: Run a daily backtest with the auto data source**

Run:
```bash
cd D:/MyProj/stock/backend && PYTHONIOENCODING=utf-8 ./venv/Scripts/python.exe -c "
from app.core.data_bridge import data_bridge

# Test daily backtest data loading via auto source
df = data_bridge.load_bars_df('600519', '2026-01-01', '2026-06-27', 'daily')
print(f'Daily bars: {len(df)} rows')
print(df.head(3))
print(df.tail(3))
assert len(df) > 30, 'Not enough daily data for backtest'
print('DAILY BACKTEST DATA OK')
"
```
Expected: Non-empty DataFrame with >30 rows

- [ ] **Step 2: Run a minute-level backtest with the auto data source**

Run:
```bash
cd D:/MyProj/stock/backend && PYTHONIOENCODING=utf-8 ./venv/Scripts/python.exe -c "
from app.core.data_bridge import data_bridge

# Test 5m backtest data loading via auto source
df = data_bridge.load_bars_df('600519', '2026-06-20', '2026-06-27', '5m')
print(f'5m bars: {len(df)} rows')
print(df.head(3))
assert len(df) > 0, 'No 5m data'

# Test 1m data
df1m = data_bridge.load_bars_df('600519', '2026-06-26', '2026-06-27', '1m')
print(f'1m bars: {len(df1m)} rows')
assert len(df1m) > 0, 'No 1m data'

print('MINUTE-LEVEL BACKTEST DATA OK')
"
```
Expected: Both queries return non-empty DataFrames

- [ ] **Step 3: Verify fallback works when a source fails**

Run:
```bash
cd D:/MyProj/stock/backend && PYTHONIOENCODING=utf-8 ./venv/Scripts/python.exe -c "
from app.core.data_source_fallback import FallbackDataSource
from app.core.data_source import DataSourceProvider
import pandas as pd

# Create a fake broken source
class BrokenSource(DataSourceProvider):
    def get_klines(self, symbol, period, start, end, dividend_type='front'):
        raise ConnectionError('simulated failure')
    def get_index_klines(self, index_code, period, start, end):
        raise ConnectionError('simulated failure')
    def is_available(self):
        return True
    def get_name(self):
        return 'broken'

from app.core.data_source_mootdx import MootdxDataSource

# Fallback: broken -> mootdx
fb = FallbackDataSource({'broken': BrokenSource(), 'mootdx': MootdxDataSource()})
df = fb.get_klines('600519.SH', '1d', '2026-06-01', '2026-06-27')
print(f'Fallback result: {len(df)} rows from {fb.get_name()}')
assert len(df) > 0, 'Fallback failed'

# Check fallback log
log = fb.get_fallback_log()
print(f'Fallback log: {len(log)} entries')
assert len(log) > 0, 'No fallback log entries'
print(f'First fallback: {log[0]}')

print('FALLBACK VERIFICATION OK')
"
```
Expected: FallbackDataSource falls back from broken to mootdx, returns data, logs the fallback event

- [ ] **Step 4: Final commit (if any fixes were needed)**

```bash
git add -A
git commit -m "fix: any fixes from end-to-end verification"
```

---

## Self-Review Checklist

**1. Spec coverage:**
- ✅ MootdxDataSource → Task 2
- ✅ FallbackDataSource with period-aware routing → Task 3
- ✅ Eastmoney rate limiting (akshare + efinance) → Task 4
- ✅ data_bridge registration → Task 5
- ✅ config default change → Task 5
- ✅ requirements.txt mootdx → Task 1
- ✅ Backward compatibility → preserved (old source names still work)

**2. Placeholder scan:** No TBD/TODO/"implement later"/"add validation" found. All code is complete.

**3. Type consistency:**
- `get_klines(symbol, period, start, end, dividend_type)` → consistent across all DataSourceProvider implementations
- `get_index_klines(index_code, period, start, end)` → consistent
- `is_available() -> bool`, `get_name() -> str` → consistent
- `_source_cache` dict key type: `str` → consistent with `get_data_source()` usage
- FallbackDataSource constructor takes `dict[str, DataSourceProvider]` → matches `_create_auto_source()` return

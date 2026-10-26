# TCP 连接爆炸修复方案

日期:2026-07-29
范围:backend + stock_filters

## 背景

多个后台循环与用户触发路径都可能触发 akshare `stock_zh_a_spot_em()`(每轮 55+ HTTP 请求),且无全局协调:
- `AkshareMarketBackend._poll_loop`(60s,有自己的 `_polling` 锁)
- AI 盯盘引擎 `monitor_engine_loop`(60s)-> `_fetch_quotes` -> auto `get_snapshot`
- AI 定时选股 `scheduled_pick_loop`(60s)-> `_fetch_pool_quotes` -> `_fetch_quotes` -> auto `get_snapshot`
- 自选股刷新 `refresh_watchlist_quotes` -> `_fetch_quotes` -> auto `get_snapshot`

auto 快照降级链 `_DAILY_SOURCE_ORDER=["tencent","mootdx","baostock","sina","akshare"]` 中,只有 tencent(1 次批量)与 akshare(`stock_zh_a_spot_em`,55+ 次)真正实现 `get_snapshot`,其余基类返回 `{}`。腾讯失败即回退 akshare 全市场拉取,多路径叠加致 TCP 爆炸。

stock_filters 是独立进程,不受 backend `main.py` 的 monkey-patch 覆盖:三个裸 `requests.Session()` 无连接池,`ak.stock_zh_a_spot()` 等走 akshare 默认 `request_with_retry`(每次新建 Session 禁用连接池)。

`AkshareDataSource` 存在两个独立实例(`AkshareMarketBackend._fetch_snapshot` 一个,`data_bridge._create_auto_source` 一个),因此 spot 缓存必须放**类级**才能跨实例共享。

## 修复 A(P0,主因):akshare 全市场快照类级 TTL 缓存 + 互斥锁

文件:`backend/app/core/data_source_akshare.py`

在 `AkshareDataSource` 类上新增类变量与类方法:

```python
# 类级全市场 spot 缓存(跨所有 AkshareDataSource 实例共享)
_spot_cache_df = None        # 缓存 stock_zh_a_spot_em() 全市场 DataFrame
_spot_cache_ts: float = 0.0  # 上次拉取时间戳
_spot_cache_lock = threading.Lock()
_SPOT_CACHE_TTL: float = 15.0  # 秒;15s 内全市场快照复用,合并所有调用方

@classmethod
def _get_spot_df(cls):
    """获取全市场 spot_em DataFrame(带 TTL 缓存 + 互斥锁)。

    多路径(AkshareMarketBackend 轮询 / auto 降级回退 / 任何 get_snapshot 调用)
    共享同一份缓存,15s 内只拉一次 stock_zh_a_spot_em()。double-check locking
    防并发拉取;拉取失败做负面缓存(更新 ts 不更新 df,返回旧缓存)避免频繁重试。
    """
    now = time.time()
    if cls._spot_cache_df is not None and (now - cls._spot_cache_ts) < cls._SPOT_CACHE_TTL:
        return cls._spot_cache_df
    with cls._spot_cache_lock:
        now = time.time()
        if cls._spot_cache_df is not None and (now - cls._spot_cache_ts) < cls._SPOT_CACHE_TTL:
            return cls._spot_cache_df
        cls._rate_limit()
        try:
            import akshare as ak
            df = ak.stock_zh_a_spot_em()
        except Exception as e:
            logger.error(f"akshare 获取快照失败: {e}")
            cls._spot_cache_ts = time.time()  # 负面缓存:短期不重试
            return cls._spot_cache_df          # 返回旧缓存(可能 None)
        if df is not None and not df.empty:
            cls._spot_cache_df = df
        cls._spot_cache_ts = time.time()
        return cls._spot_cache_df
```

改造 `get_snapshot()`(`data_source_akshare.py:255`):
- 删除方法内 `self._rate_limit()`(已移入 `_get_spot_df` 锁内,避免命中缓存也限流)
- 删除方法内 `ak.stock_zh_a_spot_em()` 直接调用,改为 `df = self._get_spot_df()`
- `df is None or df.empty` 时返回 `{}`
- 下游按 codes 过滤逻辑不变

效果:所有路径 15s 内全局只拉一次 spot_em;互斥锁防 `to_thread` 线程与事件循环线程并发拉取。

## 修复 B(P1):stock_filters 连接池 + akshare monkey-patch

### B1. `stock_filters/main.py` 顶部加 monkey-patch
复刻 `backend/app/main.py:28-127` 的 patch 逻辑(适配 stock_filters 无 app 包结构):
- monkey-patch `requests.Session.__init__`:所有新建 Session 自动挂 `HTTPAdapter(pool_connections=20, pool_maxsize=10, max_retries=Retry(...))`
- 替换模块级 `requests.get/post/put/delete/patch/head/options` 走全局共享 `_REQUESTS_SESSION`
- monkey-patch `akshare.utils.request.request_with_retry` 与 `akshare.utils.func.request_with_retry`:改用全局共享 Session
- 放在 `main()` 之前、import akshare 之前执行(实际 akshare 在 `data.akshare_source` 内 import,main.py 顶部 patch 先于 `from data.akshare_source import AKShareDataSource` 即可)

### B2. `stock_filters/data/akshare_source.py` 三个裸 Session 挂连接池
- `_SINA_SESSION`(:17 模块级)
- `self._sina_session`(:32 实例级)
- `self._tencent_session`(:37 实例级)

各自挂:
```python
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry
_adapter = HTTPAdapter(pool_connections=20, pool_maxsize=10,
                       max_retries=Retry(total=2, backoff_factor=0.5, status_forcelist=[502,503,504]))
session.mount("https://", _adapter)
session.mount("http://", _adapter)
```

注:`notifier.py` 的 `requests.post` 由 B1 模块级 patch 自动覆盖,无需单独改。

## 修复 C:过时注释

`backend/app/core/market_backend.py:775` 文档字符串 "每 3 秒拉一次快照" -> "每 60 秒拉一次快照"(实际 `_poll_interval=60.0`)。

## 不做(说明理由)

- **`_fetch_quotes` 层缓存**:tencent 快照是 1 次批量请求,本身不爆炸;A1 已覆盖 akshare 大头。codes 列表因调用方而异(盯盘股 vs 沪深300),做缓存需缓存全量再过滤,引入复杂度收益低。
- **trade_sync 逐持仓 tick**(`trade_sync_service.py:69-79`):akshare 模式下 `get_full_tick` 读 `_tick_cache` 无 HTTP;持仓量通常小;优先级低,本次不动。

## 验证

1. 现有测试:`backend/tests/test_data_source_constituents.py`、`test_akshare_market_backend.py`、`test_akshare_smoke.py`(在 venv 跑,非 anaconda)
2. 手动:交易时段观察日志,确认 `akshare 获取快照失败`/spot_em 拉取频率从"多路径每分钟多次"降到"约 15s 一次";并发场景无重复拉取日志
3. 回归:盯盘引擎信号触发、选股结果、自选股刷新功能正常(缓存 15s 新鲜度对分钟级盯盘可接受)

## 改动文件清单

- `backend/app/core/data_source_akshare.py`(A1,核心)
- `backend/app/core/market_backend.py`(C,注释)
- `stock_filters/main.py`(B1,monkey-patch)
- `stock_filters/data/akshare_source.py`(B2,三个 Session 挂连接池)

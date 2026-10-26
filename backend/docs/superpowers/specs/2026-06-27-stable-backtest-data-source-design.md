# 稳定回测数据源设计

> 日期: 2026-06-27
> 状态: 已批准

## 背景

当前回测默认数据源 `akshare` 不稳定（依赖东财API，易被限流/IP封）。`tencent` 稳定但仅支持日线，分钟线回测没有稳定数据源。参考 [a-stock-data](https://github.com/simonlin1212/a-stock-data) 项目的设计，引入分级数据源 + 自动降级机制。

## 核心设计

### 数据源分级（按IP封禁风险）

| 级别 | 数据源 | 用途 | 封禁风险 |
|------|--------|------|---------|
| Tier 1 | mootdx (新增) | 分钟线 + 日线主源 | 永不封IP |
| Tier 1 | tencent | 日线主源 | 永不封IP（仅日线/周线） |
| Tier 2 | baostock | 日线备用 | 低风险 |
| Tier 2 | sina | 日线备用 | 低风险 |
| Tier 3 | akshare | 仅做最后备选 | 中风险，严格限流 |
| Tier 3 | efinance | 仅做最后备选 | 中风险，严格限流 |
| 特殊 | xtquant | 本地QMT数据 | 需MiniQMT运行 |

### 降级优先级链

| 场景 | 数据源优先级 |
|------|-------------|
| 分钟线 (1m/5m/15m/30m/1h) | mootdx → xtquant → akshare(限流) |
| 日线/周线 | tencent → mootdx → baostock → sina → akshare(限流) |
| 指数日线 | tencent → mootdx → baostock → akshare(限流) |

## 组件设计

### 1. MootdxDataSource

**文件**: `backend/app/core/data_source_mootdx.py`

通达信TCP二进制协议数据源（端口7709），永不封IP。

```python
class MootdxDataSource(DataSourceProvider):
    """通达信数据源（TCP 二进制协议，永不封IP）"""
```

关键设计点（参考 a-stock-data）：

1. **`tdx_client()` helper** — 解决 mootdx 0.11.x 新安装 `Quotes.factory()` 因空 BESTIP 配置崩溃的问题。3级回退：
   - bestip 探测 → bare factory → 显式错误消息
2. **支持周期**: 1m/5m/15m/30m/60m/1d/1w
3. **复权**: mootdx 原生支持 fq=1(前复权) / fq=2(后复权) / fq=0(不复权)
4. **连接管理**: 模块级单例，首次使用时自动连接，断线自动重连
5. **股票代码映射**: `600519.SH` → mootdx 的 `market=1, code=600519` (SH=1, SZ=0, BJ=2)

实现接口：
- `get_klines(symbol, period, start, end, dividend_type)` → 标准 DataFrame
- `get_index_klines(index_code, period, start, end)` → 标准 DataFrame
- `is_available()` → 尝试连接
- `get_name()` → `"mootdx"`

### 2. FallbackDataSource

**文件**: `backend/app/core/data_source_fallback.py`

分级自动降级数据源。按优先级依次尝试多个数据源，首个成功即返回。自动跳过不可用的数据源，并记录降级事件供调试。

```python
class FallbackDataSource(DataSourceProvider):
    """分级自动降级数据源"""

    def __init__(self, sources: list[DataSourceProvider]):
        self._sources = sources  # 按优先级排序
        self._fallback_log: list[dict] = []  # 降级事件日志

    def get_klines(self, symbol, period, start, end, dividend_type="front"):
        for source in self._sources:
            if not source.is_available():
                continue
            try:
                df = source.get_klines(symbol, period, start, end, dividend_type)
                if not df.empty:
                    return df
            except Exception as e:
                self._log_fallback(source, e)
                continue
        return pd.DataFrame()  # 所有源都失败
```

分钟线/日线智能路由：

```python
def get_klines(self, symbol, period, start, end, dividend_type="front"):
    # 分钟线策略：只尝试支持分钟线的源
    minute_sources = ["mootdx", "xtquant", "akshare"]
    # 日线策略：尝试所有日线源
    daily_sources = ["tencent", "mootdx", "baostock", "sina", "akshare"]

    sources = minute_sources if period in ("1m","5m","15m","30m","1h","60m") else daily_sources
    for source_name in sources:
        source = self._get_source(source_name)
        ...
```

降级日志结构：
```python
{
    "timestamp": "2026-06-27T10:30:00",
    "source": "mootdx",
    "error": "ConnectionRefusedError",
    "fallback_to": "xtquant",
    "symbol": "600519.SH",
    "period": "5m",
}
```

### 3. 东财统一限流

**文件**: 直接在 `data_source_akshare.py` 和 `data_source_efinance.py` 中添加类级别限流

对 akshare/efinance 添加调用间隔控制（类级别，线程安全）：

```python
class AkshareDataSource(DataSourceProvider):
    _last_call_time: float = 0
    _call_lock = threading.Lock()
    _MIN_CALL_INTERVAL: float = 1.5  # 秒

    def get_klines(self, ...):
        with self._call_lock:
            now = time.time()
            elapsed = now - self._last_call_time
            if elapsed < self._MIN_CALL_INTERVAL:
                time.sleep(self._MIN_CALL_INTERVAL - elapsed + random.uniform(0, 0.5))
            self._last_call_time = time.time()
            # ... 原有 akshare 调用
```

efinance 同样添加相同限流机制。

限流参数（参考 a-stock-data 实测封禁阈值）：
- 最小调用间隔: 1.5s（含 0-0.5s 随机抖动）
- 封禁阈值参考: >5 req/s, ≥10 并发, ≥200/min, ≥300/5min

### 4. data_bridge 注册变更

**文件**: `backend/app/core/data_bridge.py`

```python
_DATA_SOURCES: dict[str, type[DataSourceProvider]] = {
    "mootdx": MootdxDataSource,       # 新增
    "tencent": TencentDataSource,
    "baostock": BaostockDataSource,
    "sina": SinaDataSource,
    "akshare": AkshareDataSource,
    "efinance": EfinanceDataSource,
    "xtquant": XtquantDataSource,
    "auto": FallbackDataSource,         # 新增：分级降级复合数据源
}
```

`FallbackDataSource` 注册时使用工厂函数，按优先级构建源链：

```python
def _create_auto_source() -> FallbackDataSource:
    return FallbackDataSource([
        MootdxDataSource(),      # Tier 1
        TencentDataSource(),     # Tier 1 (仅日线)
        BaostockDataSource(),    # Tier 2
        SinaDataSource(),        # Tier 2
        AkshareDataSource(),     # Tier 3 (限流)
    ])
```

### 5. 配置变更

**`backend/app/config.py`**:
```python
# 默认数据源从 akshare 改为 auto（分级降级）
DATA_SOURCE: str = "auto"
```

**`backend/requirements.txt`**:
```
mootdx>=0.10.0   # 新增
```

### 6. 向后兼容

- 旧的 `akshare` / `tencent` / `mootdx` 等单独数据源选项仍然可用
- `DATA_SOURCE` 配置支持 `.env` 覆盖，用户可回退到任何单一源
- 回测 API `/data-sources` 端点增加 `auto` 选项
- 前端数据源选择器默认选中 `auto`

## 文件变更清单

| 文件 | 操作 | 说明 |
|------|------|------|
| `backend/app/core/data_source_mootdx.py` | 新增 | 通达信数据源实现 |
| `backend/app/core/data_source_fallback.py` | 新增 | 分级自动降级数据源 |
| `backend/app/core/data_source_akshare.py` | 修改 | 添加调用间隔限流 |
| `backend/app/core/data_source_efinance.py` | 修改 | 添加调用间隔限流 |
| `backend/app/core/data_bridge.py` | 修改 | 注册新数据源，默认改为 auto |
| `backend/app/config.py` | 修改 | DATA_SOURCE 默认值改为 auto |
| `backend/requirements.txt` | 修改 | 新增 mootdx>=0.10.0 |

## 风险与缓解

| 风险 | 缓解措施 |
|------|---------|
| mootdx 连接失败（服务器维护/网络问题） | FallbackDataSource 自动降级到下一级源 |
| mootdx 版本兼容性 | `tdx_client()` helper 3级回退处理 |
| 限流导致 akshare 回测变慢 | akshare 已降级为 Tier 3 备选，正常不会走到 |
| 前端数据源选择器需更新 | 增加auto选项，保持旧选项向后兼容 |

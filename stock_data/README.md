# Stock Data Service

基于 MiniQMT (xtquant) 的 A 股数据服务，提供 REST API 和 WebSocket 实时行情推送。

## 架构概览

```
MiniQMT (xtquant) ── 本地 .DAT 文件
        │                    │
        ▼                    ▼
  xtdata_client.py ── _read_qmt_dat() (回退)
        │
        ▼
   FastAPI REST + WebSocket
        │
        ▼
   定时同步 (APScheduler) + 断点续传
```

核心设计：**xtdata 优先，本地文件回退**。当 MiniQMT 服务在线时通过 xtquant SDK 获取数据；服务不可用时直接读取 QMT 本地 `.DAT` 二进制文件，确保数据始终可用。

## 快速开始

### 前置条件

- Python 3.10+
- MiniQMT 已安装并运行（数据同步需要 QMT 客户端在线）
- Windows 环境（MiniQMT 仅支持 Windows）

### 安装与启动

```bash
# 创建虚拟环境
python -m venv venv
venv\Scripts\activate       # Windows
pip install -r requirements.txt

# 配置 API 密钥（可选，为空则不启用认证）
set STOCK_DATA_API_KEY=your_key

# 启动服务
python main.py
```

或使用 PowerShell 脚本：

```powershell
.\start.ps1
```

服务默认监听 `0.0.0.0:8000`。若 `db_data/` 目录下存在 `server.crt` 和 `server.key`，自动启用 HTTPS。

## 配置

通过 `config.py` 或环境变量配置：

| 配置项 | 环境变量 | 默认值 | 说明 |
|--------|----------|--------|------|
| `API_KEY` | `STOCK_DATA_API_KEY` | 空 | API 认证密钥，为空则不启用认证 |
| `HTTP_HOST` | - | `0.0.0.0` | 监听地址 |
| `HTTP_PORT` | - | `8000` | 监听端口 |
| `DOWNLOAD_HOUR` | - | `15` | 定时下载小时（收盘后） |
| `DOWNLOAD_MINUTE` | - | `30` | 定时下载分钟 |
| `DOWNLOAD_PERIODS` | - | `("1d","5m","1m")` | 下载的K线周期 |
| `BATCH_SIZE` | - | `{"1d":10,"5m":3,"1m":2}` | 各周期每批下载股票数 |
| `DOWNLOAD_TIMEOUT` | - | `{"1d":8,"5m":15,"1m":20}` | 各周期下载超时（秒） |
| `XTDATA_DATA_DIR` | - | QMT datadir 路径 | QMT 本地数据目录 |

## API 接口

所有接口前缀 `/api/v1`，认证通过 `X-API-Key` Header（配置了 API_KEY 时必填）。

### 服务状态

```
GET /health
```

```json
{
  "service": "stock_data",
  "status": "online",
  "xtquant": {"available": true, "connected": true, "error": null}
}
```

### K 线数据

```
GET /klines?symbol=600519.SH&period=1d&start_time=20240101&end_time=20241231&count=-1&dividend_type=none
```

| 参数 | 说明 |
|------|------|
| `symbol` | 股票代码，如 `600519.SH` |
| `period` | 周期：`1m/5m/15m/30m/60m/1h/1d/1w/1mon` |
| `start_time` | 开始日期 `YYYYMMDD` |
| `end_time` | 结束日期 `YYYYMMDD` |
| `count` | 返回条数，`-1` 为全部 |
| `dividend_type` | 复权：`none/front/back` |

返回：

```json
{
  "symbol": "600519.SH",
  "period": "1d",
  "dividend_type": "none",
  "count": 245,
  "klines": [
    {"datetime": "20240102", "open": 1680, "high": 1695, "low": 1670, "close": 1688, "volume": 12345, "amount": 208000000}
  ]
}
```

### 实时行情

```
GET /tick/600519.SH
```

```json
{
  "symbol": "600519.SH",
  "last_price": 1688.0,
  "open": 1680.0,
  "high": 1695.0,
  "low": 1670.0,
  "last_close": 1675.0,
  "volume": 12345,
  "amount": 208000000,
  "bid_prices": [1687.0, 1686.0, 1685.0, 1684.0, 1683.0],
  "bid_volumes": [100, 200, 150, 80, 60],
  "ask_prices": [1689.0, 1690.0, 1691.0, 1692.0, 1693.0],
  "ask_volumes": [50, 120, 80, 40, 30],
  "datetime": "20240102103000"
}
```

### 股票列表

```
GET /stocks?sector=沪深A股&limit=0
```

返回沪深A股列表，含代码、名称、拼音。结果缓存 5 分钟。

### 合约详情

```
GET /instruments/600519.SH
```

```json
{
  "symbol": "600519.SH",
  "instrument_id": "600519",
  "instrument_name": "贵州茅台",
  "exchange_id": "SH",
  "industry": "白酒",
  "list_date": "2001-08-27"
}
```

### 数据同步

```
GET  /sync/status    # 查询同步状态
POST /sync/trigger   # 触发同步任务
```

### WebSocket 实时行情

```
WS /ws/quote?apikey=your_key
```

连接后发送 JSON 消息：

```json
{"action": "subscribe", "symbols": ["600519.SH", "000001.SZ"]}
{"action": "unsubscribe", "symbols": ["600519.SH"]}
{"action": "ping"}
```

服务端每 3 秒推送订阅股票的实时行情：

```json
{"type": "quote", "data": {"600519.SH": {"last_price": 1688, "open": 1680, "high": 1695, "low": 1670, "volume": 12345, "amount": 208000000, "datetime": "20240102103000"}}}
```

## 数据同步机制

### 定时同步

APScheduler 每日 `15:30`（收盘后）自动执行增量下载，周期按 `1d → 5m → 1m` 顺序。

### 增量过滤

同步前检查本地数据，跳过已更新到最近交易日的股票，仅下载过期数据，大幅减少下载量。

### 断点续传

进度保存在 `db_data/sync_progress.json`，记录当前周期和已成功的股票集合。服务重启后自动从断点继续，无需重新下载。

### 连接容错

- `_ensure_connected()`：统一连接管理，30 秒内复用连接，超时自动重连
- `_find_port()`：扫描 MiniQMT 可用端口（`xtconn.scan_available_server_addr` + 常用端口探测）
- 连续超时 3 次自动断开重连

### 手动触发

```bash
# 通过 API
curl -X POST http://localhost:8000/api/v1/sync/trigger -H "X-API-Key: your_key"

# 通过脚本
python scripts/trigger_sync.py
python scripts/trigger_sync.py --local  # 本地直接执行，不依赖服务
python scripts/trigger_sync.py --host 192.168.1.10 --port 8000 --api-key your_key
```

## 数据读取回退策略

K 线数据读取遵循三级回退：

1. **xtdata.get_local_data**（复权数据） — 优先使用，支持前/后复权
2. **xtdata.get_local_data**（不复权） — 复权失败时自动回退到不复权
3. **_read_qmt_dat()**（本地 .DAT 文件） — xtdata 不可用时直接解析 QMT 二进制文件

`.DAT` 文件结构：8 字节头 + 64 字节/条记录，包含时间戳、OHLC、成交量。数据目录按市场（SH/SZ）和周期秒数组织。

## 项目结构

```
stock_data/
├── main.py              # 入口，启动 uvicorn + 定时调度
├── config.py            # 全局配置
├── api/
│   ├── routes.py        # FastAPI app 定义
│   └── v1_routes.py     # v1 版本路由（REST + WebSocket）
├── data/
│   ├── xtdata_client.py # xtdata 连接管理 + 数据读取 + .DAT 回退
│   └── sync.py          # K线下载同步（增量 + 断点续传）
├── scheduler/
│   └── jobs.py          # APScheduler 定时任务
├── scripts/
│   └── trigger_sync.py  # 手动触发同步脚本
├── db_data/             # SSL 证书 + 同步进度（gitignore）
├── start.ps1            # PowerShell 启动脚本
└── requirements.txt     # 依赖
```

## 最佳实践

### 生产部署

- 在 MiniQMT 所在机器上运行服务，确保 xtdata 可连接
- 配置 `STOCK_DATA_API_KEY` 环境变量启用认证
- 将 SSL 证书放入 `db_data/` 目录自动启用 HTTPS
- 定时下载时间设为收盘后（默认 15:30），避免盘中网络波动

### 数据完整性

- 同步任务自动断点续传，服务重启不影响进度
- 增量过滤确保只下载过期数据，避免重复下载
- `.DAT` 文件回退保证 xtdata 离线时数据仍可查询

### 性能优化

- 股票列表缓存 5 分钟，避免重复查询 xtdata
- xtdata 连接 30 秒内复用，减少重复连接开销
- 按周期配置不同批次大小和超时：日线 10 只/批、5 分钟线 3 只/批、1 分钟线 2 只/批
- WebSocket 行情每 3 秒推送，仅推送订阅的股票

### 监控与运维

- `/health` 接口可对接监控系统，检测 xtdata 连接状态
- `/sync/status` 接口查询同步任务运行状态
- 日志输出包含下载进度、速度、ETA，便于排查问题
- 连续超时自动重连，无需人工干预
# stock_data 行情数据服务 — 接口文档

## 项目定位

独立行情数据服务，提供 HTTPS RESTful API，替代对 `xtquant.xtdata` 的直接依赖。

**数据源**: 本服务内部对接 xtquant，对外统一暴露 HTTP 接口。

---

## 通用约定

- 基础路径: `/api/v1`
- 认证: API Key 请求头 `X-API-Key: <key>`（WebSocket 使用 `?apikey=<key>`）
- 股票代码格式: `{6位代码}.{交易所}` — 如 `600519.SH`、`000001.SZ`、`830799.BJ`
- 时间格式: `YYYYMMDD` 或 `YYYYMMDDhhmmss`
- 错误响应: `{ "code": int, "message": str }`
- 服务不可用返回 HTTP 503

### 认证

设置环境变量 `STOCK_DATA_API_KEY` 后，所有接口需要携带 API Key：

- HTTP 接口：请求头 `X-API-Key: <key>`
- WebSocket：连接参数 `?apikey=<key>`

未设置环境变量则不校验。

### 股票代码规则

| 后缀 | 交易所 | 示例 |
|------|--------|------|
| .SZ | 深圳证券交易所 | `000001.SZ`（平安银行） |
| .SH | 上海证券交易所 | `600519.SH`（贵州茅台） |
| .BJ | 北京证券交易所 | `830799.BJ` |

### 错误码

| HTTP 状态码 | 场景 |
|-------------|------|
| 401 | API Key 无效 |
| 404 | 资源不存在 |
| 422 | 请求参数校验失败 |
| 500 | 服务器内部错误 |
| 503 | 数据源不可用 |

---

## 1. 服务状态

### `GET /api/v1/health`

服务健康检查。

**Response**:
```json
{
  "service": "stock_data",
  "status": "online",
  "xtquant": {
    "available": true,
    "connected": true,
    "error": null
  }
}
```

| 字段 | 类型 | 说明 |
|------|------|------|
| `service` | string | 服务名称 |
| `status` | string | `"online"` / `"degraded"` |
| `xtquant` | object | xtquant 数据源状态 |
| `xtquant.available` | bool | 数据源是否可用 |
| `xtquant.connected` | bool | 数据源是否已连接 |
| `xtquant.error` | string\|null | 错误信息 |

**示例**:
```bash
curl -k https://localhost:8000/api/v1/health
```

---

## 2. K线数据

### `GET /api/v1/klines`

获取历史K线数据。

**Query Parameters**:

| 参数 | 类型 | 必填 | 默认 | 说明 |
|------|------|------|------|------|
| `symbol` | string | 是 | — | 股票代码，如 `600519.SH` |
| `period` | string | 否 | `1d` | 周期: `1m`/`5m`/`15m`/`30m`/`60m`/`1h`/`1d`/`1w`/`1mon` |
| `start_time` | string | 否 | `""` | 开始时间 YYYYMMDD |
| `end_time` | string | 否 | `""` | 结束时间 YYYYMMDD |
| `count` | int | 否 | `-1` | 返回条数，-1 表示全部 |
| `dividend_type` | string | 否 | `none` | 复权方式: `none`/`front`/`back` |

**Response**:
```json
{
  "symbol": "600519.SH",
  "period": "1d",
  "dividend_type": "front",
  "count": 100,
  "klines": [
    {
      "datetime": "20240101",
      "open": 1680.0,
      "high": 1695.0,
      "low": 1675.0,
      "close": 1690.0,
      "volume": 25000,
      "amount": 42250000.0
    }
  ]
}
```

| 字段 | 类型 | 说明 |
|------|------|------|
| `klines[].datetime` | string | 时间戳，日线为 `YYYYMMDD`，分钟线为 `YYYYMMDDhhmmss` |
| `klines[].open` | float | 开盘价 |
| `klines[].high` | float | 最高价 |
| `klines[].low` | float | 最低价 |
| `klines[].close` | float | 收盘价 |
| `klines[].volume` | int | 成交量（股） |
| `klines[].amount` | float | 成交额（元） |

**示例**:
```bash
# 日线，前复权
curl -k "https://localhost:8000/api/v1/klines?symbol=600519.SH&period=1d&start_time=20240101&dividend_type=front"

# 5分钟线
curl -k "https://localhost:8000/api/v1/klines?symbol=000001.SZ&period=5m&start_time=20250401&end_time=20250410"

# 最近100条1分钟线
curl -k "https://localhost:8000/api/v1/klines?symbol=000001.SZ&period=1m&count=100"
```

---

## 3. Tick 数据

### `GET /api/v1/tick/{symbol}`

获取最新 tick 快照。

**Path Parameters**:

| 参数 | 类型 | 说明 |
|------|------|------|
| `symbol` | string | 股票代码，如 `600519.SH` |

**Response**:
```json
{
  "symbol": "600519.SH",
  "last_price": 1690.0,
  "open": 1680.0,
  "high": 1695.0,
  "low": 1675.0,
  "last_close": 1685.0,
  "volume": 25000,
  "amount": 42250000.0,
  "bid_prices": [1689.0, 1688.0, 1687.0, 1686.0, 1685.0],
  "bid_volumes": [100, 200, 150, 300, 250],
  "ask_prices": [1691.0, 1692.0, 1693.0, 1694.0, 1695.0],
  "ask_volumes": [120, 180, 200, 100, 150],
  "datetime": "20240101150003"
}
```

| 字段 | 类型 | 说明 |
|------|------|------|
| `last_price` | float | 最新价 |
| `open` | float | 开盘价 |
| `high` | float | 最高价 |
| `low` | float | 最低价 |
| `last_close` | float | 昨收价 |
| `volume` | int | 成交量 |
| `amount` | float | 成交额 |
| `bid_prices` | float[] | 买一到买五价 |
| `bid_volumes` | int[] | 买一到买五量 |
| `ask_prices` | float[] | 卖一到卖五价 |
| `ask_volumes` | int[] | 卖一到卖五量 |
| `datetime` | string | 时间戳 YYYYMMDDhhmmss |

**示例**:
```bash
curl -k https://localhost:8000/api/v1/tick/000001.SZ
```

---

## 4. 股票列表

### `GET /api/v1/stocks`

获取板块股票列表。

**Query Parameters**:

| 参数 | 类型 | 必填 | 默认 | 说明 |
|------|------|------|------|------|
| `sector` | string | 否 | `沪深A股` | 板块名称 |
| `limit` | int | 否 | `0` | 返回数量，0 表示全部 |

**Response**:
```json
{
  "sector": "沪深A股",
  "count": 5000,
  "stocks": [
    {
      "symbol": "600519.SH",
      "code": "600519",
      "name": "贵州茅台",
      "exchange": "SH",
      "pinyin": "GZMT",
      "full_pinyin": "guizhoumaotai"
    }
  ]
}
```

| 字段 | 类型 | 说明 |
|------|------|------|
| `stocks[].symbol` | string | 带交易所后缀的代码 |
| `stocks[].code` | string | 6位纯数字代码 |
| `stocks[].name` | string | 股票名称 |
| `stocks[].exchange` | string | 交易所 SH/SZ/BJ |
| `stocks[].pinyin` | string | 拼音首字母 |
| `stocks[].full_pinyin` | string | 全拼 |

**示例**:
```bash
# 全部沪深A股
curl -k https://localhost:8000/api/v1/stocks

# 前10只
curl -k "https://localhost:8000/api/v1/stocks?limit=10"
```

---

## 5. 合约详情

### `GET /api/v1/instruments/{symbol}`

获取单个合约详情。

**Path Parameters**:

| 参数 | 类型 | 说明 |
|------|------|------|
| `symbol` | string | 股票代码，如 `600519.SH` |

**Response**:
```json
{
  "symbol": "600519.SH",
  "instrument_id": "600519",
  "instrument_name": "贵州茅台",
  "exchange_id": "SH",
  "product_class": "STOCK"
}
```

| 字段 | 类型 | 说明 |
|------|------|------|
| `instrument_id` | string | 合约ID |
| `instrument_name` | string | 合约名称 |
| `exchange_id` | string | 交易所ID |
| `product_class` | string | 品种类型 |

**示例**:
```bash
curl -k https://localhost:8000/api/v1/instruments/600519.SH
```

---

## 6. 实时行情订阅（WebSocket）

实时行情推送通过 WebSocket 实现，替代 xtquant 的 `subscribe_quote` / `unsubscribe_quote` 回调机制。

### `WS /api/v1/ws/quote`

**连接**: `wss://<host>/api/v1/ws/quote?apikey=<key>`

**客户端 → 服务端**:

订阅行情:
```json
{
  "action": "subscribe",
  "symbols": ["600519.SH", "000001.SZ"],
  "period": "tick"
}
```

取消订阅:
```json
{
  "action": "unsubscribe",
  "symbols": ["600519.SH"]
}
```

心跳:
```json
{
  "action": "ping"
}
```

**服务端 → 客户端**:

订阅确认:
```json
{
  "type": "subscribed",
  "symbols": ["600519.SH", "000001.SZ"]
}
```

取消确认:
```json
{
  "type": "unsubscribed",
  "symbols": ["600519.SH"]
}
```

Tick 推送（每 3 秒）:
```json
{
  "type": "tick",
  "symbol": "600519.SH",
  "last_price": 1690.0,
  "open": 1680.0,
  "high": 1695.0,
  "low": 1675.0,
  "last_close": 1685.0,
  "volume": 25000,
  "amount": 42250000.0,
  "bid_prices": [1689.0, 1688.0, 1687.0, 1686.0, 1685.0],
  "bid_volumes": [100, 200, 150, 300, 250],
  "ask_prices": [1691.0, 1692.0, 1693.0, 1694.0, 1695.0],
  "ask_volumes": [120, 180, 200, 100, 150],
  "datetime": "20240101150003"
}
```

心跳响应:
```json
{
  "type": "pong"
}
```

---

## 调用方改造说明

原 `market_service.py` 改为 HTTP 客户端：

| 原方法 | 改造后调用 |
|--------|-----------|
| `is_available()` | `GET /api/v1/health` → 检查 `xtquant.connected` |
| `download_kline()` + `get_klines()` | `GET /api/v1/klines` |
| `get_full_tick()` | `GET /api/v1/tick/{symbol}` |
| `get_stock_list()` | `GET /api/v1/stocks` |
| `get_instrument_detail()` | `GET /api/v1/instruments/{symbol}` |
| `subscribe_quote()` | `WS /api/v1/ws/quote` → `action: subscribe` |
| `unsubscribe_quote()` | `WS /api/v1/ws/quote` → `action: unsubscribe` |

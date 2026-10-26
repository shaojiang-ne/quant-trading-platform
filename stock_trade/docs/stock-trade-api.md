# Stock Trade API

基于 xtquant 的实盘交易 HTTP 服务。服务自动管理 QMT 连接，客户端只需查询和交易。

## 认证

**所有接口（包括健康检查）** 需在请求头中携带 API Key：

```
X-API-Key: your_secret_key
```

缺少此请求头将返回 422 Unprocessable Entity。

## 接口列表

| 方法 | 路径 | 说明 |
|------|------|------|
| GET | `/api/v1/health` | 健康检查 |
| GET | `/api/v1/asset` | 查询资金 |
| GET | `/api/v1/positions` | 查询持仓 |
| GET | `/api/v1/orders` | 查询委托 |
| GET | `/api/v1/trades` | 查询成交 |
| POST | `/api/v1/orders` | 下单 |
| DELETE | `/api/v1/orders/{order_id}` | 撤单 |
| WS | `/api/v1/ws/trade` | 实时事件推送 |

---

## 健康检查

```
GET /api/v1/health
```

**请求头：** `X-API-Key: your_secret_key`（必填）

**响应：**

```json
{
  "status": "online",
  "connected": true,
  "account_id": "8890326640",
  "error": null
}
```

| 字段 | 说明 |
|------|------|
| status | `online` 已连接，`degraded` 未连接 |
| connected | QMT 连接状态 |
| account_id | 默认账户 ID，未连接时为 null |
| error | 错误信息，正常时为 null |

---

## 查询资金

```
GET /api/v1/asset
```

**响应：**

```json
{
  "account_id": "8890326640",
  "total_assets": 1000000.00,
  "cash": 500000.00,
  "available": 480000.00,
  "market_value": 500000.00,
  "frozen": 20000.00
}
```

---

## 查询持仓

```
GET /api/v1/positions
```

**响应：**

```json
{
  "account_id": "8890326640",
  "positions": [
    {
      "symbol": "600519.SH",
      "name": "贵州茅台",
      "quantity": 100,
      "available": 100,
      "avg_cost": 1680.00,
      "current_price": 1700.00,
      "market_value": 170000.00,
      "profit": 2000.00,
      "profit_rate": 0.0119
    }
  ]
}
```

---

## 查询委托

```
GET /api/v1/orders
```

**查询参数：**

| 参数 | 类型 | 说明 |
|------|------|------|
| status | string | 按状态过滤，如 `pending`、`filled`、`cancelled` |

**响应：**

```json
{
  "account_id": "8890326640",
  "orders": [
    {
      "order_id": "123456",
      "symbol": "600519.SH",
      "name": "贵州茅台",
      "side": "buy",
      "quantity": 100,
      "price": 1680.00,
      "filled_quantity": 100,
      "filled_price": 1680.00,
      "status": "filled",
      "order_type": "limit",
      "create_time": "2026-05-11 10:00:00",
      "update_time": "2026-05-11 10:00:01"
    }
  ]
}
```

---

## 查询成交

```
GET /api/v1/trades
```

**响应：**

```json
{
  "account_id": "8890326640",
  "trades": [
    {
      "trade_id": "789012",
      "order_id": "123456",
      "symbol": "600519.SH",
      "side": "buy",
      "price": 1680.00,
      "quantity": 100,
      "time": "2026-05-11 10:00:01"
    }
  ]
}
```

---

## 下单

```
POST /api/v1/orders
```

**请求体：**

```json
{
  "symbol": "600519.SH",
  "side": "buy",
  "quantity": 100,
  "price": 1680.00,
  "order_type": "limit"
}
```

| 字段 | 类型 | 必填 | 说明 |
|------|------|------|------|
| symbol | string | 是 | 证券代码，如 `600519.SH`、`002126.SZ` |
| side | string | 是 | `buy` 或 `sell` |
| quantity | int | 是 | 数量（股） |
| price | float | 否 | 价格，市价单可省略 |
| order_type | string | 否 | `limit`（限价，默认）或 `market`（市价） |

**响应：**

```json
{
  "order_id": "123456",
  "symbol": "600519.SH",
  "side": "buy",
  "quantity": 100,
  "price": 1680.00,
  "status": "pending",
  "message": "委托已提交"
}
```

---

## 撤单

```
DELETE /api/v1/orders/{order_id}
```

**响应：**

```json
{
  "order_id": "123456",
  "status": "cancelled",
  "message": "撤单成功"
}
```

---

## WebSocket 实时推送

```
WS /api/v1/ws/trade?apikey=your_secret_key
```

连接后自动推送默认账户的交易事件。

**事件类型：**

| type | 说明 | 附加字段 |
|------|------|----------|
| connected | QMT 已连接 | account_id |
| disconnected | QMT 断线 | - |
| order_update | 委托状态更新 | order_id, symbol, status, filled_quantity, filled_price, time |
| trade | 成交回报 | order_id, symbol, side, price, quantity, time |
| order_error | 委托错误 | order_id, message |

**示例：**

```python
import asyncio
import json
import websockets

async def listen():
    uri = "wss://localhost:8800/api/v1/ws/trade?apikey=your_secret_key"
    async with websockets.connect(uri) as ws:
        while True:
            event = json.loads(await ws.recv())
            match event["type"]:
                case "connected":
                    print(f"QMT已连接, 账户: {event['account_id']}")
                case "disconnected":
                    print("QMT断线，等待自动重连...")
                case "order_update":
                    print(f"委托更新: {event['symbol']} {event['status']}")
                case "trade":
                    print(f"成交: {event['symbol']} {event['side']} {event['quantity']}@{event['price']}")
                case "order_error":
                    print(f"委托错误: {event['order_id']} {event['message']}")

asyncio.run(listen())
```

**心跳：** 客户端可发送 `{"action": "ping"}` 保持连接，服务端回复 `{"type": "pong"}`。

---

## 错误响应

| HTTP 状态码 | 说明 |
|-------------|------|
| 401 | API Key 错误 |
| 400 | 请求参数错误 |
| 422 | 缺少 X-API-Key 请求头 |
| 503 | 交易网关未连接 |

```json
{"detail": "交易网关未连接"}
```

---

## 完整调用示例

```python
import requests

BASE = "https://localhost:8800/api/v1"
HEADERS = {"X-API-Key": "your_secret_key"}
VERIFY = False

# 1. 健康检查
health = requests.get(f"{BASE}/health", headers=HEADERS, verify=VERIFY).json()
if not health["connected"]:
    print(f"QMT未连接: {health['error']}")
    exit(1)
print(f"账户: {health['account_id']}")

# 2. 查询资金
asset = requests.get(f"{BASE}/asset", headers=HEADERS, verify=VERIFY).json()
print(f"总资产: {asset['total_assets']}, 可用: {asset['available']}")

# 3. 查询持仓
positions = requests.get(f"{BASE}/positions", headers=HEADERS, verify=VERIFY).json()
for p in positions["positions"]:
    print(f"{p['symbol']} {p['name']}: {p['quantity']}股, 盈亏{p['profit']}")

# 4. 限价买入
order = requests.post(
    f"{BASE}/orders",
    headers=HEADERS,
    json={"symbol": "600519.SH", "side": "buy", "quantity": 100, "price": 1680.00, "order_type": "limit"},
    verify=VERIFY
).json()
print(f"下单: {order}")

# 5. 市价卖出
order = requests.post(
    f"{BASE}/orders",
    headers=HEADERS,
    json={"symbol": "002126.SZ", "side": "sell", "quantity": 100, "order_type": "market"},
    verify=VERIFY
).json()
print(f"下单: {order}")

# 6. 查询委托
orders = requests.get(f"{BASE}/orders", headers=HEADERS, verify=VERIFY).json()
for o in orders["orders"]:
    print(f"{o['symbol']} {o['side']} {o['quantity']}@{o['price']} {o['status']}")

# 7. 撤单
if order["status"] == "pending":
    cancel = requests.delete(
        f"{BASE}/orders/{order['order_id']}",
        headers=HEADERS, verify=VERIFY
    ).json()
    print(f"撤单: {cancel}")
```

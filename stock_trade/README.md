# Stock Trade Service

基于 xtquant 的实盘交易 HTTP 服务，提供 RESTful API 和 WebSocket 实时推送。服务自动管理 QMT 连接，客户端只需查询和交易。

## 快速开始

### 前置条件

- Python 3.13+
- QMT 极简模式客户端（XtMiniQmt）已启动并登录
- xtquant 已安装（`pip install xtquant`）

### 配置

编辑 `config.yaml`：

```yaml
server:
  host: "0.0.0.0"
  port: 8800
  ssl_cert: "cert.pem"
  ssl_key: "key.pem"

auth:
  api_key: "your_secret_key"

gateway:
  type: "xtquant"
  qmt_path: "D:/Program Files/<YourBroker>QMT/userdata_mini"
  session_id: 0
```

### 启动

```bash
python main.py
```

服务启动后自动连接 QMT，断线自动重连，无需手动干预。

## 认证

所有接口需在请求头中携带 API Key：

```
X-API-Key: your_secret_key
```

## 接口概览

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

## 使用示例

```python
import requests

BASE = "https://localhost:8800/api/v1"
HEADERS = {"X-API-Key": "your_secret_key"}

# 健康检查
health = requests.get(f"{BASE}/health", headers=HEADERS, verify=False).json()
if not health["connected"]:
    print(f"QMT未连接: {health['error']}")
    exit(1)

# 查询资金
asset = requests.get(f"{BASE}/asset", headers=HEADERS, verify=False).json()

# 限价买入
order = requests.post(
    f"{BASE}/orders",
    headers=HEADERS,
    json={"symbol": "600519.SH", "side": "buy", "quantity": 100, "price": 1680.00, "order_type": "limit"},
    verify=False
).json()

# 撤单
if order["status"] == "pending":
    requests.delete(f"{BASE}/orders/{order['order_id']}", headers=HEADERS, verify=False)
```

## 稳定性机制

| 机制 | 说明 |
|------|------|
| 自动连接 | 服务启动时自动连接 QMT |
| 自动重连 | 断线后每 5 秒自动重试 |
| 断线回调 | xtquant 的 `on_disconnected` 回调自动更新状态 |
| 心跳维持 | trader 线程独立运行，维持与 QMT 的心跳 |
| 连接锁 | `threading.Lock` 防止并发连接冲突 |
| 账户自动发现 | 连接成功后自动查询并注册 QMT 账户 |

## 错误处理

| 场景 | 响应 |
|------|------|
| API Key 错误 | `401 Unauthorized` |
| 请求参数错误 | `400 Bad Request` |
| 交易网关未连接 | `503 Service Unavailable` |
| QMT 客户端未启动 | health 返回 `connected=false`，自动重连 |

## 项目结构

```
stock_trade/
├── main.py              # 入口，lifespan/中间件/重连
├── config.yaml          # 配置文件
├── core/
│   ├── config.py        # 配置加载
│   ├── auth.py          # API Key认证
│   ├── gateway.py       # xtquant交易网关（连接/下单/查询）
│   └── callback.py      # xtquant回调（委托/成交/断线）
├── routers/
│   ├── health.py        # 健康检查
│   ├── queries.py       # 资金/持仓/委托/成交查询
│   ├── orders.py        # 下单/撤单
│   └── ws.py            # WebSocket实时推送
├── models/
│   ├── request.py       # 请求模型
│   └── response.py      # 响应模型
└── docs/
    └── stock-trade-api.md  # 完整接口文档
```
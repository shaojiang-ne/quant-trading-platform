# 模拟交易模块完整测试设计

- **日期**: 2026-07-05
- **范围**: 对模拟交易模块做真实、准确的完整测试，覆盖 SimTradeBackend 单元层 → 实盘信号链路 → LiveGateway/后端切换 → API 端到端（打桩 broker 走 sim）四层
- **现状**: 已有 15 个测试（`test_sim_trade_backend.py` / `test_market_trade_backend_integration.py`）全绿，但留有精度对账、卖出分支、持久化往返、风控集成、API 端到端等缺口

## 目标

补齐现有测试的真实性/准确性缺口，不修改产品代码，不依赖交易时段/真实行情。

## 真实性准则

| 维度 | 准则 |
|------|------|
| 金额 | 浮点近似断言（`pytest.approx`，容差 1e-2），避开 Decimal 精度坑 |
| DB | 真实远程 MySQL 往返（Order/AutoTradeConfig/Signal/TradingInstance 落库→回读） |
| 行情 | 合成数据，不依赖交易时段 |
| 隔离 | 每个用例自带 `account_id`，try/finally 清理 `_sim_accounts`/`_sim_positions`/`_instances` 及 DB 行，互不污染 |

## 被测代码地图

- `app/core/trade_backend.py` — `TradeBackend` 抽象基类 + `SimTradeBackend` + `StockTradeBackend`
- `app/core/live_gateway.py` — `LiveGateway` 按 `TRADE_BACKEND` 委托
- `app/services/vnpy_strategy_runner.py` — `_sim_accounts`/`_sim_positions` + `_update_sim_account_buy/sell` + `_execute_live_signal_sim` + `save/load_sim_account_to_db`
- `app/core/risk_manager.py` — `check_order`/`record_order`
- `app/api/trading.py` — `/trading/order` 端点（硬编码走 `broker_provider`，不经过 SimTradeBackend）

### 模拟成交规则（对账依据）

- 买入佣金 = `max(cost * 0.0003, 5)`，`cost = quantity * price`
- 买入: `balance -= cost + commission`；`available -= cost + commission`；持仓加权平均成本
- 卖出佣金 = `max(revenue * 0.0003, 5)`，印花税 = `revenue * 0.001`，`revenue = quantity * price`
- 卖出: `balance += revenue - commission - stamp_tax`；`available` 同；持仓量减少，归零时 avg_cost=0
- `get_account`: `total_assets = balance + Σ market_value`，`market_value = Σ pos.market_value`
- `get_positions` 单条: `pnl = (current_price - avg_cost) * quantity`

### 架构缺口（不改，仅在报告中标注）

`/trading/order` 手动下单 API 硬编码走 `broker_provider`(qmt)，在 `TRADE_BACKEND=sim` 下不经过 `SimTradeBackend`。本次用打桩 broker 转发到 SimTradeBackend 来测 API 层逻辑，**不修改** `trading.py`。

## 文件 1: `tests/test_sim_backend_accuracy.py` — 单元精度层

复用 `_setup_sim_account` 思路，聚焦财务对账与边缘。

- 买入单笔: `available = init - cost - max(cost*0.0003, 5)`，`avg_cost = price`，`market_value = qty*price` 精确对拍
- 买入佣金最低 5 元触发: 小额下单（cost*0.0003 < 5）验佣金=5
- 两次不同价买入加权: `avg_cost = (q1*p1 + q2*p2)/(q1+q2)` 精确对拍
- 卖出单笔: `balance += revenue - max(rev*0.0003,5) - rev*0.001`，持仓归零、avg_cost 归零
- 卖出印花税+佣金对账: 高额卖出三项分别精确
- `get_account`: `total_assets = balance + Σ market_value`，`market_value` 求和
- `get_positions`: `pnl = (current_price - avg_cost) * quantity` 公式验证
- 边缘: price≤0 返回"需指定价格"；未知 side 返回"不支持的方向"；`cancel_order` 返回"不支持撤单"；`disconnect` 置 connected=False；未初始化账户 `get_account` 返回零结构
- Order 落库: `place_order` 后真实查 `orders` 表验 `source="sim_live"`/`status="filled"`/`filled_price`，finally 删行

## 文件 2: `tests/test_live_signal_sim_full.py` — 信号链路层

复用 `test_market_trade_backend_integration` 的 instance 注入模式，覆盖 `_execute_live_signal_sim` 全分支。

- buy 自动成交: signal=1，auto_trade_enabled=True/confirm_required=False → 账户扣款 + Order 落 `source="signal_auto_sim"` + `save_sim_account_to_db` 写 `sim_account_data`
- sell 自动成交: 先 buy 建仓，再 signal=-1 → 卖出回款 + pnl = (price-avg_cost)*qty 对账
- 资金不足拒绝: available < cost+commission → 不动账户、不落 Order、push risk 日志
- 持仓不足拒绝: 无仓位 sell → 拒绝
- confirm_required 信号待确认: auto_trade_enabled=False 或 confirm_required=True → 落 `signals` 表 status=pending，不动账户
- 风控集成: `risk_manager.set_config` 设 max_order_value/blocked_symbols → `_execute_live_signal_sim` 内 `check_order` 拒绝
- 持久化往返: `save_sim_account_to_db` 后 `load_sim_account_from_db` → balance/available/positions 字段一致

## 文件 3: `tests/test_trading_api_sim.py` — API 端到端层（打桩）

用 `fastapi.testclient.TestClient` + monkeypatch `app.api.trading.get_broker` 返回把 `BrokerProvider` 方法转发到 `SimTradeBackend` 的 fake，覆盖 `/trading/order`。

- 整手校验: quantity=150 → 400 拒
- 科创板: 688xxx 非整手通过
- 未连接拒单: broker.is_connected()=False → 400
- 下单成功: 落 `orders` 表 `source="manual"`/`status="submitted"`，返回 order_id
- 风控拒绝: `risk_manager.set_config` max_order_value → 400
- 每例独立 account_id + DB 清理

## 不做

- 不改产品代码（broker_provider 路径缺口在报告里标注，不修）
- 不跑 `test_trade_flow_sim.py`（slow，已存在）
- 不依赖交易时段/真实行情
- 新用例不打 slow marker

## 运行

`venv` 下:

```
python -m pytest tests/test_sim_backend_accuracy.py tests/test_live_signal_sim_full.py tests/test_trading_api_sim.py -v
```

不加 `-m "not slow"`（本批都不打 slow marker）。预计 30+ 新用例。

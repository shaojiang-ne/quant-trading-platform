# A股本地数据库项目设计

## Context

本地维护全量A股数据库，定时增量更新，提供 HTTPS 接口供查询。数据源为 xtquant（需 QMT 客户端常驻运行），存储使用 DuckDB。

## 需求

- 存储A股所有股票 10 年日线、1 年 5 分钟线、1 年 1 分钟线
- 过期数据不清理
- 每日收盘后定时增量更新
- 提供 HTTPS 接口：股票列表、股票信息、K线查询

## 架构：单进程一体化

```
┌─────────────────────────────────────┐
│           单进程 (FastAPI)            │
│                                     │
│  ┌───────────┐  ┌────────────────┐  │
│  │ Scheduler  │  │  HTTP Handler  │  │
│  │ (APScheduler)│  │  (FastAPI)    │  │
│  └─────┬─────┘  └───────┬────────┘  │
│        │                │           │
│        ▼                ▼           │
│  ┌─────────────────────────────┐    │
│  │      Data Service Layer     │    │
│  │  (xtdata → DuckDB 读写)     │    │
│  └─────────────┬───────────────┘    │
│                ▼                    │
│  ┌─────────────────────────────┐    │
│  │         DuckDB File         │    │
│  └─────────────────────────────┘    │
└─────────────────────────────────────┘
```

- 一个进程同时跑 HTTP 服务 + 定时任务
- APScheduler 做调度，FastAPI + uvicorn 做 HTTP
- DuckDB 写操作用线程锁串行化，读可并发

## 项目结构

```
stock_data/
├── config.py              # 配置项
├── main.py                # 入口：启动 FastAPI + Scheduler
├── db/
│   ├── __init__.py
│   ├── connection.py      # DuckDB 连接管理
│   ├── schema.py          # 建表、索引定义
│   └── repository.py      # 数据读写操作
├── data/
│   ├── __init__.py
│   ├── xtdata_client.py   # xtquant 数据获取封装
│   └── sync.py            # 增量同步逻辑
├── api/
│   ├── __init__.py
│   └── routes.py          # FastAPI 路由
├── scheduler/
│   ├── __init__.py
│   └── jobs.py            # APScheduler 定时任务
├── data/                  # DuckDB 数据文件目录
│   └── stock.duckdb
├── requirements.txt
└── README.md
```

## DuckDB 存储方案

3 张 K 线表（按周期分表）+ 1 张股票信息表 + 1 张同步状态表：

```sql
CREATE TABLE kline_daily (
    stock_code  VARCHAR NOT NULL,
    trade_time  TIMESTAMP NOT NULL,
    open        DOUBLE,
    high        DOUBLE,
    low         DOUBLE,
    close       DOUBLE,
    volume      BIGINT,
    amount      DOUBLE,
    PRIMARY KEY (stock_code, trade_time)
);

CREATE TABLE kline_5min (
    stock_code  VARCHAR NOT NULL,
    trade_time  TIMESTAMP NOT NULL,
    open        DOUBLE,
    high        DOUBLE,
    low         DOUBLE,
    close       DOUBLE,
    volume      BIGINT,
    amount      DOUBLE,
    PRIMARY KEY (stock_code, trade_time)
);

CREATE TABLE kline_1min (
    stock_code  VARCHAR NOT NULL,
    trade_time  TIMESTAMP NOT NULL,
    open        DOUBLE,
    high        DOUBLE,
    low         DOUBLE,
    close       DOUBLE,
    volume      BIGINT,
    amount      DOUBLE,
    PRIMARY KEY (stock_code, trade_time)
);

CREATE TABLE stock_info (
    stock_code  VARCHAR PRIMARY KEY,
    stock_name  VARCHAR,
    industry    VARCHAR,
    list_date   DATE,
    updated_at  TIMESTAMP
);

CREATE TABLE sync_status (
    stock_code  VARCHAR NOT NULL,
    period      VARCHAR NOT NULL,  -- '1d', '5m', '1m'
    last_sync_time TIMESTAMP,
    PRIMARY KEY (stock_code, period)
);
```

按周期分表避免查询时总是带 period 过滤，主键 (stock_code, trade_time) 支持 UPSERT 去重。

## 增量同步策略

### 首次全量同步

1. `get_stock_list_in_sector("沪深A股")` 获取全部股票代码
2. 日线：`download_history_data2(stock_list, "1d", start_time="20150101")`
3. 5 分钟线：`download_history_data2(stock_list, "5m", start_time="20250429")`（近 1 年）
4. 1 分钟线：`download_history_data2(stock_list, "1m", start_time="20250429")`（近 1 年）
5. 下载完成后 `get_market_data_ex` 读取并 UPSERT 到 DuckDB
6. 更新 sync_status 表

### 每日增量同步（APScheduler，15:30 触发）

1. 从 sync_status 获取每只股票各周期的最后同步时间
2. 从 `最后时间+1` 开始下载到当前
3. 批量处理：每 50 只股票一批，避免内存溢出
4. UPSERT 到 DuckDB，更新 sync_status

### 断点续传

- sync_status 记录每只股票每个周期的最后同步时间
- 首次全量同步中断后，重启时根据 sync_status 跳过已完成的股票

## HTTPS 接口

### GET /api/stock/list

获取股票列表。

响应：
```json
{
  "code": 0,
  "data": [
    {"stock_code": "000001.SZ", "stock_name": "平安银行"},
    {"stock_code": "000002.SZ", "stock_name": "万科A"}
  ]
}
```

### GET /api/stock/info?code=000001.SZ

获取股票基本信息。

响应：
```json
{
  "code": 0,
  "data": {
    "stock_code": "000001.SZ",
    "stock_name": "平安银行",
    "industry": "银行",
    "list_date": "1991-04-03"
  }
}
```

### GET /api/kline?code=000001.SZ&period=1d&start=20240101&end=20250101

查询 K 线数据。

参数：
- `code` (必填) — 股票代码
- `period` (必填) — `1d` / `5m` / `1m`
- `start` (可选) — YYYYMMDD，默认最近 250 条
- `end` (可选) — YYYYMMDD，默认最新

响应：
```json
{
  "code": 0,
  "data": {
    "stock_code": "000001.SZ",
    "stock_name": "平安银行",
    "period": "1d",
    "count": 250,
    "kline": [
      {
        "time": "2024-01-02",
        "open": 10.5,
        "high": 10.8,
        "low": 10.3,
        "close": 10.6,
        "volume": 12345678,
        "amount": 130000000.0
      }
    ]
  }
}
```

### 错误处理

- 股票代码不存在 → 404
- 参数格式错误 → 422（FastAPI 自动校验）
- 服务内部错误 → 500

## 技术栈

- Python 3.13
- xtquant (已安装 v250516.1.1)
- DuckDB (待安装)
- FastAPI + uvicorn
- APScheduler
- pandas (xtquant 依赖)

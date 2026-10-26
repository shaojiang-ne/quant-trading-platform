# A股本地数据库 实现计划

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 构建本地A股数据库，存储全量K线数据，定时增量更新，提供HTTPS查询接口。

**Architecture:** 单进程一体化架构，FastAPI + APScheduler + DuckDB。xtquant 通过 QMT 客户端获取数据，DuckDB 按周期分表存储K线，APScheduler 每日 15:30 触发增量同步。

**Tech Stack:** Python 3.13, xtquant, DuckDB, FastAPI, uvicorn, APScheduler, pandas

---

## File Structure

| File | Responsibility |
|------|---------------|
| `config.py` | 全局配置常量 |
| `main.py` | 入口：启动 FastAPI + Scheduler |
| `db/__init__.py` | 包初始化 |
| `db/connection.py` | DuckDB 连接管理，线程安全单写多读 |
| `db/schema.py` | 建表 DDL |
| `db/repository.py` | K线数据 CRUD 操作 |
| `data/__init__.py` | 包初始化 |
| `data/xtdata_client.py` | xtquant API 封装 |
| `data/sync.py` | 全量/增量同步逻辑 |
| `api/__init__.py` | 包初始化 |
| `api/routes.py` | FastAPI 路由 |
| `scheduler/__init__.py` | 包初始化 |
| `scheduler/jobs.py` | APScheduler 任务定义 |
| `requirements.txt` | 依赖清单 |

---

### Task 1: 项目初始化与配置

**Files:**
- Create: `config.py`
- Create: `requirements.txt`

- [ ] **Step 1: 创建 requirements.txt**

```
duckdb>=1.1.0
fastapi>=0.115.0
uvicorn>=0.32.0
apscheduler>=3.10.0
pandas>=2.0.0
pydantic>=2.0.0
```

- [ ] **Step 2: 安装依赖**

Run: `pip install -r requirements.txt`
Expected: 所有包安装成功

- [ ] **Step 3: 创建 config.py**

```python
import os

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
DATA_DIR = os.path.join(BASE_DIR, "data")
DB_PATH = os.path.join(DATA_DIR, "stock.duckdb")

DAILY_YEARS = 10
MIN5_YEARS = 1
MIN1_YEARS = 1

SYNC_HOUR = 15
SYNC_MINUTE = 30

BATCH_SIZE = 50

HTTP_HOST = "0.0.0.0"
HTTP_PORT = 8000

KLINE_PERIODS = ("1d", "5m", "1m")
KLINE_TABLE_MAP = {"1d": "kline_daily", "5m": "kline_5min", "1m": "kline_1min"}
```

- [ ] **Step 4: 创建包目录和 __init__.py 文件**

创建 `db/`, `data/`, `api/`, `scheduler/` 目录及空 `__init__.py`。

创建 `data/` 数据目录（与包 `data/` 同名但路径不同，数据目录在项目根下）。

注意：Python 包 `data/` 和数据存储目录 `data/` 会冲突。将数据存储目录改名为 `db_data/`。

更新 config.py 中 DATA_DIR:

```python
DATA_DIR = os.path.join(BASE_DIR, "db_data")
```

- [ ] **Step 5: Commit**

```bash
git init
git add config.py requirements.txt db/__init__.py data/__init__.py api/__init__.py scheduler/__init__.py
git commit -m "feat: project init with config and dependencies"
```

---

### Task 2: DuckDB 连接管理与建表

**Files:**
- Create: `db/connection.py`
- Create: `db/schema.py`

- [ ] **Step 1: 创建 db/connection.py**

```python
import threading
import duckdb
from config import DB_PATH, DATA_DIR
import os


_lock = threading.Lock()
_conn = None


def get_connection() -> duckdb.DuckDBPyConnection:
    global _conn
    if _conn is None:
        os.makedirs(DATA_DIR, exist_ok=True)
        _conn = duckdb.connect(DB_PATH)
    return _conn


def execute_write(sql: str, params=None):
    with _lock:
        conn = get_connection()
        if params:
            conn.execute(sql, params)
        else:
            conn.execute(sql)


def execute_read(sql: str, params=None):
    conn = get_connection()
    if params:
        return conn.execute(sql, params).fetchall()
    return conn.execute(sql).fetchall()


def execute_read_df(sql: str, params=None):
    conn = get_connection()
    if params:
        return conn.execute(sql, params).fetchdf()
    return conn.execute(sql).fetchdf()
```

- [ ] **Step 2: 创建 db/schema.py**

```python
from db.connection import execute_write


SCHEMA_SQL = """
CREATE TABLE IF NOT EXISTS kline_daily (
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

CREATE TABLE IF NOT EXISTS kline_5min (
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

CREATE TABLE IF NOT EXISTS kline_1min (
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

CREATE TABLE IF NOT EXISTS stock_info (
    stock_code  VARCHAR PRIMARY KEY,
    stock_name  VARCHAR,
    industry    VARCHAR,
    list_date   DATE,
    updated_at  TIMESTAMP
);

CREATE TABLE IF NOT EXISTS sync_status (
    stock_code  VARCHAR NOT NULL,
    period      VARCHAR NOT NULL,
    last_sync_time TIMESTAMP,
    PRIMARY KEY (stock_code, period)
);
"""


def init_schema():
    execute_write(SCHEMA_SQL)
```

- [ ] **Step 3: 验证建表**

Run: `python -c "from db.schema import init_schema; init_schema(); print('Schema created')"`
Expected: `Schema created`

Run: `python -c "from db.connection import execute_read; print(execute_read('SHOW TABLES'))"`
Expected: 列出 5 张表

- [ ] **Step 4: Commit**

```bash
git add db/connection.py db/schema.py
git commit -m "feat: DuckDB connection management and schema"
```

---

### Task 3: 数据读写操作层

**Files:**
- Create: `db/repository.py`

- [ ] **Step 1: 创建 db/repository.py**

```python
import pandas as pd
from db.connection import execute_write, execute_read, execute_read_df
from config import KLINE_TABLE_MAP


def upsert_kline(table_name: str, df: pd.DataFrame):
    if df.empty:
        return
    cols = ["stock_code", "trade_time", "open", "high", "low", "close", "volume", "amount"]
    df = df[cols]
    from db.connection import _lock, get_connection
    with _lock:
        conn = get_connection()
        conn.execute(
            f"INSERT OR REPLACE INTO {table_name} ({', '.join(cols)}) SELECT {', '.join(cols)} FROM df"
        )


def query_kline(period: str, stock_code: str, start_time: str = "", end_time: str = "", limit: int = 250):
    table = KLINE_TABLE_MAP[period]
    conditions = ["stock_code = ?"]
    params = [stock_code]
    if start_time:
        conditions.append("trade_time >= ?")
        params.append(start_time)
    if end_time:
        conditions.append("trade_time <= ?")
        params.append(end_time)
    where = " AND ".join(conditions)
    sql = f"SELECT * FROM {table} WHERE {where} ORDER BY trade_time"
    if not start_time and not end_time:
        sql = f"SELECT * FROM (SELECT * FROM {table} WHERE {where} ORDER BY trade_time DESC LIMIT {limit}) ORDER BY trade_time"
    return execute_read_df(sql, params)


def get_last_sync_time(stock_code: str, period: str):
    rows = execute_read(
        "SELECT last_sync_time FROM sync_status WHERE stock_code = ? AND period = ?",
        [stock_code, period]
    )
    if rows and rows[0][0]:
        return str(rows[0][0])
    return None


def update_sync_status(stock_code: str, period: str, last_time: str):
    execute_write(
        "INSERT OR REPLACE INTO sync_status (stock_code, period, last_sync_time) VALUES (?, ?, ?)",
        [stock_code, period, last_time]
    )


def upsert_stock_info(stock_code: str, stock_name: str, industry: str = None, list_date: str = None):
    execute_write(
        "INSERT OR REPLACE INTO stock_info (stock_code, stock_name, industry, list_date, updated_at) VALUES (?, ?, ?, ?, CURRENT_TIMESTAMP)",
        [stock_code, stock_name, industry, list_date]
    )


def get_stock_list():
    return execute_read_df("SELECT stock_code, stock_name FROM stock_info ORDER BY stock_code")


def get_stock_info(stock_code: str):
    rows = execute_read(
        "SELECT stock_code, stock_name, industry, list_date FROM stock_info WHERE stock_code = ?",
        [stock_code]
    )
    if rows:
        return {
            "stock_code": rows[0][0],
            "stock_name": rows[0][1],
            "industry": rows[0][2],
            "list_date": str(rows[0][3]) if rows[0][3] else None,
        }
    return None
```

- [ ] **Step 2: 验证 repository**

Run: `python -c "from db.repository import upsert_stock_info, get_stock_info; upsert_stock_info('000001.SZ', '平安银行'); print(get_stock_info('000001.SZ'))"`
Expected: 输出包含平安银行信息的字典

- [ ] **Step 3: Commit**

```bash
git add db/repository.py
git commit -m "feat: data repository layer with upsert and query"
```

---

### Task 4: xtquant 数据获取封装

**Files:**
- Create: `data/xtdata_client.py`

- [ ] **Step 1: 创建 data/xtdata_client.py**

```python
from xtquant import xtdata
from config import BATCH_SIZE


def get_all_stock_codes() -> list[str]:
    xtdata.connect()
    codes = xtdata.get_stock_list_in_sector("沪深A股")
    return codes


def download_kline(stock_codes: list[str], period: str, start_time: str, end_time: str = "") -> bool:
    xtdata.connect()
    result = xtdata.download_history_data2(
        stock_list=stock_codes,
        period=period,
        start_time=start_time,
        end_time=end_time,
    )
    return result


def get_kline_data(stock_code: str, period: str, start_time: str = "", end_time: str = "") -> "pd.DataFrame":
    import pandas as pd
    xtdata.connect()
    data = xtdata.get_market_data_ex(
        field_list=[],
        stock_list=[stock_code],
        period=period,
        start_time=start_time,
        end_time=end_time,
        dividend_type="none",
        fill_data=True,
    )
    if stock_code not in data:
        return pd.DataFrame()
    df = data[stock_code]
    df = df.reset_index()
    df = df.rename(columns={
        "time": "trade_time",
        "open": "open",
        "high": "high",
        "low": "low",
        "close": "close",
        "volume": "volume",
        "amount": "amount",
    })
    df["stock_code"] = stock_code
    cols = ["stock_code", "trade_time", "open", "high", "low", "close", "volume", "amount"]
    for c in cols:
        if c not in df.columns:
            df[c] = None
    return df[cols]


def get_stock_detail(stock_code: str) -> dict:
    xtdata.connect()
    detail = xtdata.get_instrument_detail(stock_code)
    if detail:
        return {
            "stock_code": stock_code,
            "stock_name": detail.get("InstrumentName", ""),
            "industry": detail.get("ProductClass", ""),
            "list_date": str(detail.get("OpenDate", "")),
        }
    return None


def batch_download_and_get(stock_codes: list[str], period: str, start_time: str, end_time: str = "") -> "list[pd.DataFrame]":
    import pandas as pd
    results = []
    for i in range(0, len(stock_codes), BATCH_SIZE):
        batch = stock_codes[i:i + BATCH_SIZE]
        download_kline(batch, period, start_time, end_time)
        for code in batch:
            try:
                df = get_kline_data(code, period, start_time, end_time)
                if not df.empty:
                    results.append(df)
            except Exception:
                continue
    return results
```

- [ ] **Step 2: 验证 xtdata_client（需 QMT 运行）**

Run: `python -c "from data.xtdata_client import get_all_stock_codes; codes = get_all_stock_codes(); print(f'Total stocks: {len(codes)}'); print(codes[:5])"`
Expected: 输出股票总数和前5个代码

- [ ] **Step 3: Commit**

```bash
git add data/xtdata_client.py
git commit -m "feat: xtquant data client wrapper"
```

---

### Task 5: 增量同步逻辑

**Files:**
- Create: `data/sync.py`

- [ ] **Step 1: 创建 data/sync.py**

```python
from datetime import datetime, timedelta
import logging
from data.xtdata_client import get_all_stock_codes, batch_download_and_get, get_stock_detail
from db.repository import upsert_kline, update_sync_status, get_last_sync_time, upsert_stock_info
from db.connection import execute_read
from config import DAILY_YEARS, MIN5_YEARS, MIN1_YEARS, KLINE_TABLE_MAP

logger = logging.getLogger(__name__)


def _start_time_for_period(period: str) -> str:
    now = datetime.now()
    if period == "1d":
        start = now - timedelta(days=DAILY_YEARS * 365)
    elif period == "5m":
        start = now - timedelta(days=MIN5_YEARS * 365)
    elif period == "1m":
        start = now - timedelta(days=MIN1_YEARS * 365)
    else:
        start = now - timedelta(days=3650)
    return start.strftime("%Y%m%d")


def sync_stock_info():
    codes = get_all_stock_codes()
    for code in codes:
        try:
            detail = get_stock_detail(code)
            if detail:
                upsert_stock_info(
                    stock_code=code,
                    stock_name=detail["stock_name"],
                    industry=detail.get("industry"),
                    list_date=detail.get("list_date"),
                )
        except Exception as e:
            logger.warning(f"Failed to sync stock info for {code}: {e}")
    logger.info(f"Synced stock info for {len(codes)} stocks")


def sync_kline_period(period: str, stock_codes: list[str] = None, full: bool = False):
    if stock_codes is None:
        stock_codes = get_all_stock_codes()

    table = KLINE_TABLE_MAP[period]
    default_start = _start_time_for_period(period)

    for code in stock_codes:
        try:
            if full:
                start_time = default_start
            else:
                last = get_last_sync_time(code, period)
                if last:
                    start_time = last
                else:
                    start_time = default_start

            dfs = batch_download_and_get([code], period, start_time)
            for df in dfs:
                if not df.empty:
                    upsert_kline(table, df)
                    last_time = df["trade_time"].max()
                    update_sync_status(code, period, str(last_time))

        except Exception as e:
            logger.warning(f"Failed to sync {code} {period}: {e}")

    logger.info(f"Synced {period} kline for {len(stock_codes)} stocks")


def full_sync():
    logger.info("Starting full sync...")
    sync_stock_info()
    for period in ("1d", "5m", "1m"):
        sync_kline_period(period, full=True)
    logger.info("Full sync completed")


def incremental_sync():
    logger.info("Starting incremental sync...")
    sync_stock_info()
    for period in ("1d", "5m", "1m"):
        sync_kline_period(period, full=False)
    logger.info("Incremental sync completed")
```

- [ ] **Step 2: 验证同步逻辑（小范围测试）**

Run: `python -c "from data.sync import sync_kline_period; sync_kline_period('1d', stock_codes=['000001.SZ'], full=True); print('Done')"`
Expected: `Done`，DuckDB 中应有 000001.SZ 的日线数据

- [ ] **Step 3: Commit**

```bash
git add data/sync.py
git commit -m "feat: full and incremental sync logic"
```

---

### Task 6: FastAPI 路由

**Files:**
- Create: `api/routes.py`

- [ ] **Step 1: 创建 api/routes.py**

```python
from fastapi import FastAPI, HTTPException, Query
from db.repository import query_kline, get_stock_list, get_stock_info
from config import KLINE_PERIODS

app = FastAPI(title="A股数据库", version="1.0.0")


@app.get("/api/stock/list")
def stock_list():
    df = get_stock_list()
    return {
        "code": 0,
        "data": df.to_dict(orient="records") if not df.empty else [],
    }


@app.get("/api/stock/info")
def stock_info(code: str = Query(..., description="股票代码，如 000001.SZ")):
    info = get_stock_info(code)
    if not info:
        raise HTTPException(status_code=404, detail=f"Stock {code} not found")
    return {"code": 0, "data": info}


@app.get("/api/kline")
def kline(
    code: str = Query(..., description="股票代码"),
    period: str = Query(..., description="周期: 1d, 5m, 1m"),
    start: str = Query("", description="起始日期 YYYYMMDD"),
    end: str = Query("", description="结束日期 YYYYMMDD"),
):
    if period not in KLINE_PERIODS:
        raise HTTPException(status_code=422, detail=f"Invalid period: {period}, must be one of {KLINE_PERIODS}")

    info = get_stock_info(code)
    if not info:
        raise HTTPException(status_code=404, detail=f"Stock {code} not found")

    df = query_kline(period, code, start, end)
    kline_data = []
    if not df.empty:
        for _, row in df.iterrows():
            kline_data.append({
                "time": str(row["trade_time"]),
                "open": row["open"],
                "high": row["high"],
                "low": row["low"],
                "close": row["close"],
                "volume": int(row["volume"]) if row["volume"] else 0,
                "amount": row["amount"],
            })

    return {
        "code": 0,
        "data": {
            "stock_code": code,
            "stock_name": info["stock_name"],
            "period": period,
            "count": len(kline_data),
            "kline": kline_data,
        },
    }
```

- [ ] **Step 2: 验证 API**

Run: `uvicorn api.routes:app --host 0.0.0.0 --port 8000 &`

Run: `curl http://localhost:8000/api/stock/list`
Expected: JSON 响应含股票列表

Run: `curl "http://localhost:8000/api/kline?code=000001.SZ&period=1d"`
Expected: JSON 响应含K线数据

- [ ] **Step 3: Commit**

```bash
git add api/routes.py
git commit -m "feat: FastAPI routes for stock list, info, and kline"
```

---

### Task 7: APScheduler 定时任务

**Files:**
- Create: `scheduler/jobs.py`

- [ ] **Step 1: 创建 scheduler/jobs.py**

```python
from apscheduler.schedulers.background import BackgroundScheduler
from config import SYNC_HOUR, SYNC_MINUTE


scheduler = BackgroundScheduler()


def start_scheduler():
    from data.sync import incremental_sync
    scheduler.add_job(
        incremental_sync,
        "cron",
        hour=SYNC_HOUR,
        minute=SYNC_MINUTE,
        id="incremental_sync",
        replace_existing=True,
    )
    scheduler.start()
```

- [ ] **Step 2: Commit**

```bash
git add scheduler/jobs.py
git commit -m "feat: APScheduler daily incremental sync job"
```

---

### Task 8: 主入口整合

**Files:**
- Create: `main.py`

- [ ] **Step 1: 创建 main.py**

```python
import uvicorn
from db.schema import init_schema
from scheduler.jobs import start_scheduler
from api.routes import app


def main():
    init_schema()
    start_scheduler()
    uvicorn.run(app, host="0.0.0.0", port=8000)


if __name__ == "__main__":
    main()
```

- [ ] **Step 2: 端到端验证**

Run: `python main.py`

验证：
1. 服务启动成功，监听 8000 端口
2. `curl http://localhost:8000/api/stock/list` 返回数据
3. `curl "http://localhost:8000/api/kline?code=000001.SZ&period=1d"` 返回K线数据
4. 定时任务已注册（日志输出）

- [ ] **Step 3: Commit**

```bash
git add main.py
git commit -m "feat: main entry point integrating FastAPI and Scheduler"
```

---

### Task 9: 首次全量同步脚本

**Files:**
- Create: `scripts/full_sync.py`

- [ ] **Step 1: 创建 scripts/full_sync.py**

```python
import sys
import os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from db.schema import init_schema
from data.sync import full_sync


if __name__ == "__main__":
    init_schema()
    full_sync()
```

- [ ] **Step 2: 验证全量同步**

Run: `python scripts/full_sync.py`
Expected: 下载并写入所有股票数据（耗时较长，约 1-2 小时）

- [ ] **Step 3: Commit**

```bash
git add scripts/full_sync.py
git commit -m "feat: standalone full sync script"
```

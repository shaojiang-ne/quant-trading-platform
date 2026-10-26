import asyncio
import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.config import settings
from app.database import engine, Base
from app.api import api_router
from app.ws.handlers import websocket_endpoint
from app.core.engine import engine_manager
from app.core.event_handler import event_handler
from app.services.trade_sync_service import trade_sync_service

# ── 全局 requests 连接池补丁 ──────────────────────────────────────────────────
# akshare 等第三方库内部用裸 requests.get()（每次新建 Session → TCP 连接用完即丢 → TIME_WAIT 堆积）。
# 给 requests 模块级默认方法挂一个带连接池的 Session，使裸调用也复用连接，避免端口耗尽。
#
# 【关键】akshare utils/request.py 的 request_with_retry 每次请求都新建 Session 并禁用连接池
# （pool_connections=1, pool_maxsize=1），导致每次 HTTP 请求都新建 TCP 连接 → TIME_WAIT 堆积。
# stock_zh_a_spot_em() 通过 fetch_paginated_data 分页拉取 5000+ 只股票（50+ 次请求），
# 每 3 秒轮询一次 = 每分钟 1000+ 个新 TCP 连接 → 几小时后端口耗尽。
#
# 修复策略：
# 1. monkey-patch requests.Session.__init__，让所有新建 Session 自动挂载带连接池的 Adapter
# 2. 同时保留模块级 get/post 补丁，覆盖裸 requests.get() 调用
import requests as _requests
from requests.adapters import HTTPAdapter as _HTTPAdapter
from urllib3.util.retry import Retry as _Retry

# 连接池参数：足够覆盖项目连接的所有主机（东财/腾讯/新浪/巨潮/同花顺等约 10 个不同域名）
_POOL_CONNECTIONS = 20   # 连接池数量（每个 host 一个池）
_POOL_MAXSIZE = 10       # 每个池最大连接数
_MAX_RETRIES = _Retry(total=2, backoff_factor=0.5, status_forcelist=[502, 503, 504])

# 全局共享 Session（供模块级 get/post 补丁使用）
_REQUESTS_SESSION = _requests.Session()
_REQUESTS_SESSION.mount("https://", _HTTPAdapter(
    pool_connections=_POOL_CONNECTIONS,
    pool_maxsize=_POOL_MAXSIZE,
    max_retries=_MAX_RETRIES,
))
_REQUESTS_SESSION.mount("http://", _HTTPAdapter(
    pool_connections=_POOL_CONNECTIONS,
    pool_maxsize=_POOL_MAXSIZE,
    max_retries=_MAX_RETRIES,
))

# 替换模块级 get/post/put/delete/patch/head/options，使裸调用走连接池 Session
_requests.get = _REQUESTS_SESSION.get
_requests.post = _REQUESTS_SESSION.post
_requests.put = _REQUESTS_SESSION.put
_requests.delete = _REQUESTS_SESSION.delete
_requests.patch = _REQUESTS_SESSION.patch
_requests.head = _REQUESTS_SESSION.head
_requests.options = _REQUESTS_SESSION.options

# ── monkey-patch requests.Session.__init__ ──────────────────────────────────
# 让所有新建的 Session（包括 akshare request_with_retry 里的临时 Session）
# 自动挂载带连接池的 Adapter，而不是默认的 pool_connections=1/pool_maxsize=1。
# 这样即使 akshare 每次新建 Session，底层 urllib3 连接池仍然复用 TCP 连接。
_OriginalSessionInit = _requests.Session.__init__

def _patched_session_init(self, *args, **kwargs):
    _OriginalSessionInit(self, *args, **kwargs)
    # 覆盖默认 Adapter 为带连接池的版本
    self.mount("https://", _HTTPAdapter(
        pool_connections=_POOL_CONNECTIONS,
        pool_maxsize=_POOL_MAXSIZE,
        max_retries=_MAX_RETRIES,
    ))
    self.mount("http://", _HTTPAdapter(
        pool_connections=_POOL_CONNECTIONS,
        pool_maxsize=_POOL_MAXSIZE,
        max_retries=_MAX_RETRIES,
    ))

_requests.Session.__init__ = _patched_session_init

# ── monkey-patch akshare request_with_retry ─────────────────────────────────
# akshare utils/request.py 的 request_with_retry 每次请求都：
#   with requests.Session() as session:  ← 新建临时 Session
#       adapter = HTTPAdapter(pool_connections=1, pool_maxsize=1)  ← 禁用连接池
#       session.mount(...)
#       response = session.get(url, ...)
#   ← with 退出时 Session.close() 关闭所有连接 → TCP 进入 TIME_WAIT
#
# 即使 __init__ patch 让新建 Session 带连接池，with 退出时 close() 仍会清空池。
# 根治方案：patch request_with_retry，改为使用全局共享 Session（_REQUESTS_SESSION），
# 连接在 Session 生命周期内持续复用，不再每次新建/关闭。
try:
    import akshare.utils.request as _ak_req

    def _patched_request_with_retry(
        url, params=None, timeout=15, max_retries=3,
        base_delay=1.0, random_delay_range=(0.5, 1.5),
    ):
        """使用全局共享 Session 的 request_with_retry 替代实现。
        连接池复用 TCP 连接，避免 TIME_WAIT 堆积。"""
        import random
        import time as _time
        last_exception = None
        for attempt in range(max_retries):
            try:
                response = _REQUESTS_SESSION.get(url, params=params, timeout=timeout)
                response.raise_for_status()
                return response
            except (_requests.RequestException, ValueError) as e:
                last_exception = e
                if attempt < max_retries - 1:
                    delay = base_delay * (2 ** attempt) + random.uniform(*random_delay_range)
                    _time.sleep(delay)
        raise last_exception

    _ak_req.request_with_retry = _patched_request_with_retry

    # 同时 patch func.py 中的直接引用（from ... import 绑定的是函数对象，修改模块属性无法覆盖）
    try:
        import akshare.utils.func as _ak_func
        _ak_func.request_with_retry = _patched_request_with_retry
    except ImportError:
        pass

    logging.info("akshare request_with_retry 已替换为全局连接池版本")
except ImportError:
    pass  # akshare 未安装，跳过

# 配置日志
logging.basicConfig(level=logging.INFO, format="[backend] %(asctime)s %(levelname)s %(name)s %(message)s")

# 降噪：第三方库日志级别调高
logging.getLogger("uvicorn.access").setLevel(logging.WARNING)
logging.getLogger("uvicorn.error").setLevel(logging.WARNING)
logging.getLogger("httpx").setLevel(logging.WARNING)
logging.getLogger("httpcore").setLevel(logging.WARNING)
logging.getLogger("websockets").setLevel(logging.WARNING)
logging.getLogger("sqlalchemy.engine").setLevel(logging.WARNING)

logger = logging.getLogger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI):
    """应用生命周期管理"""
    # 启动时
    logger.info(f"启动 {settings.APP_NAME} v{settings.VERSION}")
    logger.info(f"行情后端: {settings.MARKET_BACKEND}"
                + (f" ({settings.STOCK_DATA_URL})" if settings.MARKET_BACKEND == "stock_data" else ""))
    logger.info(f"交易后端: {settings.TRADE_BACKEND}"
                + (f" ({settings.STOCK_TRADE_URL})" if settings.TRADE_BACKEND == "stock_trade" else ""))

    # 创建数据库表
    Base.metadata.create_all(bind=engine)
    logger.info("数据库表已创建")

    # 迁移：为已有表添加新列（SQLite 不支持 ALTER ADD COLUMN 通过 create_all）
    if settings.DATABASE_URL.startswith("sqlite"):
        import sqlite3
        db_path = settings.DATABASE_URL.replace("sqlite:///", "")
        if db_path and db_path != ":memory:":
            conn = sqlite3.connect(db_path)
            cursor = conn.cursor()
            # 检查 intraday_results 列是否存在
            cursor.execute("PRAGMA table_info(backtest_results)")
            columns = {row[1] for row in cursor.fetchall()}
            if "intraday_results" not in columns:
                cursor.execute("ALTER TABLE backtest_results ADD COLUMN intraday_results JSON DEFAULT '[]'")
                conn.commit()
                logger.info("已添加 intraday_results 列到 backtest_results 表")
            # 迁移：为 backtest_results 表添加回测配置字段
            for col_name, col_type in [
                ("period", "VARCHAR(10) DEFAULT 'daily'"),
                ("initial_position", "INTEGER DEFAULT 0"),
                ("commission_rate", "NUMERIC(10, 6) DEFAULT 0.0003"),
                ("stamp_tax_rate", "NUMERIC(10, 6) DEFAULT 0.001"),
            ]:
                if col_name not in columns:
                    cursor.execute(f"ALTER TABLE backtest_results ADD COLUMN {col_name} {col_type}")
                    logger.info(f"已添加 {col_name} 列到 backtest_results 表")
            # 迁移：为 orders 表添加新列
            cursor.execute("PRAGMA table_info(orders)")
            order_columns = {row[1] for row in cursor.fetchall()}
            for col_name, col_type in [("source", "VARCHAR(20) DEFAULT 'manual'"), ("signal_id", "VARCHAR(36)"), ("gateway_order_id", "VARCHAR(50)")]:
                if col_name not in order_columns:
                    cursor.execute(f"ALTER TABLE orders ADD COLUMN {col_name} {col_type}")
                    logger.info(f"已添加 {col_name} 列到 orders 表")
            conn.commit()
            conn.close()

    # 初始化vnpy引擎（如果可用）
    if engine_manager.available:
        engine_manager.get_engine()
        # 注册模拟网关供策略运行器使用
        try:
            from app.core.vnpy_sim_gateway import SimulatedStockGateway
            engine_manager._main_engine.add_gateway(SimulatedStockGateway)
        except Exception:
            pass
        event_handler.register()
        logger.info("vnpy引擎已初始化")
    else:
        logger.info("vnpy不可用，运行在模拟模式")

    # 初始化 vnpy 策略运行器
    try:
        from app.services.vnpy_strategy_runner import vnpy_strategy_runner
        vnpy_strategy_runner._ensure_engine()
        logger.info("vnpy策略运行器已初始化")
    except Exception as e:
        logger.warning(f"vnpy策略运行器初始化异常: {e}")

    # 恢复 DB 中的模拟交易实例到策略运行器
    try:
        from app.database import SessionLocal
        from app.models import TradingInstance, Strategy
        from app.services.vnpy_strategy_runner import vnpy_strategy_runner as strategy_runner

        db = SessionLocal()
        all_instances = db.query(TradingInstance).all()
        for inst in all_instances:
            if inst.id not in strategy_runner._instances:
                strategy = db.query(Strategy).filter(Strategy.id == inst.strategy_id).first()
                class_name = strategy.class_name if strategy else ""
                params = inst.params or (strategy.parameters if strategy else {})
                if isinstance(params, str):
                    import json
                    params = json.loads(params)
                initial_equity = float(inst.current_equity) if inst.current_equity else 1000000
                strategy_runner.register(
                    instance_id=inst.id,
                    symbol=inst.symbol,
                    strategy_id=inst.strategy_id,
                    account_id=inst.account_id,
                    mode=inst.mode,
                    initial_equity=initial_equity,
                    class_name=class_name,
                    params=params,
                    # auto_trade_enabled/confirm_required 留 None，register() 按 mode 取默认值
                )
                # 模拟实例从 DB 恢复模拟账户数据（余额、持仓）
                if inst.mode == "simulation":
                    strategy_runner.load_sim_account_from_db(inst.id)
                logger.info(f"已恢复实例: {inst.id} ({inst.name}, {inst.mode})")
        # 重启之前状态为 running 的实例
        running_instances = [i for i in all_instances if i.status == "running"]
        for inst in running_instances:
            strategy_runner.start(inst.id)
            logger.info(f"已重启实例: {inst.id} ({inst.name}, {inst.mode})")
        db.close()
        logger.info(f"实例恢复完成: 共 {len(all_instances)} 个，重启 {len(running_instances)} 个")
    except Exception as e:
        logger.warning(f"模拟实例恢复异常: {e}")

    # 初始化行情服务
    from app.services.market_service import market_service
    market_service.is_available()

    # 自动连接交易网关（后台执行，不阻塞启动）
    from app.core.live_gateway import live_gateway
    from app.ws.manager import ws_manager

    async def on_gateway_disconnect(message: str):
        """网关断连通知回调"""
        await ws_manager.broadcast({
            "type": "gateway_disconnected",
            "data": {"message": message},
        })

    live_gateway._set_disconnect_callback(on_gateway_disconnect)
    # 使用后台连接，避免交易网关不可达时阻塞整个应用启动
    asyncio.create_task(live_gateway.auto_connect_background())
    logger.info("交易网关后台连接已启动")

    # 启动交易同步服务
    try:
        await trade_sync_service.start()
        logger.info("交易同步服务已启动")
    except Exception as e:
        logger.warning(f"交易同步服务启动异常: {e}")

    # 启动 AI 智能体后台循环：定时选股 + 盯盘引擎（交易时段每分钟执行一次）
    agent_stop_event = asyncio.Event()
    agent_tasks: list[asyncio.Task] = []
    try:
        from app.services.agent_service import scheduled_pick_loop, monitor_engine_loop
        agent_tasks.append(asyncio.create_task(scheduled_pick_loop(agent_stop_event)))
        agent_tasks.append(asyncio.create_task(monitor_engine_loop(agent_stop_event)))
        logger.info("AI智能体后台循环已启动（定时选股 / 盯盘引擎）")
    except Exception as e:
        logger.warning(f"AI智能体后台循环启动异常: {e}")

    yield

    # 停止 AI 智能体后台循环
    agent_stop_event.set()
    for t in agent_tasks:
        t.cancel()
    for t in agent_tasks:
        try:
            await t
        except (asyncio.CancelledError, Exception):
            pass

    # 停止交易同步服务
    try:
        await trade_sync_service.stop()
    except Exception:
        pass

    # 关闭策略运行器
    try:
        from app.services.vnpy_strategy_runner import vnpy_strategy_runner
        vnpy_strategy_runner.shutdown()
    except Exception:
        pass

    # 关闭实盘交易网关
    try:
        from app.core.live_gateway import live_gateway
        if live_gateway.is_connected:
            await live_gateway.disconnect()
            logger.info("交易网关已断开")
    except Exception:
        pass

    # 关闭行情服务
    try:
        from app.services.market_service import market_service
        market_service.close()
    except Exception:
        pass

    # 关闭全局 requests Session（释放连接池中的 TCP 连接）
    try:
        _REQUESTS_SESSION.close()
    except Exception:
        pass

    # 关闭 vnpy 实盘网关
    try:
        from app.core.vnpy_live_gateway import vnpy_live_gateway
        vnpy_live_gateway.disconnect()
    except Exception:
        pass

    # 关闭vnpy引擎
    try:
        engine_manager.shutdown()
    except Exception:
        pass
    logger.info("应用已关闭")


app = FastAPI(
    title=settings.APP_NAME,
    version=settings.VERSION,
    lifespan=lifespan,
)

# CORS - 允许前端访问
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],  # 生产环境应限制具体域名
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# 注册API路由
app.include_router(api_router)

# WebSocket路由
app.websocket("/ws")(websocket_endpoint)


@app.get("/")
def root():
    return {
        "name": settings.APP_NAME,
        "version": settings.VERSION,
        "docs": "/docs",
    }


@app.get("/health")
def health():
    from app.services.market_service import market_service
    from app.core.live_gateway import live_gateway

    trading_status = {
        "service": "trading",
        "status": "online" if live_gateway.is_connected else "offline",
        "xtquant": {
            "available": live_gateway.is_connected,
            "connected": live_gateway.is_connected,
            "error": "" if live_gateway.is_connected else "未连接交易网关",
        },
    }
    return {
        "status": "ok",
        "market": market_service.check_health(),
        "trading": trading_status,
    }


@app.get("/api/health")
def api_health():
    from app.services.market_service import market_service
    from app.core.live_gateway import live_gateway

    trading_status = {
        "service": "trading",
        "status": "online" if live_gateway.is_connected else "offline",
        "xtquant": {
            "available": live_gateway.is_connected,
            "connected": live_gateway.is_connected,
            "error": "" if live_gateway.is_connected else "未连接交易网关",
        },
    }
    return {
        "status": "ok",
        "market": market_service.check_health(),
        "trading": trading_status,
    }
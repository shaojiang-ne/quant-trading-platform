import asyncio
import logging
import json
import sys
from contextlib import asynccontextmanager
from pathlib import Path

import uvicorn
from fastapi import FastAPI, Request
from core.config import settings
from routers import health, orders, queries, ws


def _suppress_connection_reset(loop, context):
    """抑制 Windows ProactorEventLoop 的 ConnectionResetError 日志噪音"""
    exception = context.get("exception")
    if isinstance(exception, ConnectionResetError):
        return
    loop.default_exception_handler(context)


if sys.platform == "win32":
    asyncio.set_event_loop_policy(asyncio.WindowsSelectorEventLoopPolicy())

logging.basicConfig(
    level=logging.INFO,
    format="[stock_trade] %(asctime)s %(levelname)s %(name)s %(message)s",
)

# uvicorn access log handles normal request logging
logging.getLogger("uvicorn.access").setLevel(logging.INFO)
logger = logging.getLogger("stock_trade.main")

RECONNECT_INTERVAL = 5
_reconnect_task = None
_shutting_down = False


async def _reconnect_loop():
    """后台定时重连，直到连接成功"""
    import asyncio
    from core.gateway import gateway, run_sync
    attempt = 0
    while not _shutting_down:
        attempt += 1
        await asyncio.sleep(RECONNECT_INTERVAL)
        if _shutting_down or gateway.connected:
            if gateway.connected:
                logger.info("已连接成功，停止重连任务")
            return
        try:
            connected, msg = await run_sync(
                gateway.connect, settings.gateway.get_effective_qmt_path(), settings.gateway.session_id
            )
            if connected:
                logger.info("重连成功(第%d次尝试): %s", attempt, msg)
                return
            logger.warning("重连失败(第%d次): %s, %ds后重试", attempt, msg, RECONNECT_INTERVAL)
        except Exception as e:
            logger.error("重连异常(第%d次): %s, %ds后重试", attempt, e, RECONNECT_INTERVAL)


def _start_reconnect():
    """启动重连任务（如果尚未启动）"""
    import asyncio
    global _reconnect_task
    if _reconnect_task and not _reconnect_task.done():
        return
    logger.info("将在后台每%ds尝试重连 xtquant", RECONNECT_INTERVAL)
    _reconnect_task = asyncio.create_task(_reconnect_loop())


@asynccontextmanager
async def lifespan(app: FastAPI):
    import asyncio
    from core.gateway import gateway, run_sync
    from routers.ws import manager
    gateway.ws_manager = manager
    loop = asyncio.get_event_loop()
    loop.set_exception_handler(_suppress_connection_reset)
    gateway.loop = loop

    # \u540e\u53f0\u8fde\u63a5 xtquant\uff0c\u4e0d\u963b\u585e\u542f\u52a8
    if settings.gateway.get_effective_qmt_path() and settings.gateway.session_id is not None:
        _start_reconnect()
    else:
        logger.warning("启动时跳过自动连接: qmt_path或session_id未配置")

    yield

    global _shutting_down
    _shutting_down = True
    if _reconnect_task and not _reconnect_task.done():
        _reconnect_task.cancel()
    gateway.shutdown()


app = FastAPI(title="Stock Trade Service", lifespan=lifespan)

app.include_router(health.router)
app.include_router(queries.router)
app.include_router(orders.router)
app.include_router(ws.router)


@app.get("/health")
async def health_shortcut():
    return await health.check_health()


@app.middleware("http")
async def request_logging_middleware(request: Request, call_next):
    """断线自动重连 + 出错时详细日志"""
    query_params = dict(request.query_params) if request.query_params else None
    body = None
    if request.method in ("POST", "PUT", "PATCH"):
        try:
            body = await request.json()
        except Exception:
            body = None

    response = await call_next(request)

    if response.status_code >= 400:
        detail = ""
        if query_params:
            detail += f" query={query_params}"
        if body:
            detail += f" body={json.dumps(body, ensure_ascii=False)}"
        logger.warning("%s %s %s%s", request.method, request.url.path, response.status_code, detail)

    # 断线时触发重连
    from core.gateway import gateway
    if not gateway.connected and settings.gateway.get_effective_qmt_path() and settings.gateway.session_id is not None:
        _start_reconnect()

    return response


if __name__ == "__main__":
    import datetime
    import ipaddress
    from cryptography import x509
    from cryptography.x509.oid import NameOID
    from cryptography.hazmat.primitives import hashes, serialization
    from cryptography.hazmat.primitives.asymmetric import rsa

    base = Path(__file__).parent
    cert = base / settings.server.ssl_cert if settings.server.ssl_cert else None
    key = base / settings.server.ssl_key if settings.server.ssl_key else None

    if cert and key and not (cert.exists() and key.exists()):
        k = rsa.generate_private_key(public_exponent=65537, key_size=2048)
        key.parent.mkdir(parents=True, exist_ok=True)
        key.write_bytes(k.private_bytes(
            serialization.Encoding.PEM,
            serialization.PrivateFormat.TraditionalOpenSSL,
            serialization.NoEncryption(),
        ))
        subject = issuer = x509.Name([
            x509.NameAttribute(NameOID.COMMON_NAME, "stock_trade"),
            x509.NameAttribute(NameOID.ORGANIZATION_NAME, "stock_trade"),
        ])
        crt = (
            x509.CertificateBuilder()
            .subject_name(subject)
            .issuer_name(issuer)
            .public_key(k.public_key())
            .serial_number(x509.random_serial_number())
            .not_valid_before(datetime.datetime.now(datetime.UTC))
            .not_valid_after(datetime.datetime.now(datetime.UTC) + datetime.timedelta(days=3650))
            .add_extension(x509.SubjectAlternativeName([x509.DNSName("localhost"), x509.IPAddress(ipaddress.IPv4Address("127.0.0.1"))]), critical=False)
            .sign(k, hashes.SHA256())
        )
        cert.parent.mkdir(parents=True, exist_ok=True)
        cert.write_bytes(crt.public_bytes(serialization.Encoding.PEM))
        print(f"Generated self-signed cert: {cert}, {key}")

    ssl_kwargs = {}
    if cert and key and cert.exists() and key.exists():
        ssl_kwargs["ssl_certfile"] = str(cert)
        ssl_kwargs["ssl_keyfile"] = str(key)

    uvicorn.run(
        app,
        host=settings.server.host,
        port=settings.server.port,
        timeout_graceful_shutdown=3,
        **ssl_kwargs,
    )
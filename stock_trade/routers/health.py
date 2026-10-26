import logging

from fastapi import APIRouter, Depends
from core.auth import verify_api_key
from core.gateway import gateway

router = APIRouter(prefix="/api/v1", tags=["health"])
logger = logging.getLogger("stock_trade.health")


async def check_health():
    error = None
    if not gateway.connected:
        if not gateway.trader:
            error = "交易网关未连接"
        elif gateway._last_connect_result is not None:
            error = f"连接失败(错误码: {gateway._last_connect_result})"
        else:
            error = "未连接"

    return {
        "status": "online" if gateway.connected else "degraded",
        "connected": gateway.connected,
        "account_id": gateway.account_id,
        "error": error,
    }


@router.get("/health")
async def health_check(_: str = Depends(verify_api_key)):
    return await check_health()

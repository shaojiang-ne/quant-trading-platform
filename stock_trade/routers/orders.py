import logging

from fastapi import APIRouter, Depends, HTTPException
from core.auth import verify_api_key
from core.gateway import gateway, run_sync
from models.request import OrderRequest

router = APIRouter(prefix="/api/v1", tags=["orders"])
logger = logging.getLogger("stock_trade.orders")


@router.post("/orders")
async def place_order(req: OrderRequest, _: str = Depends(verify_api_key)):
    try:
        return await run_sync(
            gateway.place_order,
            req.symbol, req.side, req.quantity, req.price, req.order_type,
        )
    except ConnectionError as e:
        raise HTTPException(status_code=503, detail=str(e))
    except Exception as e:
        logger.error("下单异常: %s", e, exc_info=True)
        raise HTTPException(status_code=500, detail=f"下单失败: {e}")


@router.delete("/orders/{order_id}")
async def cancel_order(order_id: str, _: str = Depends(verify_api_key)):
    try:
        return await run_sync(gateway.cancel_order, order_id)
    except ConnectionError as e:
        raise HTTPException(status_code=503, detail=str(e))
    except Exception as e:
        logger.error("撤单异常: order_id=%s, %s", order_id, e, exc_info=True)
        raise HTTPException(status_code=500, detail=f"撤单失败: {e}")

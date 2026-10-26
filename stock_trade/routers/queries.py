import logging

from fastapi import APIRouter, Depends, HTTPException, Query
from core.auth import verify_api_key
from core.gateway import gateway, run_sync

router = APIRouter(prefix="/api/v1", tags=["queries"])
logger = logging.getLogger("stock_trade.queries")


@router.get("/asset")
async def query_asset(_: str = Depends(verify_api_key)):
    try:
        return await run_sync(gateway.query_asset)
    except ConnectionError as e:
        raise HTTPException(status_code=503, detail=str(e))
    except Exception as e:
        logger.error("查询资产异常: %s", e, exc_info=True)
        raise HTTPException(status_code=500, detail=f"查询失败: {e}")


@router.get("/positions")
async def query_positions(_: str = Depends(verify_api_key)):
    try:
        return await run_sync(gateway.query_positions)
    except ConnectionError as e:
        raise HTTPException(status_code=503, detail=str(e))
    except Exception as e:
        logger.error("查询持仓异常: %s", e, exc_info=True)
        raise HTTPException(status_code=500, detail=f"查询失败: {e}")


@router.get("/orders")
async def query_orders(status: str = Query(default=""),
                       _: str = Depends(verify_api_key)):
    try:
        result = await run_sync(gateway.query_orders)
        if status:
            result["orders"] = [o for o in result["orders"] if o["status"] == status]
        return result
    except ConnectionError as e:
        raise HTTPException(status_code=503, detail=str(e))
    except Exception as e:
        logger.error("查询委托异常: %s", e, exc_info=True)
        raise HTTPException(status_code=500, detail=f"查询失败: {e}")


@router.get("/trades")
async def query_trades(_: str = Depends(verify_api_key)):
    try:
        return await run_sync(gateway.query_trades)
    except ConnectionError as e:
        raise HTTPException(status_code=503, detail=str(e))
    except Exception as e:
        logger.error("查询成交异常: %s", e, exc_info=True)
        raise HTTPException(status_code=500, detail=f"查询失败: {e}")

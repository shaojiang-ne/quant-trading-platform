from fastapi import APIRouter, HTTPException, Query, Request, Depends, WebSocket, WebSocketDisconnect
from pydantic import BaseModel
from typing import Optional
from datetime import datetime, timezone, timedelta
from data.xtdata_client import get_all_stock_codes, get_stock_detail, get_stock_detail_batch, get_kline_data, get_full_tick, _ensure_connected
from data.sync import is_sync_running, trigger_download
from config import API_KEY
import pandas as pd
import asyncio
import logging
import threading
import time

logger = logging.getLogger(__name__)


def _normalize_symbol(symbol: str) -> str:
    """自动补全股票代码后缀：6开头.SH，0/3开头.SZ，北交所8/4开头.BJ"""
    if "." in symbol:
        return symbol
    if symbol.startswith("6"):
        return symbol + ".SH"
    elif symbol.startswith("0") or symbol.startswith("3"):
        return symbol + ".SZ"
    elif symbol.startswith("8") or symbol.startswith("4"):
        return symbol + ".BJ"
    return symbol

_CST = timezone(timedelta(hours=8))

router = APIRouter()

# --- /stocks 缓存 ---
_stocks_cache_lock = threading.Lock()
_stocks_cache: dict | None = None
_stocks_cache_ts: float = 0
_STOCKS_CACHE_TTL = 300  # 5 minutes


# --- API Key 认证 ---


def verify_api_key(request: Request):
    if not API_KEY:
        return
    key = request.headers.get("X-API-Key", "")
    if key != API_KEY:
        raise HTTPException(status_code=401, detail="Invalid API Key")


# --- 1. 服务状态 ---


class XtquantStatus(BaseModel):
    available: bool
    connected: bool
    error: Optional[str] = None


class HealthResponse(BaseModel):
    service: str
    status: str
    xtquant: XtquantStatus


@router.get("/health", response_model=HealthResponse, dependencies=[Depends(verify_api_key)])
def health():
    xt_connected = _ensure_connected()
    xt_error = None if xt_connected else "xtdata service unavailable"
    return HealthResponse(
        service="stock_data",
        status="online",
        xtquant=XtquantStatus(
            available=xt_connected,
            connected=xt_connected,
            error=xt_error,
        ),
    )


# --- 2. K线数据 ---


DIVIDEND_TYPE_MAP = {"none": "none", "front": "front", "back": "back"}
XT_PERIOD_MAP = {
    "1m": "1m", "5m": "5m", "15m": "15m", "30m": "30m",
    "60m": "1h", "1h": "1h", "1d": "1d", "1w": "1w", "1mon": "1mon",
}


@router.get("/klines", dependencies=[Depends(verify_api_key)])
def klines(
    symbol: str = Query(..., description="股票代码，如 600519.SH"),
    period: str = Query("1d", description="周期: 1m/5m/15m/30m/60m/1h/1d/1w/1mon"),
    start_time: str = Query("", description="开始时间 YYYYMMDD"),
    end_time: str = Query("", description="结束时间 YYYYMMDD"),
    count: int = Query(-1, description="返回条数，-1表示全部"),
    dividend_type: str = Query("none", description="复权方式: none/front/back"),
):
    xt_period = XT_PERIOD_MAP.get(period)
    if not xt_period:
        raise HTTPException(status_code=422, detail=f"Invalid period: {period}")

    if dividend_type not in DIVIDEND_TYPE_MAP:
        raise HTTPException(status_code=422, detail=f"Invalid dividend_type: {dividend_type}")

    xt_dividend = DIVIDEND_TYPE_MAP[dividend_type]

    try:
        df = get_kline_data(symbol, xt_period, start_time, end_time, dividend_type=xt_dividend, count=count)
        if df.empty:
            return {
                "symbol": symbol,
                "period": period,
                "dividend_type": dividend_type,
                "count": 0,
                "klines": [],
            }

        # 向量化构建 kline_list，避免逐行 iterrows
        import numpy as np
        is_daily = period in ("1d", "1w", "1mon")
        dts = df["trade_time"]
        if is_daily:
            dt_strs = dts.dt.strftime("%Y%m%d")
        else:
            dt_strs = dts.dt.strftime("%Y%m%d%H%M%S")

        kline_list = [
            {
                "datetime": dt_strs.iloc[i],
                "open": float(df["open"].iloc[i]),
                "high": float(df["high"].iloc[i]),
                "low": float(df["low"].iloc[i]),
                "close": float(df["close"].iloc[i]),
                "volume": int(df["volume"].iloc[i]) if not pd.isna(df["volume"].iloc[i]) else 0,
                "amount": float(df["amount"].iloc[i]),
            }
            for i in range(len(df))
        ]

        if count > 0:
            kline_list = kline_list[-count:]

        return {
            "symbol": symbol,
            "period": period,
            "dividend_type": dividend_type,
            "count": len(kline_list),
            "klines": kline_list,
        }
    except RuntimeError as e:
        logger.error(f"[klines] xtdata unavailable for {symbol}: {e}")
        raise HTTPException(status_code=503, detail="xtdata service unavailable, please start MiniQMT")
    except Exception as e:
        logger.error(f"[klines] Failed for {symbol}: {e}")
        raise HTTPException(status_code=503, detail=f"Data source unavailable: {type(e).__name__}: {e}")


# --- 3. Tick 数据 ---


@router.get("/tick/{symbol}", dependencies=[Depends(verify_api_key)])
def tick(symbol: str):
    try:
        xt_symbol = _normalize_symbol(symbol)
        tick_data = get_full_tick([xt_symbol])
        if xt_symbol not in tick_data:
            raise HTTPException(status_code=404, detail=f"Tick data not found for {symbol}")
        t = tick_data[xt_symbol]
        ts = t.get("time", 0)
        dt_str = ""
        if ts:
            dt = datetime.fromtimestamp(ts / 1000, tz=_CST)
            dt_str = dt.strftime("%Y%m%d%H%M%S")
        return {
            "symbol": xt_symbol,
            "last_price": t.get("lastPrice", 0),
            "open": t.get("open", 0),
            "high": t.get("high", 0),
            "low": t.get("low", 0),
            "last_close": t.get("lastClose", 0),
            "volume": int(t.get("volume", 0)),
            "amount": t.get("amount", 0),
            "bid_prices": t.get("bidPrice", [0]*5)[:5],
            "bid_volumes": [int(v) for v in t.get("bidVol", [0]*5)[:5]],
            "ask_prices": t.get("askPrice", [0]*5)[:5],
            "ask_volumes": [int(v) for v in t.get("askVol", [0]*5)[:5]],
            "datetime": dt_str,
        }
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Failed to get tick for {symbol}: {e}")
        raise HTTPException(status_code=503, detail=f"Data source unavailable: {type(e).__name__}: {e}")


# --- 4. 股票列表 ---


@router.get("/stocks", dependencies=[Depends(verify_api_key)])
def stocks(
    sector: str = Query("沪深A股", description="板块名称"),
    limit: int = Query(0, description="返回数量，0表示全部"),
):
    global _stocks_cache, _stocks_cache_ts

    now = time.time()
    with _stocks_cache_lock:
        if _stocks_cache and (now - _stocks_cache_ts) < _STOCKS_CACHE_TTL:
            cached = _stocks_cache
            stock_list = cached["stocks"]
            if limit > 0:
                stock_list = stock_list[:limit]
            return {"sector": sector, "count": len(stock_list), "stocks": stock_list}

    try:
        codes = get_all_stock_codes()
    except Exception:
        raise HTTPException(status_code=503, detail=f"Data source unavailable: {type(e).__name__}: {e}")

    details = {}
    try:
        details = get_stock_detail_batch(codes)
    except Exception as e:
        logger.warning(f"Failed to batch get stock details: {e}")

    stock_list = []
    for code in codes:
        parts = code.split(".")
        exchange = parts[1] if len(parts) == 2 else ""
        pure_code = parts[0] if len(parts) == 2 else code
        detail = details.get(code)
        name = detail["stock_name"] if detail else ""
        pinyin = detail.get("pinyin", "") if detail else ""
        stock_list.append({
            "symbol": code,
            "code": pure_code,
            "name": name,
            "exchange": exchange,
            "pinyin": pinyin,
            "full_pinyin": "",
        })

    with _stocks_cache_lock:
        _stocks_cache = {"stocks": stock_list}
        _stocks_cache_ts = time.time()

    if limit > 0:
        stock_list = stock_list[:limit]

    return {
        "sector": sector,
        "count": len(stock_list),
        "stocks": stock_list,
    }


# --- 5. 合约详情 ---


@router.get("/instruments/{symbol}", dependencies=[Depends(verify_api_key)])
def instruments(symbol: str):
    try:
        detail = get_stock_detail(symbol)
        if not detail:
            raise HTTPException(status_code=404, detail=f"Instrument {symbol} not found")
        parts = symbol.split(".")
        return {
            "symbol": symbol,
            "instrument_id": parts[0] if len(parts) == 2 else symbol,
            "instrument_name": detail["stock_name"],
            "exchange_id": parts[1] if len(parts) == 2 else "",
            "industry": detail.get("industry", ""),
            "list_date": detail.get("list_date", ""),
        }
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Failed to get instrument detail for {symbol}: {e}")
        raise HTTPException(status_code=503, detail=f"Data source unavailable: {type(e).__name__}: {e}")


# --- 6. 数据同步触发 ---


@router.get("/sync/status", dependencies=[Depends(verify_api_key)])
def sync_status():
    return {"running": is_sync_running()}


@router.post("/sync/trigger", dependencies=[Depends(verify_api_key)])
def sync_trigger():
    if is_sync_running():
        raise HTTPException(status_code=409, detail="Download task is already running")
    started = trigger_download()
    if not started:
        raise HTTPException(status_code=409, detail="Download task is already running")
    return {"status": "started", "message": "Download task triggered"}


# --- 7. WebSocket 实时行情 ---


class ConnectionManager:
    def __init__(self):
        self.active: dict[WebSocket, set[str]] = {}

    async def connect(self, ws: WebSocket):
        await ws.accept()
        self.active[ws] = set()

    def disconnect(self, ws: WebSocket):
        self.active.pop(ws, None)

    def subscribe(self, ws: WebSocket, symbols: list[str]):
        if ws in self.active:
            self.active[ws].update(symbols)

    def unsubscribe(self, ws: WebSocket, symbols: list[str]):
        if ws in self.active:
            for s in symbols:
                self.active[ws].discard(s)


manager = ConnectionManager()


async def push_quotes():
    """后台任务：每 3 秒推送订阅股票的实时行情"""
    while True:
        try:
            await asyncio.sleep(3)
            if not manager.active:
                continue
            all_symbols = set()
            for symbols in manager.active.values():
                all_symbols.update(symbols)
            if not all_symbols:
                continue
            try:
                tick_data = get_full_tick(list(all_symbols))
            except RuntimeError as e:
                logger.warning(f"[ws] xtdata unavailable for quote push: {e}")
                continue
            except Exception as e:
                logger.warning(f"[ws] Failed to get tick data: {e}")
                continue
            for ws, subscribed in list(manager.active.items()):
                if not subscribed:
                    continue
                quotes = {}
                for sym in subscribed:
                    if sym in tick_data:
                        t = tick_data[sym]
                        ts = t.get("time", 0)
                        dt_str = ""
                        if ts:
                            dt = datetime.fromtimestamp(ts / 1000, tz=_CST)
                            dt_str = dt.strftime("%Y%m%d%H%M%S")
                        quotes[sym] = {
                            "last_price": t.get("lastPrice", 0),
                            "open": t.get("open", 0),
                            "high": t.get("high", 0),
                            "low": t.get("low", 0),
                            "volume": int(t.get("volume", 0)),
                            "amount": t.get("amount", 0),
                            "datetime": dt_str,
                        }
                try:
                    await ws.send_json({"type": "quote", "data": quotes})
                except Exception as e:
                    logger.warning(f"[ws] Failed to send to client, disconnecting: {e}")
                    manager.disconnect(ws)
        except asyncio.CancelledError:
            logger.info("[ws] push_quotes task cancelled")
            raise
        except Exception as e:
            logger.error(f"[ws] Unexpected error in push_quotes, restarting loop: {e}")
            await asyncio.sleep(5)


@router.on_event("startup")
async def startup():
    asyncio.create_task(push_quotes())


@router.websocket("/ws/quote")
async def ws_quote(websocket: WebSocket):
    if API_KEY:
        key = websocket.query_params.get("apikey", "")
        if key != API_KEY:
            await websocket.close(code=4001, reason="Invalid API Key")
            return

    await manager.connect(websocket)
    try:
        while True:
            data = await websocket.receive_json()
            action = data.get("action", "")

            if action == "subscribe":
                symbols = data.get("symbols", [])
                manager.subscribe(websocket, symbols)
                await websocket.send_json({"type": "subscribed", "symbols": symbols})

            elif action == "unsubscribe":
                symbols = data.get("symbols", [])
                manager.unsubscribe(websocket, symbols)
                await websocket.send_json({"type": "unsubscribed", "symbols": symbols})

            elif action == "ping":
                await websocket.send_json({"type": "pong"})

    except WebSocketDisconnect:
        manager.disconnect(websocket)

import asyncio
import json
import logging

from fastapi import APIRouter, Query, WebSocket, WebSocketDisconnect
from core.auth import verify_ws_api_key
from core.gateway import gateway

router = APIRouter(prefix="/api/v1", tags=["websocket"])
logger = logging.getLogger("stock_trade.ws")


class ConnectionManager:
    def __init__(self):
        self.active: list[WebSocket] = []
        self._lock = asyncio.Lock()

    async def connect(self, ws: WebSocket):
        await ws.accept()
        async with self._lock:
            self.active.append(ws)

    async def disconnect(self, ws: WebSocket):
        async with self._lock:
            if ws in self.active:
                self.active.remove(ws)

    async def broadcast(self, event: dict):
        if not self.active:
            return
        data = json.dumps(event, ensure_ascii=False)
        async with self._lock:
            targets = self.active[:]
        for ws in targets:
            try:
                await ws.send_text(data)
            except Exception as e:
                logger.warning("WebSocket推送失败，移除连接: %s", e)
                await self.disconnect(ws)


manager = ConnectionManager()


@router.websocket("/ws/trade")
async def ws_trade(ws: WebSocket, apikey: str = Query(default="")):
    if not verify_ws_api_key(apikey):
        await ws.close(code=4001, reason="Unauthorized")
        return

    await manager.connect(ws)
    try:
        # 连接后发送当前状态
        await ws.send_text(json.dumps({
            "type": "connected" if gateway.connected else "disconnected",
            "account_id": gateway.account_id,
        }, ensure_ascii=False))

        while True:
            data = await ws.receive_text()
            try:
                msg = json.loads(data)
                if msg.get("action") == "ping":
                    await ws.send_text(json.dumps({"type": "pong"}))
            except (json.JSONDecodeError, KeyError):
                pass
    except WebSocketDisconnect:
        pass
    finally:
        await manager.disconnect(ws)

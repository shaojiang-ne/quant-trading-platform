from fastapi import WebSocket
from typing import Dict, Set
import json


class ConnectionManager:
    """WebSocket 连接管理器"""

    def __init__(self):
        # user_id -> set of WebSocket connections
        self.active_connections: Dict[str, Set[WebSocket]] = {}

    async def connect(self, websocket: WebSocket, user_id: str):
        await websocket.accept()
        if user_id not in self.active_connections:
            self.active_connections[user_id] = set()
        self.active_connections[user_id].add(websocket)

    def disconnect(self, websocket: WebSocket, user_id: str):
        if user_id in self.active_connections:
            self.active_connections[user_id].discard(websocket)
            if not self.active_connections[user_id]:
                del self.active_connections[user_id]

    async def send_to_user(self, user_id: str, message: dict):
        """向指定用户的所有连接推送消息"""
        connections = self.active_connections.get(user_id)
        if not connections:
            return
        data = json.dumps(message, ensure_ascii=False)
        disconnected = set()
        for ws in list(connections):
            try:
                await ws.send_text(data)
            except Exception:
                disconnected.add(ws)
        for ws in disconnected:
            connections.discard(ws)
            if not connections:
                self.active_connections.pop(user_id, None)

    async def broadcast(self, message: dict):
        """向所有连接广播消息"""
        data = json.dumps(message, ensure_ascii=False)
        for user_id in list(self.active_connections.keys()):
            connections = self.active_connections.get(user_id)
            if not connections:
                continue
            disconnected = set()
            for ws in list(connections):
                try:
                    await ws.send_text(data)
                except Exception:
                    disconnected.add(ws)
            for ws in disconnected:
                connections.discard(ws)
                if not connections:
                    self.active_connections.pop(user_id, None)


ws_manager = ConnectionManager()

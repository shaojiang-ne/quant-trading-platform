import asyncio
import json
import logging
from concurrent.futures import ThreadPoolExecutor

from fastapi import WebSocket
from jose import jwt, JWTError

from app.config import settings
from app.services.market_service import market_service
from app.ws.manager import ws_manager

logger = logging.getLogger(__name__)

# 用户订阅记录: user_id -> {channel: set(symbols)}
_subscriptions: dict[str, dict[str, set]] = {}

# 行情推送任务
_tick_task: asyncio.Task | None = None

# 线程池用于同步 HTTP 调用
_executor = ThreadPoolExecutor(max_workers=4)


async def websocket_endpoint(websocket: WebSocket, token: str):
    """WebSocket 主入口，通过token认证"""
    try:
        payload = jwt.decode(token, settings.JWT_SECRET_KEY, algorithms=[settings.JWT_ALGORITHM])
        user_id = payload.get("sub")
        if not user_id:
            await websocket.close(code=4001, reason="无效token")
            return
    except JWTError:
        await websocket.close(code=4001, reason="无效token")
        return

    await handle_websocket(websocket, user_id)


async def _tick_poll_loop():
    """轮询 stock_data HTTP API 获取 tick 数据并推送给订阅用户"""
    while True:
        try:
            # 收集所有需要轮询的 symbol
            symbols: set[str] = set()
            for user_subs in _subscriptions.values():
                tick_subs = user_subs.get("tick", set())
                symbols.update(tick_subs)

            if not symbols:
                await asyncio.sleep(1)
                continue

            # 并发获取所有 symbol 的 tick 数据
            loop = asyncio.get_event_loop()
            tasks = []
            for symbol in symbols:
                tasks.append(
                    loop.run_in_executor(_executor, market_service.get_full_tick, symbol)
                )

            results = await asyncio.gather(*tasks, return_exceptions=True)

            # 推送给订阅用户
            for symbol, result in zip(symbols, results):
                if isinstance(result, Exception) or result is None:
                    continue
                # 转换字段名为前端期望的下划线格式
                tick_data = _convert_tick_fields(symbol, result)
                # 找到订阅了该 symbol 的用户
                for user_id, user_subs in _subscriptions.items():
                    if symbol in user_subs.get("tick", set()):
                        await ws_manager.send_to_user(user_id, {
                            "type": "tick",
                            "data": tick_data,
                        })

        except Exception as e:
            logger.error(f"Tick poll error: {e}")

        await asyncio.sleep(5)  # 每5秒轮询一次（原3s过于频繁，stock_data模式下每symbol一次HTTP）


async def handle_websocket(websocket: WebSocket, user_id: str):
    """处理 WebSocket 连接"""
    await ws_manager.connect(websocket, user_id)
    _subscriptions.setdefault(user_id, {})

    # 启动轮询任务
    global _tick_task
    if _tick_task is None or _tick_task.done():
        _tick_task = asyncio.create_task(_tick_poll_loop())

    try:
        while True:
            data = await websocket.receive_text()
            try:
                msg = json.loads(data)
            except json.JSONDecodeError:
                continue

            await _handle_message(websocket, user_id, msg)

    except Exception:
        pass
    finally:
        ws_manager.disconnect(websocket, user_id)
        _subscriptions.pop(user_id, None)


async def _handle_message(websocket: WebSocket, user_id: str, msg: dict):
    """处理客户端消息"""
    msg_type = msg.get("type", "")

    if msg_type == "subscribe":
        channel = msg.get("channel", "")
        symbols = msg.get("symbols", [])

        if channel == "tick":
            # 记录订阅
            if channel not in _subscriptions[user_id]:
                _subscriptions[user_id][channel] = set()
            _subscriptions[user_id][channel].update(symbols)

            await websocket.send_json({
                "type": "subscribed",
                "channel": channel,
                "symbols": list(symbols),
            })

        elif channel == "trade":
            # 交易频道订阅
            if channel not in _subscriptions[user_id]:
                _subscriptions[user_id][channel] = set()
            _subscriptions[user_id][channel].update(symbols)

            await websocket.send_json({
                "type": "subscribed",
                "channel": channel,
                "symbols": list(symbols),
            })

    elif msg_type == "unsubscribe":
        channel = msg.get("channel", "")
        symbols = msg.get("symbols", [])

        if channel in _subscriptions.get(user_id, {}):
            _subscriptions[user_id][channel] -= set(symbols)
            if not _subscriptions[user_id][channel]:
                del _subscriptions[user_id][channel]

        await websocket.send_json({
            "type": "unsubscribed",
            "channel": channel,
            "symbols": list(symbols),
        })

    elif msg_type == "ping":
        await websocket.send_json({"type": "pong"})


def _convert_tick_fields(symbol: str, data: dict) -> dict:
    """将 stock_data 的驼峰字段转为前端期望的下划线格式"""
    bid_prices = data.get("bidPrice", []) or []
    ask_prices = data.get("askPrice", []) or []
    bid_volumes = data.get("bidVol", []) or []
    ask_volumes = data.get("askVol", []) or []
    last_price = data.get("lastPrice", 0)
    pre_close = data.get("lastClose", 0)
    return {
        "symbol": symbol,
        "name": data.get("name", ""),
        "last_price": last_price,
        "open_price": data.get("open", 0),
        "high_price": data.get("high", 0),
        "low_price": data.get("low", 0),
        "pre_close": pre_close,
        "volume": data.get("volume", 0),
        "amount": data.get("amount", 0),
        "bid_price_1": bid_prices[0] if len(bid_prices) > 0 else 0,
        "bid_volume_1": bid_volumes[0] if len(bid_volumes) > 0 else 0,
        "ask_price_1": ask_prices[0] if len(ask_prices) > 0 else 0,
        "ask_volume_1": ask_volumes[0] if len(ask_volumes) > 0 else 0,
        "change": last_price - pre_close,
        "datetime": data.get("timetag", ""),
    }

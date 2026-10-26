"""
vnpy 事件处理器

将 vnpy 事件引擎的事件桥接到 WebSocket，推送给前端。
支持行情、委托、成交、持仓、账户、日志事件，
以及 CTA 策略运行时的策略日志/交易/账户更新事件。
"""

import asyncio
import logging
from typing import Optional

from app.ws.manager import ws_manager

try:
    from vnpy.trader.constant import Direction
    from vnpy.trader.event import (
        EVENT_TICK, EVENT_ORDER, EVENT_TRADE,
        EVENT_POSITION, EVENT_ACCOUNT, EVENT_LOG,
    )
    VNPY_AVAILABLE = True
except ImportError:
    VNPY_AVAILABLE = False

    class _StubEnum:
        def __getattr__(self, name):
            return name
    Direction = _StubEnum()
    EVENT_TICK = "eTick"
    EVENT_ORDER = "eOrder"
    EVENT_TRADE = "eTrade"
    EVENT_POSITION = "ePosition"
    EVENT_ACCOUNT = "eAccount"
    EVENT_LOG = "eLog"

logger = logging.getLogger(__name__)


class VnpyEventHandler:
    """vnpy 事件 → WebSocket 推送桥接"""

    def __init__(self):
        self._registered = False

    def register(self):
        """注册vnpy事件监听"""
        if self._registered:
            return

        try:
            from vnpy.event import EventEngine
            from app.core.engine import engine_manager

            engine = engine_manager.get_engine()
            if not engine:
                return

            event_engine = engine_manager._event_engine
            event_engine.register(EVENT_TICK, self._on_tick)
            event_engine.register(EVENT_ORDER, self._on_order)
            event_engine.register(EVENT_TRADE, self._on_trade)
            event_engine.register(EVENT_POSITION, self._on_position)
            event_engine.register(EVENT_ACCOUNT, self._on_account)
            event_engine.register(EVENT_LOG, self._on_log)

            self._registered = True
            logger.info("vnpy事件处理器已注册")
        except ImportError:
            logger.debug("vnpy不可用，事件处理器未注册")

    def register_on_engine(self, event_engine):
        """直接注册到指定的 EventEngine（用于 vnpy_strategy_runner）"""
        if self._registered:
            return

        if not VNPY_AVAILABLE:
            return

        event_engine.register(EVENT_TICK, self._on_tick)
        event_engine.register(EVENT_ORDER, self._on_order)
        event_engine.register(EVENT_TRADE, self._on_trade)
        event_engine.register(EVENT_POSITION, self._on_position)
        event_engine.register(EVENT_ACCOUNT, self._on_account)
        event_engine.register(EVENT_LOG, self._on_log)

        self._registered = True
        logger.info("vnpy事件处理器已注册（直接模式）")

    def _on_tick(self, event):
        """行情推送"""
        tick = event.data
        data = {
            "type": "tick",
            "data": {
                "symbol": tick.vt_symbol,
                "last_price": tick.last_price,
                "volume": tick.volume,
                "open_price": tick.open_price,
                "high_price": tick.high_price,
                "low_price": tick.low_price,
                "pre_close": tick.pre_close,
                "bid_price_1": tick.bid_price_1,
                "bid_volume_1": tick.bid_volume_1,
                "ask_price_1": tick.ask_price_1,
                "ask_volume_1": tick.ask_volume_1,
                "datetime": str(tick.datetime),
            }
        }
        asyncio.create_task(ws_manager.broadcast(data))

    def _on_order(self, event):
        """委托状态更新"""
        order = event.data
        side = "buy" if order.direction == Direction.LONG else "sell"
        status_map = {
            "SUBMITTING": "pending", "NOTTRADED": "pending",
            "PARTTRADED": "partial", "ALLTRADED": "filled",
            "CANCELLED": "cancelled", "REJECTED": "rejected",
        }
        data = {
            "type": "order",
            "data": {
                "orderid": order.vt_orderid,
                "symbol": order.vt_symbol,
                "side": side,
                "price": order.price,
                "volume": order.volume,
                "traded": order.traded,
                "status": status_map.get(order.status.value, "pending"),
                "datetime": str(order.datetime),
            }
        }
        asyncio.create_task(ws_manager.broadcast(data))

    def _on_trade(self, event):
        """成交回报"""
        trade = event.data
        side = "buy" if trade.direction == Direction.LONG else "sell"
        data = {
            "type": "trade",
            "data": {
                "tradeid": trade.vt_tradeid,
                "orderid": trade.vt_orderid,
                "symbol": trade.vt_symbol,
                "side": side,
                "price": trade.price,
                "volume": trade.volume,
                "datetime": str(trade.datetime),
            }
        }
        asyncio.create_task(ws_manager.broadcast(data))

    def _on_position(self, event):
        """持仓更新"""
        position = event.data
        data = {
            "type": "position",
            "data": {
                "symbol": position.vt_symbol,
                "direction": position.direction.value,
                "volume": position.volume,
                "frozen": position.frozen,
                "price": position.price,
                "pnl": position.pnl,
            }
        }
        asyncio.create_task(ws_manager.broadcast(data))

    def _on_account(self, event):
        """账户资金更新"""
        account = event.data
        data = {
            "type": "account",
            "data": {
                "gateway_name": account.gateway_name,
                "balance": account.balance,
                "frozen": account.frozen,
                "available": account.available,
            }
        }
        asyncio.create_task(ws_manager.broadcast(data))

    def _on_log(self, event):
        """日志"""
        log = event.data
        data = {
            "type": "log",
            "data": {
                "msg": log.msg,
                "gateway_name": log.gateway_name,
                "time": str(log.time),
            }
        }
        asyncio.create_task(ws_manager.broadcast(data))


# 全局单例
event_handler = VnpyEventHandler()
import asyncio
import logging
from xtquant.xttrader import XtQuantTraderCallback
from xtquant import xtconstant

logger = logging.getLogger("stock_trade.callback")

STATUS_MAP = {
    xtconstant.ORDER_UNREPORTED: "pending",
    xtconstant.ORDER_WAIT_REPORTING: "pending",
    xtconstant.ORDER_REPORTED: "pending",
    xtconstant.ORDER_REPORTED_CANCEL: "pending",
    xtconstant.ORDER_PARTSUCC_CANCEL: "partial",
    xtconstant.ORDER_PART_CANCEL: "cancelled",
    xtconstant.ORDER_CANCELED: "cancelled",
    xtconstant.ORDER_PART_SUCC: "partial",
    xtconstant.ORDER_SUCCEEDED: "filled",
    xtconstant.ORDER_JUNK: "rejected",
    xtconstant.ORDER_UNKNOWN: "pending",
}

SIDE_MAP = {
    xtconstant.STOCK_BUY: "buy",
    xtconstant.STOCK_SELL: "sell",
}

SIDE_REVERSE = {"buy": xtconstant.STOCK_BUY, "sell": xtconstant.STOCK_SELL}
PRICE_TYPE_MAP = {"limit": xtconstant.FIX_PRICE, "market": xtconstant.LATEST_PRICE}


class TradeCallback(XtQuantTraderCallback):
    def __init__(self, ws_manager=None, loop=None, gateway=None):
        self.ws_manager = ws_manager
        self.loop = loop
        self.gateway = gateway

    def _emit(self, event: dict):
        if self.ws_manager and self.loop:
            asyncio.run_coroutine_threadsafe(
                self.ws_manager.broadcast(event), self.loop
            )

    def on_disconnected(self):
        logger.warning("xtquant on_disconnected 回调触发")
        if self.gateway:
            self.gateway.on_disconnected()
        self._emit({"type": "disconnected"})

    def on_stock_order(self, order):
        status = STATUS_MAP.get(order.order_status, "pending")
        self._emit({
            "type": "order_update",
            "order_id": str(order.order_id),
            "symbol": order.stock_code,
            "status": status,
            "filled_quantity": order.traded_volume,
            "filled_price": order.traded_price,
            "time": order.order_time,
        })

    def on_stock_trade(self, trade):
        side = SIDE_MAP.get(trade.order_type, "buy")
        self._emit({
            "type": "trade",
            "order_id": str(trade.order_id),
            "symbol": trade.stock_code,
            "side": side,
            "price": trade.traded_price,
            "quantity": trade.traded_volume,
            "time": trade.traded_time,
        })

    def on_order_error(self, order_error):
        self._emit({
            "type": "order_error",
            "order_id": str(order_error.order_id),
            "message": order_error.error_msg,
        })

    def on_cancel_error(self, cancel_error):
        self._emit({
            "type": "order_error",
            "order_id": str(cancel_error.order_id),
            "message": cancel_error.error_msg,
        })
"""
vnpy 实盘交易网关封装

基于 vnpy MainEngine + XtpGateway/CtpGateway 的实盘交易封装，
替代原有直接使用 xtquant SDK 的方式。
"""

import logging
from collections import defaultdict
from datetime import datetime
from typing import Optional

from vnpy.event import EventEngine
from vnpy.trader.constant import Direction, Exchange, Offset, Status, OrderType
from vnpy.trader.engine import MainEngine
from vnpy.trader.event import (
    EVENT_ORDER, EVENT_TRADE, EVENT_POSITION, EVENT_ACCOUNT,
    EVENT_TICK, EVENT_CONTRACT, EVENT_LOG,
)
from vnpy.trader.gateway import BaseGateway
from vnpy.trader.object import (
    AccountData, ContractData, OrderData, OrderRequest,
    PositionData, SubscribeRequest, TradeData, TickData,
    CancelRequest,
)

logger = logging.getLogger(__name__)


class VnpyLiveGateway:
    """基于 vnpy XTP/CTP 网关的实盘交易封装"""

    # 网关名称 → 类名映射
    GATEWAY_MAP = {
        "xtp": "XTP",
        "ctp": "CTP",
    }

    def __init__(self) -> None:
        self._event_engine: Optional[EventEngine] = None
        self._main_engine: Optional[MainEngine] = None
        self._active_gateway: Optional[BaseGateway] = None
        self._gateway_name: str = ""

        # 缓存
        self._accounts: dict[str, AccountData] = {}
        self._positions: dict[str, PositionData] = {}
        self._orders: dict[str, OrderData] = {}
        self._trades: dict[str, TradeData] = {}
        self._ticks: dict[str, TickData] = {}
        self._contracts: dict[str, ContractData] = {}

        # 回调
        self._on_trade_callback = None
        self._on_order_callback = None
        self._on_tick_callback = None

    def connect(self, gateway_name: str, setting: dict) -> bool:
        """连接实盘网关

        Args:
            gateway_name: "xtp" 或 "ctp"
            setting: 网关连接参数
                XTP: {td_address, md_address, appid, auth, userid, password, software_key }
                CTP: {userid, password, brokerid, td_address, md_address, appid, auth_code }
        """
        gw_type = self.GATEWAY_MAP.get(gateway_name.lower())
        if not gw_type:
            logger.error(f"不支持的网关: {gateway_name}")
            return False

        try:
            self._event_engine = EventEngine()
            self._main_engine = MainEngine(self._event_engine)

            # 注册网关
            if gw_type == "XTP":
                from vnpy_xtp import XtpGateway
                self._main_engine.add_gateway(XtpGateway)
            elif gw_type == "CTP":
                from vnpy_ctp import CtpGateway
                self._main_engine.add_gateway(CtpGateway)

            self._gateway_name = gw_type

            # 注册事件处理器
            self._register_event_handlers()

            # 连接网关
            self._main_engine.connect(setting, gw_type)
            logger.info(f"实盘网关连接中: {gw_type}")

            return True

        except Exception as e:
            logger.error(f"实盘网关连接失败: {e}")
            return False

    def disconnect(self) -> None:
        """断开连接"""
        if self._main_engine:
            self._main_engine.close()
            self._main_engine = None
        if self._event_engine:
            self._event_engine.stop()
            self._event_engine = None
        self._active_gateway = None
        logger.info("实盘网关已断开")

    def subscribe(self, vt_symbols: list[str]) -> None:
        """订阅行情"""
        if not self._main_engine:
            return

        for vt_symbol in vt_symbols:
            parts = vt_symbol.split(".")
            symbol = parts[0]
            exchange_str = parts[1] if len(parts) > 1 else "SSE"
            exchange = Exchange(exchange_str)

            req = SubscribeRequest(symbol=symbol, exchange=exchange)
            self._main_engine.subscribe(req, self._gateway_name)

    def place_order(
        self, vt_symbol: str, direction: str, price: float,
        volume: float, order_type: str = "limit",
    ) -> Optional[str]:
        """下单

        Args:
            vt_symbol: "600519.SSE"
            direction: "buy" / "sell"
            price: 价格
            volume: 数量
            order_type: "limit" / "market"
        """
        if not self._main_engine:
            logger.error("未连接实盘网关")
            return None

        parts = vt_symbol.split(".")
        symbol = parts[0]
        exchange_str = parts[1] if len(parts) > 1 else "SSE"
        exchange = Exchange(exchange_str)

        if direction == "buy":
            vnpy_direction = Direction.LONG
            vnpy_offset = Offset.OPEN
        else:
            vnpy_direction = Direction.SHORT
            vnpy_offset = Offset.CLOSE

        if order_type == "market":
            vnpy_order_type = OrderType.MARKET
        else:
            vnpy_order_type = OrderType.LIMIT

        req = OrderRequest(
            symbol=symbol,
            exchange=exchange,
            direction=vnpy_direction,
            type=vnpy_order_type,
            volume=volume,
            price=price,
            offset=vnpy_offset,
        )

        vt_orderid = self._main_engine.send_order(req, self._gateway_name)
        if vt_orderid:
            logger.info(f"下单成功: {direction} {vt_symbol} {volume}@{price}, orderid={vt_orderid}")
        else:
            logger.error(f"下单失败: {direction} {vt_symbol} {volume}@{price}")

        return vt_orderid

    def cancel_order(self, vt_orderid: str) -> bool:
        """撤单"""
        if not self._main_engine:
            return False

        order = self._orders.get(vt_orderid)
        if not order:
            logger.warning(f"委托不存在: {vt_orderid}")
            return False

        req = CancelRequest(
            orderid=order.orderid,
            symbol=order.symbol,
            exchange=order.exchange,
        )
        self._main_engine.cancel_order(req, self._gateway_name)
        return True

    def query_asset(self) -> dict:
        """查询账户资产"""
        if not self._accounts:
            return {}

        # 取第一个账户
        account = next(iter(self._accounts.values()))

        # 从持仓计算市值
        market_value = 0.0
        for pos in self._positions.values():
            if pos.volume > 0:
                tick = self._ticks.get(pos.vt_symbol)
                price = tick.last_price if tick and tick.last_price > 0 else pos.price
                market_value += price * pos.volume

        return {
            "total_assets": round(account.balance, 2),
            "cash": round(account.balance - account.frozen, 2),
            "frozen_cash": round(account.frozen, 2),
            "market_value": round(market_value, 2),
            "available_cash": round(account.available, 2),
        }

    def query_positions(self) -> list[dict]:
        """查询持仓"""
        result = []
        for vt_positionid, pos in self._positions.items():
            if pos.volume <= 0:
                continue

            tick = self._ticks.get(pos.vt_symbol)
            current_price = tick.last_price if tick else pos.price

            market_value = current_price * pos.volume
            cost = pos.price * pos.volume
            pnl = market_value - cost
            pnl_pct = (pnl / cost * 100) if cost > 0 else 0

            result.append({
                "symbol": pos.symbol,
                "name": "",
                "volume": int(pos.volume),
                "available_volume": int(pos.volume - pos.frozen),
                "cost_price": round(pos.price, 2),
                "current_price": round(current_price, 2),
                "market_value": round(market_value, 2),
                "pnl": round(pnl, 2),
                "pnl_pct": round(pnl_pct, 2),
            })
        return result

    def query_orders(self) -> list[dict]:
        """查询委托"""
        result = []
        for order in self._orders.values():
            side = "buy" if order.direction == Direction.LONG else "sell"
            status_map = {
                Status.SUBMITTING: "pending",
                Status.NOTTRADED: "pending",
                Status.PARTTRADED: "partial",
                Status.ALLTRADED: "filled",
                Status.CANCELLED: "cancelled",
                Status.REJECTED: "rejected",
            }
            result.append({
                "order_id": order.vt_orderid,
                "symbol": order.symbol,
                "side": side,
                "price": round(order.price, 2),
                "quantity": int(order.volume),
                "filled_quantity": int(order.traded),
                "status": status_map.get(order.status, "unknown"),
                "time": order.datetime.strftime("%H:%M:%S") if order.datetime else "",
            })
        return result

    def query_trades(self) -> list[dict]:
        """查询成交"""
        result = []
        for trade in self._trades.values():
            side = "buy" if trade.direction == Direction.LONG else "sell"
            result.append({
                "trade_id": trade.vt_tradeid,
                "symbol": trade.symbol,
                "side": side,
                "price": round(trade.price, 2),
                "quantity": int(trade.volume),
                "time": trade.datetime.strftime("%H:%M:%S") if trade.datetime else "",
            })
        return result

    # ── 事件处理 ──────────────────────────────────────────────────────────

    def _register_event_handlers(self) -> None:
        """注册 vnpy 事件处理器"""
        if not self._event_engine:
            return

        self._event_engine.register(EVENT_TICK, self._on_tick)
        self._event_engine.register(EVENT_ORDER, self._on_order)
        self._event_engine.register(EVENT_TRADE, self._on_trade)
        self._event_engine.register(EVENT_POSITION, self._on_position)
        self._event_engine.register(EVENT_ACCOUNT, self._on_account)
        self._event_engine.register(EVENT_CONTRACT, self._on_contract)
        self._event_engine.register(EVENT_LOG, self._on_log)

    def _on_tick(self, event) -> None:
        tick = event.data
        if isinstance(tick, TickData):
            self._ticks[tick.vt_symbol] = tick
            if self._on_tick_callback:
                self._on_tick_callback(tick)

    def _on_order(self, event) -> None:
        order = event.data
        if isinstance(order, OrderData):
            self._orders[order.vt_orderid] = order
            if self._on_order_callback:
                self._on_order_callback(order)

    def _on_trade(self, event) -> None:
        trade = event.data
        if isinstance(trade, TradeData):
            self._trades[trade.vt_tradeid] = trade
            if self._on_trade_callback:
                self._on_trade_callback(trade)

    def _on_position(self, event) -> None:
        position = event.data
        if isinstance(position, PositionData):
            self._positions[position.vt_positionid] = position

    def _on_account(self, event) -> None:
        account = event.data
        if isinstance(account, AccountData):
            self._accounts[account.accountid] = account

    def _on_contract(self, event) -> None:
        contract = event.data
        if isinstance(contract, ContractData):
            self._contracts[contract.vt_symbol] = contract

    def _on_log(self, event) -> None:
        log = event.data
        logger.info(f"[VNPY_LIVE] {log.msg}")

    # ── 回调注册 ──────────────────────────────────────────────────────────

    def set_trade_callback(self, callback) -> None:
        self._on_trade_callback = callback

    def set_ordercallback(self, callback) -> None:
        self._on_order_callback = callback

    def set_tick_callback(self, callback) -> None:
        self._on_tick_callback = callback


# 全局单例
vnpy_live_gateway = VnpyLiveGateway()

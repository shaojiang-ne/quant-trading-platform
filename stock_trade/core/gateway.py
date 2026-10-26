import asyncio
import logging
import os
import threading
import time
from functools import partial
from pathlib import Path
from xtquant.xttype import StockAccount
from xtquant import xtconstant
from core.callback import TradeCallback, STATUS_MAP, SIDE_MAP, SIDE_REVERSE, PRICE_TYPE_MAP

logger = logging.getLogger("stock_trade.gateway")

# 交易审计日志 - 独立文件，不随普通日志轮转
_audit_logger = logging.getLogger("stock_trade.audit")
_audit_logger.setLevel(logging.INFO)
if not _audit_logger.handlers:
    _audit_dir = Path(__file__).resolve().parent.parent / "logs"
    _audit_dir.mkdir(exist_ok=True)
    _audit_handler = logging.FileHandler(
        _audit_dir / "trade_audit.log", encoding="utf-8"
    )
    _audit_handler.setFormatter(logging.Formatter(
        "%(asctime)s|%(message)s"
    ))
    _audit_logger.addHandler(_audit_handler)

CONNECT_ERROR_CODES = {
    0: "成功",
    -1: "连接失败(可能QMT客户端未启动或路径错误)",
    -2: "连接超时",
}

RECONNECT_INTERVAL = 5


class XtQuantGateway:
    _instance = None

    def __new__(cls, *args, **kwargs):
        if cls._instance is None:
            cls._instance = super().__new__(cls)
            cls._instance._initialized = False
        return cls._instance

    def __init__(self, ws_manager=None, loop=None):
        if self._initialized:
            return
        self._initialized = True
        self.trader = None
        self.callback = None
        self.connected = False
        self.account: StockAccount | None = None
        self.account_id: str | None = None
        self.ws_manager = ws_manager
        self.loop = loop
        self._last_connect_result = None
        self._last_connect_time = None
        self._last_connect_path = None
        self._connect_lock = threading.Lock()
        self._trader_thread = None
        self._stop_event = threading.Event()
        self._reconnecting = False

    def _get_loop(self):
        if self.loop is None:
            self.loop = asyncio.get_event_loop()
        return self.loop

    def _auto_register_account(self):
        """连接成功后自动发现并注册账户"""
        try:
            account_infos = self.trader.query_account_infos()
            if account_infos:
                info = account_infos[0]
                account_id = info.m_strAccountID if hasattr(info, 'm_strAccountID') else str(info)
                if account_id:
                    self.account = StockAccount(account_id)
                    self.account_id = account_id
                    self.trader.subscribe(self.account)
                    logger.info("自动注册账户: %s", account_id)
                    return
        except Exception as e:
            logger.warning("query_account_infos失败: %s", e)

        try:
            account_status = self.trader.query_account_status()
            if account_status:
                s = account_status[0]
                account_id = s.m_strAccountID if hasattr(s, 'm_strAccountID') else str(s)
                if account_id:
                    self.account = StockAccount(account_id)
                    self.account_id = account_id
                    self.trader.subscribe(self.account)
                    logger.info("从account_status注册账户: %s", account_id)
        except Exception as e:
            logger.warning("query_account_status失败: %s", e)

    def _run_trader(self, path, session_id):
        """在独立线程中运行 trader

        关键: 不调用trader.stop()来断开连接
        - stop()会向QMT发送断开信号，QMT端需要~10秒清理session
        - 清理期间新连接会被拒绝(connect返回-1)
        - 不调用stop()直接放弃旧trader，1-2秒内即可重连
        """
        try:
            from xtquant.xttrader import XtQuantTrader

            logger.info("trader线程启动, path=%s, session_id=%s", path, session_id)

            self.callback = TradeCallback(self.ws_manager, self._get_loop(), self)
            self.trader = XtQuantTrader(path, session_id, self.callback)
            logger.info("XtQuantTrader 已创建")

            self.trader.start()
            logger.info("trader.start() 完成")

            result = self.trader.connect()
            error_desc = CONNECT_ERROR_CODES.get(result, f"未知错误码({result})")
            logger.info("connect() 返回值: %s (%s)", result, error_desc)

            self._last_connect_result = result
            self._last_connect_time = time.strftime("%Y-%m-%d %H:%M:%S")
            self._last_connect_path = path
            self.connected = result == 0

            msg = "连接成功" if self.connected else f"连接失败(错误码: {result}, {error_desc})"
            logger.info("连接结果: connected=%s, msg=%s", self.connected, msg)

            self._connect_event.set()

            if self.connected:
                self._auto_register_account()

                # 心跳维持循环
                logger.info("trader进入心跳维持循环")
                self._stop_event.clear()
                while not self._stop_event.is_set():
                    self._stop_event.wait(2)
                logger.info("trader心跳维持循环已退出")

            logger.info("trader线程正常退出")
        except Exception as e:
            logger.error("trader线程异常: %s", e, exc_info=True)
            self.connected = False
            self._last_connect_result = -999
            self._last_connect_time = time.strftime("%Y-%m-%d %H:%M:%S")
            self._last_connect_path = path
            self._connect_event.set()
        finally:
            self.connected = False
            logger.info("trader线程退出")

    def connect(self, path: str, session_id: int) -> tuple[bool, str]:
        with self._connect_lock:
            try:
                logger.info("开始连接 xtquant, path=%s, session_id=%s", path, session_id)
                self._cleanup_old_connection()

                if not os.path.isdir(path):
                    logger.error("QMT路径不存在: %s", path)
                    self._last_connect_result = -1
                    self._last_connect_time = time.strftime("%Y-%m-%d %H:%M:%S")
                    self._last_connect_path = path
                    return False, f"QMT路径不存在: {path}"

                self._connect_event = threading.Event()
                self._trader_thread = threading.Thread(
                    target=self._run_trader,
                    args=(path, session_id),
                    name="trader-heartbeat",
                    daemon=True,
                )
                self._trader_thread.start()

                self._connect_event.wait(timeout=15)

                if self.connected:
                    logger.info("连接成功, 账户: %s", self.account_id)
                    self._reconnecting = False
                    return True, "连接成功"
                else:
                    logger.info("连接失败, 错误码=%s", self._last_connect_result)
                    return False, f"连接失败(错误码: {self._last_connect_result})"
            except Exception as e:
                logger.error("连接异常: %s", e, exc_info=True)
                self.connected = False
                self._last_connect_result = -999
                self._last_connect_time = time.strftime("%Y-%m-%d %H:%M:%S")
                self._last_connect_path = path
                return False, f"连接失败: {e}"

    def _cleanup_old_connection(self):
        """清理旧 trader，不调用stop()避免QMT端session清理延迟"""
        if self.trader:
            logger.info("清理旧 trader 实例(不调用stop)")
            self.trader = None
            self.connected = False
            self.account = None
            self.account_id = None
        self._stop_event.set()
        if self._trader_thread and self._trader_thread.is_alive():
            logger.info("等待旧 trader 线程退出")
            self._trader_thread.join(timeout=5)
            if self._trader_thread.is_alive():
                logger.warning("旧 trader 线程未在5秒内退出")
        self._trader_thread = None

    def on_disconnected(self):
        """xtquant 断线回调"""
        logger.warning("xtquant 连接断开(on_disconnected回调)")
        self.connected = False
        self._start_reconnect_if_needed()

    def _start_reconnect_if_needed(self):
        """断线后自动启动重连任务"""
        if self._reconnecting:
            return
        from core.config import settings
        if settings.gateway.get_effective_qmt_path() and settings.gateway.session_id:
            self._reconnecting = True
            logger.info("断线后启动自动重连")
            try:
                loop = self._get_loop()
                asyncio.run_coroutine_threadsafe(self._async_reconnect(), loop)
            except Exception as e:
                self._reconnecting = False
                logger.error("启动自动重连失败: %s", e)

    async def _async_reconnect(self):
        """在事件循环中启动重连"""
        from core.config import settings
        import asyncio
        attempt = 0
        while not self._stop_event.is_set():
            attempt += 1
            await asyncio.sleep(RECONNECT_INTERVAL)
            if self._stop_event.is_set() or self.connected:
                if self.connected:
                    logger.info("重连: 已连接成功，停止重连")
                    self._reconnecting = False
                return
            try:
                connected, msg = await run_sync(
                    self.connect, settings.gateway.get_effective_qmt_path(), settings.gateway.session_id
                )
                if connected:
                    logger.info("重连成功(第%d次尝试): %s", attempt, msg)
                    self._reconnecting = False
                    return
                logger.warning("重连失败(第%d次): %s, %ds后重试", attempt, msg, RECONNECT_INTERVAL)
            except Exception as e:
                logger.error("重连异常(第%d次): %s, %ds后重试", attempt, e, RECONNECT_INTERVAL)

    def shutdown(self):
        """服务关闭时清理资源"""
        logger.info("服务关闭，清理资源")
        self._stop_event.set()
        self.connected = False
        self.trader = None
        self._trader_thread = None

    def _require_connected(self):
        if not self.connected or not self.trader:
            raise ConnectionError("交易网关未连接")
        if not self.account:
            raise ConnectionError("无可用账户")

    def place_order(self, symbol: str, side: str, quantity: int,
                    price: float = 0, order_type: str = "limit") -> dict:
        self._require_connected()

        order_type_const = SIDE_REVERSE.get(side, xtconstant.STOCK_BUY)
        price_type_const = PRICE_TYPE_MAP.get(order_type, xtconstant.FIX_PRICE)

        logger.info("下单: account=%s, symbol=%s, side=%s, qty=%d, price=%s, type=%s",
                     self.account_id, symbol, side, quantity, price, order_type)
        order_id = self.trader.order_stock(
            self.account, symbol, order_type_const, quantity, price_type_const, price
        )
        result = {
            "order_id": str(order_id),
            "symbol": symbol,
            "side": side,
            "quantity": quantity,
            "price": price,
            "status": "pending" if order_id > 0 else "rejected",
            "message": "委托已提交" if order_id > 0 else "委托失败",
        }
        logger.info("下单结果: %s", result)
        _audit_logger.info("ORDER|account=%s|symbol=%s|side=%s|qty=%d|price=%s|type=%s|order_id=%s|status=%s",
                           self.account_id, symbol, side, quantity, price, order_type, order_id, result["status"])
        return result

    def cancel_order(self, order_id: str) -> dict:
        self._require_connected()

        logger.info("撤单: account=%s, order_id=%s", self.account_id, order_id)
        result = self.trader.cancel_order_stock(self.account, int(order_id))
        cancel_result = {
            "order_id": order_id,
            "status": "cancelled" if result == 0 else "rejected",
            "message": "撤单成功" if result == 0 else "撤单失败",
        }
        _audit_logger.info("CANCEL|account=%s|order_id=%s|result=%d|status=%s",
                           self.account_id, order_id, result, cancel_result["status"])
        return cancel_result

    def query_asset(self) -> dict:
        self._require_connected()

        asset = self.trader.query_stock_asset(self.account)
        if asset is None:
            return {
                "account_id": self.account_id,
                "total_assets": 0, "cash": 0, "available": 0,
                "market_value": 0, "frozen": 0,
            }
        # xtquant: cash=可用资金, frozen_cash=冻结资金, total_asset=总资产
        return {
            "account_id": self.account_id,
            "total_assets": asset.total_asset,
            "cash": asset.total_asset - asset.market_value,  # 总现金 = 总资产 - 市值
            "available": asset.cash,
            "market_value": asset.market_value,
            "frozen": asset.frozen_cash,
        }

    def query_positions(self) -> dict:
        self._require_connected()

        positions = self.trader.query_stock_positions(self.account) or []
        result = []
        for p in positions:
            if p.volume == 0:
                continue
            result.append({
                "symbol": p.stock_code,
                "name": getattr(p, "instrument_name", ""),
                "quantity": p.volume,
                "available": p.can_use_volume,
                "avg_cost": p.avg_price,
                "current_price": p.last_price,
                "market_value": p.market_value,
                "daily_profit": (p.last_price - p.open_price) * p.volume if p.open_price > 0 else 0,
                "profit": (p.last_price - p.avg_price) * p.volume if p.avg_price > 0 else 0,
                "profit_rate": p.profit_rate,
            })
        return {"account_id": self.account_id, "positions": result}

    def query_orders(self) -> dict:
        self._require_connected()

        orders = self.trader.query_stock_orders(self.account) or []
        result = []
        for o in orders:
            status = STATUS_MAP.get(o.order_status, "pending")
            side = SIDE_MAP.get(o.order_type, "buy")
            is_market = o.price_type != xtconstant.FIX_PRICE
            result.append({
                "order_id": str(o.order_id),
                "symbol": o.stock_code,
                "name": getattr(o, "instrument_name", ""),
                "side": side,
                "quantity": o.order_volume,
                "price": o.price,
                "filled_quantity": o.traded_volume,
                "filled_price": o.traded_price,
                "status": status,
                "order_type": "market" if is_market else "limit",
                "create_time": o.order_time,
                "update_time": o.order_time,
            })
        return {"account_id": self.account_id, "orders": result}

    def query_trades(self) -> dict:
        self._require_connected()

        trades = self.trader.query_stock_trades(self.account) or []
        result = []
        for t in trades:
            side = SIDE_MAP.get(t.order_type, "buy")
            result.append({
                "trade_id": str(t.traded_id),
                "order_id": str(t.order_id),
                "symbol": t.stock_code,
                "side": side,
                "price": t.traded_price,
                "quantity": t.traded_volume,
                "time": t.traded_time,
            })
        return {"account_id": self.account_id, "trades": result}


gateway = XtQuantGateway()

_executor = None


def _get_executor():
    global _executor
    if _executor is None:
        from concurrent.futures import ThreadPoolExecutor
        _executor = ThreadPoolExecutor(max_workers=4, thread_name_prefix="gateway")
    return _executor


async def run_sync(func, *args):
    loop = asyncio.get_event_loop()
    return await loop.run_in_executor(_get_executor(), partial(func, *args))

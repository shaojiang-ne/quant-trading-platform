"""
交易数据同步服务 - 定期从 stock_trade 同步账户/持仓/委托/成交数据
"""

import asyncio
import logging
from typing import Optional

from app.core.live_gateway import live_gateway

logger = logging.getLogger(__name__)


class TradeSyncService:
    """交易数据同步服务"""

    def __init__(self):
        self._running = False
        self._task: Optional[asyncio.Task] = None
        self._interval = 30  # 秒
        self._ws_manager = None

    def set_ws_manager(self, ws_manager):
        """设置 WebSocket 管理器，用于通知前端刷新"""
        self._ws_manager = ws_manager

    async def start(self):
        """启动同步服务"""
        if self._running:
            return
        self._running = True
        self._task = asyncio.create_task(self._sync_loop())
        logger.info("交易数据同步服务已启动")

    async def stop(self):
        """停止同步服务"""
        self._running = False
        if self._task:
            self._task.cancel()
            try:
                await self._task
            except asyncio.CancelledError:
                pass
            self._task = None
        logger.info("交易数据同步服务已停止")

    async def _sync_loop(self):
        """同步循环"""
        while self._running:
            try:
                if live_gateway.is_connected:
                    await self.sync_all()
            except Exception as e:
                logger.error(f"同步数据异常: {e}")
            await asyncio.sleep(self._interval)

    async def sync_all(self):
        """执行一次数据同步"""
        try:
            account = await live_gateway.get_account()
            positions = await live_gateway.get_positions()
            orders = await live_gateway.get_orders()
            trades = await live_gateway.get_trades()

            # 为每个持仓计算今日盈亏
            from app.services.market_service import market_service
            from app.core.data_bridge import data_bridge
            if isinstance(positions, list) and market_service.is_available():
                for pos in positions:
                    symbol = pos.get("symbol", "")
                    current_price = float(pos.get("current_price", 0))
                    quantity = int(pos.get("quantity", pos.get("volume", 0)))
                    xt_symbol = data_bridge.to_xt_symbol(symbol.split(".")[0] if "." in symbol else symbol)
                    tick = market_service.get_full_tick(xt_symbol)
                    pre_close = float(tick.get("lastClose", 0)) if tick else 0
                    if pre_close > 0 and current_price > 0:
                        pos["daily_profit"] = round((current_price - pre_close) * quantity, 2)
                    else:
                        pos["daily_profit"] = 0

            if self._ws_manager:
                await self._ws_manager.broadcast({
                    "type": "trade_sync",
                    "data": {
                        "account": account,
                        "positions": positions,
                        "orders": orders,
                        "trades": trades,
                    },
                })

            logger.debug("交易数据同步完成")
        except Exception as e:
            logger.error(f"同步数据失败: {e}")


# 全局单例
trade_sync_service = TradeSyncService()

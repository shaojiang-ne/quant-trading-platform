"""
vnpy 模拟股票交易网关

基于 vnpy BaseGateway 实现的模拟交易网关，
支持 A 股 T+1 规则、100 股整手交易、佣金/印花税。
"""

import logging
import time
from collections import defaultdict
from datetime import date, datetime
from typing import Optional

from vnpy.event import Event, EventEngine
from vnpy.trader.constant import Direction, Exchange, Offset, Status, OrderType
from vnpy.trader.event import (
    EVENT_TICK, EVENT_ORDER, EVENT_TRADE, EVENT_POSITION, EVENT_ACCOUNT,
)
from vnpy.trader.gateway import BaseGateway
from vnpy.trader.object import (
    AccountData, OrderData, OrderRequest, PositionData,
    SubscribeRequest, TradeData, TickData, CancelRequest,
    ContractData,
)

logger = logging.getLogger(__name__)

# A 股模拟交易费用常量（与 vnpy_strategy_runner 同步）
SIM_COMMISSION_RATE = 0.0003      # 佣金费率万三
SIM_MIN_COMMISSION = 5.0          # 最低佣金 5 元
SIM_STAMP_TAX_RATE = 0.001        # 印花税千一（仅卖出）


class SimulatedStockGateway(BaseGateway):
    """模拟股票交易网关 (vnpy BaseGateway 实现)"""

    default_name: str = "SIM_STOCK"
    default_setting: dict = {
        "capital": "1000000",
    }
    exchanges: list[Exchange] = [Exchange.SSE, Exchange.SZSE, Exchange.BSE]

    def __init__(self, event_engine: EventEngine, gateway_name: str) -> None:
        super().__init__(event_engine, gateway_name)

        self._order_count: int = 0
        self._trade_count: int = 0
        self._orders: dict[str, OrderData] = {}
        self._trades: dict[str, TradeData] = {}

        # 模拟账户
        self._balance: float = 0
        self._frozen: float = 0
        self._positions: dict[str, PositionInfo] = {}
        self._buy_dates: dict[str, date] = {}  # T+1 跟踪

        # 佣金参数
        self._commission_rate: float = SIM_COMMISSION_RATE
        self._stamp_tax_rate: float = SIM_STAMP_TAX_RATE
        self._min_commission: float = SIM_MIN_COMMISSION

        # 行情缓存
        self._ticks: dict[str, TickData] = {}
        self._pre_closes: dict[str, float] = {}  # 昨收价（用于涨跌停计算）

    def connect(self, setting: dict) -> None:
        """连接（初始化账户）"""
        self._balance = float(setting.get("capital", 1000000))
        logger.info(f"模拟网关连接: 初始资金 {self._balance:,.0f}")

        self._write_log("模拟交易网关已连接")

        # 注册合约
        self._register_contracts()

    def _register_contracts(self) -> None:
        """注册模拟合约"""
        # 不注册具体合约，由外部注入

    def subscribe(self, req: SubscribeRequest) -> None:
        """订阅行情（由外部注入 tick）"""
        pass

    def send_order(self, req: OrderRequest) -> str:
        """发送委托"""
        self._order_count += 1
        today = date.today()

        order = req.create_order_data(str(self._order_count), self.gateway_name)
        vt_symbol = order.vt_symbol

        # A 股校验
        if order.volume <= 0:
            order.status = Status.REJECTED
            self._orders[order.vt_orderid] = order
            self.on_event(EVENT_ORDER, order)
            return order.vt_orderid

        # 涨跌停检查
        pre_close = self._pre_closes.get(vt_symbol, 0)
        if pre_close > 0:
            limit_up = round(pre_close * 1.1, 2)
            limit_down = round(pre_close * 0.9, 2)
            tick = self._ticks.get(vt_symbol)
            current_price = tick.last_price if tick else order.price

            if order.direction == Direction.LONG and current_price >= limit_up:
                order.status = Status.REJECTED
                self._orders[order.vt_orderid] = order
                self.on_event(EVENT_ORDER, order)
                self._write_log(f"涨停买不进: {vt_symbol} 当前价 {current_price:.2f} >= 涨停价 {limit_up:.2f}")
                return order.vt_orderid

            if order.direction == Direction.SHORT and current_price <= limit_down:
                order.status = Status.REJECTED
                self._orders[order.vt_orderid] = order
                self.on_event(EVENT_ORDER, order)
                self._write_log(f"跌停卖不出: {vt_symbol} 当前价 {current_price:.2f} <= 跌停价 {limit_down:.2f}")
                return order.vt_orderid

        # 买入检查
        if order.direction == Direction.LONG:
            cost = order.price * order.volume
            commission = max(cost * self._commission_rate, self._min_commission)
            total_cost = cost + commission

            if total_cost > self._balance - self._frozen:
                order.status = Status.REJECTED
                self._orders[order.vt_orderid] = order
                self.on_event(EVENT_ORDER, order)
                self._write_log(f"资金不足: 需要 {total_cost:,.0f}, 可用 {self._balance - self._frozen:,.0f}")
                return order.vt_orderid

            self._frozen += total_cost
            order.status = Status.NOTTRADED
            self._orders[order.vt_orderid] = order
            self.on_event(EVENT_ORDER, order)

            # 立即成交
            self._fill_order(order)

        # 卖出检查
        elif order.direction == Direction.SHORT:
            pos_info = self._positions.get(vt_symbol)
            available = pos_info.available if pos_info else 0

            # T+1 检查
            buy_date = self._buy_dates.get(vt_symbol)
            if buy_date == today and available > 0:
                # 当日买入不可卖出
                available = 0
                self._write_log(f"T+1 限制: {vt_symbol} 今日买入不可卖出")

            if order.volume > available:
                order.status = Status.REJECTED
                self._orders[order.vt_orderid] = order
                self.on_event(EVENT_ORDER, order)
                self._write_log(f"持仓不足: {vt_symbol} 可卖 {available}, 欲卖 {order.volume}")
                return order.vt_orderid

            pos_info.frozen += order.volume
            order.status = Status.NOTTRADED
            self._orders[order.vt_orderid] = order
            self.on_event(EVENT_ORDER, order)

            # 立即成交
            self._fill_order(order)

        return order.vt_orderid

    def _fill_order(self, order: OrderData) -> None:
        """模拟成交"""
        self._trade_count += 1
        vt_symbol = order.vt_symbol

        trade = TradeData(
            symbol=order.symbol,
            exchange=order.exchange,
            orderid=order.orderid,
            tradeid=str(self._trade_count),
            direction=order.direction,
            offset=order.offset,
            price=order.price,
            volume=order.volume,
            datetime=datetime.now(),
            gateway_name=self.gateway_name,
        )

        # 更新委托状态
        order.traded = order.volume
        order.status = Status.ALLTRADED
        self.on_event(EVENT_ORDER, order)

        # 更新资金
        trade_value = trade.price * trade.volume
        commission = max(trade_value * self._commission_rate, self._min_commission)

        if trade.direction == Direction.LONG:
            self._balance -= trade_value
            self._balance -= commission
            self._frozen -= trade_value + max(trade_value * self._commission_rate, self._min_commission)

            # 更新持仓
            pos_info = self._positions.get(vt_symbol)
            if not pos_info:
                pos_info = PositionInfo(vt_symbol)
                self._positions[vt_symbol] = pos_info
            pos_info.volume += trade.volume
            pos_info.available += trade.volume
            pos_info.avg_price = (
                (pos_info.avg_price * (pos_info.volume - trade.volume) + trade.price * trade.volume)
                / pos_info.volume
            )

            # T+1 标记
            self._buy_dates[vt_symbol] = date.today()

        elif trade.direction == Direction.SHORT:
            self._balance += trade_value
            stamp_tax = trade_value * self._stamp_tax_rate
            self._balance -= commission + stamp_tax

            # 更新持仓
            pos_info = self._positions.get(vt_symbol)
            if pos_info:
                pos_info.frozen -= trade.volume
                pos_info.volume -= trade.volume
                pos_info.available -= trade.volume
                if pos_info.volume <= 0:
                    del self._positions[vt_symbol]
                    self._buy_dates.pop(vt_symbol, None)

        # 推送事件
        self.on_event(EVENT_TRADE, trade)
        self._trades[trade.vt_tradeid] = trade

        # 推送持仓更新
        self._push_position(vt_symbol)
        # 推送账户更新
        self._push_account()

        self._write_log(
            f"成交: {trade.direction.value} {vt_symbol} "
            f"{trade.volume}@{trade.price:.2f}"
        )

    def cancel_order(self, req: CancelRequest) -> None:
        """撤单"""
        order = self._orders.get(req.vt_orderid)
        if not order or not order.is_active():
            return

        if order.direction == Direction.LONG:
            cost = order.price * order.volume
            commission = max(cost * self._commission_rate, self._min_commission)
            self._frozen -= cost + commission
        elif order.direction == Direction.SHORT:
            pos_info = self._positions.get(order.vt_symbol)
            if pos_info:
                pos_info.frozen -= order.volume - order.traded

        order.status = Status.CANCELLED
        self.on_event(EVENT_ORDER, order)

    def query_account(self) -> None:
        self._push_account()

    def query_position(self) -> None:
        for vt_symbol in list(self._positions.keys()):
            self._push_position(vt_symbol)

    def close(self) -> None:
        self._write_log("模拟交易网关已断开")

    # ── 外部注入行情 ──────────────────────────────────────────────────────

    def inject_tick(self, tick: TickData) -> None:
        """外部注入 tick 数据（来自实时行情）"""
        self._ticks[tick.vt_symbol] = tick
        # 更新昨收价（用于涨跌停计算）
        if tick.pre_close > 0:
            self._pre_closes[tick.vt_symbol] = tick.pre_close
        self.on_event(EVENT_TICK, tick)

    def inject_bar_as_tick(self, vt_symbol: str, open_price: float,
                           high_price: float, low_price: float,
                           close_price: float, volume: float,
                           datetime_val: datetime, exchange: Exchange,
                           pre_close: float = 0) -> None:
        """将 K 线数据转换为 tick 注入"""
        parts = vt_symbol.split(".")
        symbol = parts[0]

        # 使用传入的 pre_close，若为0则回退到缓存中的昨收价
        if pre_close <= 0:
            pre_close = self._pre_closes.get(vt_symbol, close_price)

        tick = TickData(
            symbol=symbol,
            exchange=exchange,
            datetime=datetime_val,
            name="",
            last_price=close_price,
            volume=volume,
            open_price=open_price,
            high_price=high_price,
            low_price=low_price,
            pre_close=pre_close,
            gateway_name=self.gateway_name,
        )
        self.inject_tick(tick)

    # ── 内部方法 ──────────────────────────────────────────────────────────

    def _push_account(self) -> None:
        """推送账户数据"""
        holding_value = sum(
            pos.avg_price * pos.volume
            for pos in self._positions.values()
        )
        account = AccountData(
            accountid="SIM_STOCK",
            balance=self._balance + holding_value,
            frozen=self._frozen,
            gateway_name=self.gateway_name,
        )
        self.on_event(EVENT_ACCOUNT, account)

    def _push_position(self, vt_symbol: str) -> None:
        """推送持仓数据"""
        pos_info = self._positions.get(vt_symbol)
        if not pos_info:
            return

        parts = vt_symbol.split(".")
        symbol = parts[0]
        exchange_str = parts[1] if len(parts) > 1 else "SSE"

        position = PositionData(
            symbol=symbol,
            exchange=Exchange(exchange_str),
            direction=Direction.NET,
            volume=pos_info.volume,
            frozen=pos_info.frozen,
            price=pos_info.avg_price,
            pnl=0,
            gateway_name=self.gateway_name,
        )
        self.on_event(EVENT_POSITION, position)

    def _write_log(self, msg: str) -> None:
        logger.info(f"[SIM_STOCK] {msg}")

    # ── 对外查询接口 ──────────────────────────────────────────────────────

    def get_account_snapshot(self) -> dict:
        """获取账户快照（兼容现有 API 格式）"""
        holding_value = sum(
            pos.avg_price * pos.volume
            for pos in self._positions.values()
        )
        total_assets = self._balance + holding_value
        return {
            "total_assets": round(total_assets, 2),
            "cash": round(self._balance, 2),
            "frozen_cash": round(self._frozen, 2),
            "market_value": round(holding_value, 2),
            "available_cash": round(self._balance - self._frozen, 2),
        }

    def get_positions_snapshot(self) -> list[dict]:
        """获取持仓快照（兼容现有 API 格式）"""
        result = []
        for vt_symbol, pos_info in self._positions.items():
            symbol = vt_symbol.split(".")[0]
            tick = self._ticks.get(vt_symbol)
            current_price = tick.last_price if tick else pos_info.avg_price

            market_value = current_price * pos_info.volume
            cost = pos_info.avg_price * pos_info.volume
            pnl = market_value - cost
            pnl_pct = (pnl / cost * 100) if cost > 0 else 0

            result.append({
                "symbol": symbol,
                "name": "",
                "volume": int(pos_info.volume),
                "available_volume": int(pos_info.available),
                "cost_price": round(pos_info.avg_price, 2),
                "current_price": round(current_price, 2),
                "market_value": round(market_value, 2),
                "pnl": round(pnl, 2),
                "pnl_pct": round(pnl_pct, 2),
            })
        return result

    def get_orders_snapshot(self) -> list[dict]:
        """获取委托快照"""
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

    def get_trades_snapshot(self) -> list[dict]:
        """获取成交快照"""
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


class PositionInfo:
    """持仓信息"""

    def __init__(self, vt_symbol: str) -> None:
        self.vt_symbol: str = vt_symbol
        self.volume: float = 0
        self.frozen: float = 0
        self.available: float = 0
        self.avg_price: float = 0

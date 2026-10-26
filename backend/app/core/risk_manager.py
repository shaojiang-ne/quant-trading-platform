"""
风控管理器

在实盘交易委托提交前进行风控检查，防止超限交易。
"""

import logging
from dataclasses import dataclass, field
from datetime import datetime
from typing import Optional

logger = logging.getLogger(__name__)


@dataclass
class RiskConfig:
    """风控配置"""
    # 单标的最大持仓金额（元），0=不限
    max_position_value: float = 0
    # 单笔最大委托金额（元），0=不限
    max_order_value: float = 0
    # 日亏损上限（元），0=不限
    max_daily_loss: float = 0
    # 日委托次数上限，0=不限
    max_daily_orders: int = 0
    # 单标的最大持仓占比（0-1），0=不限
    max_position_ratio: float = 0
    # 禁止买入列表
    blocked_symbols: list[str] = field(default_factory=list)


@dataclass
class DailyRiskState:
    """每日风控状态"""
    date: str = ""
    order_count: int = 0
    realized_loss: float = 0.0


class RiskManager:
    """风控管理器"""

    _configs: dict[str, RiskConfig] = {}   # account_id -> config
    _states: dict[str, DailyRiskState] = {}  # account_id -> daily state

    def get_config(self, account_id: str) -> RiskConfig:
        return self._configs.get(account_id, RiskConfig())

    def set_config(self, account_id: str, config: RiskConfig):
        self._configs[account_id] = config
        logger.info(f"风控配置已更新: account={account_id}")

    def check_order(
        self,
        account_id: str,
        symbol: str,
        side: str,
        quantity: int,
        price: float,
        total_assets: float = 0,
        current_position_value: float = 0,
    ) -> tuple[bool, str]:
        """
        风控检查

        Returns:
            (passed, reason) — passed=True 表示通过，reason 为拒绝原因
        """
        config = self.get_config(account_id)
        state = self._get_state(account_id)
        order_value = quantity * price

        # 禁止买入列表
        if side == "buy" and symbol in config.blocked_symbols:
            return False, f"标的 {symbol} 在禁止买入列表中"

        # 单笔最大委托金额
        if config.max_order_value > 0 and order_value > config.max_order_value:
            return False, f"单笔委托金额 {order_value:.0f} 超过上限 {config.max_order_value:.0f}"

        # 日委托次数上限
        if config.max_daily_orders > 0 and state.order_count >= config.max_daily_orders:
            return False, f"今日委托次数 {state.order_count} 已达上限 {config.max_daily_orders}"

        # 日亏损上限
        if config.max_daily_loss > 0 and state.realized_loss <= -config.max_daily_loss:
            return False, f"今日亏损 {state.realized_loss:.0f} 已达上限 -{config.max_daily_loss:.0f}"

        # 单标的最大持仓金额（买入时检查）
        if side == "buy" and config.max_position_value > 0:
            new_value = current_position_value + order_value
            if new_value > config.max_position_value:
                return False, f"持仓金额 {new_value:.0f} 将超过上限 {config.max_position_value:.0f}"

        # 单标的最大持仓占比（买入时检查）
        if side == "buy" and config.max_position_ratio > 0 and total_assets > 0:
            new_value = current_position_value + order_value
            ratio = new_value / total_assets
            if ratio > config.max_position_ratio:
                return False, f"持仓占比 {ratio:.1%} 将超过上限 {config.max_position_ratio:.1%}"

        return True, ""

    def record_order(self, account_id: str):
        """记录已提交委托"""
        state = self._get_state(account_id)
        state.order_count += 1

    def record_loss(self, account_id: str, loss: float):
        """记录亏损（loss 为负数表示亏损）"""
        state = self._get_state(account_id)
        if loss < 0:
            state.realized_loss += loss

    def _get_state(self, account_id: str) -> DailyRiskState:
        today = datetime.now().strftime("%Y-%m-%d")
        state = self._states.get(account_id)
        if not state or state.date != today:
            state = DailyRiskState(date=today)
            self._states[account_id] = state
        return state


# 全局单例
risk_manager = RiskManager()
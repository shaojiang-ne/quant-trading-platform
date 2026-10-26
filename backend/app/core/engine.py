"""
vnpy 核心引擎封装

提供 MainEngine 单例管理、事件桥接、网关管理。
当 vnpy 未安装时，提供 mock 降级。
"""

import logging
from typing import Optional

logger = logging.getLogger(__name__)

# 尝试导入vnpy，不可用时降级
VNPY_AVAILABLE = False
try:
    from vnpy.event import EventEngine
    from vnpy.trader.engine import MainEngine
    from vnpy.trader.gateway import BaseGateway
    VNPY_AVAILABLE = True
    logger.info("vnpy 已加载")
except ImportError:
    logger.warning("vnpy 未安装，使用模拟模式")


class VnpyEngineManager:
    """vnpy MainEngine 单例管理器"""

    _instance: Optional["VnpyEngineManager"] = None
    _main_engine = None
    _event_engine = None

    def __new__(cls):
        if cls._instance is None:
            cls._instance = super().__new__(cls)
        return cls._instance

    @property
    def available(self) -> bool:
        return VNPY_AVAILABLE

    def get_engine(self):
        """获取 MainEngine 实例"""
        if not VNPY_AVAILABLE:
            return None

        if self._main_engine is None:
            self._event_engine = EventEngine()
            self._main_engine = MainEngine(self._event_engine)
            self._register_gateways()
            # MainEngine.__init__ already starts the event engine
            logger.info("vnpy MainEngine 已启动")

        return self._main_engine

    def _register_gateways(self):
        """注册可用的交易网关"""
        if not VNPY_AVAILABLE:
            return

        try:
            from vnpy_ctp import CtpGateway
            self._main_engine.add_gateway(CtpGateway)
            logger.info("CTP网关已注册")
        except ImportError:
            logger.debug("CTP网关不可用")

        try:
            from vnpy_xtp import XtpGateway
            self._main_engine.add_gateway(XtpGateway)
            logger.info("XTP网关已注册")
        except ImportError:
            logger.debug("XTP网关不可用")

    def connect_gateway(self, gateway_name: str, setting: dict) -> bool:
        """连接交易网关"""
        engine = self.get_engine()
        if not engine:
            logger.warning(f"vnpy不可用，无法连接 {gateway_name}")
            return False

        try:
            engine.connect(setting, gateway_name)
            logger.info(f"网关 {gateway_name} 连接请求已发送")
            return True
        except Exception as e:
            logger.error(f"网关 {gateway_name} 连接失败: {e}")
            return False

    def close_gateway(self, gateway_name: str):
        """断开网关连接"""
        engine = self.get_engine()
        if not engine:
            return
        try:
            engine.close_gateway(gateway_name)
            logger.info(f"网关 {gateway_name} 已断开")
        except Exception as e:
            logger.error(f"网关 {gateway_name} 断开失败: {e}")

    def shutdown(self):
        """关闭引擎"""
        if self._main_engine:
            self._main_engine.close()
            self._main_engine = None
            self._event_engine = None
            logger.info("vnpy MainEngine 已关闭")


# 全局单例
engine_manager = VnpyEngineManager()

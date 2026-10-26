"""
行情数据后端抽象 + 实现

MarketBackend 定义行情服务的统一接口，
StockDataMarketBackend 是原有 stock_data 微服务实现（HTTP + WebSocket），
AkshareMarketBackend 是 akshare 公开 HTTP 轮询实现。
"""

import abc
import asyncio
import json
import logging
import ssl
from typing import Optional

import httpx
import pandas as pd
import websockets
import urllib3

urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)

from app.config import settings

logger = logging.getLogger(__name__)


class MarketBackend(abc.ABC):
    """行情数据后端抽象基类"""

    @abc.abstractmethod
    def is_available(self) -> bool: ...

    @abc.abstractmethod
    def check_health(self) -> dict: ...

    @abc.abstractmethod
    def get_klines(self, symbol, period='1d', start_time='', end_time='',
                   count=-1, dividend_type='none') -> pd.DataFrame: ...

    @abc.abstractmethod
    def get_full_tick(self, symbol: str) -> Optional[dict]: ...

    @abc.abstractmethod
    def get_stock_list(self, sector: str = '沪深A股') -> list[str]: ...

    @abc.abstractmethod
    def get_stock_list_full(self, sector: str = '沪深A股') -> list[dict]: ...

    @abc.abstractmethod
    def get_instrument_detail(self, symbol: str) -> Optional[dict]: ...

    @abc.abstractmethod
    def get_instruments_batch(self, symbols: list[str]) -> dict[str, Optional[dict]]: ...

    @abc.abstractmethod
    def subscribe_quote(self, symbol: str, period: str = 'tick', callback=None) -> Optional[int]: ...

    @abc.abstractmethod
    def unsubscribe_quote(self, seq: int) -> bool: ...

    @abc.abstractmethod
    def close(self) -> None: ...


class StockDataMarketBackend(MarketBackend):
    """stock_data 微服务后端（原有实现，HTTP + WebSocket）"""

    VALID_PERIODS = {'1m', '5m', '15m', '30m', '60m', '1h', '1d', '1w', '1mon'}
    VALID_DIVIDEND_TYPES = {'none', 'front', 'back'}

    def __init__(self):
        self._available: Optional[bool] = None
        self._client: Optional[httpx.Client] = None
        self._sub_seq_counter: int = 0
        self._sub_callbacks: dict[int, tuple[str, object]] = {}  # seq -> (symbol, callback)

        # WebSocket 订阅管理
        self._ws_subscribed_symbols: set[str] = set()  # 已通过 WS 订阅的 symbol 集合
        self._ws_task: Optional[asyncio.Task] = None
        self._ws_connected: bool = False
        self._ws: Optional[websockets.WebClientProtocol] = None  # 当前 WS 连接

        # 合约详情缓存
        self._instrument_cache: dict[str, Optional[dict]] = {}

    def _log_request(self, request: httpx.Request):
        logger.debug(f"[stock_data] >>> {request.method} {request.url}")

    def _log_response(self, response: httpx.Response):
        request = response.request
        logger.debug(f"[stock_data] <<< {request.method} {request.url} -> {response.status_code}")

    def _get_client(self) -> httpx.Client:
        if self._client is None or self._client.is_closed:
            headers = {}
            if settings.STOCK_DATA_API_KEY:
                headers["X-API-Key"] = settings.STOCK_DATA_API_KEY
            self._client = httpx.Client(
                base_url=settings.STOCK_DATA_URL,
                timeout=10.0,
                headers=headers,
                verify=False,
                limits=httpx.Limits(max_connections=20, max_keepalive_connections=5),
                event_hooks={"request": [self._log_request], "response": [self._log_response]},
            )
        return self._client

    def _check_available(self) -> bool:
        """检查 stock_data 服务是否可用"""
        try:
            resp = self._get_client().get("/api/v1/health")
            if resp.status_code == 200:
                data = resp.json()
                # 服务在线即可获取K线数据，xtquant 是实盘行情才需要
                return data.get("status") == "online"
            return False
        except httpx.HTTPStatusError as e:
            logger.error(f"[stock_data] GET /api/v1/health -> {e.response.status_code}")
            return False
        except httpx.RequestError as e:
            logger.error(f"[stock_data] GET /api/v1/health 请求失败: {e}")
            return False
        except Exception as e:
            logger.error(f"[stock_data] GET /api/v1/health 异常: {e}")
            return False

    def is_available(self) -> bool:
        """返回缓存的可用状态（启动时探测一次）"""
        if self._available is None:
            self._available = self._check_available()
            if self._available:
                logger.info("stock_data 行情服务已连接")
            else:
                logger.warning("stock_data 行情服务不可用")
        return self._available

    def check_health(self) -> dict:
        """实时探测行情服务健康状态，返回详细信息"""
        try:
            resp = self._get_client().get("/api/v1/health", timeout=3)
            data = resp.json() if resp.status_code == 200 else {}
            service_online = data.get("status") == "online"
            xtq = data.get("xtquant", {})
            # 行情数据可用只需服务在线，xtquant 是实盘行情才需要
            self._available = service_online
            return {
                "service": data.get("service", "unknown"),
                "status": data.get("status", "unknown"),
                "xtquant": {
                    "available": xtq.get("available", False),
                    "connected": xtq.get("connected", False),
                    "error": xtq.get("error", ""),
                },
            }
        except Exception as e:
            self._available = False
            logger.error(f"[stock_data] GET /api/v1/health 请求失败: {e}")
            return {
                "service": "stock_data",
                "status": "offline",
                "xtquant": {"available": False, "connected": False, "error": str(e)},
            }

    def get_klines(
        self,
        symbol: str,
        period: str = '1d',
        start_time: str = '',
        end_time: str = '',
        count: int = -1,
        dividend_type: str = 'none',
    ) -> pd.DataFrame:
        """获取K线数据"""
        if period not in self.VALID_PERIODS:
            logger.error(f"无效周期: {period}")
            return pd.DataFrame()

        if dividend_type not in self.VALID_DIVIDEND_TYPES:
            dividend_type = 'none'

        try:
            params = {
                "symbol": symbol, "period": period,
                "start_time": start_time, "end_time": end_time,
                "count": count, "dividend_type": dividend_type,
            }
            # 1m/5m 等细颗粒度数据量大，需要更长超时
            timeout = 30.0 if period in ("1m", "5m", "15m", "30m", "1h") else 10.0
            resp = self._get_client().get("/api/v1/klines", params=params, timeout=timeout)
            if resp.status_code != 200:
                logger.error(f"获取K线失败: HTTP {resp.status_code}")
                return pd.DataFrame()

            data = resp.json()
            klines = data.get("klines", [])
            if not klines:
                return pd.DataFrame()

            df = pd.DataFrame(klines)
            df = df.rename(columns={"datetime": "date"})
            df = df.set_index("date")
            for col in ["open", "high", "low", "close", "volume", "amount"]:
                if col in df.columns:
                    df[col] = pd.to_numeric(df[col], errors="coerce")
            return df
        except httpx.RequestError as e:
            logger.error(f"[stock_data] GET /api/v1/klines 请求失败 {symbol} {period}: {e}")
            return pd.DataFrame()
        except Exception as e:
            logger.error(f"获取K线失败 {symbol} {period}: {e}")
            return pd.DataFrame()

    def get_full_tick(self, symbol: str) -> Optional[dict]:
        """获取最新 tick 数据

        返回兼容格式（lastPrice/bidPrice 等），供 _on_tick 回调使用。
        """
        try:
            resp = self._get_client().get(f"/api/v1/tick/{symbol}")
            if resp.status_code != 200:
                return None
            data = resp.json()
            return self._convert_tick_format(data)
        except httpx.RequestError as e:
            logger.error(f"[stock_data] GET /api/v1/tick/{symbol} 请求失败: {e}")
            return None
        except Exception as e:
            logger.error(f"获取tick失败 {symbol}: {e}")
            return None

    def get_stock_list(self, sector: str = '沪深A股') -> list[str]:
        """获取股票代码列表"""
        try:
            resp = self._get_client().get("/api/v1/stocks", params={"sector": sector})
            if resp.status_code != 200:
                return []
            data = resp.json()
            return [s["symbol"] for s in data.get("stocks", [])]
        except Exception as e:
            logger.error(f"获取股票列表失败: {e}")
            return []

    def get_stock_list_full(self, sector: str = '沪深A股') -> list[dict]:
        """获取完整股票列表（含名称、交易所、拼音），一次请求，无需再查 instruments"""
        try:
            resp = self._get_client().get("/api/v1/stocks", params={"sector": sector})
            if resp.status_code != 200:
                return []
            data = resp.json()
            return data.get("stocks", [])
        except Exception as e:
            logger.error(f"获取股票列表失败: {e}")
            return []

    def get_instrument_detail(self, symbol: str) -> Optional[dict]:
        """获取合约详情（带缓存，避免重复请求）"""
        if symbol in self._instrument_cache:
            return self._instrument_cache[symbol]

        try:
            resp = self._get_client().get(f"/api/v1/instruments/{symbol}")
            if resp.status_code != 200:
                self._instrument_cache[symbol] = None
                return None
            data = resp.json()
            result = {
                "InstrumentID": data.get("instrument_id", ""),
                "InstrumentName": data.get("instrument_name", ""),
                "ExchangeID": data.get("exchange_id", ""),
            }
            self._instrument_cache[symbol] = result
            return result
        except Exception as e:
            logger.error(f"获取合约详情失败 {symbol}: {e}")
            self._instrument_cache[symbol] = None
            return None

    def get_instruments_batch(self, symbols: list[str]) -> dict[str, Optional[dict]]:
        """批量获取合约详情

        优先尝试 stock_data 的批量接口 /api/v1/instruments/batch，
        不可用时回退到逐个查询（带缓存）。
        """
        result: dict[str, Optional[dict]] = {}
        uncached: list[str] = []

        for symbol in symbols:
            if symbol in self._instrument_cache:
                result[symbol] = self._instrument_cache[symbol]
            else:
                uncached.append(symbol)

        if not uncached:
            return result

        # 尝试批量接口
        try:
            resp = self._get_client().post(
                "/api/v1/instruments/batch",
                json={"symbols": uncached},
                timeout=30.0,
            )
            if resp.status_code == 200:
                batch_data = resp.json()
                if isinstance(batch_data, dict):
                    for symbol in uncached:
                        raw = batch_data.get(symbol)
                        if raw:
                            detail = {
                                "InstrumentID": raw.get("instrument_id", ""),
                                "InstrumentName": raw.get("instrument_name", ""),
                                "ExchangeID": raw.get("exchange_id", ""),
                            }
                        else:
                            detail = None
                        self._instrument_cache[symbol] = detail
                        result[symbol] = detail
                    return result
        except Exception as e:
            logger.warning(f"[stock_data] POST /api/v1/instruments/batch 请求失败，回退逐个查询: {e}")

        # 批量接口不可用，逐个查（已有缓存）
        for symbol in uncached:
            result[symbol] = self.get_instrument_detail(symbol)

        return result

    # ── WebSocket 实时行情订阅 ─────────────────────────────────────────────

    def subscribe_quote(
        self,
        symbol: str,
        period: str = 'tick',
        callback=None,
    ) -> Optional[int]:
        """订阅实时行情

        通过 WebSocket 连接 stock_data /api/v1/ws/quote，
        收到 tick 推送时调用 callback。

        Returns:
            订阅序号，用于取消订阅；失败返回 None
        """
        self._sub_seq_counter += 1
        seq = self._sub_seq_counter

        if callback:
            self._sub_callbacks[seq] = (symbol, callback)

        # 首次订阅时启动 WebSocket 连接
        self._ensure_ws_connection()

        # 如果该 symbol 尚未订阅，发送 subscribe 消息
        if symbol not in self._ws_subscribed_symbols:
            self._ws_subscribed_symbols.add(symbol)
            if self._ws_connected and self._ws:
                asyncio.create_task(self._ws_send({
                    "action": "subscribe",
                    "symbols": [symbol],
                    "period": "tick",
                }))

        return seq

    def unsubscribe_quote(self, seq: int) -> bool:
        """取消订阅"""
        sub = self._sub_callbacks.pop(seq, None)
        if not sub:
            return True

        symbol, callback = sub

        # 检查是否还有其他 callback 订阅该 symbol
        still_subscribed = any(
            s == symbol for s, _ in self._sub_callbacks.values()
        )

        if not still_subscribed and symbol in self._ws_subscribed_symbols:
            self._ws_subscribed_symbols.discard(symbol)
            if self._ws_connected and self._ws:
                asyncio.create_task(self._ws_send({
                    "action": "unsubscribe",
                    "symbols": [symbol],
                }))

        # 无订阅时关闭 WebSocket
        if not self._ws_subscribed_symbols:
            self._close_ws()

        return True

    def _ensure_ws_connection(self):
        """确保 WebSocket 连接已启动"""
        if self._ws_task is not None and not self._ws_task.done():
            return
        self._ws_task = asyncio.create_task(self._ws_loop())

    def _close_ws(self):
        """关闭 WebSocket 连接"""
        if self._ws_task and not self._ws_task.done():
            self._ws_task.cancel()
            self._ws_task = None
        self._ws = None
        self._ws_connected = False

    async def _ws_loop(self):
        """WebSocket 连接循环：连接 stock_data /api/v1/ws/quote，接收 tick 推送"""
        base_url = settings.STOCK_DATA_URL.replace("http://", "ws://").replace("https://", "wss://")
        url = f"{base_url}/api/v1/ws/quote"
        if settings.STOCK_DATA_API_KEY:
            url += f"?apikey={settings.STOCK_DATA_API_KEY}"

        while True:
            try:
                ssl_ctx = ssl.SSLContext(ssl.PROTOCOL_TLS_CLIENT)
                ssl_ctx.check_hostname = False
                ssl_ctx.verify_mode = ssl.CERT_NONE

                async with websockets.connect(url, ping_interval=30, ping_timeout=10, ssl=ssl_ctx) as ws:
                    self._ws = ws
                    self._ws_connected = True
                    logger.info(f"行情 WebSocket 已连接: {url}")

                    # 重新订阅已有 symbol
                    if self._ws_subscribed_symbols:
                        await ws.send(json.dumps({
                            "action": "subscribe",
                            "symbols": list(self._ws_subscribed_symbols),
                            "period": "tick",
                        }))
                        logger.debug(f"重新订阅: {self._ws_subscribed_symbols}")

                    # 接收消息
                    async for message in ws:
                        try:
                            data = json.loads(message)
                            msg_type = data.get("type")

                            if msg_type == "tick":
                                self._dispatch_tick(data)
                            elif msg_type == "quote":
                                # stock_data WS 推送格式: {"type": "quote", "data": {"600519.SH": {...}}}
                                self._dispatch_quote(data)
                            elif msg_type == "subscribed":
                                logger.debug(f"行情订阅确认: {data.get('symbols', [])}")
                            elif msg_type == "unsubscribed":
                                logger.debug(f"行情取消订阅确认: {data.get('symbols', [])}")
                            elif msg_type == "pong":
                                pass
                        except json.JSONDecodeError:
                            pass

            except asyncio.CancelledError:
                self._ws = None
                self._ws_connected = False
                break
            except Exception as e:
                self._ws = None
                self._ws_connected = False
                logger.warning(f"行情 WebSocket 断开: {e}，5秒后重连...")
                await asyncio.sleep(5)

    async def _ws_send(self, msg: dict):
        """通过 WebSocket 发送消息"""
        if self._ws and self._ws_connected:
            try:
                await self._ws.send(json.dumps(msg))
            except Exception as e:
                logger.warning(f"WebSocket 发送失败: {e}")

    def _dispatch_tick(self, data: dict):
        """将 WebSocket tick 推送分发给所有订阅了该 symbol 的 callback"""
        symbol = data.get("symbol", "")
        if not symbol:
            return

        # 转换为 callback 兼容格式
        tick = self._convert_tick_format(data)
        tick["stock"] = symbol

        for seq, (sub_symbol, callback) in list(self._sub_callbacks.items()):
            if sub_symbol == symbol and callback:
                try:
                    callback(tick)
                except Exception as e:
                    logger.error(f"tick 回调异常: {e}")

    def _dispatch_quote(self, data: dict):
        """处理 stock_data WS 推送的 quote 格式: {"type": "quote", "data": {"600519.SH": {...}}}"""
        quotes = data.get("data", {})
        for symbol, tick_data in quotes.items():
            if not symbol or not tick_data:
                continue
            tick = self._convert_tick_format(tick_data)
            tick["stock"] = symbol
            for seq, (sub_symbol, callback) in list(self._sub_callbacks.items()):
                if sub_symbol == symbol and callback:
                    try:
                        callback(tick)
                    except Exception as e:
                        logger.error(f"quote 回调异常: {e}")

    @staticmethod
    def _convert_tick_format(data: dict) -> dict:
        """将 stock_data API 格式转为 callback 兼容格式

        API 字段: last_price, bid_prices, bid_volumes, ask_prices, ask_volumes, last_close, datetime
        回调字段: lastPrice, bidPrice, bidVol, askPrice, askVol, lastClose, timetag
        """
        return {
            "lastPrice": data.get("last_price", 0),
            "open": data.get("open", 0),
            "high": data.get("high", 0),
            "low": data.get("low", 0),
            "lastClose": data.get("last_close", 0),
            "volume": data.get("volume", 0),
            "amount": data.get("amount", 0),
            "bidPrice": data.get("bid_prices", []),
            "bidVol": data.get("bid_volumes", []),
            "askPrice": data.get("ask_prices", []),
            "askVol": data.get("ask_volumes", []),
            "timetag": data.get("datetime", ""),
        }

    def close(self):
        """关闭 HTTP 客户端和 WebSocket"""
        self._close_ws()
        if self._client and not self._client.is_closed:
            self._client.close()


class AkshareMarketBackend(MarketBackend):
    """akshare 公开 HTTP 后端：60 秒轮询全市场快照

    注意：akshare 的 stock_zh_a_spot_em() 通过 fetch_paginated_data 分页拉取
    （5000+ 只股票，每页 100 条 = 55+ 次 HTTP 请求），一轮耗时 30-80s。
    轮询间隔 60s + _polling 互斥锁，确保不会并发拉取导致 TCP 端口耗尽。
    """

    def __init__(self):
        self._available: Optional[bool] = None
        self._tick_cache: dict[str, dict] = {}  # symbol -> tick
        self._instrument_cache: dict[str, Optional[dict]] = {}

        # 订阅管理
        self._sub_seq_counter: int = 0
        self._sub_callbacks: dict[int, tuple[str, object]] = {}  # seq -> (symbol, callback)
        self._subscribed_symbols: set[str] = set()

        # 轮询任务
        self._poll_task: Optional[asyncio.Task] = None
        self._poll_interval: float = 60.0  # 秒（akshare 分页拉取 55+ 次 HTTP，一轮 30-80s，间隔须大于一轮耗时）
        self._polling: bool = False  # 互斥锁，防止上一轮未完成就开始下一轮

        # 缓存数据源实例，避免每次轮询都新建
        self._akshare_source: Optional[object] = None

    def is_available(self) -> bool:
        if self._available is None:
            try:
                import akshare  # noqa: F401
                self._available = True
                logger.info("akshare 行情后端可用")
            except ImportError:
                self._available = False
                logger.warning("akshare 未安装，行情后端不可用")
        return self._available

    def check_health(self) -> dict:
        available = self.is_available()
        return {
            "service": "akshare",
            "status": "online" if available else "offline",
            "xtquant": {"available": False, "connected": False,
                        "error": "" if available else "akshare 未安装"},
        }

    def get_full_tick(self, symbol: str) -> Optional[dict]:
        return self._tick_cache.get(symbol)

    def _snapshot_to_tick(self, symbol: str, snap: dict) -> dict:
        """快照转 callback 兼容 tick 格式

        akshare spot_em 字段: name/price/change_pct/turnover_pct/pe_ttm/pb/
        float_mcap_yi/vol_ratio/amount_wan。无 open/high/low/lastClose/volume/五档。
        缺失字段置 0/[]，对齐 _on_tick 期望的 lastPrice/bidPrice 等字段名。
        """
        def _f(key):
            v = snap.get(key)
            try:
                return float(v) if v is not None and str(v) != "nan" else 0
            except (TypeError, ValueError):
                return 0

        return {
            "stock": symbol,
            "lastPrice": _f("price"),
            "open": 0,
            "high": 0,
            "low": 0,
            "lastClose": 0,  # akshare 快照无昨收，置 0（pre_close 由 _on_tick 旧缓存兜底）
            "volume": 0,
            "amount": _f("amount_wan") * 1e4,  # 万 → 元
            "bidPrice": [],
            "bidVol": [],
            "askPrice": [],
            "askVol": [],
            "timetag": "",
        }

    def _update_cache(self, snapshot: dict[str, dict]) -> None:
        """把快照结果写入 _tick_cache"""
        for symbol, snap in snapshot.items():
            self._tick_cache[symbol] = self._snapshot_to_tick(symbol, snap)

    # market_service 周期 → data_bridge.load_bars_df period
    # data_bridge period_map 仅识别 daily/weekly/monthly/tick/1m/5m，其余原样透传
    # 给底层数据源（akshare _PERIOD_MAP 支持 15m/30m/60m/1h）
    _PERIOD_TO_DATABRIDGE = {
        "1d": "daily",
        "1w": "weekly",
        "1m": "1m",
        "5m": "5m",
        "15m": "15m",
        "30m": "30m",
        "60m": "60m",
        "1h": "60m",
        "1mon": "daily",  # data_bridge 无月线，近似用 daily
    }

    @staticmethod
    def _normalize_date(s: str) -> str:
        """YYYYMMDD → YYYY-MM-DD；空/已带分隔符原样返回"""
        if not s:
            return ""
        s = s.strip()
        if len(s) == 8 and s.isdigit():
            return f"{s[:4]}-{s[4:6]}-{s[6:]}"
        return s

    def get_klines(self, symbol, period='1d', start_time='', end_time='',
                   count=-1, dividend_type='none') -> pd.DataFrame:
        """委托 data_bridge.load_bars_df（auto 多源降级），返回 market_service 契约 df。

        契约：date 作为 index，列含 open/high/low/close/volume/amount。
        """
        from app.core.data_bridge import data_bridge

        db_period = self._PERIOD_TO_DATABRIDGE.get(period)
        if db_period is None:
            logger.warning(f"akshare backend 未知周期 '{period}'，回退 daily")
            db_period = "daily"
        if period == "1mon":
            logger.warning("akshare backend 不支持月线，近似用 daily")

        start_date = self._normalize_date(start_time)
        end_date = self._normalize_date(end_time)

        try:
            df = data_bridge.load_bars_df(
                symbol=symbol,
                start_date=start_date,
                end_date=end_date,
                period=db_period,
            )
        except Exception as e:
            logger.error(f"akshare backend get_klines 委托失败 {symbol} {period}: {e}")
            return pd.DataFrame()

        if df is None or df.empty:
            return pd.DataFrame()

        # data_bridge 返回列 [date, open, high, low, close, volume, turnover]
        # market_service 契约：date 为 index，turnover → amount
        out = df.copy()
        if "turnover" in out.columns and "amount" not in out.columns:
            out = out.rename(columns={"turnover": "amount"})
        if "date" in out.columns:
            out = out.set_index("date")
        return out

    def get_stock_list(self, sector='沪深A股') -> list[str]:
        """获取股票代码列表（裸 6 位代码）"""
        return [s["symbol"] for s in self.get_stock_list_full(sector) if s.get("symbol")]

    def get_stock_list_full(self, sector='沪深A股') -> list[dict]:
        """获取完整股票列表（含 symbol/name/exchange），lazy 用 akshare spot_em。

        复用 data_source_akshare.get_snapshot 的「代码/名称」列名匹配模式。
        """
        try:
            import akshare as ak
        except ImportError:
            logger.error("akshare 未安装，无法获取股票列表")
            return []
        try:
            df = ak.stock_zh_a_spot_em()
        except Exception as e:
            logger.error(f"akshare 获取股票列表失败: {e}")
            return []
        if df is None or df.empty:
            return []

        # 列名为中文，按关键字匹配（复用 data_source_akshare.get_snapshot 模式）
        def col(*keywords):
            for c in df.columns:
                cs = str(c)
                if all(k in cs for k in keywords):
                    return c
            return None

        code_col = col("代码")
        name_col = col("名称")
        if code_col is None:
            logger.error(f"akshare spot_em 找不到代码列，实际列: {list(df.columns)}")
            return []

        out: list[dict] = []
        for _, row in df.iterrows():
            code = str(row[code_col]).strip()
            if not code or len(code) != 6 or not code.isdigit():
                continue
            name = str(row[name_col]).strip() if name_col else ""
            out.append({"symbol": code, "name": name, "exchange": ""})
        return out

    def get_instrument_detail(self, symbol: str) -> Optional[dict]:
        return None  # akshare 后端不提供合约详情

    def get_instruments_batch(self, symbols: list[str]) -> dict[str, Optional[dict]]:
        return {s: None for s in symbols}

    def subscribe_quote(self, symbol: str, period: str = 'tick',
                        callback=None) -> Optional[int]:
        self._sub_seq_counter += 1
        seq = self._sub_seq_counter
        if callback:
            self._sub_callbacks[seq] = (symbol, callback)
        self._subscribed_symbols.add(symbol)
        self._ensure_poll_loop()
        return seq

    def unsubscribe_quote(self, seq: int) -> bool:
        sub = self._sub_callbacks.pop(seq, None)
        if not sub:
            return True
        symbol = sub[0]
        still_subscribed = any(s == symbol for s, _ in self._sub_callbacks.values())
        if not still_subscribed:
            self._subscribed_symbols.discard(symbol)
        if not self._sub_callbacks:
            self._close_poll_loop()
        return True

    def close(self) -> None:
        self._close_poll_loop()
        self._tick_cache.clear()

    def _ensure_poll_loop(self) -> None:
        if self._poll_task is not None and not self._poll_task.done():
            return
        try:
            self._poll_task = asyncio.create_task(self._poll_loop())
        except RuntimeError:
            # 无 event loop（同步上下文调用）时跳过，等首次异步调用再起
            pass

    def _close_poll_loop(self) -> None:
        if self._poll_task and not self._poll_task.done():
            self._poll_task.cancel()
        self._poll_task = None

    async def _poll_loop(self) -> None:
        """轮询循环：每 60 秒拉一次快照（_poll_interval）"""
        try:
            while self._sub_callbacks:
                await self._poll_once()
                await asyncio.sleep(self._poll_interval)
        except asyncio.CancelledError:
            pass
        except Exception as e:
            logger.error(f"akshare 轮询循环异常退出: {e}", exc_info=True)
            await asyncio.sleep(5)
            # 重启
            if self._sub_callbacks:
                self._poll_task = asyncio.create_task(self._poll_loop())

    async def _poll_once(self) -> None:
        """单次轮询：检查交易时间 → 拉快照 → 更新缓存 → 分发

        使用 _polling 互斥锁防止并发：stock_zh_a_spot_em() 分页拉取 55+ 次 HTTP，
        一轮耗时 30-80s，若上一轮未完成则跳过本轮。
        """
        if self._polling:
            logger.debug("akshare 上一轮轮询未完成，跳过本轮")
            return

        from app.services.trading_calendar_service import trading_calendar

        if not trading_calendar.is_trading_time():
            return  # 非交易时间跳过

        self._polling = True
        try:
            snapshot = await asyncio.to_thread(self._fetch_snapshot)
        except Exception as e:
            logger.warning(f"akshare 拉取快照失败，保留旧缓存: {e}")
            return  # 异常时不清缓存、不推送
        finally:
            self._polling = False

        if not snapshot:
            return  # 空结果保留旧缓存

        self._update_cache(snapshot)
        self._dispatch(snapshot)

    def _fetch_snapshot(self) -> dict[str, dict]:
        """同步拉快照（在 to_thread 里跑）。复用缓存的 AkshareDataSource 实例，避免每次新建。"""
        if not self._subscribed_symbols:
            return {}
        if self._akshare_source is None:
            from app.core.data_source_akshare import AkshareDataSource
            self._akshare_source = AkshareDataSource()
        codes = list(self._subscribed_symbols)
        return self._akshare_source.get_snapshot(codes)

    def _dispatch(self, snapshot: dict[str, dict]) -> None:
        """把缓存的 tick 分发给订阅了该 symbol 的 callback"""
        # 拷贝一份：callback 内可能调 unsubscribe_quote 改动 _subscribed_symbols，
        # 直接迭代会 RuntimeError: Set changed size during iteration。
        for symbol in list(self._subscribed_symbols):
            tick = self._tick_cache.get(symbol)
            if tick is None:
                logger.debug(f"轮询结果无 {symbol}（停牌/退市?）")
                continue
            for seq, (sub_symbol, callback) in list(self._sub_callbacks.items()):
                if sub_symbol == symbol and callback:
                    try:
                        callback(tick)
                    except Exception as e:
                        logger.error(f"tick 回调异常: {e}")

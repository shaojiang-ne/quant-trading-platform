import logging
from functools import lru_cache

from fastapi import APIRouter, Query
from pypinyin import lazy_pinyin
from pydantic import BaseModel

from app.services.market_service import market_service

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/stocks", tags=["股票"])


class StockInfo(BaseModel):
    code: str        # 6位代码，如 600519
    name: str        # 股票名称，如 贵州茅台
    exchange: str    # 交易所，如 SH/SZ
    pinyin: str      # 拼音首字母，如 GZMT
    full_pinyin: str # 全拼，如 guizhoumaotai


# ── 股票列表缓存 ────────────────────────────────────────────────────────────────

_stock_list: list[StockInfo] | None = None


def _make_pinyin(name: str) -> tuple[str, str]:
    """生成拼音首字母和全拼"""
    try:
        py_list = lazy_pinyin(name)
        first_letters = "".join(p[0] for p in py_list)
        full = "".join(py_list)
        return first_letters.lower(), full.lower()
    except Exception:
        return "", ""


def _load_stocks_from_mootdx() -> list[StockInfo]:
    """从 mootdx（通达信）加载 A 股列表（首选，不封IP）"""
    try:
        from mootdx.quotes import Quotes
        import socket

        # 实测可用的备选服务器（SKILL.md 推荐）
        _TDX_SERVERS = [
            ('119.97.185.59', 7709), ('124.70.133.119', 7709), ('116.205.183.150', 7709),
            ('123.60.73.44', 7709), ('116.205.163.254', 7709), ('121.36.225.169', 7709),
        ]

        # TCP 探测找可用服务器
        def _probe(ip, port, timeout=2.0):
            try:
                with socket.create_connection((ip, port), timeout=timeout):
                    return True
            except Exception:
                return False

        # 创建客户端（规避 mootdx 0.11.x BESTIP bug）
        client = None
        for ip, port in _TDX_SERVERS:
            if _probe(ip, port):
                client = Quotes.factory(market='std', server=(ip, port))
                break

        if not client:
            # 回退到 mootdx 自带 bestip
            try:
                client = Quotes.factory(market='std', bestip=True)
            except Exception:
                client = Quotes.factory(market='std')

        if not client:
            logger.warning("mootdx 客户端创建失败")
            return []

        # 获取股票列表
        stocks = []
        # 沪市 A 股
        sh_stocks = client.stocks(market=1)  # market=1 为上海
        for s in sh_stocks:
            code = s.get('code', '')
            name = s.get('name', '')
            if code and name:
                py, full_py = _make_pinyin(name)
                stocks.append(StockInfo(
                    code=code,
                    name=name,
                    exchange='SH',
                    pinyin=py,
                    full_pinyin=full_py,
                ))

        # 深市 A 股
        sz_stocks = client.stocks(market=0)  # market=0 为深圳
        for s in sz_stocks:
            code = s.get('code', '')
            name = s.get('name', '')
            if code and name:
                py, full_py = _make_pinyin(name)
                stocks.append(StockInfo(
                    code=code,
                    name=name,
                    exchange='SZ',
                    pinyin=py,
                    full_pinyin=full_py,
                ))

        logger.info(f"从 mootdx 加载 {len(stocks)} 只股票")
        return stocks
    except Exception as e:
        logger.error(f"从 mootdx 加载股票列表失败: {e}")
        return []


def _load_stocks_from_baostock() -> list[StockInfo]:
    """从 baostock 加载 A 股列表（备选）"""
    try:
        import baostock as bs
        from datetime import datetime, timedelta

        # 登录 baostock
        lg = bs.login()
        if lg.error_code != '0':
            logger.warning(f"baostock 登录失败: {lg.error_msg}")
            return []

        # 查询股票列表（使用 query_all_stock）
        day = (datetime.now() - timedelta(days=1)).strftime('%Y-%m-%d')
        rs = bs.query_all_stock(day=day)
        stocks = []
        while (rs.error_code == '0') & rs.next():
            row = rs.get_row_data()
            # row 字段: code, trade_status, code_name
            code = row[0]  # 代码格式：sh.600519
            name = row[2] if len(row) > 2 else ''

            # 解析代码
            if '.' in code:
                parts = code.split('.')
                exchange_prefix = parts[0].lower()
                pure_code = parts[1]
                exchange = "SH" if exchange_prefix == "sh" else "SZ" if exchange_prefix == "sz" else "BJ"
            else:
                pure_code = code
                exchange = "SH" if pure_code.startswith(("60", "68")) else "SZ"

            if pure_code and name:
                py, full_py = _make_pinyin(name)
                stocks.append(StockInfo(
                    code=pure_code,
                    name=name,
                    exchange=exchange,
                    pinyin=py,
                    full_pinyin=full_py,
                ))

        bs.logout()
        logger.info(f"从 baostock 加载 {len(stocks)} 只股票")
        return stocks
    except Exception as e:
        logger.error(f"从 baostock 加载股票列表失败: {e}")
        return []


def _load_stocks_from_akshare() -> list[StockInfo]:
    """从 akshare 加载 A 股列表（备用方案）"""
    try:
        import akshare as ak
        df = ak.stock_info_a_code_name()
        stocks = []
        for row in df.itertuples():
            code = str(row.code)
            name = str(row.name)
            # 根据代码判断交易所
            exchange = "SH" if code.startswith(("60", "68")) else "SZ"
            py, full_py = _make_pinyin(name)
            stocks.append(StockInfo(
                code=code,
                name=name,
                exchange=exchange,
                pinyin=py,
                full_pinyin=full_py,
            ))
        logger.info(f"从 akshare 加载 {len(stocks)} 只股票")
        return stocks
    except Exception as e:
        logger.error(f"从 akshare 加载股票列表失败: {e}")
        return []


def _load_stocks() -> list[StockInfo]:
    """加载 A 股列表，优先级：mootdx > baostock > akshare > stock_data 服务"""
    stocks = []

    # 1. 首选：mootdx（通达信，TCP 7709，不封IP）
    stocks = _load_stocks_from_mootdx()
    if stocks:
        return stocks

    # 2. 备选：baostock（免费开源）
    stocks = _load_stocks_from_baostock()
    if stocks:
        return stocks

    # 3. 备选：akshare
    stocks = _load_stocks_from_akshare()
    if stocks:
        return stocks

    # 4. 最终备用：stock_data 行情服务（如果在线）
    if market_service.is_available():
        stocks_data = market_service.get_stock_list_full("沪深A股")
        if stocks_data:
            for item in stocks_data:
                name = item.get("name", "")
                py = item.get("pinyin", "")
                full_py = item.get("full_pinyin", "")
                if not py or not full_py:
                    py, full_py = _make_pinyin(name)
                stocks.append(StockInfo(
                    code=item.get("code", item.get("symbol", "").split(".")[0]),
                    name=name,
                    exchange=item.get("exchange", ""),
                    pinyin=py,
                    full_pinyin=full_py,
                ))
            logger.info(f"从行情服务加载 {len(stocks)} 只股票")
            return stocks

    logger.error("所有数据源均无法加载股票列表")
    return []


def get_stock_list() -> list[StockInfo]:
    global _stock_list
    if _stock_list is None:
        _stock_list = _load_stocks()
    return _stock_list


# ── 搜索接口 ────────────────────────────────────────────────────────────────────

@router.get("/all", response_model=list[StockInfo])
def get_all_stocks():
    """返回全量股票列表，供前端缓存"""
    return get_stock_list()


@router.get("/search", response_model=list[StockInfo])
def search_stocks(q: str = Query("", max_length=50), limit: int = 20):
    """搜索股票，支持按代码、名称、拼音首字母、全拼搜索"""
    if not q:
        return []

    q = q.strip().lower()
    stocks = get_stock_list()
    results = []

    for s in stocks:
        if (
            s.code.startswith(q)
            or q in s.name.lower()
            or s.pinyin.startswith(q)
            or q in s.full_pinyin
        ):
            results.append(s)
            if len(results) >= limit:
                break

    return results


@router.get("/lookup/{code}", response_model=StockInfo | None)
def lookup_stock(code: str):
    """根据股票代码查名称"""
    stocks = get_stock_list()
    for s in stocks:
        if s.code == code:
            return s
    return None
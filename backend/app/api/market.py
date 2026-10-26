from fastapi import APIRouter, Query, HTTPException
import logging

from app.services.market_service import market_service
from app.core.data_bridge import get_available_sources, get_data_source

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/market", tags=["行情"])

# 数据源描述信息
_SOURCE_DESCRIPTIONS = {
    "mootdx": "通达信行情服务器，TCP 二进制协议（端口 7709），永不封 IP，分钟线回测首选",
    "akshare": "东方财富数据源（akshare SDK），免费开源，数据全面，有频率限制",
    "efinance": "东方财富数据源（efinance SDK），比 akshare 更轻量稳定",
    "baostock": "证券宝数据源，免费开源，不支持 1m 分钟线",
    "sina": "新浪财经 HTTP 接口，主备双接口，频率宽容度较高",
    "tencent": "腾讯财经 HTTP 接口，仅支持日线和周线",
    "xtquant": "本地 stock_data 行情微服务，全周期支持",
}

# 降级优先级链
_MINUTE_SOURCE_ORDER = ["mootdx", "xtquant", "akshare"]
_DAILY_SOURCE_ORDER = ["tencent", "mootdx", "baostock", "sina", "akshare"]


@router.get("/data-sources")
def list_data_sources():
    """获取所有数据源的状态信息"""
    available = get_available_sources()
    available_map = {item["name"]: item["available"] for item in available}

    result = []
    for name, desc in _SOURCE_DESCRIPTIONS.items():
        priority_min = None
        priority_daily = None
        if name in _MINUTE_SOURCE_ORDER:
            priority_min = _MINUTE_SOURCE_ORDER.index(name) + 1
        if name in _DAILY_SOURCE_ORDER:
            priority_daily = _DAILY_SOURCE_ORDER.index(name) + 1

        result.append({
            "name": name,
            "available": available_map.get(name, False),
            "description": desc,
            "priority_min": priority_min,
            "priority_daily": priority_daily,
        })

    return result


@router.get("/data-sources/klines")
def get_data_source_klines(
    symbol: str = Query("600519.SH", description="股票代码，如 600519.SH"),
    period: str = Query("1d", description="周期: 1m/5m/15m/30m/1h/1d/1w"),
    start_time: str = Query("", description="开始日期 YYYY-MM-DD"),
    end_time: str = Query("", description="结束日期 YYYY-MM-DD"),
    source: str = Query("auto", description="数据源: auto/mootdx/akshare/efinance/baostock/sina/tencent/xtquant"),
    dividend_type: str = Query("front", description="复权方式: none/front/back"),
):
    """从指定数据源获取K线数据"""
    try:
        ds = get_data_source(source)
    except Exception as e:
        raise HTTPException(status_code=400, detail=f"数据源 '{source}' 不可用: {e}")

    # 日期格式转换：YYYYMMDD → YYYY-MM-DD（如果传入的是 YYYYMMDD 格式）
    if start_time and "-" not in start_time:
        start_time = f"{start_time[:4]}-{start_time[4:6]}-{start_time[6:8]}"
    if end_time and "-" not in end_time:
        end_time = f"{end_time[:4]}-{end_time[4:6]}-{end_time[6:8]}"

    try:
        df = ds.get_klines(
            symbol=symbol,
            period=period,
            start=start_time,
            end=end_time,
            dividend_type=dividend_type,
        )
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"获取K线数据失败: {e}")

    if df.empty:
        return {"symbol": symbol, "interval": period, "source": ds.get_name(), "klines": [], "count": 0}

    klines = []
    for _, row in df.iterrows():
        klines.append({
            "date": str(row["date"]),
            "open": round(float(row["open"]), 2),
            "high": round(float(row["high"]), 2),
            "low": round(float(row["low"]), 2),
            "close": round(float(row["close"]), 2),
            "volume": int(row["volume"]),
            "amount": round(float(row["amount"]), 2),
        })

    return {
        "symbol": symbol,
        "interval": period,
        "source": ds.get_name(),
        "klines": klines,
        "count": len(klines),
    }


@router.get("/symbols")
def list_symbols(
    sector: str = Query("沪深A股", description="板块名称"),
    limit: int = Query(100, description="返回数量"),
):
    """获取可用合约列表"""
    if not market_service.is_available():
        raise HTTPException(status_code=503, detail="行情数据服务不可用，请确保 stock_data 服务已启动")

    # 一次请求拿到完整数据，无需逐个查 instruments
    stocks_data = market_service.get_stock_list_full(sector)
    stocks_data = stocks_data[:limit]

    symbols = []
    for item in stocks_data:
        symbols.append({
            "symbol": item.get("symbol", ""),
            "name": item.get("name", ""),
            "exchange": item.get("exchange", ""),
        })

    return {"symbols": symbols}


@router.get("/klines")
def get_klines(
    symbol: str = Query("002202.SZ", description="股票代码，如 002202.SZ"),
    period: str = Query("5m", description="周期: 1m/5m/15m/30m/1h/1d/1w"),
    start_time: str = Query("", description="开始时间 YYYYMMDD"),
    end_time: str = Query("", description="结束时间 YYYYMMDD"),
    count: int = Query(-1, description="返回条数，-1表示全部"),
    dividend_type: str = Query("front", description="复权方式: none/front/back"),
):
    """获取K线数据"""
    if not market_service.is_available():
        raise HTTPException(status_code=503, detail="行情数据服务不可用")

    df = market_service.get_klines(
        symbol=symbol,
        period=period,
        start_time=start_time,
        end_time=end_time,
        count=count,
        dividend_type=dividend_type,
    )

    if df.empty:
        return {"symbol": symbol, "interval": period, "klines": []}

    klines = []
    for idx, row in df.iterrows():
        klines.append({
            "date": str(idx),
            "open": row.get("open", 0),
            "high": row.get("high", 0),
            "low": row.get("low", 0),
            "close": row.get("close", 0),
            "volume": int(row.get("volume", 0)),
            "amount": row.get("amount", 0),
        })

    return {"symbol": symbol, "interval": period, "klines": klines}


@router.get("/tick/{symbol}")
def get_tick(symbol: str):
    """获取最新 tick 数据"""
    if not market_service.is_available():
        raise HTTPException(status_code=503, detail="行情数据服务不可用")

    tick = market_service.get_full_tick(symbol)
    if not tick:
        raise HTTPException(status_code=404, detail=f"未找到 {symbol} 的行情数据")

    return {
        "symbol": symbol,
        "last_price": tick.get("lastPrice", 0),
        "open": tick.get("open", 0),
        "high": tick.get("high", 0),
        "low": tick.get("low", 0),
        "last_close": tick.get("lastClose", 0),
        "volume": tick.get("volume", 0),
        "amount": tick.get("amount", 0),
        "bid_prices": tick.get("bidPrice", []),
        "bid_volumes": tick.get("bidVol", []),
        "ask_prices": tick.get("askPrice", []),
        "ask_volumes": tick.get("askVol", []),
        "datetime": tick.get("timetag", ""),
    }


# ── 基本面数据接口（通过 akshare）───────────────────────────────────────────────

def _strip_suffix(symbol: str) -> str:
    """600519.SH → 600519"""
    return symbol.split(".")[0] if "." in symbol else symbol


@router.get("/financial/abstract")
def get_financial_abstract(
    symbol: str = Query("600519.SH", description="股票代码"),
):
    """获取财务摘要（同花顺）：净利润、营收、每股收益、ROE 等"""
    try:
        import akshare as ak
    except ImportError:
        raise HTTPException(status_code=503, detail="akshare 未安装")
    try:
        code = _strip_suffix(symbol)
        df = ak.stock_financial_abstract_ths(symbol=code)
        if df.empty:
            return {"symbol": symbol, "data": []}
        # 统一列名为英文
        col_map = {
            "报告期": "date", "净利润": "net_profit", "净利润同比增长率": "net_profit_yoy",
            "扣非净利润": "deducted_net_profit", "扣非净利润同比增长率": "deducted_net_profit_yoy",
            "营业总收入": "total_revenue", "营业总收入同比增长率": "total_revenue_yoy",
            "基本每股收益": "basic_eps", "每股净资产": "bps",
            "每股资本公积金": "capital_reserve_per_share", "每股未分配利润": "undistributed_profit_per_share",
            "每股经营现金流": "ocf_per_share", "销售净利率": "net_margin",
            "销售毛利率": "gross_margin", "净资产收益率": "roe",
            "净资产收益率-摊薄": "roe_diluted", "营业周期": "operating_cycle",
            "存货周转率": "inventory_turnover", "存货周转天数": "inventory_days",
            "应收账款周转天数": "ar_days", "流动比率": "current_ratio",
            "速动比率": "quick_ratio", "保守速动比率": "conservative_quick_ratio",
            "产权比率": "equity_ratio", "资产负债率": "debt_ratio",
        }
        df = df.rename(columns={k: v for k, v in col_map.items() if k in df.columns})
        records = df.to_dict(orient="records")
        return {"symbol": symbol, "data": records}
    except Exception as e:
        logger.error(f"获取财务摘要失败 {symbol}: {e}")
        raise HTTPException(status_code=500, detail=f"获取财务摘要失败: {e}")


@router.get("/financial/indicators")
def get_financial_indicators(
    symbol: str = Query("600519.SH", description="股票代码"),
    start_year: str = Query("2023", description="开始年份"),
):
    """获取财务分析指标（东方财富）：每股收益、ROE、ROA、毛利率、周转率等 86 项"""
    try:
        import akshare as ak
    except ImportError:
        raise HTTPException(status_code=503, detail="akshare 未安装")
    try:
        code = _strip_suffix(symbol)
        df = ak.stock_financial_analysis_indicator(symbol=code, start_year=start_year)
        if df.empty:
            return {"symbol": symbol, "data": [], "columns": []}
        columns = df.columns.tolist()
        records = df.fillna("").to_dict(orient="records")
        return {"symbol": symbol, "data": records, "columns": columns}
    except Exception as e:
        logger.error(f"获取财务分析指标失败 {symbol}: {e}")
        raise HTTPException(status_code=500, detail=f"获取财务分析指标失败: {e}")


@router.get("/financial/income")
def get_income_statement(
    symbol: str = Query("600519.SH", description="股票代码"),
):
    """获取利润表（新浪财经）：营业收入、营业成本、净利润等"""
    try:
        import akshare as ak
    except ImportError:
        raise HTTPException(status_code=503, detail="akshare 未安装")
    try:
        code = _strip_suffix(symbol)
        df = ak.stock_financial_report_sina(stock=code, symbol="利润表")
        if df.empty:
            return {"symbol": symbol, "data": [], "columns": []}
        columns = df.columns.tolist()
        records = df.fillna("").to_dict(orient="records")
        return {"symbol": symbol, "data": records, "columns": columns}
    except Exception as e:
        logger.error(f"获取利润表失败 {symbol}: {e}")
        raise HTTPException(status_code=500, detail=f"获取利润表失败: {e}")


@router.get("/financial/balance")
def get_balance_sheet(
    symbol: str = Query("600519.SH", description="股票代码"),
):
    """获取资产负债表（新浪财经）：货币资金、应收账款、存货、固定资产等"""
    try:
        import akshare as ak
    except ImportError:
        raise HTTPException(status_code=503, detail="akshare 未安装")
    try:
        code = _strip_suffix(symbol)
        df = ak.stock_financial_report_sina(stock=code, symbol="资产负债表")
        if df.empty:
            return {"symbol": symbol, "data": [], "columns": []}
        columns = df.columns.tolist()
        records = df.fillna("").to_dict(orient="records")
        return {"symbol": symbol, "data": records, "columns": columns}
    except Exception as e:
        logger.error(f"获取资产负债表失败 {symbol}: {e}")
        raise HTTPException(status_code=500, detail=f"获取资产负债表失败: {e}")


@router.get("/financial/cashflow")
def get_cashflow_statement(
    symbol: str = Query("600519.SH", description="股票代码"),
):
    """获取现金流量表（新浪财经）：经营/投资/筹资现金流等"""
    try:
        import akshare as ak
    except ImportError:
        raise HTTPException(status_code=503, detail="akshare 未安装")
    try:
        code = _strip_suffix(symbol)
        df = ak.stock_financial_report_sina(stock=code, symbol="现金流量表")
        if df.empty:
            return {"symbol": symbol, "data": [], "columns": []}
        columns = df.columns.tolist()
        records = df.fillna("").to_dict(orient="records")
        return {"symbol": symbol, "data": records, "columns": columns}
    except Exception as e:
        logger.error(f"获取现金流量表失败 {symbol}: {e}")
        raise HTTPException(status_code=500, detail=f"获取现金流量表失败: {e}")


@router.get("/financial/dividend")
def get_dividend_history(
    symbol: str = Query("600519.SH", description="股票代码"),
):
    """获取分红送股历史（巨潮资讯）"""
    try:
        import akshare as ak
    except ImportError:
        raise HTTPException(status_code=503, detail="akshare 未安装")
    try:
        code = _strip_suffix(symbol)
        df = ak.stock_dividend_cninfo(symbol=code)
        if df.empty:
            return {"symbol": symbol, "data": []}
        col_map = {
            "实施方案公告日期": "announce_date", "分红类型": "dividend_type",
            "送股比例": "bonus_share_ratio", "转增比例": "conversion_ratio",
            "派息比例": "cash_dividend_ratio", "股权登记日": "record_date",
            "除权日": "ex_dividend_date", "派息日": "payment_date",
            "股份到账日": "share_arrival_date", "实施方案分红说明": "description",
            "报告时间": "report_period",
        }
        df = df.rename(columns={k: v for k, v in col_map.items() if k in df.columns})
        records = df.fillna("").to_dict(orient="records")
        return {"symbol": symbol, "data": records}
    except Exception as e:
        logger.error(f"获取分红送股历史失败 {symbol}: {e}")
        raise HTTPException(status_code=500, detail=f"获取分红送股历史失败: {e}")
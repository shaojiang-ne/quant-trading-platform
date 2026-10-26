"""
股票研究数据 API

基于 a-stock-data 技术方案，直接调用东财/同花顺/腾讯/巨潮等底层 API。
"""

from fastapi import APIRouter, Query
from datetime import datetime
import logging

from app.services.stock_research_service import stock_research_service
from app.services.technical_analysis_service import technical_analysis_service

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/research", tags=["研究数据"])


@router.get("/quote")
def get_quote(codes: str = Query("600519", description="股票代码，逗号分隔")):
    """腾讯实时行情：PE/PB/市值/换手率/涨跌停等"""
    code_list = [c.strip() for c in codes.split(",") if c.strip()]
    return stock_research_service.tencent_quote(code_list)


@router.get("/concepts")
def get_concepts(code: str = Query("688017", description="股票代码")):
    """东财概念板块归属"""
    return stock_research_service.eastmoney_concept_blocks(code)


@router.get("/fund-flow")
def get_fund_flow(code: str = Query("000858", description="股票代码")):
    """分钟级资金流向（主力/大/中/小/超大户）"""
    return {"code": code, "data": stock_research_service.eastmoney_fund_flow_minute(code)}


@router.get("/fund-flow-120d")
def get_fund_flow_120d(code: str = Query("000858", description="股票代码")):
    """120日日线资金流向"""
    return {"code": code, "data": stock_research_service.stock_fund_flow_120d(code)}


@router.get("/dragon-tiger")
def get_dragon_tiger(
    code: str = Query("002475", description="股票代码"),
    date: str = Query("", description="查询日期 YYYY-MM-DD"),
):
    """个股龙虎榜+营业部席位"""
    if not date:
        date = datetime.now().strftime("%Y-%m-%d")
    return stock_research_service.dragon_tiger_board(code, date)


@router.get("/daily-dragon-tiger")
def get_daily_dragon_tiger(
    date: str = Query("", description="查询日期 YYYY-MM-DD"),
    min_net_buy: float = Query(None, description="最小净买入万元"),
):
    """全市场龙虎榜净买入排名"""
    if not date:
        date = datetime.now().strftime("%Y-%m-%d")
    return stock_research_service.daily_dragon_tiger(date, min_net_buy)


@router.get("/lockup")
def get_lockup(
    code: str = Query("688017", description="股票代码"),
    date: str = Query("", description="基准日期 YYYY-MM-DD"),
    forward_days: int = Query(90, description="向前看天数"),
):
    """限售解禁日历"""
    if not date:
        date = datetime.now().strftime("%Y-%m-%d")
    return stock_research_service.lockup_expiry(code, date, forward_days)


@router.get("/industry")
def get_industry(top_n: int = Query(20, description="返回前N个行业")):
    """行业涨幅排名"""
    return stock_research_service.industry_comparison(top_n)


@router.get("/margin")
def get_margin(code: str = Query("600519", description="股票代码")):
    """融资融券余额变化"""
    return {"code": code, "data": stock_research_service.margin_trading(code)}


@router.get("/block-trade")
def get_block_trade(code: str = Query("600519", description="股票代码")):
    """大宗交易+溢价折价率"""
    return {"code": code, "data": stock_research_service.block_trade(code)}


@router.get("/holders")
def get_holders(code: str = Query("000858", description="股票代码")):
    """股东户数变化+筹码集中度"""
    return {"code": code, "data": stock_research_service.holder_num_change(code)}


@router.get("/dividend")
def get_dividend(code: str = Query("600519", description="股票代码")):
    """分红送转历史"""
    return {"code": code, "data": stock_research_service.dividend_history(code)}


@router.get("/news")
def get_news(code: str = Query("300476", description="股票代码")):
    """个股新闻"""
    return {"code": code, "data": stock_research_service.eastmoney_stock_news(code)}


@router.get("/stock-info")
def get_stock_info(code: str = Query("688017", description="股票代码")):
    """东财基本信息：行业/股本/市值/上市日期"""
    return stock_research_service.eastmoney_stock_info(code)


@router.get("/reports")
def get_reports(code: str = Query("688017", description="股票代码")):
    """研报列表+评级+EPS预测"""
    return {"code": code, "data": stock_research_service.eastmoney_reports(code)}


@router.get("/announcements")
def get_announcements(code: str = Query("300476", description="股票代码")):
    """巨潮资讯监管公告"""
    return {"code": code, "data": stock_research_service.cninfo_announcements(code)}


@router.get("/hot-stocks")
def get_hot_stocks(date: str = Query("", description="日期 YYYY-MM-DD")):
    """同花顺热门股票+题材归因"""
    if not date:
        date = datetime.now().strftime("%Y-%m-%d")
    return {"date": date, "data": stock_research_service.ths_hot_reason(date)}


@router.get("/northbound")
def get_northbound():
    """同花顺北向资金分钟级流入流出"""
    return {"data": stock_research_service.hsgt_realtime()}


@router.get("/technical-analysis")
def get_technical_analysis(code: str = Query(..., description="股票代码")):
    """个股技术分析：趋势/震荡/波动指标 + K线形态 + 支撑阻力 + 成交量"""
    from app.core.data_bridge import data_bridge
    from datetime import datetime, timedelta

    end_date = datetime.now().strftime("%Y-%m-%d")
    start_date = (datetime.now() - timedelta(days=180)).strftime("%Y-%m-%d")

    stock_name = ""
    latest_price = 0.0
    try:
        info = stock_research_service.eastmoney_stock_info(code)
        stock_name = info.get("name", "")
    except Exception:
        pass

    try:
        df = data_bridge.load_bars_df(code, start_date, end_date, period="1d")
        if df is not None and not df.empty:
            latest_price = float(df["close"].iloc[-1])
            if not stock_name:
                try:
                    q = stock_research_service.tencent_quote([code])
                    stock_name = q.get(code, {}).get("name", "")
                except Exception:
                    pass
            result = technical_analysis_service.analyze(df)
        else:
            result = {
                "analysis": "无法获取K线数据",
                "signals": None,
            }
    except Exception as e:
        logger.error(f"技术分析数据获取失败: {e}")
        result = {
            "analysis": f"获取行情数据失败: {e}",
            "signals": None,
        }

    return {
        "code": code,
        "stock_name": stock_name,
        "latest_price": latest_price,
        "analysis": result["analysis"],
        "signals": result["signals"],
    }

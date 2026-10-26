import datetime
import json
import logging
import re
import threading
import time
from concurrent.futures import ThreadPoolExecutor, as_completed

import akshare as ak
import pandas as pd
import requests
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry
from data.interface import DataSourceInterface

logger = logging.getLogger(__name__)

# 新浪财经 HTTP 会话（参考 fetch_stock_info.py）
_SINA_SESSION = requests.Session()
_SINA_SESSION.headers.update({
    "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36",
    "Referer": "https://finance.sina.com.cn",
})
# 显式挂连接池，避免端口耗尽（与 backend 参数一致）
_SINA_RETRY = Retry(total=2, backoff_factor=0.5, status_forcelist=[502, 503, 504])
_SINA_ADAPTER = HTTPAdapter(pool_connections=20, pool_maxsize=10, max_retries=_SINA_RETRY)
_SINA_SESSION.mount("https://", _SINA_ADAPTER)
_SINA_SESSION.mount("http://", _SINA_ADAPTER)


class AKShareDataSource(DataSourceInterface):
    """AKShare数据源实现 - K线使用腾讯接口(主力)，新浪接口(fallback)"""

    def __init__(self):
        self._trading_days: set[str] | None = None
        self._spot_cache: pd.DataFrame | None = None
        self._spot_cache_time: float = 0
        self._quote_cache: dict[str, pd.DataFrame] = {}  # K线缓存（batch预加载后策略复用）
        self._sina_session = requests.Session()
        self._sina_session.headers.update({
            "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36",
            "Referer": "https://finance.sina.com.cn",
        })
        self._tencent_session = requests.Session()
        self._tencent_session.headers.update({
            "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36",
        })
        # 显式挂连接池，避免端口耗尽（与 backend 参数一致）
        _retry = Retry(total=2, backoff_factor=0.5, status_forcelist=[502, 503, 504])
        for _sess in (self._sina_session, self._tencent_session):
            _adapter = HTTPAdapter(pool_connections=20, pool_maxsize=10, max_retries=_retry)
            _sess.mount("https://", _adapter)
            _sess.mount("http://", _adapter)

    def get_stock_list(self) -> pd.DataFrame:
        """获取全市场股票列表，用新浪行情+新浪详情补充市值/PE/PB/行业/财务指标"""
        df = self._get_spot_data()
        if df.empty:
            return pd.DataFrame()

        # 基础字段映射（新浪行情已有）
        result = pd.DataFrame({
            "code": df["代码"],
            "name": df["名称"],
            "industry": "",
            "list_date": "",
            "is_st": df["名称"].str.contains("ST", case=False, na=False),
            "market_cap": 0.0,
            "amount": df["成交额"].astype(float),
            "pe": 0.0,
            "pb": 0.0,
        })

        # 用新浪 _i 接口补充详情（并发）
        codes = result["code"].tolist()
        logger.info(f"补充 {len(codes)} 只股票的详情信息...")
        detail_map = self._batch_fetch_sina_detail(codes)
        for col in ("market_cap", "pe", "pb", "industry"):
            if col not in result.columns:
                result[col] = 0.0 if col != "industry" else ""
        for code, detail in detail_map.items():
            mask = result["code"] == code
            if mask.any():
                idx = mask.idxmax()
                result.loc[idx, "market_cap"] = detail.get("market_cap", 0)
                result.loc[idx, "pe"] = detail.get("pe", 0)
                result.loc[idx, "pb"] = detail.get("pb", 0)
                result.loc[idx, "industry"] = detail.get("industry", "")

        return result

    def _safe_float(self, s, default: float = 0) -> float:
        """安全转换为浮点数"""
        try:
            return float(s)
        except (ValueError, TypeError):
            return default

    def _fetch_sina_detail(self, code: str) -> dict:
        """从新浪财经 API 获取单只股票详情
        参考 fetch_stock_info.py 的网络请求方式和字段解析
        code 格式: 带市场前缀如 sz000737, sh600519, bj920001

        _i 详细字段:
          0=股票类型(A), 1=拼音缩写, 2=每股收益-本报告期, 3=每股收益-上年同期
          4=每股收益-扣除后, 5=每股净资产, 7=总股本(万股)
          12=净利润-本报告期(亿元), 13=净利润-年初至报告期(亿元)
          14=净利润同比增长率(%), 16=每股净资产-最新(元)
          17=营业收入(亿元), 18=归母净利润(亿元)
          19=营业收入同比增长率(%), 20=营业利润同比增长率(%)
          34=行业板块(申万), 37=总市值(元)
          39=财务数据子字段(管道分隔)
        """
        try:
            url = f"https://hq.sinajs.cn/list={code},{code}_i"
            resp = _SINA_SESSION.get(url, timeout=10)
            resp.encoding = "gbk"
            text = resp.text

            basic_match = re.search(r'hq_str_' + re.escape(code) + r'="([^"]*)"', text)
            detail_match = re.search(r'hq_str_' + re.escape(code) + r'_i="([^"]*)"', text)

            if not basic_match:
                return {}

            basic = basic_match.group(1).split(",")
            detail = detail_match.group(1).split(",") if detail_match else []

            # 基础行情: 0=名称, 1=今开, 2=昨收, 3=当前价, 4=最高, 5=最低, 8=成交量, 9=成交额
            price = self._safe_float(basic[3]) if len(basic) > 3 else 0
            prev_close = self._safe_float(basic[2]) if len(basic) > 2 else 0

            # _i 字段解析
            sf = self._safe_float
            eps = sf(detail[2])            # 每股收益-本报告期
            eps_yoy = sf(detail[3])        # 每股收益-上年同期
            eps_deducted = sf(detail[4])   # 每股收益-扣除后
            bvps = sf(detail[5])           # 每股净资产
            totalcapital = sf(detail[7])   # 总股本(万股)
            profit_report = sf(detail[12]) # 净利润-本报告期(亿元)
            profit_ytd = sf(detail[13])    # 净利润-年初至报告期(亿元)
            profit_yoy = sf(detail[14])    # 净利润同比增长率(%)
            bvps_latest = sf(detail[16])   # 每股净资产-最新
            revenue = sf(detail[17])       # 营业收入(亿元)
            net_profit = sf(detail[18])    # 归母净利润(亿元)
            revenue_yoy = sf(detail[19])   # 营业收入同比增长率(%)
            industry = detail[34] if len(detail) > 34 else ""

            # field 39 子字段: 报告期|归母净利润|扣非净利润|营业收入|营业成本|总资产|每股净资产|每股收益|...
            f39 = detail[39].split("|") if len(detail) > 39 else []
            report_date = f39[0] if len(f39) > 0 else ""
            deducted_net_profit = sf(f39[2])  # 扣非净利润(元)
            operating_cost = sf(f39[4])       # 营业成本(元)
            total_assets = sf(f39[5])         # 总资产(元)

            # 计算指标
            # 市值: 优先用 价格×总股本 计算(最可靠)，回退到 detail[37]
            if price and totalcapital:
                total_market_cap = price * totalcapital * 10000  # 元
            else:
                total_market_cap = sf(detail[37]) * 1000 if len(detail) > 37 else 0  # 千元→元

            # 市盈率: 优先用 price/eps，回退到市值/净利润
            pe = price / eps if price and eps else 0
            if pe <= 0 and total_market_cap and profit_ytd:
                pe = total_market_cap / (profit_ytd * 1e8)

            # 市净率: 优先用 price/bvps，回退到 price/bvps_latest
            pb = price / bvps if price and bvps else 0
            if pb <= 0 and price and bvps_latest:
                pb = price / bvps_latest

            return {
                "market_cap": total_market_cap / 1e8,  # 元→亿元
                "pe": pe,
                "pb": pb,
                "industry": industry,
                "eps": eps,
                "eps_yoy": eps_yoy,
                "eps_deducted": eps_deducted,
                "bvps": bvps,
                "totalcapital": totalcapital,       # 万股
                "profit_report": profit_report,      # 亿元
                "profit_ytd": profit_ytd,            # 亿元
                "profit_yoy": profit_yoy,            # %
                "revenue": revenue,                  # 亿元
                "net_profit": net_profit,            # 亿元
                "revenue_yoy": revenue_yoy,          # %
                "total_assets": total_assets / 1e8 if total_assets else 0,  # 亿元
                "deducted_net_profit": deducted_net_profit / 1e8 if deducted_net_profit else 0,  # 亿元
                "operating_cost": operating_cost / 1e8 if operating_cost else 0,  # 亿元
                "report_date": report_date,
            }
        except Exception as e:
            logger.debug(f"获取 {code} 新浪详情失败: {e}")
            return {}

    def _batch_fetch_sina_detail(self, codes: list[str]) -> dict[str, dict]:
        """并发获取多只股票的新浪详情"""
        result = {}
        with ThreadPoolExecutor(max_workers=10) as executor:
            futures = {executor.submit(self._fetch_sina_detail, code): code for code in codes}
            done_count = 0
            for future in as_completed(futures):
                done_count += 1
                code = futures[future]
                try:
                    detail = future.result()
                    if detail:
                        result[code] = detail
                except Exception as e:
                    logger.debug(f"{code} 详情获取异常: {e}")
                if done_count % 100 == 0:
                    logger.info(f"详情补充进度: {done_count}/{len(codes)}")
        logger.info(f"详情补充完成: {len(result)}/{len(codes)} 只成功")
        return result

    def get_stock_basic(self, code: str) -> pd.DataFrame:
        """获取个股基本面数据，使用新浪 _i 接口
        返回: code, market_cap, pe, pb, total_shares, float_shares,
              industry, list_date, eps, eps_yoy, revenue, net_profit,
              profit_yoy, revenue_yoy, total_assets, report_date
        """
        detail = self._fetch_sina_detail(code)
        list_date = self._fetch_list_date(code)

        return pd.DataFrame({
            "code": [code],
            "market_cap": [detail.get("market_cap", 0)],
            "pe": [detail.get("pe", 0)],
            "pb": [detail.get("pb", 0)],
            "total_shares": [detail.get("totalcapital", 0) * 1e4],  # 万股→股
            "float_shares": [0],
            "industry": [detail.get("industry", "")],
            "list_date": [list_date],
            "eps": [detail.get("eps", 0)],
            "eps_yoy": [detail.get("eps_yoy", 0)],
            "revenue": [detail.get("revenue", 0)],
            "net_profit": [detail.get("net_profit", 0)],
            "profit_yoy": [detail.get("profit_yoy", 0)],
            "revenue_yoy": [detail.get("revenue_yoy", 0)],
            "total_assets": [detail.get("total_assets", 0)],
            "report_date": [detail.get("report_date", "")],
        })

    def _fetch_list_date(self, code: str) -> str:
        """从新浪公司信息页获取上市日期
        参考 fetch_stock_info.py 的上市日期获取方式
        code 格式: 带市场前缀如 sz000737
        """
        try:
            stockid = code[2:]  # sz000737 → 000737
            corp_url = f"https://vip.stock.finance.sina.com.cn/corp/go.php/vCI_CorpInfo/stockid/{stockid}.phtml"
            resp = _SINA_SESSION.get(corp_url, timeout=10)
            resp.encoding = "gbk"
            m = re.search(r'上市日期.*?(\d{4}-\d{2}-\d{2})', resp.text, re.DOTALL)
            if m:
                return m.group(1)
        except Exception:
            pass
        return ""

    def get_daily_quote(self, code: str, days: int = 60) -> pd.DataFrame:
        """获取日K线 - 优先从预加载缓存取，否则腾讯→新浪依次尝试"""
        if code in self._quote_cache:
            return self._quote_cache[code]
        df = self._fetch_daily_quote_tencent(code, days)
        if df.empty:
            df = self._fetch_daily_quote_sina(code, days)
        return df

    def batch_get_daily_quotes(self, codes: list[str], days: int = 60) -> dict[str, pd.DataFrame]:
        """并发获取多只股票日K线（腾讯主力+新浪fallback），带限速控制"""
        self._quote_cache.clear()
        result = {}
        lock = threading.Lock()
        total = len(codes)
        success = 0
        fail = 0
        max_workers = 5   # 腾讯接口并发5无压力
        request_delay = 0.05  # 腾讯50ms间隔即可

        def fetch_with_delay(code: str) -> tuple[str, pd.DataFrame]:
            nonlocal success, fail
            with lock:
                time.sleep(request_delay)
            # 先腾讯，失败再新浪
            df = self._fetch_daily_quote_tencent(code, days)
            if df.empty:
                df = self._fetch_daily_quote_sina(code, days)
            with lock:
                if df.empty:
                    fail += 1
                else:
                    success += 1
                done = success + fail
                if done % 200 == 0 or done == total:
                    logger.info(f"K线获取进度: {done}/{total} (成功{success}, 失败{fail})")
            return code, df

        with ThreadPoolExecutor(max_workers=max_workers) as pool:
            futures = {pool.submit(fetch_with_delay, code): code for code in codes}
            for future in as_completed(futures):
                code, df = future.result()
                result[code] = df
                if not df.empty:
                    self._quote_cache[code] = df

        logger.info(f"K线批量获取完成: 成功{success}/{total}, 失败{fail}")
        return result

    # ─── 新浪K线接口 ──────────────────────────────────────

    @staticmethod
    def _code_to_sina_symbol(code: str) -> str:
        """将股票代码转换为新浪K线接口的symbol格式
        例: 000001 -> sz000001, 600519 -> sh600519, sz000001 -> sz000001
        """
        pure = code[2:] if len(code) > 6 else code
        if pure.startswith(("6",)):
            return f"sh{pure}"
        else:
            return f"sz{pure}"

    # ─────────── K线数据获取（腾讯主力 + 新浪fallback） ───────────

    @staticmethod
    def _code_to_tencent_symbol(code: str) -> str:
        """将股票代码转为腾讯格式 sh/sz+6位"""
        code = code.strip()
        if code.startswith(("sh", "sz")):
            return code
        return f"sh{code}" if code.startswith("6") else f"sz{code}"

    def _fetch_daily_quote_tencent(self, code: str, days: int = 60) -> pd.DataFrame:
        """通过腾讯K线接口获取日K线数据（主力源）
        接口: web.ifzq.gtimg.cn 前复权日K
        返回: [日期, 开盘, 收盘, 最高, 最低, 成交量]
        """
        empty = pd.DataFrame(columns=["date", "open", "high", "low", "close", "volume", "amount", "turnover"])
        try:
            symbol = self._code_to_tencent_symbol(code)
            url = f"http://web.ifzq.gtimg.cn/appstock/app/fqkline/get?param={symbol},day,,,{days},qfq"
            resp = self._tencent_session.get(url, timeout=10)
            data = resp.json()
            stock_data = data.get("data", {}).get(symbol, {})
            # 腾讯返回 qfqday(前复权) 或 day(不复权)
            raw = stock_data.get("qfqday", stock_data.get("day", []))
            if not raw:
                return empty
            rows = []
            for item in raw:
                # 格式: ["2025-01-02", "1500.00", "1520.00", "1530.00", "1490.00", "123456.00"]
                rows.append({
                    "date": pd.Timestamp(item[0]).date(),
                    "open": float(item[1]),
                    "close": float(item[2]),
                    "high": float(item[3]),
                    "low": float(item[4]),
                    "volume": float(item[5]) if len(item) > 5 else 0.0,
                })
            df = pd.DataFrame(rows)
            return pd.DataFrame({
                "date": df["date"],
                "open": df["open"],
                "high": df["high"],
                "low": df["low"],
                "close": df["close"],
                "volume": df["volume"],
                "amount": 0.0,
                "turnover": 0.0,
            })
        except Exception as e:
            logger.warning(f"腾讯K线 {code} 获取失败: {e}")
            return empty

    def _fetch_daily_quote_sina(self, code: str, days: int = 60) -> pd.DataFrame:
        """通过新浪K线接口获取单只股票日K线数据
        接口: quotes.sina.cn/CN_MarketDataService.getKLineData
        返回字段: day, open, high, low, close, volume（无成交额和换手率）
        """
        max_retries = 2
        for attempt in range(max_retries + 1):
            try:
                symbol = self._code_to_sina_symbol(code)
                url = (
                    f"https://quotes.sina.cn/cn/api/jsonp_v2.php"
                    f"/var%20_={int(time.time()*1000)}/CN_MarketDataService.getKLineData"
                    f"?symbol={symbol}&scale=240&ma=no&datalen={days}"
                )
                resp = self._sina_session.get(url, timeout=10)
                # 检测新浪反爬拦截页面
                if "location.href" in resp.text or "sina.com" in resp.text[:200]:
                    if attempt < max_retries:
                        time.sleep(1.0 * (attempt + 1))  # 递增等待后重试
                        continue
                    logger.warning(f"新浪K线 {code} 被反爬拦截，重试{max_retries}次后仍失败")
                    return pd.DataFrame(columns=["date", "open", "high", "low", "close", "volume", "amount", "turnover"])
                m = re.search(r"\((\[.*\])\)", resp.text, re.DOTALL)
                if not m:
                    if attempt < max_retries:
                        time.sleep(0.5 * (attempt + 1))
                        continue
                    logger.warning(f"新浪K线 {code} 返回格式异常: {resp.text[:100]}")
                    return pd.DataFrame(columns=["date", "open", "high", "low", "close", "volume", "amount", "turnover"])
                data = json.loads(m.group(1))
                if not data:
                    return pd.DataFrame(columns=["date", "open", "high", "low", "close", "volume", "amount", "turnover"])
                df = pd.DataFrame(data)
                return pd.DataFrame({
                    "date": pd.to_datetime(df["day"]).dt.date,
                    "open": df["open"].astype(float),
                    "high": df["high"].astype(float),
                    "low": df["low"].astype(float),
                    "close": df["close"].astype(float),
                    "volume": df["volume"].astype(float),
                    "amount": 0.0,       # 新浪K线不提供成交额，用0占位
                    "turnover": 0.0,     # 新浪K线不提供换手率，用0占位
                })
            except Exception as e:
                if attempt < max_retries:
                    time.sleep(0.5 * (attempt + 1))
                    continue
                logger.warning(f"新浪K线 {code} 获取失败: {e}")
                return pd.DataFrame(columns=["date", "open", "high", "low", "close", "volume", "amount", "turnover"])
        return pd.DataFrame(columns=["date", "open", "high", "low", "close", "volume", "amount", "turnover"])

    def get_realtime_quote(self, codes: list[str]) -> pd.DataFrame:
        df = self._get_spot_data()
        filtered = df[df["代码"].isin(codes)]
        return pd.DataFrame({
            "code": filtered["代码"],
            "name": filtered["名称"],
            "price": filtered["最新价"].astype(float),
            "change_pct": filtered["涨跌幅"].astype(float),
            "volume": filtered["成交量"].astype(float),
            "amount": filtered["成交额"].astype(float),
        })

    def get_money_flow(self, code: str, days: int = 10) -> pd.DataFrame:
        symbol = code[2:] if len(code) > 6 else code
        market = "sz" if symbol[:2] in ("00", "30") else "sh"
        try:
            df = ak.stock_individual_fund_flow(stock=symbol, market=market)
            df = df.tail(days)
            return pd.DataFrame({
                "date": pd.to_datetime(df["日期"]),
                "net_inflow": df["主力净流入-净额"].astype(float),
                "main_inflow": df["超大单净流入-净额"].astype(float),
                "main_outflow": df["大单净流入-净额"].astype(float),
            })
        except Exception as e:
            logger.warning(f"获取 {code} 资金流向失败: {e}")
            return pd.DataFrame(columns=["date", "net_inflow", "main_inflow", "main_outflow"])

    def is_trading_day(self) -> bool:
        trading_days = self._get_trading_days()
        today = datetime.date.today().strftime("%Y-%m-%d")
        if trading_days:
            return today in trading_days
        return datetime.date.today().weekday() < 5

    def is_trading_time(self) -> bool:
        if not self.is_trading_day():
            return False
        now = datetime.datetime.now().time()
        morning = datetime.time(9, 30) <= now <= datetime.time(11, 30)
        afternoon = datetime.time(13, 0) <= now <= datetime.time(15, 0)
        return morning or afternoon

    def get_industry_map(self) -> dict[str, str]:
        """从 get_stock_list() 提取行业映射（已通过新浪 _i 接口获取行业）"""
        df = self.get_stock_list()
        if df.empty or "industry" not in df.columns:
            return {}
        industry_map = {}
        for _, row in df.iterrows():
            ind = row.get("industry", "")
            if ind:
                industry_map[row["code"]] = ind
        logger.info(f"行业映射: {len(industry_map)} 只股票有行业信息")
        return industry_map

    def _get_trading_days(self) -> set[str]:
        if self._trading_days is None:
            try:
                df = ak.tool_trade_date_hist_sina()
                self._trading_days = set(df["trade_date"].astype(str))
            except Exception as e:
                logger.warning(f"获取交易日历失败: {e}，使用工作日判断")
                self._trading_days = None
        return self._trading_days if self._trading_days is not None else set()

    def _get_spot_data(self) -> pd.DataFrame:
        """获取新浪全市场行情（仅新浪，不再使用EM）"""
        import time
        now = time.time()
        if self._spot_cache is None or (now - self._spot_cache_time) > 60:
            try:
                df = ak.stock_zh_a_spot()
                self._spot_cache = df
                self._spot_cache_time = now
                return self._spot_cache
            except Exception as e:
                logger.warning(f"新浪行情接口失败: {e}")

            # 全部失败
            logger.error("行情接口失败")
            if self._spot_cache is None:
                self._spot_cache = pd.DataFrame()
        return self._spot_cache
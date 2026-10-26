"""
股票研究数据服务

基于 a-stock-data 技术方案，直接调用东财/同花顺/腾讯/巨潮等底层 HTTP API，
不走 akshare 中间层，减少故障点。

数据源优先级（按封IP风险排序）：
1. mootdx (通达信 TCP) — 永不封IP
2. 腾讯财经 HTTP — 永不封IP
3. 同花顺 HTTP — 极低风险
4. 东财 datacenter/push2 HTTP — 中等风险（em_get 限流）
5. 巨潮资讯 HTTP — 低风险
"""

import json
import logging
import random
import re
import socket
import time
from datetime import datetime, timedelta
from pathlib import Path
from typing import Optional

import pandas as pd
import requests
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry

logger = logging.getLogger(__name__)

# ── 通用常量 ──────────────────────────────────────────────────────────────────
UA = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"
DATACENTER_URL = "https://datacenter-web.eastmoney.com/api/data/v1/get"

# ── 东财限流 ──────────────────────────────────────────────────────────────────
EM_SESSION = requests.Session()
EM_SESSION.headers.update({"User-Agent": UA})
# 显式挂载连接池，避免端口耗尽
_retry = Retry(total=2, backoff_factor=0.5, status_forcelist=[502, 503, 504])
_adapter = HTTPAdapter(pool_connections=20, pool_maxsize=10, max_retries=_retry)
EM_SESSION.mount("https://", _adapter)
EM_SESSION.mount("http://", _adapter)
EM_MIN_INTERVAL = 1.0
_em_last_call = [0.0]

# ── 通用 HTTP Session（巨潮/同花顺/腾讯等，连接复用避免端口耗尽）───────────────
_GENERIC_SESSION = requests.Session()
_GENERIC_SESSION.headers.update({"User-Agent": UA})
_adapter2 = HTTPAdapter(pool_connections=20, pool_maxsize=10, max_retries=_retry)
_GENERIC_SESSION.mount("https://", _adapter2)
_GENERIC_SESSION.mount("http://", _adapter2)


def em_get(url: str, params: dict | None = None, headers: dict | None = None,
           timeout: int = 15, **kwargs):
    """东财统一限流请求：间隔 ≥1s + 随机抖动"""
    wait = EM_MIN_INTERVAL - (time.time() - _em_last_call[0])
    if wait > 0:
        time.sleep(wait + random.uniform(0.1, 0.5))
    try:
        return EM_SESSION.get(url, params=params, headers=headers, timeout=timeout, **kwargs)
    finally:
        _em_last_call[0] = time.time()


def eastmoney_datacenter(report_name: str, columns: str = "ALL",
                         filter_str: str = "", page_size: int = 50,
                         sort_columns: str = "", sort_types: str = "-1") -> list[dict]:
    """东财 datacenter-web 通用查询"""
    params = {
        "reportName": report_name, "columns": columns,
        "filter": filter_str, "pageNumber": "1", "pageSize": str(page_size),
        "sortColumns": sort_columns, "sortTypes": sort_types,
        "source": "WEB", "client": "WEB",
    }
    try:
        r = em_get(DATACENTER_URL, params=params, timeout=15)
        d = r.json()
        if d.get("result") and d["result"].get("data"):
            return d["result"]["data"]
    except Exception as e:
        logger.error(f"eastmoney_datacenter 请求失败: {e}")
    return []


def get_prefix(code: str) -> str:
    """纯代码 → 前缀: 600xxx→sh, 000/300xxx→sz, 8/4xx→bj"""
    if code.startswith(("6", "9")):
        return "sh"
    elif code.startswith("8"):
        return "bj"
    return "sz"


def strip_suffix(symbol: str) -> str:
    """600519.SH → 600519"""
    return symbol.split(".")[0] if "." in symbol else symbol


# ── 巨潮 orgId 映射 ──────────────────────────────────────────────────────────
_CNINFO_ORGID_MAP: dict[str, str] = {}


def _cninfo_orgid(code: str) -> str:
    global _CNINFO_ORGID_MAP
    if not _CNINFO_ORGID_MAP:
        try:
            r = _GENERIC_SESSION.get("http://www.cninfo.com.cn/new/data/szse_stock.json",
                             timeout=15)
            _CNINFO_ORGID_MAP = {s["code"]: s["orgId"]
                                 for s in r.json().get("stockList", [])}
        except Exception as e:
            logger.warning(f"巨潮 orgId 映射拉取失败: {e}")
    org = _CNINFO_ORGID_MAP.get(code)
    if org:
        return org
    if code.startswith("6"):
        return f"gssh0{code}"
    elif code.startswith("8") or code.startswith("4"):
        return f"gsbj0{code}"
    return f"gssz0{code}"


def _cninfo_ts_to_date(ts) -> str:
    if isinstance(ts, (int, float)):
        return datetime.fromtimestamp(ts / 1000).strftime("%Y-%m-%d")
    return str(ts)[:10] if ts else ""


# ── StockResearchService ────────────────────────────────────────────────────

class StockResearchService:
    """股票研究数据服务"""

    # ── 1. 腾讯财经实时行情 ─────────────────────────────────────────────────
    def tencent_quote(self, codes: list[str]) -> dict[str, dict]:
        """批量获取 PE/PB/市值/换手率/涨跌停等实时行情"""
        prefixed = [f"{get_prefix(c)}{c}" for c in codes]
        url = "https://qt.gtimg.cn/q=" + ",".join(prefixed)
        try:
            resp = _GENERIC_SESSION.get(url, timeout=10)
            resp.encoding = "gbk"
            data = resp.text
        except Exception as e:
            logger.error(f"腾讯行情请求失败: {e}")
            return {}

        result = {}
        for line in data.strip().split(";"):
            if not line.strip() or "=" not in line or '"' not in line:
                continue
            key = line.split("=")[0].split("_")[-1]
            vals = line.split('"')[1].split("~")
            if len(vals) < 53:
                continue
            code = key[2:]
            try:
                result[code] = {
                    "name": vals[1],
                    "price": float(vals[3]) if vals[3] else 0,
                    "last_close": float(vals[4]) if vals[4] else 0,
                    "open": float(vals[5]) if vals[5] else 0,
                    "change_amt": float(vals[31]) if vals[31] else 0,
                    "change_pct": float(vals[32]) if vals[32] else 0,
                    "high": float(vals[33]) if vals[33] else 0,
                    "low": float(vals[34]) if vals[34] else 0,
                    "amount_wan": float(vals[37]) if vals[37] else 0,
                    "turnover_pct": float(vals[38]) if vals[38] else 0,
                    "pe_ttm": float(vals[39]) if vals[39] else 0,
                    "amplitude_pct": float(vals[43]) if vals[43] else 0,
                    "mcap_yi": float(vals[44]) if vals[44] else 0,
                    "float_mcap_yi": float(vals[45]) if vals[45] else 0,
                    "pb": float(vals[46]) if vals[46] else 0,
                    "limit_up": float(vals[47]) if vals[47] else 0,
                    "limit_down": float(vals[48]) if vals[48] else 0,
                    "vol_ratio": float(vals[49]) if vals[49] else 0,
                    "pe_static": float(vals[52]) if vals[52] else 0,
                }
            except (ValueError, IndexError):
                continue
        return result

    # ── 2. 东财概念板块归属 ─────────────────────────────────────────────────
    def eastmoney_concept_blocks(self, code: str) -> dict:
        market_code = 1 if code.startswith("6") else 0
        params = {
            "fltt": "2", "invt": "2",
            "secid": f"{market_code}.{code}",
            "spt": "3", "pi": "0", "pz": "200", "po": "1",
            "fields": "f12,f14,f3,f128",
        }
        headers = {"User-Agent": UA, "Referer": "https://quote.eastmoney.com/"}
        try:
            r = em_get("https://push2.eastmoney.com/api/qt/slist/get",
                       params=params, headers=headers, timeout=15)
            d = r.json()
        except Exception as e:
            logger.error(f"东财板块归属请求失败: {e}")
            return {"total": 0, "boards": [], "concept_tags": []}

        diff = (d.get("data") or {}).get("diff") or {}
        items = diff.values() if isinstance(diff, dict) else diff
        boards = []
        for it in items:
            boards.append({
                "name": it.get("f14", ""),
                "code": it.get("f12", ""),
                "change_pct": it.get("f3", ""),
                "lead_stock": it.get("f128", ""),
            })
        return {
            "total": len(boards),
            "boards": boards,
            "concept_tags": [b["name"] for b in boards],
        }

    # ── 3. 东财分钟级资金流 ─────────────────────────────────────────────────
    def eastmoney_fund_flow_minute(self, code: str) -> list[dict]:
        """分钟资金流。优先 push2（按单笔分类的主力/大/中/小/超大净额），
        push2 在本机不可达时 fallback 到腾讯分钟量价近似（仅 main_net 有意义）。"""
        secid = f"1.{code}" if code.startswith("6") else f"0.{code}"
        url = "https://push2.eastmoney.com/api/qt/stock/fflow/kline/get"
        params = {
            "secid": secid, "klt": 1,
            "fields1": "f1,f2,f3,f7",
            "fields2": "f51,f52,f53,f54,f55,f56,f57",
        }
        headers = {
            "User-Agent": UA,
            "Referer": "https://quote.eastmoney.com/",
            "Origin": "https://quote.eastmoney.com",
        }
        try:
            r = em_get(url, params=params, headers=headers, timeout=10)
            d = r.json()
        except Exception as e:
            logger.warning(f"push2 资金流不可达，fallback 腾讯量价近似: {e}")
            return self._tencent_fund_flow_approx(code)

        rows = []
        for line in d.get("data", {}).get("klines", []):
            parts = line.split(",")
            if len(parts) >= 6:
                rows.append({
                    "time": parts[0],
                    "main_net": float(parts[1]) if parts[1] != "-" else 0,
                    "small_net": float(parts[2]) if parts[2] != "-" else 0,
                    "mid_net": float(parts[3]) if parts[3] != "-" else 0,
                    "large_net": float(parts[4]) if parts[4] != "-" else 0,
                    "super_net": float(parts[5]) if parts[5] != "-" else 0,
                    "source": "eastmoney_push2",
                })
        return rows

    def _tencent_fund_flow_approx(self, code: str) -> list[dict]:
        """腾讯 minute 量价近似的"主力净流入"。

        数据源: web.ifzq.gtimg.cn/appstock/app/day/query 返回最近 5 个交易日全天分钟数据，
        每条 entry 含 240 条分钟行（09:30~11:30 + 13:00~15:00），格式 time price cum_vol cum_amt。

        近似逻辑（与东财 fflow 的"主力净额"非完全等价，仅作量级参考）：
          - 每分钟成交额 delta = cum_amt[i] - cum_amt[i-1]
          - 如果该分钟收盘价 > 上一分钟收盘价（资金推动上涨），delta 视为"净流入"；
            否则视为"净流出"
          - main_net 返回**单笔**值（万元），与 push2 f51 字段语义一致
            （每分钟"当时净额"，不是累计），前端/LLM 沿用现有逻辑即可
        """
        # 深圳 sz / 上海 sh 前缀
        prefix = "sz" if code.startswith(("0", "3")) else "sh"
        symbol = f"{prefix}{code}"
        url = "https://web.ifzq.gtimg.cn/appstock/app/day/query"
        try:
            r = _GENERIC_SESSION.get(url, params={"code": symbol}, timeout=10)
            d = r.json()
        except Exception as e:
            logger.error(f"腾讯量价分钟拉取失败: {e}")
            return []

        entries = d.get("data", {}).get(symbol, {}).get("data", []) or []
        if not entries:
            logger.error(f"腾讯 day/query 返回空: {symbol}")
            return []

        # 取最近一个交易日
        today = entries[0]
        lines = today.get("data", []) or []
        if not lines:
            return []

        # 解析累计 amount
        parsed = []
        for line in lines:
            parts = line.split()
            if len(parts) < 4:
                continue
            try:
                parsed.append({
                    "time": parts[0],
                    "price": float(parts[1]),
                    "cum_amount": float(parts[3]),  # 元
                })
            except (ValueError, IndexError):
                continue

        rows = []
        prev_amount = 0.0
        prev_price = None
        for p in parsed:
            delta_amount = p["cum_amount"] - prev_amount  # 元
            # 价格方向：close 涨 -> 资金流入；跌 -> 流出
            sign = 1.0
            if prev_price is not None:
                if p["price"] < prev_price:
                    sign = -1.0
            elif delta_amount < 0:
                sign = -1.0  # 首分钟没 prev，按 delta 方向
            main_wan = round((delta_amount * sign) / 10000.0, 2)  # 单笔万元
            rows.append({
                "time": p["time"],
                "main_net": main_wan,
                "small_net": 0.0,
                "mid_net": 0.0,
                "large_net": 0.0,
                "super_net": 0.0,
                "source": "tencent_approx",
            })
            prev_amount = p["cum_amount"]
            prev_price = p["price"]

        return rows

    # ── 4. 120日日线资金流 ──────────────────────────────────────────────────
    def stock_fund_flow_120d(self, code: str) -> list[dict]:
        market_code = 1 if code.startswith("6") else 0
        url = "https://push2his.eastmoney.com/api/qt/stock/fflow/daykline/get"
        params = {
            "secid": f"{market_code}.{code}",
            "fields1": "f1,f2,f3,f7",
            "fields2": "f51,f52,f53,f54,f55,f56,f57,f58,f59,f60,f61,f62,f63,f64,f65",
            "lmt": "120",
        }
        headers = {
            "User-Agent": UA,
            "Referer": "https://quote.eastmoney.com/",
            "Origin": "https://quote.eastmoney.com",
        }
        try:
            r = em_get(url, params=params, headers=headers, timeout=15)
            d = r.json()
        except Exception as e:
            logger.error(f"push2 日线资金流请求失败: {e}")
            return []
        rows = []
        for line in d.get("data", {}).get("klines", []):
            parts = line.split(",")
            if len(parts) >= 7:
                rows.append({
                    "date": parts[0],
                    "main_net": float(parts[1]) if parts[1] != "-" else 0,
                    "small_net": float(parts[2]) if parts[2] != "-" else 0,
                    "mid_net": float(parts[3]) if parts[3] != "-" else 0,
                    "large_net": float(parts[4]) if parts[4] != "-" else 0,
                    "super_net": float(parts[5]) if parts[5] != "-" else 0,
                })
        return rows

    # ── 5. 个股龙虎榜 ──────────────────────────────────────────────────────
    def dragon_tiger_board(self, code: str, trade_date: str, look_back: int = 30) -> dict:
        start = datetime.strptime(trade_date, "%Y-%m-%d") - timedelta(days=look_back)
        start_str = start.strftime("%Y-%m-%d")

        records = []
        data = eastmoney_datacenter(
            "RPT_DAILYBILLBOARD_DETAILSNEW",
            filter_str=f"(TRADE_DATE>='{start_str}')(TRADE_DATE<='{trade_date}')(SECURITY_CODE=\"{code}\")",
            page_size=50, sort_columns="TRADE_DATE", sort_types="-1",
        )
        for row in data:
            records.append({
                "date": str(row.get("TRADE_DATE", ""))[:10],
                "reason": row.get("EXPLANATION", ""),
                "net_buy": round((row.get("BILLBOARD_NET_AMT") or 0) / 10000, 1),
                "turnover": round(float(row.get("TURNOVERRATE") or 0), 2),
            })

        seats = {"buy": [], "sell": []}
        buy_data = []
        sell_data = []
        if records:
            latest_date = records[0]["date"]
            buy_data = eastmoney_datacenter(
                "RPT_BILLBOARD_DAILYDETAILSBUY",
                filter_str=f"(TRADE_DATE='{latest_date}')(SECURITY_CODE=\"{code}\")",
                page_size=10, sort_columns="BUY", sort_types="-1",
            )
            for row in buy_data[:5]:
                seats["buy"].append({
                    "name": row.get("OPERATEDEPT_NAME", ""),
                    "buy_amt": round((row.get("BUY") or 0) / 10000, 1),
                    "sell_amt": round((row.get("SELL") or 0) / 10000, 1),
                    "net": round((row.get("NET") or 0) / 10000, 1),
                })
            sell_data = eastmoney_datacenter(
                "RPT_BILLBOARD_DAILYDETAILSSELL",
                filter_str=f"(TRADE_DATE='{latest_date}')(SECURITY_CODE=\"{code}\")",
                page_size=10, sort_columns="SELL", sort_types="-1",
            )
            for row in sell_data[:5]:
                seats["sell"].append({
                    "name": row.get("OPERATEDEPT_NAME", ""),
                    "buy_amt": round((row.get("BUY") or 0) / 10000, 1),
                    "sell_amt": round((row.get("SELL") or 0) / 10000, 1),
                    "net": round((row.get("NET") or 0) / 10000, 1),
                })

        institution = {"buy_amt": 0, "sell_amt": 0, "net_amt": 0}
        for detail_data, side in [(buy_data, "buy"), (sell_data, "sell")]:
            for row in detail_data:
                if str(row.get("OPERATEDEPT_CODE", "")) == "0":
                    amt = (row.get("BUY") or 0) if side == "buy" else (row.get("SELL") or 0)
                    if side == "buy":
                        institution["buy_amt"] += amt
                    else:
                        institution["sell_amt"] += amt
        institution["buy_amt"] = round(institution["buy_amt"] / 10000, 1)
        institution["sell_amt"] = round(institution["sell_amt"] / 10000, 1)
        institution["net_amt"] = round(institution["buy_amt"] - institution["sell_amt"], 1)

        return {
            "records": records,
            "seats": seats,
            "institution": institution,
            # records 为空时给前端/LLM 一个明确提示，避免被误读为"席位为空"
            "message": "" if records else f"{code} 近 {look_back} 天未上龙虎榜",
        }

    # ── 6. 全市场龙虎榜 ────────────────────────────────────────────────────
    def daily_dragon_tiger(self, trade_date: str = None, min_net_buy: float = None) -> dict:
        if trade_date is None:
            trade_date = datetime.now().strftime("%Y-%m-%d")

        data = eastmoney_datacenter(
            "RPT_DAILYBILLBOARD_DETAILSNEW",
            filter_str=f"(TRADE_DATE>='{trade_date}')(TRADE_DATE<='{trade_date}')",
            page_size=500, sort_columns="BILLBOARD_NET_AMT", sort_types="-1",
        )
        if not data:
            return {"date": trade_date, "total_records": 0, "stocks": [],
                    "note": "无数据（非交易日或盘后未更新）"}

        actual_date = str(data[0].get("TRADE_DATE", ""))[:10] if data else trade_date
        stocks = []
        for row in data:
            net_buy = (row.get("BILLBOARD_NET_AMT") or 0) / 10000
            if min_net_buy is not None and net_buy < min_net_buy:
                continue
            stocks.append({
                "code": row.get("SECURITY_CODE", ""),
                "name": row.get("SECURITY_NAME_ABBR", ""),
                "reason": row.get("EXPLANATION", ""),
                "close": row.get("CLOSE_PRICE") or 0,
                "change_pct": round(float(row.get("CHANGE_RATE") or 0), 2),
                "net_buy_wan": round(net_buy, 1),
                "buy_wan": round((row.get("BILLBOARD_BUY_AMT") or 0) / 10000, 1),
                "sell_wan": round((row.get("BILLBOARD_SELL_AMT") or 0) / 10000, 1),
                "turnover_pct": round(float(row.get("TURNOVERRATE") or 0), 2),
            })
        return {"date": actual_date, "total_records": len(stocks), "stocks": stocks}

    # ── 7. 限售解禁 ────────────────────────────────────────────────────────
    def lockup_expiry(self, code: str, trade_date: str, forward_days: int = 90) -> dict:
        history = []
        for row in eastmoney_datacenter(
            "RPT_LIFT_STAGE",
            filter_str=f'(SECURITY_CODE="{code}")',
            page_size=15, sort_columns="FREE_DATE", sort_types="-1",
        ):
            history.append({
                "date": str(row.get("FREE_DATE", ""))[:10],
                "type": row.get("LIMITED_STOCK_TYPE", ""),
                "shares": row.get("FREE_SHARES_NUM", 0),
                "ratio": row.get("FREE_RATIO", 0),
            })

        end_date = datetime.strptime(trade_date, "%Y-%m-%d") + timedelta(days=forward_days)
        end_str = end_date.strftime("%Y-%m-%d")
        upcoming = []
        for row in eastmoney_datacenter(
            "RPT_LIFT_STAGE",
            filter_str=f'(SECURITY_CODE="{code}")(FREE_DATE>=\'{trade_date}\')(FREE_DATE<=\'{end_str}\')',
            page_size=20, sort_columns="FREE_DATE", sort_types="1",
        ):
            upcoming.append({
                "date": str(row.get("FREE_DATE", ""))[:10],
                "type": row.get("LIMITED_STOCK_TYPE", ""),
                "shares": row.get("FREE_SHARES_NUM", 0),
                "ratio": row.get("FREE_RATIO", 0),
            })
        return {"history": history, "upcoming": upcoming}

    # ── 8. 行业排名 ────────────────────────────────────────────────────────
    def industry_comparison(self, top_n: int = 20) -> dict:
        url = "https://push2.eastmoney.com/api/qt/clist/get"
        params = {
            "pn": "1", "pz": "100", "po": "1", "np": "1",
            "fltt": "2", "invt": "2",
            "fs": "m:90+t:2",
            "fields": "f2,f3,f4,f12,f13,f14,f104,f105,f128,f136,f140,f141,f207",
        }
        try:
            r = em_get(url, params=params, headers={"User-Agent": UA}, timeout=15)
            items = r.json().get("data", {}).get("diff", [])
        except Exception as e:
            logger.error(f"行业排名请求失败: {e}")
            return {"top": [], "bottom": [], "total": 0}
        if not items:
            return {"top": [], "bottom": [], "total": 0}

        rows = []
        for i, item in enumerate(items):
            rows.append({
                "rank": i + 1,
                "name": item.get("f14", ""),
                "change_pct": item.get("f3", 0),
                "code": item.get("f12", ""),
                "up_count": item.get("f104", 0),
                "down_count": item.get("f105", 0),
                "leader": item.get("f140", ""),
                "leader_change": item.get("f136", 0),
            })
        return {"top": rows[:top_n], "bottom": rows[-top_n:], "total": len(rows)}

    # ── 9. 融资融券 ────────────────────────────────────────────────────────
    def margin_trading(self, code: str, page_size: int = 30) -> list[dict]:
        rows = []
        for row in eastmoney_datacenter(
            "RPTA_WEB_RZRQ_GGMX",
            filter_str=f'(SCODE="{code}")',
            page_size=page_size, sort_columns="DATE", sort_types="-1",
        ):
            rows.append({
                "date": str(row.get("DATE", ""))[:10],
                "rzye": row.get("RZYE", 0),
                "rzmre": row.get("RZMRE", 0),
                "rzche": row.get("RZCHE", 0),
                "rqye": row.get("RQYE", 0),
                "rqmcl": row.get("RQMCL", 0),
                "rqchl": row.get("RQCHL", 0),
                "rzrqye": row.get("RZRQYE", 0),
            })
        return rows

    # ── 10. 大宗交易 ───────────────────────────────────────────────────────
    def block_trade(self, code: str, page_size: int = 20) -> list[dict]:
        rows = []
        for row in eastmoney_datacenter(
            "RPT_DATA_BLOCKTRADE",
            filter_str=f'(SECURITY_CODE="{code}")',
            page_size=page_size, sort_columns="TRADE_DATE", sort_types="-1",
        ):
            close = row.get("CLOSE_PRICE") or 0
            deal_price = row.get("DEAL_PRICE") or 0
            premium = ((deal_price / close - 1) * 100) if close else 0
            rows.append({
                "date": str(row.get("TRADE_DATE", ""))[:10],
                "price": deal_price,
                "close": close,
                "premium_pct": round(premium, 2),
                "vol": row.get("DEAL_VOLUME", 0),
                "amount": row.get("DEAL_AMT", 0),
                "buyer": row.get("BUYER_NAME", ""),
                "seller": row.get("SELLER_NAME", ""),
            })
        return rows

    # ── 11. 股东户数 ────────────────────────────────────────────────────────
    def holder_num_change(self, code: str, page_size: int = 10) -> list[dict]:
        rows = []
        for row in eastmoney_datacenter(
            "RPT_HOLDERNUMLATEST",
            filter_str=f'(SECURITY_CODE="{code}")',
            page_size=page_size, sort_columns="END_DATE", sort_types="-1",
        ):
            rows.append({
                "date": str(row.get("END_DATE", ""))[:10],
                "holder_num": row.get("HOLDER_NUM", 0),
                "change_num": row.get("HOLDER_NUM_CHANGE", 0),
                "change_ratio": row.get("HOLDER_NUM_RATIO", 0),
                "avg_shares": row.get("AVG_HOLD_NUM", 0),
            })
        return rows

    # ── 12. 分红送转 ───────────────────────────────────────────────────────
    def dividend_history(self, code: str, page_size: int = 20) -> list[dict]:
        rows = []
        for row in eastmoney_datacenter(
            "RPT_SHAREBONUS_DET",
            filter_str=f'(SECURITY_CODE="{code}")',
            page_size=page_size, sort_columns="EX_DIVIDEND_DATE", sort_types="-1",
        ):
            rows.append({
                "date": str(row.get("EX_DIVIDEND_DATE", ""))[:10],
                "bonus_rmb": row.get("PRETAX_BONUS_RMB", 0),
                # 东财对纯现金分红（无送股/转增）返回 None，or 0 兜住「值为 None」而非仅「键缺失」
                "transfer_ratio": row.get("TRANSFER_RATIO") or 0,
                "bonus_ratio": row.get("BONUS_RATIO") or 0,
                "plan": row.get("ASSIGN_PROGRESS", ""),
            })
        return rows

    # ── 13. 个股新闻 ───────────────────────────────────────────────────────
    def eastmoney_stock_news(self, code: str, page_size: int = 20) -> list[dict]:
        cb = "jQuery_news"
        url = "https://search-api-web.eastmoney.com/search/jsonp"
        inner_params = json.dumps({
            "uid": "", "keyword": code,
            "type": ["cmsArticleWebOld"], "client": "web",
            "clientType": "web", "clientVersion": "curr",
            "param": {"cmsArticleWebOld": {"searchScope": "default", "sort": "default",
                      "pageIndex": 1, "pageSize": page_size, "preTag": "", "postTag": ""}},
        }, separators=(',', ':'))
        params = {"cb": cb, "param": inner_params}
        headers = {"User-Agent": UA, "Referer": "https://so.eastmoney.com/"}
        try:
            r = em_get(url, params=params, headers=headers, timeout=15)
            text = r.text
            json_str = text[text.index("(") + 1 : text.rindex(")")]
            d = json.loads(json_str)
        except Exception as e:
            logger.error(f"东财新闻请求失败: {e}")
            return []

        rows = []
        articles = d.get("result", {}).get("cmsArticleWebOld", []) or []
        for a in articles:
            rows.append({
                "title": re.sub(r'<[^>]+>', '', a.get("title", "")),
                "content": re.sub(r'<[^>]+>', '', a.get("content", ""))[:200],
                "time": a.get("date", ""),
                "source": a.get("mediaName", ""),
                "url": a.get("url", ""),
            })
        return rows

    # ── 14. 东财基本信息 ──────────────────────────────────────────────────
    def eastmoney_stock_info(self, code: str) -> dict:
        market_code = 1 if code.startswith("6") else 0
        url = "https://push2.eastmoney.com/api/qt/stock/get"
        params = {
            "fltt": "2", "invt": "2",
            "fields": "f57,f58,f84,f85,f127,f116,f117,f189,f43",
            "secid": f"{market_code}.{code}",
        }
        try:
            r = em_get(url, params=params, headers={"User-Agent": UA}, timeout=10)
            d = r.json().get("data") or {}
        except Exception as e:
            logger.error(f"东财基本信息请求失败: {e}")
            return {}
        if not d:
            return {}
        return {
            "code": d.get("f57", ""),
            "name": d.get("f58", ""),
            "industry": d.get("f127", ""),
            "total_shares": d.get("f84", 0),
            "float_shares": d.get("f85", 0),
            "mcap": d.get("f116", 0),
            "float_mcap": d.get("f117", 0),
            "list_date": str(d.get("f189", "")),
            "price": d.get("f43", 0),
        }

    # ── 15. 研报列表 ───────────────────────────────────────────────────────
    def eastmoney_reports(self, code: str, max_pages: int = 3) -> list[dict]:
        all_records = []
        for page in range(1, max_pages + 1):
            params = {
                "industryCode": "*", "pageSize": "50", "industry": "*",
                "rating": "*", "ratingChange": "*",
                "beginTime": "2000-01-01", "endTime": "2030-01-01",
                "pageNo": str(page), "fields": "", "qType": "0",
                "orgCode": "", "code": code, "rcode": "",
                "p": str(page), "pageNum": str(page), "pageNumber": str(page),
            }
            try:
                r = em_get("https://reportapi.eastmoney.com/report/list", params=params,
                           headers={"Referer": "https://data.eastmoney.com/"}, timeout=30)
                d = r.json()
            except Exception as e:
                logger.error(f"研报列表请求失败 page={page}: {e}")
                break
            rows = d.get("data") or []
            if not rows:
                break
            for row in rows:
                all_records.append({
                    "title": row.get("title", ""),
                    "org": row.get("orgSName", ""),
                    "rating": row.get("emRatingName", ""),
                    "date": (row.get("publishDate") or "")[:10],
                    "predict_next_eps": row.get("predictNextTwoYearEps", 0),
                    "predict_this_eps": row.get("predictThisYearEps", 0),
                })
            if page >= (d.get("TotalPage", 1) or 1):
                break
        return all_records

    # ── 16. 巨潮公告 ──────────────────────────────────────────────────────
    def cninfo_announcements(self, code: str, page_size: int = 30) -> list[dict]:
        url = "https://www.cninfo.com.cn/new/hisAnnouncement/query"
        org_id = _cninfo_orgid(code)
        payload = {
            "stock": f"{code},{org_id}",
            "tabName": "fulltext", "pageSize": str(page_size),
            "pageNum": "1", "column": "", "category": "",
            "plate": "", "seDate": "", "searchkey": "",
            "secid": "", "sortName": "", "sortType": "",
            "isHLtitle": "true",
        }
        headers = {
            "User-Agent": UA,
            "Content-Type": "application/x-www-form-urlencoded",
            "Referer": "https://www.cninfo.com.cn/new/disclosure",
            "Origin": "https://www.cninfo.com.cn",
        }
        try:
            r = _GENERIC_SESSION.post(url, data=payload, headers=headers, timeout=15)
            d = r.json()
        except Exception as e:
            logger.error(f"巨潮公告请求失败: {e}")
            return []

        rows = []
        for item in d.get("announcements", []) or []:
            rows.append({
                # 巨潮 announcementTypeName 对多数公告返回 None（非键缺失），or "" 兜住 None
                "title": re.sub(r'<[^>]+>', '', item.get("announcementTitle", "")),
                "type": item.get("announcementTypeName") or "",
                "date": _cninfo_ts_to_date(item.get("announcementTime")),
                "url": f"https://www.cninfo.com.cn/new/disclosure/detail?annoId={item.get('announcementId', '')}",
            })
        return rows

    # ── 17. 同花顺热门题材归因 ────────────────────────────────────────────
    def ths_hot_reason(self, date: str = None) -> list[dict]:
        if date is None:
            date = datetime.now().strftime("%Y-%m-%d")
        url = (
            f"http://zx.10jqka.com.cn/event/api/getharden/"
            f"date/{date}/orderby/date/orderway/desc/charset/GBK/"
        )
        headers = {
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) Chrome/117.0.0.0 Safari/537.36"
        }
        try:
            r = _GENERIC_SESSION.get(url, headers=headers, timeout=10)
            data = r.json()
        except Exception as e:
            logger.error(f"同花顺热门请求失败: {e}")
            return []
        if data.get("errocode", 0) != 0:
            logger.error(f"同花顺热门错误: {data.get('errormsg', '')}")
            return []

        rows = []
        for item in data.get("data") or []:
            rows.append({
                "name": item.get("name", ""),
                "code": item.get("code", ""),
                "reason": item.get("reason", ""),
                # getharden 接口不返回行情字段，以下先占位，再由腾讯实时行情回填
                "close": item.get("close", ""),
                "change_pct": item.get("zhangfu", ""),
                "turnover_pct": item.get("huanshou", ""),
                "dde_net": item.get("ddejingliang", ""),
            })

        # 同花顺 getharden 只给代码/名称/题材，不带涨跌幅/换手/价格。
        # 用腾讯实时行情批量回填，使前端「涨幅X%」不再显示成「涨幅%」。
        codes = [r["code"] for r in rows if r.get("code")]
        quotes: dict[str, dict] = {}
        for i in range(0, len(codes), 50):  # 分块避免 URL 过长
            chunk = codes[i:i + 50]
            try:
                quotes.update(self.tencent_quote(chunk))
            except Exception as e:
                logger.warning(f"热门题材回填行情失败(chunk {i}): {e}")
        if quotes:
            for r in rows:
                q = quotes.get(r["code"])
                if not q:
                    continue
                # 仅当腾讯有有效值时回填，否则保留原占位（多为 ""）
                if q.get("change_pct"):
                    r["change_pct"] = q["change_pct"]
                if q.get("turnover_pct"):
                    r["turnover_pct"] = q["turnover_pct"]
                if q.get("price"):
                    r["close"] = q["price"]
        return rows

    # ── 18. 同花顺北向资金 ────────────────────────────────────────────────
    def hsgt_realtime(self) -> list[dict]:
        """同花顺北向资金分钟级流。

        注意：接口返回的 hgt 全天连续（≈242 点），sgt 仅开盘前段
        （实测约 30~40 点，从 09:10 起），其余位置接口补 null。
        这里把 null/缺失统一兜底为 0.0，并加 sgt_valid 字段让前端
        /LLM 区分"真实为 0"与"补的 0"，避免把数据缺失误读为资金清零。
        """
        url = "https://data.hexin.cn/market/hsgtApi/method/dayChart/"
        headers = {
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) Chrome/117.0.0.0 Safari/537.36",
            "Host": "data.hexin.cn",
            "Referer": "https://data.hexin.cn/",
        }
        try:
            r = _GENERIC_SESSION.get(url, headers=headers, timeout=10)
            d = r.json()
        except Exception as e:
            logger.error(f"北向资金请求失败: {e}")
            return []

        times = d.get("time", []) or []
        hgt = d.get("hgt", []) or []
        sgt = d.get("sgt", []) or []
        n = len(times)

        rows = []
        for i in range(n):
            h_val = hgt[i] if i < len(hgt) else None
            s_val = sgt[i] if i < len(sgt) else None
            rows.append({
                "time": times[i],
                "hgt_yi": h_val if h_val is not None else 0.0,
                "sgt_yi": s_val if s_val is not None else 0.0,
                # sgt_valid=False 表示该行 sgt 是接口缺失补的 0，不是真实 0
                "sgt_valid": s_val is not None,
            })
        return rows


# 全局单例
stock_research_service = StockResearchService()

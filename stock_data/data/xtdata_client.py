import logging
import os
import struct
import threading
import time
from datetime import datetime

import numpy as np
import pandas as pd
from xtquant import xtdata, xtconn

logger = logging.getLogger(__name__)

_client_lock = threading.Lock()
_client_connected = False
_client_last_check = 0
_CLIENT_CHECK_INTERVAL = 30

# 本地 QMT 客户端路径（因人而异），建议通过环境变量配置，不要写死在代码里：
#   QMT_DATA_DIR  —— QMT userdata_mini/datadir 目录
#   QMT_APP_DIR   —— QMT bin.x64 目录
DATA_DIR = os.environ.get("QMT_DATA_DIR", "")
APP_DIR = os.environ.get("QMT_APP_DIR", "")


_PERIOD_DIR_MAP = {
    "1m": "60", "5m": "300", "15m": "900", "30m": "1800",
    "1h": "3600", "1d": "86400", "1w": "604800", "1mon": "2592000",
}

_DAT_HEADER_SIZE = 8
_DAT_RECORD_SIZE = 64


def _find_port() -> int | None:
    try:
        addrs = xtconn.scan_available_server_addr()
        if addrs:
            for addr in addrs:
                try:
                    return int(addr.split(":")[-1])
                except Exception:
                    continue
    except Exception:
        pass

    import socket
    for port in [58610, 58600, 58611, 58612]:
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
            s.settimeout(1)
            if s.connect_ex(("127.0.0.1", port)) == 0:
                return port
    return None


def _setup_data_dir():
    try:
        data_dir = getattr(xtdata, "data_dir", None)
        server_dir = getattr(xtdata, "_XtQuantDataManager__data_dir_from_server", None)
        if not data_dir or not server_dir:
            xtdata.data_dir = DATA_DIR
            try:
                setattr(xtdata, "_XtQuantDataManager__data_dir_from_server", DATA_DIR)
            except Exception:
                pass
    except Exception:
        xtdata.data_dir = DATA_DIR


def _ensure_connected() -> bool:
    global _client_connected, _client_last_check

    now = time.time()
    if _client_connected and (now - _client_last_check) < _CLIENT_CHECK_INTERVAL:
        try:
            client = getattr(xtdata, "_XtQuantDataManager__client", None)
            if client and hasattr(client, "is_connected") and client.is_connected():
                return True
        except Exception:
            pass

    with _client_lock:
        try:
            xtdata.connect()
            _setup_data_dir()
            _client_connected = True
            _client_last_check = time.time()
            return True
        except Exception:
            pass

        port = _find_port()
        if port:
            try:
                xtdata.connect(port=port)
                _setup_data_dir()
                _client_connected = True
                _client_last_check = time.time()
                logger.info(f"xtdata connected on port {port}")
                return True
            except Exception as e:
                logger.warning(f"xtdata connect port={port} failed: {e}")

        _client_connected = False
        _client_last_check = time.time()
        return False


def _read_qmt_dat(stock_code: str, period: str) -> pd.DataFrame:
    period_dir = _PERIOD_DIR_MAP.get(period)
    if not period_dir:
        return pd.DataFrame()

    parts = stock_code.split(".")
    if len(parts) != 2:
        return pd.DataFrame()
    code, market = parts[0], parts[1].upper()

    fpath = os.path.join(DATA_DIR, market, period_dir, f"{code}.DAT")
    if not os.path.exists(fpath):
        return pd.DataFrame()

    try:
        with open(fpath, "rb") as f:
            data = f.read()
    except Exception as e:
        logger.warning(f"read .DAT failed for {stock_code}/{period}: {e}")
        return pd.DataFrame()

    file_size = len(data)
    if file_size <= _DAT_HEADER_SIZE:
        return pd.DataFrame()

    n = (file_size - _DAT_HEADER_SIZE) // _DAT_RECORD_SIZE
    if n <= 0:
        return pd.DataFrame()

    timestamps = np.empty(n, dtype="int64")
    opens = np.empty(n, dtype="float64")
    highs = np.empty(n, dtype="float64")
    lows = np.empty(n, dtype="float64")
    closes = np.empty(n, dtype="float64")
    volumes = np.empty(n, dtype="int64")

    for i in range(n):
        pos = _DAT_HEADER_SIZE + i * _DAT_RECORD_SIZE
        ts, o, h, l, c = struct.unpack_from("<5I", data, pos)
        vol = struct.unpack_from("<I", data, pos + 24)[0]
        timestamps[i] = ts
        opens[i] = o / 100.0
        highs[i] = h / 100.0
        lows[i] = l / 100.0
        closes[i] = c / 100.0
        volumes[i] = vol

    index = pd.DatetimeIndex(pd.to_datetime(timestamps, unit="s") + pd.Timedelta(hours=8))
    amounts = volumes * 100 * (opens + closes) / 2
    df = pd.DataFrame({
        "open": opens, "high": highs, "low": lows, "close": closes,
        "volume": volumes, "amount": amounts,
    }, index=index)
    return df


def get_all_stock_codes() -> list[str]:
    if not _ensure_connected():
        raise RuntimeError("xtdata service unavailable")
    codes = xtdata.get_stock_list_in_sector("沪深A股")
    return codes


def get_kline_data(stock_code: str, period: str, start_time: str = "", end_time: str = "",
                   dividend_type: str = "front", count: int = -1) -> pd.DataFrame:
    df = pd.DataFrame()

    if _ensure_connected():
        df = _try_get_local_data(stock_code, period, start_time, end_time, dividend_type, count)
        if df.empty and dividend_type != "none":
            logger.info(f"[kline] {stock_code}/{period} dividend_type={dividend_type} failed, fallback to none")
            df = _try_get_local_data(stock_code, period, start_time, end_time, "none", count)

    if df.empty:
        df = _read_qmt_dat(stock_code, period)

    if df.empty:
        return pd.DataFrame()

    if not isinstance(df.index, pd.DatetimeIndex):
        try:
            df.index = pd.to_datetime(df.index, unit="ms") + pd.Timedelta(hours=8)
        except Exception:
            df.index = pd.to_datetime(df.index)

    if start_time:
        df = df[df.index >= pd.Timestamp(start_time)]
    if end_time:
        df = df[df.index <= pd.Timestamp(end_time)]
    if count > 0:
        df = df.tail(count)

    df = df.reset_index()
    df = df.rename(columns={"index": "trade_time"})
    df["stock_code"] = stock_code

    if not pd.api.types.is_datetime64_any_dtype(df["trade_time"]):
        df["trade_time"] = pd.to_datetime(df["trade_time"], errors="coerce")

    cols = ["stock_code", "trade_time", "open", "high", "low", "close", "volume", "amount"]
    for c in ["open", "high", "low", "close", "volume", "amount"]:
        if c not in df.columns:
            df[c] = None
    return df[cols]


def _try_get_local_data(stock_code: str, period: str, start_time: str, end_time: str,
                        dividend_type: str, count: int) -> pd.DataFrame:
    try:
        data = xtdata.get_local_data(
            field_list=[], stock_list=[stock_code], period=period,
            start_time=start_time, end_time=end_time, count=count,
            dividend_type=dividend_type, fill_data=True,
        )
        if stock_code in data and not data[stock_code].empty:
            return data[stock_code]
    except Exception as e:
        logger.warning(f"get_local_data({stock_code}/{period}/{dividend_type}) failed: {e}")
    return pd.DataFrame()


def get_stock_detail(stock_code: str) -> dict:
    if not _ensure_connected():
        raise RuntimeError("xtdata service unavailable")
    detail = xtdata.get_instrument_detail(stock_code)
    if detail:
        open_date = detail.get("OpenDate", 0)
        list_date = ""
        if open_date and open_date != 0:
            s = str(open_date)
            list_date = f"{s[:4]}-{s[4:6]}-{s[6:8]}" if len(s) == 8 else s
        return {
            "stock_code": stock_code,
            "stock_name": detail.get("InstrumentName", ""),
            "pinyin": detail.get("ProductID", "") or "",
            "industry": detail.get("ProductName", ""),
            "list_date": list_date,
        }
    return None


def get_stock_detail_batch(stock_codes: list[str]) -> dict[str, dict]:
    if not _ensure_connected():
        raise RuntimeError("xtdata service unavailable")
    result = {}
    try:
        raw = xtdata.get_instrument_detail_list(stock_codes)
        for code, detail in raw.items():
            if not detail:
                continue
            open_date = detail.get("OpenDate", 0)
            list_date = ""
            if open_date and open_date != 0:
                s = str(open_date)
                list_date = f"{s[:4]}-{s[4:6]}-{s[6:8]}" if len(s) == 8 else s
            result[code] = {
                "stock_code": code,
                "stock_name": detail.get("InstrumentName", ""),
                "pinyin": detail.get("ProductID", "") or "",
                "industry": detail.get("ProductName", ""),
                "list_date": list_date,
            }
    except Exception as e:
        logger.warning(f"get_instrument_detail_list failed: {e}")
    return result


def get_full_tick(stock_codes: list[str]) -> dict:
    if not _ensure_connected():
        raise RuntimeError("xtdata service unavailable")
    try:
        return xtdata.get_full_tick(stock_codes)
    except Exception as e:
        raise RuntimeError(f"xtdata get_full_tick failed: {e}") from e

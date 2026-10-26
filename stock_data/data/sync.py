import json
import logging
import os
import threading
import time
from datetime import datetime
from pathlib import Path
from data.xtdata_client import _find_port
from xtquant import xtdata
from config import BATCH_SIZE, DOWNLOAD_TIMEOUT, DOWNLOAD_PERIODS, DOWNLOAD_SLEEP, DATA_DIR

logger = logging.getLogger(__name__)

PROGRESS_FILE = Path(DATA_DIR) / "sync_progress.json"

_sync_running = False
_sync_lock = threading.Lock()


def is_sync_running() -> bool:
    return _sync_running


def trigger_download() -> bool:
    """触发下载任务，返回 True 表示成功启动，False 表示已有任务在运行"""
    global _sync_running
    with _sync_lock:
        if _sync_running:
            return False
        _sync_running = True

    t = threading.Thread(target=_run_download, daemon=True)
    t.start()
    return True


def _run_download():
    global _sync_running
    try:
        download_all_klines()
    finally:
        with _sync_lock:
            _sync_running = False


def _download_batch(stock_codes: list[str], period: str, start_time: str, end_time: str = "", timeout: int = 30) -> bool:
    result = [None]
    exc = [None]

    def _worker():
        try:
            result[0] = xtdata.download_history_data2(
                stock_list=stock_codes,
                period=period,
                start_time=start_time,
                end_time=end_time,
            )
        except Exception as e:
            exc[0] = e

    t0_diag = time.time()
    t = threading.Thread(target=_worker, daemon=True)
    t.start()
    t.join(timeout=timeout)
    elapsed = time.time() - t0_diag
    if t.is_alive():
        logger.warning(f"[{period}] Download timeout ({timeout}s) for {len(stock_codes)} stocks, skipping")
        return False
    if exc[0]:
        logger.warning(f"[{period}] Download error for {stock_codes[:3]}...: {type(exc[0]).__name__}: {exc[0]}")
        return False
    logger.info(f"[{period}] download_history_data2 returned {result[0]!r} in {elapsed:.1f}s for {len(stock_codes)} stocks")
    return True


_CONSECUTIVE_TIMEOUT_LIMIT = 3
_TIMEOUT_COOLDOWN = 5


def _reconnect():
    """重连xtdata"""
    try:
        xtdata.disconnect()
    except Exception:
        pass
    time.sleep(1)
    try:
        xtdata.connect()
        logger.info("[download] Reconnected to xtdata")
    except Exception:
        port = _find_port()
        if port:
            try:
                xtdata.connect(port=port)
                logger.info(f"[download] Reconnected to xtdata on port {port}")
            except Exception as e:
                logger.error(f"[download] Reconnect failed: {e}")
        else:
            logger.error("[download] No xtdata server found")


def _load_progress() -> dict | None:
    try:
        if PROGRESS_FILE.exists():
            return json.loads(PROGRESS_FILE.read_text(encoding="utf-8"))
    except Exception:
        logger.warning("Failed to load progress file, starting from scratch")
    return None


def _save_progress(period: str, total: int, succeeded: set[str], end_date: str = ""):
    PROGRESS_FILE.parent.mkdir(parents=True, exist_ok=True)
    data = {
        "period": period,
        "total": total,
        "succeeded": sorted(succeeded),
        "end_date": end_date,
        "updated_at": datetime.now().isoformat(),
    }
    tmp = PROGRESS_FILE.with_suffix(".tmp")
    tmp.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
    tmp.replace(PROGRESS_FILE)


def _clear_progress():
    try:
        PROGRESS_FILE.unlink(missing_ok=True)
    except Exception:
        pass


def _last_trading_date() -> str:
    """获取最近的交易日期，格式 'YYYYMMDD'。
    非交易日运行时，截止日期应为上一个交易日，避免请求到空数据。"""
    try:
        dates = xtdata.get_trading_dates("SH", start_time="", end_time="")
        if dates:
            return datetime.fromtimestamp(dates[-1] / 1000).strftime("%Y%m%d")
    except Exception:
        pass
    return datetime.now().strftime("%Y%m%d")


def _filter_stale(codes: list[str], period: str, end_date: str) -> list[str]:
    """检查本地数据，过滤出需要下载的股票（本地数据未更新到 end_date 的）"""
    try:
        data = xtdata.get_local_data(
            field_list=[],
            stock_list=codes,
            period=period,
            start_time=end_date,
            end_time=end_date + "235959",
            count=-1,
            dividend_type="none",
        )
        stale = []
        for code in codes:
            if code not in data or len(data[code]) == 0:
                stale.append(code)
            else:
                df = data[code]
                # get_local_data 可能返回全 NaN 的填充行（suspendFlag=1），需要排除
                if "close" in df.columns and df["close"].isna().all():
                    stale.append(code)
        if stale:
            logger.info(f"[{period}] {len(codes) - len(stale)}/{len(codes)} up-to-date, {len(stale)} need download")
        else:
            logger.info(f"[{period}] All {len(codes)} stocks up-to-date, skipping download")
        return stale
    except Exception as e:
        logger.warning(f"[{period}] Failed to check local data: {e}, will download all")
        return codes


def download_all_klines():
    """下载全部沪深A股的K线数据（增量），支持断点续传"""
    # 连接 xtdata（支持脱机模式端口扫描）
    try:
        xtdata.connect()
    except Exception:
        port = _find_port()
        if port:
            try:
                xtdata.connect(port=port)
                logger.info(f"[download] Connected on port {port}")
            except Exception as e:
                logger.error(f"Cannot connect to xtdata: {e}")
                return
        else:
            logger.error("Cannot connect to xtdata: no server found")
            return

    # 设置 data_dir（脱机模式下 connect 不会自动设置）
    from data.xtdata_client import _setup_data_dir
    _setup_data_dir()

    try:
        codes = xtdata.get_stock_list_in_sector("沪深A股")
    except Exception as e:
        logger.error(f"Cannot get stock list: {e}")
        return

    total = len(codes)
    end_date = _last_trading_date()

    # 断点续传：加载上次进度
    progress = _load_progress()
    resume_period = None
    prev_succeeded: set[str] | None = None
    prev_end_date = ""
    if progress and progress.get("total") == total:
        resume_period = progress.get("period")
        prev_end_date = progress.get("end_date", "")
        if "succeeded" in progress:
            prev_succeeded = set(progress["succeeded"])
        # 如果 end_date 变了（新交易日），之前的 succeeded 不再可靠，需要重新检查
        if prev_end_date and prev_end_date != end_date:
            logger.info(
                f"[download] New trading day ({prev_end_date} -> {end_date}), "
                f"re-checking previously succeeded stocks"
            )
            # 不丢弃 succeeded，但会在 _filter_stale 后重新验证
        logger.info(
            f"[download] Resuming from period={resume_period}"
            + (f", {len(prev_succeeded)} previously succeeded" if prev_succeeded is not None else " (no succeeded info)")
        )
    elif progress:
        logger.info("[download] Stock list changed since last run, starting from scratch")

    logger.info(f"[download] Starting incremental download for {total} stocks, periods={DOWNLOAD_PERIODS}, end_date={end_date}")

    skip_period = resume_period is not None
    for period in DOWNLOAD_PERIODS:
        if skip_period:
            if period != resume_period:
                logger.info(f"[{period}] Skipping (already completed)")
                continue
            skip_period = False

        batch_size = BATCH_SIZE.get(period, 5) if isinstance(BATCH_SIZE, dict) else BATCH_SIZE
        timeout = DOWNLOAD_TIMEOUT.get(period, 30)

        # 检查本地数据，过滤出需要下载的股票
        stale_codes = _filter_stale(codes, period, end_date)
        if not stale_codes:
            logger.info(f"[{period}] Skipped (all up-to-date)")
            resume_period = None
            continue

        stale_total = len(stale_codes)
        t0 = time.time()
        success = 0
        failed = 0
        succeeded: set[str] = set()
        consecutive_timeouts = 0

        # 续传时恢复已成功的股票集合
        # 关键：prev_succeeded 中的股票如果在 stale_codes 中，说明上次标记成功但数据实际没到位，需要重新下载
        if period == resume_period and prev_succeeded is not None:
            # 只恢复不在 stale_codes 中的 succeeded 股票（这些确实已下载成功）
            truly_succeeded = prev_succeeded - set(stale_codes)
            succeeded = truly_succeeded
            logger.info(
                f"[{period}] Resumed: {len(prev_succeeded)} previously succeeded, "
                f"{len(truly_succeeded)} confirmed up-to-date, "
                f"{len(prev_succeeded) - len(truly_succeeded)} re-queued for download"
            )

        for i in range(0, stale_total, batch_size):
            batch = stale_codes[i:i + batch_size]

            # 只下载尚未成功的股票
            pending = [c for c in batch if c not in succeeded]
            if not pending:
                continue

            ok = _download_batch(pending, period, start_time="", end_time=end_date, timeout=timeout)
            if ok:
                succeeded.update(pending)
                success += len(pending)
                consecutive_timeouts = 0
            else:
                failed += len(pending)
                consecutive_timeouts += 1
                if consecutive_timeouts >= _CONSECUTIVE_TIMEOUT_LIMIT:
                    logger.warning(f"[{period}] {consecutive_timeouts} consecutive timeouts, reconnecting...")
                    _reconnect()
                    time.sleep(_TIMEOUT_COOLDOWN)
                    consecutive_timeouts = 0

            done = min(i + batch_size, stale_total)
            elapsed = time.time() - t0
            speed = done / elapsed if elapsed > 0 else 0
            eta = (stale_total - done) / speed if speed > 0 else 0
            logger.info(
                f"[{period}] Progress: {done}/{stale_total} ({done * 100 // stale_total}%) | "
                f"success={success} failed={failed} | speed={speed:.1f}/s ETA={eta:.0f}s"
            )

            # 保存断点
            _save_progress(period, total, succeeded, end_date)

            time.sleep(DOWNLOAD_SLEEP)

        elapsed = time.time() - t0
        logger.info(f"[{period}] Done: success={success} failed={failed} elapsed={elapsed:.1f}s")
        resume_period = None

    _clear_progress()
    logger.info("[download] All periods completed")

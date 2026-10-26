import logging
from datetime import datetime
from apscheduler.schedulers.background import BackgroundScheduler
from config import DOWNLOAD_HOUR, DOWNLOAD_MINUTE, DOWNLOAD_DAY_OF_WEEK
from data.sync import trigger_download

logger = logging.getLogger(__name__)

_scheduler: BackgroundScheduler | None = None

# 启动后自动触发同步的时间窗口
_AUTO_SYNC_START = 15 * 60 + 5   # 15:05
_AUTO_SYNC_END = 19 * 60          # 19:00


def start_scheduler():
    global _scheduler
    _scheduler = BackgroundScheduler()

    _scheduler.add_job(
        trigger_download,
        "cron",
        hour=DOWNLOAD_HOUR,
        minute=DOWNLOAD_MINUTE,
        day_of_week=DOWNLOAD_DAY_OF_WEEK,
        id="download_klines",
        replace_existing=True,
    )

    _scheduler.start()
    logger.info(f"Scheduler started: download job at {DOWNLOAD_HOUR:02d}:{DOWNLOAD_MINUTE:02d} every {DOWNLOAD_DAY_OF_WEEK}")

    # 启动时如果是周五 15:05-19:00，自动触发一次同步
    now = datetime.now()
    now_minutes = now.hour * 60 + now.minute
    is_friday = now.weekday() == 4  # Monday=0, Friday=4
    if is_friday and _AUTO_SYNC_START <= now_minutes < _AUTO_SYNC_END:
        if trigger_download():
            logger.info(f"Auto-sync triggered on startup (current time {now:%H:%M})")
        else:
            logger.info("Auto-sync skipped on startup (sync already running)")


def stop_scheduler():
    global _scheduler
    if _scheduler:
        _scheduler.shutdown(wait=False)
        _scheduler = None

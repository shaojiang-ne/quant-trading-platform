"""
交易日历服务

通过 AKShare 获取 A 股交易日历，持久化缓存到本地文件。
当今日超过缓存中最后一个交易日期时才更新缓存。
"""

import json
import logging
from datetime import date, timedelta
from pathlib import Path
from typing import Optional

import akshare as ak

logger = logging.getLogger(__name__)

# 缓存文件路径
CACHE_PATH = Path(__file__).parent.parent.parent / "data" / "trading_calendar.json"


class TradingCalendarService:
    """A 股交易日历服务（持久化缓存）"""

    def __init__(self):
        self._trading_dates: set[str] = set()
        self._max_date: Optional[str] = None  # 缓存中最后一个交易日
        self._loaded: bool = False

    def _load_cache(self) -> bool:
        """从本地文件加载缓存"""
        if not CACHE_PATH.exists():
            return False
        try:
            with open(CACHE_PATH, "r", encoding="utf-8") as f:
                data = json.load(f)
            self._trading_dates = set(data.get("dates", []))
            self._max_date = data.get("max_date")
            self._loaded = True
            logger.info(f"交易日历从缓存加载: {len(self._trading_dates)} 个交易日, 最后日期: {self._max_date}")
            return True
        except Exception as e:
            logger.warning(f"加载交易日历缓存失败: {e}")
            return False

    def _save_cache(self) -> None:
        """保存缓存到本地文件"""
        CACHE_PATH.parent.mkdir(parents=True, exist_ok=True)
        try:
            data = {
                "dates": sorted(self._trading_dates),
                "max_date": self._max_date,
            }
            with open(CACHE_PATH, "w", encoding="utf-8") as f:
                json.dump(data, f)
            logger.info(f"交易日历已缓存到文件: {len(self._trading_dates)} 个交易日, 最后日期: {self._max_date}")
        except Exception as e:
            logger.error(f"保存交易日历缓存失败: {e}")

    def _fetch_from_akshare(self) -> None:
        """从 AKShare 获取交易日历"""
        try:
            df = ak.tool_trade_date_hist_sina()
            dates = sorted(df["trade_date"].astype(str).tolist())
            self._trading_dates = set(dates)
            self._max_date = dates[-1] if dates else None
            self._loaded = True
            self._save_cache()
            logger.info(f"交易日历从 AKShare 加载: {len(self._trading_dates)} 个交易日, 最后日期: {self._max_date}")
        except Exception as e:
            logger.error(f"[akshare] 加载交易日历失败: {e}")
            self._loaded = False

    def _ensure_loaded(self) -> None:
        """确保交易日历已加载，必要时更新缓存"""
        if not self._loaded:
            # 先尝试从缓存加载
            if self._load_cache():
                # 缓存加载成功，检查是否需要更新
                self._maybe_update()
            else:
                # 缓存不存在，从 AKShare 获取
                self._fetch_from_akshare()
            return

        # 已加载，检查是否需要更新
        self._maybe_update()

    def _maybe_update(self) -> None:
        """当今日超过缓存中最后一个交易日期时更新"""
        if not self._max_date or not self._loaded:
            self._fetch_from_akshare()
            return

        today_str = date.today().strftime("%Y-%m-%d")
        if today_str > self._max_date:
            logger.info(f"今日 {today_str} 超过缓存最后交易日 {self._max_date}，更新交易日历")
            self._fetch_from_akshare()

    def is_trading_time(self) -> bool:
        """判断当前是否在A股交易时间内

        A股交易时段：
        - 9:15-9:25 集合竞价（可产生信号但不应下单）
        - 9:30-11:30 上午连续竞价
        - 13:00-15:00 下午连续竞价

        信号可在 9:30-11:30 和 13:00-14:57 产生，
        14:57-15:00 为收盘集合竞价，不应产生新信号。
        """
        from datetime import datetime
        now = datetime.now()
        h, m = now.hour, now.minute

        if not self.is_trading_day(now.date()):
            return False

        # 上午 9:30-11:30
        if h == 9 and m >= 30:
            return True
        if h == 10:
            return True
        if h == 11 and m <= 30:
            return True

        # 下午 13:00-14:57
        if h == 13:
            return True
        if h == 14 and m <= 57:
            return True

        return False

    def is_trading_day(self, d: Optional[date] = None) -> bool:
        """判断是否为交易日

        优先使用 AKShare 交易日历（含法定节假日），
        AKShare 不可用时回退到周末判断。
        """
        if d is None:
            d = date.today()

        self._ensure_loaded()

        if self._loaded:
            return d.strftime("%Y-%m-%d") in self._trading_dates

        # 回退：仅排除周末
        return d.weekday() < 5

    def get_last_trading_day(self, d: Optional[date] = None) -> date:
        """获取指定日期之前的最后一个交易日"""
        if d is None:
            d = date.today()

        offset = 1
        while True:
            candidate = d - timedelta(days=offset)
            if self.is_trading_day(candidate):
                return candidate
            offset += 1
            if offset > 10:
                return candidate

    def get_next_trading_day(self, d: Optional[date] = None) -> date:
        """获取指定日期之后的下一个交易日"""
        if d is None:
            d = date.today()

        offset = 1
        while True:
            candidate = d + timedelta(days=offset)
            if self.is_trading_day(candidate):
                return candidate
            offset += 1
            if offset > 10:
                return candidate


# 全局单例
trading_calendar = TradingCalendarService()
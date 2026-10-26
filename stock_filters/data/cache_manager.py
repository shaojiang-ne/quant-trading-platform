import datetime
import json
import logging
import os
import time

import pandas as pd

logger = logging.getLogger(__name__)

DEFAULT_CACHE_DIR = os.path.join(os.path.dirname(__file__), "cache")


class CacheManager:
    """本地持久化缓存：股票池、行业映射等"""

    def __init__(self, cache_dir: str = DEFAULT_CACHE_DIR):
        self.cache_dir = cache_dir
        os.makedirs(cache_dir, exist_ok=True)

    # ---- 股票池缓存 ----

    def save_stock_pool(self, pool: pd.DataFrame):
        """保存初筛结果到本地CSV"""
        path = os.path.join(self.cache_dir, "stock_pool.csv")
        pool.to_csv(path, index=False, encoding="utf-8")
        # 记录保存时间
        self._save_meta("stock_pool", {"saved_at": time.time()})
        logger.info(f"股票池已保存到 {path}，共 {len(pool)} 只")

    def load_stock_pool(self, max_age_hours: int = 24) -> pd.DataFrame | None:
        """加载本地缓存的股票池，超时返回None"""
        path = os.path.join(self.cache_dir, "stock_pool.csv")
        if not os.path.exists(path):
            return None
        meta = self._load_meta("stock_pool")
        if meta and (time.time() - meta.get("saved_at", 0)) > max_age_hours * 3600:
            logger.info("股票池缓存已过期")
            return None
        pool = pd.read_csv(path, dtype=str, encoding="utf-8")
        for col in ("is_st", "is_valid"):
            if col in pool.columns:
                pool[col] = pool[col].map({"True": True, "False": False})
        logger.info(f"从缓存加载股票池，共 {len(pool)} 只")
        return pool

    # ---- 行业映射缓存 ----

    def save_industry_map(self, industry_map: dict[str, str]):
        """保存 code->industry 映射到本地JSON"""
        path = os.path.join(self.cache_dir, "industry_map.json")
        with open(path, "w", encoding="utf-8") as f:
            json.dump(industry_map, f, ensure_ascii=False, indent=2)
        self._save_meta("industry_map", {"saved_at": time.time(), "count": len(industry_map)})
        logger.info(f"行业映射已保存到 {path}，共 {len(industry_map)} 条")

    def load_industry_map(self, max_age_days: int = 7) -> dict[str, str] | None:
        """加载本地缓存的行业映射，超时返回None"""
        path = os.path.join(self.cache_dir, "industry_map.json")
        if not os.path.exists(path):
            return None
        meta = self._load_meta("industry_map")
        if meta and (time.time() - meta.get("saved_at", 0)) > max_age_days * 86400:
            logger.info("行业映射缓存已过期")
            return None
        with open(path, "r", encoding="utf-8") as f:
            data = json.load(f)
        logger.info(f"从缓存加载行业映射，共 {len(data)} 条")
        return data

    # ---- 内部方法 ----

    def _save_meta(self, name: str, meta: dict):
        path = os.path.join(self.cache_dir, f"{name}_meta.json")
        with open(path, "w", encoding="utf-8") as f:
            json.dump(meta, f)

    def _load_meta(self, name: str) -> dict | None:
        path = os.path.join(self.cache_dir, f"{name}_meta.json")
        if not os.path.exists(path):
            return None
        with open(path, "r", encoding="utf-8") as f:
            return json.load(f)

import datetime
import logging

import pandas as pd
from data.cache_manager import CacheManager
from data.interface import DataSourceInterface

logger = logging.getLogger(__name__)


class Screener:
    """初筛逻辑：根据配置条件过滤全市场股票，形成关注股票池"""

    def __init__(self, config: dict, data: DataSourceInterface, cache: CacheManager | None = None):
        self.config = config
        self.data = data
        self.cache = cache or CacheManager()

    def run(self) -> pd.DataFrame:
        stocks = self.data.get_stock_list()
        pool = stocks.copy()
        pool["exclude_reason"] = ""

        # 排除ST
        if self.config.get("exclude_st", True):
            mask = pool["is_st"]
            pool.loc[mask, "exclude_reason"] += "ST;"

        # 排除指定代码前缀（兼容 sz30/30 两种格式：去掉市场前缀后匹配）
        prefixes = self.config.get("exclude_code_prefix", [])
        if prefixes:
            # 去掉市场前缀(sh/sz/bj)得到纯数字代码，再匹配前缀
            pure_codes = pool["code"].str.replace(r"^(sh|sz|bj)", "", regex=True)
            for p in prefixes:
                mask = pure_codes.str.startswith(p)
                pool.loc[mask, "exclude_reason"] += f"代码前缀{p};"

        # 排除新股（仅当有上市日期时过滤，空日期保留）
        new_days = self.config.get("exclude_new_stock_days", 0)
        if new_days > 0 and "list_date" in pool.columns:
            cutoff_ts = pd.Timestamp(datetime.date.today() - datetime.timedelta(days=new_days))
            pool = pool.copy()
            pool["list_date"] = pd.to_datetime(pool["list_date"], errors="coerce")
            has_date = pool["list_date"].notna()
            too_new = has_date & (pool["list_date"] > cutoff_ts)
            pool.loc[too_new, "exclude_reason"] += f"新股(上市<{new_days}天);"

        # 市值过滤（数据不完整时跳过：所有市值都为0说明接口缺失数据）
        if "market_cap" in pool.columns:
            min_cap = self.config.get("min_market_cap", 0)
            if min_cap > 0 and pool["market_cap"].gt(0).any():
                low_cap = pool["market_cap"].gt(0) & (pool["market_cap"] < min_cap)
                pool.loc[low_cap, "exclude_reason"] += f"市值<{min_cap}亿;"

        # 成交额过滤
        if "amount" in pool.columns:
            min_amount = self.config.get("min_daily_amount", 0)
            low_amount = pool["amount"].notna() & (pool["amount"] < min_amount * 1e8)
            pool.loc[low_amount, "exclude_reason"] += f"成交额<{min_amount}亿;"

        # 行业过滤
        exclude_industries = self.config.get("exclude_industries", [])
        industries_whitelist = self.config.get("industries", [])
        if (exclude_industries or industries_whitelist) and not pool.empty:
            pool = self._apply_industry_filter(pool, exclude_industries, industries_whitelist)

        # 设置是否有效
        pool["is_valid"] = pool["exclude_reason"] == ""

        # 清理额外列，只保留标准字段 + exclude_reason + is_valid
        standard_cols = ["code", "name", "industry", "list_date", "is_st", "exclude_reason", "is_valid"]
        keep_cols = [c for c in standard_cols if c in pool.columns]
        result = pool[keep_cols].reset_index(drop=True)

        # 持久化股票池（由 engine 决定是否保存，screener 只负责计算）
        excluded_count = (~result["is_valid"]).sum()
        passed_count = result["is_valid"].sum()
        logger.info(f"初筛完成: 有效 {passed_count} 只, 排除 {excluded_count} 只")

        return result

    def _apply_industry_filter(self, pool: pd.DataFrame, exclude_industries: list, industries_whitelist: list) -> pd.DataFrame:
        """使用批量行业映射进行行业过滤"""
        if pool.empty:
            return pool

        # 优先从本地缓存加载行业映射
        industry_map = self.cache.load_industry_map()

        # 缓存不存在或过期，从数据源批量获取
        if industry_map is None:
            logger.info("行业映射缓存不存在或过期，从数据源批量获取...")
            industry_map = self.data.get_industry_map()
            if industry_map:
                self.cache.save_industry_map(industry_map)

        if not industry_map:
            logger.warning("行业映射为空，跳过行业过滤")
            return pool

        # 将行业映射应用到股票池
        pool = pool.copy()
        pool["industry"] = pool["code"].map(industry_map).fillna(pool.get("industry", ""))

        # 行业黑名单（包含匹配：如"房地产"匹配"房地产开发"）
        if exclude_industries:
            mask = pool["industry"].apply(
                lambda ind: any(ex in str(ind) for ex in exclude_industries) if ind else False
            )
            for idx in pool.index[mask]:
                pool.loc[idx, "exclude_reason"] += f"行业黑名单({pool.loc[idx, 'industry']});"

        # 行业白名单（包含匹配）
        if industries_whitelist:
            mask = pool["industry"].apply(
                lambda ind: not any(wl in str(ind) for wl in industries_whitelist) if ind else False
            )
            for idx in pool.index[mask]:
                pool.loc[idx, "exclude_reason"] += f"不在行业白名单({pool.loc[idx, 'industry']});"

        return pool

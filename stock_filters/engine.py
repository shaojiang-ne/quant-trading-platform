import datetime
import logging
import time

import pandas as pd
from data.cache_manager import CacheManager
from data.interface import DataSourceInterface
from screener import Screener
from strategies import load_strategies
from notifier import DingTalkNotifier

logger = logging.getLogger(__name__)


class Engine:
    """主引擎：串联初筛→策略→通知"""

    def __init__(self, config: dict, data: DataSourceInterface, is_production: bool = False):
        self.config = config
        self.data = data
        self.cache = CacheManager()
        self.screener = Screener(config.get("screener", {}), data, self.cache)
        self.strategies = load_strategies(config)
        self.notifier = DingTalkNotifier(config.get("dingtalk", {}), config.get("dingtalk_test", {}))
        self.is_production = is_production
        self._pool: pd.DataFrame | None = None

    def run_screener(self, force: bool = False) -> pd.DataFrame:
        """执行初筛，更新股票池。新数据质量OK才替换缓存，否则保留旧数据。完成后发送钉钉通知"""
        t0 = time.time()

        success = False
        error_msg = ""

        # 尝试从缓存加载（非强制时）
        if not force:
            cached = self.cache.load_stock_pool(max_age_hours=24)
            if cached is not None and not cached.empty:
                logger.info(f"使用缓存的股票池，共 {len(cached)} 只股票")
                self._pool = cached
                return self._pool

        # 执行初筛
        try:
            logger.info("开始初筛...")
            new_pool = self.screener.run()

            # 校验新数据质量
            if self._is_pool_valid(new_pool):
                # 新数据OK，替换缓存
                self.cache.save_stock_pool(new_pool)
                self._pool = new_pool
                logger.info(f"初筛完成，股票池已更新，共 {len(new_pool)} 只股票")
            else:
                # 新数据有问题，尝试回退到旧缓存
                logger.warning("新初筛数据质量异常，尝试回退到旧缓存")
                old_cached = self._load_cached_pool_ignore_age()
                if old_cached is not None and not old_cached.empty and self._is_pool_valid(old_cached):
                    self._pool = old_cached
                    logger.info(f"回退到旧缓存，共 {len(old_cached)} 只股票")
                else:
                    # 旧缓存也没有或也无效，只能用新数据
                    logger.warning("旧缓存不可用，使用异常新数据（策略可能受影响）")
                    self._pool = new_pool

            success = True
        except Exception as e:
            error_msg = str(e)
            logger.error(f"初筛失败: {e}")

        elapsed = time.time() - t0

        # 发送钉钉通知
        self._notify_screener_result(success, error_msg, elapsed)

        return self._pool if self._pool is not None else pd.DataFrame()

    def _notify_screener_result(self, success: bool, error_msg: str, elapsed: float):
        """初筛完成后发送钉钉通知总结"""
        now = datetime.datetime.now().strftime("%Y-%m-%d %H:%M")

        if not success:
            msg = f"初筛失败 {now}\n耗时: {elapsed:.0f}s\n错误: {error_msg}"
            self.notifier.send(msg, test=not self.is_production)
            return

        pool = self._pool
        if pool is None or pool.empty:
            msg = f"初筛完成 {now}\n耗时: {elapsed:.0f}s\n结果: 无数据"
            self.notifier.send(msg, test=not self.is_production)
            return

        total = len(pool)
        valid = pool["is_valid"].sum() if "is_valid" in pool.columns else total
        excluded = total - valid

        # 排除原因统计
        from collections import Counter
        reasons = Counter()
        if "exclude_reason" in pool.columns:
            for _, row in pool[~pool["is_valid"]].iterrows():
                for r in str(row["exclude_reason"]).rstrip(";").split(";"):
                    if r:
                        reasons[r] += 1

        lines = [
            f"初筛完成 {now}",
            f"耗时: {elapsed:.0f}s",
            f"总数: {total} | 通过: {valid} | 排除: {excluded}",
        ]

        if reasons:
            lines.append("")
            lines.append("排除原因:")
            for reason, count in reasons.most_common(8):
                lines.append(f"  {reason}: {count}")

        # 数据质量
        if "market_cap" in pool.columns:
            has_cap = (pool["market_cap"] > 0).sum()
            lines.append(f"\n数据: 市值{has_cap}/{total} PE{(pool['pe']>0).sum()}/{total} PB{(pool['pb']>0).sum()}/{total}")

        msg = "\n".join(lines)
        self.notifier.send(msg, test=not self.is_production)

    def _is_pool_valid(self, pool: pd.DataFrame) -> bool:
        """校验股票池质量：有效股票数>0 且有效比例合理"""
        if pool.empty:
            return False
        if "is_valid" not in pool.columns:
            return True
        valid_count = pool["is_valid"].sum()
        if valid_count == 0:
            return False
        valid_ratio = valid_count / len(pool)
        # 有效比例低于5%视为异常（正常应>30%）
        if valid_ratio < 0.05:
            return False
        return True

    def _load_cached_pool_ignore_age(self) -> pd.DataFrame | None:
        """加载缓存股票池，忽略过期时间"""
        import os
        path = os.path.join(self.cache.cache_dir, "stock_pool.csv")
        if not os.path.exists(path):
            return None
        pool = pd.read_csv(path, dtype=str, encoding="utf-8")
        for col in ("is_st", "is_valid"):
            if col in pool.columns:
                pool[col] = pool[col].map({"True": True, "False": False})
        return pool

    def _get_passed_pool(self) -> pd.DataFrame:
        """获取有效股票（is_valid为True）"""
        if self._pool is None:
            return pd.DataFrame()
        if "is_valid" in self._pool.columns:
            return self._pool[self._pool["is_valid"]]
        return self._pool

    def run_strategies(self) -> dict[str, list[dict]]:
        """在股票池上运行所有启用的策略"""
        if self._pool is None or self._pool.empty:
            self.run_screener()

        passed = self._get_passed_pool()
        codes = passed["code"].tolist()

        # 预加载所有K线数据（并发实时获取）
        logger.info(f"实时获取 {len(codes)} 只股票K线数据...")
        self.data.batch_get_daily_quotes(codes, days=60)

        results = {}
        for strategy in self.strategies:
            try:
                logger.info(f"运行策略: {strategy.name}")
                hits = strategy.scan(passed, self.data)
                results[strategy.description] = hits
                if hits:
                    logger.info(f"策略 {strategy.name} 命中 {len(hits)} 只股票")
                else:
                    logger.info(f"策略 {strategy.name} 未命中")
            except Exception as e:
                logger.error(f"策略 {strategy.name} 执行失败: {e}")
        return results

    def run(self):
        """完整流程：初筛→策略→通知"""
        t0 = time.time()
        self.run_screener()
        return self._run_strategies_and_notify(t0)

    def run_strategies_and_notify(self) -> dict[str, list[dict]]:
        """策略扫描+通知（使用缓存的股票池）"""
        t0 = time.time()
        if self._pool is None or self._pool.empty:
            self.run_screener()
        return self._run_strategies_and_notify(t0)

    def _run_strategies_and_notify(self, t0: float) -> dict[str, list[dict]]:
        """策略扫描+通知，t0为计时起点"""
        results = self.run_strategies()
        elapsed = time.time() - t0
        if results:
            self._enrich_with_price(results)
        messages = self.notifier.format_messages(results, elapsed=elapsed)
        all_ok = True
        for msg in messages:
            if not self.notifier.send(msg, test=not self.is_production):
                all_ok = False
        if all_ok:
            logger.info("通知发送成功")
        else:
            logger.error("部分通知发送失败")
        return results

    def _enrich_with_price(self, results: dict[str, list[dict]]):
        """为策略命中的股票补充价格信息（从实时行情取最新价和涨跌幅）"""
        all_codes = list({hit["code"] for hits in results.values() for hit in hits})
        if not all_codes:
            return
        try:
            realtime = self.data.get_realtime_quote(all_codes)
            price_map = dict(zip(realtime["code"], realtime["price"]))
            change_map = dict(zip(realtime["code"], realtime["change_pct"]))
            for hits in results.values():
                for hit in hits:
                    code = hit["code"]
                    price = price_map.get(code, 0)
                    hit["price"] = round(float(price), 2) if price else 0
                    change_pct = change_map.get(code, 0)
                    hit["change_pct"] = round(float(change_pct), 2) if change_pct else 0
        except Exception as e:
            logger.warning(f"获取价格信息失败: {e}")
            for hits in results.values():
                for hit in hits:
                    hit.setdefault("price", 0)
                    hit.setdefault("change_pct", 0)

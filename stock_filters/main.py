import argparse
import logging

# ── 全局 requests 连接池补丁（防 TCP 端口耗尽）──────────────────────────────
# 同 backend/app/main.py：akshare request_with_retry 每次新建 Session 并禁用
# 连接池，stock_zh_a_spot() / stock_individual_fund_flow 等接口会堆积 TIME_WAIT。
# 必须在 from data.akshare_source import ... 之前执行（该 import 会触发 akshare）。
import requests as _requests
from requests.adapters import HTTPAdapter as _HTTPAdapter
from urllib3.util.retry import Retry as _Retry

_POOL_CONNECTIONS = 20
_POOL_MAXSIZE = 10
_MAX_RETRIES = _Retry(total=2, backoff_factor=0.5, status_forcelist=[502, 503, 504])

_REQUESTS_SESSION = _requests.Session()
_REQUESTS_SESSION.mount("https://", _HTTPAdapter(
    pool_connections=_POOL_CONNECTIONS, pool_maxsize=_POOL_MAXSIZE, max_retries=_MAX_RETRIES))
_REQUESTS_SESSION.mount("http://", _HTTPAdapter(
    pool_connections=_POOL_CONNECTIONS, pool_maxsize=_POOL_MAXSIZE, max_retries=_MAX_RETRIES))

# 模块级裸调用（如 notifier.requests.post）也走连接池 Session
_requests.get = _REQUESTS_SESSION.get
_requests.post = _REQUESTS_SESSION.post
_requests.put = _REQUESTS_SESSION.put
_requests.delete = _REQUESTS_SESSION.delete
_requests.patch = _REQUESTS_SESSION.patch
_requests.head = _REQUESTS_SESSION.head
_requests.options = _REQUESTS_SESSION.options

# 所有新建 Session 自动挂连接池（覆盖 akshare 内部临时 Session）
_OriginalSessionInit = _requests.Session.__init__

def _patched_session_init(self, *args, **kwargs):
    _OriginalSessionInit(self, *args, **kwargs)
    self.mount("https://", _HTTPAdapter(
        pool_connections=_POOL_CONNECTIONS, pool_maxsize=_POOL_MAXSIZE, max_retries=_MAX_RETRIES))
    self.mount("http://", _HTTPAdapter(
        pool_connections=_POOL_CONNECTIONS, pool_maxsize=_POOL_MAXSIZE, max_retries=_MAX_RETRIES))

_requests.Session.__init__ = _patched_session_init

# 替换 akshare request_with_retry 走全局共享 Session（根治每次新建/关闭连接）
try:
    import akshare.utils.request as _ak_req

    def _patched_request_with_retry(
        url, params=None, timeout=15, max_retries=3,
        base_delay=1.0, random_delay_range=(0.5, 1.5),
    ):
        import random
        import time as _time
        last_exception = None
        for attempt in range(max_retries):
            try:
                response = _REQUESTS_SESSION.get(url, params=params, timeout=timeout)
                response.raise_for_status()
                return response
            except (_requests.RequestException, ValueError) as e:
                last_exception = e
                if attempt < max_retries - 1:
                    delay = base_delay * (2 ** attempt) + random.uniform(*random_delay_range)
                    _time.sleep(delay)
        raise last_exception

    _ak_req.request_with_retry = _patched_request_with_retry
    try:
        import akshare.utils.func as _ak_func
        _ak_func.request_with_retry = _patched_request_with_retry
    except ImportError:
        pass
    logging.getLogger(__name__).info("akshare request_with_retry 已替换为全局连接池版本")
except ImportError:
    pass  # akshare 未安装，跳过

import pandas as pd
import yaml
from data.akshare_source import AKShareDataSource
from engine import Engine
from scheduler import StockScheduler

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
)
logger = logging.getLogger(__name__)


def load_config(path: str = "config.yaml") -> dict:
    with open(path, "r", encoding="utf-8") as f:
        return yaml.safe_load(f)


def main():
    parser = argparse.ArgumentParser(description="股票筛选系统")
    parser.add_argument("--run-screener", action="store_true", help="手动执行初筛")
    parser.add_argument("--run-strategies", action="store_true", help="手动执行策略扫描")
    parser.add_argument("--run", action="store_true", help="手动执行完整流程（初筛+策略+通知）")
    parser.add_argument("--schedule", action="store_true", help="启动定时调度")
    parser.add_argument("--config", default="config.yaml", help="配置文件路径")
    parser.add_argument("--force", action="store_true", help="强制刷新，忽略缓存")
    args = parser.parse_args()

    config = load_config(args.config)
    data = AKShareDataSource()

    if args.run_screener:
        engine = Engine(config, data)
        pool = engine.run_screener(force=args.force)
        valid = pool[pool["is_valid"]] if "is_valid" in pool.columns else pool
        excluded = pool[~pool["is_valid"]] if "is_valid" in pool.columns else pd.DataFrame()
        logger.info(f"总数: {len(pool)}, 有效: {len(valid)}, 排除: {len(excluded)}")
        if not excluded.empty:
            logger.info(f"排除原因分布:\n{excluded['exclude_reason'].value_counts().to_string()}")
        logger.info(f"有效股票:\n{valid[['code','name','industry']].to_string(index=False)}")
    elif args.run_strategies:
        engine = Engine(config, data)
        results = engine.run_strategies_and_notify()
        for strategy_name, hits in results.items():
            logger.info(f"{strategy_name}: {len(hits)} 只")
    elif args.run:
        engine = Engine(config, data)
        engine.run()
    elif args.schedule:
        scheduler = StockScheduler(config)
        scheduler.start()
    else:
        parser.print_help()


if __name__ == "__main__":
    main()
"""AkshareDataSource._get_spot_df 类级 TTL 缓存测试。

验证多路径（轮询 / auto 降级回退 / 自选股刷新）在 TTL 内复用同一份
stock_zh_a_spot_em() 全市场快照，避免 55+ HTTP 请求被重复触发导致 TCP 爆炸。
"""
import time

import pandas as pd

from app.core.data_source_akshare import AkshareDataSource


def _make_spot_df():
    """构造 stock_zh_a_spot_em 的中文列结构（仅含 get_snapshot 用到的列）。"""
    return pd.DataFrame({
        "代码": ["600519", "000001"],
        "名称": ["贵州茅台", "平安银行"],
        "最新价": [1680.0, 12.0],
        "涨跌幅": [1.2, 0.3],
        "换手率": [0.5, 0.2],
        "市盈率-动态": [30.0, 8.0],
        "市净率": [10.0, 0.7],
        "流通市值": [2.1e12, 2.3e11],
        "量比": [1.1, 0.9],
        "成交额": [5e9, 1e9],
    })


def _reset_cache():
    AkshareDataSource._spot_cache_df = None
    AkshareDataSource._spot_cache_ts = 0.0


def test_empty_codes_returns_empty():
    """空 codes 不触发拉取"""
    _reset_cache()
    ds = AkshareDataSource()
    assert ds.get_snapshot([]) == {}


def test_spot_cached_within_ttl(monkeypatch):
    """TTL 内重复调用只拉一次 stock_zh_a_spot_em"""
    _reset_cache()
    monkeypatch.setattr(AkshareDataSource, "_rate_limit", lambda *a, **k: None)
    import akshare
    calls = {"n": 0}

    def _fake_spot():
        calls["n"] += 1
        return _make_spot_df()

    monkeypatch.setattr(akshare, "stock_zh_a_spot_em", _fake_spot)

    ds = AkshareDataSource()
    r1 = ds.get_snapshot(["600519"])
    r2 = ds.get_snapshot(["600519"])
    assert calls["n"] == 1, "TTL 内应只拉一次 spot_em"
    assert r1["600519"]["price"] == 1680.0
    assert r2["600519"]["price"] == 1680.0


def test_spot_cache_shared_across_instances(monkeypatch):
    """两个 AkshareDataSource 实例共享同一份类级缓存"""
    _reset_cache()
    monkeypatch.setattr(AkshareDataSource, "_rate_limit", lambda *a, **k: None)
    import akshare
    calls = {"n": 0}

    def _fake_spot():
        calls["n"] += 1
        return _make_spot_df()

    monkeypatch.setattr(akshare, "stock_zh_a_spot_em", _fake_spot)

    ds1 = AkshareDataSource()
    ds2 = AkshareDataSource()
    ds1.get_snapshot(["600519"])
    ds2.get_snapshot(["000001"])
    assert calls["n"] == 1, "跨实例应共享缓存，只拉一次"


def test_spot_failure_keeps_old_cache_and_backoff(monkeypatch):
    """拉取失败时返回旧缓存且更新 ts（负面缓存，短期不重试）"""
    _reset_cache()
    monkeypatch.setattr(AkshareDataSource, "_rate_limit", lambda *a, **k: None)
    import akshare
    calls = {"n": 0}

    def _fake_spot():
        calls["n"] += 1
        if calls["n"] == 1:
            return _make_spot_df()
        raise RuntimeError("akshare 挂了")

    monkeypatch.setattr(akshare, "stock_zh_a_spot_em", _fake_spot)

    ds = AkshareDataSource()
    r1 = ds.get_snapshot(["600519"])
    assert calls["n"] == 1
    assert r1["600519"]["price"] == 1680.0

    # 强制缓存过期，触发重拉（这次失败）
    AkshareDataSource._spot_cache_ts = time.time() - AkshareDataSource._SPOT_CACHE_TTL - 1
    r2 = ds.get_snapshot(["600519"])
    assert calls["n"] == 2, "过期后应重拉一次"
    assert r2["600519"]["price"] == 1680.0, "失败时应返回旧缓存"

    # 负面缓存：失败后 ts 已更新，TTL 内再调不重拉
    r3 = ds.get_snapshot(["600519"])
    assert calls["n"] == 2, "负面缓存期内不应重拉"


def test_spot_refreshes_after_ttl(monkeypatch):
    """TTL 过期后重新拉取"""
    _reset_cache()
    monkeypatch.setattr(AkshareDataSource, "_rate_limit", lambda *a, **k: None)
    import akshare
    calls = {"n": 0}

    def _fake_spot():
        calls["n"] += 1
        return _make_spot_df()

    monkeypatch.setattr(akshare, "stock_zh_a_spot_em", _fake_spot)

    ds = AkshareDataSource()
    ds.get_snapshot(["600519"])
    assert calls["n"] == 1
    # 过期
    AkshareDataSource._spot_cache_ts = time.time() - AkshareDataSource._SPOT_CACHE_TTL - 1
    ds.get_snapshot(["600519"])
    assert calls["n"] == 2, "TTL 过期后应重新拉取"

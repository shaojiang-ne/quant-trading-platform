"""测试 akshare 成分股取数的列名匹配(避免命中指数代码列)。"""
import pandas as pd
from app.core.data_source_akshare import AkshareDataSource


def _make_csindex_df():
    """构造 akshare.index_stock_cons_csindex 的真实 9 列结构。"""
    return pd.DataFrame({
        "日期": ["2026-06-30"] * 3,
        "指数代码": ["000300"] * 3,
        "指数名称": ["沪深300"] * 3,
        "指数英文名称": ["CSI 300"] * 3,
        "成分券代码": ["000001", "000002", "000063"],
        "成分券名称": ["平安银行", "万科A", "中兴通讯"],
        "成分券英文名称": ["x", "y", "z"],
        "交易所": ["深圳证券交易所"] * 3,
        "交易所英文名称": ["Shenzhen"] * 3,
    })


def test_constituents_picks_component_code_not_index_code(monkeypatch):
    """成分股代码应取「成分券代码」列,而非「指数代码」列。"""
    df = _make_csindex_df()

    # mock akshare.index_stock_cons_csindex 返回真实结构
    import akshare
    monkeypatch.setattr(akshare, "index_stock_cons_csindex", lambda symbol: df)
    # 跳过限速睡眠
    monkeypatch.setattr(AkshareDataSource, "_rate_limit", lambda self: None)

    ds = AkshareDataSource()
    out = ds.get_index_constituents("000300")

    codes = [c["code"] for c in out]
    names = [c["name"] for c in out]
    assert codes == ["000001", "000002", "000063"], f"应取成分券代码, 实际: {codes}"
    assert names == ["平安银行", "万科A", "中兴通讯"], f"应取成分券名称, 实际: {names}"
    # 关键:不应出现指数代码 000300
    assert "000300" not in codes, "不应把指数代码当成成分股代码"


def test_constituents_empty_df(monkeypatch):
    import akshare
    monkeypatch.setattr(akshare, "index_stock_cons_csindex", lambda symbol: pd.DataFrame())
    monkeypatch.setattr(AkshareDataSource, "_rate_limit", lambda self: None)
    ds = AkshareDataSource()
    assert ds.get_index_constituents("000300") == []

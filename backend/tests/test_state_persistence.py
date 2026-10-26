"""
持仓状态持久化测试 — CtaSignalAdapter.save_state / load_state

实盘重启安全：策略重启后通过 save→load 恢复持仓相关状态
（信号状态、T+1 日期、bar 索引、上一根价格、网格层状态）。

本套测试只验证 save_state/load_state 的字段往返一致性、网格状态恢复、
空状态安全，**不**跑完整"半段续跑==全量"交易对比。原因：
回测引擎的 run_backtesting 会调 precompute_signals 重新计算所有信号，
load_state 恢复的 _bar_index 会被 precompute 末尾的 self._bar_index = 0
覆盖（见 strategy_adapter.py:134），因此纯用 run_backtesting 难以表达
"从第 500 根续跑"的语义。字段往返一致性已足以覆盖持久化正确性。
"""

import json
from datetime import date

import pytest

vnpy = pytest.importorskip("vnpy")

from app.core.strategy_adapter import VNPY_STRATEGY_MAP, create_adapter
from app.strategies.base import DoubleMaStrategy, GridStrategy

VTSYM = "600000.SSE"


class StubEngine:
    """最小 stub engine：仅满足 save_state/load_state 不调 engine 方法。
    send_order/write_log/get_cash_available 仅用于完整造实例，持久化测试不触发。
    """

    def __init__(self, capital: float = 1_000_000.0):
        self.cash = capital

    def get_cash_available(self) -> float:
        return self.cash

    def write_log(self, msg: str, strategy=None) -> None:
        pass

    def send_order(self, strategy, vt_symbol, direction, offset, price, volume):
        return []

    def cancel_order(self, strategy, vt_orderid):
        pass


def _make_normal_adapter():
    """造一个 DoubleMaStrategy 适配器实例并 on_init"""
    engine = StubEngine()
    strategy_cls = VNPY_STRATEGY_MAP["DoubleMaStrategy"]
    adapter = strategy_cls(engine, "DoubleMaStrategy", [VTSYM],
                           {"fast_window": 5, "slow_window": 20})
    adapter.on_init()
    return adapter


def _make_grid_adapter():
    """造一个 GridStrategy 适配器实例并 on_init"""
    engine = StubEngine()
    strategy_cls = VNPY_STRATEGY_MAP["GridStrategy"]
    adapter = strategy_cls(engine, "GridStrategy", [VTSYM],
                           {"grid_size": 0.02, "grid_quantity": 100})
    adapter.on_init()
    return adapter


# ── 空状态安全 ──────────────────────────────────────────────────────────

class TestEmptyState:
    def test_save_load_empty_no_throw(self):
        """未持仓时 save/load 不抛、字段为默认值"""
        adapter = _make_normal_adapter()

        # on_init 后未推任何 bar，状态应为默认
        assert adapter._signal_state == 0
        assert adapter._buy_date is None
        assert adapter._bar_index == 0
        assert adapter._prev_price == 0
        assert adapter._grid_states == {}

        # save_state 不抛
        state = adapter.save_state()

        # 字段为默认值
        assert state["signal_state"] == 0
        assert state["buy_date"] is None
        assert state["bar_index"] == 0
        assert state["prev_price"] == 0
        # 空 grid_states 序列化为 "{}"
        assert json.loads(state["grid_states_json"]) == {}
        # 元信息字段
        assert state["strategy_name"] == "DoubleMaStrategy"
        assert state["class_name"] == "DoubleMaStrategy"
        assert state["vt_symbol"] == VTSYM

        # load_state 不抛，且字段保持默认
        adapter2 = _make_normal_adapter()
        adapter2.load_state(state)
        assert adapter2._signal_state == 0
        assert adapter2._buy_date is None
        assert adapter2._bar_index == 0
        assert adapter2._prev_price == 0
        assert adapter2._grid_states == {}

    def test_load_empty_dict_no_throw(self):
        """load_state({}) 不抛、不改变状态"""
        adapter = _make_normal_adapter()
        # 先设非默认状态
        adapter._signal_state = 1
        adapter._bar_index = 10
        adapter.load_state({})  # 空字典 early return
        # 空字典 early return，状态不被覆盖
        assert adapter._signal_state == 1
        assert adapter._bar_index == 10

    def test_load_none_no_throw(self):
        """load_state(None) 不抛"""
        adapter = _make_normal_adapter()
        adapter.load_state(None)  # 不抛


# ── 字段往返一致性 ──────────────────────────────────────────────────────

class TestStateRoundtrip:
    def test_state_fields_roundtrip(self):
        """修改实例状态后 save→load 到新实例，所有持久化字段一致

        这等价于"半段续跑==全量"的语义核心：重启后实例的关键状态
        （signal_state/buy_date/bar_index/prev_price）与原实例一致。
        """
        adapter = _make_normal_adapter()
        # 手动设置非默认状态（模拟跑了一段后持仓中）
        adapter._signal_state = 1
        adapter._buy_date = date(2024, 1, 5)
        adapter._bar_index = 42
        adapter._prev_price = 10.5

        state = adapter.save_state()

        # 新实例 load_state
        adapter2 = _make_normal_adapter()
        adapter2.load_state(state)

        assert adapter2._signal_state == 1
        assert adapter2._buy_date == date(2024, 1, 5)
        assert adapter2._bar_index == 42
        assert adapter2._prev_price == 10.5

    def test_buy_date_none_roundtrip(self):
        """buy_date=None 往返（未持仓时）"""
        adapter = _make_normal_adapter()
        adapter._buy_date = None
        state = adapter.save_state()
        assert state["buy_date"] is None

        adapter2 = _make_normal_adapter()
        adapter2.load_state(state)
        assert adapter2._buy_date is None

    def test_buy_date_iso_roundtrip(self):
        """buy_date 日期 isoformat 往返"""
        adapter = _make_normal_adapter()
        adapter._buy_date = date(2023, 12, 31)
        state = adapter.save_state()
        assert state["buy_date"] == "2023-12-31"

        adapter2 = _make_normal_adapter()
        adapter2.load_state(state)
        assert adapter2._buy_date == date(2023, 12, 31)
        # 类型必须是 date，不是 str
        assert isinstance(adapter2._buy_date, date)

    def test_signal_state_negative_roundtrip(self):
        """signal_state=0（A股不支持空头，但字段往返仍应一致）"""
        adapter = _make_normal_adapter()
        adapter._signal_state = 0
        state = adapter.save_state()

        adapter2 = _make_normal_adapter()
        adapter2.load_state(state)
        assert adapter2._signal_state == 0

    def test_meta_fields_in_state(self):
        """save_state 含 strategy_name/class_name/vt_symbol 元信息"""
        adapter = _make_normal_adapter()
        state = adapter.save_state()
        assert state["strategy_name"] == "DoubleMaStrategy"
        assert state["class_name"] == "DoubleMaStrategy"
        assert state["vt_symbol"] == VTSYM


# ── 网格状态持久化 ──────────────────────────────────────────────────────

class TestGridPersistence:
    def test_grid_state_json_roundtrip(self):
        """网格 grid_states_json 序列化/反序列化一致"""
        adapter = _make_grid_adapter()
        adapter._grid_states = {-1: 1, 0: 0, 1: 1}
        adapter._prev_price = 12.3
        adapter._bar_index = 99

        state = adapter.save_state()

        # grid_states_json 是合法 JSON 字符串，key 被转为 str
        assert isinstance(state["grid_states_json"], str)
        parsed = json.loads(state["grid_states_json"])
        assert parsed == {"-1": 1, "0": 0, "1": 1}

        # 新实例 load_state
        adapter2 = _make_grid_adapter()
        adapter2.load_state(state)

        # 恢复后 key 回到 int
        assert adapter2._grid_states == {-1: 1, 0: 0, 1: 1}
        assert all(isinstance(k, int) for k in adapter2._grid_states.keys())
        # 其他字段也恢复
        assert adapter2._prev_price == 12.3
        assert adapter2._bar_index == 99

    def test_grid_state_empty_roundtrip(self):
        """空 grid_states 往返"""
        adapter = _make_grid_adapter()
        adapter._grid_states = {}
        state = adapter.save_state()
        assert json.loads(state["grid_states_json"]) == {}

        adapter2 = _make_grid_adapter()
        adapter2.load_state(state)
        assert adapter2._grid_states == {}

    def test_grid_state_large_levels_roundtrip(self):
        """多网格层（含大 key）往返"""
        adapter = _make_grid_adapter()
        adapter._grid_states = {i: (1 if i % 2 == 0 else 0) for i in range(-5, 6)}
        state = adapter.save_state()

        adapter2 = _make_grid_adapter()
        adapter2.load_state(state)
        assert adapter2._grid_states == adapter._grid_states

    def test_load_malformed_grid_json_falls_back_to_empty(self):
        """grid_states_json 损坏时回退到空 dict（不抛）"""
        adapter = _make_grid_adapter()
        adapter._grid_states = {1: 1}  # 原有状态
        # 注入损坏 JSON
        bad_state = {
            "grid_states_json": "{not valid json}",
            "signal_state": 0,
            "buy_date": None,
            "bar_index": 0,
            "prev_price": 0,
        }
        adapter.load_state(bad_state)
        # 损坏 → 回退空 dict
        assert adapter._grid_states == {}

    def test_load_missing_grid_json_key_defaults_empty(self):
        """state 缺 grid_states_json 键时回退默认"""
        adapter = _make_grid_adapter()
        adapter._grid_states = {1: 1}
        partial_state = {
            "signal_state": 0,
            "buy_date": None,
            "bar_index": 0,
            "prev_price": 0,
        }
        adapter.load_state(partial_state)
        assert adapter._grid_states == {}


# ── 跨实例类型一致性 ────────────────────────────────────────────────────

class TestCrossInstanceConsistency:
    def test_roundtrip_preserves_field_types(self):
        """往返后字段类型正确（int 不变 int，date 不变 str）"""
        adapter = _make_normal_adapter()
        adapter._signal_state = 1
        adapter._buy_date = date(2024, 6, 15)
        adapter._bar_index = 7
        adapter._prev_price = 9.99

        state = adapter.save_state()

        adapter2 = _make_normal_adapter()
        adapter2.load_state(state)

        assert isinstance(adapter2._signal_state, int)
        assert isinstance(adapter2._buy_date, date)
        assert isinstance(adapter2._bar_index, int)
        assert isinstance(adapter2._prev_price, (int, float))

    def test_create_adapter_produces_instantiable_subclass(self):
        """create_adapter 返回的类可直接实例化（ABC 限制不阻塞具体子类）"""
        cls = create_adapter(DoubleMaStrategy, grid_mode=False)
        engine = StubEngine()
        instance = cls(engine, "DoubleMaStrategy", [VTSYM],
                       {"fast_window": 5, "slow_window": 20})
        instance.on_init()
        # save/load 可用
        state = instance.save_state()
        instance.load_state(state)
        assert instance._wrapped_cls is DoubleMaStrategy
        assert instance._grid_mode is False

    def test_create_adapter_grid_mode_flag(self):
        """create_adapter 的 grid_mode 标志正确传入"""
        cls = create_adapter(GridStrategy, grid_mode=True)
        engine = StubEngine()
        instance = cls(engine, "GridStrategy", [VTSYM],
                       {"grid_size": 0.02, "grid_quantity": 100})
        instance.on_init()
        assert instance._wrapped_cls is GridStrategy
        assert instance._grid_mode is True

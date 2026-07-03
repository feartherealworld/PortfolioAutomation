"""apply_signal / _mark_equity / mark_runtime_point — the paper-trading state
machine behind TradingView signal strategies."""
from signalbot.strategies import (
    new_runtime_entry, apply_signal, _mark_equity, mark_runtime_point,
)


def test_new_runtime_entry():
    rt = new_runtime_entry(10_000)
    assert rt["equity"] == 10_000
    assert rt["position"] is None
    assert rt["equity_curve"] == []


def test_long_open_and_mark():
    rt = apply_signal(new_runtime_entry(10_000), "long", 100.0)
    pos = rt["position"]
    assert pos["side"] == "long"
    assert abs(pos["qty"] - 100.0) < 1e-9        # 10k / 100
    assert _mark_equity(rt, 110.0) == 11_000.0   # +10 × 100
    assert _mark_equity(rt, 90.0) == 9_000.0


def test_buy_sell_aliases():
    rt = apply_signal(new_runtime_entry(1_000), "BUY", 10.0)
    assert rt["position"]["side"] == "long"
    rt = apply_signal(new_runtime_entry(1_000), "Sell", 10.0)
    assert rt["position"]["side"] == "short"


def test_flip_realizes_pnl():
    rt = apply_signal(new_runtime_entry(10_000), "long", 100.0)
    rt = apply_signal(rt, "short", 110.0)        # realize +1000, flip short
    assert rt["equity"] == 11_000.0
    pos = rt["position"]
    assert pos["side"] == "short"
    assert abs(pos["qty"] - 100.0) < 1e-9        # 11k / 110
    rt = apply_signal(rt, "flat", 100.0)         # short gains 10 × 100
    assert rt["equity"] == 12_000.0
    assert rt["position"] is None


def test_repeat_signal_is_noop():
    rt = apply_signal(new_runtime_entry(10_000), "long", 100.0)
    rt2 = apply_signal(rt, "long", 120.0)
    assert rt2["position"]["entry_px"] == rt["position"]["entry_px"]
    assert rt2["equity"] == rt["equity"]
    assert "already long" in rt2["signal_log"][-1]["note"]


def test_leverage_scales_qty():
    rt = apply_signal(new_runtime_entry(10_000), "long", 100.0, leverage=3)
    assert abs(rt["position"]["qty"] - 300.0) < 1e-9
    assert _mark_equity(rt, 110.0) == 13_000.0


def test_unknown_action_ignored():
    rt = apply_signal(new_runtime_entry(10_000), "hodl", 100.0)
    assert rt["position"] is None
    assert rt["equity"] == 10_000
    assert "ignored" in rt["signal_log"][-1]["note"]


def test_equity_floor_at_zero():
    rt = apply_signal(new_runtime_entry(1_000), "long", 100.0, leverage=5)
    rt = apply_signal(rt, "flat", 50.0)          # -50 × 50 qty = -2500 → floor 0
    assert rt["equity"] == 0.0
    assert _mark_equity(rt, 50.0) == 0.0


def test_apply_signal_does_not_mutate_input():
    rt0 = apply_signal(new_runtime_entry(1_000), "long", 10.0)
    snapshot = dict(rt0["position"])
    apply_signal(rt0, "flat", 20.0)
    assert rt0["position"] == snapshot


def test_mark_runtime_point_hourly_dedup():
    rt = apply_signal(new_runtime_entry(1_000), "long", 10.0)
    t0 = 1_700_000_000_000
    rt = mark_runtime_point(rt, 10.0, ts=t0)
    rt = mark_runtime_point(rt, 12.0, ts=t0 + 60_000)          # same hour → replace
    assert len(rt["equity_curve"]) == 1
    assert rt["equity_curve"][0]["v"] == 1_200.0
    rt = mark_runtime_point(rt, 11.0, ts=t0 + 3_600_000)       # next hour → append
    assert len(rt["equity_curve"]) == 2

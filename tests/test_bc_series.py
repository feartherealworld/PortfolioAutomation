"""bc_cumulative_series — the dense 'daily open' comparison line.
Sparse per-rebalance bc points become a running-sum shift of the actual
equity curve, so the chart toggle is meaningful between fill days too."""
from signalbot.strategies import bc_cumulative_series

H = 3_600_000
T0 = 1_700_000_000_000


def snaps(*vals):
    return [{"ts": T0 + i * H, "v": float(v)} for i, v in enumerate(vals)]


def test_no_bc_points_returns_actual_unshifted():
    out = bc_cumulative_series(snaps(100, 101, 102), [])
    assert [p["v"] for p in out] == [100.0, 101.0, 102.0]


def test_single_adjustment_shifts_from_its_hour_onward():
    actual = snaps(100, 100, 100, 100)
    # rebalance in hour 1: bc says 99.5 while actual that hour is 100 → adj -0.5
    bc = [{"ts": T0 + 1 * H + 60_000, "v": 99.5}]
    out = bc_cumulative_series(actual, bc)
    assert [p["v"] for p in out] == [100.0, 99.5, 99.5, 99.5]


def test_adjustments_accumulate_across_rebalances():
    actual = snaps(100, 100, 100, 100)
    bc = [{"ts": T0 + 1 * H, "v": 99.5},    # adj -0.5
          {"ts": T0 + 3 * H, "v": 99.8}]    # adj vs hour-3 actual 100 → -0.2
    out = bc_cumulative_series(actual, bc)
    assert [p["v"] for p in out] == [100.0, 99.5, 99.5, 99.3]


def test_beat_the_open_puts_actual_above_daily_open_line():
    """Bought cheaper than the daily open → adjustment negative → bc line
    below actual (the gap = execution alpha GAINED)."""
    actual = snaps(95.84, 95.9)
    bc = [{"ts": T0, "v": 95.70}]           # post-fix sign: bc < actual
    out = bc_cumulative_series(actual, bc)
    assert out[0]["v"] == 95.70
    assert out[1]["v"] == 95.76             # actual 95.9 - 0.14 cumulative
    assert all(p["v"] < a["v"] for p, a in zip(out, actual))


def test_bc_point_before_history_uses_first_actual():
    actual = snaps(100, 101)
    bc = [{"ts": T0 - 5 * H, "v": 99.0}]    # adj vs first actual → -1.0
    out = bc_cumulative_series(actual, bc)
    assert [p["v"] for p in out] == [99.0, 100.0]


def test_empty_actual_returns_empty():
    assert bc_cumulative_series([], [{"ts": T0, "v": 1.0}]) == []


def test_malformed_bc_points_skipped():
    out = bc_cumulative_series(snaps(100, 100), [{"bad": 1}, {"ts": "x", "v": None}])
    assert [p["v"] for p in out] == [100.0, 100.0]

"""Portfolio math: XIRR, Modified-Dietz market index, metrics, series merge."""
from signalbot.strategies import (
    _xirr, _xnpv, _market_index, compute_portfolio_metrics,
    merge_equity_into_portfolio,
)

H = 3_600_000
DAY = 24 * H
YEAR_MS = int(365 * 86_400_000)
T0 = 1_700_000_000_000


def test_xnpv_at_zero_rate_is_sum():
    assert _xnpv(0.0, [(0.0, -1000.0), (1.0, 1100.0)]) == 100.0


def test_xirr_simple_10pct():
    r = _xirr([(0.0, -1000.0), (1.0, 1100.0)])
    assert r is not None
    assert abs(r - 0.10) < 1e-4


def test_xirr_requires_both_signs():
    assert _xirr([(0.0, -1000.0), (1.0, -100.0)]) is None
    assert _xirr([(0.0, 1000.0)]) is None
    assert _xirr([]) is None


def test_xirr_two_deposits():
    # 1000 at t0 + 1000 at 6mo → 2200 at 1yr; rate must be between the
    # naive 10% (all money full year) and 20%.
    r = _xirr([(0.0, -1000.0), (0.5, -1000.0), (1.0, 2200.0)])
    assert r is not None and 0.10 < r < 0.20


def test_market_index_no_flows():
    snaps = [{"ts": T0, "v": 1000.0}, {"ts": T0 + DAY, "v": 2000.0}]
    out = _market_index(snaps, [])
    assert out is not None
    _, idx = out
    assert idx == [1.0, 2.0]


def test_market_index_modified_dietz_mid_period_flow():
    # 1000 → deposit 500 at exactly mid-period → 2000.
    # Gain = 2000 - 1000 - 500 = 500 on a weighted base of 1000 + 500·0.5 = 1250.
    snaps = [{"ts": T0, "v": 1000.0}, {"ts": T0 + DAY, "v": 2000.0}]
    flows = [{"ts": T0 + DAY // 2, "amount": 500.0}]
    _, idx = _market_index(snaps, flows)
    assert abs(idx[-1] - 1.4) < 1e-9


def test_market_index_needs_two_points():
    assert _market_index([{"ts": T0, "v": 1000.0}], []) is None


def test_compute_portfolio_metrics_basic():
    snaps = [{"ts": T0, "v": 1000.0}, {"ts": T0 + YEAR_MS, "v": 1100.0}]
    flows = [{"ts": T0, "amount": 1000.0, "note": "deposit"}]
    m = compute_portfolio_metrics(snaps, flows, 1100.0)
    assert m["net_deposited"] == 1000.0
    assert m["true_pnl"] == 100.0
    assert abs(m["simple_return"] - 0.10) < 1e-9
    assert abs(m["twr"] - 0.10) < 1e-9
    assert len(m["injections"]) == 1
    assert abs(m["injections"][0]["contribution"] - 100.0) < 0.5


def test_metrics_withdrawal_counts_against_deposits():
    flows = [{"ts": T0, "amount": 1000.0}, {"ts": T0 + DAY, "amount": -400.0}]
    m = compute_portfolio_metrics([], flows, 700.0)
    assert m["net_deposited"] == 600.0
    assert m["true_pnl"] == 100.0


def test_merge_equity_into_portfolio():
    equity = [{"ts": T0, "v": 100.0}, {"ts": T0 + H, "v": 110.0}]
    port   = [{"ts": T0 + H + 60_000, "v": 999.0}]   # same hour as 2nd equity pt
    merged = merge_equity_into_portfolio(equity, port)
    assert len(merged) == 2
    assert merged[0]["v"] == 100.0     # backfilled from equity
    assert merged[1]["v"] == 999.0     # portfolio wins the shared hour


# ── Risk metrics (_risk_metrics via compute_portfolio_metrics) ───────────────

def _snaps_from_daily(values):
    """One snapshot per day at 12:00 UTC from a list of NAVs."""
    return [{"ts": T0 + i * DAY, "v": float(v)} for i, v in enumerate(values)]


def test_risk_metrics_basic_shape():
    from signalbot.strategies import _market_index, _risk_metrics
    snaps = _snaps_from_daily([100, 110, 99, 105, 112, 108])
    mkt = _market_index(snaps, [])
    r = _risk_metrics(*mkt)
    assert r["vol_annual"] > 0
    assert r["sharpe"] is not None
    assert r["sortino"] is not None
    assert r["best_day"]["r"] == 0.1          # 100 → 110
    assert abs(r["worst_day"]["r"] - (99 / 110 - 1)) < 1e-9
    assert abs(r["max_drawdown"] - (99 / 110 - 1)) < 1e-9
    assert r["cagr"] is not None and r["cagr"] > 0


def test_risk_metrics_flow_adjusted():
    """A deposit must not register as a gain in the risk stats."""
    from signalbot.strategies import _market_index, _risk_metrics
    snaps = _snaps_from_daily([100, 100, 100])
    snaps[1]["v"] = 200.0                      # NAV jump from a deposit...
    snaps[2]["v"] = 200.0
    flows = [{"ts": snaps[1]["ts"] - 1000, "amount": 100.0}]
    r = _risk_metrics(*_market_index(snaps, flows))
    assert r["best_day"]["r"] < 0.01           # index flat — no phantom +100%
    assert r["max_drawdown"] == 0.0


def test_risk_metrics_insufficient_history():
    from signalbot.strategies import _market_index, _risk_metrics
    snaps = _snaps_from_daily([100, 105])
    r = _risk_metrics(*_market_index(snaps, []))
    assert r["sharpe"] is None and r["vol_annual"] is None
    assert r["max_drawdown"] is not None       # dd still computable


def test_metrics_include_risk_block():
    snaps = _snaps_from_daily([100, 110, 99, 105])
    flows = [{"ts": T0 - DAY, "amount": 100.0}]
    m = compute_portfolio_metrics(snaps, flows, 105.0)
    assert "risk" in m
    assert m["risk"]["max_drawdown"] is not None


def test_metrics_risk_block_empty_history():
    m = compute_portfolio_metrics([], [], 0.0)
    assert m["risk"]["sharpe"] is None

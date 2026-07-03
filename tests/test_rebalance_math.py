"""compute_rebalance — pins the trade-computation behavior (RSPS logic is
frozen; these tests document and protect the current maths)."""
from signalbot.hyperliquid import compute_rebalance
from signalbot.config import MIN_TRADE_USD, MAX_SINGLE_ORDER_USD

SPOT_INDEX = {"ETH": "@151", "BTC": "@142", "HYPE": "@107"}


def alloc(asset, pct):
    return {"asset": asset, "percent": pct, "type": "Spot"}


def test_buy_from_cash_uses_spot():
    trades = compute_rebalance([alloc("ETH", 100)], 1000.0, {}, {"ETH": 2000.0},
                               SPOT_INDEX)
    assert len(trades) == 1
    t = trades[0]
    assert t["side"] == "buy"
    assert t["mode"] == "spot"
    assert t["ticker"] == "@151"          # HL spot orders use @universe_index
    assert abs(t["size"] - 0.5) < 1e-9


def test_perp_fallback_when_no_spot_market():
    trades = compute_rebalance([alloc("PAXG", 100)], 1000.0, {}, {"PAXG": 3000.0},
                               SPOT_INDEX)
    assert trades[0]["mode"] == "perp"
    assert trades[0]["ticker"] == "PAXG"


def test_leverage_forces_perp():
    trades = compute_rebalance([alloc("ETH", 100)], 1000.0, {}, {"ETH": 2000.0},
                               SPOT_INDEX, leverage_map={"ETH": 3})
    t = trades[0]
    assert t["mode"] == "perp"
    assert t["ticker"] == "ETH"
    assert t["leverage"] == 3


def test_sells_ordered_before_buys():
    positions = {"BTC": {"size": 0.02, "mark_px": 50_000.0, "mode": "spot"}}
    trades = compute_rebalance([alloc("ETH", 100)], 1000.0, positions,
                               {"ETH": 2000.0}, SPOT_INDEX)
    assert [t["side"] for t in trades] == ["sell", "buy"]


def test_small_delta_skipped():
    # Position already ~matches target; delta below MIN_TRADE_USD is dropped.
    positions = {"ETH": {"size": 0.499, "mark_px": 2000.0, "mode": "spot"}}
    trades = compute_rebalance([alloc("ETH", 100)], 1000.0, positions,
                               {"ETH": 2000.0}, SPOT_INDEX)
    assert trades == []
    assert 0.001 * 2000.0 < MIN_TRADE_USD  # the delta this test relies on


def test_full_exit_bypasses_min_trade():
    # Dust position with no target must still be fully closed.
    positions = {"HYPE": {"size": 0.1, "mark_px": 30.0, "mode": "spot"}}
    trades = compute_rebalance([alloc("ETH", 100)], 1000.0, positions,
                               {"ETH": 2000.0}, SPOT_INDEX)
    sells = [t for t in trades if t["side"] == "sell"]
    assert len(sells) == 1
    assert sells[0]["target_size"] == 0.0
    assert sells[0]["value_usd"] == 3.0 < MIN_TRADE_USD


def test_order_capped_at_max_single_order():
    trades = compute_rebalance([alloc("ETH", 100)], 200_000.0, {},
                               {"ETH": 2000.0}, SPOT_INDEX)
    assert trades[0]["value_usd"] == MAX_SINGLE_ORDER_USD
    assert abs(trades[0]["size"] - MAX_SINGLE_ORDER_USD / 2000.0) < 1e-9


def test_usdc_allocation_ignored():
    trades = compute_rebalance(
        [alloc("USDC", 100)], 1000.0, {}, {"USDC": 1.0}, SPOT_INDEX)
    assert trades == []


def test_mode_change_spot_to_perp_full_swap():
    """Raising leverage on an existing spot position closes spot and opens perp.
    Pins current behavior: the two legs are NOT subject to MIN/MAX trade caps."""
    positions = {"ETH": {"size": 0.5, "mark_px": 2000.0, "mode": "spot"}}
    trades = compute_rebalance([alloc("ETH", 100)], 1000.0, positions,
                               {"ETH": 2000.0}, SPOT_INDEX,
                               leverage_map={"ETH": 2})
    assert [t["side"] for t in trades] == ["sell", "buy"]
    sell, buy = trades
    assert sell["mode"] == "spot" and sell["ticker"] == "@151"
    assert buy["mode"] == "perp" and buy["ticker"] == "ETH"
    assert buy["leverage"] == 2
    assert abs(sell["size"] - 0.5) < 1e-9
    assert abs(buy["size"] - 0.5) < 1e-9

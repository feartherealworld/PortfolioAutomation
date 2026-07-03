"""parse_signal — pins the TRW signal-parsing behavior (RSPS logic is frozen;
these tests protect it from accidental change)."""
from signalbot.trw import parse_signal


STANDARD_SIGNAL = """Portfolio Signal Update

RSPS Signal:
**80% Spot $ETH**
**14.3% Spot $HYPE**
**5.7% Gold $PAXG / $XAUT**

Executive Summary: Rotation into ETH continues, gold hedge unchanged.
Associated Data: blah blah
"""


def test_standard_allocations():
    r = parse_signal(STANDARD_SIGNAL)
    allocs = {a["asset"]: a for a in r["allocations"]}
    assert not r["no_change"]
    assert allocs["ETH"]["percent"] == 80.0
    assert allocs["ETH"]["type"] == "Spot"
    assert allocs["HYPE"]["percent"] == 14.3
    assert "PAXG/XAUT" in allocs
    assert allocs["PAXG/XAUT"]["type"] == "Gold"
    assert abs(sum(a["percent"] for a in r["allocations"]) - 100.0) < 0.01


def test_no_change_detected():
    content = STANDARD_SIGNAL.replace(
        "Executive Summary: Rotation into ETH continues, gold hedge unchanged.",
        "Executive Summary: No change to the portfolio today.")
    r = parse_signal(content)
    assert r["no_change"] is True
    # Allocations are still parsed even when nothing changed
    assert r["allocations"]


def test_cash_signal():
    content = """Portfolio Signal Update

RSPS Signal:
**100% $CASH**

Executive Summary: Fully defensive.
"""
    r = parse_signal(content)
    assert len(r["allocations"]) == 1
    a = r["allocations"][0]
    assert a["asset"] == "USDC"
    assert a["type"] == "Cash"
    assert a["percent"] == 100.0


def test_btc_leverage_flag():
    content = STANDARD_SIGNAL + "\nBTC Leverage Signal = Impermissible\n"
    assert parse_signal(content)["btc_leverage"] == "Impermissible"
    content = STANDARD_SIGNAL + "\nBTC Leverage Signal = Permissible\n"
    assert parse_signal(content)["btc_leverage"] == "Permissible"
    assert parse_signal(STANDARD_SIGNAL)["btc_leverage"] is None


def test_garbage_yields_no_allocations():
    r = parse_signal("Good morning everyone, no signal here today.")
    assert r["allocations"] == []
    assert not r["no_change"]


def test_allocation_sum_guard_range():
    """do_rebalance aborts outside 90–110%; a parse missing an asset must not
    silently produce a plausible-but-wrong total."""
    partial = """RSPS Signal:
**47.3%** Spot $ETH

Executive Summary: rest of message got truncated
"""
    r = parse_signal(partial)
    total = sum(a["percent"] for a in r["allocations"])
    assert total < 90  # the safety gate in do_rebalance would refuse this

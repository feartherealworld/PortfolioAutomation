"""_sanitized_spot_meta — the fix for the no-spot-orders incident (2026-07-05):
an empty spot_meta left the SDK unable to resolve '@N' tickers, so every spot
order raised KeyError before reaching Hyperliquid."""
from signalbot.hyperliquid import _sanitized_spot_meta


class FakeInfo:
    def __init__(self, meta=None, raise_exc=False):
        self._meta = meta
        self._raise = raise_exc

    def spot_meta(self):
        if self._raise:
            raise RuntimeError("boom")
        return self._meta


GOOD_META = {
    "tokens": [{"name": "USDC", "szDecimals": 8},
               {"name": "PURR", "szDecimals": 0},
               {"name": "USOL", "szDecimals": 3}],
    "universe": [
        {"name": "PURR/USDC", "tokens": [1, 0], "index": 0, "isCanonical": True},
        {"name": "@156",      "tokens": [2, 0], "index": 156},
    ],
}


def test_valid_entries_pass_through():
    out = _sanitized_spot_meta(FakeInfo(GOOD_META))
    assert out["tokens"] == GOOD_META["tokens"]
    assert len(out["universe"]) == 2
    assert out["universe"][1]["name"] == "@156"


def test_out_of_range_entries_dropped():
    meta = {
        "tokens": GOOD_META["tokens"],
        "universe": GOOD_META["universe"] + [
            {"name": "@999", "tokens": [777, 0], "index": 999},   # token 777 missing
            {"name": "@998", "tokens": [-1, 0],  "index": 998},   # negative index
        ],
    }
    out = _sanitized_spot_meta(FakeInfo(meta))
    names = [p["name"] for p in out["universe"]]
    assert names == ["PURR/USDC", "@156"]        # broken entries gone
    assert out["tokens"] == meta["tokens"]        # tokens untouched


def test_fetch_failure_fails_open_empty():
    out = _sanitized_spot_meta(FakeInfo(raise_exc=True))
    assert out == {"tokens": [], "universe": []}

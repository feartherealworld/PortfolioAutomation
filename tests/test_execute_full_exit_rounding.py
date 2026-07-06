"""Full-exit size rounding in execute_trades — the daily 'Insufficient spot
balance asset=10107' incident: dust below one size step rounded UP past the
held balance, so HL rejected the sell on every rebalance."""
import pytest

from signalbot.hyperliquid import execute_trades


class FakeInfo:
    """spot @107 has szDecimals=2 (token idx 1); no perps needed."""
    def spot_meta(self):
        return {
            "tokens": [{"name": "USDC", "szDecimals": 8},
                       {"name": "HYPE", "szDecimals": 2}],
            "universe": [{"name": "@107", "tokens": [1, 0], "index": 107}],
        }

    def meta(self):
        return {"universe": []}


class FakeExchange:
    def __init__(self):
        self.orders = []

    def update_leverage(self, *a, **kw):
        pass

    def market_open(self, ticker, is_buy, sz, slippage):
        self.orders.append({"ticker": ticker, "is_buy": is_buy, "sz": sz})
        return {"status": "ok", "response": {"data": {"statuses": [
            {"filled": {"totalSz": str(sz), "avgPx": "50.0"}}]}}}


def full_exit(size):
    return {"asset": "HYPE", "ticker": "@107", "side": "sell", "size": size,
            "value_usd": size * 50.0, "price": 50.0, "mode": "spot",
            "leverage": 1, "target_size": 0.0}


@pytest.fixture(autouse=True)
def no_sleep(monkeypatch):
    monkeypatch.setattr("time.sleep", lambda s: None)


def test_dust_below_one_step_skips_instead_of_failing():
    """0.00855526 HYPE (2dp step) used to round UP to 0.01 > balance → HL
    'Insufficient spot balance'. Now it rounds down to 0 and is skipped."""
    ex = FakeExchange()
    results = execute_trades(FakeInfo(), ex, [full_exit(0.00855526)])
    assert results[0]["status"] == "skipped"
    assert results[0]["reason"] == "size rounded to 0"
    assert ex.orders == []                     # nothing sent to the exchange


def test_misaligned_balance_sells_the_sellable_part():
    """0.283 held → 0.29 would exceed the balance; falls back to 0.28."""
    ex = FakeExchange()
    results = execute_trades(FakeInfo(), ex, [full_exit(0.283)])
    assert results[0]["status"] == "filled"
    assert ex.orders[0]["sz"] == 0.28


def test_step_aligned_full_exit_unchanged():
    """A bot-created position (already step-aligned) sells exactly as before."""
    ex = FakeExchange()
    results = execute_trades(FakeInfo(), ex, [full_exit(0.28)])
    assert results[0]["status"] == "filled"
    assert ex.orders[0]["sz"] == 0.28


def test_buy_rounding_unchanged():
    ex = FakeExchange()
    trade = {"asset": "HYPE", "ticker": "@107", "side": "buy", "size": 0.288,
             "value_usd": 14.4, "price": 50.0, "mode": "spot",
             "leverage": 1, "target_size": 0.288}
    results = execute_trades(FakeInfo(), ex, [trade])
    assert results[0]["status"] == "filled"
    assert ex.orders[0]["sz"] == 0.28          # buys still ROUND_DOWN

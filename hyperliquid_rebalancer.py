"""
Hyperliquid Portfolio Rebalancer — Unified Account Edition

Trades spot assets by default. Falls back to 1x perp for assets with no spot
market on Hyperliquid (e.g. PAXG). Uses Hyperliquid's unified account mode so
spot holdings and perp margin share the same collateral pool.

On first run, ensure_unified_account() calls exchange.agent_set_abstraction("u")
which switches the account to unified mode. This is idempotent and safe to
call every run.

Asset routing:
  ETH, BTC, HYPE, SOL, DOGE, XRP  →  spot  (e.g. "ETH/USDC")
  PAXG, any unknown asset           →  1x perp
  USDC / Cash                       →  hold as USDC, no trade placed

Usage:
    python hyperliquid_rebalancer.py --status
    python hyperliquid_rebalancer.py --preview-live
    python hyperliquid_rebalancer.py --execute-live
    python hyperliquid_rebalancer.py --preview  signal.json
    python hyperliquid_rebalancer.py --execute  signal.json
"""

import os
import sys
import json
import argparse
import time
from decimal import Decimal, ROUND_DOWN
from pathlib import Path

import eth_account
from eth_account.signers.local import LocalAccount
from hyperliquid.exchange import Exchange
from hyperliquid.info import Info
from hyperliquid.utils import constants
from dotenv import load_dotenv

load_dotenv(Path(__file__).resolve().parent / ".env")

# ── Config ───────────────────────────────────────────────────────────────────

API_PRIVATE_KEY      = os.getenv("HYPERLIQUID_API_PRIVATE_KEY")
MASTER_ADDRESS       = os.getenv("HYPERLIQUID_MASTER_ACCOUNT_ADDRESS")

MIN_TRADE_USD        = 10.0      # HL spot min order is $10
MAX_SLIPPAGE         = 0.03      # 3% max slippage on market orders
MAX_SINGLE_ORDER_USD = 50_000    # Safety cap per single order

# Canonical perp ticker for each signal asset name
ASSET_TO_TICKER: dict[str, str] = {
    "ETH":      "ETH",
    "BTC":      "BTC",
    "HYPE":     "HYPE",
    "SOL":      "SOL",
    "DOGE":     "DOGE",
    "XRP":      "XRP",
    "PAXG/XAUT":"PAXG",
    "PAXG":     "PAXG",
    "XAUT":     "PAXG",
    "GOLD":     "PAXG",
    "USDC":     "USDC",
}

# Assets with a liquid spot market on Hyperliquid.
# Anything not here falls back to a 1x perp.
SPOT_ASSETS: frozenset[str] = frozenset({"ETH", "BTC", "HYPE", "SOL", "DOGE", "XRP"})


# ── Client setup ──────────────────────────────────────────────────────────────

def get_clients() -> tuple[Info, Exchange]:
    if not API_PRIVATE_KEY or not MASTER_ADDRESS:
        print("ERROR: HYPERLIQUID_API_PRIVATE_KEY and "
              "HYPERLIQUID_MASTER_ACCOUNT_ADDRESS must be set in .env",
              file=sys.stderr)
        sys.exit(1)
    wallet: LocalAccount = eth_account.Account.from_key(API_PRIVATE_KEY)
    info     = Info(constants.MAINNET_API_URL, skip_ws=True)
    exchange = Exchange(wallet, constants.MAINNET_API_URL,
                        account_address=MASTER_ADDRESS)
    return info, exchange


def ensure_unified_account(exchange: Exchange, info: Info) -> None:
    """
    Switch the account to unified mode so spot holdings and perp margin share
    one collateral pool. agent_set_abstraction("u") is idempotent.
    """
    try:
        state = info.query_user_abstraction_state(MASTER_ADDRESS)
        if state and state.get("abstraction") == "unifiedAccount":
            print("  Unified account: already active.")
            return
    except Exception:
        pass  # method may not exist on older SDK builds — try to set anyway

    print("  Activating unified account mode…", end=" ")
    result = exchange.agent_set_abstraction("u")
    if result.get("status") == "ok":
        print("OK")
    else:
        print(f"\n  WARNING: could not activate unified account: {result}",
              file=sys.stderr)


# ── Spot market helpers ───────────────────────────────────────────────────────

def build_spot_index(info: Info) -> dict[str, str]:
    """
    Build a map of canonical ticker → spot pair name used by the SDK,
    e.g.  "ETH" → "ETH/USDC",  "BTC" → "BTC/USDC".
    Reads spot_meta() so we never hard-code pair names.
    """
    mapping: dict[str, str] = {}
    try:
        meta   = info.spot_meta()
        tokens = meta.get("tokens", [])
        idx_to_name = {i: t.get("name", "") for i, t in enumerate(tokens)}
        for pair in meta.get("universe", []):
            t = pair.get("tokens", [])
            if len(t) == 2 and t[1] == 0:        # quote is USDC (index 0)
                raw_name  = idx_to_name.get(t[0], "")
                pair_name = pair.get("name", "")
                if raw_name and pair_name:
                    # HL names BTC's native token "UBTC" — strip leading U
                    clean = raw_name.lstrip("U").upper()
                    mapping[clean]          = pair_name
                    mapping[raw_name.upper()] = pair_name
    except Exception as e:
        print(f"WARNING: spot_meta lookup failed: {e}", file=sys.stderr)
    return mapping


def get_spot_sz_decimals(info: Info) -> dict[str, int]:
    """Return pair_name → szDecimals for all spot pairs."""
    result: dict[str, int] = {}
    try:
        meta = info.spot_meta()
        for pair in meta.get("universe", []):
            result[pair["name"]] = pair.get("szDecimals", 2)
    except Exception:
        pass
    return result


# ── Account state ─────────────────────────────────────────────────────────────

def get_account_state(info: Info) -> dict:
    """
    Unified state: merges perp positions and spot holdings.

    positions key is the canonical ticker (e.g. "ETH", "PAXG").
    Each entry has: size, entry_px, unrealized_pnl, value_usd, mode ("spot"/"perp").
    """
    state         = info.user_state(MASTER_ADDRESS)
    margin        = state["marginSummary"]
    perp_value = float(margin["accountValue"])
    positions: dict[str, dict] = {}

    # Perp positions
    for pos in state.get("assetPositions", []):
        p    = pos["position"]
        coin = p["coin"]
        size = float(p.get("szi", 0))
        if size == 0:
            continue
        entry_px = float(p["entryPx"]) if p.get("entryPx") else 0
        positions[coin] = {
            "size":           size,
            "entry_px":       entry_px,
            "unrealized_pnl": float(p.get("unrealizedPnl", 0)),
            "value_usd":      abs(size) * entry_px,
            "mode":           "perp",
        }

    # Spot balances — add to total and track as positions
    spot_total_usd = 0.0
    try:
        spot_state = info.spot_user_state(MASTER_ADDRESS)
        all_mids   = info.all_mids()
        for bal in spot_state.get("balances", []):
            coin_raw = bal["coin"].upper()
            total    = float(bal.get("total", 0))
            if total <= 0:
                continue
            if coin_raw == "USDC":
                spot_total_usd += total   # idle cash
                continue
            # Normalise e.g. "UBTC" → "BTC"
            canon = coin_raw.lstrip("U")
            price = float(all_mids.get(canon, all_mids.get(coin_raw, 0)))
            value = total * price
            spot_total_usd += value
            positions[canon] = {
                "size":           total,
                "entry_px":       price,
                "unrealized_pnl": 0.0,
                "value_usd":      value,
                "mode":           "spot",
            }
    except Exception as e:
        print(f"WARNING: spot balance fetch failed: {e}", file=sys.stderr)

    account_value = perp_value + spot_total_usd
    return {"account_value": account_value, "positions": positions}


def get_current_prices(info: Info, assets: list[str]) -> dict[str, float]:
    all_mids = info.all_mids()
    prices: dict[str, float] = {}
    for asset in assets:
        ticker = ASSET_TO_TICKER.get(asset, asset)
        if ticker == "USDC":
            prices[asset] = 1.0
        elif ticker in all_mids:
            prices[asset] = float(all_mids[ticker])
        else:
            print(f"WARNING: no price for {asset} (ticker: {ticker})",
                  file=sys.stderr)
    return prices


# ── Rebalancing logic ─────────────────────────────────────────────────────────

def compute_rebalance(
    allocations:       list[dict],
    account_value:     float,
    current_positions: dict,
    prices:            dict[str, float],
    spot_index:        dict[str, str],
) -> list[dict]:
    """
    Compute the trades needed to reach target allocations.

    Returns list of trade dicts:
        asset, ticker, side, size, value_usd, price, mode,
        current_size, target_size
    """
    trades: list[dict] = []
    target_map: dict[str, dict] = {}   # canonical ticker → target

    for alloc in allocations:
        asset  = alloc["asset"]
        ticker = ASSET_TO_TICKER.get(asset, asset)
        if ticker == "USDC":
            continue
        if asset not in prices:
            continue

        target_usd  = account_value * (alloc["percent"] / 100.0)
        target_size = target_usd / prices[asset]
        use_spot    = ticker in SPOT_ASSETS and ticker in spot_index
        trade_ticker = spot_index[ticker] if use_spot else ticker

        target_map[ticker] = {
            "asset":        asset,
            "ticker":       trade_ticker,
            "target_usd":   target_usd,
            "target_size":  target_size,
            "price":        prices[asset],
            "mode":         "spot" if use_spot else "perp",
        }

    all_tickers = set(target_map.keys())
    for coin in current_positions:
        if current_positions[coin].get("size", 0) != 0:
            all_tickers.add(coin)

    for canon in all_tickers:
        cur_pos      = current_positions.get(canon, {})
        current_size = cur_pos.get("size", 0)
        target       = target_map.get(canon)

        if target:
            target_size  = target["target_size"]
            price        = target["price"]
            asset        = target["asset"]
            mode         = target["mode"]
            trade_ticker = target["ticker"]
        else:
            # Not in new signal — close existing position
            price = cur_pos.get("entry_px", 0)
            if not price:
                print(f"WARNING: no price to close {canon}, skipping",
                      file=sys.stderr)
                continue
            target_size  = 0.0
            asset        = canon
            mode         = cur_pos.get("mode", "perp")
            trade_ticker = (spot_index.get(canon, f"{canon}/USDC")
                            if mode == "spot" else canon)

        delta_size = target_size - current_size
        delta_usd  = abs(delta_size) * price

        if delta_usd < MIN_TRADE_USD:
            continue

        if delta_usd > MAX_SINGLE_ORDER_USD:
            print(f"WARNING: capping {asset} trade from ${delta_usd:.0f} "
                  f"to ${MAX_SINGLE_ORDER_USD}", file=sys.stderr)
            delta_size = (MAX_SINGLE_ORDER_USD / price) * (1 if delta_size > 0 else -1)
            delta_usd  = MAX_SINGLE_ORDER_USD

        trades.append({
            "asset":        asset,
            "ticker":       trade_ticker,
            "side":         "buy" if delta_size > 0 else "sell",
            "size":         abs(delta_size),
            "value_usd":    delta_usd,
            "price":        price,
            "mode":         mode,
            "current_size": current_size,
            "target_size":  target_size,
        })

    # Sells first to free collateral, then largest buys first
    trades.sort(key=lambda t: (0 if t["side"] == "sell" else 1, -t["value_usd"]))
    return trades


# ── Execution ─────────────────────────────────────────────────────────────────

def execute_trades(info: Info, exchange: Exchange,
                   trades: list[dict]) -> list[dict]:
    results: list[dict] = []
    spot_sz_map  = get_spot_sz_decimals(info)
    perp_meta    = {a["name"]: a["szDecimals"] for a in info.meta()["universe"]}

    # Pre-set 1x leverage for perp tickers
    perp_tickers    = {t["ticker"] for t in trades if t["mode"] == "perp"}
    leverage_ok:     set[str] = set()
    leverage_failed: set[str] = set()
    for ticker in perp_tickers:
        print(f"  Setting {ticker} to 1x cross leverage…", end=" ")
        try:
            exchange.update_leverage(1, ticker, is_cross=True)
            leverage_ok.add(ticker)
            print("OK")
        except Exception as e:
            print(f"FAILED: {e}")
            leverage_failed.add(ticker)
        time.sleep(0.3)

    for trade in trades:
        ticker = trade["ticker"]
        mode   = trade["mode"]
        is_buy = trade["side"] == "buy"

        if mode == "perp" and ticker in leverage_failed:
            print(f"  SKIP {ticker} — leverage not confirmed")
            results.append({**trade, "status": "skipped",
                             "reason": "leverage set failed"})
            continue

        sz_dec = (spot_sz_map.get(ticker) or perp_meta.get(ticker) or 2)
        size   = float(
            Decimal(str(trade["size"]))
            .quantize(Decimal(10) ** -sz_dec, rounding=ROUND_DOWN)
        )
        if size == 0:
            results.append({**trade, "status": "skipped",
                             "reason": "size rounded to 0"})
            continue

        label = "SPOT" if mode == "spot" else "PERP"
        print(f"  {'BUY' if is_buy else 'SELL'} {size} {ticker} "
              f"(~${trade['value_usd']:.2f}) [{label}]…", end=" ")

        try:
            result = exchange.market_open(
                ticker,
                is_buy=is_buy,
                sz=size,
                slippage=MAX_SLIPPAGE,
            )
            if result["status"] == "ok":
                for status in result["response"]["data"]["statuses"]:
                    if "filled" in status:
                        f = status["filled"]
                        print(f"FILLED {f['totalSz']} @ ${f['avgPx']}")
                        results.append({**trade, "status": "filled",
                                        "filled_size": float(f["totalSz"]),
                                        "avg_price":   float(f["avgPx"])})
                    elif "error" in status:
                        print(f"ERROR: {status['error']}")
                        results.append({**trade, "status": "error",
                                        "error": status["error"]})
                    elif "resting" in status:
                        print("RESTING")
                        results.append({**trade, "status": "resting"})
            else:
                err = result.get("response", {}).get("data", str(result))
                print(f"FAILED: {err}")
                results.append({**trade, "status": "failed", "error": str(err)})
        except Exception as e:
            print(f"EXCEPTION: {e}")
            results.append({**trade, "status": "exception", "error": str(e)})

        time.sleep(0.5)

    return results


# ── Display ───────────────────────────────────────────────────────────────────

def print_status(info: Info) -> None:
    state = get_account_state(info)
    print(f"\nAccount Value: ${state['account_value']:.2f}")
    if not state["positions"]:
        print("No open positions.")
        return
    print(f"\n  {'Asset':<8} {'Mode':<5} {'Size':>10} {'Entry':>10} "
          f"{'Value':>10} {'PnL':>10}")
    print("  " + "─" * 58)
    for coin, pos in state["positions"].items():
        print(f"  {coin:<8} {pos['mode'].upper():<5} {pos['size']:>10.4f} "
              f"{pos['entry_px']:>10.2f} "
              f"${pos['value_usd']:>9.2f} ${pos['unrealized_pnl']:>9.2f}")


def print_preview(trades: list[dict], account_value: float) -> None:
    if not trades:
        print("No trades needed — portfolio already matches signal.")
        return
    print(f"\nPlanned trades (account: ${account_value:.2f}):")
    print(f"  {'Action':<6} {'Ticker':<12} {'Mode':<5} {'Size':>10} "
          f"{'Value':>10} {'Price':>10}")
    print("  " + "─" * 60)
    total = 0.0
    for t in trades:
        print(f"  {t['side'].upper():<6} {t['ticker']:<12} "
              f"{t['mode'].upper():<5} {t['size']:>10.4f} "
              f"${t['value_usd']:>9.2f} ${t['price']:>9.2f}")
        total += t["value_usd"]
    print("  " + "─" * 60)
    print(f"  Total volume: ${total:.2f}")


# ── Signal loading ─────────────────────────────────────────────────────────────

def load_signal_live() -> dict:
    sys.path.insert(0, str(Path(__file__).resolve().parent))
    from trw_signal_reader import fetch_recent_messages, find_latest_signal, parse_signal
    msgs   = fetch_recent_messages(limit=20)
    msg    = find_latest_signal(msgs)
    if not msg:
        print("ERROR: No signal found in TRW channel.", file=sys.stderr)
        sys.exit(1)
    return parse_signal(msg["content"])


# ── CLI ───────────────────────────────────────────────────────────────────────

def main() -> None:
    parser = argparse.ArgumentParser(
        description="Hyperliquid Unified Portfolio Rebalancer")
    grp = parser.add_mutually_exclusive_group(required=True)
    grp.add_argument("--status",       action="store_true",
                     help="Show account state")
    grp.add_argument("--preview",      type=str, nargs="?", const="__live__",
                     help="Preview trades (path or live)")
    grp.add_argument("--execute",      type=str, nargs="?", const="__live__",
                     help="Execute trades (path or live)")
    grp.add_argument("--preview-live", action="store_true",
                     help="Preview using live TRW signal")
    grp.add_argument("--execute-live", action="store_true",
                     help="Execute using live TRW signal")
    args = parser.parse_args()

    info, exchange = get_clients()

    if args.status:
        ensure_unified_account(exchange, info)
        print_status(info)
        return

    ensure_unified_account(exchange, info)

    is_live = (args.preview_live or args.execute_live
               or args.preview == "__live__" or args.execute == "__live__")
    signal  = load_signal_live() if is_live else \
              json.load(open(args.preview or args.execute))

    if signal.get("no_change"):
        print("Signal says NO CHANGE. Nothing to do.")
        return

    total_pct = sum(a["percent"] for a in signal["allocations"])
    if not (90 <= total_pct <= 110):
        print(f"ERROR: allocations sum to {total_pct:.1f}% — possible parse failure.",
              file=sys.stderr)
        sys.exit(1)

    state         = get_account_state(info)
    account_value = state["account_value"]
    if account_value < 1.0:
        print(f"ERROR: account value ${account_value:.2f} too low.", file=sys.stderr)
        sys.exit(1)

    prices     = get_current_prices(info, [a["asset"] for a in signal["allocations"]])
    spot_index = build_spot_index(info)
    trades     = compute_rebalance(signal["allocations"], account_value,
                                   state["positions"], prices, spot_index)

    is_execute = args.execute is not None or args.execute_live
    print_preview(trades, account_value)
    if not trades or not is_execute:
        return

    print(f"\nExecuting {len(trades)} trades…")
    results = execute_trades(info, exchange, trades)
    filled  = [r for r in results if r["status"] == "filled"]
    failed  = [r for r in results if r["status"] in ("error", "failed", "exception")]
    print(f"\nDone: {len(filled)} filled, {len(failed)} failed "
          f"out of {len(results)} trades.")
    if failed:
        for f in failed:
            print(f"  FAIL {f['side'].upper()} {f['ticker']}: {f.get('error', '?')}")


if __name__ == "__main__":
    main()
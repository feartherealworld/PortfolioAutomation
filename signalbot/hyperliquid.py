import os
import json
import re
import time
import hmac
import secrets
from datetime import datetime, timezone
from decimal import Decimal, ROUND_DOWN
from signalbot.config import *
from signalbot.notify import *

__all__ = [
    'get_hl_clients',
    'HlInfo',
    'safe_all_mids',
    'ensure_unified_account',
    'build_spot_index',
    'get_daily_open_prices',
    'get_account_state',
    'get_current_prices',
    'compute_rebalance',
    'execute_trades',
]



def _sanitized_spot_meta(info) -> dict:
    """
    Real spot metadata with broken universe entries removed.

    HL sometimes publishes spot_meta whose universe references token indices
    beyond tokens[] — that crashes the SDK Info constructor ("list index out
    of range"). The old workaround passed an EMPTY spot_meta, which silently
    broke every spot order: the SDK had no '@N' entries in its ticker map, so
    exchange.market_open('@156', ...) raised KeyError before any order was
    sent (root cause of the no-trades-since-May incident, fixed 2026-07-05).
    Keeping only in-range universe entries restores spot execution while
    still dodging the constructor crash.
    """
    try:
        meta   = info.spot_meta()
        tokens = meta.get("tokens", [])
        n      = len(tokens)
        universe = [p for p in meta.get("universe", [])
                    if all(isinstance(t, int) and 0 <= t < n
                           for t in p.get("tokens", []))]
        dropped = len(meta.get("universe", [])) - len(universe)
        if dropped:
            print(f"[spot_meta] dropped {dropped} broken universe entries")
        return {"tokens": tokens, "universe": universe}
    except Exception as e:
        # Fail open (empty meta): perp trading keeps working; spot orders
        # would fail loudly in execute_trades and reach Slack.
        print(f"[spot_meta] sanitize failed ({e}) — spot orders unavailable this run")
        return {"tokens": [], "universe": []}


def get_hl_clients():
    import eth_account as _ea
    from hyperliquid.exchange import Exchange
    from hyperliquid.utils import constants
    wallet = _ea.Account.from_key(os.environ["HYPERLIQUID_API_PRIVATE_KEY"])
    addr   = os.environ["HYPERLIQUID_MASTER_ACCOUNT_ADDRESS"]
    url    = constants.MAINNET_API_URL

    # Use HlInfo (our own wrapper) instead of the SDK's Info class.
    # The SDK's Info.__init__ crashes with "list index out of range" when HL's
    # spot_meta["universe"] references token indices beyond tokens[] length.
    # HlInfo makes raw HTTP calls to the same endpoints — no broken constructor.
    info = HlInfo(url)

    # The Exchange needs real (sanitized) spot metadata so it can resolve
    # spot tickers like "@156" to asset ids when placing orders.
    exchange = Exchange(wallet, url, account_address=addr,
                        spot_meta=_sanitized_spot_meta(info))
    return info, exchange


class HlInfo:
    """
    Drop-in replacement for hyperliquid.info.Info using direct HTTP calls.
    Avoids the SDK constructor crash caused by HL's spot_meta token index mismatch.
    All methods match the SDK's Info API so the rest of the code works unchanged.
    """
    HL_URL = "https://api.hyperliquid.xyz"

    def __init__(self, base_url: str = "https://api.hyperliquid.xyz"):
        import requests as _req
        self._url  = base_url.rstrip("/")
        self._sess = _req.Session()
        self._sess.headers.update({"Content-Type": "application/json"})

    def _post(self, payload: dict) -> dict:
        r = self._sess.post(f"{self._url}/info", json=payload, timeout=15)
        r.raise_for_status()
        return r.json()

    def user_state(self, address: str) -> dict:
        return self._post({"type": "clearinghouseState", "user": address})

    def spot_user_state(self, address: str) -> dict:
        return self._post({"type": "spotClearinghouseState", "user": address})

    def meta(self) -> dict:
        return self._post({"type": "meta"})

    def spot_meta(self) -> dict:
        return self._post({"type": "spotMeta"})

    def all_mids(self) -> dict:
        raw = self._post({"type": "allMids"})
        # allMids returns {"ETH": "2000.5", ...} — convert values to float
        if isinstance(raw, dict):
            return {k: float(v) for k, v in raw.items()}
        return {}

    def query_order_by_oid(self, address: str, oid: int) -> dict:
        return self._post({"type": "orderStatus", "user": address, "oid": oid})

    def open_orders(self, address: str) -> list:
        return self._post({"type": "openOrders", "user": address})

    def candle_snapshot(self, coin: str, interval: str,
                        start_time: int, end_time: int) -> list:
        return self._post({"type": "candleSnapshot", "req": {
            "coin": coin, "interval": interval,
            "startTime": start_time, "endTime": end_time,
        }})



def safe_all_mids(info) -> dict[str, float]:
    """Fetch mid prices as {ticker: float}. Works with both HlInfo and SDK Info."""
    try:
        raw = info.all_mids()
        if isinstance(raw, dict):
            return {k: float(v) for k, v in raw.items() if v is not None}
        return {}
    except Exception as e:
        print(f"all_mids fetch failed: {e}")
        return {}


def ensure_unified_account(exchange, info) -> None:
    """
    Activate unified account mode (idempotent). Only logs — never sends Slack.
    The HL SDK may return "Abstraction transition not allowed" when the account
    is already unified; we treat that as success.
    query_user_abstraction_state() may not exist on all SDK builds — we catch
    that and fall through to agent_set_abstraction which is safe to call again.
    """
    address = os.environ["HYPERLIQUID_MASTER_ACCOUNT_ADDRESS"]
    try:
        state = info.query_user_abstraction_state(address)
        if state and state.get("abstraction") == "unifiedAccount":
            print("Unified account: already active.")
            return
    except Exception:
        pass  # method absent on this SDK build — fall through

    result = exchange.agent_set_abstraction("u")
    msg    = str(result)
    if result.get("status") == "ok":
        print("Unified account: activated.")
    elif "transition not allowed" in msg.lower() or "already" in msg.lower():
        print("Unified account: already active (HL confirmed).")
    else:
        # Log unexpected response — happens occasionally when HL is slow.
        # Not Slacked because it runs on every rebalance and is non-fatal.
        print(f"Unified account activation note: {result}")


def build_spot_index(info) -> dict[str, str]:
    """
    Return canonical ticker → HL spot asset identifier for use in orders.

    HL API rules (from docs):
      - PURR/USDC  → use the pair name "PURR/USDC"  (isCanonical=true, index=0)
      - All others → use "@{universe_index}"  e.g. HYPE → "@107"
    The pair-name format ("HYPE/USDC") is NOT accepted by the exchange endpoint
    for non-canonical pairs — it will return "Invalid size" or asset-not-found errors.
    """
    mapping: dict[str, str] = {}
    try:
        meta        = info.spot_meta()
        tokens      = meta.get("tokens", [])
        # token index → canonical uppercase name (strip leading U for bridged tokens)
        idx_to_name: dict[int, str] = {}
        for i, t in enumerate(tokens):
            raw = t.get("name", "")
            if raw:
                idx_to_name[i] = raw.upper()

        for pair in meta.get("universe", []):
            t          = pair.get("tokens", [])
            pair_index = pair.get("index", None)   # universe index → "@{index}"
            pair_name  = pair.get("name", "")       # e.g. "PURR/USDC" or "@1"
            is_canonical = pair.get("isCanonical", False)

            if len(t) != 2 or t[1] != 0:   # quote must be USDC (token 0)
                continue
            if pair_index is None:
                continue

            raw_name = idx_to_name.get(t[0], "")
            if not raw_name:
                continue

            # Canonical name used by the rest of our code (strip U-prefix)
            clean = raw_name.lstrip("U") if raw_name.startswith("U") and len(raw_name) > 1 else raw_name

            # Trade identifier: PURR/USDC by pair name, everything else by @index
            if is_canonical and pair_name and not pair_name.startswith("@"):
                trade_id = pair_name          # "PURR/USDC"
            else:
                trade_id = f"@{pair_index}"   # "@107" for HYPE, "@0" for BTC/USDC etc.

            # Map both the clean name and the raw name so lookups always hit
            mapping[clean]             = trade_id
            mapping[raw_name]          = trade_id
            if pair_name and not pair_name.startswith("@"):
                mapping[pair_name]     = trade_id  # also accept "HYPE/USDC" as input key

    except Exception as e:
        print(f"build_spot_index failed: {e}")
    return mapping


def get_daily_open_prices(assets: list[str], signal_ts_ms: int) -> dict[str, float]:
    """
    Fetch the UTC 00:00 price for each asset on the day the signal was released.

    "Bar close" is defined as: the open price of the daily candle on the signal date,
    which equals the price at exactly midnight UTC (00:00) of that day.
    This represents "what would the portfolio be worth if rebalanced at the daily
    open instead of at the intraday signal price?"

    Example: signal released Tuesday 14:30 UTC → we fetch the Tuesday 1d candle
    open price = Tuesday 00:00 UTC price.

    Falls back to the 00:00 1h candle open if 1d data is unavailable.
    """
    import requests as req
    from datetime import datetime, timezone

    prices: dict[str, float] = {}
    signal_dt   = datetime.fromtimestamp(signal_ts_ms / 1000, tz=timezone.utc)
    midnight_dt = signal_dt.replace(hour=0, minute=0, second=0, microsecond=0)
    midnight_ms = int(midnight_dt.timestamp() * 1000)

    for asset in assets:
        ticker = ASSET_TO_TICKER.get(asset, asset)
        if ticker == "USDC":
            continue
        fetched = False
        for interval, window_ms in [("1d", 86_400_000), ("1h", 3_600_000)]:
            try:
                resp = req.post(
                    "https://api.hyperliquid.xyz/info",
                    json={"type": "candleSnapshot", "req": {
                        "coin":      ticker,
                        "interval":  interval,
                        "startTime": midnight_ms,
                        "endTime":   midnight_ms + window_ms,
                    }},
                    timeout=10,
                )
                candles = resp.json()
                if not isinstance(candles, list) or not candles:
                    continue
                # Open of first candle = price at midnight UTC of the signal date
                prices[asset] = float(candles[0]["o"])
                print(f"[bar_close] {asset} 00:00 UTC {midnight_dt.date()}: "
                      f"${prices[asset]:.4f}  (signal at {signal_dt.strftime('%H:%M UTC')})")
                fetched = True
                break
            except Exception as e:
                print(f"[bar_close] {interval} failed for {asset}: {e}")
        if not fetched:
            print(f"[bar_close] WARNING: no 00:00 price for {asset} on {midnight_dt.date()}")
    return prices


def get_account_state(info) -> dict:
    """
    Unified account state: positions + total equity.

    On HL unified account, spot_user_state is the source of truth for total
    balance. marginSummary.accountValue only reflects USDC locked in the perp
    margin engine — it does NOT include spot token holdings.

    Correct total = USDC (spot) + Σ(spot token qty × mark_px) + perp uPnL
    """
    address    = os.environ["HYPERLIQUID_MASTER_ACCOUNT_ADDRESS"]
    state      = info.user_state(address)
    positions: dict[str, dict] = {}

    all_mids: dict = {}
    try:
        all_mids = safe_all_mids(info)
        if not isinstance(all_mids, dict):
            print(f"[warning] safe_all_mids returned {type(all_mids)}, resetting to {{}}")
            all_mids = {}
    except Exception as e:
        import traceback
        print(f"all_mids fetch failed:\n{traceback.format_exc()}")

    # Perp positions — contribute uPnL to total, not notional
    perp_upnl = 0.0
    for pos in state.get("assetPositions", []):
        p    = pos["position"]
        coin = p["coin"]
        size = float(p.get("szi", 0))
        if size == 0:
            continue
        entry_px = float(p["entryPx"]) if p.get("entryPx") else 0
        mark_px  = float(all_mids.get(coin, entry_px))
        upnl     = float(p.get("unrealizedPnl", 0))
        perp_upnl += upnl
        positions[coin] = {
            "size":           size,
            "entry_px":       entry_px,
            "mark_px":        mark_px,
            "unrealized_pnl": upnl,
            "value_usd":      abs(size) * mark_px,
            "mode":           "perp",
        }

    # Spot balances — source of truth for total value on unified accounts
    usdc_balance   = 0.0
    spot_token_usd = 0.0
    try:
        spot_state = info.spot_user_state(address)
        for bal in spot_state.get("balances", []):
            coin_raw = bal["coin"].upper()
            total    = float(bal.get("total", 0))
            if total <= 0:
                continue
            if coin_raw == "USDC":
                usdc_balance = total
                continue

            canon   = coin_raw.lstrip("U") if coin_raw.startswith("U") and len(coin_raw) > 1 else coin_raw
            mark_px = float(all_mids.get(canon, all_mids.get(coin_raw, 0)))
            value   = total * mark_px
            spot_token_usd += value

            entry_ntl = float(bal.get("entryNtl") or bal.get("entryCost") or 0)
            if entry_ntl > 0 and total > 0:
                entry_px       = entry_ntl / total
                unrealized_pnl = value - entry_ntl
            elif mark_px > 0:
                entry_px       = mark_px
                unrealized_pnl = 0.0
            else:
                entry_px       = 0.0
                unrealized_pnl = 0.0

            positions[canon] = {
                "size":           total,
                "entry_px":       entry_px,
                "mark_px":        mark_px,
                "unrealized_pnl": unrealized_pnl,
                "value_usd":      value,
                "mode":           "spot",
            }
    except Exception as e:
        print(f"spot balance fetch failed: {e}")
        # Fallback: use marginSummary if spot fetch fails
        usdc_balance = float(state["marginSummary"]["accountValue"])

    # USDC (incl. perp margin reserve) + spot token values + open perp uPnL
    account_value = usdc_balance + spot_token_usd + perp_upnl

    return {"account_value": account_value, "positions": positions}


def get_current_prices(info, assets: list[str]) -> dict[str, float]:
    all_mids = safe_all_mids(info)
    prices: dict[str, float] = {}
    for asset in assets:
        ticker = ASSET_TO_TICKER.get(asset, asset)
        if ticker == "USDC":
            prices[asset] = 1.0
        elif ticker in all_mids:
            prices[asset] = float(all_mids[ticker])
    return prices


def compute_rebalance(allocations, account_value, current_positions,
                      prices, spot_index,
                      leverage_map: dict | None = None) -> list[dict]:
    """
    Compute trades to reach target allocations.

    leverage_map: {asset → leverage_multiplier}
      - 1 (or missing) → use spot if available, else 1x perp
      - >1             → force perp with that leverage
      - 0              → skip (manual override to hold nothing)

    Size is always the notional position size (USD / price).
    HL handles margin requirements internally — we just set the leverage
    via exchange.update_leverage before placing the order.
    """
    leverage_map = leverage_map or {}
    trades:     list[dict] = []
    target_map: dict[str, dict] = {}

    for alloc in allocations:
        asset  = alloc["asset"]
        ticker = ASSET_TO_TICKER.get(asset, asset)
        if ticker == "USDC" or asset not in prices:
            continue

        lev = leverage_map.get(asset, leverage_map.get(ticker, 1))
        try:
            lev = max(1, int(lev))
        except (TypeError, ValueError):
            lev = 1

        target_usd  = account_value * (alloc["percent"] / 100.0)
        target_size = target_usd / prices[asset]

        # Force perp if leverage > 1, otherwise use spot if available
        if lev > 1:
            use_spot     = False
            trade_ticker = ticker
        else:
            use_spot     = ticker in SPOT_ASSETS and ticker in spot_index
            trade_ticker = spot_index[ticker] if use_spot else ticker

        target_map[ticker] = {
            "asset":        asset,
            "ticker":       trade_ticker,
            "target_size":  target_size,
            "price":        prices[asset],
            "mode":         "spot" if use_spot else "perp",
            "leverage":     lev,
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
            leverage     = target["leverage"]
        else:
            price = cur_pos.get("mark_px", cur_pos.get("entry_px", 0))
            if not price:
                continue
            target_size  = 0.0
            asset        = canon
            mode         = cur_pos.get("mode", "perp")
            leverage     = 1
            trade_ticker = (spot_index.get(canon, spot_index.get(f"U{canon}", canon))
                            if mode == "spot" else canon)

        delta_size   = target_size - current_size
        delta_usd    = abs(delta_size) * price
        is_full_exit = target_size == 0.0 and current_size != 0

        # If the asset needs to switch instruments (spot→perp or perp→spot),
        # treat it as a full exit + full entry regardless of size delta.
        current_mode = cur_pos.get("mode", "perp") if cur_pos else None
        mode_change  = current_mode is not None and current_size != 0 and current_mode != mode

        if mode_change:
            # Close the existing position fully, then open in the new instrument.
            # Two separate trade entries — sell old mode, buy new mode.
            old_ticker = (spot_index.get(canon, spot_index.get(f"U{canon}", canon))
                          if current_mode == "spot" else canon)
            trades.append({
                "asset":       canon,
                "ticker":      old_ticker,
                "side":        "sell",
                "size":        abs(current_size),
                "value_usd":   abs(current_size) * price,
                "price":       price,
                "mode":        current_mode,
                "leverage":    1,
                "target_size": 0.0,
                "_reason":     f"mode change {current_mode}→{mode}",
            })
            trades.append({
                "asset":       asset,
                "ticker":      trade_ticker,
                "side":        "buy",
                "size":        target_size,
                "value_usd":   target_size * price,
                "price":       price,
                "mode":        mode,
                "leverage":    leverage,
                "target_size": target_size,
                "_reason":     f"mode change {current_mode}→{mode}",
            })
            continue

        if not is_full_exit and delta_usd < MIN_TRADE_USD:
            continue
        if delta_usd > MAX_SINGLE_ORDER_USD:
            delta_size = (MAX_SINGLE_ORDER_USD / price) * (1 if delta_size > 0 else -1)
            delta_usd  = MAX_SINGLE_ORDER_USD

        trades.append({
            "asset":       asset,
            "ticker":      trade_ticker,
            "side":        "buy" if delta_size > 0 else "sell",
            "size":        abs(delta_size),
            "value_usd":   delta_usd,
            "price":       price,
            "mode":        mode,
            "leverage":    leverage,
            "target_size": target_size,
        })

    trades.sort(key=lambda t: (0 if t["side"] == "sell" else 1, -t["value_usd"]))
    return trades


def execute_trades(info, exchange, trades: list[dict]) -> list[dict]:
    results: list[dict] = []

    # Build size-decimals maps.
    # Spot: keyed by "@{universe_index}" — must match what build_spot_index returns.
    #       szDecimals comes from tokens[], NOT universe[] (universe entries don't carry it).
    # Perp: keyed by asset name e.g. "ETH", "HYPE".
    spot_sz_map:  dict[str, int] = {}
    perp_sz_map:  dict[str, int] = {}
    try:
        spot_meta = info.spot_meta()
        tokens    = spot_meta.get("tokens", [])
        # token_index → szDecimals
        tok_sz: dict[int, int] = {i: int(t.get("szDecimals", 2)) for i, t in enumerate(tokens)}
        for pair in spot_meta.get("universe", []):
            pair_idx = pair.get("index")
            toks     = pair.get("tokens", [])
            if pair_idx is not None and len(toks) == 2 and toks[1] == 0:
                sz = tok_sz.get(toks[0], 2)
                spot_sz_map[f"@{pair_idx}"] = sz
                # Also key by pair name for PURR/USDC which uses name format
                pname = pair.get("name", "")
                if pname and not pname.startswith("@"):
                    spot_sz_map[pname] = sz
    except Exception as e:
        print(f"spot_sz_map build failed: {e}")
    try:
        for a in info.meta()["universe"]:
            perp_sz_map[a["name"]] = int(a["szDecimals"])
    except Exception:
        pass

    # Pre-set leverage for all perp tickers using per-trade leverage values
    perp_leverage: dict[str, int] = {}
    for t in trades:
        if t["mode"] == "perp":
            perp_leverage[t["ticker"]] = max(perp_leverage.get(t["ticker"], 1),
                                             int(t.get("leverage", 1)))
    leverage_failed: set[str] = set()
    for ticker, lev in perp_leverage.items():
        try:
            exchange.update_leverage(lev, ticker, is_cross=True)
            print(f"[leverage] {ticker} set to {lev}×")
        except Exception as e:
            send_slack(f"⚠️ *Leverage set failed* for {ticker} ({lev}×)\n`{e}`", mention=True)
            leverage_failed.add(ticker)
        time.sleep(0.3)

    for trade in trades:
        ticker = trade["ticker"]
        mode   = trade["mode"]
        is_buy = trade["side"] == "buy"

        if mode == "perp" and ticker in leverage_failed:
            results.append({**trade, "status": "skipped",
                             "reason": "leverage set failed"})
            continue

        sz_dec = spot_sz_map.get(ticker) if mode == "spot" else perp_sz_map.get(ticker)
        if sz_dec is None:
            sz_dec = 2
            print(f"[execute] WARNING: no szDecimals for {ticker} ({mode}), defaulting to 2")
        # For full exits (target=0), round UP so no dust remainder is left behind
        if trade["side"] == "sell" and trade.get("target_size", -1) == 0:
            from decimal import ROUND_UP
            rounding = ROUND_UP
        else:
            rounding = ROUND_DOWN
        size = float(
            Decimal(str(trade["size"]))
            .quantize(Decimal(10) ** -sz_dec, rounding=rounding)
        )
        # A full exit rounded UP can exceed the held size when the balance is
        # smaller than one size step (dust) or not step-aligned — HL rejects
        # those with "Insufficient spot balance" on every rebalance. Fall back
        # to ROUND_DOWN: sellable amount is sold, sub-step dust skips below.
        if rounding != ROUND_DOWN and size > trade["size"]:
            size = float(
                Decimal(str(trade["size"]))
                .quantize(Decimal(10) ** -sz_dec, rounding=ROUND_DOWN)
            )
        if size == 0:
            results.append({**trade, "status": "skipped",
                             "reason": "size rounded to 0"})
            continue

        try:
            result = exchange.market_open(
                ticker, is_buy=is_buy, sz=size, slippage=MAX_SLIPPAGE)
            if result["status"] == "ok":
                for status in result["response"]["data"]["statuses"]:
                    if "filled" in status:
                        f = status["filled"]
                        results.append({**trade, "status": "filled",
                                        "filled_size": float(f["totalSz"]),
                                        "avg_price":   float(f["avgPx"])})
                    elif "error" in status:
                        results.append({**trade, "status": "error",
                                        "error": status["error"]})
            else:
                # Single retry after 2s for transient HL API failures
                time.sleep(2)
                retry = exchange.market_open(
                    ticker, is_buy=is_buy, sz=size, slippage=MAX_SLIPPAGE)
                if retry["status"] == "ok":
                    for status in retry["response"]["data"]["statuses"]:
                        if "filled" in status:
                            f = status["filled"]
                            results.append({**trade, "status": "filled",
                                            "filled_size": float(f["totalSz"]),
                                            "avg_price":   float(f["avgPx"])})
                        elif "error" in status:
                            results.append({**trade, "status": "error",
                                            "error": status["error"]})
                else:
                    results.append({**trade, "status": "failed",
                                    "error": str(retry)})
        except Exception as e:
            results.append({**trade, "status": "exception", "error": str(e)})
        time.sleep(0.5)

    return results

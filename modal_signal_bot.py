"""
Modal Signal Bot — Unified Account Edition

Polls TRW for Prof Adam's portfolio signal and auto-rebalances on Hyperliquid.
Uses unified account mode: spot assets traded as actual spot; assets with no
spot market (PAXG) fall back to 1x perps. Spot and perp share one collateral pool.

Schedule (UK time):
  00:00-00:30 → every 2 minutes
  00:30-05:00 → every 10 minutes
  05:00-00:00 → every hour

Trading mode:
  00:00-05:00 → fully autonomous (auto-execute)
  05:00-00:00 → approval required (Slack + dashboard link)

Required Modal secrets (signal-bot-secrets):
  TRW_SESSION_TOKEN
  TRW_SIGNAL_CHANNEL_ID   (default: 01H83QAX979K9R7QTMH74ATR8C)
  TRW_PROF_ADAM_USER_ID   (default: 01GHHHWZE7Q77AKGWZDGC5PDCN)
  HYPERLIQUID_API_PRIVATE_KEY
  HYPERLIQUID_MASTER_ACCOUNT_ADDRESS
  SLACK_WEBHOOK_URL        (optional)
  DASHBOARD_USERNAME
  DASHBOARD_PASSWORD
  MODAL_WORKSPACE          (set automatically by manage.py)
"""

import hmac
import os
import json
import re
import time
import secrets
from datetime import datetime, timezone
from decimal import Decimal, ROUND_DOWN

import modal

app = modal.App("signal-bot")

image = (
    modal.Image.debian_slim(python_version="3.12")
    .pip_install(
        "requests",
        "hyperliquid-python-sdk",
        "eth-account",
        "fastapi[standard]",
    )
)

# ── Slack ─────────────────────────────────────────────────────────────────────

def send_slack(text: str, mention: bool = False):
    import requests as req
    webhook = os.environ.get("SLACK_WEBHOOK_URL", "")
    if not webhook:
        print(f"[SLACK SKIPPED] {text}")
        return
    try:
        req.post(webhook, json={"text": text}, timeout=10)
    except Exception as e:
        print(f"[SLACK ERROR] {e}")


# ── TRW Signal Reader ─────────────────────────────────────────────────────────

TRW_API_BASE = "https://eden.therealworld.ag"

def fetch_recent_messages(limit: int = 20) -> list[dict]:
    import requests as req
    resp = req.post(
        f"{TRW_API_BASE}/messages/query",
        headers={
            "x-session-token": os.environ["TRW_SESSION_TOKEN"],
            "Content-Type": "application/json",
            "Origin": "https://app.jointherealworld.com",
        },
        json={
            "channel": os.environ.get("TRW_SIGNAL_CHANNEL_ID",
                                      "01H83QAX979K9R7QTMH74ATR8C"),
            "limit": limit,
            "sort": "Latest",
        },
        timeout=15,
    )
    if resp.status_code == 401:
        raise RuntimeError("TRW session token expired")
    resp.raise_for_status()
    return resp.json().get("messages", [])


def find_latest_signal(messages: list[dict]) -> dict | None:
    prof_adam = os.environ.get("TRW_PROF_ADAM_USER_ID",
                               "01GHHHWZE7Q77AKGWZDGC5PDCN")
    for msg in messages:
        if (msg.get("author") == prof_adam
                and "Portfolio Signal Update" in msg.get("content", "")):
            return msg
    return None


def parse_signal(content: str) -> dict:
    result = {"allocations": [], "no_change": False, "btc_leverage": None}
    exec_match = re.search(
        r"Executive Summary:(.+?)(?:Associated Data|$)", content, re.DOTALL)
    if exec_match and "no change" in exec_match.group(1).lower():
        result["no_change"] = True
    alloc_pattern = re.compile(
        r"\*?\*?(\d+(?:\.\d+)?)\s*%\s*(Spot|Gold|Leverage)?\s*\$?([\w/$]+)\*?\*?",
        re.IGNORECASE,
    )
    signal_section = re.search(
        r"(?:RSPS Signal|Risk-On Crypto Signal|\*\*Signal:\*\*).*?"
        r"(?:Executive Summary|Associated Data|───|$)",
        content, re.DOTALL,
    )
    if signal_section:
        section_text = signal_section.group(0)
        for match in alloc_pattern.finditer(section_text):
            pct_str, alloc_type, asset = match.groups()
            asset = asset.strip("$*").upper()
            if asset == "GOLD" or (alloc_type and alloc_type.lower() == "gold"):
                gold_match = re.search(r"PAXG(?:\s*/\s*\$?XAUT)?",
                                       section_text, re.IGNORECASE)
                asset = (gold_match.group(0).upper().replace(" ", "")
                         .replace("$", "") if gold_match else "PAXG/XAUT")
                alloc_type = "Gold"
            elif asset in ("CASH", "USDC"):
                alloc_type = "Cash"
                asset = "USDC"
            elif not alloc_type:
                alloc_type = "Spot"
            else:
                alloc_type = alloc_type.capitalize()
            result["allocations"].append({
                "percent": float(pct_str),
                "type":    alloc_type,
                "asset":   asset,
            })
    lev_match = re.search(
        r"BTC Leverage.*?=.*?(Impermissible|Permissible)", content, re.IGNORECASE)
    if lev_match:
        result["btc_leverage"] = lev_match.group(1).capitalize()
    return result


# ── Hyperliquid — unified account ─────────────────────────────────────────────

# Canonical perp ticker for each signal asset name
ASSET_TO_TICKER: dict[str, str] = {
    "ETH":       "ETH",
    "BTC":       "BTC",
    "HYPE":      "HYPE",
    "SOL":       "SOL",
    "DOGE":      "DOGE",
    "XRP":       "XRP",
    "PAXG/XAUT": "PAXG",
    "PAXG":      "PAXG",
    "XAUT":      "PAXG",
    "GOLD":      "PAXG",
    "USDC":      "USDC",
}

# Assets with a liquid spot market. Everything else falls back to 1x perp.
SPOT_ASSETS: frozenset[str] = frozenset({"ETH", "BTC", "HYPE", "SOL", "DOGE", "XRP"})

MIN_TRADE_USD        = 10.0
MAX_SLIPPAGE         = 0.03
MAX_SINGLE_ORDER_USD = 50_000


def get_hl_clients():
    import eth_account as _ea
    from hyperliquid.exchange import Exchange
    from hyperliquid.info import Info
    from hyperliquid.utils import constants
    wallet   = _ea.Account.from_key(os.environ["HYPERLIQUID_API_PRIVATE_KEY"])
    info     = Info(constants.MAINNET_API_URL, skip_ws=True)
    exchange = Exchange(wallet, constants.MAINNET_API_URL,
                        account_address=os.environ[
                            "HYPERLIQUID_MASTER_ACCOUNT_ADDRESS"])
    return info, exchange


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
    """Return canonical ticker → spot pair name e.g. "ETH" → "ETH/USDC"."""
    mapping: dict[str, str] = {}
    try:
        meta        = info.spot_meta()
        tokens      = meta.get("tokens", [])
        idx_to_name = {i: t.get("name", "") for i, t in enumerate(tokens)}
        for pair in meta.get("universe", []):
            t = pair.get("tokens", [])
            if len(t) == 2 and t[1] == 0:
                raw_name  = idx_to_name.get(t[0], "")
                pair_name = pair.get("name", "")
                if raw_name and pair_name:
                    clean = raw_name.lstrip("U").upper()
                    mapping[clean]             = pair_name
                    mapping[raw_name.upper()]  = pair_name
    except Exception as e:
        print(f"build_spot_index failed: {e}")
    return mapping


def get_bar_close_prices(assets: list[str]) -> dict[str, float]:
    """
    Fetch the most recently *closed* candle price for each asset.
    Uses 5-minute candles on Hyperliquid for maximum resolution —
    the previous closed 5m bar is the best proxy for "signal bar close".
    Falls back to the last closed 1h bar if 5m data is unavailable.
    """
    import requests as req
    prices: dict[str, float] = {}
    now_ms = int(time.time() * 1000)
    for asset in assets:
        ticker = ASSET_TO_TICKER.get(asset, asset)
        if ticker == "USDC":
            continue
        # Try 5m first (last 30 minutes covers at least 5 closed bars)
        fetched = False
        for interval, lookback_s in [("5m", 1800), ("15m", 3600), ("1h", 7200)]:
            try:
                resp = req.post(
                    "https://api.hyperliquid.xyz/info",
                    json={"type": "candleSnapshot", "req": {
                        "coin": ticker, "interval": interval,
                        "startTime": now_ms - lookback_s * 1000,
                        "endTime":   now_ms,
                    }},
                    timeout=10,
                )
                candles = resp.json()
                # Use second-to-last candle — the last one may still be open
                if candles and len(candles) >= 2:
                    prices[asset] = float(candles[-2]["c"])
                    fetched = True
                    break
                elif candles:
                    prices[asset] = float(candles[-1]["c"])
                    fetched = True
                    break
            except Exception as e:
                print(f"Bar close ({interval}) failed for {asset}: {e}")
        if not fetched:
            print(f"Warning: could not get bar close price for {asset}")
    return prices


def get_account_state(info) -> dict:
    """
    Unified state: perp positions + spot balances merged under canonical ticker.

    With unified account, funds may live entirely in the spot wallet (as USDC
    or spot tokens) while perp marginSummary.accountValue shows $0.
    True account value = perp equity + spot USDC + spot token market values.
    """
    address    = os.environ["HYPERLIQUID_MASTER_ACCOUNT_ADDRESS"]
    state      = info.user_state(address)
    margin     = state["marginSummary"]
    perp_value = float(margin["accountValue"])
    positions: dict[str, dict] = {}

    # Fetch current mark prices once — used for both perp value and spot
    all_mids: dict = {}
    try:
        all_mids = info.all_mids()
    except Exception as e:
        print(f"all_mids fetch failed: {e}")

    # Perp positions
    for pos in state.get("assetPositions", []):
        p        = pos["position"]
        coin     = p["coin"]
        size     = float(p.get("szi", 0))
        if size == 0:
            continue
        entry_px = float(p["entryPx"]) if p.get("entryPx") else 0
        mark_px  = float(all_mids.get(coin, entry_px))   # live mark price
        positions[coin] = {
            "size":           size,
            "entry_px":       entry_px,
            "mark_px":        mark_px,
            "unrealized_pnl": float(p.get("unrealizedPnl", 0)),
            "value_usd":      abs(size) * mark_px,        # use mark, not entry
            "mode":           "perp",
        }

    # Spot balances — counts toward total and tracked as positions
    spot_total_usd = 0.0
    try:
        spot_state = info.spot_user_state(address)
        for bal in spot_state.get("balances", []):
            coin_raw = bal["coin"].upper()
            total    = float(bal.get("total", 0))
            if total <= 0:
                continue
            if coin_raw == "USDC":
                spot_total_usd += total   # idle cash, no position to track
                continue

            # Normalise: HL prefixes EVM-bridged tokens with "U" (UETH→ETH, UBTC→BTC)
            # Native tokens like HYPE have no prefix and must not be stripped
            canon = coin_raw.lstrip("U") if coin_raw.startswith("U") and len(coin_raw) > 1 else coin_raw
            # Look up mark price (all_mids uses canonical ticker without U prefix)
            mark_px = float(all_mids.get(canon, all_mids.get(coin_raw, 0)))
            value   = total * mark_px
            spot_total_usd += value

            # Unrealised PnL from entry notional cost.
            # HL spot_user_state returns "entryNtl" = total USD cost of current holdings.
            entry_ntl = float(bal.get("entryNtl") or bal.get("entryCost") or 0)
            if entry_ntl > 0 and total > 0:
                entry_px       = entry_ntl / total      # avg cost per unit
                unrealized_pnl = value - entry_ntl      # MTM minus cost
            elif mark_px > 0:
                entry_px       = mark_px
                unrealized_pnl = 0.0                    # no cost data — PnL unknown
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

    account_value = perp_value + spot_total_usd
    return {"account_value": account_value, "positions": positions}


def get_current_prices(info, assets: list[str]) -> dict[str, float]:
    all_mids = info.all_mids()
    prices: dict[str, float] = {}
    for asset in assets:
        ticker = ASSET_TO_TICKER.get(asset, asset)
        if ticker == "USDC":
            prices[asset] = 1.0
        elif ticker in all_mids:
            prices[asset] = float(all_mids[ticker])
    return prices


def compute_rebalance(allocations, account_value, current_positions,
                      prices, spot_index) -> list[dict]:
    """
    Compute trades to reach target allocations.
    Spot-first: uses spot pair if in SPOT_ASSETS and spot_index has it,
    else 1x perp.
    """
    trades:     list[dict] = []
    target_map: dict[str, dict] = {}

    for alloc in allocations:
        asset  = alloc["asset"]
        ticker = ASSET_TO_TICKER.get(asset, asset)
        if ticker == "USDC" or asset not in prices:
            continue
        target_usd   = account_value * (alloc["percent"] / 100.0)
        target_size  = target_usd / prices[asset]
        use_spot     = ticker in SPOT_ASSETS and ticker in spot_index
        trade_ticker = spot_index[ticker] if use_spot else ticker
        target_map[ticker] = {
            "asset":        asset,
            "ticker":       trade_ticker,
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
            price = cur_pos.get("entry_px", 0)
            if not price:
                continue
            target_size  = 0.0
            asset        = canon
            mode         = cur_pos.get("mode", "perp")
            trade_ticker = (spot_index.get(canon, f"{canon}/USDC")
                            if mode == "spot" else canon)

        delta_size  = target_size - current_size
        delta_usd   = abs(delta_size) * price
        is_full_exit = target_size == 0.0 and current_size != 0
        # Always close positions with zero target — skip MIN_TRADE_USD for dust sweeps
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
            "target_size": target_size,
        })

    trades.sort(key=lambda t: (0 if t["side"] == "sell" else 1, -t["value_usd"]))
    return trades


def execute_trades(info, exchange, trades: list[dict]) -> list[dict]:
    results: list[dict] = []

    # Build size-decimals lookup keyed THREE ways so we always hit:
    #   1. by pair name   ("ETH/USDC" → 4)   for spot trades
    #   2. by base ticker ("ETH"      → 4)   canonical fallback for spot
    #   3. by perp ticker ("ETH"      → 3)   for perp trades
    sz_dec_map: dict[str, int] = {}
    try:
        meta   = info.spot_meta()
        tokens = meta.get("tokens", [])
        idx_to_name = {i: t.get("name", "") for i, t in enumerate(tokens)}
        for pair in meta.get("universe", []):
            sd        = pair.get("szDecimals", 4)
            pair_name = pair.get("name", "")
            t         = pair.get("tokens", [])
            if pair_name:
                sz_dec_map[pair_name] = sd          # "ETH/USDC" → 4
            if len(t) >= 1:
                raw  = idx_to_name.get(t[0], "")
                if raw:
                    sz_dec_map[raw.upper()]              = sd   # "UETH" → 4
                    sz_dec_map[raw.lstrip("U").upper()]  = sd   # "ETH"  → 4
    except Exception as e:
        print(f"spot sz_dec build failed: {e}")
    try:
        for a in info.meta()["universe"]:
            # Perp entries only overwrite if not already set by spot
            sz_dec_map.setdefault(a["name"], a["szDecimals"])
    except Exception:
        pass

    # Pre-set 1x leverage for all perp tickers
    perp_tickers    = {t["ticker"] for t in trades if t["mode"] == "perp"}
    leverage_failed: set[str] = set()
    for ticker in perp_tickers:
        try:
            exchange.update_leverage(1, ticker, is_cross=True)
        except Exception as e:
            send_slack(f"⚠️ *Leverage set failed* for {ticker}\n`{e}`", mention=True)
            leverage_failed.add(ticker)
        time.sleep(0.3)

    for trade in trades:
        ticker = trade["ticker"]
        mode   = trade["mode"]
        is_buy = trade["side"] == "buy"
        asset  = trade.get("asset", ticker)   # canonical asset name e.g. "ETH"

        if mode == "perp" and ticker in leverage_failed:
            results.append({**trade, "status": "skipped",
                             "reason": "leverage set failed"})
            continue

        # Look up precision: try pair name first, then canonical ticker, then default 4
        # Default is 4 (not 2) — HL spot assets are typically 4 decimal places
        sz_dec = (sz_dec_map.get(ticker)
                  or sz_dec_map.get(asset)
                  or sz_dec_map.get(ASSET_TO_TICKER.get(asset, asset))
                  or 4)
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
                results.append({**trade, "status": "failed",
                                 "error": str(result)})
        except Exception as e:
            results.append({**trade, "status": "exception", "error": str(e)})
        time.sleep(0.5)

    return results


# ── State ─────────────────────────────────────────────────────────────────────

signal_state = modal.Dict.from_name("signal-bot-state", create_if_missing=True)


def record_equity_snapshot(account_value: float) -> None:
    """
    Append a timestamped equity snapshot to cloud storage.
    Called on every scheduled poll so we build a continuous live equity history
    regardless of which device visits the dashboard.

    Storage key: "equity_snapshots"
    Format: JSON list of {"ts": unix_ms, "v": float} sorted oldest→newest.
    Deduplicated to one point per hour — we keep the last value of each hour.
    Cap at 3650 points (~10 years of hourly data).
    """
    if account_value <= 0:
        return
    try:
        raw = signal_state.get("equity_snapshots", "[]")
        snaps: list[dict] = json.loads(raw)
    except Exception:
        snaps = []

    now_ms  = int(time.time() * 1000)
    hour_ms = (now_ms // 3_600_000) * 3_600_000   # round down to hour boundary

    # Upsert: replace the current hour's entry if it already exists
    if snaps and snaps[-1]["ts"] // 3_600_000 == now_ms // 3_600_000:
        snaps[-1] = {"ts": now_ms, "v": round(account_value, 2)}
    else:
        snaps.append({"ts": now_ms, "v": round(account_value, 2)})

    # Keep cap
    snaps = snaps[-3650:]
    try:
        signal_state["equity_snapshots"] = json.dumps(snaps)
    except Exception as e:
        print(f"[equity_snapshot] write failed: {e}")


def is_autonomous_hours() -> bool:
    from zoneinfo import ZoneInfo
    now = datetime.now(ZoneInfo("Europe/London"))
    return 0 <= now.hour < 5


def should_poll_now() -> bool:
    from zoneinfo import ZoneInfo
    now = datetime.now(ZoneInfo("Europe/London"))
    h, m = now.hour, now.minute
    if h == 0 and m < 30:
        return m % 2 == 0
    if (h == 0 and m >= 30) or (1 <= h < 5):
        return m % 10 == 0
    return m == 0


def do_rebalance(parsed: dict, msg_id: str) -> dict:
    """Execute a rebalance and send a detailed Slack report."""
    info, exchange = get_hl_clients()

    # Ensure unified account is active before every rebalance
    ensure_unified_account(exchange, info)

    state         = get_account_state(info)
    account_value = state["account_value"]

    if account_value < 1.0:
        send_slack("🚨 *Skipped* — account value too low to trade. Deposit USDC first.", mention=True)
        return {"status": "error", "error": "account_value_too_low"}

    alloc_total = sum(a["percent"] for a in parsed["allocations"])
    if not (90 <= alloc_total <= 110):
        msg = (f"ABORTED — allocations sum to {alloc_total:.1f}% "
               f"(expected ~100%). Possible parse failure.")
        send_slack(msg, mention=True)
        return {"status": "error", "error": f"allocation_sum_invalid: {alloc_total:.1f}%"}

    prices     = get_current_prices(info, [a["asset"] for a in parsed["allocations"]])
    spot_index = build_spot_index(info)
    trades     = compute_rebalance(parsed["allocations"], account_value,
                                   state["positions"], prices, spot_index)

    if not trades:
        send_slack("✅ *Signal processed* — positions already match, no trades needed.")
        signal_state["last_signal_id"] = msg_id
        return {"status": "already_aligned", "signal_id": msg_id}

    bar_close_prices: dict[str, float] = {}
    try:
        bar_close_prices = json.loads(signal_state.get("bar_close_prices", "{}"))
    except Exception:
        pass

    results = execute_trades(info, exchange, trades)
    filled  = [r for r in results if r["status"] == "filled"]
    failed  = [r for r in results if r["status"] in ("error", "failed", "exception")]

    total_slippage_usd = 0.0
    trade_lines: list[str] = []

    for r in results:
        asset     = r.get("asset", r.get("ticker", "?"))
        ticker    = r.get("ticker", asset)
        side      = r.get("side", "?").upper()
        mode      = r.get("mode", "perp")
        mode_tag  = "◆" if mode == "spot" else "◇"  # filled = spot, outline = perp
        bar_px    = bar_close_prices.get(asset)
        side_icon = "↑" if side == "BUY" else "↓"

        if r["status"] == "filled":
            exec_px   = r["avg_price"]
            fill_size = r["filled_size"]
            line = f"{side_icon} {side} {fill_size:.4f} {ticker} {mode_tag}  @  ${exec_px:,.2f}"
            if bar_px and bar_px > 0:
                raw_dev  = (exec_px - bar_px) / bar_px * 100
                dev      = raw_dev if side == "BUY" else -raw_dev
                slip_usd = abs(exec_px - bar_px) * fill_size
                total_slippage_usd += slip_usd
                dev_sign = "+" if dev >= 0 else ""
                slip_str = f"${slip_usd:.2f}" if side == "BUY" else f"-${slip_usd:.2f}"
                line += f"\n   bar ${bar_px:,.2f}  ·  dev {dev_sign}{dev:.3f}%  ·  slip {slip_str}"
            trade_lines.append(line)
        elif r["status"] == "skipped":
            trade_lines.append(f"— SKIP {ticker}: {r.get('reason', '?')}")
        else:
            trade_lines.append(f"✗ FAIL {ticker} {side}: {r.get('error', '?')}")

    if not failed:
        status_icon, status_label = "✅", "Rebalance complete"
    elif filled:
        status_icon, status_label = "⚠️", "Rebalance partial"
    else:
        status_icon, status_label = "🚨", "Rebalance FAILED"

    lines = [f"{status_icon} *{status_label}*"]
    lines.append(f"Account  *${account_value:,.2f}*   ·   {len(filled)} filled   ·   {len(failed)} failed")
    if bar_close_prices and filled and total_slippage_usd > 0:
        lines.append(f"Slippage  ${total_slippage_usd:.2f}  ({total_slippage_usd / account_value * 100:.3f}%)")
    lines.append("──────────────────")
    lines.extend(trade_lines)
    lines.append(f"\n◆ spot  ◇ perp")

    send_slack("\n".join(lines), mention=bool(failed))
    signal_state["last_signal_id"] = msg_id

    return {
        "status":       "rebalanced",
        "signal_id":    msg_id,
        "filled":       len(filled),
        "failed":       len(failed),
        "slippage_usd": round(total_slippage_usd, 4),
    }


# ── Main cron ─────────────────────────────────────────────────────────────────

@app.function(
    image=image,
    secrets=[modal.Secret.from_name("signal-bot-secrets")],
    schedule=modal.Cron("* * * * *"),
    timeout=120,
)
def check_signal():
    if not should_poll_now():
        return {"status": "skipped", "reason": "not scheduled this minute"}

    # ── Equity snapshot (cloud storage for cross-device history) ──────────
    try:
        _info, _ = get_hl_clients()
        _state   = get_account_state(_info)
        record_equity_snapshot(_state["account_value"])
    except Exception as e:
        print(f"[equity_snapshot] skipped: {e}")

    try:
        messages = fetch_recent_messages(limit=20)
    except RuntimeError as e:
        send_slack(f"🔑 *TRW auth error* — token expired\n`{e}`\nRun `python manage.py` to refresh.", mention=True)
        return {"status": "error", "error": str(e)}
    except Exception as e:
        return {"status": "error", "error": str(e)}

    signal_msg = find_latest_signal(messages)
    if not signal_msg:
        return {"status": "no_signal"}

    msg_id = signal_msg["_id"]

    try:
        last_acted_id = signal_state["last_signal_id"]
    except KeyError:
        last_acted_id = None

    if msg_id == last_acted_id:
        return {"status": "already_acted", "signal_id": msg_id}

    parsed    = parse_signal(signal_msg["content"])
    timestamp = signal_msg.get("timestamp", 0)
    dt        = datetime.fromtimestamp(timestamp / 1000, tz=timezone.utc)
    alloc_lines = "\n".join(
        f"  {a['percent']}% {a['type']} {a['asset']}"
        for a in parsed["allocations"]
    )

    if parsed["no_change"]:
        send_slack(
            f"📋 *No change*  ·  {dt.strftime('%d %b %H:%M UTC')}\n{alloc_lines}")
        signal_state["last_signal_id"] = msg_id
        return {"status": "no_change", "signal_id": msg_id}

    # Capture bar close prices at detection time (before execution)
    signal_assets = [
        a["asset"] for a in parsed["allocations"]
        if ASSET_TO_TICKER.get(a["asset"], a["asset"]) not in ("USDC", "")
    ]
    try:
        bar_close_px = get_bar_close_prices(signal_assets)
        signal_state["bar_close_prices"] = json.dumps(bar_close_px)
    except Exception as e:
        print(f"Failed to capture bar close prices: {e}")

    if is_autonomous_hours():
        send_slack(
            f"🤖 *New signal — auto-rebalancing*  ·  {dt.strftime('%d %b %H:%M UTC')}\n{alloc_lines}",
            mention=True,
        )
        try:
            return do_rebalance(parsed, msg_id)
        except Exception as e:
            send_slack(f"🚨 *Rebalance error*\n`{e}`", mention=True)
            return {"status": "error", "error": str(e)}
    else:
        approval_token = secrets.token_urlsafe(16)
        signal_state["pending_signal"] = json.dumps(parsed)
        signal_state["pending_msg_id"] = msg_id
        signal_state["approval_token"] = approval_token

        workspace     = os.environ.get("MODAL_WORKSPACE", "YOUR_WORKSPACE")
        dashboard_url = f"https://{workspace}--signal-bot-web.modal.run"
        send_slack(
            f"📬 *New signal — approval required*  ·  {dt.strftime('%d %b %H:%M UTC')}\n"
            f"{alloc_lines}\n"
            f"──────────────────\n"
            f"<{dashboard_url}?action=approve&token={approval_token}|✅ Approve>   "
            f"<{dashboard_url}?action=dismiss&token={approval_token}|✗ Dismiss>   "
            f"<{dashboard_url}|Dashboard>",
            mention=True,
        )
        return {"status": "pending_approval", "signal_id": msg_id}


# ── Web endpoint ──────────────────────────────────────────────────────────────

@app.function(
    image=image,
    secrets=[modal.Secret.from_name("signal-bot-secrets")],
    timeout=120,
)
@modal.fastapi_endpoint(method="GET")
async def web(action: str = "", token: str = "", auth: str = "", points: str = ""):
    from fastapi.responses import HTMLResponse
    import base64

    # ── Auth ──────────────────────────────────────────────────────────────────
    expected_user = os.environ.get("DASHBOARD_USERNAME", "")
    expected_pass = os.environ.get("DASHBOARD_PASSWORD", "")

    authorized = True   # default: open if no creds configured
    if expected_user and expected_pass:
        authorized = False
        if auth:
            try:
                from urllib.parse import unquote
                decoded  = base64.b64decode(
                    unquote(auth) + "==").decode("utf-8")
                username, password = decoded.split(":", 1)
                authorized = (username.strip() == expected_user.strip()
                              and password.strip() == expected_pass.strip())
            except Exception as e:
                print(f"Auth decode error: {e}")

        if not authorized:
            show_error = "true" if (auth and not authorized) else "false"
            login_html = f"""<!DOCTYPE html>
<html><head>
<meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>Signal Bot — Login</title>
<style>
  *{{margin:0;padding:0;box-sizing:border-box}}
  body{{font-family:'DM Mono',monospace;background:#0a0a0a;color:#f0ede8;
       min-height:100vh;display:flex;align-items:center;justify-content:center}}
  .box{{background:#111;border:1px solid rgba(255,255,255,0.08);border-radius:8px;
        padding:32px;width:100%;max-width:360px}}
  .logo{{font-family:'Syne',sans-serif;font-size:18px;font-weight:700;margin-bottom:24px}}
  .logo span{{color:#c8f563}}
  label{{font-size:11px;letter-spacing:.1em;text-transform:uppercase;
         color:#6b6860;display:block;margin-bottom:6px}}
  input{{width:100%;padding:10px 12px;background:#0a0a0a;
         border:1px solid rgba(255,255,255,0.12);border-radius:5px;
         color:#f0ede8;font-family:'DM Mono',monospace;font-size:13px;margin-bottom:16px}}
  input:focus{{outline:none;border-color:#c8f563}}
  button{{width:100%;padding:11px;background:rgba(200,245,99,0.12);
          border:1px solid rgba(200,245,99,0.35);border-radius:5px;color:#c8f563;
          font-family:'DM Mono',monospace;font-size:12px;
          letter-spacing:.06em;text-transform:uppercase;cursor:pointer}}
  button:hover{{background:rgba(200,245,99,0.2)}}
  .err{{color:#ff5c5c;font-size:12px;margin-bottom:12px}}
</style></head><body>
<div class="box">
  <div class="logo">signal<span>bot</span></div>
  <div class="err" id="err"
       style="display:{{"block" if show_error=="true" else "none"}}">
    Invalid credentials</div>
  <label>Username</label>
  <input type="text" id="u" autofocus>
  <label>Password</label>
  <input type="password" id="p" onkeydown="if(event.key==='Enter')login()">
  <button onclick="login()">Sign in</button>
</div>
<script>
function login(){{
  const u=document.getElementById('u').value.trim();
  const p=document.getElementById('p').value;
  if(!u||!p)return;
  const encoded=btoa(unescape(encodeURIComponent(u+':'+p)));
  window.location.href='?auth='+encoded;
}}
</script></body></html>"""
            return HTMLResponse(login_html)

    # ── Helper: auth-preserving redirect back to dashboard ─────────────────
    def _dash_redirect(auth_token: str) -> HTMLResponse:
        url = f"?auth={auth_token}" if auth_token else "?"
        return HTMLResponse(
            f'<html><head><meta http-equiv="refresh" content="1;url={url}">'
            f'</head><body></body></html>')

    # ── Approve ────────────────────────────────────────────────────────────
    if action == "approve":
        try:
            stored = signal_state.get("approval_token", "")
        except Exception:
            stored = ""
        if not token or not hmac.compare_digest(token, stored):
            return HTMLResponse(
                _page("Invalid or expired approval token.",
                      "Use the link from your Slack notification."),
                status_code=403)
        try:
            pending = json.loads(signal_state.get("pending_signal", "null"))
            msg_id  = signal_state.get("pending_msg_id", "")
        except Exception:
            pending, msg_id = None, ""
        if not pending:
            return HTMLResponse(_page("No pending signal to approve.", ""))
        try:
            del signal_state["pending_signal"]
            del signal_state["pending_msg_id"]
            del signal_state["approval_token"]
        except KeyError:
            pass
        try:
            result = do_rebalance(pending, msg_id)
            return HTMLResponse(_page(
                f"Rebalance executed: {result.get('status')}",
                f"Filled: {result.get('filled', 0)}, "
                f"Failed: {result.get('failed', 0)}"
            ))
        except Exception as e:
            send_slack(f"🚨 *Approval rebalance error*\n`{e}`", mention=True)
            return HTMLResponse(_page(f"Error: {e}", ""), status_code=500)

    # ── Dismiss ────────────────────────────────────────────────────────────
    if action == "dismiss":
        try:
            stored = signal_state.get("approval_token", "")
        except Exception:
            stored = ""
        if not token or not hmac.compare_digest(token, stored):
            return HTMLResponse(
                _page("Invalid or expired token.", ""), status_code=403)
        try:
            mid = signal_state.get("pending_msg_id", "")
            if mid:
                signal_state["last_signal_id"] = mid
            del signal_state["pending_signal"]
            del signal_state["pending_msg_id"]
            del signal_state["approval_token"]
        except KeyError:
            pass
        send_slack("🗑️ Signal dismissed via dashboard.")
        return HTMLResponse(_page("Signal dismissed.", ""))

    # ── Force rebalance ────────────────────────────────────────────────────
    # NOTE: Force does NOT require an approval token — dashboard login is
    # sufficient authorisation. This fixes the bug where force always showed
    # "invalid token" unless a pending approval happened to exist.
    if action == "force":
        if not authorized:
            return HTMLResponse(
                _page("Not authorised.", "Log in first."), status_code=403)
        try:
            messages   = fetch_recent_messages(limit=20)
            signal_msg = find_latest_signal(messages)
            if not signal_msg:
                return HTMLResponse(_page("No signal found in TRW channel.",
                                          "Nothing to rebalance."))
            parsed = parse_signal(signal_msg["content"])
            parsed["no_change"] = False   # force execution even on no-change signals
            send_slack("🔄 *Force rebalance* triggered via dashboard")
            result = do_rebalance(parsed, signal_msg["_id"])
            return HTMLResponse(_page(
                f"Force rebalance: {result.get('status')}",
                f"Filled: {result.get('filled', 0)}, "
                f"Failed: {result.get('failed', 0)}"
            ))
        except Exception as e:
            send_slack(f"🚨 *Force rebalance error*\n`{e}`", mention=True)
            return HTMLResponse(_page(f"Error: {e}",
                                       "Check Modal logs for details."),
                                status_code=500)

    # ── Health ─────────────────────────────────────────────────────────────
    if action == "health":
        issues: list[str] = []
        try:
            msgs = fetch_recent_messages(limit=1)
            if not msgs:
                issues.append("TRW: no messages returned")
        except Exception as e:
            issues.append(f"TRW: {e}")
        try:
            slack_url = os.environ.get("SLACK_WEBHOOK_URL", "")
            if not slack_url:
                issues.append("Slack: SLACK_WEBHOOK_URL not set (optional)")
        except Exception:
            pass
        try:
            info, _ = get_hl_clients()
            get_account_state(info)
        except Exception as e:
            issues.append(f"Hyperliquid: {e}")
        status = "HEALTHY" if not issues else "ISSUES: " + "; ".join(issues)
        return HTMLResponse(_page("Health Check", status))

    # ── History tab ────────────────────────────────────────────────────────
    if action == "history":
        return HTMLResponse(_render_history(auth))

    # ── History signals API (called by JS in history tab) ──────────────────
    if action == "history_signals":
        if not authorized:
            from fastapi.responses import JSONResponse
            return JSONResponse({"error": "not authorized"}, status_code=403)
        try:
            sigs = _fetch_history_signals(limit=600)
            from fastapi.responses import JSONResponse
            return JSONResponse(sigs)
        except Exception as e:
            from fastapi.responses import JSONResponse
            return JSONResponse({"error": str(e)}, status_code=500)

    # ── Cloud equity history API ────────────────────────────────────────────
    if action == "equity_history":
        if not authorized:
            from fastapi.responses import JSONResponse
            return JSONResponse({"error": "not authorized"}, status_code=403)
        try:
            raw   = signal_state.get("equity_snapshots", "[]")
            snaps = json.loads(raw)
            from fastapi.responses import JSONResponse
            return JSONResponse(snaps)
        except Exception as e:
            from fastapi.responses import JSONResponse
            return JSONResponse([], status_code=200)

    # ── Store backtest result in cloud (called by JS after backtest) ────────
    if action == "equity_store_backtest":
        if not authorized:
            from fastapi.responses import JSONResponse
            return JSONResponse({"error": "not authorized"}, status_code=403)
        from fastapi.responses import JSONResponse
        try:
            data = json.loads(points) if points else {}
            pts  = data.get("points", [])
            if pts:
                try:
                    existing = json.loads(signal_state.get("equity_snapshots", "[]"))
                except Exception:
                    existing = []
                earliest_live = existing[0]["ts"] if existing else float("inf")
                bt_points = [p for p in pts if p["ts"] < earliest_live]
                merged = bt_points + existing
                merged.sort(key=lambda p: p["ts"])
                merged = merged[-3650:]
                signal_state["equity_snapshots"] = json.dumps(merged)
            return JSONResponse({"ok": True, "stored": len(pts)})
        except Exception as e:
            return JSONResponse({"error": str(e)}, status_code=500)

    # ── Dashboard ──────────────────────────────────────────────────────────
    return HTMLResponse(_render_dashboard())


def _html_escape(s: str) -> str:
    """Escape HTML special characters to prevent reflected XSS."""
    return (s.replace("&", "&amp;").replace("<", "&lt;")
             .replace(">", "&gt;").replace('"', "&quot;"))

def _page(title: str, body: str) -> str:
    t = _html_escape(title)
    b = _html_escape(body)
    return f"""<!DOCTYPE html>
<html>
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>{t}</title>
  <style>
    body {{ font-family: 'DM Mono', monospace; background: #0a0a0a; color: #f0ede8;
           padding: 40px 28px; max-width: 600px; margin: 0 auto; }}
    h2 {{ font-family: 'Syne', sans-serif; font-size: 20px; font-weight: 700;
          margin-bottom: 12px; color: #c8f563; }}
    p {{ color: #6b6860; font-size: 13px; margin-bottom: 20px; white-space: pre-wrap; }}
    a {{ color: #5b9cf6; text-decoration: none; font-size: 12px;
         border: 1px solid rgba(91,156,246,0.3); padding: 6px 14px; border-radius: 4px; }}
    a:hover {{ background: rgba(91,156,246,0.1); }}
  </style>
</head>
<body>
  <h2>{t}</h2>
  <p>{b}</p>
  <a href="?">Back to dashboard</a>
</body>
</html>"""



_DASHBOARD_HTML = r"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1, maximum-scale=1">
<title>Signal Bot</title>
<script src="https://cdnjs.cloudflare.com/ajax/libs/Chart.js/4.4.1/chart.umd.js"></script>
<style>
  @import url('https://fonts.googleapis.com/css2?family=DM+Mono:wght@400;500&family=Syne:wght@400;600;700&display=swap');
  *,*::before,*::after{box-sizing:border-box;margin:0;padding:0}
  :root{--bg:#0a0a0a;--surface:#111111;--surface2:#1a1a1a;--border:rgba(255,255,255,0.08);--border2:rgba(255,255,255,0.14);--text:#f0ede8;--muted:#6b6860;--accent:#c8f563;--accent-dim:rgba(200,245,99,0.12);--red:#ff5c5c;--red-dim:rgba(255,92,92,0.12);--blue:#5b9cf6;--blue-dim:rgba(91,156,246,0.12);--amber:#f5a623;--purple:#c084fc;--font-mono:'DM Mono',monospace;--font-display:'Syne',sans-serif}
  body{background:var(--bg);color:var(--text);font-family:var(--font-mono);font-size:13px;line-height:1.6;min-height:100vh}
  .header{display:flex;align-items:center;justify-content:space-between;padding:16px 20px;border-bottom:1px solid var(--border);position:sticky;top:0;background:var(--bg);z-index:10;gap:10px;flex-wrap:wrap}
  .header-left{display:flex;align-items:center;gap:10px;min-width:0;flex-shrink:0}
  .logo{font-family:var(--font-display);font-size:15px;font-weight:700;letter-spacing:-0.02em;white-space:nowrap}
  .logo span{color:var(--accent)}
  .pulse-dot{width:7px;height:7px;border-radius:50%;background:var(--accent);flex-shrink:0;animation:pulse 2s ease-in-out infinite}
  @keyframes pulse{0%,100%{opacity:1;transform:scale(1)}50%{opacity:.4;transform:scale(.8)}}
  .tab-nav{display:flex;gap:1px;background:var(--border);border-radius:5px;overflow:hidden;padding:1px}
  .tab-btn{font-size:11px;font-family:var(--font-mono);letter-spacing:.06em;text-transform:uppercase;padding:5px 12px;border-radius:4px;cursor:pointer;color:var(--muted);border:none;background:none;transition:all .15s;white-space:nowrap;text-decoration:none;display:inline-block}
  .tab-btn.active{background:var(--surface2);color:var(--text)}
  .tab-btn:hover:not(.active){color:var(--text)}
  .header-badges{display:flex;gap:6px;flex-wrap:wrap}
  .badge{font-size:10px;font-family:var(--font-mono);font-weight:500;padding:3px 7px;border-radius:3px;letter-spacing:.05em;text-transform:uppercase;white-space:nowrap}
  .badge-ok{background:rgba(200,245,99,.15);color:var(--accent);border:1px solid rgba(200,245,99,.25)}
  .badge-err{background:var(--red-dim);color:var(--red);border:1px solid rgba(255,92,92,.25)}
  .badge-auto{background:var(--blue-dim);color:var(--blue);border:1px solid rgba(91,156,246,.25)}
  .badge-manual{background:rgba(245,166,35,.15);color:var(--amber);border:1px solid rgba(245,166,35,.25)}
  .main{padding:16px 20px;max-width:1200px}
  .pending-banner{border:1px solid rgba(245,166,35,.35);background:rgba(245,166,35,.06);border-radius:8px;padding:16px;margin-bottom:16px}
  .pending-label{font-family:var(--font-display);font-size:11px;font-weight:600;letter-spacing:.1em;text-transform:uppercase;color:var(--amber);margin-bottom:8px}
  .pending-allocs{font-size:13px;color:var(--text);display:flex;gap:14px;flex-wrap:wrap;margin-bottom:14px}
  .pending-actions{display:flex;gap:8px;flex-wrap:wrap}
  .metrics{display:grid;grid-template-columns:repeat(4,1fr);gap:1px;background:var(--border);border:1px solid var(--border);border-radius:8px;overflow:hidden;margin-bottom:16px}
  .metric{background:var(--surface);padding:14px 16px}
  .metric-label{font-size:10px;letter-spacing:.1em;text-transform:uppercase;color:var(--muted);margin-bottom:6px}
  .metric-value{font-family:var(--font-display);font-size:22px;font-weight:700;letter-spacing:-0.02em;line-height:1}
  .metric-sub{font-size:11px;color:var(--muted);margin-top:3px}
  .pos{color:var(--accent)}.neg{color:var(--red)}
  .chart-section{background:var(--surface);border:1px solid var(--border);border-radius:8px;margin-bottom:16px;overflow:hidden}
  .chart-header{display:flex;align-items:center;justify-content:space-between;padding:12px 14px;border-bottom:1px solid var(--border);flex-wrap:wrap;gap:8px}
  .panel-title{font-size:10px;letter-spacing:.1em;text-transform:uppercase;color:var(--muted);font-weight:500}
  .chart-controls{display:flex;gap:6px;flex-wrap:wrap;align-items:center}
  .ctrl-group{display:flex;gap:2px;background:var(--bg);border:1px solid var(--border);border-radius:4px;padding:2px}
  .ctrl-btn{font-size:11px;font-family:var(--font-mono);padding:4px 9px;border-radius:3px;cursor:pointer;color:var(--muted);border:none;background:none;transition:all .15s;letter-spacing:.04em;white-space:nowrap}
  .ctrl-btn.active{background:var(--surface2);color:var(--text)}
  .chart-body{padding:14px}
  .chart-legend{display:flex;gap:14px;margin-bottom:10px;flex-wrap:wrap}
  .legend-item{display:flex;align-items:center;gap:5px;font-size:11px;color:var(--muted)}
  .legend-dot{width:8px;height:8px;border-radius:50%;flex-shrink:0}
  .chart-wrap{position:relative;width:100%;height:220px}
  .grid-2{display:grid;grid-template-columns:1fr 1fr;gap:14px;margin-bottom:16px}
  .panel{background:var(--surface);border:1px solid var(--border);border-radius:8px;overflow:hidden}
  .panel-header{display:flex;align-items:center;justify-content:space-between;padding:11px 14px;border-bottom:1px solid var(--border)}
  .signal-time{font-size:11px;color:var(--muted)}
  .pos-table{width:100%;border-collapse:collapse}
  .pos-table th{font-size:10px;letter-spacing:.08em;text-transform:uppercase;color:var(--muted);font-weight:500;padding:9px 14px;text-align:left;border-bottom:1px solid var(--border)}
  .pos-table th:not(:first-child){text-align:right}
  .pos-table td{padding:11px 14px;border-bottom:1px solid var(--border);font-size:13px}
  .pos-table td:not(:first-child){text-align:right}
  .pos-table tr:last-child td{border-bottom:none}
  .pos-table tr:hover td{background:var(--surface2)}
  .coin-badge{display:inline-flex;align-items:center;gap:6px;font-family:var(--font-display);font-weight:600;font-size:13px}
  .coin-dot{width:6px;height:6px;border-radius:50%;flex-shrink:0}
  .mode-spot{background:rgba(200,245,99,0.12);color:#c8f563;border:1px solid rgba(200,245,99,0.3);border-radius:3px;padding:1px 5px;font-size:10px;letter-spacing:.04em;font-family:var(--font-mono)}
  .mode-perp{background:rgba(91,156,246,0.12);color:#5b9cf6;border:1px solid rgba(91,156,246,0.3);border-radius:3px;padding:1px 5px;font-size:10px;letter-spacing:.04em;font-family:var(--font-mono)}
  .alloc-list{padding:6px 0}
  .alloc-row{display:flex;align-items:center;gap:10px;padding:9px 14px;border-bottom:1px solid var(--border);transition:background .15s}
  .alloc-row:last-child{border-bottom:none}
  .alloc-row:hover{background:var(--surface2)}
  .alloc-pct{font-family:var(--font-display);font-weight:700;font-size:17px;color:var(--accent);min-width:56px;letter-spacing:-0.02em}
  .alloc-bar-wrap{flex:1;height:3px;background:var(--border2);border-radius:2px;overflow:hidden}
  .alloc-bar{height:100%;background:var(--accent);border-radius:2px}
  .alloc-asset{font-family:var(--font-display);font-weight:600;font-size:13px;min-width:52px;text-align:right}
  .alloc-type{font-size:10px;color:var(--muted);min-width:32px;text-align:right;letter-spacing:.06em;text-transform:uppercase}
  .actions{display:flex;gap:8px;flex-wrap:wrap;margin-bottom:16px}
  .btn{font-family:var(--font-mono);font-size:11px;letter-spacing:.06em;text-transform:uppercase;padding:8px 14px;border-radius:5px;cursor:pointer;border:1px solid var(--border2);background:var(--surface);color:var(--text);text-decoration:none;display:inline-flex;align-items:center;gap:6px;transition:all .15s}
  .btn:hover{background:var(--surface2)}
  .btn-approve{background:var(--accent-dim);border-color:rgba(200,245,99,.35);color:var(--accent)}
  .btn-approve:hover{background:rgba(200,245,99,.2)}
  .btn-danger{background:var(--red-dim);border-color:rgba(255,92,92,.35);color:var(--red)}
  .btn-export{background:var(--blue-dim);border-color:rgba(91,156,246,.35);color:var(--blue)}
  .footer{padding:14px 20px;border-top:1px solid var(--border);display:flex;justify-content:space-between;align-items:center;font-size:11px;color:var(--muted);flex-wrap:wrap;gap:6px}
  .no-pos{padding:20px 14px;color:var(--muted);font-size:12px;text-align:center}
  .toggle-pill{display:inline-flex;align-items:center;gap:6px;font-size:10px;font-family:var(--font-mono);letter-spacing:.06em;text-transform:uppercase;color:var(--muted);cursor:pointer;padding:3px 8px 3px 6px;border:1px solid var(--border);border-radius:20px;background:none;transition:all .15s;user-select:none}
  .toggle-pill:hover{border-color:var(--border2);color:var(--text)}
  .toggle-pill.active{background:var(--accent-dim);border-color:rgba(200,245,99,.35);color:var(--accent)}
  .toggle-pill .pip{width:6px;height:6px;border-radius:50%;background:currentColor;opacity:.5;transition:opacity .15s}
  .toggle-pill.active .pip{opacity:1}
  .dust-count{font-size:10px;color:var(--muted);margin-left:2px}
  @media(max-width:600px){
    .header{padding:10px 14px}
    .main{padding:12px 14px}
    .metrics{grid-template-columns:1fr 1fr}
    .metric{padding:12px 12px}
    .metric-value{font-size:18px}
    .grid-2{grid-template-columns:1fr}
    .chart-wrap{height:180px}
    .pos-table .hide-mobile{display:none}
    .pending-actions .btn{flex:1;justify-content:center;padding:12px 8px;font-size:12px}
    .actions .btn{padding:10px 12px}
  }
  @media(max-width:480px){
    .logo{display:none}
    .header-badges{gap:4px}
    .badge{font-size:9px;padding:2px 5px}
  }
  @media(max-width:380px){
    .metrics{grid-template-columns:1fr}
    .header-badges{display:none}
  }
  ::-webkit-scrollbar{width:4px;height:4px}
  ::-webkit-scrollbar-thumb{background:var(--border2);border-radius:2px}
</style>
</head>
<body>
<div class="header">
  <div class="header-left">
    <div class="pulse-dot"></div>
    <div class="logo">signal<span>bot</span></div>
    <div class="tab-nav">
      <a class="tab-btn active" id="dashTab" href="?">Dashboard</a>
    <a class="tab-btn" id="histTab" href="?action=history">History</a>
    </div>
  </div>
  <div class="header-badges" id="badges"></div>
</div>
<div class="main">
  <div class="pending-banner" id="pendingBanner" style="display:none">
    <div class="pending-label">Approval required</div>
    <div class="pending-allocs" id="pendingAllocs"></div>
    <div class="pending-actions">
      <a class="btn btn-approve" id="approveBtn" style="flex:1;justify-content:center;padding:12px 8px">Approve &amp; execute</a>
      <a class="btn" id="dismissBtn" style="color:var(--muted)">Dismiss</a>
    </div>
  </div>
  <div class="metrics">
    <div class="metric"><div class="metric-label">Account value</div><div class="metric-value" id="accountValue">—</div><div class="metric-sub">spot + perp unified</div></div>
    <div class="metric"><div class="metric-label">Unrealised PnL</div><div class="metric-value" id="totalPnl">—</div><div class="metric-sub">open positions</div></div>
    <div class="metric"><div class="metric-label">Positions</div><div class="metric-value" id="posCount">—</div><div class="metric-sub">open positions</div></div>
    <div class="metric"><div class="metric-label">All-time PnL</div><div class="metric-value" id="allTimePnl">—</div><div class="metric-sub" id="allTimePnlSub">since first record</div></div>

  </div>
  <div class="chart-section">
    <div class="chart-header">
      <div class="panel-title">Equity curve</div>
      <div class="chart-controls">
        <div class="ctrl-group" id="seriesTabs">
          <button class="ctrl-btn active" onclick="setSeries('actual',this)">Actual</button>
          <button class="ctrl-btn" onclick="setSeries('barclose',this)">Bar close</button>
          <button class="ctrl-btn" onclick="setSeries('both',this)">Both</button>
        </div>
        <div class="ctrl-group" id="rangeTabs">
          <button class="ctrl-btn active" onclick="setRange('7d',this)">7d</button>
          <button class="ctrl-btn" onclick="setRange('30d',this)">30d</button>
          <button class="ctrl-btn" onclick="setRange('all',this)">All</button>
        </div>
        <button class="btn btn-export" onclick="exportCSV()" style="padding:4px 10px;font-size:11px">Export CSV</button>
      </div>
    </div>
    <div class="chart-body">
      <div class="chart-legend" id="chartLegend"></div>
      <div class="chart-wrap" id="chartWrap"><canvas id="equityChart"></canvas></div>
      <div id="noHistory" style="display:none;text-align:center;padding:32px 0;color:var(--muted);font-size:12px">No equity history yet — data accumulates as the bot runs</div>
    </div>
  </div>
  <div class="grid-2">
    <div class="panel">
      <div class="panel-header"><div class="panel-title">Positions</div><button class="toggle-pill active" id="dustToggle" onclick="toggleDust(this)"><span class="pip"></span>Show dust<span class="dust-count" id="dustCount"></span></button></div>
      <div id="positionsBody"><div class="no-pos">Loading...</div></div>
    </div>
    <div class="panel">
      <div class="panel-header"><div class="panel-title">Latest signal</div><div class="signal-time" id="signalTime"></div></div>
      <div class="alloc-list" id="allocList"><div class="no-pos">Loading...</div></div>
    </div>
  </div>
  <div class="actions">
    <a href="?action=force" class="btn btn-danger" id="forceBtn" onclick="return confirm('Force rebalance now?')">Force rebalance</a>
    <a href="?action=health" class="btn">Health check</a>
    <a href="?" class="btn" id="refreshBtn">Refresh</a>
  </div>
</div>
<div class="footer">
  <span id="lastActed">Last acted: —</span>
  <span id="footerTime"></span>
</div>
<script>
const SK='equity_history_v2',BC='barclose_history_v2';
function loadH(k){try{return JSON.parse(localStorage.getItem(k)||'[]')}catch{return[]}}
function saveH(k,h){try{localStorage.setItem(k,JSON.stringify(h.slice(-365)))}catch{}}
function recordPt(k,v){const h=loadH(k);const t=new Date().toISOString().slice(0,10);const l=h[h.length-1];if(l&&l.date===t){l.value=parseFloat(v.toFixed(2))}else{h.push({date:t,value:parseFloat(v.toFixed(2))})}saveH(k,h);return h}
function filterH(h,r){if(r==='all')return h;const d=r==='7d'?7:30;const c=new Date();c.setDate(c.getDate()-d);const cs=c.toISOString().slice(0,10);return h.filter(p=>p.date>=cs)}
let chart=null,fullA=[],fullB=[],range='7d',series='actual';
function fmt$(v){return'$'+parseFloat(v).toLocaleString('en-US',{minimumFractionDigits:2,maximumFractionDigits:2})}
function buildLegend(a,b){const el=document.getElementById('chartLegend');let h='';if(a)h+='<div class="legend-item"><div class="legend-dot" style="background:#c8f563"></div>Actual equity</div>';if(b)h+='<div class="legend-item"><div class="legend-dot" style="background:#c084fc"></div>Bar close equity</div>';if(a&&b)h+='<div class="legend-item" style="color:#888;font-size:10px">gap = execution alpha loss</div>';el.innerHTML=h}
function buildChart(){
  const showA=series==='actual'||series==='both';
  const showB=series==='barclose'||series==='both';
  const fa=filterH(fullA,range);const fb=filterH(fullB,range);
  buildLegend(showA&&fa.length>0,showB&&fb.length>0);
  const noH=document.getElementById('noHistory');const wrap=document.getElementById('chartWrap');
  const has=(showA&&fa.length>=2)||(showB&&fb.length>=2);
  if(!has){noH.style.display='block';wrap.style.display='none';return}
  noH.style.display='none';wrap.style.display='block';
  const allDates=[...new Set([...(showA?fa:[]).map(p=>p.date),...(showB?fb:[]).map(p=>p.date)])].sort();
  const labels=allDates.map(d=>{const dt=new Date(d);return dt.toLocaleDateString('en-GB',{day:'numeric',month:'short'})});
  const toMap=arr=>Object.fromEntries(arr.map(p=>[p.date,p.value]));
  const aMap=toMap(fa);const bMap=toMap(fb);
  const datasets=[];
  if(showA&&fa.length>=2){const data=allDates.map(d=>aMap[d]??null);const up=fa[fa.length-1].value>=fa[0].value;datasets.push({label:'Actual',data,borderColor:up?'#c8f563':'#ff5c5c',backgroundColor:up?'rgba(200,245,99,0.06)':'rgba(255,92,92,0.06)',borderWidth:1.5,pointRadius:allDates.length>30?0:3,pointHoverRadius:5,pointBackgroundColor:up?'#c8f563':'#ff5c5c',fill:series==='actual',tension:0.35,spanGaps:true})}
  if(showB&&fb.length>=2){datasets.push({label:'Bar close',data:allDates.map(d=>bMap[d]??null),borderColor:'#c084fc',backgroundColor:'rgba(192,132,252,0.06)',borderWidth:1.5,borderDash:[4,3],pointRadius:allDates.length>30?0:3,pointHoverRadius:5,pointBackgroundColor:'#c084fc',fill:series==='barclose',tension:0.35,spanGaps:true})}
  if(chart){chart.data.labels=labels;chart.data.datasets=datasets;chart.update('active');return}
  chart=new Chart(document.getElementById('equityChart'),{type:'line',data:{labels,datasets},options:{responsive:true,maintainAspectRatio:false,interaction:{mode:'index',intersect:false},plugins:{legend:{display:false},tooltip:{backgroundColor:'#1a1a1a',borderColor:'rgba(255,255,255,0.1)',borderWidth:1,titleColor:'#666',bodyColor:'#f0ede8',titleFont:{family:'DM Mono',size:11},bodyFont:{family:'DM Mono',size:12},callbacks:{label:ctx=>{const pre=ctx.dataset.label==='Bar close'?' Bar close: ':' Actual:    ';return pre+fmt$(ctx.parsed.y)}}}},scales:{x:{grid:{color:'rgba(255,255,255,0.04)'},ticks:{color:'#555',font:{family:'DM Mono',size:11},maxTicksLimit:7},border:{display:false}},y:{position:'right',grid:{color:'rgba(255,255,255,0.04)'},ticks:{color:'#555',font:{family:'DM Mono',size:11},callback:v=>'$'+v.toLocaleString()},border:{display:false}}}}});
}
function setRange(r,el){range=r;document.querySelectorAll('#rangeTabs .ctrl-btn').forEach(b=>b.classList.remove('active'));el.classList.add('active');if(chart){chart.destroy();chart=null}buildChart()}
function setSeries(s,el){series=s;document.querySelectorAll('#seriesTabs .ctrl-btn').forEach(b=>b.classList.remove('active'));el.classList.add('active');if(chart){chart.destroy();chart=null}buildChart()}
function exportCSV(){const a=loadH(SK);const b=loadH(BC);if(!a.length&&!b.length){alert('No equity history to export yet.');return}const dates=[...new Set([...a.map(p=>p.date),...b.map(p=>p.date)])].sort();const am=Object.fromEntries(a.map(p=>[p.date,p.value]));const bm=Object.fromEntries(b.map(p=>[p.date,p.value]));const rows=[['date','actual_equity_usd','barclose_equity_usd']];for(const d of dates)rows.push([d,am[d]??'',bm[d]??'']);const csv=rows.map(r=>r.join(',')).join('\n');const blob=new Blob([csv],{type:'text/csv'});const url=URL.createObjectURL(blob);const a2=document.createElement('a');a2.href=url;a2.download='equity_'+new Date().toISOString().slice(0,10)+'.csv';a2.click();URL.revokeObjectURL(url)}
const DUST_USD=0.5;
let _hideDust=true;
let _positions=[];
function fmtSize(size,markPx){
  // Choose decimal places based on price magnitude so dust doesn't read as "0.0100"
  const s=parseFloat(size);
  if(markPx>=10000)return s.toFixed(5);   // BTC: 0.00123
  if(markPx>=1000) return s.toFixed(4);   // ETH: 0.0100 → still 4dp but correct
  if(markPx>=10)   return s.toFixed(3);
  return s.toFixed(2);
}
function fmtPx(v){
  const n=parseFloat(v);
  if(n>=1000)return'$'+n.toLocaleString('en-US',{minimumFractionDigits:0,maximumFractionDigits:0});
  if(n>=1)   return'$'+n.toFixed(2);
  return'$'+n.toFixed(4);
}
function renderPositions(){
  const pb=document.getElementById('positionsBody');
  const dustPos=_positions.filter(p=>p.value<DUST_USD);
  const visPos=_hideDust?_positions.filter(p=>p.value>=DUST_USD):_positions;
  const dc2=document.getElementById('dustCount');
  if(dc2)dc2.textContent=dustPos.length>0?` (${dustPos.length})`:'';
  document.getElementById('posCount').textContent=visPos.length+(_hideDust&&dustPos.length>0?` +${dustPos.length} dust`:'');
  const dc=['#c8f563','#5b9cf6','#f5a623','#ff5c5c','#c084fc'];
  if(!visPos.length){pb.innerHTML=`<div class="no-pos">${_positions.length?'No significant positions — off risk':'No open positions'}</div>`;return;}
  pb.innerHTML=`<table class="pos-table"><thead><tr>
    <th>Asset</th>
    <th class="hide-mobile">Mode</th>
    <th class="hide-mobile">Size</th>
    <th class="hide-mobile">Entry → Mark</th>
    <th>Value</th>
    <th>PnL</th>
  </tr></thead><tbody>${visPos.map((p,i)=>{
    const modeTag=p.mode==='spot'?'<span class="mode-spot">SPOT</span>':'<span class="mode-perp">PERP</span>';
    const markPx=p.markPx||p.entryPx||0;
    const sizeStr=fmtSize(p.size,markPx);
    // Entry → Mark: show both so user can see where they are vs current price
    const entryMark=`<span style="color:var(--muted)">${fmtPx(p.entryPx)}</span><span style="color:var(--muted2)"> → </span>${fmtPx(markPx)}`;
    // PnL: dollar + percent
    const costBasis=p.entryPx>0?parseFloat(p.size)*p.entryPx:p.value-p.pnl;
    const pnlPct=costBasis>0?(p.pnl/costBasis)*100:0;
    const pnlStr=(p.pnl>=0?'+':'')+fmt$(p.pnl)
      +(costBasis>0?` <span style="font-size:10px;opacity:.7">(${pnlPct>=0?'+':''}${pnlPct.toFixed(2)}%)</span>`:'');
    return`<tr>
      <td><span class="coin-badge"><span class="coin-dot" style="background:${dc[i%dc.length]}"></span>${p.coin}</span></td>
      <td class="hide-mobile">${modeTag}</td>
      <td class="hide-mobile" style="font-variant-numeric:tabular-nums">${sizeStr}</td>
      <td class="hide-mobile" style="font-size:12px">${entryMark}</td>
      <td style="color:${p.value<DUST_USD?'var(--muted)':'inherit'}">${fmt$(p.value)}</td>
      <td class="${p.pnl>=0?'pos':'neg'}">${pnlStr}</td>
    </tr>`;
  }).join('')}</tbody></table>`;
}
function toggleDust(btn){
  _hideDust=!_hideDust;
  btn.classList.toggle('active',_hideDust);
  btn.childNodes[1].textContent=_hideDust?'Show dust':'Hide dust';
  renderPositions();
}
function init(d){
  const{account,positions,signal,pending,lastActedId,trwOk,hlOk,isAuto,approvalToken,barCloseEquity}=d;
  document.getElementById('badges').innerHTML=`<span class="badge ${trwOk?'badge-ok':'badge-err'}">TRW ${trwOk?'OK':'ERR'}</span><span class="badge ${hlOk?'badge-ok':'badge-err'}">HL ${hlOk?'OK':'ERR'}</span><span class="badge ${isAuto?'badge-auto':'badge-manual'}" title="${isAuto?'Autonomous 00:00–05:00 UK':'Approval required 05:00–00:00 UK'}">${isAuto?'Auto 00–05':'Approval'}</span>`;
  const tp=positions.reduce((s,p)=>s+p.pnl,0);
  document.getElementById('accountValue').textContent=fmt$(account.value);
  document.getElementById('totalPnl').textContent=(tp>=0?'+':'')+fmt$(tp);
  document.getElementById('totalPnl').className='metric-value '+(tp>=0?'pos':'neg');

  // All-time PnL: difference between current equity and first recorded equity point
  const _allH=loadH(SK);
  const _atEl=document.getElementById('allTimePnl');
  const _atSub=document.getElementById('allTimePnlSub');
  if(_allH.length>=2){
    const _atPnl=account.value-_allH[0].value;
    if(_atEl){_atEl.textContent=(_atPnl>=0?'+':'')+fmt$(_atPnl);_atEl.className='metric-value '+(_atPnl>=0?'pos':'neg')}
    if(_atSub){const _pct=(_atPnl/_allH[0].value*100);_atSub.textContent=(_pct>=0?'+':'')+_pct.toFixed(1)+'%  since '+_allH[0].date}
  } else {
    if(_atEl){_atEl.textContent='—';_atEl.className='metric-value'}
    if(_atSub){_atSub.textContent='accumulating history...'}
  }

  fullA=account.value>0?recordPt(SK,account.value):loadH(SK);
  fullB=loadH(BC);
  if(barCloseEquity&&barCloseEquity>0)fullB=recordPt(BC,barCloseEquity);
  buildChart();
  _positions=positions;
  renderPositions();
  const al=document.getElementById('allocList');const st=document.getElementById('signalTime');
  if(signal&&signal.allocations&&signal.allocations.length){st.textContent=signal.time||'';al.innerHTML=signal.allocations.map(a=>`<div class="alloc-row"><div class="alloc-pct">${a.percent}%</div><div class="alloc-bar-wrap"><div class="alloc-bar" style="width:${a.percent}%"></div></div><div class="alloc-asset">${a.asset}</div><div class="alloc-type">${a.type}</div></div>`).join('')}
  else{al.innerHTML='<div class="no-pos">No signal found</div>'}
  if(pending&&approvalToken){const bn=document.getElementById('pendingBanner');bn.style.display='block';document.getElementById('pendingAllocs').innerHTML=pending.map(a=>`<span><strong>${a.percent}%</strong> ${a.asset}</span>`).join('');document.getElementById('approveBtn').href='?action=approve&token='+approvalToken;document.getElementById('approveBtn').onclick=()=>confirm('Execute rebalance now?');document.getElementById('dismissBtn').href='?action=dismiss&token='+approvalToken}
  const forceBtn=document.getElementById('forceBtn');
  if(forceBtn&&approvalToken)forceBtn.href='?action=force&token='+approvalToken;

  const _auth=new URLSearchParams(window.location.search).get('auth')||'';
  if(_auth){
    document.querySelectorAll('a[href^="?"]').forEach(a=>{
      if(!a.href.includes('auth='))a.href+=(a.href.includes('?')&&a.href!=='?'?'&':'?')+'auth='+encodeURIComponent(_auth);
    });
    // Fix tab nav links
    const histTab=document.getElementById('histTab');
    if(histTab)histTab.href='?action=history&auth='+encodeURIComponent(_auth);
  }
  document.getElementById('lastActed').textContent='Last acted: '+(lastActedId&&lastActedId!=='none'?lastActedId.slice(0,12)+'...':'none');
  document.getElementById('footerTime').textContent=new Date().toLocaleString('en-GB',{timeZone:'UTC'})+' UTC';
}
init(DASHBOARD_DATA);

let _refreshTimer = null;
const REFRESH_MS = 60000;

function startRefresh() {
  if (_refreshTimer) return;
  _refreshTimer = setInterval(() => {
    if (!document.hidden) {
      const btn = document.getElementById('refreshBtn');
      if (btn) { btn.textContent = 'Refreshing...'; btn.style.opacity = '0.5'; }
      const _auth=new URLSearchParams(window.location.search).get('auth')||'';
      window.location.href = _auth ? '?auth='+encodeURIComponent(_auth) : '?';
    }
  }, REFRESH_MS);
}

function stopRefresh() {
  clearInterval(_refreshTimer);
  _refreshTimer = null;
}

document.addEventListener('visibilitychange', () => {
  document.hidden ? stopRefresh() : startRefresh();
});

startRefresh();

const _footer = document.getElementById('footerTime');
if (_footer) {
  let _secs = 0;
  setInterval(() => {
    _secs++;
    const remaining = Math.max(0, Math.round((REFRESH_MS - _secs * 1000) / 1000));
    const base = new Date().toLocaleString('en-GB', { timeZone: 'UTC' }) + ' UTC';
    _footer.textContent = base + '  ·  refresh in ' + remaining + 's';
  }, 1000);
}
</script>
</body>
</html>"""


def _render_dashboard() -> str:
    """Build dashboard HTML with live data + bar close equity injected as JSON."""

    signal_msg, parsed, signal_time, trw_ok = None, None, "N/A", False
    try:
        messages   = fetch_recent_messages(limit=20)
        signal_msg = find_latest_signal(messages)
        if signal_msg:
            parsed      = parse_signal(signal_msg["content"])
            signal_time = datetime.fromtimestamp(
                signal_msg["timestamp"] / 1000, tz=timezone.utc
            ).strftime("%Y-%m-%d %H:%M UTC")
            trw_ok = True
    except Exception:
        pass

    state = {"account_value": 0, "positions": {}}
    hl_ok = False
    try:
        info, _ = get_hl_clients()
        state   = get_account_state(info)
        hl_ok   = True
    except Exception:
        pass

    pending_allocs = None
    approval_token = ""
    try:
        pending_raw    = signal_state.get("pending_signal", "null")
        pending_parsed = json.loads(pending_raw)
        if pending_parsed:
            pending_allocs = pending_parsed.get("allocations", [])
        approval_token = signal_state.get("approval_token", "")
    except Exception:
        pass

    last_acted_id = "none"
    try:
        last_acted_id = signal_state["last_signal_id"]
    except KeyError:
        pass

    # ── Bar close equity reconstruction ──────────────────────────────────────
    # Computes what the portfolio would be worth if filled exactly at bar close.
    # For assets where we have a bar-close price: scale target % by ratio of
    # current price to bar-close price so we get the fill-price-adjusted value.
    bar_close_equity = None
    try:
        bar_close_px   = json.loads(signal_state.get("bar_close_prices", "{}"))
        account_value  = state.get("account_value", 0)
        if bar_close_px and parsed and parsed.get("allocations") and account_value > 0:
            all_mids_now: dict = {}
            try:
                _info, _ = get_hl_clients()
                all_mids_now = _info.all_mids()
            except Exception:
                pass
            bc_equity = 0.0
            for alloc in parsed["allocations"]:
                asset    = alloc["asset"]
                pct      = alloc["percent"] / 100.0
                bc_price = bar_close_px.get(asset)
                ticker   = ASSET_TO_TICKER.get(asset, asset)
                now_price = float(all_mids_now.get(ticker, 0)) if all_mids_now else 0
                if bc_price and bc_price > 0 and now_price > 0:
                    # Ratio: if you bought at bar-close, your position is now worth:
                    bc_equity += account_value * pct * (now_price / bc_price)
                else:
                    bc_equity += account_value * pct  # fallback: same value
            bar_close_equity = round(bc_equity, 2)
    except Exception:
        pass

    positions_js = [
        {
            "coin":    coin,
            "size":    pos.get("size", 0),
            "entryPx": pos.get("entry_px", 0),
            "markPx":  pos.get("mark_px", pos.get("entry_px", 0)),
            "value":   pos.get("value_usd", 0),
            "pnl":     pos.get("unrealized_pnl", 0),
            "mode":    pos.get("mode", "perp"),
        }
        for coin, pos in state.get("positions", {}).items()
    ]

    signal_js = None
    if parsed and parsed.get("allocations"):
        signal_js = {
            "time": signal_time,
            "allocations": [
                {"percent": a["percent"], "asset": a["asset"], "type": a.get("type", "Spot")}
                for a in parsed["allocations"]
            ],
        }

    dashboard_data = {
        "trwOk":          trw_ok,
        "hlOk":           hl_ok,
        "isAuto":         is_autonomous_hours(),
        "account":        {"value": state.get("account_value", 0)},
        "positions":      positions_js,
        "signal":         signal_js,
        "pending":        pending_allocs,
        "approvalToken":  approval_token,
        "lastActedId":    last_acted_id,
        "barCloseEquity": bar_close_equity,
    }

    data_json = json.dumps(dashboard_data)
    return _DASHBOARD_HTML.replace(
        "init(DASHBOARD_DATA);",
        f"const DASHBOARD_DATA = {data_json};\ninit(DASHBOARD_DATA);"
    )

# ══════════════════════════════════════════════════════════════════════════════
# HISTORY TAB — backend
# ══════════════════════════════════════════════════════════════════════════════

def _fetch_history_signals(limit: int = 600) -> list[dict]:
    """
    Paginate through TRW channel to collect ALL Portfolio Signal Update
    messages from Prof Adam, up to `limit` total messages scanned.
    Returns list sorted oldest → newest.
    """
    import requests as req
    PROF_ADAM  = os.environ.get("TRW_PROF_ADAM_USER_ID", "01GHHHWZE7Q77AKGWZDGC5PDCN")
    CHANNEL_ID = os.environ.get("TRW_SIGNAL_CHANNEL_ID", "01H83QAX979K9R7QTMH74ATR8C")
    TOKEN      = os.environ["TRW_SESSION_TOKEN"]
    signals    = []
    before_id  = None
    scanned    = 0

    while scanned < limit:
        body: dict = {"channel": CHANNEL_ID, "limit": 20, "sort": "Latest"}
        if before_id:
            body["before"] = before_id
        try:
            resp = req.post(
                "https://eden.therealworld.ag/messages/query",
                headers={
                    "x-session-token": TOKEN,
                    "Content-Type": "application/json",
                    "Origin": "https://app.jointherealworld.com",
                },
                json=body, timeout=15,
            )
            if resp.status_code == 401:
                raise RuntimeError("TRW session token expired")
            resp.raise_for_status()
            messages = resp.json().get("messages", [])
        except Exception as e:
            print(f"[history] fetch error: {e}")
            break

        if not messages:
            break

        for msg in messages:
            if (msg.get("author") == PROF_ADAM
                    and "Portfolio Signal Update" in msg.get("content", "")):
                signals.append(msg)

        scanned  += len(messages)
        before_id = messages[-1]["_id"]
        if len(messages) < 20:
            break   # no more pages

    signals.sort(key=lambda m: m.get("timestamp", 0))
    return signals


def _render_history(auth: str = "") -> str:
    """Build the History tab HTML with auth token injected."""
    token = os.environ.get("TRW_SESSION_TOKEN", "")
    auth_param = f"&auth={auth}" if auth else ""
    html = _HISTORY_HTML
    # Inject session token so JS can call Binance/CoinGecko directly
    html = html.replace("__TRW_TOKEN_PLACEHOLDER__", token)
    html = html.replace("__AUTH_PARAM_PLACEHOLDER__", auth_param)
    return html


# ══════════════════════════════════════════════════════════════════════════════
# HISTORY TAB — HTML
# ══════════════════════════════════════════════════════════════════════════════

_HISTORY_HTML = r"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1, maximum-scale=1">
<title>Signal Bot — History</title>
<script src="https://cdnjs.cloudflare.com/ajax/libs/Chart.js/4.4.1/chart.umd.js"></script>
<style>
  @import url('https://fonts.googleapis.com/css2?family=DM+Mono:wght@400;500&family=Syne:wght@400;600;700&display=swap');
  *,*::before,*::after{box-sizing:border-box;margin:0;padding:0}
  :root{
    --bg:#0a0a0a;--surface:#111111;--surface2:#1a1a1a;--surface3:#222222;
    --border:rgba(255,255,255,0.08);--border2:rgba(255,255,255,0.14);
    --text:#f0ede8;--muted:#6b6860;--muted2:#3e3c3a;
    --accent:#c8f563;--accent-dim:rgba(200,245,99,0.12);
    --red:#ff5c5c;--red-dim:rgba(255,92,92,0.12);
    --blue:#5b9cf6;--blue-dim:rgba(91,156,246,0.12);
    --amber:#f5a623;--amber-dim:rgba(245,166,35,0.12);
    --purple:#c084fc;--purple-dim:rgba(192,132,252,0.12);
    --font-mono:'DM Mono',monospace;--font-display:'Syne',sans-serif
  }
  body{background:var(--bg);color:var(--text);font-family:var(--font-mono);font-size:13px;line-height:1.6;min-height:100vh}
  .header{display:flex;align-items:center;justify-content:space-between;padding:16px 20px;border-bottom:1px solid var(--border);position:sticky;top:0;background:var(--bg);z-index:20;gap:10px}
  .header-left{display:flex;align-items:center;gap:12px}
  .logo{font-family:var(--font-display);font-size:15px;font-weight:700;letter-spacing:-0.02em}
  .logo span{color:var(--accent)}
  .tab-nav{display:flex;gap:1px;background:var(--border);border-radius:5px;overflow:hidden;padding:1px}
  .tab-btn{font-size:11px;font-family:var(--font-mono);letter-spacing:.06em;text-transform:uppercase;padding:5px 12px;border-radius:4px;cursor:pointer;color:var(--muted);border:none;background:none;transition:all .15s;white-space:nowrap;text-decoration:none;display:inline-block}
  .tab-btn.active{background:var(--surface2);color:var(--text)}
  .tab-btn:hover:not(.active){color:var(--text)}
  .main{padding:16px 20px;max-width:1200px}
  .config-panel{background:var(--surface);border:1px solid var(--border);border-radius:8px;padding:16px;margin-bottom:16px}
  .config-title{font-size:10px;letter-spacing:.12em;text-transform:uppercase;color:var(--muted);margin-bottom:12px}
  .config-grid{display:grid;grid-template-columns:repeat(auto-fit,minmax(170px,1fr));gap:12px;align-items:end}
  .config-field{display:flex;flex-direction:column;gap:5px}
  .config-label{font-size:10px;letter-spacing:.08em;text-transform:uppercase;color:var(--muted)}
  .config-input{background:var(--surface2);border:1px solid var(--border2);border-radius:5px;color:var(--text);font-family:var(--font-mono);font-size:13px;padding:7px 10px;outline:none;transition:border-color .15s}
  .config-input:focus{border-color:rgba(200,245,99,.4)}
  .config-actions{display:flex;gap:8px;flex-wrap:wrap;align-items:center;margin-top:12px}
  .config-note{font-size:11px;color:var(--muted);margin-top:10px;line-height:1.6;padding-top:10px;border-top:1px solid var(--border)}
  .btn{font-family:var(--font-mono);font-size:11px;letter-spacing:.06em;text-transform:uppercase;padding:8px 14px;border-radius:5px;cursor:pointer;border:1px solid var(--border2);background:var(--surface);color:var(--text);text-decoration:none;display:inline-flex;align-items:center;gap:6px;transition:all .15s;white-space:nowrap}
  .btn:hover:not(:disabled){background:var(--surface2)}
  .btn:disabled{opacity:.35;cursor:default;pointer-events:none}
  .btn-accent{background:var(--accent-dim);border-color:rgba(200,245,99,.35);color:var(--accent)}
  .btn-accent:hover:not(:disabled){background:rgba(200,245,99,.2)}
  .btn-export{background:var(--blue-dim);border-color:rgba(91,156,246,.35);color:var(--blue)}
  .btn-export:hover:not(:disabled){background:rgba(91,156,246,.2)}
  .metrics{display:grid;grid-template-columns:repeat(5,1fr);gap:1px;background:var(--border);border:1px solid var(--border);border-radius:8px;overflow:hidden;margin-bottom:16px}
  .metric{background:var(--surface);padding:14px 16px}
  .metric-label{font-size:10px;letter-spacing:.1em;text-transform:uppercase;color:var(--muted);margin-bottom:6px}
  .metric-value{font-family:var(--font-display);font-size:20px;font-weight:700;letter-spacing:-0.02em;line-height:1}
  .metric-sub{font-size:11px;color:var(--muted);margin-top:3px}
  .pos{color:var(--accent)}.neg{color:var(--red)}
  .chart-section{background:var(--surface);border:1px solid var(--border);border-radius:8px;margin-bottom:16px;overflow:hidden}
  .chart-header{display:flex;align-items:center;justify-content:space-between;padding:12px 14px;border-bottom:1px solid var(--border);flex-wrap:wrap;gap:8px}
  .panel-title{font-size:10px;letter-spacing:.1em;text-transform:uppercase;color:var(--muted);font-weight:500}
  .chart-controls{display:flex;gap:6px;flex-wrap:wrap;align-items:center}
  .ctrl-group{display:flex;gap:2px;background:var(--bg);border:1px solid var(--border);border-radius:4px;padding:2px}
  .ctrl-btn{font-size:11px;font-family:var(--font-mono);padding:4px 9px;border-radius:3px;cursor:pointer;color:var(--muted);border:none;background:none;transition:all .15s;letter-spacing:.04em;white-space:nowrap}
  .ctrl-btn.active{background:var(--surface2);color:var(--text)}
  .ctrl-btn:hover:not(.active){color:var(--text)}
  .chart-body{padding:14px}
  .chart-legend{display:flex;gap:14px;margin-bottom:10px;flex-wrap:wrap}
  .legend-item{display:flex;align-items:center;gap:5px;font-size:11px;color:var(--muted)}
  .legend-dot{width:8px;height:8px;border-radius:50%;flex-shrink:0}
  .chart-wrap{position:relative;width:100%;height:260px}
  .chart-note{font-size:10px;color:var(--muted2);padding:8px 14px;border-top:1px solid var(--border);line-height:1.6}
  /* kelly panel */
  .kelly-section{background:var(--surface);border:1px solid var(--border);border-radius:8px;margin-bottom:16px;overflow:hidden}
  .kelly-header{display:flex;align-items:center;justify-content:space-between;padding:12px 14px;border-bottom:1px solid var(--border);flex-wrap:wrap;gap:10px}
  .kelly-body{padding:16px}
  .kelly-fraction-row{display:flex;align-items:center;gap:14px;margin-bottom:18px;flex-wrap:wrap}
  .fraction-label{font-size:11px;color:var(--muted);white-space:nowrap}
  .fraction-slider{flex:1;min-width:160px;accent-color:var(--accent);height:4px;cursor:pointer}
  .fraction-value{font-family:var(--font-display);font-size:18px;font-weight:700;color:var(--accent);min-width:44px;text-align:right}
  .kelly-grid{display:grid;grid-template-columns:repeat(auto-fill,minmax(200px,1fr));gap:10px}
  .kelly-card{background:var(--surface2);border:1px solid var(--border);border-radius:6px;padding:13px 14px}
  .kelly-card-asset{font-family:var(--font-display);font-size:14px;font-weight:700;margin-bottom:8px;display:flex;align-items:center;gap:8px}
  .kelly-card-rows{display:flex;flex-direction:column;gap:5px}
  .kelly-row{display:flex;justify-content:space-between;font-size:11px}
  .kelly-key{color:var(--muted)}
  .kelly-val{font-family:var(--font-display);font-weight:600}
  .kelly-bar-wrap{height:3px;background:var(--border2);border-radius:2px;margin-top:9px;overflow:hidden}
  .kelly-bar{height:100%;border-radius:2px;transition:width .4s ease}
  .kelly-note{font-size:10px;color:var(--muted2);margin-top:14px;padding-top:10px;border-top:1px solid var(--border);line-height:1.6}
  .kelly-empty{padding:30px;text-align:center;color:var(--muted);font-size:12px}
  /* signal table */
  .table-section{background:var(--surface);border:1px solid var(--border);border-radius:8px;overflow:hidden;margin-bottom:16px}
  .table-header{display:flex;align-items:center;justify-content:space-between;padding:12px 14px;border-bottom:1px solid var(--border)}
  .sig-table{width:100%;border-collapse:collapse}
  .sig-table th{font-size:10px;letter-spacing:.08em;text-transform:uppercase;color:var(--muted);font-weight:500;padding:9px 14px;text-align:left;border-bottom:1px solid var(--border);white-space:nowrap}
  .sig-table th:not(:first-child){text-align:right}
  .sig-table td{padding:10px 14px;border-bottom:1px solid var(--border);font-size:12px;vertical-align:middle}
  .sig-table td:not(:first-child){text-align:right}
  .sig-table tr:last-child td{border-bottom:none}
  .sig-table tr:hover td{background:var(--surface2)}
  .alloc-pills{display:flex;gap:4px;flex-wrap:wrap;justify-content:flex-end}
  .pill{font-size:10px;padding:2px 6px;border-radius:3px;white-space:nowrap}
  .pill-eth{background:rgba(91,156,246,.15);color:#5b9cf6;border:1px solid rgba(91,156,246,.25)}
  .pill-btc{background:rgba(245,166,35,.15);color:#f5a623;border:1px solid rgba(245,166,35,.25)}
  .pill-hype{background:rgba(200,245,99,.12);color:#c8f563;border:1px solid rgba(200,245,99,.25)}
  .pill-sol{background:rgba(192,132,252,.15);color:#c084fc;border:1px solid rgba(192,132,252,.25)}
  .pill-paxg{background:rgba(255,215,0,.15);color:#ffd700;border:1px solid rgba(255,215,0,.25)}
  .pill-usdc{background:rgba(255,255,255,.06);color:var(--muted);border:1px solid var(--border2)}
  .pill-other{background:var(--surface3);color:var(--text);border:1px solid var(--border2)}
  .badge{font-size:10px;padding:2px 7px;border-radius:3px;font-family:var(--font-mono)}
  .badge-pos{background:var(--accent-dim);color:var(--accent);border:1px solid rgba(200,245,99,.25)}
  .badge-neg{background:var(--red-dim);color:var(--red);border:1px solid rgba(255,92,92,.25)}
  .badge-flat{background:var(--surface3);color:var(--muted);border:1px solid var(--border)}
  /* cloud equity banner */
  .cloud-banner{background:var(--surface);border:1px solid var(--border);border-radius:8px;padding:12px 14px;margin-bottom:16px;display:flex;align-items:center;gap:10px;font-size:11px;color:var(--muted)}
  .cloud-banner.cloud-ok{border-color:rgba(200,245,99,.2);background:rgba(200,245,99,.04)}
  .cloud-banner.cloud-warn{border-color:rgba(245,166,35,.2);background:rgba(245,166,35,.04)}
  /* loading */
  .loading-overlay{position:fixed;inset:0;background:rgba(10,10,10,.9);display:flex;flex-direction:column;align-items:center;justify-content:center;z-index:100;gap:14px}
  .loading-overlay.hidden{display:none}
  .loading-title{font-family:var(--font-display);font-size:14px;color:var(--text)}
  .loading-sub{font-size:11px;color:var(--muted);text-align:center;max-width:340px;line-height:1.6}
  .spinner{border:2px solid var(--border2);border-top-color:var(--accent);border-radius:50%;animation:spin .7s linear infinite}
  @keyframes spin{to{transform:rotate(360deg)}}
  .progress-bar{width:280px;height:2px;background:var(--border2);border-radius:1px;overflow:hidden}
  .progress-fill{height:100%;background:var(--accent);border-radius:1px;transition:width .4s ease}
  .empty{padding:44px 20px;text-align:center;color:var(--muted);font-size:12px}
  .status-ok{color:var(--accent)}.status-err{color:var(--red)}.status-warn{color:var(--amber)}
  .footer{padding:14px 20px;border-top:1px solid var(--border);display:flex;justify-content:space-between;font-size:11px;color:var(--muted);flex-wrap:wrap;gap:6px}
  @media(max-width:700px){
    .header,.main{padding:10px 14px}
    .metrics{grid-template-columns:repeat(2,1fr)}
    .metric{padding:12px}
    .metric-value{font-size:16px}
    .chart-wrap{height:200px}
    .sig-table .hm{display:none}
    .config-grid{grid-template-columns:1fr 1fr}
    .kelly-grid{grid-template-columns:1fr 1fr}
  }
  @media(max-width:480px){.logo{display:none}}
  @media(max-width:420px){.metrics{grid-template-columns:1fr}.config-grid{grid-template-columns:1fr}.kelly-grid{grid-template-columns:1fr}}
  ::-webkit-scrollbar{width:4px;height:4px}
  ::-webkit-scrollbar-thumb{background:var(--border2);border-radius:2px}
</style>
</head>
<body>

<div class="loading-overlay hidden" id="loadingOverlay">
  <div class="spinner" style="width:22px;height:22px"></div>
  <div class="loading-title" id="loadingTitle">Fetching signals…</div>
  <div class="progress-bar"><div class="progress-fill" id="progressFill"></div></div>
  <div class="loading-sub" id="loadingSub"></div>
</div>

<div class="header">
  <div class="header-left">
    <div class="logo">signal<span>bot</span></div>
    <div class="tab-nav">
      <a class="tab-btn" id="dashTab" href="?__AUTH_PARAM_PLACEHOLDER__">Dashboard</a>
      <a class="tab-btn active" href="#">History</a>
    </div>
  </div>
</div>

<div class="main">

  <!-- Cloud equity status banner -->
  <div class="cloud-banner" id="cloudBanner" style="display:none">
    <svg width="12" height="12" viewBox="0 0 12 12" fill="currentColor" style="flex-shrink:0"><path d="M9.5 5.5a3.5 3.5 0 10-6.86-.9A2.5 2.5 0 003 9.5h6a2 2 0 00.5-3.93V5.5z"/></svg>
    <span id="cloudBannerText"></span>
  </div>

  <div class="config-panel">
    <div class="config-title">Backtest Configuration</div>
    <div class="config-grid">
      <div class="config-field">
        <label class="config-label">Starting Balance (USD)</label>
        <input class="config-input" id="startBalance" type="number" value="10000" min="1" step="100">
      </div>
      <div class="config-field">
        <label class="config-label">Start Date (blank = all history)</label>
        <input class="config-input" id="startDate" type="date">
      </div>
      <div class="config-field">
        <label class="config-label">HL Taker Fee %</label>
        <input class="config-input" id="feeRate" type="number" value="0.035" min="0" max="1" step="0.005">
      </div>
    </div>
    <div class="config-actions">
      <button class="btn btn-accent" id="runBtn" onclick="runBacktest()">
        <svg width="10" height="10" viewBox="0 0 10 10" fill="currentColor"><path d="M1 1l8 4-8 4V1z"/></svg>
        Run Backtest
      </button>
      <button class="btn btn-export" id="exportBtn" onclick="exportCSV()" disabled>⬇ Export CSV</button>
      <span id="statusMsg" style="font-size:11px"></span>
    </div>
    <div class="config-note">
      Prices: <strong>Binance 5m candle close</strong> at exact signal timestamp (falls back 1m → 15m → 1h).
      PAXG uses CoinGecko daily. Fees on rebalance notional. Slippage excluded.
      After running, backtest equity is pushed to cloud storage so it fills in history for everyone.
    </div>
  </div>

  <div class="metrics">
    <div class="metric"><div class="metric-label">Total Return</div><div class="metric-value" id="mTR">—</div><div class="metric-sub" id="mTRsub">–</div></div>
    <div class="metric"><div class="metric-label">CAGR</div><div class="metric-value" id="mCAGR">—</div><div class="metric-sub" id="mCAGRsub">annualised</div></div>
    <div class="metric"><div class="metric-label">Max Drawdown</div><div class="metric-value" id="mMDD">—</div><div class="metric-sub" id="mMDDsub">peak→trough</div></div>
    <div class="metric"><div class="metric-label">Win Rate</div><div class="metric-value" id="mWR">—</div><div class="metric-sub" id="mWRsub">periods up</div></div>
    <div class="metric"><div class="metric-label">Signals</div><div class="metric-value" id="mSig">—</div><div class="metric-sub" id="mSigsub">parsed</div></div>
  </div>

  <div class="chart-section">
    <div class="chart-header">
      <div class="panel-title">Equity Curve</div>
      <div class="chart-controls">
        <div class="ctrl-group" id="seriesTabs">
          <button class="ctrl-btn active" onclick="setSeries('actual',this)">Signal px</button>
          <button class="ctrl-btn" onclick="setSeries('barclose',this)">Bar close</button>
          <button class="ctrl-btn" onclick="setSeries('live',this)">Live</button>
          <button class="ctrl-btn" onclick="setSeries('merged',this)">Merged</button>
        </div>
        <div class="ctrl-group" id="rangeTabs">
          <button class="ctrl-btn" onclick="setRange('3m',this)">3m</button>
          <button class="ctrl-btn" onclick="setRange('6m',this)">6m</button>
          <button class="ctrl-btn" onclick="setRange('1y',this)">1y</button>
          <button class="ctrl-btn active" onclick="setRange('all',this)">All</button>
        </div>
      </div>
    </div>
    <div class="chart-body">
      <div class="chart-legend" id="chartLegend"></div>
      <div id="chartWrap" class="chart-wrap" style="display:none"><canvas id="equityChart"></canvas></div>
      <div id="noHistory" class="empty">Run the backtest above to generate the equity curve</div>
    </div>
    <div class="chart-note">
      <strong>Signal px</strong> — 5m close at exact signal time.
      <strong>Bar close</strong> — next complete 5m bar close (worst-case fill timing).
      <strong>Live</strong> — real account snapshots stored in cloud (recorded hourly by bot).
      <strong>Merged</strong> — backtest fills in pre-deployment history, live takes over from bot launch.
    </div>
  </div>

  <!-- Kelly Criterion Panel -->
  <div class="kelly-section">
    <div class="kelly-header">
      <div class="panel-title">Kelly Criterion — Optimal Allocation per Asset</div>
      <div style="display:flex;align-items:center;gap:12px;flex-wrap:wrap">
        <div class="kelly-fraction-row" style="margin:0">
          <span class="fraction-label">Fraction:</span>
          <input type="range" class="fraction-slider" id="kellySlider" min="0.1" max="1.0" step="0.05" value="0.5" oninput="onFractionChange(this.value)">
          <span class="fraction-value" id="kellyFractionVal">0.5×</span>
        </div>
        <span style="font-size:10px;color:var(--muted2)">Half-Kelly is default · drag to adjust</span>
      </div>
    </div>
    <div class="kelly-body">
      <div id="kellyCards"><div class="kelly-empty">Run backtest to calculate Kelly fractions</div></div>
      <div class="kelly-note" id="kellyNote" style="display:none"></div>
    </div>
  </div>

  <div class="table-section">
    <div class="table-header">
      <div class="panel-title">Signal History</div>
      <span id="tableCount" style="font-size:11px;color:var(--muted)"></span>
    </div>
    <div id="tableBody"><div class="empty">No data — run backtest first</div></div>
  </div>

</div>

<div class="footer">
  <span>Prices: Binance 5m close · CoinGecko daily (PAXG) · Cloud equity stored per-hour in Modal Dict</span>
  <span id="footerTime"></span>
</div>

<script>
// ── Injected server-side ──────────────────────────────────────────────────────
const _TRW_TOKEN = '__TRW_TOKEN_PLACEHOLDER__';

// ── Signal parser (JS port of trw_signal_reader.py) ───────────────────────────
function parseSignal(content) {
  const r = { allocations: [], no_change: false };
  const execM = content.match(/Executive Summary:([\s\S]+?)(?:Associated Data|$)/);
  if (execM && execM[1].toLowerCase().includes('no change')) r.no_change = true;
  const sigM = content.match(/(?:RSPS Signal|Risk-On Crypto Signal|\*\*Signal:\*\*)[\s\S]*?(?:Executive Summary|Associated Data|───|$)/);
  if (sigM) {
    const sec = sigM[0];
    const re = /\*?\*?(\d+(?:\.\d+)?)\s*%\s*(Spot|Gold|Leverage|Cash)?\s*\$?([\w/$]+)\*?\*?/gi;
    let m;
    while ((m = re.exec(sec)) !== null) {
      let [, pct, type, asset] = m;
      asset = asset.replace(/^\$+|\*+$/g, '').toUpperCase();
      if (asset === 'GOLD' || (type && type.toLowerCase() === 'gold')) {
        const gm = sec.match(/PAXG(?:\s*\/\s*\$?XAUT)?/i);
        asset = gm ? gm[0].toUpperCase().replace(/[\s$]/g,'') : 'PAXG/XAUT';
        type = 'Gold';
      } else if (asset === 'CASH' || (type && type.toLowerCase() === 'cash')) {
        type = 'Cash'; asset = 'USDC';
      } else {
        type = type ? type[0].toUpperCase()+type.slice(1).toLowerCase() : 'Spot';
      }
      r.allocations.push({ percent: parseFloat(pct), type, asset });
    }
  }
  return r;
}

// ── Price fetching ─────────────────────────────────────────────────────────────
const BINANCE_SYM = {
  ETH:'ETHUSDT',BTC:'BTCUSDT',HYPE:'HYPEUSDT',SOL:'SOLUSDT',
  DOGE:'DOGEUSDT',XRP:'XRPUSDT',BNB:'BNBUSDT',AVAX:'AVAXUSDT',
  LINK:'LINKUSDT',UNI:'UNIUSDT',AAVE:'AAVEUSDT',ARB:'ARBUSDT',
};
const priceCache = {};
async function getBinancePrice(asset, tsMs, barClose=false) {
  const sym = BINANCE_SYM[asset]; if (!sym) return null;
  const intervals = [{iv:'5m',ms:300_000},{iv:'1m',ms:60_000},{iv:'15m',ms:900_000},{iv:'1h',ms:3_600_000}];
  for (const {iv, ms} of intervals) {
    const candleStart = Math.floor(tsMs/ms)*ms;
    const targetStart = barClose ? candleStart+ms : candleStart;
    const ck = `${sym}_${targetStart}_${iv}`;
    if (priceCache[ck]!==undefined) return priceCache[ck];
    try {
      const r = await fetch(`https://api.binance.com/api/v3/klines?symbol=${sym}&interval=${iv}&startTime=${targetStart}&limit=1`);
      if (!r.ok) continue;
      const d = await r.json();
      if (!d||!d[0]) continue;
      const p = parseFloat(d[0][4]);
      priceCache[ck]=p; return p;
    } catch { continue; }
  }
  return null;
}
const cgCache = {};
async function getPaxgPrice(tsMs) {
  const d=new Date(tsMs);
  const key=`${String(d.getUTCDate()).padStart(2,'0')}-${String(d.getUTCMonth()+1).padStart(2,'0')}-${d.getUTCFullYear()}`;
  if (cgCache[key]!==undefined) return cgCache[key];
  try {
    const r=await fetch(`https://api.coingecko.com/api/v3/coins/pax-gold/history?date=${key}&localization=false`);
    if (!r.ok) return null;
    const data=await r.json();
    const p=data?.market_data?.current_price?.usd||null;
    if (p) cgCache[key]=p; return p;
  } catch { return null; }
}
async function getPrice(asset,tsMs,barClose=false) {
  const a=asset.split('/')[0];
  if (a==='PAXG'||a==='XAUT') return getPaxgPrice(tsMs);
  if (a==='USDC'||a==='CASH') return 1.0;
  return getBinancePrice(a,tsMs,barClose);
}
async function fetchAllPrices(assets,tsMs,barClose) {
  const prices={};
  await Promise.all(assets.map(async a=>{const p=await getPrice(a,tsMs,barClose);if(p!==null)prices[a]=p;}));
  return prices;
}

// ── Fee model ─────────────────────────────────────────────────────────────────
function calcFee(prevAllocs,newAllocs,equity,feeRate) {
  const prev=Object.fromEntries(prevAllocs.map(a=>[a.asset,a.percent/100]));
  const next=Object.fromEntries(newAllocs.map(a=>[a.asset,a.percent/100]));
  const assets=new Set([...Object.keys(prev),...Object.keys(next)]);
  let buyNotional=0;
  for (const a of assets){const delta=(next[a]||0)-(prev[a]||0);if(delta>0)buyNotional+=delta*equity;}
  return buyNotional*2*feeRate;
}

// ── Cloud equity ──────────────────────────────────────────────────────────────
let _liveSnaps = [];   // [{ts,v}] from cloud
async function loadCloudEquity() {
  const banner=document.getElementById('cloudBanner');
  const bannerText=document.getElementById('cloudBannerText');
  try {
    const authParam = window._auth ? '&auth='+encodeURIComponent(window._auth) : '';
    const r=await fetch('?action=equity_history'+authParam);
    if (!r.ok) throw new Error('HTTP '+r.status);
    const data=await r.json();
    if (Array.isArray(data)&&data.length>0) {
      _liveSnaps=data;
      banner.className='cloud-banner cloud-ok';
      banner.style.display='flex';
      const first=new Date(_liveSnaps[0].ts).toISOString().slice(0,10);
      const last=new Date(_liveSnaps[_liveSnaps.length-1].ts).toISOString().slice(0,10);
      bannerText.textContent=`☁ Cloud equity loaded — ${_liveSnaps.length} snapshots · ${first} → ${last}`;
    } else {
      banner.className='cloud-banner cloud-warn';
      banner.style.display='flex';
      bannerText.textContent='☁ Cloud equity: no snapshots yet — deploy the bot to start accumulating hourly data';
    }
  } catch(e) {
    banner.className='cloud-banner cloud-warn';
    banner.style.display='flex';
    bannerText.textContent='☁ Cloud equity unavailable ('+e.message+')';
  }
}
async function pushBacktestToCloud(timeline) {
  if (window._btPushed) return;
  window._btPushed = true;
  try {
    const points = timeline.map(t => ({ts: t.ts, v: t.equity}));
    const authParam = window._auth ? '&auth='+encodeURIComponent(window._auth) : '';
    const encoded  = encodeURIComponent(JSON.stringify({points}));
    const r = await fetch('?action=equity_store_backtest'+authParam+'&points='+encoded);
    if (r.ok) console.log('[history] backtest equity pushed to cloud');
  } catch(e) { console.warn('[history] cloud push failed:', e); }
}

// ── Backtest engine ───────────────────────────────────────────────────────────
let _result = null;
async function runBacktest() {
  const startBalance=parseFloat(document.getElementById('startBalance').value)||10000;
  const startDateStr=document.getElementById('startDate').value;
  const feeRate=(parseFloat(document.getElementById('feeRate').value)||0.035)/100;
  setStatus('','');
  document.getElementById('exportBtn').disabled=true;
  window._btPushed=false;
  showOverlay(true);
  setProgress(0,'Fetching signals from TRW…','');

  let rawSignals=[];
  try {
    const authParam=window._auth?'&auth='+encodeURIComponent(window._auth):'';
    const pr=await fetch('?action=history_signals'+authParam);
    if (pr.ok){const d=await pr.json();if(Array.isArray(d)&&d.length>0)rawSignals=d;}
  } catch {}
  if (!rawSignals.length) {
    const token=_TRW_TOKEN||localStorage.getItem('trw_token')||'';
    if (!token){hideOverlay();promptToken();return;}
    try{rawSignals=await fetchTRWSignals(token);}
    catch(e){hideOverlay();if(e.message==='TOKEN_EXPIRED'){promptToken();return;}setStatus('err','Fetch error: '+e.message);return;}
  }
  if (!rawSignals.length){hideOverlay();setStatus('warn','No signals found.');return;}

  rawSignals.sort((a,b)=>a.timestamp-b.timestamp);
  const startMs=startDateStr?new Date(startDateStr+'T00:00:00Z').getTime():0;
  const signals=rawSignals.filter(m=>m.timestamp>=startMs);
  setProgress(12,`${signals.length} signals loaded — fetching prices…`,'Using Binance 5m candles at signal timestamp');

  const timeline=[];
  let equity=startBalance, equityBC=startBalance;
  let prevAllocs=[], prevPrices={}, prevPricesBC={};
  // Track per-asset returns for Kelly calculation
  const assetReturns = {};   // asset → [return_pct per period when held]

  for (let i=0;i<signals.length;i++) {
    const msg=signals[i];
    const parsed=parseSignal(msg.content);
    const ts=msg.timestamp;
    const date=new Date(ts).toISOString().slice(0,10);
    const timeStr=new Date(ts).toISOString().slice(11,16);
    setProgress(12+Math.floor((i/signals.length)*80),`Signal ${i+1}/${signals.length} · ${date}`,parsed.allocations.map(a=>a.percent+'%'+a.asset).join(' · '));

    const assets=parsed.allocations.map(a=>a.asset);
    const [sigPrices,bcPrices]=await Promise.all([
      fetchAllPrices(assets,ts,false),
      fetchAllPrices(assets,ts,true),
    ]);

    let periodReturn=null;
    if (prevAllocs.length>0) {
      let newEq=0;
      for (const a of prevAllocs) {
        const prev=prevPrices[a.asset], curr=sigPrices[a.asset];
        const portion = equity*(a.percent/100);
        if (a.asset==='USDC'||!prev||!curr){newEq+=portion;}
        else {
          const assetRet=(curr/prev)-1;
          newEq+=portion*(1+assetRet);
          // Record per-asset return for Kelly (weighted by allocation)
          const key=a.asset.split('/')[0];
          if (!assetReturns[key]) assetReturns[key]=[];
          assetReturns[key].push({ret:assetRet, pct:a.percent/100});
        }
      }
      if (!parsed.no_change) newEq-=calcFee(prevAllocs,parsed.allocations,newEq,feeRate);
      periodReturn=(newEq-equity)/equity;
      equity=newEq;

      let newEqBC=0;
      for (const a of prevAllocs) {
        const prev=prevPricesBC[a.asset], curr=bcPrices[a.asset];
        if (a.asset==='USDC'||!prev||!curr){newEqBC+=equityBC*(a.percent/100);}
        else{newEqBC+=equityBC*(a.percent/100)*(curr/prev);}
      }
      if (!parsed.no_change) newEqBC-=calcFee(prevAllocs,parsed.allocations,newEqBC,feeRate);
      equityBC=newEqBC;
    }

    timeline.push({ts,date,time:timeStr,allocations:parsed.allocations,no_change:parsed.no_change,
      equity:+equity.toFixed(2),equity_bc:+equityBC.toFixed(2),period_return:periodReturn,
      prices:sigPrices,prices_bc:bcPrices});

    if (!parsed.no_change&&parsed.allocations.length>0) {
      prevAllocs=parsed.allocations; prevPrices=sigPrices; prevPricesBC=bcPrices;
    }
  }

  setProgress(95,'Computing stats & Kelly…','');

  // Build series
  const eqSeries=[{date:timeline[0]?.date||'',value:startBalance},...timeline.map(t=>({date:t.date,value:t.equity}))];
  const bcSeries=[{date:timeline[0]?.date||'',value:startBalance},...timeline.map(t=>({date:t.date,value:t.equity_bc}))];
  // Live series from cloud snapshots
  const liveSeries=_liveSnaps.map(s=>({date:new Date(s.ts).toISOString().slice(0,10),value:s.v,ts:s.ts}));
  // Merged: backtest up to first live snapshot, then live
  let mergedSeries;
  if (liveSeries.length>0) {
    const liveStart=liveSeries[0].date;
    const btPart=eqSeries.filter(p=>p.date<liveStart);
    mergedSeries=[...btPart,...liveSeries];
  } else {
    mergedSeries=eqSeries;
  }

  const finalEq=timeline[timeline.length-1]?.equity??startBalance;
  const totalReturn=(finalEq-startBalance)/startBalance;
  const t0=new Date(eqSeries[0].date+'T00:00:00Z'), t1=new Date(eqSeries[eqSeries.length-1].date+'T00:00:00Z');
  const years=Math.max((t1-t0)/(365.25*86400000),0.01);
  const cagr=Math.pow(finalEq/startBalance,1/years)-1;
  let peak=startBalance,mdd=0;
  for (const pt of eqSeries){if(pt.value>peak)peak=pt.value;const dd=(peak-pt.value)/peak;if(dd>mdd)mdd=dd;}
  const returnsOnly=timeline.filter(t=>t.period_return!==null);
  const wins=returnsOnly.filter(t=>t.period_return>0).length;
  const winRate=returnsOnly.length?wins/returnsOnly.length:null;

  // Kelly calculation per asset
  const kellyData=computeKelly(assetReturns);

  _result={timeline,eqSeries,bcSeries,liveSeries,mergedSeries,startBalance,
    totalReturn,cagr,mdd,winRate,years,kellyData,assetReturns};

  setProgress(100,'Done!','');
  setTimeout(async ()=>{
    hideOverlay();
    renderMetrics();
    renderChart();
    renderKelly(0.5);
    renderTable();
    document.getElementById('exportBtn').disabled=false;
    setStatus('ok',`${timeline.length} signals · ${eqSeries[0]?.date||'?'} → ${eqSeries[eqSeries.length-1]?.date||'?'}`);
    // Push backtest points to cloud storage (fills in pre-deployment history)
    await pushBacktestToCloud(timeline);
    // Reload cloud snaps to show updated banner
    await loadCloudEquity();
    renderChart();  // re-render with merged view updated
  },250);
}

// ── Kelly Criterion ───────────────────────────────────────────────────────────
/**
 * Full Kelly per asset using the continuous/log-optimal formula.
 * For each asset, we collect all periods where it was held with some allocation,
 * compute the distribution of returns, then calculate:
 *
 *   Full Kelly f* = E[r] / E[r^2]   (Kelly for log-normal returns, single asset)
 *
 * This is equivalent to maximising expected log growth.
 * For discrete outcomes: f* = (p*b - q) / b  where b=avg_win/avg_loss
 * We use both and show the geometric mean formula as primary.
 *
 * Also computes: win rate, avg win, avg loss, Sharpe-like ratio, expected value
 */
function computeKelly(assetReturns) {
  const results = {};
  for (const [asset, records] of Object.entries(assetReturns)) {
    if (records.length < 3) continue;   // need minimum sample
    const rets = records.map(r => r.ret);
    const n    = rets.length;
    const wins = rets.filter(r=>r>0);
    const losses = rets.filter(r=>r<0);
    if (!wins.length || !losses.length) continue;

    const p  = wins.length / n;                             // win probability
    const q  = 1 - p;
    const b  = wins.reduce((s,r)=>s+r,0)/wins.length;      // avg win (fraction)
    const a  = Math.abs(losses.reduce((s,r)=>s+r,0)/losses.length); // avg loss magnitude
    const EV = p*b - q*a;                                   // expected value per period

    // Kelly fraction: f* = (p*b - q*a) / b  (classical)
    const kellyClassic = EV / b;

    // Log-optimal Kelly: f* = μ/σ² where μ=mean(r), σ²=var(r)
    const mu  = rets.reduce((s,r)=>s+r,0)/n;
    const variance = rets.reduce((s,r)=>s+(r-mu)**2,0)/n;
    const kellyLog = variance > 0 ? mu/variance : 0;

    // Use the more conservative of the two (they diverge when distribution is skewed)
    const kellyRaw = Math.min(kellyClassic, kellyLog);
    // Cap at 1.0 (never recommend going all-in based on small sample)
    const kelly = Math.max(0, Math.min(1, kellyRaw));

    // Geometric mean of returns (compound growth per period)
    const geoMean = Math.exp(rets.reduce((s,r)=>s+Math.log(1+r),0)/n) - 1;

    // Sortino-style ratio: mean / downside_std
    const downDev = Math.sqrt(losses.reduce((s,r)=>s+r*r,0)/losses.length);
    const sortino = downDev > 0 ? mu / downDev : null;

    results[asset] = {
      n, p, q, b, a, EV,
      kellyClassic: Math.max(0,kellyClassic),
      kellyLog: Math.max(0,kellyLog),
      kelly,      // conservative kelly (pre-fraction)
      geoMean,
      sortino,
      mu, variance,
    };
  }
  return results;
}

let _kellyFraction = 0.5;
function onFractionChange(val) {
  _kellyFraction=parseFloat(val);
  document.getElementById('kellyFractionVal').textContent=val+'×';
  if (_result?.kellyData) renderKelly(_kellyFraction);
}

const ASSET_COLORS = {
  ETH:'#5b9cf6',BTC:'#f5a623',HYPE:'#c8f563',SOL:'#c084fc',
  PAXG:'#ffd700',USDC:'#6b6860',DEFAULT:'#f0ede8'
};
function assetColor(a){return ASSET_COLORS[a.split('/')[0]]||ASSET_COLORS.DEFAULT;}

function renderKelly(fraction) {
  const container=document.getElementById('kellyCards');
  const noteEl=document.getElementById('kellyNote');
  const kd=_result?.kellyData;
  if (!kd||!Object.keys(kd).length){
    container.innerHTML='<div class="kelly-empty">Not enough signal history to calculate Kelly fractions (need ≥3 periods per asset)</div>';
    noteEl.style.display='none';
    return;
  }

  const cards=Object.entries(kd).map(([asset,k])=>{
    const fk=+(k.kelly*fraction*100).toFixed(1);         // fractional kelly %
    const fkRaw=k.kelly*fraction;
    const color=assetColor(asset);
    const barW=Math.min(100,fk);
    const barColor=fk>80?'#ff5c5c':fk>50?'#f5a623':color;
    const sampleNote=k.n<10?`<span style="color:var(--amber);font-size:10px"> ⚠ n=${k.n}</span>`:'';

    return `<div class="kelly-card">
      <div class="kelly-card-asset">
        <span style="width:8px;height:8px;border-radius:50%;background:${color};display:inline-block;flex-shrink:0"></span>
        ${asset}${sampleNote}
      </div>
      <div class="kelly-card-rows">
        <div class="kelly-row"><span class="kelly-key">Fractional Kelly (${fraction}×)</span><span class="kelly-val" style="color:${barColor};font-size:16px">${fk}%</span></div>
        <div class="kelly-row"><span class="kelly-key">Full Kelly</span><span class="kelly-val">${(k.kelly*100).toFixed(1)}%</span></div>
        <div class="kelly-row"><span class="kelly-key">Win rate</span><span class="kelly-val">${(k.p*100).toFixed(0)}% <span style="font-size:10px;color:var(--muted)">(${Math.round(k.p*k.n)}/${k.n})</span></span></div>
        <div class="kelly-row"><span class="kelly-key">Avg win</span><span class="kelly-val pos">+${(k.b*100).toFixed(2)}%</span></div>
        <div class="kelly-row"><span class="kelly-key">Avg loss</span><span class="kelly-val neg">-${(k.a*100).toFixed(2)}%</span></div>
        <div class="kelly-row"><span class="kelly-key">Expected value/period</span><span class="kelly-val ${k.EV>=0?'pos':'neg'}">${k.EV>=0?'+':''}${(k.EV*100).toFixed(3)}%</span></div>
        <div class="kelly-row"><span class="kelly-key">Geo mean/period</span><span class="kelly-val ${k.geoMean>=0?'pos':'neg'}">${k.geoMean>=0?'+':''}${(k.geoMean*100).toFixed(3)}%</span></div>
        ${k.sortino!==null?`<div class="kelly-row"><span class="kelly-key">Sortino ratio</span><span class="kelly-val">${k.sortino.toFixed(2)}</span></div>`:''}
      </div>
      <div class="kelly-bar-wrap"><div class="kelly-bar" style="width:${barW}%;background:${barColor}"></div></div>
    </div>`;
  }).join('');

  container.innerHTML=cards;

  // Summary note
  const allKelly=Object.entries(kd).map(([a,k])=>({asset:a,fk:k.kelly*fraction}));
  const totalKelly=allKelly.reduce((s,x)=>s+x.fk,0);
  const topAsset=allKelly.sort((a,b)=>b.fk-a.fk)[0];
  noteEl.style.display='block';
  noteEl.innerHTML=`
    <strong>How to use:</strong> Fractional Kelly = ${fraction}× Full Kelly.
    Full Kelly maximises long-run log-growth but risks large drawdowns on small samples.
    Half-Kelly (0.5×) is the standard practitioner choice — it gives ~75% of the maximum growth rate
    with roughly half the variance. Quarter-Kelly (0.25×) for extra caution.
    Total allocation summing all fractional Kellys: <strong>${(totalKelly*100).toFixed(1)}%</strong>
    ${totalKelly>1?'— this exceeds 100%, which means assets are correlated or sample is too small; apply additional scaling.':''}<br>
    <strong>Caveats:</strong> Based on ${_result?.timeline?.length||0} signals using simulated backtest returns.
    Kelly assumes independent, identically distributed returns — RSPS periods are <em>not</em> i.i.d.
    Treat these as directional sizing signals, not precise allocations.
    Always cross-reference with current signal allocations and your own risk tolerance.
  `;
  noteEl.style.color='var(--muted)';
  noteEl.style.fontSize='11px';
  noteEl.style.lineHeight='1.6';
}

// ── Chart ─────────────────────────────────────────────────────────────────────
let chart=null, currentSeries='actual', currentRange='all';
function filterRange(arr,range) {
  if(range==='all')return arr;
  const days={'3m':90,'6m':180,'1y':365}[range];
  const cut=new Date();cut.setDate(cut.getDate()-days);
  const cs=cut.toISOString().slice(0,10);
  return arr.filter(p=>p.date>=cs);
}
function buildLegend(showA,showB,showL,showM) {
  let h='';
  if(showA)h+='<div class="legend-item"><div class="legend-dot" style="background:#c8f563"></div>Signal 5m close</div>';
  if(showB)h+='<div class="legend-item"><div class="legend-dot" style="background:#c084fc"></div>Bar close</div>';
  if(showL)h+='<div class="legend-item"><div class="legend-dot" style="background:#5b9cf6"></div>Live (cloud)</div>';
  if(showM)h+='<div class="legend-item"><div class="legend-dot" style="background:#f5a623"></div>Merged</div>';
  document.getElementById('chartLegend').innerHTML=h;
}
function renderChart() {
  const r=_result; if(!r)return;
  const showA=currentSeries==='actual';
  const showB=currentSeries==='barclose';
  const showL=currentSeries==='live';
  const showM=currentSeries==='merged';
  const fa=showA?filterRange(r.eqSeries,currentRange):[];
  const fb=showB?filterRange(r.bcSeries,currentRange):[];
  const fl=showL?filterRange(r.liveSeries,currentRange):[];
  const fm=showM?filterRange(r.mergedSeries,currentRange):[];
  buildLegend(showA&&fa.length>1,showB&&fb.length>1,showL&&fl.length>1,showM&&fm.length>1);
  const noH=document.getElementById('noHistory'),wrap=document.getElementById('chartWrap');
  const activeArr=[fa,fb,fl,fm].find(a=>a.length>=2);
  if(!activeArr){noH.style.display='block';wrap.style.display='none';return;}
  noH.style.display='none';wrap.style.display='block';
  const allDates=[...new Set([...fa,...fb,...fl,...fm].map(p=>p.date))].sort();
  const labels=allDates.map(d=>{const dt=new Date(d+'T00:00:00Z');return dt.toLocaleDateString('en-GB',{day:'numeric',month:'short',year:allDates.length>300?'2-digit':undefined});});
  const toMap=a=>Object.fromEntries(a.map(p=>[p.date,p.value]));
  const aMap=toMap(fa),bMap=toMap(fb),lMap=toMap(fl),mMap=toMap(fm);
  const datasets=[];
  const mkDs=(data,label,color,dashed,fill)=>{
    const up=data.filter(v=>v!==null);
    const isUp=up.length<2||up[up.length-1]>=up[0];
    const c=color==='auto'?(isUp?'#c8f563':'#ff5c5c'):color;
    return{label,data,borderColor:c,backgroundColor:c.replace(')',',0.05)').replace('rgb','rgba'),
      borderWidth:1.5,borderDash:dashed?[4,3]:undefined,
      pointRadius:allDates.length>80?0:3,pointHoverRadius:5,fill,tension:.35,spanGaps:true};
  };
  if(showA&&fa.length>=2)datasets.push(mkDs(allDates.map(d=>aMap[d]??null),'Signal px','auto',false,true));
  if(showB&&fb.length>=2)datasets.push(mkDs(allDates.map(d=>bMap[d]??null),'Bar close','#c084fc',true,true));
  if(showL&&fl.length>=2)datasets.push(mkDs(allDates.map(d=>lMap[d]??null),'Live','#5b9cf6',false,true));
  if(showM&&fm.length>=2)datasets.push(mkDs(allDates.map(d=>mMap[d]??null),'Merged','#f5a623',false,true));
  if(chart){chart.destroy();chart=null;}
  chart=new Chart(document.getElementById('equityChart'),{
    type:'line',data:{labels,datasets},
    options:{responsive:true,maintainAspectRatio:false,interaction:{mode:'index',intersect:false},
      plugins:{legend:{display:false},tooltip:{backgroundColor:'#1a1a1a',borderColor:'rgba(255,255,255,.1)',borderWidth:1,
        titleColor:'#555',bodyColor:'#f0ede8',titleFont:{family:'DM Mono',size:11},bodyFont:{family:'DM Mono',size:12},
        callbacks:{label:ctx=>` ${ctx.dataset.label}:  `+fmtDollar(ctx.parsed.y)}}},
      scales:{
        x:{grid:{color:'rgba(255,255,255,.04)'},ticks:{color:'#555',font:{family:'DM Mono',size:11},maxTicksLimit:8},border:{display:false}},
        y:{position:'right',grid:{color:'rgba(255,255,255,.04)'},ticks:{color:'#555',font:{family:'DM Mono',size:11},callback:v=>'$'+v.toLocaleString()},border:{display:false}}
      }}
  });
}
function setSeries(s,el){currentSeries=s;document.querySelectorAll('#seriesTabs .ctrl-btn').forEach(b=>b.classList.remove('active'));el.classList.add('active');renderChart();}
function setRange(r,el){currentRange=r;document.querySelectorAll('#rangeTabs .ctrl-btn').forEach(b=>b.classList.remove('active'));el.classList.add('active');renderChart();}

// ── Metrics ───────────────────────────────────────────────────────────────────
function fmtDollar(v){return'$'+parseFloat(v).toLocaleString('en-US',{minimumFractionDigits:2,maximumFractionDigits:2});}
function fmtPct(v,d=2){return(v>=0?'+':'')+(v*100).toFixed(d)+'%';}
function renderMetrics() {
  const r=_result;if(!r)return;
  const set=(id,txt,cls)=>{const el=document.getElementById(id);el.textContent=txt;if(cls)el.className='metric-value '+cls;};
  set('mTR',fmtPct(r.totalReturn),r.totalReturn>=0?'pos':'neg');
  document.getElementById('mTRsub').textContent=fmtDollar(r.eqSeries[r.eqSeries.length-1].value)+' final';
  set('mCAGR',fmtPct(r.cagr),r.cagr>=0?'pos':'neg');
  document.getElementById('mCAGRsub').textContent=r.years.toFixed(1)+'yr period';
  set('mMDD','-'+(r.mdd*100).toFixed(1)+'%','neg');
  set('mWR',r.winRate!==null?(r.winRate*100).toFixed(0)+'%':'N/A',r.winRate>=.5?'pos':'neg');
  const retN=r.timeline.filter(t=>t.period_return!==null);
  document.getElementById('mWRsub').textContent=`${retN.filter(t=>t.period_return>0).length} / ${retN.length} periods`;
  set('mSig',r.timeline.length,'metric-value');
  document.getElementById('mSigsub').textContent=r.timeline.filter(t=>Object.keys(t.prices).length>0).length+' with price data';
}

// ── Table ─────────────────────────────────────────────────────────────────────
const PCLS={'ETH':'pill-eth','BTC':'pill-btc','HYPE':'pill-hype','SOL':'pill-sol','PAXG':'pill-paxg','PAXG/XAUT':'pill-paxg','USDC':'pill-usdc'};
function pillCls(a){return PCLS[a.split('/')[0]]||'pill-other';}
function renderTable() {
  const r=_result;if(!r||!r.timeline.length)return;
  document.getElementById('tableCount').textContent=r.timeline.length+' signals';
  const rows=[...r.timeline].reverse().map(t=>{
    const pills=t.allocations.map(a=>`<span class="pill ${pillCls(a.asset)}">${a.percent}% ${a.asset}</span>`).join('');
    const pr=t.period_return!==null?`<span class="badge ${t.period_return>0.001?'badge-pos':t.period_return<-0.001?'badge-neg':'badge-flat'}">${fmtPct(t.period_return)}</span>`:'<span style="color:var(--muted2)">—</span>';
    const ncBadge=t.no_change?'<span class="badge badge-flat" style="margin-left:4px;font-size:10px">no chg</span>':'';
    const pxStr=Object.entries(t.prices).filter(([k])=>k!=='USDC').map(([k,v])=>`<span style="color:var(--muted);font-size:11px">${k.split('/')[0]}:$${v>=1000?v.toFixed(0):v>=1?v.toFixed(2):v.toFixed(4)}</span>`).join('  ');
    return`<tr>
      <td><span style="font-family:var(--font-display);font-weight:600">${t.date}</span> <span style="color:var(--muted);font-size:11px">${t.time}z</span>${ncBadge}</td>
      <td class="hm"><div class="alloc-pills">${pills}</div></td>
      <td class="hm" style="text-align:right">${pxStr}</td>
      <td>${pr}</td>
      <td><span style="font-family:var(--font-display);font-weight:600">${fmtDollar(t.equity)}</span></td>
    </tr>`;
  }).join('');
  document.getElementById('tableBody').innerHTML=`
    <table class="sig-table"><thead><tr>
      <th>Date / Time (UTC)</th><th class="hm" style="text-align:right">Allocations</th>
      <th class="hm" style="text-align:right">Prices at Signal</th><th>Period Return</th><th>Portfolio Value</th>
    </tr></thead><tbody>${rows}</tbody></table>`;
}

// ── CSV export ────────────────────────────────────────────────────────────────
function exportCSV() {
  if (!_result?.timeline.length){alert('No data. Run backtest first.');return;}
  const {timeline}=_result;
  const hdr=['date','time_utc','no_change','allocations','signal_prices_usd','period_return_pct','portfolio_value_usd','barclose_portfolio_usd'];
  const rows=[hdr.join(',')];
  for (const t of timeline) {
    const allocs=t.allocations.map(a=>`${a.percent}%${a.asset}`).join('|');
    const px=Object.entries(t.prices).map(([k,v])=>`${k}:${v.toFixed(4)}`).join('|');
    const pr=t.period_return!==null?(t.period_return*100).toFixed(4):'';
    rows.push([t.date,t.time+':00',t.no_change?'1':'0',`"${allocs}"`,`"${px}"`,pr,t.equity.toFixed(2),t.equity_bc.toFixed(2)].join(','));
  }
  const blob=new Blob([rows.join('\n')],{type:'text/csv'});
  const url=URL.createObjectURL(blob);
  const a=document.createElement('a');a.href=url;a.download='rsps_backtest_'+new Date().toISOString().slice(0,10)+'.csv';a.click();URL.revokeObjectURL(url);
}

// ── TRW direct fetch fallback ─────────────────────────────────────────────────
async function fetchTRWSignals(token) {
  const CHANNEL='01H83QAX979K9R7QTMH74ATR8C', ADAM='01GHHHWZE7Q77AKGWZDGC5PDCN';
  const sigs=[];let beforeId=null,page=0;
  while(page<40){
    const body={channel:CHANNEL,limit:20,sort:'Latest'};if(beforeId)body.before=beforeId;
    const resp=await fetch('https://eden.therealworld.ag/messages/query',{method:'POST',headers:{'x-session-token':token,'Content-Type':'application/json','Origin':'https://app.jointherealworld.com'},body:JSON.stringify(body)});
    if(resp.status===401)throw new Error('TOKEN_EXPIRED');if(!resp.ok)throw new Error('TRW '+resp.status);
    const data=await resp.json();const msgs=data.messages||[];if(!msgs.length)break;
    for(const m of msgs){if(m.author===ADAM&&m.content?.includes('Portfolio Signal Update'))sigs.push(m);}
    beforeId=msgs[msgs.length-1]._id;page++;
    setProgress(Math.min(10,page),`Fetching page ${page}…`,'');
    if(msgs.length<20)break;
  }
  return sigs;
}

// ── UI helpers ────────────────────────────────────────────────────────────────
function showOverlay(v){document.getElementById('loadingOverlay').classList.toggle('hidden',!v);}
function hideOverlay(){showOverlay(false);}
function setProgress(pct,title,sub){
  document.getElementById('progressFill').style.width=pct+'%';
  if(title)document.getElementById('loadingTitle').textContent=title;
  if(sub!==undefined)document.getElementById('loadingSub').textContent=sub;
}
function setStatus(type,msg){
  const el=document.getElementById('statusMsg');el.textContent=msg;
  el.className=type==='ok'?'status-ok':type==='err'?'status-err':type==='warn'?'status-warn':'';
}
function promptToken(){
  const existing=localStorage.getItem('trw_token')||'';
  const token=prompt('Enter your TRW session token.\n(DevTools → Network → x-session-token header)\nStored in localStorage only.',existing);
  if(!token){setStatus('warn','No token.');return;}
  localStorage.setItem('trw_token',token);runBacktest();
}

// Footer clock
setInterval(()=>{document.getElementById('footerTime').textContent=new Date().toLocaleString('en-GB',{timeZone:'UTC'})+' UTC';},1000);

// ── Init ──────────────────────────────────────────────────────────────────────
window._auth=new URLSearchParams(window.location.search).get('auth')||'';
if(window._auth){const dt=document.getElementById('dashTab');if(dt)dt.href='?auth='+encodeURIComponent(window._auth);}
loadCloudEquity();   // load live snapshots on page open (shows banner immediately)
</script>
</body>
</html>"""
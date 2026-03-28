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
    import requests as req
    prices: dict[str, float] = {}
    for asset in assets:
        ticker = ASSET_TO_TICKER.get(asset, asset)
        if ticker == "USDC":
            continue
        try:
            resp = req.post(
                "https://api.hyperliquid.xyz/info",
                json={"type": "candleSnapshot", "req": {
                    "coin": ticker, "interval": "1h",
                    "startTime": int((time.time() - 7200) * 1000),
                    "endTime":   int(time.time() * 1000),
                }},
                timeout=10,
            )
            candles = resp.json()
            if candles:
                last_closed = candles[-2] if len(candles) >= 2 else candles[-1]
                prices[asset] = float(last_closed["c"])
        except Exception as e:
            print(f"Bar close price fetch failed for {asset}: {e}")
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

    # Spot balances — counts toward total and tracked as positions
    spot_total_usd = 0.0
    try:
        spot_state = info.spot_user_state(address)
        all_mids   = info.all_mids()
        for bal in spot_state.get("balances", []):
            coin_raw = bal["coin"].upper()
            total    = float(bal.get("total", 0))
            if total <= 0:
                continue
            if coin_raw == "USDC":
                spot_total_usd += total   # idle cash, no position to track
                continue
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

        delta_size = target_size - current_size
        delta_usd  = abs(delta_size) * price
        if delta_usd < MIN_TRADE_USD:
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
        })

    trades.sort(key=lambda t: (0 if t["side"] == "sell" else 1, -t["value_usd"]))
    return trades


def execute_trades(info, exchange, trades: list[dict]) -> list[dict]:
    results: list[dict] = []

    # Fetch size decimals for both spot and perp
    spot_sz_map:  dict[str, int] = {}
    perp_sz_map:  dict[str, int] = {}
    try:
        for pair in info.spot_meta().get("universe", []):
            spot_sz_map[pair["name"]] = pair.get("szDecimals", 2)
    except Exception:
        pass
    try:
        for a in info.meta()["universe"]:
            perp_sz_map[a["name"]] = a["szDecimals"]
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

        if mode == "perp" and ticker in leverage_failed:
            results.append({**trade, "status": "skipped",
                             "reason": "leverage set failed"})
            continue

        sz_dec = spot_sz_map.get(ticker) or perp_sz_map.get(ticker) or 2
        size   = float(
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
                results.append({**trade, "status": "failed",
                                 "error": str(result)})
        except Exception as e:
            results.append({**trade, "status": "exception", "error": str(e)})
        time.sleep(0.5)

    return results


# ── State ─────────────────────────────────────────────────────────────────────

signal_state = modal.Dict.from_name("signal-bot-state", create_if_missing=True)


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
def web(action: str = "", token: str = "", auth: str = ""):
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
  .header{display:flex;align-items:center;justify-content:space-between;padding:16px 20px;border-bottom:1px solid var(--border);position:sticky;top:0;background:var(--bg);z-index:10;gap:10px}
  .header-left{display:flex;align-items:center;gap:12px;min-width:0}
  .logo{font-family:var(--font-display);font-size:15px;font-weight:700;letter-spacing:-0.02em;white-space:nowrap}
  .logo span{color:var(--accent)}
  .pulse-dot{width:7px;height:7px;border-radius:50%;background:var(--accent);flex-shrink:0;animation:pulse 2s ease-in-out infinite}
  @keyframes pulse{0%,100%{opacity:1;transform:scale(1)}50%{opacity:.4;transform:scale(.8)}}
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
  @media(max-width:600px){
    .header{padding:12px 14px}
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
  @media(max-width:380px){.metrics{grid-template-columns:1fr}.header-badges .badge:nth-child(3){display:none}}
  ::-webkit-scrollbar{width:4px;height:4px}
  ::-webkit-scrollbar-thumb{background:var(--border2);border-radius:2px}
</style>
</head>
<body>
<div class="header">
  <div class="header-left">
    <div class="pulse-dot"></div>
    <div class="logo">signal<span>bot</span></div>
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
      <div class="panel-header"><div class="panel-title">Positions</div></div>
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
function init(d){
  const{account,positions,signal,pending,lastActedId,trwOk,hlOk,isAuto,approvalToken,barCloseEquity}=d;
  document.getElementById('badges').innerHTML=`<span class="badge ${trwOk?'badge-ok':'badge-err'}">TRW ${trwOk?'OK':'ERR'}</span><span class="badge ${hlOk?'badge-ok':'badge-err'}">HL ${hlOk?'OK':'ERR'}</span><span class="badge ${isAuto?'badge-auto':'badge-manual'}" title="${isAuto?'Autonomous 00:00–05:00 UK':'Approval required 05:00–00:00 UK'}">${isAuto?'Auto 00–05':'Approval'}</span>`;
  const tp=positions.reduce((s,p)=>s+p.pnl,0);
  document.getElementById('accountValue').textContent=fmt$(account.value);
  document.getElementById('totalPnl').textContent=(tp>=0?'+':'')+fmt$(tp);
  document.getElementById('totalPnl').className='metric-value '+(tp>=0?'pos':'neg');
  document.getElementById('posCount').textContent=positions.length;
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
  const dc=['#c8f563','#5b9cf6','#f5a623','#ff5c5c','#c084fc'];
  const pb=document.getElementById('positionsBody');
  if(!positions.length){pb.innerHTML='<div class="no-pos">No open positions</div>'}
  else{pb.innerHTML=`<table class="pos-table"><thead><tr><th>Asset</th><th class="hide-mobile">Mode</th><th class="hide-mobile">Size</th><th class="hide-mobile">Entry</th><th>Value</th><th>PnL</th></tr></thead><tbody>${positions.map((p,i)=>{const modeTag=p.mode==='spot'?'<span class="mode-spot">SPOT</span>':'<span class="mode-perp">PERP</span>';return`<tr><td><span class="coin-badge"><span class="coin-dot" style="background:${dc[i%dc.length]}"></span>${p.coin}</span></td><td class="hide-mobile">${modeTag}</td><td class="hide-mobile">${parseFloat(p.size).toFixed(4)}</td><td class="hide-mobile">${fmt$(p.entryPx)}</td><td>${fmt$(p.value)}</td><td class="${p.pnl>=0?'pos':'neg'}">${p.pnl>=0?'+':''}${fmt$(p.pnl)}</td></tr>`}).join('')}</tbody></table>`}
  const al=document.getElementById('allocList');const st=document.getElementById('signalTime');
  if(signal&&signal.allocations&&signal.allocations.length){st.textContent=signal.time||'';al.innerHTML=signal.allocations.map(a=>`<div class="alloc-row"><div class="alloc-pct">${a.percent}%</div><div class="alloc-bar-wrap"><div class="alloc-bar" style="width:${a.percent}%"></div></div><div class="alloc-asset">${a.asset}</div><div class="alloc-type">${a.type}</div></div>`).join('')}
  else{al.innerHTML='<div class="no-pos">No signal found</div>'}
  if(pending&&approvalToken){const bn=document.getElementById('pendingBanner');bn.style.display='block';document.getElementById('pendingAllocs').innerHTML=pending.map(a=>`<span><strong>${a.percent}%</strong> ${a.asset}</span>`).join('');document.getElementById('approveBtn').href='?action=approve&token='+approvalToken;document.getElementById('approveBtn').onclick=()=>confirm('Execute rebalance now?');document.getElementById('dismissBtn').href='?action=dismiss&token='+approvalToken}
  const forceBtn=document.getElementById('forceBtn');
  if(forceBtn&&approvalToken)forceBtn.href='?action=force&token='+approvalToken;

  const _auth=new URLSearchParams(window.location.search).get('auth')||'';
  if(_auth){
    document.querySelectorAll('a[href^="?"]').forEach(a=>{
      if(!a.href.includes('auth='))a.href+='&auth='+encodeURIComponent(_auth);
    });
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
            "value":   pos.get("value_usd", 0),
            "pnl":     pos.get("unrealized_pnl", 0),
            "mode":    pos.get("mode", "perp"),   # "spot" or "perp"
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
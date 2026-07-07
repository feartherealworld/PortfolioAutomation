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
from signalbot.trw import *
from signalbot.hyperliquid import *
from signalbot.strategies import *
from signalbot.safety import *

__all__ = [
    'is_autonomous_hours',
    'should_poll_now',
    'do_rebalance',
]



def is_autonomous_hours() -> bool:
    """
    Autonomous window: 00:00–05:00 UK local time (Europe/London).
    Handles BST/GMT automatically via zoneinfo.
    In winter (GMT): autonomous = 00:00–05:00 UTC
    In summer (BST = UTC+1): autonomous = 23:00–04:00 UTC previous night
    Signals almost always drop at/just after UK midnight, so this window
    captures the signal regardless of DST.
    """
    from zoneinfo import ZoneInfo
    now = datetime.now(ZoneInfo("Europe/London"))
    return 0 <= now.hour < 5


def should_poll_now() -> bool:
    """
    Gate how often we actually do work inside the 2-min cron.

    Schedule (UK time):
      00:00–00:30  every 2 min  — signal usually drops here, tight window
      00:30–05:00  every 10 min — autonomous execution window, relaxed
      05:00–24:00  every 2 h   — daytime: signals almost never drop, just
                                  keep equity snapshots + catch edge cases

    Total real polls/day ≈ 15 (00–00:30) + 27 (00:30–05:00) + 10 (day) = ~52
    vs 1440 invocations/day before — 97% reduction in actual work.
    Container cold-starts still happen every 2 min but exit in <5ms when skipped.
    """
    from zoneinfo import ZoneInfo
    now = datetime.now(ZoneInfo("Europe/London"))
    h, m = now.hour, now.minute
    if h == 0 and m < 30:
        return True                # every 2 min (cron rate) — tightest window
    if (h == 0 and m >= 30) or (1 <= h < 5):
        return m % 10 == 0         # every 10 min during autonomous hours
    return m == 0 and h % 2 == 0  # every 2 hours during the day


def do_rebalance(parsed: dict, msg_id: str,
                 bar_close_prices: dict | None = None) -> dict:
    """Execute a rebalance and send a detailed Slack report.

    bar_close_prices: pre-fetched {asset → 00:00 UTC daily open price}.
    Passed directly from check_signal to avoid Modal Dict read-after-write
    race conditions.
    """
    # Kill switch — hard gate before any HL interaction. Covers every caller
    # (autonomous check_signal, manual approve, force rebalance).
    if is_trading_halted():
        reason = get_halt_state().get("reason") or "kill switch engaged"
        send_slack(f"🛑 *Trading halted* — rebalance refused.\nReason: {reason}\n"
                   f"Resume from the dashboard to re-enable execution.", mention=True)
        return {"status": "halted", "reason": reason}

    info, exchange = get_hl_clients()
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

    # Load persisted leverage settings
    leverage_map: dict[str, int] = {}
    try:
        leverage_map = json.loads(signal_state.get("leverage_settings", "{}"))
    except Exception:
        pass

    trades = compute_rebalance(parsed["allocations"], account_value,
                               state["positions"], prices, spot_index,
                               leverage_map=leverage_map)

    if not trades:
        send_slack("✅ *Signal processed* — positions already match, no trades needed.")
        signal_state["last_signal_id"] = msg_id
        return {"status": "already_aligned", "signal_id": msg_id}

    # Use bar_close_prices passed directly from check_signal (avoids Modal Dict race).
    # Fall back to signal_state for manual approve/force-rebalance paths.
    if bar_close_prices is None:
        bar_close_prices = {}
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
                line += f"\n   00:00 open ${bar_px:,.2f}  ·  dev {dev_sign}{dev:.3f}%  ·  Δ {slip_str}"
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

    # ── Store bar-close equity snapshot at execution time ─────────────────────
    # Bar-close equity = what the account would be worth if every filled trade
    # had been executed at the 00:00 UTC daily open instead of the intraday price.
    # Computed as: actual post-trade equity ± Σ(daily_open - exec_price) * fill_size
    # Stored once per rebalance so the dashboard never needs to recompute it.
    try:
        post_state    = get_account_state(info)
        actual_equity = post_state["account_value"]
        record_equity_snapshot(actual_equity)

        bc_adjustment = 0.0
        bc_has_prices = False
        for r in results:
            if r["status"] != "filled":
                continue
            asset  = r.get("asset", "")
            bar_px = bar_close_prices.get(asset)
            if not bar_px or bar_px <= 0:
                continue
            exec_px   = r["avg_price"]
            fill_size = r["filled_size"]
            side      = r.get("side", "buy")
            # Hypothetical daily-open portfolio: buying at the (higher/lower)
            # daily open changes cash by (exec - bar) * size relative to the
            # actual fill; selling by (bar - exec) * size. A buy filled BELOW
            # the daily open therefore means bc_equity < actual (we beat the
            # benchmark). Sign was inverted before 2026-07-07 (display-only).
            if side == "buy":
                bc_adjustment += (exec_px - bar_px) * fill_size
            else:
                bc_adjustment += (bar_px - exec_px) * fill_size
            bc_has_prices = True

        if bc_has_prices and actual_equity > 0:
            bc_equity = round(actual_equity + bc_adjustment, 2)
            try:
                bc_snaps: list[dict] = json.loads(
                    signal_state.get("bc_snapshots", "[]"))
            except Exception:
                bc_snaps = []
            now_ms  = int(time.time() * 1000)
            if bc_snaps and bc_snaps[-1]["ts"] // 3_600_000 == now_ms // 3_600_000:
                bc_snaps[-1] = {"ts": now_ms, "v": bc_equity}
            else:
                bc_snaps.append({"ts": now_ms, "v": bc_equity})
            bc_snaps = bc_snaps[-3650:]
            signal_state["bc_snapshots"] = json.dumps(bc_snaps)
            print(f"[bc_equity] actual={actual_equity:.2f}  "
                  f"daily_open={bc_equity:.2f}  adj={bc_adjustment:+.2f}")
    except Exception as e:
        print(f"[bc_equity] snapshot failed: {e}")

    return {
        "status":       "rebalanced",
        "signal_id":    msg_id,
        "filled":       len(filled),
        "failed":       len(failed),
        "slippage_usd": round(total_slippage_usd, 4),
    }

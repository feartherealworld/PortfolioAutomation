import os
import json
import re
import time
import hmac
import secrets
from datetime import datetime, timezone
from decimal import Decimal, ROUND_DOWN
import copy
from signalbot.config import *

__all__ = [
    'record_equity_snapshot',
    'get_strategies',
    'get_cash_flows',
    'record_portfolio_snapshot',
    'merge_equity_into_portfolio',
    'detect_hl_cash_flows',
    'sync_cash_flows',
    '_xnpv',
    '_xirr',
    '_market_index',
    'compute_portfolio_metrics',
    'get_signal_strategies',
    'get_signal_runtime',
    'new_runtime_entry',
    '_mark_equity',
    'apply_signal',
    'mark_runtime_point',
]



def record_equity_snapshot(account_value: float) -> None:
    """
    Append a timestamped equity snapshot to cloud storage.
    Deduplicates to one point per hour. Only writes to Modal Dict when the
    value has actually changed by more than $0.01 (avoids write on every poll).
    Cap at 3650 points (~10 years of daily data).
    """
    if account_value <= 0:
        return
    try:
        raw = signal_state.get("equity_snapshots", "[]")
        snaps: list[dict] = json.loads(raw)
    except Exception:
        snaps = []

    now_ms  = int(time.time() * 1000)

    # Upsert: update current hour's entry only if value changed meaningfully
    if snaps and snaps[-1]["ts"] // 3_600_000 == now_ms // 3_600_000:
        if abs(snaps[-1]["v"] - account_value) < 0.01:
            return   # same hour, negligible change — skip write
        snaps[-1] = {"ts": now_ms, "v": round(account_value, 2)}
    else:
        snaps.append({"ts": now_ms, "v": round(account_value, 2)})

    snaps = snaps[-3650:]
    try:
        signal_state["equity_snapshots"] = json.dumps(snaps)
    except Exception as e:
        print(f"[equity_snapshot] write failed: {e}")


def get_strategies() -> list[dict]:
    try:
        raw = signal_state.get("strategies", "")
        if raw:
            strats = json.loads(raw)
            if strats:
                return strats
    except Exception:
        pass
    try:
        signal_state["strategies"] = json.dumps(DEFAULT_STRATEGIES)
    except Exception:
        pass
    return list(DEFAULT_STRATEGIES)


def get_cash_flows() -> list[dict]:
    try:
        flows = json.loads(signal_state.get("cash_flows", "[]"))
        flows.sort(key=lambda f: f.get("ts", 0))
        return flows
    except Exception:
        return []


def record_portfolio_snapshot(total_value: float) -> None:
    """Snapshot total portfolio value. Hourly dedup like equity snapshot."""
    if total_value <= 0:
        return
    try:
        snaps: list[dict] = json.loads(signal_state.get("portfolio_snapshots", "[]"))
    except Exception:
        snaps = []
    now_ms = int(time.time() * 1000)
    if snaps and snaps[-1]["ts"] // 3_600_000 == now_ms // 3_600_000:
        if abs(snaps[-1]["v"] - total_value) < 0.01:
            return
        snaps[-1] = {"ts": now_ms, "v": round(total_value, 2)}
    else:
        snaps.append({"ts": now_ms, "v": round(total_value, 2)})
    snaps = snaps[-3650:]
    try:
        signal_state["portfolio_snapshots"] = json.dumps(snaps)
    except Exception as e:
        print(f"[portfolio_snapshot] write failed: {e}")


def merge_equity_into_portfolio(equity: list[dict], portfolio: list[dict]) -> list[dict]:
    """
    Backfill the portfolio snapshot series from the RSPS equity series.
    Both are [{ts, v}] with hourly dedup. Equity is used only to fill hours the
    portfolio series doesn't already have — existing portfolio snapshots are
    authoritative and never overwritten (forward-safe once portfolio != RSPS).
    Returns merged, sorted, capped to 3650 points.
    """
    by_hour: dict[int, dict] = {}
    for s in equity:
        try:
            by_hour[s["ts"] // 3_600_000] = {"ts": s["ts"], "v": s["v"]}
        except (KeyError, TypeError):
            continue
    for s in portfolio:                       # portfolio overrides equity for shared hours
        try:
            by_hour[s["ts"] // 3_600_000] = {"ts": s["ts"], "v": s["v"]}
        except (KeyError, TypeError):
            continue
    merged = sorted(by_hour.values(), key=lambda x: x["ts"])
    return merged[-3650:]


def detect_hl_cash_flows(address: str) -> list[dict]:
    """
    Auto-detect deposits/withdrawals from HL ledger (userNonFundingLedgerUpdates).
    Returns NEW flows not already recorded (matched by hash).
    """
    import requests as _req
    new_flows: list[dict] = []
    try:
        resp = _req.post(
            "https://api.hyperliquid.xyz/info",
            json={"type": "userNonFundingLedgerUpdates", "user": address},
            timeout=15,
        )
        if not resp.ok:
            return []
        updates = resp.json()
    except Exception as e:
        print(f"[cash_flow] ledger fetch failed: {e}")
        return []

    try:
        existing = json.loads(signal_state.get("cash_flows", "[]"))
    except Exception:
        existing = []
    seen = {f.get("hash") for f in existing if f.get("hash")}

    for u in updates:
        delta = u.get("delta", {})
        kind  = delta.get("type", "")
        ts    = u.get("time", 0)
        h     = u.get("hash", "")
        if h and h in seen:
            continue
        if kind == "deposit":
            amount = float(delta.get("usdc", 0))
        elif kind == "withdraw":
            amount = -float(delta.get("usdc", 0))
        else:
            continue
        if amount == 0:
            continue
        new_flows.append({
            "ts": ts, "amount": round(amount, 2),
            "note": "deposit" if amount > 0 else "withdrawal",
            "source": "auto", "hash": h,
        })
    return new_flows


def sync_cash_flows(address: str) -> int:
    """Detect and persist new HL deposits/withdrawals. Returns count added."""
    new_flows = detect_hl_cash_flows(address)
    if not new_flows:
        return 0
    try:
        existing = json.loads(signal_state.get("cash_flows", "[]"))
    except Exception:
        existing = []
    existing.extend(new_flows)
    existing.sort(key=lambda f: f.get("ts", 0))
    try:
        signal_state["cash_flows"] = json.dumps(existing)
    except Exception as e:
        print(f"[cash_flow] write failed: {e}")
        return 0
    return len(new_flows)


def _xnpv(rate: float, cashflows: list[tuple[float, float]]) -> float:
    """Net present value of dated cashflows. `cashflows` = [(years_from_t0, amount)]."""
    if rate <= -1.0:
        rate = -0.999999
    return sum(amt / (1.0 + rate) ** t for t, amt in cashflows)


def _xirr(cashflows: list[tuple[float, float]]) -> float | None:
    """
    Date-aware money-weighted return. `cashflows` = [(years_from_t0, amount)],
    investor-perspective sign convention (outflow negative, inflow positive).
    Solved by bracketed bisection on NPV — robust, never diverges. Returns the
    annualized rate, or None if there aren't both signs / no sign change found.
    """
    amts = [a for _, a in cashflows]
    if not amts or min(amts) >= 0 or max(amts) <= 0:
        return None
    lo, hi = -0.9999, 10.0
    f_lo, f_hi = _xnpv(lo, cashflows), _xnpv(hi, cashflows)
    tries = 0
    while f_lo * f_hi > 0 and hi < 1e7 and tries < 80:
        hi *= 2.0
        f_hi = _xnpv(hi, cashflows)
        tries += 1
    if f_lo * f_hi > 0:
        return None
    for _ in range(200):
        mid = (lo + hi) / 2.0
        f_mid = _xnpv(mid, cashflows)
        if abs(f_mid) < 1e-7:
            return mid
        if f_lo * f_mid < 0:
            hi, f_hi = mid, f_mid
        else:
            lo, f_lo = mid, f_mid
    return (lo + hi) / 2.0


def _market_index(snapshots: list[dict], flows: list[dict]) -> tuple[list[dict], list[float]] | None:
    """
    Chain-linked market-return index over the snapshot series using Modified
    Dietz per inter-snapshot interval (time-weights external flows *within* the
    period, and counts negative periods). Returns (clean_snaps, cum_idx) where
    cum_idx[i] is the cumulative growth of $1 of exposure up to clean_snaps[i],
    or None if there is too little data.
    """
    snaps = [s for s in snapshots if s.get("v", 0) > 0]
    if len(snaps) < 2:
        return None
    cum_idx = [1.0]
    chained = 1.0
    for i in range(1, len(snaps)):
        prev_ts, prev_v = snaps[i - 1]["ts"], snaps[i - 1]["v"]
        cur_ts,  cur_v  = snaps[i]["ts"],     snaps[i]["v"]
        period = cur_ts - prev_ts
        fl = [(f["ts"], f["amount"]) for f in flows if prev_ts < f["ts"] <= cur_ts]
        net_flow = sum(a for _, a in fl)
        if period > 0 and fl:
            # Modified Dietz: weight each flow by the fraction of the period it
            # was invested (a flow near the end barely participates).
            weighted = sum(a * ((cur_ts - t) / period) for t, a in fl)
        else:
            weighted = net_flow
        denom = prev_v + weighted
        if denom > 0:
            period_return = (cur_v - prev_v - net_flow) / denom
            growth = 1.0 + period_return
            if growth <= 0:                # guard against bad data / total wipe
                growth = 1e-6
        else:
            growth = 1.0
        chained *= growth
        cum_idx.append(chained)
    return snaps, cum_idx


def compute_portfolio_metrics(snapshots: list[dict], flows: list[dict],
                              current_value: float) -> dict:
    """
    True performance metrics accounting for cash flows.
      net_deposited : Σ flows (deposits − withdrawals)
      true_pnl      : current_value − net_deposited
      simple_return : true_pnl / net_deposited
      twr           : chain-linked Modified-Dietz time-weighted return
      xirr          : date-aware money-weighted annualized return (all flows + NAV)
      injections    : per-deposit money-weighted contribution & return, based on
                      the actual market path from that deposit's date to now
    """
    net_deposited = sum(f["amount"] for f in flows)
    true_pnl      = current_value - net_deposited
    simple_return = (true_pnl / net_deposited) if net_deposited > 0 else 0.0
    now_ms        = int(time.time() * 1000)

    # ── Time-weighted return via chain-linked Modified Dietz ──────────────────
    mkt = _market_index(snapshots, flows)
    twr = None
    if mkt is not None:
        _, cum_idx = mkt
        twr = cum_idx[-1] - 1.0

    # ── Per-injection money-weighted contribution ────────────────────────────
    # Each deposit earns the market's growth from its own date to now, taken
    # from the cumulative index. An early deposit that rode a 2× shows a far
    # bigger contribution than a recent one. Falls back to a flat proportional
    # estimate when there isn't enough snapshot history to build the index.
    injections = []
    g_now = mkt[1][-1] if mkt is not None else None
    flat_growth = (current_value / net_deposited) if net_deposited > 0 else 1.0
    for f in flows:
        if f["amount"] <= 0:
            continue
        amt, t = f["amount"], f["ts"]
        if mkt is not None:
            snaps, cum_idx = mkt
            if t <= snaps[0]["ts"]:
                base_idx = cum_idx[0]                      # deposited at/before start
            else:
                base_idx = None
                for k, s in enumerate(snaps):              # first snapshot at/after deposit
                    if s["ts"] >= t:
                        base_idx = cum_idx[k]
                        break
                if base_idx is None:                       # deposited after last snapshot
                    base_idx = g_now
            g = (g_now / base_idx) if base_idx and base_idx > 0 else 1.0
        else:
            g = flat_growth
        days = max((now_ms - t) / 86_400_000.0, 1.0)
        annualized = (g ** (365.0 / days) - 1.0) if g > 0 else None
        injections.append({
            "ts": t, "amount": amt,
            "note": f.get("note", ""),
            "contribution": round(amt * (g - 1.0), 2),
            "return_pct": round(g - 1.0, 4),
            "annualized": (round(annualized, 4) if annualized is not None else None),
            "source": f.get("source", "manual"),
        })

    # ── Headline XIRR across every flow + current NAV ────────────────────────
    xirr = None
    if flows:
        t0  = min(f["ts"] for f in flows)
        cfs = [((f["ts"] - t0) / _MS_PER_YEAR, -f["amount"]) for f in flows]
        cfs.append(((now_ms - t0) / _MS_PER_YEAR, current_value))
        xirr = _xirr(cfs)

    return {
        "current_value": round(current_value, 2),
        "net_deposited": round(net_deposited, 2),
        "true_pnl":      round(true_pnl, 2),
        "simple_return": simple_return,
        "twr":           twr,
        "xirr":          xirr,
        "injections":    injections,
        "flow_count":    len(flows),
    }


def get_signal_strategies() -> list[dict]:
    return [s for s in get_strategies() if s.get("kind") == "signal"]


def get_signal_runtime() -> dict:
    try:
        return json.loads(signal_state.get(SIGNAL_RUNTIME_KEY, "{}"))
    except Exception:
        return {}


def new_runtime_entry(paper_capital: float) -> dict:
    """Fresh paper account: all equity in cash, no open position."""
    return {
        "equity":     round(float(paper_capital), 2),   # realized equity (updated on close)
        "position":   None,                              # {side, qty, entry_px, entry_ts}
        "equity_curve": [],                              # [{ts, v}] marked equity, hourly dedup
        "signal_log": [],                                # recent signals (capped)
        "processed":  [],                                # recent alert ids for dedup (capped)
    }


def _mark_equity(rt: dict, mark_px: float) -> float:
    """Current marked equity = realized equity + unrealized PnL of open position."""
    equity = rt.get("equity", 0.0)
    pos = rt.get("position")
    if not pos or mark_px <= 0:
        return round(equity, 2)
    qty, entry = pos["qty"], pos["entry_px"]
    upnl = qty * (mark_px - entry) if pos["side"] == "long" else qty * (entry - mark_px)
    return round(max(0.0, equity + upnl), 2)   # paper account can't go below zero


def apply_signal(rt: dict, action: str, mark_px: float, leverage: float = 1.0,
                 ts: int | None = None) -> dict:
    """
    Pure paper-account state machine for an all-in long/short/flat strategy.
    Mutates and returns a COPY of `rt`. No Modal access — fully testable.
      long  → close any opposite position, go all-in long  at mark_px
      short → close any opposite position, go all-in short at mark_px
      flat  → close any position
    Realized equity updates only on close; an open position is marked to market
    for display. Leverage multiplies position size (and thus PnL).
    """
    import copy
    rt = copy.deepcopy(rt)
    if ts is None:
        ts = int(time.time() * 1000)
    action = (action or "").lower().strip()
    if action in ("buy", "long"):
        action = "long"
    elif action in ("sell", "short"):
        action = "short"
    elif action in ("flat", "close", "exit"):
        action = "flat"
    else:
        rt.setdefault("signal_log", []).append({"ts": ts, "action": action, "note": "ignored: unknown action"})
        rt["signal_log"] = rt["signal_log"][-50:]
        return rt

    pos = rt.get("position")

    def _close(p):
        """Realize PnL of position p at mark_px into equity."""
        if not p:
            return
        qty, entry = p["qty"], p["entry_px"]
        pnl = qty * (mark_px - entry) if p["side"] == "long" else qty * (entry - mark_px)
        rt["equity"] = round(max(0.0, rt.get("equity", 0.0) + pnl), 2)

    note = ""
    if action == "flat":
        if pos:
            _close(pos)
            rt["position"] = None
            note = "closed to flat"
        else:
            note = "already flat"
    else:  # long or short
        if pos and pos["side"] == action:
            note = f"already {action}"
        else:
            if pos:
                _close(pos)                     # flip: realize the opposite side first
            equity = rt.get("equity", 0.0)
            if mark_px > 0 and equity > 0:
                qty = (equity * max(1.0, leverage)) / mark_px
                rt["position"] = {"side": action, "qty": round(qty, 8),
                                  "entry_px": round(mark_px, 6), "entry_ts": ts}
                note = f"opened {action} @ {mark_px:g}" + (f" {leverage:g}x" if leverage > 1 else "")
            else:
                rt["position"] = None
                note = "skipped: no paper equity"

    rt.setdefault("signal_log", []).append({"ts": ts, "action": action,
                                            "px": round(mark_px, 6), "note": note})
    rt["signal_log"] = rt["signal_log"][-50:]
    return rt


def mark_runtime_point(rt: dict, mark_px: float, ts: int | None = None) -> dict:
    """Append a marked-equity point to the curve (hourly dedup). Mutates a copy."""
    import copy
    rt = copy.deepcopy(rt)
    if ts is None:
        ts = int(time.time() * 1000)
    v = _mark_equity(rt, mark_px)
    curve = rt.setdefault("equity_curve", [])
    if curve and curve[-1]["ts"] // 3_600_000 == ts // 3_600_000:
        curve[-1] = {"ts": ts, "v": v}
    else:
        curve.append({"ts": ts, "v": v})
    rt["equity_curve"] = curve[-3650:]
    return rt

import modal
import asyncio
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
from signalbot.rebalance import *
from signalbot.ui import *
from signalbot.ui2 import *
from signalbot.safety import *
from signalbot.auth import *

__all__ = [
    'daily_equity_snapshot',
    'check_signal',
    'tv_webhook',
    'web',
]



# ── Main cron ─────────────────────────────────────────────────────────────────

@app.function(
    image=image,
    secrets=[modal.Secret.from_name("signal-bot-secrets")],
    schedule=modal.Cron("55 23 * * *"),   # 23:55 UTC daily — end-of-day equity snapshot
    timeout=60,
)
def daily_equity_snapshot():
    """Guaranteed daily equity + portfolio snapshot at end of day (23:55 UTC).
    Also syncs cash flows from HL ledger so deposits/withdrawals are tracked.
    """
    try:
        info, _ = get_hl_clients()
        state   = get_account_state(info)
        av      = state["account_value"]
        record_equity_snapshot(av)
        # Portfolio layer: total value (== RSPS for now) + cash flow sync
        record_portfolio_snapshot(av)
        addr = os.environ["HYPERLIQUID_MASTER_ACCOUNT_ADDRESS"]
        added = sync_cash_flows(addr)
        print(f"[daily_snapshot] equity=${av:.2f}  new_cash_flows={added}")
        return {"status": "ok", "value": av, "new_flows": added}
    except Exception as e:
        print(f"[daily_snapshot] failed: {e}")
        return {"status": "error", "error": str(e)}


@app.function(
    image=image,
    secrets=[modal.Secret.from_name("signal-bot-secrets")],
    schedule=modal.Cron("*/2 * * * *"),
    timeout=120,
)
def check_signal():
    if not should_poll_now():
        return {"status": "skipped"}

    # Only fetch account state when we're actually doing real work
    # (avoids 2 extra HL HTTP calls on every skipped invocation)
    try:
        _info, _ = get_hl_clients()
        _state   = get_account_state(_info)
        record_equity_snapshot(_state["account_value"])
    except Exception as e:
        print(f"[equity_snapshot] skipped: {e}")

    try:
        messages = fetch_recent_messages(limit=5)
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

    # Kill switch — skip auto-execution quietly. Do NOT mark the signal as acted,
    # so the latest signal is picked up automatically once trading is resumed.
    # No Slack here (avoids spam every poll); the dashboard shows the HALTED state.
    if is_trading_halted():
        print(f"[check_signal] trading halted — holding signal {msg_id} (not executed)")
        return {"status": "halted", "signal_id": msg_id}

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

    # Detect all-cash signal (100% USDC / Cash allocation)
    non_cash = [a for a in parsed["allocations"]
                if ASSET_TO_TICKER.get(a["asset"], a["asset"]) not in ("USDC", "")]
    if not non_cash:
        # All cash — close any open positions then hold USDC, no rebalance needed each poll
        info, exchange = get_hl_clients()
        state = get_account_state(info)
        open_positions = {k: v for k, v in state["positions"].items()
                          if abs(v.get("size", 0)) > 0}
        if not open_positions:
            # Already in cash — just mark as acted and stay quiet
            signal_state["last_signal_id"] = msg_id
            return {"status": "already_cash", "signal_id": msg_id}
        # Have open positions — close them once, then stay quiet on future polls
        send_slack(
            f"💵 *Cash signal — closing positions*  ·  {dt.strftime('%d %b %H:%M UTC')}\n{alloc_lines}",
            mention=True,
        )
        return do_rebalance(parsed, msg_id)

    # Fetch daily-open prices (bar close = 00:00 UTC on signal date)
    signal_assets = [
        a["asset"] for a in parsed["allocations"]
        if ASSET_TO_TICKER.get(a["asset"], a["asset"]) not in ("USDC", "")
    ]
    bar_close_px: dict[str, float] = {}
    try:
        bar_close_px = get_daily_open_prices(signal_assets, timestamp)
        # Also persist for the approval/force-rebalance paths
        signal_state["bar_close_prices"] = json.dumps(bar_close_px)
    except Exception as e:
        print(f"Failed to capture daily open prices: {e}")

    if is_autonomous_hours():
        send_slack(
            f"🤖 *New signal — auto-rebalancing*  ·  {dt.strftime('%d %b %H:%M UTC')}\n{alloc_lines}",
            mention=True,
        )
        try:
            # Pass bar_close_px directly — avoids Modal Dict read-after-write race
            return do_rebalance(parsed, msg_id, bar_close_prices=bar_close_px)
        except Exception as e:
            send_slack(f"🚨 *Rebalance error*\n`{e}`", mention=True)
            return {"status": "error", "error": str(e)}
    else:
        approval_token = secrets.token_urlsafe(16)
        pending_with_ts = {**parsed, "_ts": timestamp}   # embed ts for bar-close on approve
        signal_state["pending_signal"] = json.dumps(pending_with_ts)
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


# ── TradingView webhook endpoint ───────────────────────────────────────────────
# Separate POST endpoint (its own Modal URL) that ingests TradingView alert
# webhooks for signal strategies. Isolated from the GET dashboard handler and
# from every real-money trading path. Payload (JSON body):
#   {"token": "<strategy secret>", "action": "long"|"short"|"flat", "id": "<opt>"}
# `id` (optional) makes the alert idempotent — TV can double-fire on a bar.

# FastAPI must be told `request` is the Request object (else it's treated as a
# query param). fastapi isn't installed in the local deploy env — it lives in the
# Modal image — so guard the import; the annotation resolves on the container.
try:
    from fastapi import Request
except ModuleNotFoundError:
    Request = None


@app.function(
    image=image,
    secrets=[modal.Secret.from_name("signal-bot-secrets")],
    timeout=60,
)
@modal.fastapi_endpoint(method="POST")
async def tv_webhook(request: Request):
    from fastapi.responses import JSONResponse

    # Parse body — TV posts the alert message as the body (JSON text).
    try:
        body = await request.json()
    except Exception:
        try:
            raw = (await request.body()).decode("utf-8", "ignore").strip()
            body = json.loads(raw) if raw else {}
        except Exception:
            return JSONResponse({"error": "bad payload"}, status_code=400)
    if not isinstance(body, dict):
        return JSONResponse({"error": "bad payload"}, status_code=400)

    token  = str(body.get("token", "")).strip()
    action = str(body.get("action", "")).strip()
    alert_id = body.get("id") or body.get("alert_id")
    if not token or not action:
        return JSONResponse({"error": "missing token or action"}, status_code=400)

    # Match strategy by secret token (constant-time compare).
    strats = json.loads(await signal_state.get.aio("strategies", "[]"))
    strat  = next((s for s in strats
                   if s.get("kind") == "signal"
                   and hmac.compare_digest(str(s.get("token") or ""), token)), None)
    if strat is None:
        return JSONResponse({"error": "unauthorized"}, status_code=401)

    sid      = strat["id"]
    asset    = strat.get("asset", "BTC")
    leverage = float(strat.get("leverage", 1) or 1)
    mode     = strat.get("mode", "paper")
    paper_capital = float(strat.get("paper_capital", 10000) or 10000)

    # Load runtime, init entry if first signal.
    runtime = json.loads(await signal_state.get.aio(SIGNAL_RUNTIME_KEY, "{}"))
    rt = runtime.get(sid) or new_runtime_entry(paper_capital)

    # Idempotency: skip a repeated alert id.
    if alert_id is not None:
        aid = str(alert_id)
        if aid in rt.get("processed", []):
            return JSONResponse({"ok": True, "dedup": True})
        rt.setdefault("processed", []).append(aid)
        rt["processed"] = rt["processed"][-100:]

    # Current mark for the asset.
    mark = 0.0
    try:
        mark = safe_all_mids(HlInfo("https://api.hyperliquid.xyz")).get(asset, 0.0)
    except Exception as e:
        print(f"[tv_webhook] price fetch failed: {e}")
    if mark <= 0:
        return JSONResponse({"error": f"no price for {asset}"}, status_code=503)

    now_ms = int(time.time() * 1000)
    rt = apply_signal(rt, action, mark, leverage=leverage, ts=now_ms)
    if mode == "live":
        # Phase 2 will route this through the HL execution layer. For now it
        # paper-tracks and flags so signals aren't silently dropped.
        rt["signal_log"][-1]["note"] += " · live exec pending (Phase 2)"
    rt = mark_runtime_point(rt, mark, ts=now_ms)

    runtime[sid] = rt
    await signal_state.__setitem__.aio(SIGNAL_RUNTIME_KEY, json.dumps(runtime))

    return JSONResponse({
        "ok": True, "strategy": sid, "action": action,
        "mark": mark, "position": rt.get("position"),
        "equity": _mark_equity(rt, mark),
    })


# ── Web endpoint ──────────────────────────────────────────────────────────────

def _login_page(next_q: str = "", error: bool = False) -> str:
    """Login form. POSTs credentials to /login; `next_q` (a "?..." query string)
    brings the user back to the page they wanted — e.g. a Slack approve link."""
    err_div  = '<div class="err">✕ Invalid credentials</div>' if error else ""
    shake    = " shake" if error else ""
    next_esc = _html_escape(next_q)
    return f"""<!DOCTYPE html>
<html><head>
<meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>WealthOS — Sign in</title>
{_theme_head()}
<style>
  body{{display:flex;align-items:center;justify-content:center;padding:24px}}
  .box{{position:relative;background:var(--glass);border:1px solid var(--border);border-radius:20px;
        backdrop-filter:blur(20px) saturate(1.2);-webkit-backdrop-filter:blur(20px) saturate(1.2);
        box-shadow:0 30px 70px -24px rgba(0,0,0,.8),inset 0 1px 0 rgba(255,255,255,.07);
        padding:38px 36px 34px;width:100%;max-width:390px;
        animation:wosRise .8s var(--ease) backwards}}
  .box::before{{content:'';position:absolute;inset:0 0 auto 0;height:1px;
        background:linear-gradient(90deg,transparent,rgba(200,245,99,.45),rgba(126,245,208,.35),transparent)}}
  .box.shake{{animation:wosRise .8s var(--ease) backwards,wosShake .4s ease .1s}}
  @keyframes wosShake{{20%{{transform:translateX(-7px)}}40%{{transform:translateX(6px)}}60%{{transform:translateX(-4px)}}80%{{transform:translateX(3px)}}}}
  .logo{{font-family:var(--font-display);font-size:26px;font-weight:800;letter-spacing:-.02em;margin-bottom:4px}}
  .logo span{{background:var(--grad);background-size:220% 100%;-webkit-background-clip:text;background-clip:text;color:transparent;
        animation:wosShimmer 6s linear infinite}}
  .tagline{{font-size:11px;letter-spacing:.14em;text-transform:uppercase;color:var(--muted);margin-bottom:28px}}
  label{{font-size:10px;letter-spacing:.12em;text-transform:uppercase;color:var(--muted);display:block;margin-bottom:6px}}
  input{{width:100%;padding:12px 14px;background:rgba(0,0,0,.35);
        border:1px solid var(--border2);border-radius:10px;
        color:var(--text);font-family:var(--font-mono);font-size:13px;margin-bottom:18px;
        transition:border-color .25s,box-shadow .25s;outline:none}}
  input:focus{{border-color:rgba(200,245,99,.55);box-shadow:0 0 0 3px rgba(200,245,99,.12),0 0 20px -4px rgba(200,245,99,.3)}}
  button{{width:100%;padding:13px;background:var(--grad);border:none;border-radius:10px;color:#10130a;
        font-family:var(--font-mono);font-size:12px;font-weight:500;letter-spacing:.08em;text-transform:uppercase;
        cursor:pointer;transition:all .25s var(--ease);box-shadow:0 0 22px rgba(200,245,99,.25)}}
  button:hover{{box-shadow:0 0 34px rgba(200,245,99,.5);transform:translateY(-1px)}}
  button:active{{transform:translateY(0)}}
  .err{{color:var(--red);font-size:12px;margin-bottom:14px;padding:9px 12px;border-radius:9px;
        background:var(--red-dim);border:1px solid rgba(255,92,92,.35)}}
</style></head><body>
<div class="wos-aurora"></div>
<div class="wos-grid"></div>
<form class="box{shake}" method="POST" action="/login">
  <div class="logo">wealth<span>os</span></div>
  <div class="tagline">portfolio command center</div>
  {err_div}
  <input type="hidden" name="next" value="{next_esc}">
  <label>Username</label>
  <input type="text" name="username" autofocus autocomplete="username">
  <label>Password</label>
  <input type="password" name="password" autocomplete="current-password">
  <button type="submit">Sign in</button>
</form>
</body></html>"""


@app.function(
    image=image,
    secrets=[modal.Secret.from_name("signal-bot-secrets")],
    timeout=120,
)
@modal.asgi_app()
def web():
    """Dashboard app on the same URL as before (app `signal-bot`, function
    `web`). Was a single GET fastapi_endpoint with credentials base64-encoded
    in the ?auth= query param (leaked via logs/history/referrers); now an ASGI
    app with POST /login setting an HttpOnly session cookie. Query-param
    routing (?action=...) is unchanged."""
    from fastapi import FastAPI, Request
    from fastapi.responses import HTMLResponse, RedirectResponse

    api = FastAPI()

    @api.post("/login")
    async def login(request: Request):
        try:
            form     = await request.form()
            username = str(form.get("username", ""))
            password = str(form.get("password", ""))
            next_q   = str(form.get("next", ""))
        except Exception:
            username, password, next_q = "", "", ""
        if not next_q.startswith("?"):
            next_q = ""          # only same-page query strings — no open redirect
        if not verify_credentials(username, password):
            return HTMLResponse(_login_page(next_q, error=True), status_code=401)
        resp = RedirectResponse("/" + next_q, status_code=303)
        resp.set_cookie(SESSION_COOKIE, await create_session_async(),
                        max_age=SESSION_TTL_MS // 1000, path="/",
                        httponly=True, secure=True, samesite="lax")
        return resp

    @api.get("/")
    async def index(request: Request, action: str = "", token: str = "",
                    auth: str = "", points: str = "", v: float = 0):
        # `auth` is accepted-and-ignored so old bookmarked ?auth= URLs and the
        # auth-propagating JS in cached pages keep working (cookie decides).
        return await _web_handler(request, action, token, points, v)

    return api


def _portfolio_live_fetch() -> float:
    """Blocking pre-fetch for the Portfolio tab (HL account value + snapshot
    + cash-flow sync). Runs via asyncio.to_thread from the async handler."""
    try:
        info, _    = get_hl_clients()
        state      = get_account_state(info)
        live_value = state["account_value"]
        record_portfolio_snapshot(live_value)
        sync_cash_flows(os.environ["HYPERLIQUID_MASTER_ACCOUNT_ADDRESS"])
        return live_value
    except Exception as e:
        print(f"[portfolio] live fetch failed: {e}")
        return 0.0


async def _halt_state_async() -> dict:
    """Kill-switch state, async read (for the nav banner on non-RSPS tabs)."""
    try:
        raw = await signal_state.get.aio(HALT_KEY, "")
        d = json.loads(raw) if raw else {}
        if isinstance(d, dict):
            return {"halted": bool(d.get("halted")), "reason": str(d.get("reason", ""))}
    except Exception:
        pass
    return {"halted": False, "reason": ""}


async def _web_handler(request, action: str, token: str, points: str, v: float):
    from fastapi.responses import HTMLResponse

    # ── Auth: session cookie (set by POST /login) ─────────────────────────────
    authorized = True   # default: open if no creds configured
    auth = ""           # renderers embed this in links; empty → cookie carries auth
    if auth_configured():
        authorized = await check_session_async(request.cookies.get(SESSION_COOKIE, ""))
        if not authorized:
            q = str(request.url.query or "")
            return HTMLResponse(_login_page(f"?{q}" if q else ""))

    # ── Helper: auth-preserving redirect back to dashboard ─────────────────
    def _dash_redirect(auth_token: str) -> HTMLResponse:
        url = f"?auth={auth_token}" if auth_token else "?"
        return HTMLResponse(
            f'<html><head><meta http-equiv="refresh" content="1;url={url}">'
            f'</head><body></body></html>')

    # ── Approve ────────────────────────────────────────────────────────────
    if action == "approve":
        try:
            stored = await signal_state.get.aio("approval_token", "")
        except Exception:
            stored = ""
        if not token or not hmac.compare_digest(token, stored):
            return HTMLResponse(
                _page("Invalid or expired approval token.",
                      "Use the link from your Slack notification."),
                status_code=403)
        try:
            pending = json.loads(await signal_state.get.aio("pending_signal", "null"))
            msg_id  = await signal_state.get.aio("pending_msg_id", "")
        except Exception:
            pending, msg_id = None, ""
        if not pending:
            return HTMLResponse(_page("No pending signal to approve.", ""))
        try:
            await signal_state.__delitem__.aio("pending_signal")
            await signal_state.__delitem__.aio("pending_msg_id")
            await signal_state.__delitem__.aio("approval_token")
        except KeyError:
            pass
        try:
            # Fetch daily-open prices here too — check_signal stored them in
            # signal_state but that write may not have propagated, so re-fetch
            # from the signal's own timestamp to be safe.
            bc_px: dict[str, float] = {}
            try:
                sig_ts = pending.get("_ts") or 0
                if not sig_ts:
                    # Fall back to signal_state if timestamp wasn't embedded
                    bc_px = json.loads(await signal_state.get.aio("bar_close_prices", "{}"))
                else:
                    assets = [a["asset"] for a in pending.get("allocations", [])
                              if ASSET_TO_TICKER.get(a["asset"], a["asset"]) != "USDC"]
                    bc_px = get_daily_open_prices(assets, sig_ts)
            except Exception as e:
                print(f"[approve] bar_close fetch failed: {e}")
            result = do_rebalance(pending, msg_id, bar_close_prices=bc_px)
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
            stored = await signal_state.get.aio("approval_token", "")
        except Exception:
            stored = ""
        if not token or not hmac.compare_digest(token, stored):
            return HTMLResponse(
                _page("Invalid or expired token.", ""), status_code=403)
        try:
            mid = await signal_state.get.aio("pending_msg_id", "")
            if mid:
                await signal_state.__setitem__.aio("last_signal_id", mid)
            await signal_state.__delitem__.aio("pending_signal")
            await signal_state.__delitem__.aio("pending_msg_id")
            await signal_state.__delitem__.aio("approval_token")
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
            parsed["no_change"] = False
            send_slack("🔄 *Force rebalance* triggered via dashboard")
            # Fetch daily-open prices for bar-close tracking
            bc_px_force: dict[str, float] = {}
            try:
                sig_ts = signal_msg.get("timestamp", 0)
                assets = [a["asset"] for a in parsed.get("allocations", [])
                          if ASSET_TO_TICKER.get(a["asset"], a["asset"]) != "USDC"]
                bc_px_force = get_daily_open_prices(assets, sig_ts)
            except Exception as e:
                print(f"[force] bar_close fetch failed: {e}")
            result = do_rebalance(parsed, signal_msg["_id"], bar_close_prices=bc_px_force)
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

    # ── Kill switch (halt / resume) ────────────────────────────────────────
    if action in ("halt", "resume"):
        if not authorized:
            return HTMLResponse(
                _page("Not authorised.", "Log in first."), status_code=403)
        halted = (action == "halt")
        state  = {"halted": halted,
                  "reason": "manual kill switch" if halted else "",
                  "ts": int(time.time() * 1000)}
        await signal_state.__setitem__.aio("trading_halted", json.dumps(state))
        if halted:
            send_slack("🛑 *Trading HALTED* via dashboard kill switch.\n"
                       "No signals will execute until resumed.", mention=True)
        else:
            send_slack("✅ *Trading RESUMED* via dashboard. Auto-execution re-enabled.")
        return _dash_redirect(auth)

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
            import traceback
            tb = traceback.format_exc()
            print(f"[health] HL error:\n{tb}")
            issues.append(f"Hyperliquid: {e} | {tb.splitlines()[-2].strip()}")
        status = "HEALTHY" if not issues else "ISSUES: " + "; ".join(issues)
        return HTMLResponse(_page("Health Check", status))

    # ── WealthOS Terminal (experimental ground-up UI, side-by-side) ─────────
    if action == "next":
        return HTMLResponse(_TERMINAL_HTML)

    if action == "rsps_data":
        if not authorized:
            from fastapi.responses import JSONResponse
            return JSONResponse({"error": "not authorized"}, status_code=403)
        from fastapi.responses import JSONResponse
        try:
            return JSONResponse(await asyncio.to_thread(collect_rsps_data))
        except Exception as e:
            return JSONResponse({"error": str(e)}, status_code=500)

    # ── History tab ────────────────────────────────────────────────────────
    if action == "history":
        return HTMLResponse(_render_history(auth, halt=await _halt_state_async()))

    # ── History signals API (called by JS in history tab) ──────────────────
    if action == "history_signals":
        if not authorized:
            from fastapi.responses import JSONResponse
            return JSONResponse({"error": "not authorized"}, status_code=403)
        try:
            sigs = await asyncio.to_thread(_fetch_history_signals, 600)
            from fastapi.responses import JSONResponse
            return JSONResponse(sigs)
        except Exception as e:
            from fastapi.responses import JSONResponse
            return JSONResponse({"error": str(e)}, status_code=500)

    # ── Leverage settings ──────────────────────────────────────────────────
    if action == "leverage_load":
        if not authorized:
            from fastapi.responses import JSONResponse
            return JSONResponse({"error": "not authorized"}, status_code=403)
        try:
            data = json.loads(await signal_state.get.aio("leverage_settings", "{}"))
            from fastapi.responses import JSONResponse
            return JSONResponse(data)
        except Exception:
            from fastapi.responses import JSONResponse
            return JSONResponse({})

    if action == "leverage_save":
        if not authorized:
            from fastapi.responses import JSONResponse
            return JSONResponse({"error": "not authorized"}, status_code=403)
        from fastapi.responses import JSONResponse
        try:
            data = json.loads(points) if points else {}
            # Validate: values must be integers 1–20
            cleaned = {k: max(1, min(20, int(v))) for k, v in data.items()}
            await signal_state.__setitem__.aio("leverage_settings", json.dumps(cleaned))
            return JSONResponse({"ok": True, "saved": cleaned})
        except Exception as e:
            return JSONResponse({"error": str(e)}, status_code=500)

    # ── Reset equity history (wipe bad/migrated data) ──────────────────────
    if action == "equity_reset":
        if not authorized:
            from fastapi.responses import JSONResponse
            return JSONResponse({"error": "not authorized"}, status_code=403)
        from fastapi.responses import JSONResponse
        try:
            await signal_state.__setitem__.aio("equity_snapshots", "[]")
            await signal_state.__setitem__.aio("bc_snapshots", "[]")
            return JSONResponse({"ok": True, "message": "equity history wiped"})
        except Exception as e:
            return JSONResponse({"error": str(e)}, status_code=500)

    # ── (Deprecated) client equity upsert ──────────────────────────────────
    # The dashboard used to POST back its own server-rendered account value,
    # meaning any authorized client could write arbitrary equity history.
    # Snapshots are now recorded server-side in _render_dashboard; this stays
    # as a no-op so cached pages don't 404.
    if action == "equity_upsert":
        from fastapi.responses import JSONResponse
        return JSONResponse({"ok": True, "stored": False, "deprecated": True})

    # ── Cloud equity history API ────────────────────────────────────────────
    if action == "equity_history":
        if not authorized:
            from fastapi.responses import JSONResponse
            return JSONResponse({"error": "not authorized"}, status_code=403)
        try:
            raw   = await signal_state.get.aio("equity_snapshots", "[]")
            snaps = json.loads(raw)
            from fastapi.responses import JSONResponse
            return JSONResponse(snaps)
        except Exception as e:
            from fastapi.responses import JSONResponse
            return JSONResponse([], status_code=200)

    # ── (Disabled) Store backtest result in cloud ──────────────────────────
    # History is backtest-only. This used to merge backtest equity into the live
    # equity_snapshots (polluting the RSPS + WealthOS dashboards). Kept as an
    # explicit no-op so any cached/old History page can't write live data.
    if action == "equity_store_backtest":
        from fastapi.responses import JSONResponse
        return JSONResponse({"ok": True, "stored": 0, "disabled": True})

    # ── Bar-close equity history API ────────────────────────────────────────
    if action == "bc_equity_history":
        if not authorized:
            from fastapi.responses import JSONResponse
            return JSONResponse({"error": "not authorized"}, status_code=403)
        try:
            raw   = await signal_state.get.aio("bc_snapshots", "[]")
            snaps = json.loads(raw)
            from fastapi.responses import JSONResponse
            return JSONResponse(snaps)
        except Exception:
            from fastapi.responses import JSONResponse
            return JSONResponse([], status_code=200)

    # ── Portfolio tab (main wealth overview) ────────────────────────────────
    if action == "portfolio":
        # Live value fetch does blocking HL HTTP + sync Dict writes — run in a
        # worker thread so the event loop stays clean (no AsyncUsageWarning).
        live_value = await asyncio.to_thread(_portfolio_live_fetch)
        # Backfill portfolio history from RSPS equity (RSPS is 100% for now).
        # Only runs when equity has earlier data than portfolio — idempotent.
        try:
            equity = json.loads(await signal_state.get.aio("equity_snapshots", "[]"))
            port   = json.loads(await signal_state.get.aio("portfolio_snapshots", "[]"))
            e_start = equity[0]["ts"] if equity else None
            p_start = port[0]["ts"]   if port   else None
            if equity and (p_start is None or e_start < p_start or len(equity) > len(port)):
                merged = merge_equity_into_portfolio(equity, port)
                if len(merged) != len(port):
                    await signal_state.__setitem__.aio("portfolio_snapshots", json.dumps(merged))
                    print(f"[portfolio] backfilled {len(merged) - len(port)} snapshots from equity")
        except Exception as e:
            print(f"[portfolio] backfill failed: {e}")
        return HTMLResponse(_render_portfolio(auth, live_value,
                                              halt=await _halt_state_async()))

    if action == "portfolio_data":
        if not authorized:
            from fastapi.responses import JSONResponse
            return JSONResponse({"error": "not authorized"}, status_code=403)
        from fastapi.responses import JSONResponse
        try:
            snaps   = json.loads(await signal_state.get.aio("portfolio_snapshots", "[]"))
            flows   = json.loads(await signal_state.get.aio("cash_flows", "[]"))
            flows.sort(key=lambda f: f.get("ts", 0))
            # Paper forward-test strategies live in the Strategies tab only — they
            # represent hypothetical capital, so keep them out of the WealthOS
            # allocation view. A signal strategy promoted to LIVE (real capital)
            # does belong here and stays.
            all_strats = (json.loads(await signal_state.get.aio("strategies", "[]"))
                          or list(DEFAULT_STRATEGIES))
            strats  = [s for s in all_strats
                       if not (s.get("kind") == "signal" and s.get("mode") == "paper")]
            live    = v if v > 0 else (snaps[-1]["v"] if snaps else 0)
            metrics = compute_portfolio_metrics(snaps, flows, live)
            # Flow-adjusted TWR index series — powers the Performance and
            # Drawdown chart modes (deposits never show up as gains there).
            index_series = []
            mkt = _market_index(snaps, flows)
            if mkt is not None:
                index_series = [{"ts": s["ts"], "v": round(ix, 6)}
                                for s, ix in zip(*mkt)]
            return JSONResponse({
                "snapshots":    snaps,
                "flows":        flows,
                "strategies":   strats,
                "metrics":      metrics,
                "index_series": index_series,
            })
        except Exception as e:
            return JSONResponse({"error": str(e)}, status_code=500)

    # ── Benchmark closes (BTC/ETH daily) for the Performance overlay ────────
    # Read-only public-data fetch from HL; `points` = {"start": unix_ms}.
    if action == "benchmark_data":
        if not authorized:
            from fastapi.responses import JSONResponse
            return JSONResponse({"error": "not authorized"}, status_code=403)
        from fastapi.responses import JSONResponse
        try:
            data  = json.loads(points) if points else {}
            end   = int(time.time() * 1000)
            start = int(data.get("start", 0))
            if start <= 0 or start >= end:
                start = end - 365 * 86_400_000
            info = HlInfo()
            out: dict = {}
            for coin in ("BTC", "ETH"):
                try:
                    candles = info.candle_snapshot(coin, "1d", start, end)
                    out[coin] = [{"ts": int(c["t"]), "c": float(c["c"])}
                                 for c in (candles or [])]
                except Exception as e:
                    print(f"[benchmark] {coin} fetch failed: {e}")
                    out[coin] = []
            return JSONResponse(out)
        except Exception as e:
            return JSONResponse({"error": str(e)}, status_code=500)

    if action == "cashflow_add":
        if not authorized:
            from fastapi.responses import JSONResponse
            return JSONResponse({"error": "not authorized"}, status_code=403)
        from fastapi.responses import JSONResponse
        try:
            data   = json.loads(points) if points else {}
            amount = float(data.get("amount", 0))
            ts     = int(data.get("ts", int(time.time() * 1000)))
            note   = str(data.get("note", ""))[:80]
            if amount == 0:
                return JSONResponse({"error": "amount cannot be zero"}, status_code=400)
            flows = json.loads(await signal_state.get.aio("cash_flows", "[]"))
            flows.append({
                "ts": ts, "amount": round(amount, 2),
                "note": note or ("deposit" if amount > 0 else "withdrawal"),
                "source": "manual",
            })
            flows.sort(key=lambda f: f.get("ts", 0))
            await signal_state.__setitem__.aio("cash_flows", json.dumps(flows))
            return JSONResponse({"ok": True, "count": len(flows)})
        except Exception as e:
            return JSONResponse({"error": str(e)}, status_code=500)

    if action == "cashflow_delete":
        if not authorized:
            from fastapi.responses import JSONResponse
            return JSONResponse({"error": "not authorized"}, status_code=403)
        from fastapi.responses import JSONResponse
        try:
            data = json.loads(points) if points else {}
            del_ts   = int(data.get("ts", 0))
            del_hash = data.get("hash", "")
            flows = json.loads(await signal_state.get.aio("cash_flows", "[]"))
            flows = [f for f in flows
                     if not (f.get("ts") == del_ts and
                             f.get("hash", "") == del_hash and
                             f.get("source") == "manual")]
            await signal_state.__setitem__.aio("cash_flows", json.dumps(flows))
            return JSONResponse({"ok": True, "count": len(flows)})
        except Exception as e:
            return JSONResponse({"error": str(e)}, status_code=500)

    if action == "strategies_save":
        if not authorized:
            from fastapi.responses import JSONResponse
            return JSONResponse({"error": "not authorized"}, status_code=403)
        from fastapi.responses import JSONResponse
        try:
            data = json.loads(points) if points else {}
            strats = data.get("strategies", [])
            await signal_state.__setitem__.aio("strategies", json.dumps(strats))
            return JSONResponse({"ok": True})
        except Exception as e:
            return JSONResponse({"error": str(e)}, status_code=500)

    # ── Signal Strategies tab ───────────────────────────────────────────────
    if action == "strategies":
        return HTMLResponse(_render_strategies(auth, halt=await _halt_state_async()))

    if action == "strategies_data":
        if not authorized:
            from fastapi.responses import JSONResponse
            return JSONResponse({"error": "not authorized"}, status_code=403)
        from fastapi.responses import JSONResponse
        try:
            strats  = json.loads(await signal_state.get.aio("strategies", "[]"))
            sigs    = [s for s in strats if s.get("kind") == "signal"]
            runtime = json.loads(await signal_state.get.aio(SIGNAL_RUNTIME_KEY, "{}"))
            mids    = {}
            try:
                mids = safe_all_mids(HlInfo("https://api.hyperliquid.xyz"))
            except Exception as e:
                print(f"[strategies_data] price fetch failed: {e}")
            now_ms = int(time.time() * 1000)
            out, dirty = [], False
            for s in sigs:
                sid  = s["id"]
                mark = mids.get(s.get("asset", "BTC"), 0.0)
                rt   = runtime.get(sid) or new_runtime_entry(s.get("paper_capital", 10000))
                if mark > 0:                       # mark-to-market + record a curve point
                    rt = mark_runtime_point(rt, mark, ts=now_ms)
                    runtime[sid] = rt
                    dirty = True
                equity = _mark_equity(rt, mark) if mark > 0 else rt.get("equity", 0.0)
                base   = float(s.get("paper_capital", 10000) or 10000)
                out.append({
                    **s,
                    "mark":        mark,
                    "position":    rt.get("position"),
                    "equity":      equity,
                    "paper_pnl":   round(equity - base, 2),
                    "paper_return": round((equity / base - 1.0), 4) if base > 0 else 0.0,
                    "equity_curve": rt.get("equity_curve", []),
                    "signal_log":  rt.get("signal_log", [])[-12:][::-1],
                })
            if dirty:
                await signal_state.__setitem__.aio(SIGNAL_RUNTIME_KEY, json.dumps(runtime))
            return JSONResponse({"strategies": out})
        except Exception as e:
            return JSONResponse({"error": str(e)}, status_code=500)

    if action == "signal_strategy_add":
        if not authorized:
            from fastapi.responses import JSONResponse
            return JSONResponse({"error": "not authorized"}, status_code=403)
        from fastapi.responses import JSONResponse
        import re as _re
        try:
            data = json.loads(points) if points else {}
            name = str(data.get("name", "")).strip()[:40]
            if not name:
                return JSONResponse({"error": "name required"}, status_code=400)
            strats = json.loads(await signal_state.get.aio("strategies", "[]"))
            base_id = _re.sub(r"[^a-z0-9]+", "-", name.lower()).strip("-") or "strat"
            sid, n = base_id, 2
            existing = {s.get("id") for s in strats}
            while sid in existing:
                sid = f"{base_id}-{n}"; n += 1
            entry = {
                "id":            sid,
                "name":          name,
                "kind":          "signal",
                "asset":         str(data.get("asset", "BTC")).upper()[:8] or "BTC",
                "direction":     data.get("direction", "long_short"),
                "leverage":      max(1, int(data.get("leverage", 1) or 1)),
                "mode":          "live" if data.get("mode") == "live" else "paper",
                "paper_capital": max(1.0, float(data.get("paper_capital", 10000) or 10000)),
                "target_pct":    0.0,
                "status":        "forward_test",
                "source":        "tradingview",
                "token":         secrets.token_urlsafe(18),
                "created":       int(time.time() * 1000),
            }
            strats.append(entry)
            await signal_state.__setitem__.aio("strategies", json.dumps(strats))
            runtime = json.loads(await signal_state.get.aio(SIGNAL_RUNTIME_KEY, "{}"))
            runtime[sid] = new_runtime_entry(entry["paper_capital"])
            await signal_state.__setitem__.aio(SIGNAL_RUNTIME_KEY, json.dumps(runtime))
            return JSONResponse({"ok": True, "id": sid, "token": entry["token"]})
        except Exception as e:
            return JSONResponse({"error": str(e)}, status_code=500)

    if action == "signal_strategy_delete":
        if not authorized:
            from fastapi.responses import JSONResponse
            return JSONResponse({"error": "not authorized"}, status_code=403)
        from fastapi.responses import JSONResponse
        try:
            data = json.loads(points) if points else {}
            sid  = str(data.get("id", ""))
            strats = json.loads(await signal_state.get.aio("strategies", "[]"))
            strats = [s for s in strats if s.get("id") != sid]
            await signal_state.__setitem__.aio("strategies", json.dumps(strats))
            runtime = json.loads(await signal_state.get.aio(SIGNAL_RUNTIME_KEY, "{}"))
            if sid in runtime:
                del runtime[sid]
                await signal_state.__setitem__.aio(SIGNAL_RUNTIME_KEY, json.dumps(runtime))
            return JSONResponse({"ok": True})
        except Exception as e:
            return JSONResponse({"error": str(e)}, status_code=500)

    # ── Dashboard ──────────────────────────────────────────────────────────
    # Pre-fetch all Modal Dict values here (async context) before passing to sync _render_dashboard
    dash_state = {
        "pending_signal":   await signal_state.get.aio("pending_signal",   "null"),
        "approval_token":   await signal_state.get.aio("approval_token",   ""),
        "last_signal_id":   await signal_state.get.aio("last_signal_id",   "none"),
        "leverage_settings": await signal_state.get.aio("leverage_settings", "{}"),
        "halt":             await signal_state.get.aio("trading_halted",    ""),
    }
    # Render in a worker thread: it does blocking TRW/HL fetches and sync
    # Modal Dict writes (equity snapshot) that would otherwise stall the event
    # loop and spam AsyncUsageWarning.
    return HTMLResponse(await asyncio.to_thread(_render_dashboard, dash_state))

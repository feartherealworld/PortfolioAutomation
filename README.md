# WealthOS

**A self-hosted portfolio command center for Hyperliquid.** Executes Prof Adam's RSPS (Relative Strength Portfolio System) signal on autopilot, tracks your total wealth with institutional-grade metrics, and bridges any TradingView strategy into paper or live trading — all from one dashboard, running free on Modal.

> **New here?** The [full setup guide](guide.html) takes you from zero to deployed in ~20 minutes.

---

## The three pillars

| | |
|---|---|
| **RSPS Autopilot** | Reads Prof Adam's Portfolio Signal at bar close via TRW's API, parses allocations, and rebalances your Hyperliquid unified account — spot where available, 1x perps otherwise, optional per-asset leverage. Autonomous overnight, Slack-approval by day. |
| **WealthOS Analytics** | True P&L that can't be fooled by deposits: time-weighted return (Modified Dietz), XIRR, Sharpe, Sortino, volatility, max drawdown, best/worst day — plus performance charted against BTC-hold and ETH-hold benchmarks, and an underwater drawdown view. |
| **Strategy Lab** | Bridge any TradingView strategy via webhook into a paper-trading engine with its own equity curve, position state, and signal log. Forward-test with fake money until a strategy earns real capital. |

## Dashboard

Four tabs, one login (30-day session cookie), aurora-glass UI, mobile-friendly:

- **RSPS** — live health badges (TRW / HL / Slack), account metrics with count-up animations, equity curve with bar-close comparison, positions with funding APR and liquidation distance, per-asset leverage panel, kill switch, force rebalance, one-tap signal approval.
- **Portfolio** — total wealth hero, deposit-aware returns, risk metric tiles, Value / vs-Deposited / Performance / Drawdown chart modes with BTC & ETH overlays, strategy allocation editor, auto-detected cash flows.
- **Strategies** — TradingView webhook strategies as glass cards: sparkline equity, paper/live badge, open position, signal log, copy-paste Pine `alert()` snippet.
- **History** — backtest the RSPS signal archive on Hyperliquid candles with fees, equity curve variants, and a Kelly-criterion allocation panel.

## Quick start

1. Gather your tokens (TRW session token, Hyperliquid API wallet, Modal account) — the [guide](guide.html) shows each step with exact clicks.
2. ```
   pip install -r requirements.txt
   python manage.py
   ```
3. A browser page opens — paste your tokens, set a dashboard password, click **Save & Deploy**.
4. Your dashboard lives at `https://YOUR_WORKSPACE--signal-bot-web.modal.run`. Bookmark it on your phone.

Running `python manage.py` again any time shows connection status for every service, updates expired tokens, and redeploys.

## How the RSPS autopilot behaves

| Time (UK) | Polling | Mode |
|---|---|---|
| 00:00–00:30 | every 2 min | **Autonomous** — signal usually drops here |
| 00:30–05:00 | every 10 min | **Autonomous** |
| 05:00–00:00 | every 2 h | **Approval** — Slack link to approve/dismiss |

Safety rails: a manual **kill switch** gates every real order; allocation-sum validation aborts on parse failures; per-order size caps and slippage limits; a full execution report (fills, deviation from bar close, slippage cost) lands in Slack after every rebalance.

## Repository layout

| Path | What it does |
|---|---|
| `manage.py` | **Start here** — GUI for setup, token management, connection checks |
| `modal_signal_bot.py` | Deploy entry point (`modal deploy modal_signal_bot.py`) |
| `signalbot/config.py` | Modal app, image, state, constants |
| `signalbot/trw.py` | Signal reading + parsing |
| `signalbot/hyperliquid.py` | Account state, rebalance math, order execution |
| `signalbot/rebalance.py` | Rebalance orchestration + scheduling |
| `signalbot/strategies.py` | Paper engine, portfolio metrics, snapshots |
| `signalbot/auth.py` | Dashboard sessions (login cookie) |
| `signalbot/safety.py` | Global kill switch |
| `signalbot/endpoints.py` | Web app, TradingView webhook, cron functions |
| `signalbot/ui/` | Dashboard — one module per tab + shared design system |
| `tests/` | 48 pytest tests pinning parsing, rebalance math, metrics, auth |
| `slack_tests.py` | Fire sample notifications at your Slack webhook |
| `guide.html` | Full setup guide |

## Development

```
pip install -r requirements-dev.txt
python -m pytest tests/
```

Trading logic is covered by regression tests — the signal parser, rebalance computation, paper engine, and portfolio math are all pure functions with pinned behavior.

## Security

Connects to exactly **three services, all yours**: TRW (read signals), Hyperliquid (read positions, place orders), and your own Slack webhook. No analytics, no telemetry, no third parties. Secrets live in your local `.env` (git-ignored) and Modal's encrypted secrets — nowhere else. The Hyperliquid API wallet **cannot withdraw or transfer funds**, only place and cancel orders; revoke it any time at app.hyperliquid.xyz.

Dashboard auth uses a POST login with an HttpOnly session cookie — credentials never appear in URLs or logs.

## Cost

**$0/month.** Modal free tier + Hyperliquid trading fees (~0.04% per trade).

## Versions

- **`main`** (tag `v2.0-wealthos`) — this version.
- **[`legacy-v1`](../../tree/legacy-v1)** (tag `v1-legacy`) — the original single-file signal bot, preserved as-is.

## Disclaimer

This automates real trades on a live account. Start small, understand the signals you're automating, and use at your own risk. Not financial advice.

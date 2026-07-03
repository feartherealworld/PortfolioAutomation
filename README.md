# TRW Auto-Trade Signal Bot

Automatically execute Prof Adam's RSPS portfolio signals on Hyperliquid. Runs 24/7 in the cloud for free.

> **New here?** Read the [full setup guide](guide.html) for step-by-step instructions with screenshots.

---

## What It Does

- Reads Prof Adam's Portfolio Signal at bar close (~00:00 UTC) via TRW's API
- Parses the allocation percentages (e.g. 80% ETH, 14.3% HYPE, 5.7% PAXG)
- Rebalances your Hyperliquid portfolio to match using 1x leverage perps
- Runs 24/7 in the cloud on [Modal](https://modal.com) free tier — no computer needed
- Slack notifications with execution status and price deviation from bar close
- Web dashboard to monitor positions, equity curve, and approve trades from your phone
- Password-protected dashboard login

## Features

- **Smart polling** — every 2 min during signal window, hourly otherwise
- **Autonomous mode** — auto-executes 00:00–05:00 UTC when the signal drops
- **Approval mode** — sends Slack notification with approve/dismiss link during daytime
- **Execution report** — shows fill price vs bar close price and total slippage cost
- **Equity chart** — tracks your portfolio value over time with bar close comparison toggle
- **CSV export** — download equity history for analysis
- **Safety guards** — allocation sum validation aborts trades if signal parsing fails
- **Mobile optimised** — dashboard works well on phone for midnight approvals

## Quick Start

Full details in the [setup guide](guide.html). Short version:

1. Get your tokens ready (TRW session token, Hyperliquid API keys, Modal account)
2. Install Python 3.12 and dependencies:
   ```
   pip install -r requirements.txt
   ```
3. Launch the setup manager:
   ```
   python manage.py
   ```
4. A browser page opens — paste your tokens, set a dashboard password, click **Save & Deploy**

## Managing Your Bot

Run `python manage.py` any time to:

- Check connection status (TRW, Hyperliquid, Slack)
- Update tokens when they expire
- Change your dashboard password
- Redeploy after changes

## Dashboard

Your dashboard URL will be:
```
https://YOUR_WORKSPACE--signal-bot-web.modal.run
```

The manager shows your exact URL after first deploy. Features:

- Live account value and PnL
- Open positions with entry prices
- Latest signal allocations
- Equity curve with bar close comparison
- Approve / dismiss pending signals
- Force rebalance
- Health check

## Files

| File | What it does |
|---|---|
| `manage.py` | **Start here** — GUI for setup, token management, and connection checks |
| `modal_signal_bot.py` | Deploy entry point (`modal deploy modal_signal_bot.py`) |
| `signalbot/` | The bot itself — signal reading, rebalancing, dashboard, strategies |
| `setup.py` | CLI alternative to manage.py |
| `slack_tests.py` | Fire test notifications at your Slack webhook |
| `guide.html` | Full setup guide |

## Security

This code connects to exactly **3 services** — all yours:

| Service | URL | Why |
|---|---|---|
| TRW | `eden.therealworld.ag` | Read signals |
| Hyperliquid | `api.hyperliquid.xyz` | Read positions and place trades |
| Slack | Your own webhook URL | Send you notifications |

No analytics. No telemetry. No data sent anywhere else. Runs on your own Modal account.

The Hyperliquid API wallet **cannot withdraw funds** — it can only place and cancel orders.

## Cost

$0/month. Modal free tier + Hyperliquid trading fees (~0.04% per trade).

## Polling Schedule

| Time (UK) | Frequency |
|---|---|
| 00:00–00:30 | Every 2 minutes |
| 00:30–05:00 | Every 10 minutes |
| 05:00–00:00 | Every hour |

## Trading Modes

| Time (UK) | Mode |
|---|---|
| 00:00–05:00 | Autonomous — auto-executes |
| 05:00–00:00 | Approval — sends Slack link to approve |

## Disclaimer

⚠️ This bot automates real trades on a live trading account. Start with a small amount to test. Use at your own risk — this is not financial advice. Always understand the signals before automating them.

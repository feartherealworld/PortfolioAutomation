"""
Slack notification tester — fires every notification type to your webhook.

Usage:
    python test_slack.py                        # uses SLACK_WEBHOOK_URL from .env
    python test_slack.py https://hooks.slack.com/...  # pass webhook directly
    python test_slack.py --only rebalance       # fire just one type

Types: all, nochange, approval, autotrade, rebalance, partial, failed,
       aligned, lowbalance, parseerror, trwerror, rebalanceerror,
       dismissed, force, leveragefail
"""

import sys
import os
import time
import argparse
import requests
from pathlib import Path
from dotenv import load_dotenv

load_dotenv(Path(__file__).resolve().parent / ".env")

WEBHOOK = None  # set below


def send(text: str, label: str) -> None:
    resp = requests.post(WEBHOOK, json={"text": text}, timeout=10)
    ok = "✓" if resp.status_code == 200 else f"✗ HTTP {resp.status_code}"
    print(f"  [{ok}] {label}")
    time.sleep(0.4)   # avoid Slack rate limit


def run(types: set[str]) -> None:
    dt = "28 Mar 01:02 UTC"
    alloc_lines = "  80% Spot ETH\n  14.3% Spot HYPE\n  5.7% Gold PAXG"
    new_alloc   = "  60% Spot ETH\n  25% Spot BTC\n  15% Gold PAXG"
    acct        = "$94.12"
    dashboard   = "https://your-workspace--signal-bot-web.modal.run"

    notifications = {

        # ── Routine ──────────────────────────────────────────────────────────
        "nochange": (
            f"📋 *No change*  ·  {dt}\n{alloc_lines}",
            "No change"
        ),

        "approval": (
            f"📬 *New signal — approval required*  ·  {dt}\n"
            f"{new_alloc}\n"
            f"──────────────────\n"
            f"<{dashboard}?action=approve&token=testtoken123|✅ Approve>   "
            f"<{dashboard}?action=dismiss&token=testtoken123|✗ Dismiss>   "
            f"<{dashboard}|Dashboard>",
            "Approval required"
        ),

        "autotrade": (
            f"🤖 *New signal — auto-rebalancing*  ·  {dt}\n{new_alloc}",
            "Auto-rebalance triggered"
        ),

        # ── Rebalance results ─────────────────────────────────────────────────
        "rebalance": (
            "✅ *Rebalance complete*\n"
            f"Account  *{acct}*   ·   3 filled   ·   0 failed\n"
            "Slippage  $0.04  (0.042%)\n"
            "──────────────────\n"
            "↑ BUY 0.0240 ETH/USDC ◆  @  $2,847.20\n"
            "   bar $2,841.00  ·  dev +0.218%  ·  slip $0.01\n"
            "↑ BUY 0.0002 BTC/USDC ◆  @  $71,240.00\n"
            "   bar $71,190.00  ·  dev +0.070%  ·  slip $0.01\n"
            "↑ BUY 0.0158 PAXG ◇  @  $2,961.40\n"
            "   bar $2,958.00  ·  dev +0.115%  ·  slip $0.02\n"
            "\n◆ spot  ◇ perp",
            "Rebalance complete"
        ),

        "partial": (
            "⚠️ *Rebalance partial*\n"
            f"Account  *{acct}*   ·   2 filled   ·   1 failed\n"
            "──────────────────\n"
            "↑ BUY 0.0240 ETH/USDC ◆  @  $2,847.20\n"
            "   bar $2,841.00  ·  dev +0.218%  ·  slip $0.01\n"
            "↑ BUY 0.0002 BTC/USDC ◆  @  $71,240.00\n"
            "   bar $71,190.00  ·  dev +0.070%  ·  slip $0.01\n"
            "✗ FAIL PAXG BUY: Order size below minimum\n"
            "\n◆ spot  ◇ perp",
            "Rebalance partial"
        ),

        "failed": (
            "🚨 *Rebalance FAILED*\n"
            f"Account  *{acct}*   ·   0 filled   ·   3 failed\n"
            "──────────────────\n"
            "✗ FAIL ETH/USDC BUY: Insufficient margin\n"
            "✗ FAIL BTC/USDC BUY: Insufficient margin\n"
            "✗ FAIL PAXG BUY: Insufficient margin",
            "Rebalance failed"
        ),

        "aligned": (
            "✅ *Signal processed* — positions already match, no trades needed.",
            "Already aligned"
        ),

        # ── Skipped / aborted ─────────────────────────────────────────────────
        "lowbalance": (
            "🚨 *Skipped* — account value too low to trade. Deposit USDC first.",
            "Low balance skip"
        ),

        "parseerror": (
            "🚨 *Aborted* — allocations sum to 47.3% (expected ~100%).\n"
            "Possible signal parse failure. No trades placed.",
            "Parse error abort"
        ),

        "leveragefail": (
            "⚠️ *Leverage set failed* for PAXG\n"
            "`Exchange error: leverage update rejected`",
            "Leverage set failed"
        ),

        # ── System errors ─────────────────────────────────────────────────────
        "trwerror": (
            "🔑 *TRW auth error* — token expired\n"
            "`TRW session token expired`\n"
            "Run `python manage.py` to refresh.",
            "TRW token expired"
        ),

        "rebalanceerror": (
            "🚨 *Rebalance error*\n"
            "`Connection timeout: api.hyperliquid.xyz`",
            "Rebalance exception"
        ),

        # ── Dashboard actions ─────────────────────────────────────────────────
        "dismissed": (
            "🗑️ Signal dismissed via dashboard.",
            "Signal dismissed"
        ),

        "force": (
            "🔄 *Force rebalance* triggered via dashboard",
            "Force rebalance"
        ),
    }

    to_send = {k: v for k, v in notifications.items()
               if "all" in types or k in types}

    if not to_send:
        print(f"Unknown type(s). Valid: all, {', '.join(notifications)}")
        sys.exit(1)

    print(f"\nFiring {len(to_send)} notification(s) to Slack...\n")
    for key, (text, label) in to_send.items():
        send(text, label)
    print(f"\nDone. Check your Slack channel.")


def main() -> None:
    global WEBHOOK

    parser = argparse.ArgumentParser(description="Test Slack notifications")
    parser.add_argument("webhook", nargs="?", help="Webhook URL (or set SLACK_WEBHOOK_URL in .env)")
    parser.add_argument("--only", nargs="+", default=["all"],
                        metavar="TYPE", help="Which notifications to send")
    args = parser.parse_args()

    WEBHOOK = args.webhook or os.getenv("SLACK_WEBHOOK_URL", "")
    if not WEBHOOK:
        print("ERROR: No webhook URL. Either:\n"
              "  python test_slack.py https://hooks.slack.com/...\n"
              "  or set SLACK_WEBHOOK_URL in your .env file")
        sys.exit(1)

    if not WEBHOOK.startswith("https://hooks.slack.com/"):
        print(f"WARNING: URL doesn't look like a Slack webhook: {WEBHOOK[:60]}")

    run(set(args.only))


if __name__ == "__main__":
    main()
"""
Modal Signal Bot — Unified Account Edition (deploy entry).

The implementation now lives in the `signalbot/` package; this file is a thin
shim that exposes the Modal `app` and registers the @app.function endpoints so
the existing workflow keeps working:

    modal deploy modal_signal_bot.py

Package layout:
    signalbot/config.py       app, image, signal_state, constants
    signalbot/notify.py       Slack
    signalbot/trw.py          TRW signal reading + parsing
    signalbot/hyperliquid.py  HlInfo, account state, rebalance compute + execute
    signalbot/strategies.py   paper engine, portfolio metrics, snapshots, registry
    signalbot/rebalance.py    do_rebalance + scheduling helpers
    signalbot/dashboard.py    HTML constants + renderers
    signalbot/endpoints.py    web + tv_webhook + cron functions (@app.function)
"""
from signalbot.config import app, image  # noqa: F401  (app is the Modal deploy target)
from signalbot import endpoints           # noqa: F401  (import registers @app.function endpoints)

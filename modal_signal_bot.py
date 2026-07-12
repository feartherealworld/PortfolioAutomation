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
    signalbot/auth.py         dashboard sessions (login cookie)
    signalbot/ui/             dashboard HTML + renderers, one module per tab
    signalbot/endpoints.py    web + tv_webhook + cron functions (@app.function)
"""
import os as _os
import subprocess as _sp
from pathlib import Path as _Path

# Bake the deployed commit into the image (runs on the DEPLOYING machine only:
# the container has no .git). signalbot/version.py reads it; the dashboard's
# update checker compares it against GitHub main.
_repo = _Path(__file__).resolve().parent
if (_repo / ".git").exists() and "MODAL_TASK_ID" not in _os.environ:
    try:
        _sha = _sp.run(["git", "rev-parse", "HEAD"], cwd=_repo,
                       capture_output=True, text=True, timeout=10).stdout.strip()
        if _sha:
            from datetime import datetime, timezone
            _built = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")
            (_repo / "signalbot" / "_build.py").write_text(
                f'COMMIT = "{_sha}"\nBUILT = "{_built}"\n', encoding="utf-8")
    except Exception as _e:
        print(f"[build] version bake skipped: {_e}")

from signalbot.config import app, image  # noqa: F401,E402  (app is the Modal deploy target)
from signalbot import endpoints           # noqa: F401,E402  (import registers @app.function endpoints)

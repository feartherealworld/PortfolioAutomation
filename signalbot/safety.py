import json
import time

from signalbot.config import *

__all__ = [
    "HALT_KEY",
    "get_halt_state",
    "is_trading_halted",
    "set_halt",
]

# Global kill switch. When halted, no REAL orders are placed by any strategy
# (RSPS rebalance, and future live signal strategies). Paper tracking is
# unaffected. State lives in signal_state under HALT_KEY as a JSON dict:
#   {"halted": bool, "reason": str, "ts": int(unix_ms)}
HALT_KEY = "trading_halted"


def get_halt_state() -> dict:
    """Sync read of the halt flag. Always returns a well-formed dict."""
    try:
        raw = signal_state.get(HALT_KEY, "")
        if raw:
            d = json.loads(raw)
            if isinstance(d, dict):
                return {
                    "halted": bool(d.get("halted")),
                    "reason": str(d.get("reason", "")),
                    "ts":     int(d.get("ts", 0)),
                }
    except Exception:
        pass
    return {"halted": False, "reason": "", "ts": 0}


def is_trading_halted() -> bool:
    """True when the global kill switch is engaged. The single gate every real
    execution path must consult before placing orders."""
    return get_halt_state()["halted"]


def set_halt(halted: bool, reason: str = "") -> dict:
    """Engage/disengage the kill switch (sync write). Returns the new state."""
    state = {"halted": bool(halted), "reason": str(reason)[:200],
             "ts": int(time.time() * 1000)}
    signal_state[HALT_KEY] = json.dumps(state)
    return state

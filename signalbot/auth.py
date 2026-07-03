import os
import json
import time
import hmac
import hashlib
import secrets

from signalbot.config import *

__all__ = [
    'SESSIONS_KEY',
    'SESSION_COOKIE',
    'SESSION_TTL_MS',
    'auth_configured',
    'verify_credentials',
    'create_session',
    'check_session',
]

# Dashboard sessions. Tokens are random 256-bit values delivered as an
# HttpOnly cookie; only their SHA-256 digests are stored server-side, so a
# leaked Modal Dict dump can't be replayed as a cookie.
#   signal_state[SESSIONS_KEY] = {"<sha256hex>": expiry_unix_ms, ...}
SESSIONS_KEY   = "dash_sessions"
SESSION_COOKIE = "wos_session"
SESSION_TTL_MS = 30 * 86_400_000   # 30 days
_MAX_SESSIONS  = 20                # oldest-expiry sessions dropped beyond this


def auth_configured() -> bool:
    """True when a dashboard username+password pair is set in the environment."""
    return bool(os.environ.get("DASHBOARD_USERNAME", "")
                and os.environ.get("DASHBOARD_PASSWORD", ""))


def verify_credentials(username: str, password: str) -> bool:
    """Constant-time check of submitted credentials against the environment."""
    expected_user = os.environ.get("DASHBOARD_USERNAME", "")
    expected_pass = os.environ.get("DASHBOARD_PASSWORD", "")
    if not expected_user or not expected_pass:
        return False
    user_ok = hmac.compare_digest(username.strip().encode(), expected_user.strip().encode())
    pass_ok = hmac.compare_digest(password.strip().encode(), expected_pass.strip().encode())
    return user_ok and pass_ok


def _hash(token: str) -> str:
    return hashlib.sha256(token.encode()).hexdigest()


def _load_sessions() -> dict[str, int]:
    try:
        d = json.loads(signal_state.get(SESSIONS_KEY, "{}"))
        if isinstance(d, dict):
            return {str(k): int(v) for k, v in d.items()}
    except Exception:
        pass
    return {}


def create_session() -> str:
    """Mint a new session token, persist its digest, return the raw token."""
    token  = secrets.token_urlsafe(32)
    now_ms = int(time.time() * 1000)
    sessions = {h: exp for h, exp in _load_sessions().items() if exp > now_ms}
    sessions[_hash(token)] = now_ms + SESSION_TTL_MS
    if len(sessions) > _MAX_SESSIONS:
        for h in sorted(sessions, key=sessions.get)[:len(sessions) - _MAX_SESSIONS]:
            del sessions[h]
    signal_state[SESSIONS_KEY] = json.dumps(sessions)
    return token


def check_session(token: str) -> bool:
    """True when `token` matches an unexpired session."""
    if not token:
        return False
    exp = _load_sessions().get(_hash(token))
    return bool(exp and exp > int(time.time() * 1000))

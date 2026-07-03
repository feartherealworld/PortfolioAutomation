"""Dashboard session auth (signalbot/auth.py) against an in-memory state."""
import time
import json
import pytest

import signalbot.auth as auth


@pytest.fixture(autouse=True)
def fake_state(monkeypatch):
    state: dict = {}
    monkeypatch.setattr(auth, "signal_state", state, raising=True)
    return state


@pytest.fixture(autouse=True)
def creds(monkeypatch):
    monkeypatch.setenv("DASHBOARD_USERNAME", "user")
    monkeypatch.setenv("DASHBOARD_PASSWORD", "correct horse")


def test_verify_credentials():
    assert auth.verify_credentials("user", "correct horse")
    assert auth.verify_credentials(" user ", "correct horse")   # strip() parity
    assert not auth.verify_credentials("user", "wrong")
    assert not auth.verify_credentials("", "")


def test_auth_not_configured(monkeypatch):
    monkeypatch.setenv("DASHBOARD_PASSWORD", "")
    assert not auth.auth_configured()
    assert not auth.verify_credentials("user", "anything")


def test_session_roundtrip(fake_state):
    token = auth.create_session()
    assert auth.check_session(token)
    assert not auth.check_session("forged")
    assert not auth.check_session("")
    # Raw token never stored server-side — only its digest.
    assert token not in fake_state[auth.SESSIONS_KEY]


def test_session_expiry(fake_state):
    token = auth.create_session()
    sessions = json.loads(fake_state[auth.SESSIONS_KEY])
    (h, _), = sessions.items()
    sessions[h] = int(time.time() * 1000) - 1     # force-expire
    fake_state[auth.SESSIONS_KEY] = json.dumps(sessions)
    assert not auth.check_session(token)


def test_session_cap(fake_state):
    tokens = [auth.create_session() for _ in range(25)]
    sessions = json.loads(fake_state[auth.SESSIONS_KEY])
    assert len(sessions) <= 20
    assert auth.check_session(tokens[-1])         # newest survives

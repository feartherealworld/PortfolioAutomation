import os
import json
import re
import time
import hmac
import secrets
from datetime import datetime, timezone
from decimal import Decimal, ROUND_DOWN
from signalbot.config import *

__all__ = [
    'fetch_recent_messages',
    'find_latest_signal',
    'parse_signal',
]


def fetch_recent_messages(limit: int = 20) -> list[dict]:
    import requests as req
    resp = req.post(
        f"{TRW_API_BASE}/messages/query",
        headers={
            "x-session-token": os.environ["TRW_SESSION_TOKEN"],
            "Content-Type": "application/json",
            "Origin": "https://app.jointherealworld.com",
        },
        json={
            "channel": os.environ.get("TRW_SIGNAL_CHANNEL_ID",
                                      "01H83QAX979K9R7QTMH74ATR8C"),
            "limit": limit,
            "sort": "Latest",
        },
        timeout=15,
    )
    if resp.status_code == 401:
        raise RuntimeError("TRW session token expired")
    resp.raise_for_status()
    return resp.json().get("messages", [])


def find_latest_signal(messages: list[dict]) -> dict | None:
    prof_adam = os.environ.get("TRW_PROF_ADAM_USER_ID",
                               "01GHHHWZE7Q77AKGWZDGC5PDCN")
    for msg in messages:
        if (msg.get("author") == prof_adam
                and "Portfolio Signal Update" in msg.get("content", "")):
            return msg
    return None


def parse_signal(content: str) -> dict:
    result = {"allocations": [], "no_change": False, "btc_leverage": None}
    exec_match = re.search(
        r"Executive Summary:(.+?)(?:Associated Data|$)", content, re.DOTALL)
    if exec_match and "no change" in exec_match.group(1).lower():
        result["no_change"] = True
    alloc_pattern = re.compile(
        r"\*?\*?(\d+(?:\.\d+)?)\s*%\s*(Spot|Gold|Leverage)?\s*\$?([\w/$]+)\*?\*?",
        re.IGNORECASE,
    )
    signal_section = re.search(
        r"(?:RSPS Signal|Risk-On Crypto Signal|\*\*Signal:\*\*).*?"
        r"(?:Executive Summary|Associated Data|───|$)",
        content, re.DOTALL,
    )
    if signal_section:
        section_text = signal_section.group(0)
        for match in alloc_pattern.finditer(section_text):
            pct_str, alloc_type, asset = match.groups()
            asset = asset.strip("$*").upper()
            if asset == "GOLD" or (alloc_type and alloc_type.lower() == "gold"):
                gold_match = re.search(r"PAXG(?:\s*/\s*\$?XAUT)?",
                                       section_text, re.IGNORECASE)
                asset = (gold_match.group(0).upper().replace(" ", "")
                         .replace("$", "") if gold_match else "PAXG/XAUT")
                alloc_type = "Gold"
            elif asset in ("CASH", "USDC"):
                alloc_type = "Cash"
                asset = "USDC"
            elif not alloc_type:
                alloc_type = "Spot"
            else:
                alloc_type = alloc_type.capitalize()
            result["allocations"].append({
                "percent": float(pct_str),
                "type":    alloc_type,
                "asset":   asset,
            })
    lev_match = re.search(
        r"BTC Leverage.*?=.*?(Impermissible|Permissible)", content, re.IGNORECASE)
    if lev_match:
        result["btc_leverage"] = lev_match.group(1).capitalize()
    return result

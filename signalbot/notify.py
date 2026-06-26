import os

__all__ = [
    'send_slack',
]


# ── Slack ─────────────────────────────────────────────────────────────────────

def send_slack(text: str, mention: bool = False):
    import requests as req
    webhook = os.environ.get("SLACK_WEBHOOK_URL", "")
    if not webhook:
        print(f"[SLACK SKIPPED] {text}")
        return
    try:
        req.post(webhook, json={"text": text}, timeout=10)
    except Exception as e:
        print(f"[SLACK ERROR] {e}")

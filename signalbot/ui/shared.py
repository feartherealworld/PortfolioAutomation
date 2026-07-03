"""Shared dashboard UI helpers (escaping, message page shell)."""
from signalbot.config import *

__all__ = ['_html_escape', '_page']


def _html_escape(s: str) -> str:
    """Escape HTML special characters to prevent reflected XSS."""
    return (s.replace("&", "&amp;").replace("<", "&lt;")
             .replace(">", "&gt;").replace('"', "&quot;"))

def _page(title: str, body: str) -> str:
    t = _html_escape(title)
    b = _html_escape(body)
    return f"""<!DOCTYPE html>
<html>
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>{t}</title>
  <style>
    body {{ font-family: 'DM Mono', monospace; background: #0a0a0a; color: #f0ede8;
           padding: 40px 28px; max-width: 600px; margin: 0 auto; }}
    h2 {{ font-family: 'Syne', sans-serif; font-size: 20px; font-weight: 700;
          margin-bottom: 12px; color: #c8f563; }}
    p {{ color: #6b6860; font-size: 13px; margin-bottom: 20px; white-space: pre-wrap; }}
    a {{ color: #5b9cf6; text-decoration: none; font-size: 12px;
         border: 1px solid rgba(91,156,246,0.3); padding: 6px 14px; border-radius: 4px; }}
    a:hover {{ background: rgba(91,156,246,0.1); }}
  </style>
</head>
<body>
  <h2>{t}</h2>
  <p>{b}</p>
  <a href="?">Back to dashboard</a>
</body>
</html>"""

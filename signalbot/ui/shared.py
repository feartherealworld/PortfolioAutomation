"""Shared dashboard UI helpers (escaping, message page shell, unified nav)."""
from signalbot.config import *

__all__ = ['_html_escape', '_page', '_nav_html']


def _html_escape(s: str) -> str:
    """Escape HTML special characters to prevent reflected XSS."""
    return (s.replace("&", "&amp;").replace("<", "&lt;")
             .replace(">", "&gt;").replace('"', "&quot;"))

# One nav to rule all four tabs. Each tab's HTML carries a __NAV_PLACEHOLDER__
# that its renderer swaps for this. Styling relies on the .header/.tab-nav/.logo
# rules each tab already defines; the halt banner is self-styled (inline) so it
# renders identically everywhere.
_NAV_TABS = [
    ("portfolio",  "Portfolio",  "?action=portfolio"),
    ("rsps",       "RSPS",       "?"),
    ("history",    "History",    "?action=history"),
    ("strategies", "Strategies", "?action=strategies"),
]


def _nav_html(active: str, halt: dict | None = None, main_open: bool = True,
              left_extra: str = "", right_extra: str = "") -> str:
    """Unified header for all tabs.

    active     : which tab gets the .active class
    halt       : kill-switch state {halted, reason}; renders a banner when
                 halted (pass None on the RSPS tab — it has its own banner
                 with a resume button)
    main_open  : also emit the `<div class="main">` opener so the banner sits
                 inside the page column (RSPS passes False and keeps its own)
    left_extra : markup before the logo (RSPS pulse-dot)
    right_extra: markup after .header-left (RSPS badges)
    """
    tabs = "\n      ".join(
        f'<a class="tab-btn{" active" if key == active else ""}" '
        f'id="nav-{key}" href="{href if key != active else "#"}">{label}</a>'
        for key, label, href in _NAV_TABS
    )
    html = f"""<div class="header">
  <div class="header-left">
    {left_extra}<div class="logo">wealth<span>os</span></div>
    <div class="tab-nav">
      {tabs}
    </div>
  </div>
  {right_extra}
</div>"""
    if main_open:
        html += '\n<div class="main">'
        if halt and halt.get("halted"):
            reason = _html_escape(str(halt.get("reason", "")))
            html += f"""
  <div style="display:flex;align-items:center;gap:10px;flex-wrap:wrap;
              background:rgba(255,92,92,.08);border:1px solid rgba(255,92,92,.35);
              color:#ff5c5c;border-radius:6px;padding:10px 14px;margin-bottom:14px;
              font-size:12px">
    <span>🛑 <b>TRADING HALTED</b> — no signals will execute.</span>
    <span style="opacity:.75">{reason}</span>
    <a href="?" style="margin-left:auto;color:#ff5c5c;text-decoration:underline">Manage on RSPS tab</a>
  </div>"""
    return html


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

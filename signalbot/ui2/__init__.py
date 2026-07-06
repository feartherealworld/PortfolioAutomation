"""WealthOS Terminal — experimental ground-up UI (single-page app).

Lives side-by-side with the classic aurora-glass UI in signalbot/ui/:
the classic UI stays the default at every existing URL; the Terminal is
served only at ?action=next. Removing this package (or never visiting
the route) restores the status quo — nothing in ui/ is touched.
"""
from signalbot.ui2.terminal import *      # noqa: F401,F403
from signalbot.ui2 import terminal

__all__ = terminal.__all__

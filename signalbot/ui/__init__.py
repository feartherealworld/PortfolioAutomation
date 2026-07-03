"""Dashboard UI package — one module per tab, shared helpers in shared.py."""
from signalbot.ui.shared import *
from signalbot.ui.rsps import *
from signalbot.ui.history import *
from signalbot.ui.portfolio import *
from signalbot.ui.strategies_tab import *

from signalbot.ui import shared, rsps, history, portfolio, strategies_tab

__all__ = (shared.__all__ + rsps.__all__ + history.__all__
           + portfolio.__all__ + strategies_tab.__all__)

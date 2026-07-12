"""Deployed-version info.

signalbot/_build.py is written by modal_signal_bot.py on the DEPLOYING
machine (it has .git; the container does not) and ships with the image.
Absent file → local dev run.
"""

try:
    from signalbot._build import COMMIT, BUILT   # type: ignore
except ImportError:
    COMMIT, BUILT = "dev", ""

__all__ = ['COMMIT', 'BUILT']

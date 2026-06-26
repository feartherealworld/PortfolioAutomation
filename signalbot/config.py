import modal

__all__ = [
    'app',
    'image',
    'TRW_API_BASE',
    'ASSET_TO_TICKER',
    'SPOT_ASSETS',
    'MIN_TRADE_USD',
    'MAX_SLIPPAGE',
    'MAX_SINGLE_ORDER_USD',
    'signal_state',
    'DEFAULT_STRATEGIES',
    '_MS_PER_YEAR',
    'SIGNAL_RUNTIME_KEY',
]


app = modal.App("signal-bot")

image = (
    modal.Image.debian_slim(python_version="3.12")
    .pip_install(
        "requests",
        "hyperliquid-python-sdk",  # always latest — pinning caused more problems than it solved
        "eth-account",
        "fastapi[standard]",
    )
    # Include the whole signalbot package in the container so all modules
    # (endpoints, strategies, dashboard, …) are importable at runtime.
    .add_local_python_source("signalbot")
)


# ── TRW Signal Reader ─────────────────────────────────────────────────────────

TRW_API_BASE = "https://eden.therealworld.ag"


# ── Hyperliquid — unified account ─────────────────────────────────────────────

# Canonical perp ticker for each signal asset name
ASSET_TO_TICKER: dict[str, str] = {
    "ETH":       "ETH",
    "BTC":       "BTC",
    "HYPE":      "HYPE",
    "SOL":       "SOL",
    "DOGE":      "DOGE",
    "XRP":       "XRP",
    "PAXG/XAUT": "PAXG",
    "PAXG":      "PAXG",
    "XAUT":      "PAXG",
    "GOLD":      "PAXG",
    "USDC":      "USDC",
}

# Assets with a liquid spot market. Everything else falls back to 1x perp.
SPOT_ASSETS: frozenset[str] = frozenset({"ETH", "BTC", "HYPE", "SOL", "DOGE", "XRP"})

MIN_TRADE_USD        = 10.0
MAX_SLIPPAGE         = 0.03
MAX_SINGLE_ORDER_USD = 50_000


# ── State ─────────────────────────────────────────────────────────────────────

signal_state = modal.Dict.from_name("signal-bot-state", create_if_missing=True)


# ══════════════════════════════════════════════════════════════════════════════
# PORTFOLIO LAYER — total wealth across all strategies
# ══════════════════════════════════════════════════════════════════════════════
# Modal Dict keys:
#   portfolio_snapshots → [{ts, v}]            total portfolio value over time
#   cash_flows          → [{ts, amount, note}] deposits(+) / withdrawals(-)
#   strategies          → [{id, name, target_pct, status}]  strategy registry
# For now one strategy: RSPS at 100%. Total portfolio == RSPS account value.

DEFAULT_STRATEGIES = [
    {
        "id":          "rsps",
        "name":        "RSPS",
        "target_pct":  100.0,
        "status":      "active",
        "source":      "signal_bot",
    },
]


_MS_PER_YEAR = 365.0 * 86_400_000.0


# ══════════════════════════════════════════════════════════════════════════════
# SIGNAL STRATEGIES — generic external-signal (TradingView webhook) strategies
# ══════════════════════════════════════════════════════════════════════════════
# A "signal strategy" is an entry in the `strategies` registry with kind=="signal".
# Its config (name, asset, mode, direction, leverage, token, paper_capital) lives
# in `strategies` (rarely written, managed by the allocation editor). Its fast-
# changing runtime (open position, paper equity curve, signal log, processed
# alert ids) lives in a SEPARATE key `signal_runtime` so frequent webhook writes
# never race the editor's full-array overwrite of `strategies` (gotcha #7).

SIGNAL_RUNTIME_KEY = "signal_runtime"

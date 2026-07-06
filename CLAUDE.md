# WealthOS — context for AI assistants

Self-hosted portfolio command center on Modal + Hyperliquid, owned by **Tobiasz**
(GitHub: feartherealworld; the Windows user "marko" is him). It trades real money.
Read this before changing anything.

## What it is

- **RSPS autopilot** — reads Prof Adam's RSPS (Relative Strength Portfolio System)
  signal from TRW daily around 00:00 UK, parses allocations, rebalances the
  Hyperliquid unified account (spot preferred, 1x perp fallback, per-asset
  leverage opt-in). Autonomous 00:00–05:00 UK, Slack-approval otherwise.
- **WealthOS portfolio layer** — total-wealth tracking with deposit-aware math
  (Modified-Dietz TWR, XIRR, Sharpe/Sortino/vol/maxDD on a flow-adjusted index).
- **Strategy lab** — TradingView webhook → paper-trading engine per strategy
  (live routing intentionally stubbed until the Phase-3 allocator exists).

## Hard constraints (owner-set — do not violate)

1. **RSPS trading logic is frozen**: no changes to signal parsing
   (`signalbot/trw.py`), rebalance computation, or execution behavior
   (`signalbot/hyperliquid.py`, `signalbot/rebalance.py`) without Tobiasz's
   explicit approval of the exact diff. Tests and display-only additions are fine.
2. **No automatic kill triggers**: nothing may auto-deactivate a strategy
   (no "halt after X% drawdown"). Safety = pre-trade validation caps + Slack
   alerts + the *manual* kill switch (`signalbot/safety.py`). Halting is always
   the owner's decision.
3. **Deploys are owner-gated**: `modal deploy modal_signal_bot.py` updates the
   PROD app "signal-bot" that trades real money. Never deploy unasked. Never
   create a staging app naively — it would register duplicate trading crons
   with the same secrets.

## Architecture map

| Path | Role |
|---|---|
| `modal_signal_bot.py` | deploy entry (thin shim) |
| `signalbot/config.py` | Modal app/image, constants, `signal_state` Dict |
| `signalbot/trw.py` | signal fetch + parse *(frozen)* |
| `signalbot/hyperliquid.py` | account state, rebalance math, execution *(frozen)* |
| `signalbot/rebalance.py` | orchestration + schedule *(frozen)* |
| `signalbot/strategies.py` | paper engine, portfolio metrics, snapshots |
| `signalbot/auth.py` | dashboard sessions (cookie; async variants for web) |
| `signalbot/safety.py` | manual kill switch |
| `signalbot/endpoints.py` | ASGI web app, TV webhook, crons |
| `signalbot/ui/` | classic dashboard (aurora-glass), one module per tab |
| `signalbot/ui2/` | experimental "Terminal" SPA (branch `redesign/terminal`, `?action=next`) |
| `tests/` | pytest suite pinning parse/rebalance/paper/metrics/auth behavior |

State: Modal Dict `signal-bot-state`, JSON-string values, one logical record per
key (per-key namespacing avoids read-modify-write races — follow that pattern).

## Operational lore (learned the hard way)

- **Warm-container trap**: right after a deploy, an open dashboard tab can get
  one more request served by OLD code. Wait ~1 min before verifying via clicks.
- **Spot orders failing with an error that is just a quoted ticker (`'@156'`)**
  = SDK ticker map missing spot entries. `_sanitized_spot_meta()` exists because
  HL publishes broken spot metadata that crashes the SDK constructor.
- **Dust below one size-step** can't be fully sold; full-exit rounding falls
  back to ROUND_DOWN (see `tests/test_execute_full_exit_rounding.py`).
- `hyperliquid-python-sdk` is unpinned but the image pip layer is cached —
  container SDK version changes only when the image rebuilds.
- fastapi exists only in the Modal image; local dev needs `requirements-dev.txt`.
- UI verification pattern: stub HTTP server rendering the real HTML with fake
  JSON actions, driven by a preview browser (no prod deploys to test UI).

## Dev workflow

```
pip install -r requirements-dev.txt
python -m pytest tests/          # must stay green
python manage.py                 # owner's setup/token GUI
```

Git: `main` is the truth (tag `v2.0-wealthos`); `legacy-v1` preserves the
original bot; `redesign/terminal` holds the experimental UI. Secrets live in
`.env` (git-ignored, NEVER commit) and Modal secrets `signal-bot-secrets`.

## Where it's going

See [ROADMAP.md](ROADMAP.md) — Phase 3 (virtual sub-account ledger + netting
allocator, the prerequisite for multi-strategy live trading) is next, then
native quant strategies (TSMOM first; account < $25k so directional only).

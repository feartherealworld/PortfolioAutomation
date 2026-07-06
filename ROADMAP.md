# WealthOS Roadmap

Approved 2026-07-03. Phases 0–2 shipped (security hardening, session auth,
test suite, dashboard split, risk metrics, benchmark/drawdown charts,
aurora-glass UI). What remains:

## Phase 3 — Sub-account infrastructure (next, the big one)

The prerequisite for running multiple strategies on one Hyperliquid account.

- **`signalbot/ledger.py` — virtual sub-accounts.** Per-strategy state under its
  own Modal Dict key `ledger:{sid}`: `{capital_usd, realized_pnl, positions,
  equity_curve, hwm, last_rebalance}`. Capital slice = `target_pct` × account
  value — the registry field finally becomes enforced.
- **`signalbot/allocator.py` — netting engine.** Each strategy produces target
  positions `{asset: usd_notional}` → allocator sums across strategies → net
  target portfolio → diff vs actual account (reuse `compute_rebalance` /
  `execute_trades`) → attribute fills back to ledgers pro-rata. One execution
  path, kill-switch gated.
- **`signalbot/strategy_base.py` — strategy interface.**
  `compute_targets(ctx) -> dict[asset, weight]`; ctx provides candles/prices/
  funding. TV webhook strategies get an adapter; native strategies implement it
  directly and get backtesting for free (same function over history).
- **RSPS stays on its own execution path, unchanged.** The allocator manages
  only the other strategies' slices; RSPS's slice is reserved and accounted for
  by observation. Migrating RSPS into the allocator only with explicit approval.
- **TV webhook live routing**: live-mode strategies route through the allocator
  (replaces the "Phase 2 pending" stub in `tv_webhook`).
- **Guardrails — alert-first, never auto-deactivating** (owner constraint):
  per-strategy max allocation %, stale-price guard, per-cycle order cap;
  Slack warnings on drawdown/exposure with a link to the *manual* kill switch.
- **External/manual strategies**: registry `kind:"external"` with manually
  updated value — tracked in totals, excluded from netting.

## Phase 4 — Native quant strategies (< $25k account → directional)

Every new strategy launches in paper mode and is promoted to live from the
allocation editor only after it earns trust.

1. **Funding monitor** (read-only): track funding paid/received, Slack alerts
   on extremes.
2. **TSMOM** on BTC/ETH/SOL: daily bars, 30/90-day return-sign ensemble,
   vol-scaled sizing, long/flat. Low turnover survives fees at small size.
3. **Cross-sectional momentum rotation** (later): weekly top-K HL perps —
   validate fee drag in paper first.
4. **Vol-targeted trend variant** (optional, standalone — never an overlay
   on RSPS).

Deprioritized until ~$100k+: delta-neutral funding carry, market-making,
stat-arb pairs (fee/spread drag).

Supporting: `signalbot/backtest.py` running any Strategy over HL candle history
with fees+slippage, walk-forward split, results in the History tab.

## Phase 5 — Analytics

- Per-strategy Sharpe/Sortino/vol/maxDD/hit-rate, monthly returns table.
- Persistent fills log → realized slippage stats (today only in Slack).
- Fee + funding attribution.

## Standing decisions

- Capital scale assumption: **< $25k** → 2–4 concurrent directional strategies.
- Autonomy: full, within guardrails — but halting is always manual.
- RSPS (Relative Strength Portfolio System) logic is frozen; see CLAUDE.md.

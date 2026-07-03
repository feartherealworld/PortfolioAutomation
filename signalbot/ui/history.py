"""History tab — signal archive + backtest (isolated from live data)."""
import os
import json
import re
import time
from datetime import datetime, timezone

from signalbot.config import *
from signalbot.trw import *
from signalbot.hyperliquid import *
from signalbot.rebalance import *
from signalbot.strategies import *
from signalbot.ui.shared import *

__all__ = ['_fetch_history_signals', '_render_history', '_HISTORY_HTML']


# ══════════════════════════════════════════════════════════════════════════════
# HISTORY TAB — backend
# ══════════════════════════════════════════════════════════════════════════════

def _fetch_history_signals(limit: int = 600) -> list[dict]:
    """
    Paginate through TRW channel to collect ALL Portfolio Signal Update
    messages from Prof Adam, up to `limit` total messages scanned.
    Returns list sorted oldest → newest.
    """
    import requests as req
    PROF_ADAM  = os.environ.get("TRW_PROF_ADAM_USER_ID", "01GHHHWZE7Q77AKGWZDGC5PDCN")
    CHANNEL_ID = os.environ.get("TRW_SIGNAL_CHANNEL_ID", "01H83QAX979K9R7QTMH74ATR8C")
    TOKEN      = os.environ["TRW_SESSION_TOKEN"]
    signals    = []
    before_id  = None
    scanned    = 0

    while scanned < limit:
        body: dict = {"channel": CHANNEL_ID, "limit": 20, "sort": "Latest"}
        if before_id:
            body["before"] = before_id
        try:
            resp = req.post(
                "https://eden.therealworld.ag/messages/query",
                headers={
                    "x-session-token": TOKEN,
                    "Content-Type": "application/json",
                    "Origin": "https://app.jointherealworld.com",
                },
                json=body, timeout=15,
            )
            if resp.status_code == 401:
                raise RuntimeError("TRW session token expired")
            resp.raise_for_status()
            messages = resp.json().get("messages", [])
        except Exception as e:
            print(f"[history] fetch error: {e}")
            break

        if not messages:
            break

        for msg in messages:
            if (msg.get("author") == PROF_ADAM
                    and "Portfolio Signal Update" in msg.get("content", "")):
                signals.append(msg)

        scanned  += len(messages)
        before_id = messages[-1]["_id"]
        if len(messages) < 20:
            break   # no more pages

    signals.sort(key=lambda m: m.get("timestamp", 0))
    return signals


def _render_history(auth: str = "", halt: dict | None = None) -> str:
    """Build the History tab HTML with auth token injected."""
    token = os.environ.get("TRW_SESSION_TOKEN", "")
    auth_param = f"&auth={auth}" if auth else ""
    html = _HISTORY_HTML
    # Inject session token so JS can call Binance/CoinGecko directly
    html = html.replace("__TRW_TOKEN_PLACEHOLDER__", token)
    html = html.replace("__AUTH_PARAM_PLACEHOLDER__", auth_param)
    html = html.replace("__NAV_PLACEHOLDER__", _nav_html("history", halt))
    return html




# ══════════════════════════════════════════════════════════════════════════════
# HISTORY TAB — HTML
# ══════════════════════════════════════════════════════════════════════════════

_HISTORY_HTML = r"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1, maximum-scale=1">
<title>Signal Bot — History</title>
<script src="https://cdnjs.cloudflare.com/ajax/libs/Chart.js/4.4.1/chart.umd.js"></script>
<style>
  @import url('https://fonts.googleapis.com/css2?family=DM+Mono:wght@400;500&family=Syne:wght@400;600;700&display=swap');
  *,*::before,*::after{box-sizing:border-box;margin:0;padding:0}
  :root{
    --bg:#0a0a0a;--surface:#111111;--surface2:#1a1a1a;--surface3:#222222;
    --border:rgba(255,255,255,0.08);--border2:rgba(255,255,255,0.14);
    --text:#f0ede8;--muted:#6b6860;--muted2:#3e3c3a;
    --accent:#c8f563;--accent-dim:rgba(200,245,99,0.12);
    --red:#ff5c5c;--red-dim:rgba(255,92,92,0.12);
    --blue:#5b9cf6;--blue-dim:rgba(91,156,246,0.12);
    --amber:#f5a623;--amber-dim:rgba(245,166,35,0.12);
    --purple:#c084fc;--purple-dim:rgba(192,132,252,0.12);
    --font-mono:'DM Mono',monospace;--font-display:'Syne',sans-serif
  }
  body{background:var(--bg);color:var(--text);font-family:var(--font-mono);font-size:13px;line-height:1.6;min-height:100vh}
  .header{display:flex;align-items:center;justify-content:space-between;padding:16px 20px;border-bottom:1px solid var(--border);position:sticky;top:0;background:var(--bg);z-index:20;gap:10px}
  .header-left{display:flex;align-items:center;gap:12px}
  .logo{font-family:var(--font-display);font-size:15px;font-weight:700;letter-spacing:-0.02em}
  .logo span{color:var(--accent)}
  .tab-nav{display:flex;gap:1px;background:var(--border);border-radius:5px;overflow:hidden;padding:1px}
  .tab-btn{font-size:11px;font-family:var(--font-mono);letter-spacing:.06em;text-transform:uppercase;padding:5px 12px;border-radius:4px;cursor:pointer;color:var(--muted);border:none;background:none;transition:all .15s;white-space:nowrap;text-decoration:none;display:inline-block}
  .tab-btn.active{background:var(--surface2);color:var(--text)}
  .tab-btn:hover:not(.active){color:var(--text)}
  .main{padding:16px 20px;max-width:1200px}
  .config-panel{background:var(--surface);border:1px solid var(--border);border-radius:8px;padding:16px;margin-bottom:16px}
  .config-title{font-size:10px;letter-spacing:.12em;text-transform:uppercase;color:var(--muted);margin-bottom:12px}
  .config-grid{display:grid;grid-template-columns:repeat(auto-fit,minmax(170px,1fr));gap:12px;align-items:end}
  .config-field{display:flex;flex-direction:column;gap:5px}
  .config-label{font-size:10px;letter-spacing:.08em;text-transform:uppercase;color:var(--muted)}
  .config-input{background:var(--surface2);border:1px solid var(--border2);border-radius:5px;color:var(--text);font-family:var(--font-mono);font-size:13px;padding:7px 10px;outline:none;transition:border-color .15s}
  .config-input:focus{border-color:rgba(200,245,99,.4)}
  .config-actions{display:flex;gap:8px;flex-wrap:wrap;align-items:center;margin-top:12px}
  .config-note{font-size:11px;color:var(--muted);margin-top:10px;line-height:1.6;padding-top:10px;border-top:1px solid var(--border)}
  .btn{font-family:var(--font-mono);font-size:11px;letter-spacing:.06em;text-transform:uppercase;padding:8px 14px;border-radius:5px;cursor:pointer;border:1px solid var(--border2);background:var(--surface);color:var(--text);text-decoration:none;display:inline-flex;align-items:center;gap:6px;transition:all .15s;white-space:nowrap}
  .btn:hover:not(:disabled){background:var(--surface2)}
  .btn:disabled{opacity:.35;cursor:default;pointer-events:none}
  .btn-accent{background:var(--accent-dim);border-color:rgba(200,245,99,.35);color:var(--accent)}
  .btn-accent:hover:not(:disabled){background:rgba(200,245,99,.2)}
  .btn-export{background:var(--blue-dim);border-color:rgba(91,156,246,.35);color:var(--blue)}
  .btn-export:hover:not(:disabled){background:rgba(91,156,246,.2)}
  .metrics{display:grid;grid-template-columns:repeat(5,1fr);gap:1px;background:var(--border);border:1px solid var(--border);border-radius:8px;overflow:hidden;margin-bottom:16px}
  .metric{background:var(--surface);padding:14px 16px}
  .metric-label{font-size:10px;letter-spacing:.1em;text-transform:uppercase;color:var(--muted);margin-bottom:6px}
  .metric-value{font-family:var(--font-display);font-size:20px;font-weight:700;letter-spacing:-0.02em;line-height:1}
  .metric-sub{font-size:11px;color:var(--muted);margin-top:3px}
  .pos{color:var(--accent)}.neg{color:var(--red)}
  .chart-section{background:var(--surface);border:1px solid var(--border);border-radius:8px;margin-bottom:16px;overflow:hidden}
  .chart-header{display:flex;align-items:center;justify-content:space-between;padding:12px 14px;border-bottom:1px solid var(--border);flex-wrap:wrap;gap:8px}
  .panel-title{font-size:10px;letter-spacing:.1em;text-transform:uppercase;color:var(--muted);font-weight:500}
  .chart-controls{display:flex;gap:6px;flex-wrap:wrap;align-items:center}
  .ctrl-group{display:flex;gap:2px;background:var(--bg);border:1px solid var(--border);border-radius:4px;padding:2px}
  .ctrl-btn{font-size:11px;font-family:var(--font-mono);padding:4px 9px;border-radius:3px;cursor:pointer;color:var(--muted);border:none;background:none;transition:all .15s;letter-spacing:.04em;white-space:nowrap}
  .ctrl-btn.active{background:var(--surface2);color:var(--text)}
  .ctrl-btn:hover:not(.active){color:var(--text)}
  .chart-body{padding:14px}
  .chart-legend{display:flex;gap:14px;margin-bottom:10px;flex-wrap:wrap}
  .legend-item{display:flex;align-items:center;gap:5px;font-size:11px;color:var(--muted)}
  .legend-dot{width:8px;height:8px;border-radius:50%;flex-shrink:0}
  .chart-wrap{position:relative;width:100%;height:260px}
  .chart-note{font-size:10px;color:var(--muted2);padding:8px 14px;border-top:1px solid var(--border);line-height:1.6}
  /* kelly panel */
  .kelly-section{background:var(--surface);border:1px solid var(--border);border-radius:8px;margin-bottom:16px;overflow:hidden}
  .kelly-header{display:flex;align-items:center;justify-content:space-between;padding:12px 14px;border-bottom:1px solid var(--border);flex-wrap:wrap;gap:10px}
  .kelly-body{padding:16px}
  .kelly-fraction-row{display:flex;align-items:center;gap:14px;margin-bottom:18px;flex-wrap:wrap}
  .fraction-label{font-size:11px;color:var(--muted);white-space:nowrap}
  .fraction-slider{flex:1;min-width:160px;accent-color:var(--accent);height:4px;cursor:pointer}
  .fraction-value{font-family:var(--font-display);font-size:18px;font-weight:700;color:var(--accent);min-width:44px;text-align:right}
  .kelly-grid{display:grid;grid-template-columns:repeat(auto-fill,minmax(200px,1fr));gap:10px}
  .kelly-card{background:var(--surface2);border:1px solid var(--border);border-radius:6px;padding:13px 14px}
  .kelly-card-asset{font-family:var(--font-display);font-size:14px;font-weight:700;margin-bottom:8px;display:flex;align-items:center;gap:8px}
  .kelly-card-rows{display:flex;flex-direction:column;gap:5px}
  .kelly-row{display:flex;justify-content:space-between;font-size:11px}
  .kelly-key{color:var(--muted)}
  .kelly-val{font-family:var(--font-display);font-weight:600}
  .kelly-bar-wrap{height:3px;background:var(--border2);border-radius:2px;margin-top:9px;overflow:hidden}
  .kelly-bar{height:100%;border-radius:2px;transition:width .4s ease}
  .kelly-note{font-size:10px;color:var(--muted2);margin-top:14px;padding-top:10px;border-top:1px solid var(--border);line-height:1.6}
  .kelly-empty{padding:30px;text-align:center;color:var(--muted);font-size:12px}
  /* signal table */
  .table-section{background:var(--surface);border:1px solid var(--border);border-radius:8px;overflow:hidden;margin-bottom:16px}
  .table-header{display:flex;align-items:center;justify-content:space-between;padding:12px 14px;border-bottom:1px solid var(--border)}
  .sig-table{width:100%;border-collapse:collapse}
  .sig-table th{font-size:10px;letter-spacing:.08em;text-transform:uppercase;color:var(--muted);font-weight:500;padding:9px 14px;text-align:left;border-bottom:1px solid var(--border);white-space:nowrap}
  .sig-table th:not(:first-child){text-align:right}
  .sig-table td{padding:10px 14px;border-bottom:1px solid var(--border);font-size:12px;vertical-align:middle}
  .sig-table td:not(:first-child){text-align:right}
  .sig-table tr:last-child td{border-bottom:none}
  .sig-table tr:hover td{background:var(--surface2)}
  .alloc-pills{display:flex;gap:4px;flex-wrap:wrap;justify-content:flex-end}
  .pill{font-size:10px;padding:2px 6px;border-radius:3px;white-space:nowrap}
  .pill-eth{background:rgba(91,156,246,.15);color:#5b9cf6;border:1px solid rgba(91,156,246,.25)}
  .pill-btc{background:rgba(245,166,35,.15);color:#f5a623;border:1px solid rgba(245,166,35,.25)}
  .pill-hype{background:rgba(200,245,99,.12);color:#c8f563;border:1px solid rgba(200,245,99,.25)}
  .pill-sol{background:rgba(192,132,252,.15);color:#c084fc;border:1px solid rgba(192,132,252,.25)}
  .pill-paxg{background:rgba(255,215,0,.15);color:#ffd700;border:1px solid rgba(255,215,0,.25)}
  .pill-usdc{background:rgba(255,255,255,.06);color:var(--muted);border:1px solid var(--border2)}
  .pill-other{background:var(--surface3);color:var(--text);border:1px solid var(--border2)}
  .badge{font-size:10px;padding:2px 7px;border-radius:3px;font-family:var(--font-mono)}
  .badge-pos{background:var(--accent-dim);color:var(--accent);border:1px solid rgba(200,245,99,.25)}
  .badge-neg{background:var(--red-dim);color:var(--red);border:1px solid rgba(255,92,92,.25)}
  .badge-flat{background:var(--surface3);color:var(--muted);border:1px solid var(--border)}
  /* cloud equity banner */
  .cloud-banner{background:var(--surface);border:1px solid var(--border);border-radius:8px;padding:12px 14px;margin-bottom:16px;display:flex;align-items:center;gap:10px;font-size:11px;color:var(--muted)}
  .cloud-banner.cloud-ok{border-color:rgba(200,245,99,.2);background:rgba(200,245,99,.04)}
  .cloud-banner.cloud-warn{border-color:rgba(245,166,35,.2);background:rgba(245,166,35,.04)}
  /* loading */
  .loading-overlay{position:fixed;inset:0;background:rgba(10,10,10,.9);display:flex;flex-direction:column;align-items:center;justify-content:center;z-index:100;gap:14px}
  .loading-overlay.hidden{display:none}
  .loading-title{font-family:var(--font-display);font-size:14px;color:var(--text)}
  .loading-sub{font-size:11px;color:var(--muted);text-align:center;max-width:340px;line-height:1.6}
  .spinner{border:2px solid var(--border2);border-top-color:var(--accent);border-radius:50%;animation:spin .7s linear infinite}
  @keyframes spin{to{transform:rotate(360deg)}}
  .progress-bar{width:280px;height:2px;background:var(--border2);border-radius:1px;overflow:hidden}
  .progress-fill{height:100%;background:var(--accent);border-radius:1px;transition:width .4s ease}
  .empty{padding:44px 20px;text-align:center;color:var(--muted);font-size:12px}
  .status-ok{color:var(--accent)}.status-err{color:var(--red)}.status-warn{color:var(--amber)}
  .footer{padding:14px 20px;border-top:1px solid var(--border);display:flex;justify-content:space-between;font-size:11px;color:var(--muted);flex-wrap:wrap;gap:6px}
  @media(max-width:700px){
    .header,.main{padding:10px 14px}
    .metrics{grid-template-columns:repeat(2,1fr)}
    .metric{padding:12px}
    .metric-value{font-size:16px}
    .chart-wrap{height:200px}
    .sig-table .hm{display:none}
    .config-grid{grid-template-columns:1fr 1fr}
    .kelly-grid{grid-template-columns:1fr 1fr}
  }
  @media(max-width:480px){.logo{display:none}}
  @media(max-width:420px){.metrics{grid-template-columns:1fr}.config-grid{grid-template-columns:1fr}.kelly-grid{grid-template-columns:1fr}}
  ::-webkit-scrollbar{width:4px;height:4px}
  ::-webkit-scrollbar-thumb{background:var(--border2);border-radius:2px}
</style>
</head>
<body>

<div class="loading-overlay hidden" id="loadingOverlay">
  <div class="spinner" style="width:22px;height:22px"></div>
  <div class="loading-title" id="loadingTitle">Fetching signals…</div>
  <div class="progress-bar"><div class="progress-fill" id="progressFill"></div></div>
  <div class="loading-sub" id="loadingSub"></div>
</div>

__NAV_PLACEHOLDER__

  <!-- Cloud equity status banner -->
  <div class="cloud-banner" id="cloudBanner" style="display:none">
    <svg width="12" height="12" viewBox="0 0 12 12" fill="currentColor" style="flex-shrink:0"><path d="M9.5 5.5a3.5 3.5 0 10-6.86-.9A2.5 2.5 0 003 9.5h6a2 2 0 00.5-3.93V5.5z"/></svg>
    <span id="cloudBannerText"></span>
  </div>

  <div class="config-panel">
    <div class="config-title">Backtest Configuration</div>
    <div class="config-grid">
      <div class="config-field">
        <label class="config-label">Starting Balance (USD)</label>
        <input class="config-input" id="startBalance" type="number" value="10000" min="1" step="100">
      </div>
      <div class="config-field">
        <label class="config-label">Start Date (blank = all history)</label>
        <input class="config-input" id="startDate" type="date">
      </div>
      <div class="config-field">
        <label class="config-label">HL Taker Fee %</label>
        <input class="config-input" id="feeRate" type="number" value="0.035" min="0" max="1" step="0.005">
      </div>
    </div>
    <div class="config-actions">
      <button class="btn btn-accent" id="runBtn" onclick="runBacktest()">
        <svg width="10" height="10" viewBox="0 0 10 10" fill="currentColor"><path d="M1 1l8 4-8 4V1z"/></svg>
        Run Backtest
      </button>
      <button class="btn btn-export" id="exportBtn" onclick="exportCSV()" disabled>⬇ Export CSV</button>
      <span id="statusMsg" style="font-size:11px"></span>
    </div>
    <div class="config-note">
      Prices from <strong>Hyperliquid candleSnapshot API</strong> — same exchange, exact prices. 5m close at signal time for signal series; 1d open at 00:00 UTC for daily open series. Fees on rebalance notional. Slippage excluded.
      After running, backtest equity is pushed to cloud storage so it fills in history for everyone.
    </div>
  </div>

  <div class="metrics">
    <div class="metric"><div class="metric-label">Total Return</div><div class="metric-value" id="mTR">—</div><div class="metric-sub" id="mTRsub">–</div></div>
    <div class="metric"><div class="metric-label">CAGR</div><div class="metric-value" id="mCAGR">—</div><div class="metric-sub" id="mCAGRsub">annualised</div></div>
    <div class="metric"><div class="metric-label">Max Drawdown</div><div class="metric-value" id="mMDD">—</div><div class="metric-sub" id="mMDDsub">peak→trough</div></div>
    <div class="metric"><div class="metric-label">Win Rate</div><div class="metric-value" id="mWR">—</div><div class="metric-sub" id="mWRsub">periods up</div></div>
    <div class="metric"><div class="metric-label">Signals</div><div class="metric-value" id="mSig">—</div><div class="metric-sub" id="mSigsub">parsed</div></div>
  </div>

  <div class="chart-section">
    <div class="chart-header">
      <div class="panel-title">Equity Curve</div>
      <div class="chart-controls">
        <div class="ctrl-group" id="seriesTabs">
          <button class="ctrl-btn active" onclick="setSeries('actual',this)">Signal px</button>
          <button class="ctrl-btn" onclick="setSeries('barclose',this)">Daily open</button>
          <button class="ctrl-btn" onclick="setSeries('live',this)">Live</button>
          <button class="ctrl-btn" onclick="setSeries('merged',this)">Merged</button>
        </div>
        <div class="ctrl-group" id="rangeTabs">
          <button class="ctrl-btn" onclick="setRange('3m',this)">3m</button>
          <button class="ctrl-btn" onclick="setRange('6m',this)">6m</button>
          <button class="ctrl-btn" onclick="setRange('1y',this)">1y</button>
          <button class="ctrl-btn active" onclick="setRange('all',this)">All</button>
        </div>
      </div>
    </div>
    <div class="chart-body">
      <div class="chart-legend" id="chartLegend"></div>
      <div id="chartWrap" class="chart-wrap" style="display:none"><canvas id="equityChart"></canvas></div>
      <div id="noHistory" class="empty">Run the backtest above to generate the equity curve</div>
    </div>
    <div class="chart-note">
      <strong>Signal px</strong> — 5m close at exact signal time.
      <strong>Daily open</strong> — portfolio value if rebalanced at UTC 00:00 on the signal date.
      <strong>Live</strong> — real account snapshots stored in cloud (recorded hourly by bot).
      <strong>Merged</strong> — backtest fills in pre-deployment history, live takes over from bot launch.
    </div>
  </div>

  <!-- Kelly Criterion Panel -->
  <div class="kelly-section">
    <div class="kelly-header">
      <div class="panel-title">Kelly Criterion — Optimal Allocation per Asset</div>
      <div style="display:flex;align-items:center;gap:12px;flex-wrap:wrap">
        <div class="kelly-fraction-row" style="margin:0">
          <span class="fraction-label">Fraction:</span>
          <input type="range" class="fraction-slider" id="kellySlider" min="0.1" max="1.0" step="0.05" value="0.5" oninput="onFractionChange(this.value)">
          <span class="fraction-value" id="kellyFractionVal">0.5×</span>
        </div>
        <span style="font-size:10px;color:var(--muted2)">Half-Kelly is default · drag to adjust</span>
      </div>
    </div>
    <div class="kelly-body">
      <div id="kellyCards"><div class="kelly-empty">Run backtest to calculate Kelly fractions</div></div>
      <div class="kelly-note" id="kellyNote" style="display:none"></div>
    </div>
  </div>

  <div class="table-section">
    <div class="table-header">
      <div class="panel-title">Signal History</div>
      <span id="tableCount" style="font-size:11px;color:var(--muted)"></span>
    </div>
    <div id="tableBody"><div class="empty">No data — run backtest first</div></div>
  </div>

</div>

<div class="footer">
  <span>Prices: Hyperliquid candleSnapshot API · 5m candle close at signal time · 1d open at 00:00 UTC for daily open series</span>
  <span id="footerTime"></span>
</div>

<script>
// ── Injected server-side ──────────────────────────────────────────────────────
const _TRW_TOKEN = '__TRW_TOKEN_PLACEHOLDER__';

// ── Signal parser (JS port of trw_signal_reader.py) ───────────────────────────
function parseSignal(content) {
  const r = { allocations: [], no_change: false };
  const execM = content.match(/Executive Summary:([\s\S]+?)(?:Associated Data|$)/);
  if (execM && execM[1].toLowerCase().includes('no change')) r.no_change = true;
  const sigM = content.match(/(?:RSPS Signal|Risk-On Crypto Signal|\*\*Signal:\*\*)[\s\S]*?(?:Executive Summary|Associated Data|───|$)/);
  if (sigM) {
    const sec = sigM[0];
    const re = /\*?\*?(\d+(?:\.\d+)?)\s*%\s*(Spot|Gold|Leverage|Cash)?\s*\$?([\w/$]+)\*?\*?/gi;
    let m;
    while ((m = re.exec(sec)) !== null) {
      let [, pct, type, asset] = m;
      asset = asset.replace(/^\$+|\*+$/g, '').toUpperCase();
      if (asset === 'GOLD' || (type && type.toLowerCase() === 'gold')) {
        const gm = sec.match(/PAXG(?:\s*\/\s*\$?XAUT)?/i);
        asset = gm ? gm[0].toUpperCase().replace(/[\s$]/g,'') : 'PAXG/XAUT';
        type = 'Gold';
      } else if (asset === 'CASH' || (type && type.toLowerCase() === 'cash')) {
        type = 'Cash'; asset = 'USDC';
      } else {
        type = type ? type[0].toUpperCase()+type.slice(1).toLowerCase() : 'Spot';
      }
      r.allocations.push({ percent: parseFloat(pct), type, asset });
    }
  }
  return r;
}

// ── Price fetching — Hyperliquid candleSnapshot API ───────────────────────────
//
// All prices come from https://api.hyperliquid.xyz/info (POST, candleSnapshot).
// Coin names match HL perp tickers: ETH, BTC, HYPE, SOL, PAXG, etc.
// No Binance or CoinGecko dependency — prices are exactly what HL traded at.
//
// HL candle fields:
//   t = open time ms,  T = close time ms
//   o = open,  h = high,  l = low,  c = close,  v = volume
//
// barClose=false → close of the 5m candle containing the signal timestamp
//                  (what HL was trading at the exact minute of the signal)
// barClose=true  → open of the 1d candle at 00:00 UTC on the signal date
//                  (what HL was trading at midnight = "daily open" benchmark)

const HL_API = 'https://api.hyperliquid.xyz/info';
const priceCache = {};

// Canonical HL ticker for each asset name used in signals
const HL_TICKER = {
  'ETH':'ETH','BTC':'BTC','HYPE':'HYPE','SOL':'SOL',
  'DOGE':'DOGE','XRP':'XRP','BNB':'BNB','AVAX':'AVAX',
  'LINK':'LINK','UNI':'UNI','AAVE':'AAVE','ARB':'ARB',
  'PAXG':'PAXG','PAXG/XAUT':'PAXG','XAUT':'PAXG',
};

// Returns midnight UTC timestamp (ms) of the day containing tsMs
function midnightUtc(tsMs) {
  const d = new Date(tsMs);
  return Date.UTC(d.getUTCFullYear(), d.getUTCMonth(), d.getUTCDate());
}

async function hlCandle(coin, interval, startTime, endTime) {
  const ck = `${coin}_${interval}_${startTime}`;
  if (priceCache[ck] !== undefined) return priceCache[ck];
  try {
    const r = await fetch(HL_API, {
      method: 'POST',
      headers: {'Content-Type': 'application/json'},
      body: JSON.stringify({
        type: 'candleSnapshot',
        req: { coin, interval, startTime, endTime },
      }),
    });
    if (!r.ok) return null;
    const candles = await r.json();
    if (!Array.isArray(candles) || !candles.length) return null;
    priceCache[ck] = candles;
    return candles;
  } catch { return null; }
}

/**
 * Get HL price for an asset at a given timestamp.
 *
 * barClose=false: close of the 5m candle that contains tsMs.
 *   Falls back to 15m → 1h if 5m unavailable.
 *
 * barClose=true: open of the 1d candle at 00:00 UTC on the signal date.
 *   Falls back to open of the 1h candle at 00:00 UTC.
 */
async function getHlPrice(asset, tsMs, barClose=false) {
  const coin = HL_TICKER[asset] || asset.split('/')[0].toUpperCase();
  if (coin === 'USDC') return 1.0;

  if (barClose) {
    const midnight = midnightUtc(tsMs);
    // Try 1d candle first (most accurate daily open), then 1h
    for (const [iv, winMs] of [['1d', 86_400_000], ['1h', 3_600_000]]) {
      const candles = await hlCandle(coin, iv, midnight, midnight + winMs);
      if (candles && candles[0]) return parseFloat(candles[0].o); // open = price at 00:00
    }
    return null;
  }

  // Signal price: close of candle containing tsMs
  for (const [iv, barMs] of [['5m', 300_000], ['15m', 900_000], ['1h', 3_600_000]]) {
    const candleStart = Math.floor(tsMs / barMs) * barMs;
    const candles = await hlCandle(coin, iv, candleStart, candleStart + barMs);
    if (candles) {
      // Find the candle that is fully closed and contains tsMs
      const closed = candles.filter(c => parseInt(c.T) <= tsMs + barMs);
      if (closed.length) return parseFloat(closed[closed.length - 1].c);
    }
  }
  return null;
}

async function getPrice(asset, tsMs, barClose=false) {
  const a = asset.split('/')[0];
  if (a === 'USDC' || a === 'CASH') return 1.0;
  return getHlPrice(asset, tsMs, barClose);
}

async function fetchAllPrices(assets, tsMs, barClose) {
  const prices = {};
  await Promise.all(assets.map(async a => {
    const p = await getPrice(a, tsMs, barClose);
    if (p !== null) prices[a] = p;
  }));
  return prices;
}

// ── Fee model ─────────────────────────────────────────────────────────────────
function calcFee(prevAllocs,newAllocs,equity,feeRate) {
  const prev=Object.fromEntries(prevAllocs.map(a=>[a.asset,a.percent/100]));
  const next=Object.fromEntries(newAllocs.map(a=>[a.asset,a.percent/100]));
  const assets=new Set([...Object.keys(prev),...Object.keys(next)]);
  let buyNotional=0;
  for (const a of assets){const delta=(next[a]||0)-(prev[a]||0);if(delta>0)buyNotional+=delta*equity;}
  return buyNotional*2*feeRate;
}

// ── Cloud equity ──────────────────────────────────────────────────────────────
let _liveSnaps = [];   // [{ts,v}] from cloud
async function loadCloudEquity() {
  const banner=document.getElementById('cloudBanner');
  const bannerText=document.getElementById('cloudBannerText');
  try {
    const authParam = window._auth ? '&auth='+encodeURIComponent(window._auth) : '';
    const r=await fetch('?action=equity_history'+authParam);
    if (!r.ok) throw new Error('HTTP '+r.status);
    const data=await r.json();
    if (Array.isArray(data)&&data.length>0) {
      _liveSnaps=data;
      banner.className='cloud-banner cloud-ok';
      banner.style.display='flex';
      const first=new Date(_liveSnaps[0].ts).toISOString().slice(0,10);
      const last=new Date(_liveSnaps[_liveSnaps.length-1].ts).toISOString().slice(0,10);
      bannerText.textContent=`☁ Cloud equity loaded — ${_liveSnaps.length} snapshots · ${first} → ${last}`;
    } else {
      banner.className='cloud-banner cloud-warn';
      banner.style.display='flex';
      bannerText.textContent='☁ Cloud equity: no snapshots yet — deploy the bot to start accumulating hourly data';
    }
  } catch(e) {
    banner.className='cloud-banner cloud-warn';
    banner.style.display='flex';
    bannerText.textContent='☁ Cloud equity unavailable ('+e.message+')';
  }
}
async function pushBacktestToCloud(timeline) {
  if (window._btPushed) return;
  window._btPushed = true;
  try {
    const points = timeline.map(t => ({ts: t.ts, v: t.equity}));
    const authParam = window._auth ? '&auth='+encodeURIComponent(window._auth) : '';
    const encoded  = encodeURIComponent(JSON.stringify({points}));
    const r = await fetch('?action=equity_store_backtest'+authParam+'&points='+encoded);
    if (r.ok) console.log('[history] backtest equity pushed to cloud');
  } catch(e) { console.warn('[history] cloud push failed:', e); }
}

// ── Backtest engine ───────────────────────────────────────────────────────────
let _result = null;
async function runBacktest() {
  const startBalance=parseFloat(document.getElementById('startBalance').value)||10000;
  const startDateStr=document.getElementById('startDate').value;
  const feeRate=(parseFloat(document.getElementById('feeRate').value)||0.035)/100;
  setStatus('','');
  document.getElementById('exportBtn').disabled=true;
  window._btPushed=false;
  showOverlay(true);
  setProgress(0,'Fetching signals from TRW…','');

  let rawSignals=[];
  try {
    const authParam=window._auth?'&auth='+encodeURIComponent(window._auth):'';
    const pr=await fetch('?action=history_signals'+authParam);
    if (pr.ok){const d=await pr.json();if(Array.isArray(d)&&d.length>0)rawSignals=d;}
  } catch {}
  if (!rawSignals.length) {
    const token=_TRW_TOKEN||localStorage.getItem('trw_token')||'';
    if (!token){hideOverlay();promptToken();return;}
    try{rawSignals=await fetchTRWSignals(token);}
    catch(e){hideOverlay();if(e.message==='TOKEN_EXPIRED'){promptToken();return;}setStatus('err','Fetch error: '+e.message);return;}
  }
  if (!rawSignals.length){hideOverlay();setStatus('warn','No signals found.');return;}

  rawSignals.sort((a,b)=>a.timestamp-b.timestamp);
  const startMs=startDateStr?new Date(startDateStr+'T00:00:00Z').getTime():0;
  const signals=rawSignals.filter(m=>m.timestamp>=startMs);
  setProgress(12,`${signals.length} signals loaded — fetching prices…`,'Using Hyperliquid candleSnapshot API');

  const timeline=[];
  let equity=startBalance, equityBC=startBalance;
  let prevAllocs=[], prevPrices={}, prevPricesBC={};
  // Track per-asset returns for Kelly calculation
  const assetReturns = {};   // asset → [return_pct per period when held]

  for (let i=0;i<signals.length;i++) {
    const msg=signals[i];
    const parsed=parseSignal(msg.content);
    const ts=msg.timestamp;
    const date=new Date(ts).toISOString().slice(0,10);
    const timeStr=new Date(ts).toISOString().slice(11,16);
    setProgress(12+Math.floor((i/signals.length)*80),`Signal ${i+1}/${signals.length} · ${date}`,parsed.allocations.map(a=>a.percent+'%'+a.asset).join(' · '));

    const assets=parsed.allocations.map(a=>a.asset);
    const [sigPrices,bcPrices]=await Promise.all([
      fetchAllPrices(assets,ts,false),
      fetchAllPrices(assets,ts,true),
    ]);

    let periodReturn=null;
    if (prevAllocs.length>0) {
      let newEq=0;
      for (const a of prevAllocs) {
        const prev=prevPrices[a.asset], curr=sigPrices[a.asset];
        const portion = equity*(a.percent/100);
        if (a.asset==='USDC'||!prev||!curr){newEq+=portion;}
        else {
          const assetRet=(curr/prev)-1;
          newEq+=portion*(1+assetRet);
          // Record per-asset return for Kelly (weighted by allocation)
          const key=a.asset.split('/')[0];
          if (!assetReturns[key]) assetReturns[key]=[];
          assetReturns[key].push({ret:assetRet, pct:a.percent/100});
        }
      }
      if (!parsed.no_change) newEq-=calcFee(prevAllocs,parsed.allocations,newEq,feeRate);
      periodReturn=(newEq-equity)/equity;
      equity=newEq;

      let newEqBC=0;
      for (const a of prevAllocs) {
        const prev=prevPricesBC[a.asset], curr=bcPrices[a.asset];
        if (a.asset==='USDC'||!prev||!curr){newEqBC+=equityBC*(a.percent/100);}
        else{newEqBC+=equityBC*(a.percent/100)*(curr/prev);}
      }
      if (!parsed.no_change) newEqBC-=calcFee(prevAllocs,parsed.allocations,newEqBC,feeRate);
      equityBC=newEqBC;
    }

    timeline.push({ts,date,time:timeStr,allocations:parsed.allocations,no_change:parsed.no_change,
      equity:+equity.toFixed(2),equity_bc:+equityBC.toFixed(2),period_return:periodReturn,
      prices:sigPrices,prices_bc:bcPrices});

    if (!parsed.no_change&&parsed.allocations.length>0) {
      prevAllocs=parsed.allocations; prevPrices=sigPrices; prevPricesBC=bcPrices;
    }
  }

  setProgress(95,'Computing stats & Kelly…','');

  // Build series
  const eqSeries=[{date:timeline[0]?.date||'',value:startBalance},...timeline.map(t=>({date:t.date,value:t.equity}))];
  const bcSeries=[{date:timeline[0]?.date||'',value:startBalance},...timeline.map(t=>({date:t.date,value:t.equity_bc}))];
  // Live series from cloud snapshots
  const liveSeries=_liveSnaps.map(s=>({date:new Date(s.ts).toISOString().slice(0,10),value:s.v,ts:s.ts}));
  // Merged: backtest up to first live snapshot, then live
  let mergedSeries;
  if (liveSeries.length>0) {
    const liveStart=liveSeries[0].date;
    const btPart=eqSeries.filter(p=>p.date<liveStart);
    mergedSeries=[...btPart,...liveSeries];
  } else {
    mergedSeries=eqSeries;
  }

  const finalEq=timeline[timeline.length-1]?.equity??startBalance;
  const totalReturn=(finalEq-startBalance)/startBalance;
  const t0=new Date(eqSeries[0].date+'T00:00:00Z'), t1=new Date(eqSeries[eqSeries.length-1].date+'T00:00:00Z');
  const years=Math.max((t1-t0)/(365.25*86400000),0.01);
  const cagr=Math.pow(finalEq/startBalance,1/years)-1;
  let peak=startBalance,mdd=0;
  for (const pt of eqSeries){if(pt.value>peak)peak=pt.value;const dd=(peak-pt.value)/peak;if(dd>mdd)mdd=dd;}
  const returnsOnly=timeline.filter(t=>t.period_return!==null);
  const wins=returnsOnly.filter(t=>t.period_return>0).length;
  const winRate=returnsOnly.length?wins/returnsOnly.length:null;

  // Kelly calculation per asset
  const kellyData=computeKelly(assetReturns);

  _result={timeline,eqSeries,bcSeries,liveSeries,mergedSeries,startBalance,
    totalReturn,cagr,mdd,winRate,years,kellyData,assetReturns};

  setProgress(100,'Done!','');
  setTimeout(async ()=>{
    hideOverlay();
    renderMetrics();
    renderChart();
    renderKelly(0.5);
    renderTable();
    document.getElementById('exportBtn').disabled=false;
    setStatus('ok',`${timeline.length} signals · ${eqSeries[0]?.date||'?'} → ${eqSeries[eqSeries.length-1]?.date||'?'}`);
    // History is backtest-only — results stay in this tab and are NOT persisted
    // to the live equity/portfolio snapshots (which the RSPS + WealthOS dashboards
    // read). Pushing backtest curves into cloud storage previously polluted them.
  },250);
}

// ── Kelly Criterion ───────────────────────────────────────────────────────────
/**
 * Full Kelly per asset using the continuous/log-optimal formula.
 * For each asset, we collect all periods where it was held with some allocation,
 * compute the distribution of returns, then calculate:
 *
 *   Full Kelly f* = E[r] / E[r^2]   (Kelly for log-normal returns, single asset)
 *
 * This is equivalent to maximising expected log growth.
 * For discrete outcomes: f* = (p*b - q) / b  where b=avg_win/avg_loss
 * We use both and show the geometric mean formula as primary.
 *
 * Also computes: win rate, avg win, avg loss, Sharpe-like ratio, expected value
 */
function computeKelly(assetReturns) {
  const results = {};
  for (const [asset, records] of Object.entries(assetReturns)) {
    if (records.length < 3) continue;   // need minimum sample
    const rets = records.map(r => r.ret);
    const n    = rets.length;
    const wins = rets.filter(r=>r>0);
    const losses = rets.filter(r=>r<0);
    if (!wins.length || !losses.length) continue;

    const p  = wins.length / n;                             // win probability
    const q  = 1 - p;
    const b  = wins.reduce((s,r)=>s+r,0)/wins.length;      // avg win (fraction)
    const a  = Math.abs(losses.reduce((s,r)=>s+r,0)/losses.length); // avg loss magnitude
    const EV = p*b - q*a;                                   // expected value per period

    // Kelly fraction: f* = (p*b - q*a) / b  (classical)
    const kellyClassic = EV / b;

    // Log-optimal Kelly: f* = μ/σ² where μ=mean(r), σ²=var(r)
    const mu  = rets.reduce((s,r)=>s+r,0)/n;
    const variance = rets.reduce((s,r)=>s+(r-mu)**2,0)/n;
    const kellyLog = variance > 0 ? mu/variance : 0;

    // Use the more conservative of the two (they diverge when distribution is skewed)
    const kellyRaw = Math.min(kellyClassic, kellyLog);
    // Cap at 1.0 (never recommend going all-in based on small sample)
    const kelly = Math.max(0, Math.min(1, kellyRaw));

    // Geometric mean of returns (compound growth per period)
    const geoMean = Math.exp(rets.reduce((s,r)=>s+Math.log(1+r),0)/n) - 1;

    // Sortino-style ratio: mean / downside_std
    const downDev = Math.sqrt(losses.reduce((s,r)=>s+r*r,0)/losses.length);
    const sortino = downDev > 0 ? mu / downDev : null;

    results[asset] = {
      n, p, q, b, a, EV,
      kellyClassic: Math.max(0,kellyClassic),
      kellyLog: Math.max(0,kellyLog),
      kelly,      // conservative kelly (pre-fraction)
      geoMean,
      sortino,
      mu, variance,
    };
  }
  return results;
}

let _kellyFraction = 0.5;
function onFractionChange(val) {
  _kellyFraction=parseFloat(val);
  document.getElementById('kellyFractionVal').textContent=val+'×';
  if (_result?.kellyData) renderKelly(_kellyFraction);
}

const ASSET_COLORS = {
  ETH:'#5b9cf6',BTC:'#f5a623',HYPE:'#c8f563',SOL:'#c084fc',
  PAXG:'#ffd700',USDC:'#6b6860',DEFAULT:'#f0ede8'
};
function assetColor(a){return ASSET_COLORS[a.split('/')[0]]||ASSET_COLORS.DEFAULT;}

function renderKelly(fraction) {
  const container=document.getElementById('kellyCards');
  const noteEl=document.getElementById('kellyNote');
  const kd=_result?.kellyData;
  if (!kd||!Object.keys(kd).length){
    container.innerHTML='<div class="kelly-empty">Not enough signal history to calculate Kelly fractions (need ≥3 periods per asset)</div>';
    noteEl.style.display='none';
    return;
  }

  const cards=Object.entries(kd).map(([asset,k])=>{
    const fk=+(k.kelly*fraction*100).toFixed(1);         // fractional kelly %
    const fkRaw=k.kelly*fraction;
    const color=assetColor(asset);
    const barW=Math.min(100,fk);
    const barColor=fk>80?'#ff5c5c':fk>50?'#f5a623':color;
    const sampleNote=k.n<10?`<span style="color:var(--amber);font-size:10px"> ⚠ n=${k.n}</span>`:'';

    return `<div class="kelly-card">
      <div class="kelly-card-asset">
        <span style="width:8px;height:8px;border-radius:50%;background:${color};display:inline-block;flex-shrink:0"></span>
        ${asset}${sampleNote}
      </div>
      <div class="kelly-card-rows">
        <div class="kelly-row"><span class="kelly-key">Fractional Kelly (${fraction}×)</span><span class="kelly-val" style="color:${barColor};font-size:16px">${fk}%</span></div>
        <div class="kelly-row"><span class="kelly-key">Full Kelly</span><span class="kelly-val">${(k.kelly*100).toFixed(1)}%</span></div>
        <div class="kelly-row"><span class="kelly-key">Win rate</span><span class="kelly-val">${(k.p*100).toFixed(0)}% <span style="font-size:10px;color:var(--muted)">(${Math.round(k.p*k.n)}/${k.n})</span></span></div>
        <div class="kelly-row"><span class="kelly-key">Avg win</span><span class="kelly-val pos">+${(k.b*100).toFixed(2)}%</span></div>
        <div class="kelly-row"><span class="kelly-key">Avg loss</span><span class="kelly-val neg">-${(k.a*100).toFixed(2)}%</span></div>
        <div class="kelly-row"><span class="kelly-key">Expected value/period</span><span class="kelly-val ${k.EV>=0?'pos':'neg'}">${k.EV>=0?'+':''}${(k.EV*100).toFixed(3)}%</span></div>
        <div class="kelly-row"><span class="kelly-key">Geo mean/period</span><span class="kelly-val ${k.geoMean>=0?'pos':'neg'}">${k.geoMean>=0?'+':''}${(k.geoMean*100).toFixed(3)}%</span></div>
        ${k.sortino!==null?`<div class="kelly-row"><span class="kelly-key">Sortino ratio</span><span class="kelly-val">${k.sortino.toFixed(2)}</span></div>`:''}
      </div>
      <div class="kelly-bar-wrap"><div class="kelly-bar" style="width:${barW}%;background:${barColor}"></div></div>
    </div>`;
  }).join('');

  container.innerHTML=cards;

  // Summary note
  const allKelly=Object.entries(kd).map(([a,k])=>({asset:a,fk:k.kelly*fraction}));
  const totalKelly=allKelly.reduce((s,x)=>s+x.fk,0);
  const topAsset=allKelly.sort((a,b)=>b.fk-a.fk)[0];
  noteEl.style.display='block';
  noteEl.innerHTML=`
    <strong>How to use:</strong> Fractional Kelly = ${fraction}× Full Kelly.
    Full Kelly maximises long-run log-growth but risks large drawdowns on small samples.
    Half-Kelly (0.5×) is the standard practitioner choice — it gives ~75% of the maximum growth rate
    with roughly half the variance. Quarter-Kelly (0.25×) for extra caution.
    Total allocation summing all fractional Kellys: <strong>${(totalKelly*100).toFixed(1)}%</strong>
    ${totalKelly>1?'— this exceeds 100%, which means assets are correlated or sample is too small; apply additional scaling.':''}<br>
    <strong>Caveats:</strong> Based on ${_result?.timeline?.length||0} signals using simulated backtest returns.
    Kelly assumes independent, identically distributed returns — RSPS periods are <em>not</em> i.i.d.
    Treat these as directional sizing signals, not precise allocations.
    Always cross-reference with current signal allocations and your own risk tolerance.
  `;
  noteEl.style.color='var(--muted)';
  noteEl.style.fontSize='11px';
  noteEl.style.lineHeight='1.6';
}

// ── Chart ─────────────────────────────────────────────────────────────────────
let chart=null, currentSeries='actual', currentRange='all';
function filterRange(arr,range) {
  if(range==='all')return arr;
  const days={'3m':90,'6m':180,'1y':365}[range];
  const cut=new Date();cut.setDate(cut.getDate()-days);
  const cs=cut.toISOString().slice(0,10);
  return arr.filter(p=>p.date>=cs);
}
function buildLegend(showA,showB,showL,showM) {
  let h='';
  if(showA)h+='<div class="legend-item"><div class="legend-dot" style="background:#c8f563"></div>Signal 5m close</div>';
  if(showB)h+='<div class="legend-item"><div class="legend-dot" style="background:#c084fc"></div>Daily open (00:00 UTC)</div>';
  if(showL)h+='<div class="legend-item"><div class="legend-dot" style="background:#5b9cf6"></div>Live (cloud)</div>';
  if(showM)h+='<div class="legend-item"><div class="legend-dot" style="background:#f5a623"></div>Merged</div>';
  document.getElementById('chartLegend').innerHTML=h;
}
function renderChart() {
  const r=_result; if(!r)return;
  const showA=currentSeries==='actual';
  const showB=currentSeries==='barclose';
  const showL=currentSeries==='live';
  const showM=currentSeries==='merged';
  const fa=showA?filterRange(r.eqSeries,currentRange):[];
  const fb=showB?filterRange(r.bcSeries,currentRange):[];
  const fl=showL?filterRange(r.liveSeries,currentRange):[];
  const fm=showM?filterRange(r.mergedSeries,currentRange):[];
  buildLegend(showA&&fa.length>1,showB&&fb.length>1,showL&&fl.length>1,showM&&fm.length>1);
  const noH=document.getElementById('noHistory'),wrap=document.getElementById('chartWrap');
  const activeArr=[fa,fb,fl,fm].find(a=>a.length>=2);
  if(!activeArr){noH.style.display='block';wrap.style.display='none';return;}
  noH.style.display='none';wrap.style.display='block';
  const allDates=[...new Set([...fa,...fb,...fl,...fm].map(p=>p.date))].sort();
  const labels=allDates.map(d=>{const dt=new Date(d+'T00:00:00Z');return dt.toLocaleDateString('en-GB',{day:'numeric',month:'short',year:allDates.length>300?'2-digit':undefined});});
  const toMap=a=>Object.fromEntries(a.map(p=>[p.date,p.value]));
  const aMap=toMap(fa),bMap=toMap(fb),lMap=toMap(fl),mMap=toMap(fm);
  const datasets=[];
  const mkDs=(data,label,color,dashed,fill)=>{
    const up=data.filter(v=>v!==null);
    const isUp=up.length<2||up[up.length-1]>=up[0];
    const c=color==='auto'?(isUp?'#c8f563':'#ff5c5c'):color;
    return{label,data,borderColor:c,backgroundColor:c.replace(')',',0.05)').replace('rgb','rgba'),
      borderWidth:1.5,borderDash:dashed?[4,3]:undefined,
      pointRadius:allDates.length>80?0:3,pointHoverRadius:5,fill,tension:.35,spanGaps:true};
  };
  if(showA&&fa.length>=2)datasets.push(mkDs(allDates.map(d=>aMap[d]??null),'Signal px','auto',false,true));
  if(showB&&fb.length>=2)datasets.push(mkDs(allDates.map(d=>bMap[d]??null),'Daily open','#c084fc',true,true));
  if(showL&&fl.length>=2)datasets.push(mkDs(allDates.map(d=>lMap[d]??null),'Live','#5b9cf6',false,true));
  if(showM&&fm.length>=2)datasets.push(mkDs(allDates.map(d=>mMap[d]??null),'Merged','#f5a623',false,true));
  if(chart){chart.destroy();chart=null;}
  chart=new Chart(document.getElementById('equityChart'),{
    type:'line',data:{labels,datasets},
    options:{responsive:true,maintainAspectRatio:false,interaction:{mode:'index',intersect:false},
      plugins:{legend:{display:false},tooltip:{backgroundColor:'#1a1a1a',borderColor:'rgba(255,255,255,.1)',borderWidth:1,
        titleColor:'#555',bodyColor:'#f0ede8',titleFont:{family:'DM Mono',size:11},bodyFont:{family:'DM Mono',size:12},
        callbacks:{label:ctx=>` ${ctx.dataset.label}:  `+fmtDollar(ctx.parsed.y)}}},
      scales:{
        x:{grid:{color:'rgba(255,255,255,.04)'},ticks:{color:'#555',font:{family:'DM Mono',size:11},maxTicksLimit:8},border:{display:false}},
        y:{position:'right',grid:{color:'rgba(255,255,255,.04)'},ticks:{color:'#555',font:{family:'DM Mono',size:11},callback:v=>'$'+v.toLocaleString()},border:{display:false}}
      }}
  });
}
function setSeries(s,el){currentSeries=s;document.querySelectorAll('#seriesTabs .ctrl-btn').forEach(b=>b.classList.remove('active'));el.classList.add('active');renderChart();}
function setRange(r,el){currentRange=r;document.querySelectorAll('#rangeTabs .ctrl-btn').forEach(b=>b.classList.remove('active'));el.classList.add('active');renderChart();}

// ── Metrics ───────────────────────────────────────────────────────────────────
function fmtDollar(v){return'$'+parseFloat(v).toLocaleString('en-US',{minimumFractionDigits:2,maximumFractionDigits:2});}
function fmtPct(v,d=2){return(v>=0?'+':'')+(v*100).toFixed(d)+'%';}
function renderMetrics() {
  const r=_result;if(!r)return;
  const set=(id,txt,cls)=>{const el=document.getElementById(id);el.textContent=txt;if(cls)el.className='metric-value '+cls;};
  set('mTR',fmtPct(r.totalReturn),r.totalReturn>=0?'pos':'neg');
  document.getElementById('mTRsub').textContent=fmtDollar(r.eqSeries[r.eqSeries.length-1].value)+' final';
  set('mCAGR',fmtPct(r.cagr),r.cagr>=0?'pos':'neg');
  document.getElementById('mCAGRsub').textContent=r.years.toFixed(1)+'yr period';
  set('mMDD','-'+(r.mdd*100).toFixed(1)+'%','neg');
  set('mWR',r.winRate!==null?(r.winRate*100).toFixed(0)+'%':'N/A',r.winRate>=.5?'pos':'neg');
  const retN=r.timeline.filter(t=>t.period_return!==null);
  document.getElementById('mWRsub').textContent=`${retN.filter(t=>t.period_return>0).length} / ${retN.length} periods`;
  set('mSig',r.timeline.length,'metric-value');
  document.getElementById('mSigsub').textContent=r.timeline.filter(t=>Object.keys(t.prices).length>0).length+' with price data';
}

// ── Table ─────────────────────────────────────────────────────────────────────
const PCLS={'ETH':'pill-eth','BTC':'pill-btc','HYPE':'pill-hype','SOL':'pill-sol','PAXG':'pill-paxg','PAXG/XAUT':'pill-paxg','USDC':'pill-usdc'};
function pillCls(a){return PCLS[a.split('/')[0]]||'pill-other';}
function renderTable() {
  const r=_result;if(!r||!r.timeline.length)return;
  document.getElementById('tableCount').textContent=r.timeline.length+' signals';
  const rows=[...r.timeline].reverse().map(t=>{
    const pills=t.allocations.map(a=>`<span class="pill ${pillCls(a.asset)}">${a.percent}% ${a.asset}</span>`).join('');
    const pr=t.period_return!==null?`<span class="badge ${t.period_return>0.001?'badge-pos':t.period_return<-0.001?'badge-neg':'badge-flat'}">${fmtPct(t.period_return)}</span>`:'<span style="color:var(--muted2)">—</span>';
    const ncBadge=t.no_change?'<span class="badge badge-flat" style="margin-left:4px;font-size:10px">no chg</span>':'';
    const pxStr=Object.entries(t.prices).filter(([k])=>k!=='USDC').map(([k,v])=>`<span style="color:var(--muted);font-size:11px">${k.split('/')[0]}:$${v>=1000?v.toFixed(0):v>=1?v.toFixed(2):v.toFixed(4)}</span>`).join('  ');
    return`<tr>
      <td><span style="font-family:var(--font-display);font-weight:600">${t.date}</span> <span style="color:var(--muted);font-size:11px">${t.time}z</span>${ncBadge}</td>
      <td class="hm"><div class="alloc-pills">${pills}</div></td>
      <td class="hm" style="text-align:right">${pxStr}</td>
      <td>${pr}</td>
      <td><span style="font-family:var(--font-display);font-weight:600">${fmtDollar(t.equity)}</span></td>
    </tr>`;
  }).join('');
  document.getElementById('tableBody').innerHTML=`
    <table class="sig-table"><thead><tr>
      <th>Date / Time (UTC)</th><th class="hm" style="text-align:right">Allocations</th>
      <th class="hm" style="text-align:right">Prices at Signal</th><th>Period Return</th><th>Portfolio Value</th>
    </tr></thead><tbody>${rows}</tbody></table>`;
}

// ── CSV export ────────────────────────────────────────────────────────────────
function exportCSV() {
  if (!_result?.timeline.length){alert('No data. Run backtest first.');return;}
  const {timeline}=_result;
  const hdr=['date','time_utc','no_change','allocations','signal_prices_usd','period_return_pct','portfolio_value_usd','barclose_portfolio_usd'];
  const rows=[hdr.join(',')];
  for (const t of timeline) {
    const allocs=t.allocations.map(a=>`${a.percent}%${a.asset}`).join('|');
    const px=Object.entries(t.prices).map(([k,v])=>`${k}:${v.toFixed(4)}`).join('|');
    const pr=t.period_return!==null?(t.period_return*100).toFixed(4):'';
    rows.push([t.date,t.time+':00',t.no_change?'1':'0',`"${allocs}"`,`"${px}"`,pr,t.equity.toFixed(2),t.equity_bc.toFixed(2)].join(','));
  }
  const blob=new Blob([rows.join('\n')],{type:'text/csv'});
  const url=URL.createObjectURL(blob);
  const a=document.createElement('a');a.href=url;a.download='rsps_backtest_'+new Date().toISOString().slice(0,10)+'.csv';a.click();URL.revokeObjectURL(url);
}

// ── TRW direct fetch fallback ─────────────────────────────────────────────────
async function fetchTRWSignals(token) {
  const CHANNEL='01H83QAX979K9R7QTMH74ATR8C', ADAM='01GHHHWZE7Q77AKGWZDGC5PDCN';
  const sigs=[];let beforeId=null,page=0;
  while(page<40){
    const body={channel:CHANNEL,limit:20,sort:'Latest'};if(beforeId)body.before=beforeId;
    const resp=await fetch('https://eden.therealworld.ag/messages/query',{method:'POST',headers:{'x-session-token':token,'Content-Type':'application/json','Origin':'https://app.jointherealworld.com'},body:JSON.stringify(body)});
    if(resp.status===401)throw new Error('TOKEN_EXPIRED');if(!resp.ok)throw new Error('TRW '+resp.status);
    const data=await resp.json();const msgs=data.messages||[];if(!msgs.length)break;
    for(const m of msgs){if(m.author===ADAM&&m.content?.includes('Portfolio Signal Update'))sigs.push(m);}
    beforeId=msgs[msgs.length-1]._id;page++;
    setProgress(Math.min(10,page),`Fetching page ${page}…`,'');
    if(msgs.length<20)break;
  }
  return sigs;
}

// ── UI helpers ────────────────────────────────────────────────────────────────
function showOverlay(v){document.getElementById('loadingOverlay').classList.toggle('hidden',!v);}
function hideOverlay(){showOverlay(false);}
function setProgress(pct,title,sub){
  document.getElementById('progressFill').style.width=pct+'%';
  if(title)document.getElementById('loadingTitle').textContent=title;
  if(sub!==undefined)document.getElementById('loadingSub').textContent=sub;
}
function setStatus(type,msg){
  const el=document.getElementById('statusMsg');el.textContent=msg;
  el.className=type==='ok'?'status-ok':type==='err'?'status-err':type==='warn'?'status-warn':'';
}
function promptToken(){
  const existing=localStorage.getItem('trw_token')||'';
  const token=prompt('Enter your TRW session token.\n(DevTools → Network → x-session-token header)\nStored in localStorage only.',existing);
  if(!token){setStatus('warn','No token.');return;}
  localStorage.setItem('trw_token',token);runBacktest();
}

// Footer clock
setInterval(()=>{document.getElementById('footerTime').textContent=new Date().toLocaleString('en-GB',{timeZone:'UTC'})+' UTC';},1000);

// ── Init ──────────────────────────────────────────────────────────────────────
window._auth=new URLSearchParams(window.location.search).get('auth')||'';
if(window._auth){const dt=document.getElementById('dashTab');if(dt)dt.href='?auth='+encodeURIComponent(window._auth);}
loadCloudEquity();   // load live snapshots on page open (shows banner immediately)
</script>
</body>
</html>"""

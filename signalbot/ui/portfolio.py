"""WealthOS tab — total-wealth portfolio overview."""
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

__all__ = ['_render_portfolio', '_PORTFOLIO_HTML']


def _render_portfolio(auth: str = "", live_value: float = 0.0,
                      halt: dict | None = None) -> str:
    """Build the Portfolio tab — main wealth overview across all strategies."""
    auth_param = f"&auth={auth}" if auth else ""
    html = _PORTFOLIO_HTML
    html = html.replace("__THEME_HEAD__", _theme_head())
    html = html.replace("__AUTH_PARAM_PLACEHOLDER__", auth_param)
    html = html.replace("__LIVE_VALUE_PLACEHOLDER__", str(live_value))
    html = html.replace("__NAV_PLACEHOLDER__", _nav_html("portfolio", halt))
    return html




# ══════════════════════════════════════════════════════════════════════════════
# PORTFOLIO TAB — HTML (main wealth overview)
# ══════════════════════════════════════════════════════════════════════════════

_PORTFOLIO_HTML = r"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1, maximum-scale=1">
<title>Portfolio</title>
<script src="https://cdnjs.cloudflare.com/ajax/libs/Chart.js/4.4.1/chart.umd.js"></script>
__THEME_HEAD__
<style>
  /* ── Hero ── */
  .hero{position:relative;padding:22px 0 32px}
  .hero::before{content:'';position:absolute;left:-6%;top:-45%;width:460px;height:300px;border-radius:50%;
    background:radial-gradient(closest-side,rgba(200,245,99,.11),transparent);filter:blur(34px);
    pointer-events:none;animation:wosBreath 6s ease-in-out infinite}
  .hero-label{font-size:11px;letter-spacing:.18em;text-transform:uppercase;color:var(--muted);margin-bottom:10px}
  .hero-value{font-family:var(--font-display);font-size:62px;font-weight:800;letter-spacing:-.03em;line-height:1;
    background:linear-gradient(100deg,#f4f1ea 32%,var(--accent) 47%,var(--accent2) 53%,#f4f1ea 68%);
    background-size:240% 100%;-webkit-background-clip:text;background-clip:text;color:transparent;
    animation:wosShimmer 8s linear infinite}
  .hero-sub{display:flex;gap:28px;margin-top:18px;flex-wrap:wrap}
  .hero-stat{display:flex;flex-direction:column;gap:2px}
  .hero-stat-label{font-size:10px;letter-spacing:.1em;text-transform:uppercase;color:var(--muted)}
  .hero-stat-val{font-family:var(--font-display);font-size:18px;font-weight:700}

  /* ── Performance window bar ── */
  .windowbar{display:flex;align-items:center;gap:10px;flex-wrap:wrap;margin:0 0 14px}
  .windowbar-label{font-size:10px;letter-spacing:.14em;text-transform:uppercase;color:var(--muted)}
  .windowbar-since{display:flex;align-items:center;gap:6px;font-size:10px;letter-spacing:.1em;
    text-transform:uppercase;color:var(--muted)}
  .windowbar-since .flow-input{padding:5px 9px;font-size:12px;color-scheme:dark}
  .windowbar-note{font-size:11px;color:var(--muted2);margin-left:auto}

  /* ── Metric tiles ── */
  .metrics{display:grid;grid-template-columns:repeat(4,1fr);gap:10px;margin-bottom:18px}
  .metric{position:relative;background:var(--glass);border:1px solid var(--border);border-radius:14px;padding:16px 18px;
    backdrop-filter:blur(14px);-webkit-backdrop-filter:blur(14px);
    box-shadow:0 14px 34px -16px rgba(0,0,0,.6),inset 0 1px 0 rgba(255,255,255,.05);
    transition:transform .3s var(--ease),border-color .3s,box-shadow .3s}
  .metric:hover{transform:translateY(-3px);border-color:rgba(200,245,99,.28);
    box-shadow:0 20px 42px -16px rgba(0,0,0,.7),0 0 26px -8px rgba(200,245,99,.16)}
  .metric-label{font-size:10px;letter-spacing:.12em;text-transform:uppercase;color:var(--muted);margin-bottom:7px}
  .metric-value{font-family:var(--font-display);font-size:21px;font-weight:700;letter-spacing:-.02em;line-height:1.1}
  .metric-sub{font-size:11px;color:var(--muted);margin-top:4px}

  /* ── Chart ── */
  .chart-controls{display:flex;gap:6px;flex-wrap:wrap;align-items:center}
  .chart-body{padding:16px}
  .chart-legend{display:flex;gap:14px;margin-bottom:10px;flex-wrap:wrap}
  .legend-item{display:flex;align-items:center;gap:6px;font-size:11px;color:var(--muted)}
  .legend-dot{width:8px;height:8px;border-radius:50%;flex-shrink:0;box-shadow:0 0 8px currentColor}
  .chart-wrap{position:relative;width:100%;height:310px}

  /* ── Strategy allocation ── */
  .strat-grid{padding:16px;display:flex;flex-direction:column;gap:16px}
  .strat-row{display:flex;flex-direction:column;gap:7px}
  .strat-head{display:flex;align-items:center;justify-content:space-between;gap:10px}
  .strat-name{font-family:var(--font-display);font-weight:700;font-size:14px}
  .strat-desc{font-size:11px;color:var(--muted)}
  .strat-pct{font-family:var(--font-display);font-weight:700;font-size:17px}
  .strat-pct-input{width:76px;text-align:right;background:rgba(0,0,0,.35);border:1px solid var(--border2);border-radius:8px;
    color:var(--text);font-family:var(--font-display);font-weight:700;font-size:15px;padding:5px 9px;outline:none;
    transition:border-color .25s,box-shadow .25s}
  .strat-pct-input:focus{border-color:rgba(200,245,99,.5);box-shadow:0 0 0 3px rgba(200,245,99,.1)}
  .strat-bar-track{height:9px;background:rgba(255,255,255,.06);border-radius:5px;overflow:hidden}
  .strat-bar-fill{height:100%;border-radius:5px;transition:width .8s var(--ease);
    box-shadow:0 0 14px -2px currentColor;position:relative}
  .strat-bar-fill::after{content:'';position:absolute;inset:0;
    background:linear-gradient(90deg,transparent 30%,rgba(255,255,255,.25) 50%,transparent 70%);
    background-size:200% 100%;animation:wosShimmer 3.2s linear infinite}
  .strat-meta{display:flex;justify-content:space-between;font-size:11px;color:var(--muted)}
  .strat-status{font-size:9px;padding:2px 7px;border-radius:999px;letter-spacing:.06em;text-transform:uppercase}
  .status-active{background:var(--accent-dim);color:var(--accent);border:1px solid rgba(200,245,99,.3);box-shadow:0 0 10px -3px rgba(200,245,99,.4)}
  .status-planned{background:rgba(255,255,255,.05);color:var(--muted);border:1px solid var(--border)}

  /* ── Cash flows ── */
  #flowTableWrap{overflow-x:auto;-webkit-overflow-scrolling:touch}
  .flow-table{width:100%;border-collapse:collapse;min-width:420px}
  .flow-table th{font-size:10px;letter-spacing:.1em;text-transform:uppercase;color:var(--muted);font-weight:500;
    padding:10px 16px;text-align:left;border-bottom:1px solid var(--border);white-space:nowrap}
  .flow-table th:not(:first-child){text-align:right}
  .flow-table td{padding:11px 16px;border-bottom:1px solid var(--border);font-size:12px;transition:background .2s}
  .flow-table td:not(:first-child){text-align:right}
  .flow-table tr:last-child td{border-bottom:none}
  .flow-table tr:hover td{background:rgba(255,255,255,.035)}
  .flow-badge{font-size:9px;padding:2px 7px;border-radius:999px;letter-spacing:.05em}
  .flow-auto{background:var(--blue-dim);color:var(--blue);border:1px solid rgba(91,156,246,.3)}
  .flow-manual{background:rgba(255,255,255,.05);color:var(--muted);border:1px solid var(--border)}
  .flow-del{cursor:pointer;color:var(--muted2);font-size:14px;transition:color .2s,transform .2s;display:inline-block}
  .flow-del:hover{color:var(--red);transform:scale(1.25)}

  .flow-form{display:flex;gap:10px;padding:14px 16px;border-top:1px solid var(--border);flex-wrap:wrap;align-items:end}
  .flow-field{display:flex;flex-direction:column;gap:4px}
  .flow-field label{font-size:10px;letter-spacing:.08em;text-transform:uppercase;color:var(--muted)}
  .flow-input{background:rgba(0,0,0,.35);border:1px solid var(--border2);border-radius:9px;color:var(--text);
    font-family:var(--font-mono);font-size:13px;padding:8px 11px;outline:none;transition:border-color .25s,box-shadow .25s}
  .flow-input:focus{border-color:rgba(200,245,99,.5);box-shadow:0 0 0 3px rgba(200,245,99,.1)}

  /* ── Mobile ─────────────────────────────────────────────────────────────
     Phones get: tighter rhythm, two-up tiles, controls that scroll instead of
     wrapping into a tangle, full-width form fields, and tables that scroll
     inside their panel so the page itself never scrolls sideways. */
  @media(max-width:700px){
    .header,.main{padding-left:14px;padding-right:14px}
    .hero{padding:14px 0 22px}
    .hero::before{width:280px;height:200px}
    .hero-value{font-size:40px}
    .hero-sub{display:grid;grid-template-columns:1fr 1fr;gap:12px 16px;margin-top:14px}
    .hero-stat-val{font-size:16px}
    .metrics{grid-template-columns:1fr 1fr;gap:8px}
    .metric{padding:13px 14px;border-radius:12px}
    .metric-value{font-size:18px}
    .metric-sub{font-size:10px}
    .chart-wrap{height:240px}
    .chart-body{padding:12px}
    .panel-header{padding:12px 14px}
    /* one horizontal scroller per control group beats a four-row wrap */
    .chart-controls{flex-wrap:nowrap;overflow-x:auto;-webkit-overflow-scrolling:touch;
      scrollbar-width:none;max-width:100%}
    .chart-controls::-webkit-scrollbar{display:none}
    .ctrl-group{flex-shrink:0}
    .ctrl-btn{padding:6px 12px}
    .windowbar{gap:8px}
    .windowbar-note{margin-left:0;width:100%;order:9}
    .strat-grid{padding:14px;gap:14px}
    .flow-form{padding:12px 14px;gap:8px}
    .flow-field{flex:1 1 100%}
    .flow-field .flow-input{width:100%}
    .flow-form .btn{flex:1 1 100%;justify-content:center;padding:11px}
    .footer{flex-direction:column;gap:4px;padding:14px}
  }
  @media(max-width:480px){
    .logo{display:none}
    .hero-value{font-size:34px}
    .hero-label{font-size:10px;margin-bottom:6px}
    .metric{padding:11px 12px}
    .metric-value{font-size:17px}
    .chart-wrap{height:210px}
    .panel-title{font-size:9px}
    .windowbar-label{display:none}
  }
</style>
</head>
<body>

__NAV_PLACEHOLDER__

  <div class="hero">
    <div class="hero-label">Total Portfolio Value</div>
    <div class="hero-value" id="heroValue" data-count>$0.00</div>
    <div class="hero-sub">
      <div class="hero-stat">
        <div class="hero-stat-label">True P&L</div>
        <div class="hero-stat-val" id="heroPnl" data-count>—</div>
      </div>
      <div class="hero-stat">
        <div class="hero-stat-label">Net Deposited</div>
        <div class="hero-stat-val" id="heroDeposited" data-count>—</div>
      </div>
      <div class="hero-stat">
        <div class="hero-stat-label">Return on Capital</div>
        <div class="hero-stat-val" id="heroReturn" data-count>—</div>
      </div>
      <div class="hero-stat">
        <div class="hero-stat-label">Time-Weighted Return</div>
        <div class="hero-stat-val" id="heroTwr" data-count>—</div>
      </div>
      <div class="hero-stat">
        <div class="hero-stat-label">XIRR (annualized)</div>
        <div class="hero-stat-val" id="heroXirr" data-count>—</div>
      </div>
    </div>
  </div>

  <div class="windowbar">
    <span class="windowbar-label">Performance window</span>
    <div class="ctrl-group" id="windowTabs">
      <button class="ctrl-btn" data-w="30">30d</button>
      <button class="ctrl-btn" data-w="90">90d</button>
      <button class="ctrl-btn" data-w="365">1y</button>
      <button class="ctrl-btn active" data-w="0">All</button>
    </div>
    <label class="windowbar-since">from
      <input type="date" id="windowStart" class="flow-input" aria-label="Performance window start date">
    </label>
    <span class="windowbar-note" id="windowNote"></span>
  </div>

  <div class="metrics">
    <div class="metric"><div class="metric-label">Current Value</div><div class="metric-value" id="mValue" data-count>—</div><div class="metric-sub">live</div></div>
    <div class="metric"><div class="metric-label">Total Deposited</div><div class="metric-value" id="mDeposited" data-count>—</div><div class="metric-sub" id="mFlowCount">—</div></div>
    <div class="metric"><div class="metric-label">Money Made</div><div class="metric-value" id="mPnl" data-count>—</div><div class="metric-sub">excl. deposits</div></div>
    <div class="metric"><div class="metric-label">Strategies</div><div class="metric-value" id="mStrats" data-count>—</div><div class="metric-sub">active</div></div>
    <div class="metric"><div class="metric-label">Sharpe</div><div class="metric-value" id="mSharpe" data-count>—</div><div class="metric-sub" id="mSortino">sortino —</div></div>
    <div class="metric"><div class="metric-label">Volatility</div><div class="metric-value" id="mVol" data-count>—</div><div class="metric-sub">annualized</div></div>
    <div class="metric"><div class="metric-label">Max Drawdown</div><div class="metric-value" id="mMaxDd" data-count>—</div><div class="metric-sub" id="mDdSub">flow-adjusted, peak to trough</div></div>
    <div class="metric"><div class="metric-label">Best / Worst Day</div><div class="metric-value" id="mBestDay" data-count>—</div><div class="metric-sub" id="mWorstDay">—</div></div>
  </div>

  <div class="panel">
    <div class="panel-header">
      <div class="panel-title">Portfolio Equity</div>
      <div class="chart-controls">
        <div class="ctrl-group" id="seriesTabs">
          <button class="ctrl-btn active" onclick="setSeries('value',this)">Value</button>
          <button class="ctrl-btn" onclick="setSeries('deposited',this)">vs Deposited</button>
          <button class="ctrl-btn" onclick="setSeries('perf',this)">Performance</button>
          <button class="ctrl-btn" onclick="setSeries('drawdown',this)">Drawdown</button>
        </div>
        <div class="ctrl-group" id="benchTabs" style="display:none">
          <button class="ctrl-btn" id="benchBTC" onclick="toggleBench('BTC',this)">vs BTC</button>
          <button class="ctrl-btn" id="benchETH" onclick="toggleBench('ETH',this)">vs ETH</button>
        </div>
      </div>
    </div>
    <div class="chart-body">
      <div class="chart-legend" id="chartLegend"></div>
      <div id="chartWrap" class="chart-wrap" style="display:none"><canvas id="portfolioChart"></canvas></div>
      <div id="noHistory" class="empty">Accumulating portfolio history — first snapshot saves at 23:55 UTC</div>
    </div>
  </div>

  <div class="panel">
    <div class="panel-header">
      <div class="panel-title">Strategy Allocation</div>
      <div style="display:flex;align-items:center;gap:10px">
        <span id="stratSum" style="font-size:11px;color:var(--muted)">% of portfolio designated per strategy</span>
        <button class="ctrl-btn" id="stratEditBtn" onclick="toggleStratEdit()">Edit</button>
        <button class="btn btn-accent" id="stratSaveBtn" onclick="saveStrategies()" style="display:none;padding:4px 12px">Save</button>
        <button class="ctrl-btn" id="stratCancelBtn" onclick="cancelStratEdit()" style="display:none">Cancel</button>
      </div>
    </div>
    <div class="strat-grid" id="stratGrid"></div>
  </div>

  <div class="panel">
    <div class="panel-header">
      <div class="panel-title">Cash Flows — deposits & withdrawals</div>
      <span style="font-size:11px;color:var(--muted)" id="flowSummary"></span>
    </div>
    <div id="flowTableWrap"><div class="empty">No cash flows recorded yet</div></div>
    <div class="flow-form">
      <div class="flow-field">
        <label>Amount (USD, − for withdrawal)</label>
        <input class="flow-input" id="flowAmount" type="number" step="0.01" placeholder="1000">
      </div>
      <div class="flow-field">
        <label>Date</label>
        <input class="flow-input" id="flowDate" type="date">
      </div>
      <div class="flow-field">
        <label>Note</label>
        <input class="flow-input" id="flowNote" type="text" placeholder="e.g. salary, profit take">
      </div>
      <button class="btn btn-accent" onclick="addFlow()">Add Flow</button>
      <span id="flowStatus" style="font-size:11px;align-self:center"></span>
    </div>
  </div>

</div>

<div class="footer">
  <span>WealthOS — unified view across all strategies · auto-detects HL deposits/withdrawals</span>
  <span id="footerTime"></span>
</div>

<script>
const _liveValue = parseFloat("__LIVE_VALUE_PLACEHOLDER__") || 0;
const _auth = new URLSearchParams(window.location.search).get('auth')||'';
function _ap(){return _auth?'&auth='+encodeURIComponent(_auth):'';}

let _data = null;
let chart = null, currentSeries='value';
// Performance window (unix ms, 0 = all history). Drives the metric tiles AND
// the charts, and is remembered server-side so every device agrees.
// null means "not asked yet" — the first load must NOT send a window, or it
// would tell the server 'all history' and overrule the date you saved.
let startTs = null;

function fmt$(v){return '$'+parseFloat(v).toLocaleString('en-US',{minimumFractionDigits:2,maximumFractionDigits:2})}
function fmtPct(v,d=1){return (v>=0?'+':'')+(v*100).toFixed(d)+'%'}

async function loadData(){
  try{
    // The server fetches the live account value itself, so this tab shows the
    // same number as the RSPS tab (_liveValue is only the first-paint hint).
    const win = (startTs === null) ? '' : `&points=${startTs}`;   // omit → use the saved default
    const r = await fetch(`?action=portfolio_data${_ap()}&v=${_liveValue}${win}`);
    if(!r.ok) throw new Error('HTTP '+r.status);
    _data = await r.json();
    if(typeof _data.start_ts === 'number') startTs = _data.start_ts;
    syncWindowControls();
    render();
  }catch(e){
    console.error('portfolio load failed', e);
    document.getElementById('noHistory').textContent = 'Failed to load: '+e.message;
  }
}

// ── Performance window control ───────────────────────────────────────────────
function syncWindowControls(){
  const inp = document.getElementById('windowStart');
  if(inp) inp.value = startTs ? new Date(startTs).toISOString().slice(0,10) : '';
  const days = startTs ? Math.round((Date.now()-startTs)/86400000) : 0;
  document.querySelectorAll('#windowTabs .ctrl-btn').forEach(b=>{
    const w = +b.dataset.w;
    b.classList.toggle('active', w===0 ? !startTs : (startTs>0 && Math.abs(days-w)<=1));
  });
  const note = document.getElementById('windowNote');
  if(note) note.textContent = startTs
    ? 'risk stats & charts since '+new Date(startTs).toLocaleDateString('en-GB',{day:'numeric',month:'short',year:'numeric'})
    : 'risk stats & charts over all history';
  const ddSub = document.getElementById('mDdSub');
  if(ddSub) ddSub.textContent = startTs ? 'flow-adjusted, in window' : 'flow-adjusted, peak to trough';
}

async function setWindow(ts){
  startTs = Math.max(0, Math.round(ts));   // never |0 — ms timestamps overflow int32
  syncWindowControls();
  try{ await fetch(`?action=portfolio_start_save${_ap()}&points=${startTs}`); }catch(e){}
  await loadData();
}

document.getElementById('windowTabs').addEventListener('click', e=>{
  const b = e.target.closest('.ctrl-btn'); if(!b) return;
  const days = +b.dataset.w;
  setWindow(days ? Date.now()-days*86400000 : 0);
});
document.getElementById('windowStart').addEventListener('change', e=>{
  const v = e.target.value;
  setWindow(v ? Date.parse(v+'T00:00:00Z') : 0);
});

function render(){
  if(!_data) return;
  const m = _data.metrics;

  // Hero
  document.getElementById('heroValue').textContent = fmt$(m.current_value);
  const pnlEl = document.getElementById('heroPnl');
  pnlEl.textContent = (m.true_pnl>=0?'+':'')+fmt$(m.true_pnl);
  pnlEl.className = 'hero-stat-val '+(m.true_pnl>=0?'pos':'neg');
  document.getElementById('heroDeposited').textContent = fmt$(m.net_deposited);
  const retEl = document.getElementById('heroReturn');
  retEl.textContent = m.net_deposited>0 ? fmtPct(m.simple_return) : '—';
  retEl.className = 'hero-stat-val '+(m.simple_return>=0?'pos':'neg');
  const twrEl = document.getElementById('heroTwr');
  twrEl.textContent = m.twr!==null ? fmtPct(m.twr) : '—';
  twrEl.className = 'hero-stat-val '+(m.twr>=0?'pos':'neg');
  const xirrEl = document.getElementById('heroXirr');
  xirrEl.textContent = (m.xirr!==null && m.xirr!==undefined) ? fmtPct(m.xirr) : '—';
  xirrEl.className = 'hero-stat-val '+((m.xirr||0)>=0?'pos':'neg');

  // Metric cards
  document.getElementById('mValue').textContent = fmt$(m.current_value);
  document.getElementById('mDeposited').textContent = fmt$(m.net_deposited);
  document.getElementById('mFlowCount').textContent = m.flow_count+' flows';
  const mp = document.getElementById('mPnl');
  mp.textContent = (m.true_pnl>=0?'+':'')+fmt$(m.true_pnl);
  mp.className = 'metric-value '+(m.true_pnl>=0?'pos':'neg');
  const activeStrats = _data.strategies.filter(s=>s.status==='active').length;
  document.getElementById('mStrats').textContent = activeStrats;

  // Risk tiles (flow-adjusted daily stats; null until ~3 days of history)
  const rk = m.risk||{};
  const dayFmt = ts=>new Date(ts).toLocaleDateString('en-GB',{day:'numeric',month:'short'});
  document.getElementById('mSharpe').textContent = rk.sharpe!=null ? rk.sharpe.toFixed(2) : '—';
  document.getElementById('mSortino').textContent = 'sortino '+(rk.sortino!=null ? rk.sortino.toFixed(2) : '—');
  document.getElementById('mVol').textContent = rk.vol_annual!=null ? (rk.vol_annual*100).toFixed(1)+'%' : '—';
  const ddEl = document.getElementById('mMaxDd');
  ddEl.textContent = rk.max_drawdown!=null ? (rk.max_drawdown*100).toFixed(1)+'%' : '—';
  if(rk.max_drawdown!=null && rk.max_drawdown<0) ddEl.className='metric-value neg';
  const bEl = document.getElementById('mBestDay');
  if(rk.best_day){ bEl.textContent=fmtPct(rk.best_day.r); bEl.className='metric-value pos'; }
  document.getElementById('mWorstDay').textContent =
    rk.worst_day ? 'worst '+fmtPct(rk.worst_day.r)+' ('+dayFmt(rk.worst_day.ts)+')' : '—';

  renderChart();
  renderStrategies();
  renderFlows();
  if(window.wosCountUp)wosCountUp();
}

function filterRange(arr){
  // One window for the whole pane — the same cut the server used for metrics
  if(!startTs) return arr;
  return arr.filter(p=>p.ts>=startTs);
}

// Collapse to one point per UTC day (keep the last snapshot of each day) so the
// chart isn't noisy when multiple snapshots land on the same day. Display-only —
// the metrics still use the full series.
function dailyDownsample(arr){
  const byDay=new Map();
  for(const p of arr){ byDay.set(Math.floor(p.ts/86400000), p); }
  return [...byDay.values()].sort((a,b)=>a.ts-b.ts);
}

function renderChart(){
  if(currentSeries==='perf'||currentSeries==='drawdown'){renderIndexChart();return}
  const snaps = dailyDownsample(filterRange(_data.snapshots||[]));
  const noH=document.getElementById('noHistory'), wrap=document.getElementById('chartWrap');
  if(snaps.length<2){noH.style.display='block';wrap.style.display='none';return}
  noH.style.display='none';wrap.style.display='block';

  const labels = snaps.map(s=>{const d=new Date(s.ts);return d.toLocaleDateString('en-GB',{day:'numeric',month:'short',year:snaps.length>200?'2-digit':undefined})});
  const values = snaps.map(s=>s.v);

  // Build "deposited" cumulative line aligned to snapshot timestamps
  const flows = _data.flows||[];
  const depositedLine = snaps.map(s=>{
    return flows.filter(f=>f.ts<=s.ts).reduce((sum,f)=>sum+f.amount,0);
  });

  const showDep = currentSeries==='deposited';
  const up = values[values.length-1]>=values[0];

  const datasets = [{
    label:'Portfolio value', data:values,
    borderColor:up?'#c8f563':'#ff5c5c',
    backgroundColor:up?'rgba(200,245,99,0.06)':'rgba(255,92,92,0.06)',
    borderWidth:2, pointRadius:snaps.length>60?0:3, pointHoverRadius:5,
    fill:!showDep, tension:0.3, order:1,
  }];
  if(showDep){
    datasets.push({
      label:'Net deposited', data:depositedLine,
      borderColor:'#5b9cf6', backgroundColor:'rgba(91,156,246,0.04)',
      borderWidth:1.5, borderDash:[5,4], pointRadius:0, fill:true, tension:0, order:2,
    });
  }

  // Legend
  let lg='<div class="legend-item"><div class="legend-dot" style="background:'+(up?'#c8f563':'#ff5c5c')+'"></div>Portfolio value</div>';
  if(showDep) lg+='<div class="legend-item"><div class="legend-dot" style="background:#5b9cf6"></div>Net deposited (cost basis)</div>';
  document.getElementById('chartLegend').innerHTML=lg;

  if(chart){chart.destroy();chart=null}
  chart=new Chart(document.getElementById('portfolioChart'),{
    type:'line', data:{labels,datasets},
    options:{
      responsive:true,maintainAspectRatio:false,interaction:{mode:'index',intersect:false},
      plugins:{legend:{display:false},tooltip:{
        backgroundColor:'#1a1a1a',borderColor:'rgba(255,255,255,0.1)',borderWidth:1,
        titleColor:'#666',bodyColor:'#f0ede8',titleFont:{family:'DM Mono',size:11},bodyFont:{family:'DM Mono',size:12},
        callbacks:{label:ctx=>' '+ctx.dataset.label+': '+fmt$(ctx.parsed.y)}
      }},
      scales:{
        x:{grid:{color:'rgba(255,255,255,0.04)'},ticks:{color:'#555',font:{family:'DM Mono',size:11},maxTicksLimit:8},border:{display:false}},
        y:{position:'right',grid:{color:'rgba(255,255,255,0.04)'},ticks:{color:'#555',font:{family:'DM Mono',size:11},callback:v=>'$'+v.toLocaleString()},border:{display:false}}
      }
    }
  });
}

// ── Performance / Drawdown modes — flow-adjusted TWR index ──────────────────
// The server sends index_series (chain-linked Modified-Dietz index), so
// deposits/withdrawals never show up as performance. Benchmarks are HL daily
// closes normalized to 100 at the first visible day — same basis as the index.
let _bench=null, _benchOn={BTC:false,ETH:false};

async function fetchBench(){
  if(_bench) return _bench;
  const s=_data.index_series||[];
  try{
    const payload=encodeURIComponent(JSON.stringify({start:s.length?s[0].ts:0}));
    const r=await fetch(`?action=benchmark_data${_ap()}&points=${payload}`);
    if(r.ok) _bench=await r.json();
  }catch(e){console.error('benchmark fetch failed',e)}
  return _bench||{BTC:[],ETH:[]};
}

function _baseOpts(yTick,tooltip){
  return {
    responsive:true,maintainAspectRatio:false,interaction:{mode:'index',intersect:false},
    plugins:{legend:{display:false},tooltip:{
      backgroundColor:'#1a1a1a',borderColor:'rgba(255,255,255,0.1)',borderWidth:1,
      titleColor:'#666',bodyColor:'#f0ede8',titleFont:{family:'DM Mono',size:11},bodyFont:{family:'DM Mono',size:12},
      callbacks:{label:tooltip}
    }},
    scales:{
      x:{grid:{color:'rgba(255,255,255,0.04)'},ticks:{color:'#555',font:{family:'DM Mono',size:11},maxTicksLimit:8},border:{display:false}},
      y:{position:'right',grid:{color:'rgba(255,255,255,0.04)'},ticks:{color:'#555',font:{family:'DM Mono',size:11},callback:yTick},border:{display:false}}
    }
  };
}

async function renderIndexChart(){
  const idxAll = dailyDownsample(_data.index_series||[]);
  const noH=document.getElementById('noHistory'), wrap=document.getElementById('chartWrap');
  const idx = filterRange(idxAll);
  if(idx.length<2){noH.style.display='block';wrap.style.display='none';return}
  noH.style.display='none';wrap.style.display='block';
  const labels = idx.map(s=>new Date(s.ts).toLocaleDateString('en-GB',{day:'numeric',month:'short',year:idx.length>200?'2-digit':undefined}));
  const mySeries=currentSeries;   // guard against mode switch during async fetch
  let datasets=[], legend='', yTick, tip;

  if(currentSeries==='drawdown'){
    // Underwater curve: running peak over FULL history, windowed for display
    let peak=0; const dd=new Map();
    for(const p of idxAll){ peak=Math.max(peak,p.v); dd.set(p.ts, peak>0?(p.v/peak-1)*100:0); }
    datasets=[{label:'Drawdown',data:idx.map(p=>dd.get(p.ts)??0),
      borderColor:'#ff5c5c',backgroundColor:'rgba(255,92,92,0.10)',
      borderWidth:2,pointRadius:0,pointHoverRadius:4,fill:'origin',tension:0.2}];
    legend='<div class="legend-item"><div class="legend-dot" style="background:#ff5c5c"></div>Drawdown from peak (flow-adjusted)</div>';
    yTick=v=>v.toFixed(0)+'%'; tip=ctx=>' '+ctx.parsed.y.toFixed(2)+'%';
  }else{
    const base=idx[0].v;
    datasets=[{label:'Portfolio',data:idx.map(p=>p.v/base*100),
      borderColor:'#c8f563',backgroundColor:'rgba(200,245,99,0.06)',
      borderWidth:2,pointRadius:0,pointHoverRadius:4,fill:false,tension:0.3}];
    legend='<div class="legend-item"><div class="legend-dot" style="background:#c8f563"></div>Portfolio (TWR, start=100)</div>';
    const bcol={BTC:'#f7931a',ETH:'#627eea'};
    if(_benchOn.BTC||_benchOn.ETH){
      const bench=await fetchBench();
      if(currentSeries!==mySeries) return;
      for(const coin of ['BTC','ETH']){
        if(!_benchOn[coin]) continue;
        const closes=bench[coin]||[];
        if(!closes.length) continue;
        const byDay=new Map(closes.map(c=>[Math.floor(c.ts/86400000),c.c]));
        let b0=null;
        const data=idx.map(p=>{
          const c=byDay.get(Math.floor(p.ts/86400000));
          if(c==null) return null;
          if(b0===null) b0=c;
          return c/b0*100;
        });
        datasets.push({label:coin+' hold',data,
          borderColor:bcol[coin],borderWidth:1.5,borderDash:[5,4],
          pointRadius:0,pointHoverRadius:3,fill:false,tension:0.2,spanGaps:true});
        legend+='<div class="legend-item"><div class="legend-dot" style="background:'+bcol[coin]+'"></div>'+coin+' hold</div>';
      }
    }
    yTick=v=>v.toFixed(0); tip=ctx=>' '+ctx.dataset.label+': '+(ctx.parsed.y??0).toFixed(1);
  }
  document.getElementById('chartLegend').innerHTML=legend;
  if(chart){chart.destroy();chart=null}
  chart=new Chart(document.getElementById('portfolioChart'),{type:'line',data:{labels,datasets},options:_baseOpts(yTick,tip)});
}

function toggleBench(coin,el){
  _benchOn[coin]=!_benchOn[coin];
  el.classList.toggle('active',_benchOn[coin]);
  renderChart();
}

function setSeries(s,el){currentSeries=s;document.querySelectorAll('#seriesTabs .ctrl-btn').forEach(b=>b.classList.remove('active'));el.classList.add('active');document.getElementById('benchTabs').style.display=(s==='perf')?'':'none';renderChart()}

const STRAT_COLORS={rsps:'#c8f563',sdca:'#5b9cf6',delta:'#c084fc',yield:'#f5a623',cfd:'#ff5c5c'};
let stratEdit=false;
function renderStrategies(){
  const grid=document.getElementById('stratGrid');
  const strats=_data.strategies||[];
  const totalVal=_data.metrics.current_value;
  grid.innerHTML=strats.map(s=>{
    const color=STRAT_COLORS[s.id]||'#6b6860';
    const allocVal=totalVal*(s.target_pct/100);
    const statusCls=s.status==='active'?'status-active':'status-planned';
    const pctCell=stratEdit
      ? `<input class="strat-pct-input" type="number" step="0.1" min="0" max="100" value="${s.target_pct}" data-id="${s.id}" oninput="updateStratSum()">`
      : `<div class="strat-pct" style="color:${color}">${s.target_pct.toFixed(1)}%</div>`;
    return `<div class="strat-row">
      <div class="strat-head">
        <div>
          <span class="strat-name">${s.name}</span>
          <span class="strat-status ${statusCls}">${s.status}</span>
          <div class="strat-desc">${s.description||''}</div>
        </div>
        ${pctCell}
      </div>
      <div class="strat-bar-track"><div class="strat-bar-fill" style="width:${s.target_pct}%;background:${color}"></div></div>
      <div class="strat-meta">
        <span>${s.status==='active'?'live value':'target allocation'}</span>
        <span>${fmt$(allocVal)}</span>
      </div>
    </div>`;
  }).join('');
}

function _stratBtns(editing){
  document.getElementById('stratEditBtn').style.display   = editing?'none':'';
  document.getElementById('stratSaveBtn').style.display   = editing?'':'none';
  document.getElementById('stratCancelBtn').style.display = editing?'':'none';
}
function updateStratSum(){
  const inputs=[...document.querySelectorAll('.strat-pct-input')];
  const el=document.getElementById('stratSum');
  if(!inputs.length){el.textContent='% of portfolio designated per strategy';el.style.color='var(--muted)';return}
  const sum=inputs.reduce((a,i)=>a+(parseFloat(i.value)||0),0);
  el.textContent='Σ '+sum.toFixed(1)+'%';
  el.style.color=(Math.abs(sum-100)<0.05)?'var(--accent)':'var(--red)';
}
function toggleStratEdit(){stratEdit=true;_stratBtns(true);renderStrategies();updateStratSum()}
function cancelStratEdit(){stratEdit=false;_stratBtns(false);renderStrategies();updateStratSum()}
async function saveStrategies(){
  const inputs=[...document.querySelectorAll('.strat-pct-input')];
  const sum=inputs.reduce((a,i)=>a+(parseFloat(i.value)||0),0);
  if(Math.abs(sum-100)>0.05 && !confirm('Allocations sum to '+sum.toFixed(1)+'%, not 100%. Save anyway?'))return;
  const byId={};inputs.forEach(i=>byId[i.dataset.id]=Math.max(0,parseFloat(i.value)||0));
  const strats=(_data.strategies||[]).map(s=>({...s,target_pct:(s.id in byId)?byId[s.id]:s.target_pct}));
  try{
    const payload=encodeURIComponent(JSON.stringify({strategies:strats}));
    const r=await fetch(`?action=strategies_save${_ap()}&points=${payload}`);
    const d=await r.json();
    if(d.ok){stratEdit=false;_stratBtns(false);await loadData()}
    else alert('Save failed: '+(d.error||'?'));
  }catch(e){alert('Save failed')}
}

function renderFlows(){
  const flows=[..._data.flows].reverse();
  const wrap=document.getElementById('flowTableWrap');
  const totalDep=_data.flows.filter(f=>f.amount>0).reduce((s,f)=>s+f.amount,0);
  const totalWd=_data.flows.filter(f=>f.amount<0).reduce((s,f)=>s+Math.abs(f.amount),0);
  document.getElementById('flowSummary').textContent=`${fmt$(totalDep)} in · ${fmt$(totalWd)} out`;
  if(!flows.length){wrap.innerHTML='<div class="empty">No cash flows recorded yet — add one below or they auto-detect from HL</div>';return}
  wrap.innerHTML=`<table class="flow-table"><thead><tr>
    <th>Date</th><th>Type</th><th>Amount</th><th>Contribution</th><th></th>
  </tr></thead><tbody>${flows.map(f=>{
    const date=new Date(f.ts).toLocaleDateString('en-GB',{day:'numeric',month:'short',year:'numeric'});
    const srcBadge=f.source==='auto'?'<span class="flow-badge flow-auto">AUTO</span>':'<span class="flow-badge flow-manual">MANUAL</span>';
    const amtCls=f.amount>=0?'pos':'neg';
    const inj=(_data.metrics.injections||[]).find(i=>i.ts===f.ts&&i.amount===f.amount);
    let contrib='<span style="color:var(--muted2)">—</span>';
    if(inj){
      const rp=(inj.return_pct!==undefined&&inj.return_pct!==null)?`<span style="color:var(--muted);font-size:11px"> · ${fmtPct(inj.return_pct)}</span>`:'';
      contrib=`<span class="${inj.contribution>=0?'pos':'neg'}">${inj.contribution>=0?'+':''}${fmt$(inj.contribution)}</span>${rp}`;
    }
    const delBtn=f.source==='manual'?`<span class="flow-del" onclick="delFlow(${f.ts},'${f.hash||''}')">×</span>`:'';
    return `<tr>
      <td>${date} ${f.note?'<span style="color:var(--muted);font-size:11px">· '+f.note+'</span>':''}</td>
      <td>${srcBadge}</td>
      <td class="${amtCls}">${f.amount>=0?'+':''}${fmt$(f.amount)}</td>
      <td>${contrib}</td>
      <td>${delBtn}</td>
    </tr>`;
  }).join('')}</tbody></table>`;
}

async function addFlow(){
  const amount=parseFloat(document.getElementById('flowAmount').value);
  const dateStr=document.getElementById('flowDate').value;
  const note=document.getElementById('flowNote').value;
  const status=document.getElementById('flowStatus');
  if(!amount){status.textContent='Enter an amount';status.style.color='var(--red)';return}
  const ts=dateStr?new Date(dateStr+'T12:00:00Z').getTime():Date.now();
  status.textContent='Saving…';status.style.color='var(--muted)';
  try{
    const payload=encodeURIComponent(JSON.stringify({amount,ts,note}));
    const r=await fetch(`?action=cashflow_add${_ap()}&points=${payload}`);
    const d=await r.json();
    if(d.ok){
      status.textContent='✓ Added';status.style.color='var(--accent)';
      document.getElementById('flowAmount').value='';
      document.getElementById('flowNote').value='';
      await loadData();
      setTimeout(()=>status.textContent='',2000);
    }else{status.textContent='Error: '+(d.error||'?');status.style.color='var(--red)'}
  }catch(e){status.textContent='Failed';status.style.color='var(--red)'}
}

async function delFlow(ts,hash){
  if(!confirm('Delete this cash flow?'))return;
  try{
    const payload=encodeURIComponent(JSON.stringify({ts,hash}));
    await fetch(`?action=cashflow_delete${_ap()}&points=${payload}`);
    await loadData();
  }catch(e){console.error(e)}
}

// Default date = today
document.getElementById('flowDate').value=new Date().toISOString().slice(0,10);
// Auth-preserve tab links
if(_auth){
  ['rspsTab','histTab','stratTab'].forEach(id=>{const el=document.getElementById(id);if(el&&!el.href.includes('auth='))el.href+=(el.href.includes('?')?'&':'?')+'auth='+encodeURIComponent(_auth)});
}
// ── Auto-refresh ─────────────────────────────────────────────────────────────
// Same 60s cadence as the RSPS tab, but data-only: no page reload, so charts
// and the entrance animations don't flash. Pauses while the tab is hidden.
const REFRESH_MS = 60000;
let _refreshTimer = null, _secs = 0;

function startRefresh(){
  if(_refreshTimer) return;
  _refreshTimer = setInterval(()=>{
    if(document.hidden) return;
    _secs = 0;
    loadData();
  }, REFRESH_MS);
}
function stopRefresh(){ clearInterval(_refreshTimer); _refreshTimer = null; }
document.addEventListener('visibilitychange', ()=>{
  if(document.hidden){ stopRefresh(); }
  else { _secs = 0; loadData(); startRefresh(); }   // catch up on return
});
startRefresh();

setInterval(()=>{
  _secs++;
  const left = Math.max(0, Math.round((REFRESH_MS - _secs*1000)/1000));
  document.getElementById('footerTime').textContent =
    new Date().toLocaleString('en-GB',{timeZone:'UTC'})+' UTC  ·  refresh in '+left+'s';
},1000);

loadData();
</script>
</body>
</html>"""

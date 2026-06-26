import os
import json
import re
import time
import hmac
import secrets
from datetime import datetime, timezone
from decimal import Decimal, ROUND_DOWN
from signalbot.config import *
from signalbot.trw import *
from signalbot.hyperliquid import *
from signalbot.rebalance import *
from signalbot.strategies import *

__all__ = [
    '_html_escape',
    '_page',
    '_DASHBOARD_HTML',
    '_render_dashboard',
    '_fetch_history_signals',
    '_render_history',
    '_render_portfolio',
    '_HISTORY_HTML',
    '_PORTFOLIO_HTML',
    '_render_strategies',
    '_STRATEGIES_HTML',
]



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



_DASHBOARD_HTML = r"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1, maximum-scale=1">
<title>Signal Bot</title>
<script src="https://cdnjs.cloudflare.com/ajax/libs/Chart.js/4.4.1/chart.umd.js"></script>
<style>
  @import url('https://fonts.googleapis.com/css2?family=DM+Mono:wght@400;500&family=Syne:wght@400;600;700&display=swap');
  *,*::before,*::after{box-sizing:border-box;margin:0;padding:0}
  :root{--bg:#0a0a0a;--surface:#111111;--surface2:#1a1a1a;--border:rgba(255,255,255,0.08);--border2:rgba(255,255,255,0.14);--text:#f0ede8;--muted:#6b6860;--accent:#c8f563;--accent-dim:rgba(200,245,99,0.12);--red:#ff5c5c;--red-dim:rgba(255,92,92,0.12);--blue:#5b9cf6;--blue-dim:rgba(91,156,246,0.12);--amber:#f5a623;--purple:#c084fc;--font-mono:'DM Mono',monospace;--font-display:'Syne',sans-serif}
  body{background:var(--bg);color:var(--text);font-family:var(--font-mono);font-size:13px;line-height:1.6;min-height:100vh}
  .header{display:flex;align-items:center;justify-content:space-between;padding:16px 20px;border-bottom:1px solid var(--border);position:sticky;top:0;background:var(--bg);z-index:10;gap:10px;flex-wrap:wrap}
  .header-left{display:flex;align-items:center;gap:10px;min-width:0;flex-shrink:0}
  .logo{font-family:var(--font-display);font-size:15px;font-weight:700;letter-spacing:-0.02em;white-space:nowrap}
  .logo span{color:var(--accent)}
  .pulse-dot{width:7px;height:7px;border-radius:50%;background:var(--accent);flex-shrink:0;animation:pulse 2s ease-in-out infinite}
  @keyframes pulse{0%,100%{opacity:1;transform:scale(1)}50%{opacity:.4;transform:scale(.8)}}
  .tab-nav{display:flex;gap:1px;background:var(--border);border-radius:5px;overflow:hidden;padding:1px}
  .tab-btn{font-size:11px;font-family:var(--font-mono);letter-spacing:.06em;text-transform:uppercase;padding:5px 12px;border-radius:4px;cursor:pointer;color:var(--muted);border:none;background:none;transition:all .15s;white-space:nowrap;text-decoration:none;display:inline-block}
  .tab-btn.active{background:var(--surface2);color:var(--text)}
  .tab-btn:hover:not(.active){color:var(--text)}
  .header-badges{display:flex;gap:6px;flex-wrap:wrap}
  .badge{font-size:10px;font-family:var(--font-mono);font-weight:500;padding:3px 7px;border-radius:3px;letter-spacing:.05em;text-transform:uppercase;white-space:nowrap}
  .badge-ok{background:rgba(200,245,99,.15);color:var(--accent);border:1px solid rgba(200,245,99,.25)}
  .badge-err{background:var(--red-dim);color:var(--red);border:1px solid rgba(255,92,92,.25)}
  .badge-auto{background:var(--blue-dim);color:var(--blue);border:1px solid rgba(91,156,246,.25)}
  .badge-manual{background:rgba(245,166,35,.15);color:var(--amber);border:1px solid rgba(245,166,35,.25)}
  .main{padding:16px 20px;max-width:1200px}
  .pending-banner{border:1px solid rgba(245,166,35,.35);background:rgba(245,166,35,.06);border-radius:8px;padding:16px;margin-bottom:16px}
  .pending-label{font-family:var(--font-display);font-size:11px;font-weight:600;letter-spacing:.1em;text-transform:uppercase;color:var(--amber);margin-bottom:8px}
  .pending-allocs{font-size:13px;color:var(--text);display:flex;gap:14px;flex-wrap:wrap;margin-bottom:14px}
  .pending-actions{display:flex;gap:8px;flex-wrap:wrap}
  .metrics{display:grid;grid-template-columns:repeat(4,1fr);gap:1px;background:var(--border);border:1px solid var(--border);border-radius:8px;overflow:hidden;margin-bottom:16px}
  .metric{background:var(--surface);padding:14px 16px}
  .metric-label{font-size:10px;letter-spacing:.1em;text-transform:uppercase;color:var(--muted);margin-bottom:6px}
  .metric-value{font-family:var(--font-display);font-size:22px;font-weight:700;letter-spacing:-0.02em;line-height:1}
  .metric-sub{font-size:11px;color:var(--muted);margin-top:3px}
  .pos{color:var(--accent)}.neg{color:var(--red)}
  .chart-section{background:var(--surface);border:1px solid var(--border);border-radius:8px;margin-bottom:16px;overflow:hidden}
  .chart-header{display:flex;align-items:center;justify-content:space-between;padding:12px 14px;border-bottom:1px solid var(--border);flex-wrap:wrap;gap:8px}
  .panel-title{font-size:10px;letter-spacing:.1em;text-transform:uppercase;color:var(--muted);font-weight:500}
  .chart-controls{display:flex;gap:6px;flex-wrap:wrap;align-items:center}
  .ctrl-group{display:flex;gap:2px;background:var(--bg);border:1px solid var(--border);border-radius:4px;padding:2px}
  .ctrl-btn{font-size:11px;font-family:var(--font-mono);padding:4px 9px;border-radius:3px;cursor:pointer;color:var(--muted);border:none;background:none;transition:all .15s;letter-spacing:.04em;white-space:nowrap}
  .ctrl-btn.active{background:var(--surface2);color:var(--text)}
  .chart-body{padding:14px}
  .chart-legend{display:flex;gap:14px;margin-bottom:10px;flex-wrap:wrap}
  .legend-item{display:flex;align-items:center;gap:5px;font-size:11px;color:var(--muted)}
  .legend-dot{width:8px;height:8px;border-radius:50%;flex-shrink:0}
  .chart-wrap{position:relative;width:100%;height:220px}
  .grid-2{display:grid;grid-template-columns:1fr 1fr;gap:14px;margin-bottom:16px}
  .panel{background:var(--surface);border:1px solid var(--border);border-radius:8px;overflow:hidden}
  .panel-header{display:flex;align-items:center;justify-content:space-between;padding:11px 14px;border-bottom:1px solid var(--border)}
  .signal-time{font-size:11px;color:var(--muted)}
  .pos-table{width:100%;border-collapse:collapse}
  .pos-table th{font-size:10px;letter-spacing:.08em;text-transform:uppercase;color:var(--muted);font-weight:500;padding:9px 14px;text-align:left;border-bottom:1px solid var(--border)}
  .pos-table th:not(:first-child){text-align:right}
  .pos-table td{padding:11px 14px;border-bottom:1px solid var(--border);font-size:13px}
  .pos-table td:not(:first-child){text-align:right}
  .pos-table tr:last-child td{border-bottom:none}
  .pos-table tr:hover td{background:var(--surface2)}
  .coin-badge{display:inline-flex;align-items:center;gap:6px;font-family:var(--font-display);font-weight:600;font-size:13px}
  .coin-dot{width:6px;height:6px;border-radius:50%;flex-shrink:0}
  .mode-spot{background:rgba(200,245,99,0.12);color:#c8f563;border:1px solid rgba(200,245,99,0.3);border-radius:3px;padding:1px 5px;font-size:10px;letter-spacing:.04em;font-family:var(--font-mono)}
  .mode-perp{background:rgba(91,156,246,0.12);color:#5b9cf6;border:1px solid rgba(91,156,246,0.3);border-radius:3px;padding:1px 5px;font-size:10px;letter-spacing:.04em;font-family:var(--font-mono)}
  .mode-perp-lev{background:rgba(245,166,35,0.15);color:#f5a623;border:1px solid rgba(245,166,35,0.4);border-radius:3px;padding:1px 5px;font-size:10px;letter-spacing:.04em;font-family:var(--font-mono);font-weight:600}
  .liq-warn{font-size:10px;color:var(--red);opacity:.8}
  .notional-row{font-size:10px;color:var(--muted);margin-top:2px}
  .alloc-list{padding:6px 0}
  .alloc-row{display:flex;align-items:center;gap:10px;padding:9px 14px;border-bottom:1px solid var(--border);transition:background .15s}
  .alloc-row:last-child{border-bottom:none}
  .alloc-row:hover{background:var(--surface2)}
  .alloc-pct{font-family:var(--font-display);font-weight:700;font-size:17px;color:var(--accent);min-width:56px;letter-spacing:-0.02em}
  .alloc-bar-wrap{flex:1;height:3px;background:var(--border2);border-radius:2px;overflow:hidden}
  .alloc-bar{height:100%;background:var(--accent);border-radius:2px}
  .alloc-asset{font-family:var(--font-display);font-weight:600;font-size:13px;min-width:52px;text-align:right}
  .alloc-type{font-size:10px;color:var(--muted);min-width:32px;text-align:right;letter-spacing:.06em;text-transform:uppercase}
  .actions{display:flex;gap:8px;flex-wrap:wrap;margin-bottom:16px}
  .btn{font-family:var(--font-mono);font-size:11px;letter-spacing:.06em;text-transform:uppercase;padding:8px 14px;border-radius:5px;cursor:pointer;border:1px solid var(--border2);background:var(--surface);color:var(--text);text-decoration:none;display:inline-flex;align-items:center;gap:6px;transition:all .15s}
  .btn:hover{background:var(--surface2)}
  .btn-approve{background:var(--accent-dim);border-color:rgba(200,245,99,.35);color:var(--accent)}
  .btn-approve:hover{background:rgba(200,245,99,.2)}
  .btn-danger{background:var(--red-dim);border-color:rgba(255,92,92,.35);color:var(--red)}
  .btn-accent{background:var(--accent-dim);border-color:rgba(200,245,99,.35);color:var(--accent)}
  .btn-accent:hover{background:rgba(200,245,99,.2)}
  .btn-export{background:var(--blue-dim);border-color:rgba(91,156,246,.35);color:var(--blue)}
  /* leverage panel */
  .lev-row{display:flex;align-items:center;gap:12px;padding:8px 0;border-bottom:1px solid var(--border)}
  .lev-row:last-child{border-bottom:none}
  .lev-asset{font-family:var(--font-display);font-weight:600;min-width:60px;font-size:14px}
  .lev-toggle{position:relative;width:36px;height:20px;flex-shrink:0;cursor:pointer}
  .lev-toggle input{opacity:0;width:0;height:0;position:absolute}
  .lev-track{position:absolute;inset:0;border-radius:10px;background:var(--border2);transition:.2s}
  .lev-toggle input:checked~.lev-track{background:var(--accent)}
  .lev-thumb{position:absolute;width:14px;height:14px;left:3px;top:3px;border-radius:50%;background:white;transition:.2s;pointer-events:none}
  .lev-toggle input:checked~.lev-thumb{transform:translateX(16px)}
  .lev-slider{flex:1;accent-color:var(--accent);cursor:pointer;height:4px;min-width:80px}
  .lev-value{font-family:var(--font-display);font-size:16px;font-weight:700;min-width:36px;text-align:right}
  .lev-spot{color:var(--muted)}
  .lev-active{color:var(--accent)}
  .lev-mode-tag{font-size:10px;padding:2px 6px;border-radius:3px;min-width:40px;text-align:center}
  .lev-mode-spot{background:var(--surface3);color:var(--muted);border:1px solid var(--border)}
  .lev-mode-perp{background:var(--accent-dim);color:var(--accent);border:1px solid rgba(200,245,99,.25)}
  .footer{padding:14px 20px;border-top:1px solid var(--border);display:flex;justify-content:space-between;align-items:center;font-size:11px;color:var(--muted);flex-wrap:wrap;gap:6px}
  .no-pos{padding:20px 14px;color:var(--muted);font-size:12px;text-align:center}
  .toggle-pill{display:inline-flex;align-items:center;gap:6px;font-size:10px;font-family:var(--font-mono);letter-spacing:.06em;text-transform:uppercase;color:var(--muted);cursor:pointer;padding:3px 8px 3px 6px;border:1px solid var(--border);border-radius:20px;background:none;transition:all .15s;user-select:none}
  .toggle-pill:hover{border-color:var(--border2);color:var(--text)}
  .toggle-pill.active{background:var(--accent-dim);border-color:rgba(200,245,99,.35);color:var(--accent)}
  .toggle-pill .pip{width:6px;height:6px;border-radius:50%;background:currentColor;opacity:.5;transition:opacity .15s}
  .toggle-pill.active .pip{opacity:1}
  .dust-count{font-size:10px;color:var(--muted);margin-left:2px}
  @media(max-width:600px){
    .header{padding:10px 14px}
    .main{padding:12px 14px}
    .metrics{grid-template-columns:1fr 1fr}
    .metric{padding:12px 12px}
    .metric-value{font-size:18px}
    .grid-2{grid-template-columns:1fr}
    .chart-wrap{height:180px}
    .pos-table .hide-mobile{display:none}
    .pending-actions .btn{flex:1;justify-content:center;padding:12px 8px;font-size:12px}
    .actions .btn{padding:10px 12px}
  }
  @media(max-width:480px){
    .logo{display:none}
    .header-badges{gap:4px}
    .badge{font-size:9px;padding:2px 5px}
  }
  @media(max-width:380px){
    .metrics{grid-template-columns:1fr}
    .header-badges{display:none}
  }
  ::-webkit-scrollbar{width:4px;height:4px}
  ::-webkit-scrollbar-thumb{background:var(--border2);border-radius:2px}
</style>
</head>
<body>
<div class="header">
  <div class="header-left">
    <div class="pulse-dot"></div>
    <div class="logo">signal<span>bot</span></div>
    <div class="tab-nav">
      <a class="tab-btn" id="portfolioTab" href="?action=portfolio">Portfolio</a>
      <a class="tab-btn active" id="dashTab" href="?">RSPS</a>
    <a class="tab-btn" id="histTab" href="?action=history">History</a>
    <a class="tab-btn" id="stratTab" href="?action=strategies">Strategies</a>
    </div>
  </div>
  <div class="header-badges" id="badges"></div>
</div>
<div class="main">
  <div class="pending-banner" id="pendingBanner" style="display:none">
    <div class="pending-label">Approval required</div>
    <div class="pending-allocs" id="pendingAllocs"></div>
    <div class="pending-actions">
      <a class="btn btn-approve" id="approveBtn" style="flex:1;justify-content:center;padding:12px 8px">Approve &amp; execute</a>
      <a class="btn" id="dismissBtn" style="color:var(--muted)">Dismiss</a>
    </div>
  </div>
  <div class="metrics">
    <div class="metric"><div class="metric-label">Account value</div><div class="metric-value" id="accountValue">—</div><div class="metric-sub">spot + perp unified</div></div>
    <div class="metric"><div class="metric-label">Unrealised PnL</div><div class="metric-value" id="totalPnl">—</div><div class="metric-sub">open positions</div></div>
    <div class="metric"><div class="metric-label">Positions</div><div class="metric-value" id="posCount">—</div><div class="metric-sub">open positions</div></div>
    <div class="metric"><div class="metric-label">All-time PnL</div><div class="metric-value" id="allTimePnl">—</div><div class="metric-sub" id="allTimePnlSub">since first record</div></div>

  </div>
  <div class="chart-section">
    <div class="chart-header">
      <div class="panel-title">Equity curve</div>
      <div class="chart-controls">
        <div class="ctrl-group" id="seriesTabs">
          <button class="ctrl-btn active" onclick="setSeries('actual',this)">Actual</button>
          <button class="ctrl-btn" onclick="setSeries('barclose',this)">Daily open</button>
          <button class="ctrl-btn" onclick="setSeries('both',this)">Both</button>
        </div>
        <div class="ctrl-group" id="rangeTabs">
          <button class="ctrl-btn active" onclick="setRange('7d',this)">7d</button>
          <button class="ctrl-btn" onclick="setRange('30d',this)">30d</button>
          <button class="ctrl-btn" onclick="setRange('all',this)">All</button>
        </div>
        <button class="btn btn-export" onclick="exportCSV()" style="padding:4px 10px;font-size:11px">Export CSV</button>
      </div>
    </div>
    <div class="chart-body">
      <div class="chart-legend" id="chartLegend"></div>
      <div class="chart-wrap" id="chartWrap"><canvas id="equityChart"></canvas></div>
      <div id="noHistory" style="display:none;text-align:center;padding:32px 0;color:var(--muted);font-size:12px">No equity history yet — data accumulates as the bot runs</div>
    </div>
  </div>
  <div class="grid-2">
    <div class="panel">
      <div class="panel-header"><div class="panel-title">Positions</div><button class="toggle-pill active" id="dustToggle" onclick="toggleDust(this)"><span class="pip"></span>Show dust<span class="dust-count" id="dustCount"></span></button></div>
      <div id="positionsBody"><div class="no-pos">Loading...</div></div>
    </div>
    <div class="panel">
      <div class="panel-header"><div class="panel-title">Latest signal</div><div class="signal-time" id="signalTime"></div></div>
      <div class="alloc-list" id="allocList"><div class="no-pos">Loading...</div></div>
    </div>
  </div>
  <div class="actions">
    <a href="?action=force" class="btn btn-danger" id="forceBtn" onclick="return confirm('Force rebalance now?')">Force rebalance</a>
    <a href="?action=health" class="btn">Health check</a>
    <a href="?" class="btn" id="refreshBtn">Refresh</a>
    <button class="btn" onclick="toggleLeverage()">⚙ Leverage</button>
  </div>

  <!-- Leverage settings panel -->
  <div id="leveragePanel" style="display:none;margin-bottom:16px">
    <div class="panel">
      <div class="panel-header">
        <div class="panel-title">Leverage settings — per asset</div>
        <span style="font-size:11px;color:var(--muted)">1× = spot · &gt;1× = perp with leverage · persists between signals</span>
      </div>
      <div style="padding:14px">
        <div id="leverageAssets" style="display:flex;flex-direction:column;gap:12px"></div>
        <div style="display:flex;gap:8px;margin-top:14px;padding-top:12px;border-top:1px solid var(--border)">
          <button class="btn btn-accent" onclick="saveLeverage()">Save settings</button>
          <span id="leverageSaveStatus" style="font-size:11px;color:var(--muted);align-self:center"></span>
        </div>
        <div style="font-size:10px;color:var(--muted2);margin-top:8px;line-height:1.6">
          ⚠️ Leverage applies to the next rebalance. Increasing leverage on an existing spot position
          will close the spot and open a perp. Use with caution — liquidation risk increases with leverage.
        </div>
      </div>
    </div>
  </div>
</div>
<div class="footer">
  <span id="lastActed">Last acted: —</span>
  <span id="footerTime"></span>
</div>
<script>
// ── Cloud-only equity storage ──────────────────────────────────────────────
// Single source of truth: Modal Dict, written by:
//   1. daily_equity_snapshot cron at 23:55 UTC every day (primary)
//   2. check_signal polls ~54x/day
//   3. equity_upsert on every dashboard page load (this code below)
//
// No localStorage involvement — every device reads the same cloud data.
// localStorage is only used as a render cache to avoid blank chart while
// the async fetch completes (cleared/overwritten on every load).

const _authParam = new URLSearchParams(window.location.search).get('auth')||'';
function _ap(){return _authParam?'&auth='+encodeURIComponent(_authParam):'';}

async function fetchCloudEquity(){
  try{
    const r=await fetch('?action=equity_history'+_ap());
    if(!r.ok) return [];
    const d=await r.json();
    return Array.isArray(d)?d:[];
  }catch{return[];}
}

async function fetchBcEquity(){
  try{
    const r=await fetch('?action=bc_equity_history'+_ap());
    if(!r.ok) return [];
    const d=await r.json();
    return Array.isArray(d)?d:[];
  }catch{return[];}
}

// Push current account value to cloud via upsert endpoint
async function upsertCloudEquity(value){
  if(value<=0) return;
  try{
    await fetch(`?action=equity_upsert${_ap()}&v=${value.toFixed(2)}`);
  }catch{}
}

// Convert cloud [{ts,v}] → [{date,value}], one point per date (last wins)
function cloudToSeries(snaps){
  const m={};
  for(const s of snaps){
    const date=new Date(s.ts).toISOString().slice(0,10);
    m[date]=s.v;
  }
  return Object.entries(m).sort((a,b)=>a[0]<b[0]?-1:1).map(([date,value])=>({date,value}));
}

let fullA=[], fullB=[], _cloudLoaded=false;

async function initEquity(accountValue){
  // Upsert today's value to cloud immediately
  if(accountValue>0) upsertCloudEquity(accountValue);

  // Fetch full history from cloud (actual + daily-open in parallel)
  const [cloudSnaps, bcSnaps] = await Promise.all([
    fetchCloudEquity(),
    fetchBcEquity(),
  ]);

  fullA = cloudToSeries(cloudSnaps);
  fullB = cloudToSeries(bcSnaps);
  _cloudLoaded = true;
  if(chart){chart.destroy();chart=null;}
  buildChart();

  // All-time PnL vs first recorded point
  const _atEl=document.getElementById('allTimePnl');
  const _atSub=document.getElementById('allTimePnlSub');
  if(fullA.length>=2){
    const first=fullA[0].value;
    const pnl=accountValue-first;
    const pct=pnl/first*100;
    if(_atEl){_atEl.textContent=(pnl>=0?'+':'')+fmt$(pnl);_atEl.className='metric-value '+(pnl>=0?'pos':'neg')}
    if(_atSub){_atSub.textContent=(pct>=0?'+':'')+pct.toFixed(1)+'%  since '+fullA[0].date}
  } else {
    if(_atEl){_atEl.textContent='—';_atEl.className='metric-value'}
    if(_atSub){_atSub.textContent='accumulating history…'}
  }
}

function filterH(h,r){
  if(r==='all')return h;
  const d=r==='7d'?7:30;
  const c=new Date();c.setDate(c.getDate()-d);
  const cs=c.toISOString().slice(0,10);
  return h.filter(p=>p.date>=cs);
}

let chart=null, range='7d', series='actual';
function fmt$(v){return'$'+parseFloat(v).toLocaleString('en-US',{minimumFractionDigits:2,maximumFractionDigits:2})}
function buildLegend(a,b){
  const el=document.getElementById('chartLegend');
  let h='';
  if(a)h+='<div class="legend-item"><div class="legend-dot" style="background:#c8f563"></div>Actual equity</div>';
  if(b)h+='<div class="legend-item"><div class="legend-dot" style="background:#c084fc"></div>Daily open equity</div>';
  if(a&&b)h+='<div class="legend-item" style="color:#888;font-size:10px">gap = intraday timing vs daily open</div>';
  el.innerHTML=h;
}
function buildChart(){
  const showA=series==='actual'||series==='both';
  const showB=series==='barclose'||series==='both';
  const fa=filterH(fullA,range);const fb=filterH(fullB,range);
  buildLegend(showA&&fa.length>0,showB&&fb.length>0);
  const noH=document.getElementById('noHistory');const wrap=document.getElementById('chartWrap');
  const has=(showA&&fa.length>=2)||(showB&&fb.length>=2);
  if(!has){noH.style.display='block';wrap.style.display='none';return}
  noH.style.display='none';wrap.style.display='block';
  const allDates=[...new Set([...(showA?fa:[]).map(p=>p.date),...(showB?fb:[]).map(p=>p.date)])].sort();
  const labels=allDates.map(d=>{const dt=new Date(d+'T12:00:00Z');return dt.toLocaleDateString('en-GB',{day:'numeric',month:'short'})});
  const toMap=arr=>Object.fromEntries(arr.map(p=>[p.date,p.value]));
  const aMap=toMap(fa);const bMap=toMap(fb);
  const datasets=[];
  if(showA&&fa.length>=2){const data=allDates.map(d=>aMap[d]??null);const up=fa[fa.length-1].value>=fa[0].value;datasets.push({label:'Actual',data,borderColor:up?'#c8f563':'#ff5c5c',backgroundColor:up?'rgba(200,245,99,0.06)':'rgba(255,92,92,0.06)',borderWidth:1.5,pointRadius:allDates.length>30?0:3,pointHoverRadius:5,pointBackgroundColor:up?'#c8f563':'#ff5c5c',fill:series==='actual',tension:0.35,spanGaps:true})}
  if(showB&&fb.length>=2){datasets.push({label:'Bar close',data:allDates.map(d=>bMap[d]??null),borderColor:'#c084fc',backgroundColor:'rgba(192,132,252,0.06)',borderWidth:1.5,borderDash:[4,3],pointRadius:allDates.length>30?0:3,pointHoverRadius:5,pointBackgroundColor:'#c084fc',fill:series==='barclose',tension:0.35,spanGaps:true})}
  if(chart){chart.data.labels=labels;chart.data.datasets=datasets;chart.update('active');return}
  chart=new Chart(document.getElementById('equityChart'),{type:'line',data:{labels,datasets},options:{responsive:true,maintainAspectRatio:false,interaction:{mode:'index',intersect:false},plugins:{legend:{display:false},tooltip:{backgroundColor:'#1a1a1a',borderColor:'rgba(255,255,255,0.1)',borderWidth:1,titleColor:'#666',bodyColor:'#f0ede8',titleFont:{family:'DM Mono',size:11},bodyFont:{family:'DM Mono',size:12},callbacks:{label:ctx=>{const pre=ctx.dataset.label==='Bar close'?' Daily open: ':' Actual:     ';return pre+fmt$(ctx.parsed.y)}}}},scales:{x:{grid:{color:'rgba(255,255,255,0.04)'},ticks:{color:'#555',font:{family:'DM Mono',size:11},maxTicksLimit:7},border:{display:false}},y:{position:'right',grid:{color:'rgba(255,255,255,0.04)'},ticks:{color:'#555',font:{family:'DM Mono',size:11},callback:v=>'$'+v.toLocaleString()},border:{display:false}}}}});
}
function setRange(r,el){range=r;document.querySelectorAll('#rangeTabs .ctrl-btn').forEach(b=>b.classList.remove('active'));el.classList.add('active');if(chart){chart.destroy();chart=null}buildChart()}
function setSeries(s,el){series=s;document.querySelectorAll('#seriesTabs .ctrl-btn').forEach(b=>b.classList.remove('active'));el.classList.add('active');if(chart){chart.destroy();chart=null}buildChart()}
function exportCSV(){
  const a=fullA;const b=fullB;
  if(!a.length&&!b.length){alert('No equity history yet.');return}
  const dates=[...new Set([...a.map(p=>p.date),...b.map(p=>p.date)])].sort();
  const am=Object.fromEntries(a.map(p=>[p.date,p.value]));
  const bm=Object.fromEntries(b.map(p=>[p.date,p.value]));
  const rows=[['date','actual_equity_usd','daily_open_equity_usd']];
  for(const d of dates)rows.push([d,am[d]??'',bm[d]??'']);
  const csv=rows.map(r=>r.join(',')).join('\n');
  const blob=new Blob([csv],{type:'text/csv'});
  const url=URL.createObjectURL(blob);
  const a2=document.createElement('a');a2.href=url;a2.download='equity_'+new Date().toISOString().slice(0,10)+'.csv';a2.click();URL.revokeObjectURL(url);
}
const DUST_USD=0.5;
let _hideDust=true;
let _positions=[];
function fmtSize(size,markPx){
  // Choose decimal places based on price magnitude so dust doesn't read as "0.0100"
  const s=parseFloat(size);
  if(markPx>=10000)return s.toFixed(5);   // BTC: 0.00123
  if(markPx>=1000) return s.toFixed(4);   // ETH: 0.0100 → still 4dp but correct
  if(markPx>=10)   return s.toFixed(3);
  return s.toFixed(2);
}
function fmtPx(v){
  const n=parseFloat(v);
  if(n>=1000)return'$'+n.toLocaleString('en-US',{minimumFractionDigits:0,maximumFractionDigits:0});
  if(n>=1)   return'$'+n.toFixed(2);
  return'$'+n.toFixed(4);
}
function renderPositions(){
  const pb=document.getElementById('positionsBody');
  const dustPos=_positions.filter(p=>p.value<DUST_USD);
  const visPos=_hideDust?_positions.filter(p=>p.value>=DUST_USD):_positions;
  const dc2=document.getElementById('dustCount');
  if(dc2)dc2.textContent=dustPos.length>0?` (${dustPos.length})`:'';
  document.getElementById('posCount').textContent=visPos.length+(_hideDust&&dustPos.length>0?` +${dustPos.length} dust`:'');
  const dc=['#c8f563','#5b9cf6','#f5a623','#ff5c5c','#c084fc'];
  if(!visPos.length){pb.innerHTML=`<div class="no-pos">${_positions.length?'No significant positions — off risk':'No open positions'}</div>`;return;}
  pb.innerHTML=`<table class="pos-table"><thead><tr>
    <th>Asset</th>
    <th class="hide-mobile">Mode</th>
    <th class="hide-mobile">Size</th>
    <th class="hide-mobile">Entry → Mark</th>
    <th>Value</th>
    <th>PnL</th>
  </tr></thead><tbody>${visPos.map((p,i)=>{
    const markPx   = p.markPx || p.entryPx || 0;
    const lev      = (_leverageSettings[p.coin] || 1);
    const isLev    = p.mode === 'perp' && lev > 1;

    // Mode tag
    let modeTag;
    if (p.mode === 'spot') {
      modeTag = '<span class="mode-spot">SPOT</span>';
    } else if (isLev) {
      modeTag = `<span class="mode-perp-lev">PERP ${lev}×</span>`;
    } else {
      modeTag = '<span class="mode-perp">PERP 1×</span>';
    }

    // Size + notional for leveraged positions
    const sizeStr  = fmtSize(p.size, markPx);
    const notional = isLev ? p.value * lev : null;  // total exposure
    const margin   = isLev ? p.value : null;         // actual margin used
    const sizeCell = notional
      ? `<div style="font-variant-numeric:tabular-nums">${sizeStr}</div>
         <div class="notional-row">notional: ${fmt$(notional)}</div>
         <div class="notional-row">margin: ${fmt$(margin)}</div>`
      : `<div style="font-variant-numeric:tabular-nums">${sizeStr}</div>`;

    // Entry → Mark
    const entryMark = `<span style="color:var(--muted)">${fmtPx(p.entryPx)}</span><span style="color:var(--muted2)"> → </span>${fmtPx(markPx)}`;

    // Liquidation distance estimate (for leveraged perps)
    // Rough estimate: liq ≈ entry × (1 - 1/lev + maintenance_margin)
    // HL maintenance margin ≈ 3% for cross margin
    let liqStr = '';
    if (isLev && p.entryPx > 0 && markPx > 0) {
      const maintenanceMargin = 0.03;
      const liqPx  = p.entryPx * (1 - (1/lev) + maintenanceMargin);
      const distPct = ((markPx - liqPx) / markPx * 100);
      if (distPct > 0) {
        const color  = distPct < 15 ? 'var(--red)' : distPct < 30 ? 'var(--amber)' : 'var(--muted2)';
        liqStr = `<div style="font-size:10px;color:${color};margin-top:2px">liq ~${fmtPx(liqPx)} (${distPct.toFixed(1)}% away)</div>`;
      }
    }

    // PnL: dollar + percent
    const costBasis = p.entryPx > 0 ? parseFloat(p.size) * p.entryPx : p.value - p.pnl;
    const pnlPct    = costBasis > 0 ? (p.pnl / costBasis) * 100 : 0;
    const pnlStr    = (p.pnl>=0?'+':'')+fmt$(p.pnl)
      + (costBasis>0?` <span style="font-size:10px;opacity:.7">(${pnlPct>=0?'+':''}${pnlPct.toFixed(2)}%)</span>`:'');

    return`<tr>
      <td><span class="coin-badge"><span class="coin-dot" style="background:${dc[i%dc.length]}"></span>${p.coin}</span></td>
      <td class="hide-mobile">${modeTag}${liqStr}</td>
      <td class="hide-mobile">${sizeCell}</td>
      <td class="hide-mobile" style="font-size:12px">${entryMark}</td>
      <td style="color:${p.value<DUST_USD?'var(--muted)':'inherit'}">${fmt$(p.value)}</td>
      <td class="${p.pnl>=0?'pos':'neg'}">${pnlStr}</td>
    </tr>`;
  }).join('')}</tbody></table>`;
}
function toggleDust(btn){
  _hideDust=!_hideDust;
  btn.classList.toggle('active',_hideDust);
  btn.childNodes[1].textContent=_hideDust?'Show dust':'Hide dust';
  renderPositions();
}
function init(d){
  const{account,positions,signal,pending,lastActedId,trwOk,hlOk,isAuto,approvalToken}=d;
  document.getElementById('badges').innerHTML=`<span class="badge ${trwOk?'badge-ok':'badge-err'}">TRW ${trwOk?'OK':'ERR'}</span><span class="badge ${hlOk?'badge-ok':'badge-err'}">HL ${hlOk?'OK':'ERR'}</span><span class="badge ${isAuto?'badge-auto':'badge-manual'}" title="${isAuto?'Autonomous 00:00–05:00 UK':'Approval required 05:00–00:00 UK'}">${isAuto?'Auto 00–05':'Approval'}</span>`;
  const tp=positions.reduce((s,p)=>s+p.pnl,0);
  document.getElementById('accountValue').textContent=fmt$(account.value);
  document.getElementById('totalPnl').textContent=(tp>=0?'+':'')+fmt$(tp);
  document.getElementById('totalPnl').className='metric-value '+(tp>=0?'pos':'neg');

  // Render positions and signal immediately (no async dependency)
  _positions=positions;
  renderPositions();
  const al=document.getElementById('allocList');const st=document.getElementById('signalTime');
  if(signal&&signal.allocations&&signal.allocations.length){st.textContent=signal.time||'';al.innerHTML=signal.allocations.map(a=>`<div class="alloc-row"><div class="alloc-pct">${a.percent}%</div><div class="alloc-bar-wrap"><div class="alloc-bar" style="width:${a.percent}%"></div></div><div class="alloc-asset">${a.asset}</div><div class="alloc-type">${a.type}</div></div>`).join('')}
  else{al.innerHTML='<div class="no-pos">No signal found</div>'}
  if(pending&&approvalToken){const bn=document.getElementById('pendingBanner');bn.style.display='block';document.getElementById('pendingAllocs').innerHTML=pending.map(a=>`<span><strong>${a.percent}%</strong> ${a.asset}</span>`).join('');document.getElementById('approveBtn').href='?action=approve&token='+approvalToken;document.getElementById('approveBtn').onclick=()=>confirm('Execute rebalance now?');document.getElementById('dismissBtn').href='?action=dismiss&token='+approvalToken}
  const forceBtn=document.getElementById('forceBtn');
  if(forceBtn&&approvalToken)forceBtn.href='?action=force&token='+approvalToken;

  // Auth-preserving links
  const _auth=new URLSearchParams(window.location.search).get('auth')||'';
  if(_auth){
    document.querySelectorAll('a[href^="?"]').forEach(a=>{
      if(!a.href.includes('auth='))a.href+=(a.href.includes('?')&&a.href!=='?'?'&':'?')+'auth='+encodeURIComponent(_auth);
    });
    const histTab=document.getElementById('histTab');
    if(histTab)histTab.href='?action=history&auth='+encodeURIComponent(_auth);
  }
  document.getElementById('lastActed').textContent='Last acted: '+(lastActedId&&lastActedId!=='none'?lastActedId.slice(0,12)+'...':'none');
  document.getElementById('footerTime').textContent=new Date().toLocaleString('en-GB',{timeZone:'UTC'})+' UTC';

  // Load leverage settings from server
  _leverageSettings = d.leverageSettings || {};
  _currentSignalAssets = (signal&&signal.allocations ? signal.allocations.map(a=>a.asset).filter(a=>a!=='USDC') : []);

  // Equity chart: fetch from cloud and render (async)
  initEquity(account.value);
}

// ── Leverage panel — declare vars before init() runs ─────────────────────────
let _leverageSettings = {};
let _leveragePanelOpen = false;
let _currentSignalAssets = [];

init(DASHBOARD_DATA);

function toggleLeverage(){
  _leveragePanelOpen = !_leveragePanelOpen;
  document.getElementById('leveragePanel').style.display = _leveragePanelOpen ? 'block' : 'none';
  if(_leveragePanelOpen) renderLeveragePanel();
}

function renderLeveragePanel(){
  const container = document.getElementById('leverageAssets');
  const assets = new Set([
    ..._currentSignalAssets,
    ..._positions.filter(p=>p.coin!=='USDC').map(p=>p.coin)
  ]);
  assets.delete('USDC');
  if(!assets.size){
    container.innerHTML = '<div style="color:var(--muted);font-size:12px">No assets in current signal or positions</div>';
    return;
  }
  container.innerHTML = [...assets].map(asset => {
    const lev = _leverageSettings[asset] || 1;
    const isLev = lev > 1;
    return `<div class="lev-row" id="levrow-${asset}">
      <div class="lev-asset">${asset}</div>
      <label class="lev-toggle" title="${isLev?'Leveraged perp':'Spot'}">
        <input type="checkbox" id="levtoggle-${asset}" ${isLev?'checked':''} onchange="onLevToggle('${asset}')">
        <div class="lev-track"></div>
        <div class="lev-thumb"></div>
      </label>
      <input type="range" class="lev-slider" id="levslider-${asset}"
        min="2" max="20" step="1" value="${Math.max(2,lev)}"
        ${isLev?'':'disabled style="opacity:.3"'}
        oninput="onLevSlider('${asset}',this.value)">
      <div class="lev-value ${isLev?'lev-active':'lev-spot'}" id="levval-${asset}">${isLev?lev+'×':'Spot'}</div>
      <span class="lev-mode-tag ${isLev?'lev-mode-perp':'lev-mode-spot'}" id="levmode-${asset}">${isLev?'PERP':'SPOT'}</span>
    </div>`;
  }).join('');
}

function onLevToggle(asset){
  const cb  = document.getElementById('levtoggle-'+asset);
  const sl  = document.getElementById('levslider-'+asset);
  const val = document.getElementById('levval-'+asset);
  const tag = document.getElementById('levmode-'+asset);
  const isLev = cb.checked;
  if(isLev){
    const lev = Math.max(2, parseInt(sl.value)||2);
    sl.value = lev; sl.disabled = false; sl.style.opacity = '1';
    val.textContent = lev+'×'; val.className = 'lev-value lev-active';
    tag.textContent = 'PERP'; tag.className = 'lev-mode-tag lev-mode-perp';
    _leverageSettings[asset] = lev;
  } else {
    sl.disabled = true; sl.style.opacity = '.3';
    val.textContent = 'Spot'; val.className = 'lev-value lev-spot';
    tag.textContent = 'SPOT'; tag.className = 'lev-mode-tag lev-mode-spot';
    _leverageSettings[asset] = 1;
  }
}

function onLevSlider(asset, rawVal){
  const lev = parseInt(rawVal);
  document.getElementById('levval-'+asset).textContent = lev+'×';
  _leverageSettings[asset] = lev;
}

async function saveLeverage(){
  const status = document.getElementById('leverageSaveStatus');
  status.textContent = 'Saving…'; status.style.color = 'var(--muted)';
  try{
    const encoded = encodeURIComponent(JSON.stringify(_leverageSettings));
    const r = await fetch('?action=leverage_save'+_ap()+'&points='+encoded);
    const d = await r.json();
    if(d.ok){
      status.textContent = '✓ Saved — applies to next rebalance';
      status.style.color = 'var(--accent)';
    } else {
      status.textContent = 'Error: '+(d.error||'unknown');
      status.style.color = 'var(--red)';
    }
  }catch(e){
    status.textContent = 'Save failed';
    status.style.color = 'var(--red)';
  }
  setTimeout(()=>{ status.textContent=''; }, 5000);
}

let _refreshTimer = null;
const REFRESH_MS = 60000;

function startRefresh() {
  if (_refreshTimer) return;
  _refreshTimer = setInterval(() => {
    if (!document.hidden) {
      const btn = document.getElementById('refreshBtn');
      if (btn) { btn.textContent = 'Refreshing...'; btn.style.opacity = '0.5'; }
      const _auth=new URLSearchParams(window.location.search).get('auth')||'';
      window.location.href = _auth ? '?auth='+encodeURIComponent(_auth) : '?';
    }
  }, REFRESH_MS);
}

function stopRefresh() {
  clearInterval(_refreshTimer);
  _refreshTimer = null;
}

document.addEventListener('visibilitychange', () => {
  document.hidden ? stopRefresh() : startRefresh();
});

startRefresh();

const _footer = document.getElementById('footerTime');
if (_footer) {
  let _secs = 0;
  setInterval(() => {
    _secs++;
    const remaining = Math.max(0, Math.round((REFRESH_MS - _secs * 1000) / 1000));
    const base = new Date().toLocaleString('en-GB', { timeZone: 'UTC' }) + ' UTC';
    _footer.textContent = base + '  ·  refresh in ' + remaining + 's';
  }, 1000);
}
</script>
</body>
</html>"""


def _render_dashboard(dash_state: dict | None = None) -> str:
    """Build dashboard HTML with live data + bar close equity injected as JSON."""
    ds = dash_state or {}

    signal_msg, parsed, signal_time, trw_ok = None, None, "N/A", False
    try:
        messages   = fetch_recent_messages(limit=20)
        signal_msg = find_latest_signal(messages)
        if signal_msg:
            parsed      = parse_signal(signal_msg["content"])
            signal_time = datetime.fromtimestamp(
                signal_msg["timestamp"] / 1000, tz=timezone.utc
            ).strftime("%Y-%m-%d %H:%M UTC")
            trw_ok = True
    except Exception:
        pass

    state = {"account_value": 0, "positions": {}}
    hl_ok = False
    try:
        info, _ = get_hl_clients()
        state   = get_account_state(info)
        hl_ok   = True
    except Exception as e:
        import traceback
        print(f"[dashboard] HL error:\n{traceback.format_exc()}")

    pending_allocs = None
    approval_token = ds.get("approval_token", "")
    try:
        pending_raw    = ds.get("pending_signal", "null")
        pending_parsed = json.loads(pending_raw)
        if pending_parsed:
            pending_allocs = pending_parsed.get("allocations", [])
    except Exception:
        pass

    last_acted_id = ds.get("last_signal_id", "none") or "none"

    lev_settings = json.loads(ds.get("leverage_settings") or "{}")
    positions_js = [
        {
            "coin":    coin,
            "size":    pos.get("size", 0),
            "entryPx": pos.get("entry_px", 0),
            "markPx":  pos.get("mark_px", pos.get("entry_px", 0)),
            "value":   pos.get("value_usd", 0),
            "pnl":     pos.get("unrealized_pnl", 0),
            "mode":    pos.get("mode", "perp"),
            "leverage": lev_settings.get(coin, 1),
        }
        for coin, pos in state.get("positions", {}).items()
    ]

    signal_js = None
    if parsed and parsed.get("allocations"):
        signal_js = {
            "time": signal_time,
            "allocations": [
                {"percent": a["percent"], "asset": a["asset"], "type": a.get("type", "Spot")}
                for a in parsed["allocations"]
            ],
        }

    dashboard_data = {
        "trwOk":            trw_ok,
        "hlOk":             hl_ok,
        "isAuto":           is_autonomous_hours(),
        "account":          {"value": state.get("account_value", 0)},
        "positions":        positions_js,
        "signal":           signal_js,
        "pending":          pending_allocs,
        "approvalToken":    approval_token,
        "lastActedId":      last_acted_id,
        "leverageSettings": json.loads(ds.get("leverage_settings") or "{}"),
    }

    data_json = json.dumps(dashboard_data)
    return _DASHBOARD_HTML.replace(
        "init(DASHBOARD_DATA);",
        f"const DASHBOARD_DATA = {data_json};\ninit(DASHBOARD_DATA);"
    )

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


def _render_history(auth: str = "") -> str:
    """Build the History tab HTML with auth token injected."""
    token = os.environ.get("TRW_SESSION_TOKEN", "")
    auth_param = f"&auth={auth}" if auth else ""
    html = _HISTORY_HTML
    # Inject session token so JS can call Binance/CoinGecko directly
    html = html.replace("__TRW_TOKEN_PLACEHOLDER__", token)
    html = html.replace("__AUTH_PARAM_PLACEHOLDER__", auth_param)
    return html


def _render_portfolio(auth: str = "", live_value: float = 0.0) -> str:
    """Build the Portfolio tab — main wealth overview across all strategies."""
    auth_param = f"&auth={auth}" if auth else ""
    html = _PORTFOLIO_HTML
    html = html.replace("__AUTH_PARAM_PLACEHOLDER__", auth_param)
    html = html.replace("__LIVE_VALUE_PLACEHOLDER__", str(live_value))
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

<div class="header">
  <div class="header-left">
    <div class="logo">signal<span>bot</span></div>
    <div class="tab-nav">
      <a class="tab-btn" id="portfolioTab" href="?action=portfolio__AUTH_PARAM_PLACEHOLDER__">Portfolio</a>
      <a class="tab-btn" id="dashTab" href="?__AUTH_PARAM_PLACEHOLDER__">RSPS</a>
      <a class="tab-btn active" href="#">History</a>
      <a class="tab-btn" id="stratTab" href="?action=strategies__AUTH_PARAM_PLACEHOLDER__">Strategies</a>
    </div>
  </div>
</div>

<div class="main">

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
    // Push backtest points to cloud storage (fills in pre-deployment history)
    await pushBacktestToCloud(timeline);
    // Reload cloud snaps to show updated banner
    await loadCloudEquity();
    renderChart();  // re-render with merged view updated
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
<style>
  @import url('https://fonts.googleapis.com/css2?family=DM+Mono:wght@400;500&family=Syne:wght@400;600;700;800&display=swap');
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
  .header{display:flex;align-items:center;justify-content:space-between;padding:16px 20px;border-bottom:1px solid var(--border);position:sticky;top:0;background:var(--bg);z-index:20;gap:10px;flex-wrap:wrap}
  .header-left{display:flex;align-items:center;gap:12px;min-width:0}
  .logo{font-family:var(--font-display);font-size:15px;font-weight:800;letter-spacing:-0.02em;white-space:nowrap}
  .logo span{color:var(--accent)}
  .tab-nav{display:flex;gap:1px;background:var(--border);border-radius:5px;overflow:hidden;padding:1px}
  .tab-btn{font-size:11px;font-family:var(--font-mono);letter-spacing:.06em;text-transform:uppercase;padding:5px 12px;border-radius:4px;cursor:pointer;color:var(--muted);border:none;background:none;transition:all .15s;white-space:nowrap;text-decoration:none;display:inline-block}
  .tab-btn.active{background:var(--surface2);color:var(--text)}
  .tab-btn:hover:not(.active){color:var(--text)}
  .main{padding:16px 20px;max-width:1200px;margin:0 auto}

  /* Hero value */
  .hero{padding:8px 0 24px}
  .hero-label{font-size:11px;letter-spacing:.12em;text-transform:uppercase;color:var(--muted);margin-bottom:8px}
  .hero-value{font-family:var(--font-display);font-size:52px;font-weight:800;letter-spacing:-0.03em;line-height:1}
  .hero-sub{display:flex;gap:18px;margin-top:12px;flex-wrap:wrap;font-size:13px}
  .hero-stat{display:flex;flex-direction:column;gap:1px}
  .hero-stat-label{font-size:10px;letter-spacing:.08em;text-transform:uppercase;color:var(--muted)}
  .hero-stat-val{font-family:var(--font-display);font-size:17px;font-weight:700}
  .pos{color:var(--accent)}.neg{color:var(--red)}

  /* Metric cards */
  .metrics{display:grid;grid-template-columns:repeat(4,1fr);gap:1px;background:var(--border);border:1px solid var(--border);border-radius:8px;overflow:hidden;margin-bottom:16px}
  .metric{background:var(--surface);padding:14px 16px}
  .metric-label{font-size:10px;letter-spacing:.1em;text-transform:uppercase;color:var(--muted);margin-bottom:6px}
  .metric-value{font-family:var(--font-display);font-size:20px;font-weight:700;letter-spacing:-0.02em;line-height:1}
  .metric-sub{font-size:11px;color:var(--muted);margin-top:3px}

  /* Chart */
  .panel{background:var(--surface);border:1px solid var(--border);border-radius:8px;margin-bottom:16px;overflow:hidden}
  .panel-header{display:flex;align-items:center;justify-content:space-between;padding:12px 14px;border-bottom:1px solid var(--border);flex-wrap:wrap;gap:8px}
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
  .chart-wrap{position:relative;width:100%;height:300px}
  .empty{padding:40px 20px;text-align:center;color:var(--muted);font-size:12px}

  /* Strategy allocation bars */
  .strat-grid{padding:14px;display:flex;flex-direction:column;gap:14px}
  .strat-row{display:flex;flex-direction:column;gap:6px}
  .strat-head{display:flex;align-items:center;justify-content:space-between;gap:10px}
  .strat-name{font-family:var(--font-display);font-weight:700;font-size:14px}
  .strat-desc{font-size:11px;color:var(--muted)}
  .strat-pct{font-family:var(--font-display);font-weight:700;font-size:16px}
  .strat-pct-input{width:74px;text-align:right;background:var(--surface2);border:1px solid var(--border2);border-radius:5px;color:var(--text);font-family:var(--font-display);font-weight:700;font-size:15px;padding:4px 8px;outline:none}
  .strat-pct-input:focus{border-color:rgba(200,245,99,.4)}
  .strat-bar-track{height:8px;background:var(--surface3);border-radius:4px;overflow:hidden}
  .strat-bar-fill{height:100%;border-radius:4px;transition:width .5s ease}
  .strat-meta{display:flex;justify-content:space-between;font-size:11px;color:var(--muted)}
  .strat-status{font-size:9px;padding:1px 6px;border-radius:3px;letter-spacing:.05em;text-transform:uppercase}
  .status-active{background:var(--accent-dim);color:var(--accent);border:1px solid rgba(200,245,99,.25)}
  .status-planned{background:var(--surface3);color:var(--muted);border:1px solid var(--border)}

  /* Cash flow table */
  .flow-table{width:100%;border-collapse:collapse}
  .flow-table th{font-size:10px;letter-spacing:.08em;text-transform:uppercase;color:var(--muted);font-weight:500;padding:9px 14px;text-align:left;border-bottom:1px solid var(--border);white-space:nowrap}
  .flow-table th:not(:first-child){text-align:right}
  .flow-table td{padding:10px 14px;border-bottom:1px solid var(--border);font-size:12px}
  .flow-table td:not(:first-child){text-align:right}
  .flow-table tr:last-child td{border-bottom:none}
  .flow-table tr:hover td{background:var(--surface2)}
  .flow-badge{font-size:9px;padding:1px 6px;border-radius:3px;letter-spacing:.04em}
  .flow-auto{background:var(--blue-dim);color:var(--blue);border:1px solid rgba(91,156,246,.25)}
  .flow-manual{background:var(--surface3);color:var(--muted);border:1px solid var(--border)}
  .flow-del{cursor:pointer;color:var(--muted2);font-size:14px;transition:color .15s}
  .flow-del:hover{color:var(--red)}

  /* Add flow form */
  .flow-form{display:flex;gap:8px;padding:12px 14px;border-top:1px solid var(--border);flex-wrap:wrap;align-items:end}
  .flow-field{display:flex;flex-direction:column;gap:4px}
  .flow-field label{font-size:10px;letter-spacing:.06em;text-transform:uppercase;color:var(--muted)}
  .flow-input{background:var(--surface2);border:1px solid var(--border2);border-radius:5px;color:var(--text);font-family:var(--font-mono);font-size:13px;padding:7px 10px;outline:none}
  .flow-input:focus{border-color:rgba(200,245,99,.4)}
  .btn{font-family:var(--font-mono);font-size:11px;letter-spacing:.06em;text-transform:uppercase;padding:8px 14px;border-radius:5px;cursor:pointer;border:1px solid var(--border2);background:var(--surface);color:var(--text);transition:all .15s}
  .btn:hover{background:var(--surface2)}
  .btn-accent{background:var(--accent-dim);border-color:rgba(200,245,99,.35);color:var(--accent)}
  .btn-accent:hover{background:rgba(200,245,99,.2)}

  .footer{padding:14px 20px;border-top:1px solid var(--border);display:flex;justify-content:space-between;font-size:11px;color:var(--muted);flex-wrap:wrap;gap:6px}
  @media(max-width:700px){
    .header,.main{padding:12px 14px}
    .hero-value{font-size:38px}
    .metrics{grid-template-columns:1fr 1fr}
    .chart-wrap{height:220px}
  }
  @media(max-width:480px){.logo{display:none}}
  ::-webkit-scrollbar{width:4px;height:4px}
  ::-webkit-scrollbar-thumb{background:var(--border2);border-radius:2px}
</style>
</head>
<body>

<div class="header">
  <div class="header-left">
    <div class="logo">wealth<span>os</span></div>
    <div class="tab-nav">
      <a class="tab-btn active" href="#">Portfolio</a>
      <a class="tab-btn" id="rspsTab" href="?__AUTH_PARAM_PLACEHOLDER__">RSPS</a>
      <a class="tab-btn" id="histTab" href="?action=history__AUTH_PARAM_PLACEHOLDER__">History</a>
      <a class="tab-btn" id="stratTab" href="?action=strategies__AUTH_PARAM_PLACEHOLDER__">Strategies</a>
    </div>
  </div>
</div>

<div class="main">

  <div class="hero">
    <div class="hero-label">Total Portfolio Value</div>
    <div class="hero-value" id="heroValue">$0.00</div>
    <div class="hero-sub">
      <div class="hero-stat">
        <div class="hero-stat-label">True P&L</div>
        <div class="hero-stat-val" id="heroPnl">—</div>
      </div>
      <div class="hero-stat">
        <div class="hero-stat-label">Net Deposited</div>
        <div class="hero-stat-val" id="heroDeposited">—</div>
      </div>
      <div class="hero-stat">
        <div class="hero-stat-label">Return on Capital</div>
        <div class="hero-stat-val" id="heroReturn">—</div>
      </div>
      <div class="hero-stat">
        <div class="hero-stat-label">Time-Weighted Return</div>
        <div class="hero-stat-val" id="heroTwr">—</div>
      </div>
      <div class="hero-stat">
        <div class="hero-stat-label">XIRR (annualized)</div>
        <div class="hero-stat-val" id="heroXirr">—</div>
      </div>
    </div>
  </div>

  <div class="metrics">
    <div class="metric"><div class="metric-label">Current Value</div><div class="metric-value" id="mValue">—</div><div class="metric-sub">live</div></div>
    <div class="metric"><div class="metric-label">Total Deposited</div><div class="metric-value" id="mDeposited">—</div><div class="metric-sub" id="mFlowCount">—</div></div>
    <div class="metric"><div class="metric-label">Money Made</div><div class="metric-value" id="mPnl">—</div><div class="metric-sub">excl. deposits</div></div>
    <div class="metric"><div class="metric-label">Strategies</div><div class="metric-value" id="mStrats">—</div><div class="metric-sub">active</div></div>
  </div>

  <div class="panel">
    <div class="panel-header">
      <div class="panel-title">Portfolio Equity</div>
      <div class="chart-controls">
        <div class="ctrl-group" id="seriesTabs">
          <button class="ctrl-btn active" onclick="setSeries('value',this)">Value</button>
          <button class="ctrl-btn" onclick="setSeries('deposited',this)">vs Deposited</button>
        </div>
        <div class="ctrl-group" id="rangeTabs">
          <button class="ctrl-btn" onclick="setRange('30d',this)">30d</button>
          <button class="ctrl-btn" onclick="setRange('90d',this)">90d</button>
          <button class="ctrl-btn" onclick="setRange('1y',this)">1y</button>
          <button class="ctrl-btn active" onclick="setRange('all',this)">All</button>
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
let chart = null, currentSeries='value', currentRange='all';

function fmt$(v){return '$'+parseFloat(v).toLocaleString('en-US',{minimumFractionDigits:2,maximumFractionDigits:2})}
function fmtPct(v,d=1){return (v>=0?'+':'')+(v*100).toFixed(d)+'%'}

async function loadData(){
  try{
    const r = await fetch(`?action=portfolio_data${_ap()}&v=${_liveValue}`);
    if(!r.ok) throw new Error('HTTP '+r.status);
    _data = await r.json();
    render();
  }catch(e){
    console.error('portfolio load failed', e);
    document.getElementById('noHistory').textContent = 'Failed to load: '+e.message;
  }
}

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

  renderChart();
  renderStrategies();
  renderFlows();
}

function filterRange(arr){
  if(currentRange==='all') return arr;
  const days={'30d':30,'90d':90,'1y':365}[currentRange];
  const cut=Date.now()-days*86400000;
  return arr.filter(p=>p.ts>=cut);
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

function setSeries(s,el){currentSeries=s;document.querySelectorAll('#seriesTabs .ctrl-btn').forEach(b=>b.classList.remove('active'));el.classList.add('active');renderChart()}
function setRange(r,el){currentRange=r;document.querySelectorAll('#rangeTabs .ctrl-btn').forEach(b=>b.classList.remove('active'));el.classList.add('active');renderChart()}

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
setInterval(()=>{document.getElementById('footerTime').textContent=new Date().toLocaleString('en-GB',{timeZone:'UTC'})+' UTC'},1000);

loadData();
</script>
</body>
</html>"""


def _render_strategies(auth: str = "") -> str:
    """Build the Signal Strategies tab — TradingView-fed external strategies."""
    auth_param = f"&auth={auth}" if auth else ""
    html = _STRATEGIES_HTML
    html = html.replace("__AUTH_PARAM_PLACEHOLDER__", auth_param)
    return html


# ══════════════════════════════════════════════════════════════════════════════
# SIGNAL STRATEGIES TAB — HTML
# ══════════════════════════════════════════════════════════════════════════════

_STRATEGIES_HTML = r"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1, maximum-scale=1">
<title>WealthOS — Strategies</title>
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
    --blue:#5b9cf6;--amber:#f5a623;--purple:#c084fc;
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
  .main{padding:16px 20px;max-width:1100px;margin:0 auto}
  .panel{background:var(--surface);border:1px solid var(--border);border-radius:10px;margin-bottom:16px;overflow:hidden}
  .panel-header{display:flex;align-items:center;justify-content:space-between;padding:12px 14px;border-bottom:1px solid var(--border);flex-wrap:wrap;gap:8px}
  .panel-title{font-family:var(--font-display);font-weight:700;font-size:15px}
  .panel-body{padding:14px}
  .intro{font-size:12px;color:var(--muted);line-height:1.7}
  .intro b{color:var(--text);font-weight:500}
  .intro code{background:var(--surface2);padding:1px 5px;border-radius:3px;color:var(--accent);font-size:11px}
  .form-grid{display:grid;grid-template-columns:repeat(auto-fit,minmax(150px,1fr));gap:10px;margin-bottom:12px}
  .field{display:flex;flex-direction:column;gap:4px}
  .field label{font-size:10px;letter-spacing:.06em;text-transform:uppercase;color:var(--muted)}
  .inp{background:var(--surface2);border:1px solid var(--border2);border-radius:5px;color:var(--text);font-family:var(--font-mono);font-size:13px;padding:7px 10px;outline:none;width:100%}
  .inp:focus{border-color:rgba(200,245,99,.4)}
  .btn{font-family:var(--font-mono);font-size:11px;letter-spacing:.06em;text-transform:uppercase;padding:8px 14px;border-radius:5px;cursor:pointer;border:1px solid var(--border2);background:var(--surface);color:var(--text);transition:all .15s}
  .btn:hover{border-color:var(--border2);background:var(--surface2)}
  .btn-accent{background:var(--accent-dim);border-color:rgba(200,245,99,.35);color:var(--accent)}
  .btn-accent:hover{background:rgba(200,245,99,.2)}
  .form-foot{display:flex;align-items:center;gap:12px}
  .status{font-size:11px;color:var(--muted)}
  .pos{color:var(--accent)}.neg{color:var(--red)}.mut{color:var(--muted)}
  .cards{display:grid;grid-template-columns:repeat(auto-fill,minmax(330px,1fr));gap:14px}
  .card{background:var(--surface);border:1px solid var(--border);border-radius:10px;overflow:hidden;display:flex;flex-direction:column}
  .card-top{padding:13px 14px;border-bottom:1px solid var(--border)}
  .card-name-row{display:flex;align-items:center;justify-content:space-between;gap:8px}
  .card-name{font-family:var(--font-display);font-weight:700;font-size:15px}
  .badges{display:flex;gap:5px;flex-wrap:wrap;margin-top:7px}
  .badge{font-size:9px;padding:2px 7px;border-radius:3px;letter-spacing:.05em;text-transform:uppercase;background:var(--surface3);color:var(--muted)}
  .badge.mode-paper{background:rgba(91,156,246,.14);color:var(--blue)}
  .badge.mode-live{background:var(--accent-dim);color:var(--accent)}
  .badge.asset{background:rgba(245,166,35,.14);color:var(--amber)}
  .card-eq{padding:12px 14px;border-bottom:1px solid var(--border)}
  .eq-val{font-family:var(--font-display);font-size:24px;font-weight:800;letter-spacing:-.02em}
  .eq-sub{font-size:11px;color:var(--muted);margin-top:2px}
  .spark{height:54px;padding:4px 10px 8px}
  .pos-row{display:flex;justify-content:space-between;padding:9px 14px;border-bottom:1px solid var(--border);font-size:12px}
  .log{padding:8px 14px;max-height:120px;overflow-y:auto;border-bottom:1px solid var(--border)}
  .log-item{font-size:11px;color:var(--muted);display:flex;justify-content:space-between;gap:8px;padding:2px 0}
  .log-item .a-long{color:var(--accent)}.log-item .a-short{color:var(--red)}.log-item .a-flat{color:var(--muted)}
  .wh{padding:11px 14px;border-bottom:1px solid var(--border)}
  .wh-label{font-size:10px;letter-spacing:.06em;text-transform:uppercase;color:var(--muted);margin-bottom:5px;display:flex;justify-content:space-between;align-items:center}
  .code{background:var(--bg);border:1px solid var(--border);border-radius:5px;padding:8px;font-size:10.5px;color:var(--muted);white-space:pre-wrap;word-break:break-all;max-height:140px;overflow-y:auto}
  .mini{font-size:10px;padding:3px 8px;border-radius:3px;cursor:pointer;border:1px solid var(--border2);background:none;color:var(--muted);text-transform:uppercase;letter-spacing:.04em}
  .mini:hover{color:var(--text)}
  .card-foot{padding:9px 14px;display:flex;justify-content:flex-end}
  .empty{padding:30px;text-align:center;color:var(--muted);font-size:12px}
  .footer{padding:14px 20px;border-top:1px solid var(--border);color:var(--muted2);font-size:11px;text-align:center}
  ::-webkit-scrollbar{width:5px;height:5px}::-webkit-scrollbar-thumb{background:var(--border2);border-radius:2px}
</style>
</head>
<body>

<div class="header">
  <div class="header-left">
    <div class="logo">wealth<span>os</span></div>
    <div class="tab-nav">
      <a class="tab-btn" id="portfolioTab" href="?action=portfolio__AUTH_PARAM_PLACEHOLDER__">Portfolio</a>
      <a class="tab-btn" id="rspsTab" href="?__AUTH_PARAM_PLACEHOLDER__">RSPS</a>
      <a class="tab-btn" id="histTab" href="?action=history__AUTH_PARAM_PLACEHOLDER__">History</a>
      <a class="tab-btn active" href="#">Strategies</a>
    </div>
  </div>
</div>

<div class="main">

  <div class="panel">
    <div class="panel-header"><div class="panel-title">TradingView Signal Strategies</div></div>
    <div class="panel-body">
      <div class="intro">
        Bridge any TradingView strategy into WealthOS. Add a strategy below, then in your Pine script
        drop the generated <code>alert()</code> calls at your entry/exit points and create one alert
        with condition <b>"Any alert() function call"</b> pointing at the strategy's webhook URL.
        Each signal (<code>long</code> / <code>short</code> / <code>flat</code>) is executed all-in on the
        strategy's capital. <b>Paper</b> mode forward-tests with a hypothetical bankroll — no real trades.
        Promote to <b>live</b> later once it earns trust. Needs a TradingView plan with webhook alerts.
      </div>
    </div>
  </div>

  <div class="panel">
    <div class="panel-header"><div class="panel-title">Add Strategy</div></div>
    <div class="panel-body">
      <div class="form-grid">
        <div class="field"><label>Name</label><input class="inp" id="fName" placeholder="e.g. BTC Momentum"></div>
        <div class="field"><label>Asset</label><input class="inp" id="fAsset" value="BTC"></div>
        <div class="field"><label>Direction</label>
          <select class="inp" id="fDir">
            <option value="long_short">Long / Short</option>
            <option value="long_flat">Long / Flat</option>
          </select>
        </div>
        <div class="field"><label>Leverage</label><input class="inp" id="fLev" type="number" min="1" max="20" value="1"></div>
        <div class="field"><label>Mode</label>
          <select class="inp" id="fMode">
            <option value="paper">Paper (forward test)</option>
            <option value="live">Live (Phase 2)</option>
          </select>
        </div>
        <div class="field"><label>Paper capital ($)</label><input class="inp" id="fCap" type="number" min="1" step="100" value="10000"></div>
      </div>
      <div class="form-foot">
        <button class="btn btn-accent" onclick="addStrategy()">Add Strategy</button>
        <span class="status" id="addStatus"></span>
      </div>
    </div>
  </div>

  <div id="cards" class="cards"></div>
  <div id="emptyMsg" class="empty" style="display:none">No signal strategies yet — add one above to start forward-testing.</div>

</div>

<div class="footer">WealthOS · Signal Strategies · <span id="footerTime"></span></div>

<script>
const _auth = new URLSearchParams(window.location.search).get('auth')||'';
function _ap(){return _auth?'&auth='+encodeURIComponent(_auth):'';}
const WEBHOOK_URL = window.location.origin.replace(/-web\.modal\.run/, '-tv-webhook.modal.run');
let _strats = [];
const _charts = {};

function fmt$(v){return '$'+parseFloat(v||0).toLocaleString('en-US',{minimumFractionDigits:2,maximumFractionDigits:2})}
function fmtPct(v,d=1){return (v>=0?'+':'')+(v*100).toFixed(d)+'%'}
function esc(s){return String(s).replace(/&/g,'&amp;').replace(/</g,'&lt;').replace(/>/g,'&gt;')}

function pineSnippet(s){
  return `// ── WealthOS bridge: ${esc(s.name)} (${esc(s.asset)}) ──
// 1) Paste into your Pine strategy. 2) Replace longCond/shortCond/flatCond
//    with your script's own entry/exit conditions.
// 3) Create ONE alert on this script: condition "Any alert() function call",
//    Webhook URL = ${WEBHOOK_URL}
sigId = syminfo.ticker + ":" + timeframe.period + ":" + str.tostring(time)
if (longCond)
    alert('{"token":"${s.token}","action":"long","id":"' + sigId + '"}', alert.freq_once_per_bar_close)
if (shortCond)
    alert('{"token":"${s.token}","action":"short","id":"' + sigId + '"}', alert.freq_once_per_bar_close)
if (flatCond)
    alert('{"token":"${s.token}","action":"flat","id":"' + sigId + '"}', alert.freq_once_per_bar_close)`;
}

async function loadData(){
  try{
    const r = await fetch(`?action=strategies_data${_ap()}`);
    if(!r.ok) throw new Error('HTTP '+r.status);
    const d = await r.json();
    if(d.error) throw new Error(d.error);
    _strats = d.strategies||[];
    render();
  }catch(e){ document.getElementById('emptyMsg').style.display='block'; document.getElementById('emptyMsg').textContent='Failed to load: '+e.message; }
}

function render(){
  const wrap=document.getElementById('cards');
  document.getElementById('emptyMsg').style.display=_strats.length?'none':'block';
  Object.values(_charts).forEach(c=>{try{c.destroy()}catch(e){}});
  wrap.innerHTML=_strats.map(s=>{
    const pos=s.position;
    const posTxt = pos
      ? `<span class="${pos.side==='long'?'pos':'neg'}">${pos.side.toUpperCase()}</span> ${(+pos.qty).toFixed(6)} ${esc(s.asset)} @ ${fmt$(pos.entry_px)}`
      : '<span class="mut">FLAT — in cash</span>';
    const pnlCls=s.paper_pnl>=0?'pos':'neg';
    const lev=(+s.leverage>1)?`<span class="badge">${s.leverage}x</span>`:'';
    const logHtml=(s.signal_log||[]).map(l=>{
      const d=new Date(l.ts).toLocaleString('en-GB',{day:'2-digit',month:'short',hour:'2-digit',minute:'2-digit'});
      return `<div class="log-item"><span class="a-${l.action}">${esc((l.action||'').toUpperCase())}</span><span>${esc(l.note||'')}</span><span class="mut">${d}</span></div>`;
    }).join('')||'<div class="log-item mut">No signals yet</div>';
    return `<div class="card">
      <div class="card-top">
        <div class="card-name-row">
          <span class="card-name">${esc(s.name)}</span>
          <button class="mini" onclick="delStrategy('${s.id}')">Delete</button>
        </div>
        <div class="badges">
          <span class="badge asset">${esc(s.asset)}</span>
          <span class="badge mode-${s.mode}">${esc(s.mode)}</span>
          <span class="badge">${s.direction==='long_short'?'L/S':'L/Flat'}</span>
          ${lev}
          <span class="badge">${esc(s.status||'')}</span>
        </div>
      </div>
      <div class="card-eq">
        <div class="eq-val ${pnlCls}">${fmt$(s.equity)}</div>
        <div class="eq-sub">paper · <span class="${pnlCls}">${s.paper_pnl>=0?'+':''}${fmt$(s.paper_pnl)} (${fmtPct(s.paper_return)})</span> · base ${fmt$(s.paper_capital)}</div>
      </div>
      <div class="spark"><canvas id="spark-${s.id}"></canvas></div>
      <div class="pos-row"><span class="mut">Position</span><span>${posTxt}</span></div>
      <div class="log">${logHtml}</div>
      <div class="wh">
        <div class="wh-label"><span>Webhook URL</span><button class="mini" onclick="copyText('${WEBHOOK_URL}',this)">Copy</button></div>
        <div class="code">${WEBHOOK_URL}</div>
      </div>
      <div class="wh">
        <div class="wh-label"><span>Pine alert() snippet</span><button class="mini" onclick="copyPine('${s.id}',this)">Copy</button></div>
        <div class="code" id="pine-${s.id}">${esc(pineSnippet(s))}</div>
      </div>
    </div>`;
  }).join('');

  // sparklines
  _strats.forEach(s=>{
    const cv=s.equity_curve||[];
    const el=document.getElementById('spark-'+s.id);
    if(!el||cv.length<2) return;
    const up=cv[cv.length-1].v>=cv[0].v;
    _charts[s.id]=new Chart(el,{type:'line',
      data:{labels:cv.map(p=>p.ts),datasets:[{data:cv.map(p=>p.v),
        borderColor:up?'#c8f563':'#ff5c5c',backgroundColor:up?'rgba(200,245,99,.07)':'rgba(255,92,92,.07)',
        borderWidth:1.5,pointRadius:0,fill:true,tension:0.3}]},
      options:{responsive:true,maintainAspectRatio:false,
        plugins:{legend:{display:false},tooltip:{enabled:false}},
        scales:{x:{display:false},y:{display:false}}}});
  });
}

async function addStrategy(){
  const name=document.getElementById('fName').value.trim();
  const st=document.getElementById('addStatus');
  if(!name){st.textContent='Enter a name';st.style.color='var(--red)';return}
  const payload={name,
    asset:document.getElementById('fAsset').value.trim()||'BTC',
    direction:document.getElementById('fDir').value,
    leverage:parseInt(document.getElementById('fLev').value)||1,
    mode:document.getElementById('fMode').value,
    paper_capital:parseFloat(document.getElementById('fCap').value)||10000};
  st.textContent='Adding…';st.style.color='var(--muted)';
  try{
    const r=await fetch(`?action=signal_strategy_add${_ap()}&points=${encodeURIComponent(JSON.stringify(payload))}`);
    const d=await r.json();
    if(d.ok){st.textContent='✓ Added';st.style.color='var(--accent)';document.getElementById('fName').value='';await loadData();setTimeout(()=>st.textContent='',2000);}
    else{st.textContent='Error: '+(d.error||'?');st.style.color='var(--red)';}
  }catch(e){st.textContent='Failed';st.style.color='var(--red)';}
}

async function delStrategy(id){
  if(!confirm('Delete this strategy and its paper history?'))return;
  try{
    await fetch(`?action=signal_strategy_delete${_ap()}&points=${encodeURIComponent(JSON.stringify({id}))}`);
    await loadData();
  }catch(e){console.error(e)}
}

function copyText(t,btn){navigator.clipboard.writeText(t).then(()=>{const o=btn.textContent;btn.textContent='Copied';setTimeout(()=>btn.textContent=o,1500)})}
function copyPine(id,btn){const s=_strats.find(x=>x.id===id);if(s)copyText(pineSnippet(s),btn)}

// auth-preserve nav links
if(_auth){['portfolioTab','rspsTab','histTab'].forEach(id=>{const el=document.getElementById(id);if(el&&!el.href.includes('auth='))el.href+=(el.href.includes('?')?'&':'?')+'auth='+encodeURIComponent(_auth)});}
setInterval(()=>{document.getElementById('footerTime').textContent=new Date().toLocaleString('en-GB',{timeZone:'UTC'})+' UTC'},1000);
loadData();
setInterval(loadData,60000);
</script>
</body>
</html>"""
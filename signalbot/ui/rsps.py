"""RSPS tab — the main signal-bot dashboard."""
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

__all__ = ['_DASHBOARD_HTML', '_render_dashboard']


_DASHBOARD_HTML = r"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1, maximum-scale=1">
<title>Signal Bot</title>
<script src="https://cdnjs.cloudflare.com/ajax/libs/Chart.js/4.4.1/chart.umd.js"></script>
__THEME_HEAD__
<style>
  /* ── Health badges ── */
  .header-badges{display:flex;gap:6px;flex-wrap:wrap}
  .badge{font-size:10px;font-family:var(--font-mono);font-weight:500;padding:3px 9px;border-radius:999px;letter-spacing:.06em;text-transform:uppercase;white-space:nowrap;backdrop-filter:blur(8px)}
  .badge-ok{background:rgba(200,245,99,.13);color:var(--accent);border:1px solid rgba(200,245,99,.3);box-shadow:0 0 12px -4px rgba(200,245,99,.5)}
  .badge-err{background:var(--red-dim);color:var(--red);border:1px solid rgba(255,92,92,.35);box-shadow:0 0 12px -4px rgba(255,92,92,.6);animation:wosHaltPulse 2.4s ease-in-out infinite}
  .badge-auto{background:var(--blue-dim);color:var(--blue);border:1px solid rgba(91,156,246,.3)}
  .badge-manual{background:rgba(245,166,35,.13);color:var(--amber);border:1px solid rgba(245,166,35,.3)}

  /* ── Banners ── */
  .pending-banner{position:relative;border:1px solid rgba(245,166,35,.45);background:rgba(245,166,35,.07);
    border-radius:14px;padding:18px;margin-bottom:16px;overflow:hidden;
    backdrop-filter:blur(12px);-webkit-backdrop-filter:blur(12px);
    box-shadow:0 0 38px -10px rgba(245,166,35,.35);
    animation:wosHaltIn .6s var(--ease) backwards,wosPendPulse 3s ease-in-out .7s infinite}
  .pending-banner::before{content:'';position:absolute;inset:0 0 auto 0;height:1px;
    background:linear-gradient(90deg,transparent,rgba(245,166,35,.7),transparent);
    background-size:220% 100%;animation:wosShimmer 3s linear infinite}
  @keyframes wosPendPulse{50%{box-shadow:0 0 52px -8px rgba(245,166,35,.5)}}
  .halt-banner{display:flex;align-items:center;gap:12px;flex-wrap:wrap;border:1px solid rgba(255,92,92,.5);
    background:rgba(255,92,92,.09);border-radius:14px;padding:15px 18px;margin-bottom:16px;
    font-family:var(--font-display);font-weight:600;color:var(--red);font-size:14px;
    backdrop-filter:blur(12px);-webkit-backdrop-filter:blur(12px);
    box-shadow:0 0 34px -8px rgba(255,92,92,.3);
    animation:wosHaltIn .6s var(--ease) backwards,wosHaltPulse 3.2s ease-in-out .7s infinite}
  .halt-banner .reason{font-family:var(--font-mono);font-weight:400;font-size:12px;color:var(--muted)}
  .pending-label{font-family:var(--font-display);font-size:11px;font-weight:600;letter-spacing:.14em;text-transform:uppercase;color:var(--amber);margin-bottom:8px}
  .pending-allocs{font-size:13px;color:var(--text);display:flex;gap:14px;flex-wrap:wrap;margin-bottom:14px}
  .pending-actions{display:flex;gap:8px;flex-wrap:wrap}

  /* ── Metric tiles ── */
  .metrics{display:grid;grid-template-columns:repeat(4,1fr);gap:10px;margin-bottom:18px}
  .metric{position:relative;background:var(--glass);border:1px solid var(--border);border-radius:14px;padding:16px 18px;
    backdrop-filter:blur(14px);-webkit-backdrop-filter:blur(14px);
    box-shadow:0 14px 34px -16px rgba(0,0,0,.6),inset 0 1px 0 rgba(255,255,255,.05);
    transition:transform .3s var(--ease),border-color .3s,box-shadow .3s}
  .metric:hover{transform:translateY(-3px);border-color:rgba(200,245,99,.28);
    box-shadow:0 20px 42px -16px rgba(0,0,0,.7),0 0 26px -8px rgba(200,245,99,.16)}
  .metric-label{font-size:10px;letter-spacing:.12em;text-transform:uppercase;color:var(--muted);margin-bottom:7px}
  .metric-value{font-family:var(--font-display);font-size:22px;font-weight:700;letter-spacing:-.02em;line-height:1.1}
  .metric-sub{font-size:11px;color:var(--muted);margin-top:4px}

  /* ── Chart ── */
  .chart-section{position:relative;background:var(--glass);border:1px solid var(--border);border-radius:16px;margin-bottom:18px;overflow:hidden;
    backdrop-filter:blur(16px) saturate(1.15);-webkit-backdrop-filter:blur(16px) saturate(1.15);
    box-shadow:0 20px 48px -20px rgba(0,0,0,.65),inset 0 1px 0 rgba(255,255,255,.05);
    transition:border-color .35s,box-shadow .35s}
  .chart-section::before{content:'';position:absolute;inset:0 0 auto 0;height:1px;pointer-events:none;
    background:linear-gradient(90deg,transparent,rgba(255,255,255,.14) 30%,rgba(200,245,99,.18) 50%,rgba(255,255,255,.14) 70%,transparent)}
  .chart-section:hover{border-color:var(--border2)}
  .chart-header{display:flex;align-items:center;justify-content:space-between;padding:13px 16px;border-bottom:1px solid var(--border);flex-wrap:wrap;gap:8px}
  .chart-controls{display:flex;gap:6px;flex-wrap:wrap;align-items:center}
  .chart-body{padding:16px}
  .chart-legend{display:flex;gap:14px;margin-bottom:10px;flex-wrap:wrap}
  .legend-item{display:flex;align-items:center;gap:6px;font-size:11px;color:var(--muted)}
  .legend-dot{width:8px;height:8px;border-radius:50%;flex-shrink:0;box-shadow:0 0 8px currentColor}
  .chart-wrap{position:relative;width:100%;height:230px}
  .grid-2{display:grid;grid-template-columns:1fr 1fr;gap:14px;margin-bottom:18px}
  .signal-time{font-size:11px;color:var(--muted)}

  /* ── Positions table ── */
  .pos-table{width:100%;border-collapse:collapse}
  .pos-table th{font-size:10px;letter-spacing:.1em;text-transform:uppercase;color:var(--muted);font-weight:500;padding:10px 16px;text-align:left;border-bottom:1px solid var(--border)}
  .pos-table th:not(:first-child){text-align:right}
  .pos-table td{padding:12px 16px;border-bottom:1px solid var(--border);font-size:13px;transition:background .2s}
  .pos-table td:not(:first-child){text-align:right}
  .pos-table tr:last-child td{border-bottom:none}
  .pos-table tr:hover td{background:rgba(255,255,255,.035)}
  .coin-badge{display:inline-flex;align-items:center;gap:7px;font-family:var(--font-display);font-weight:600;font-size:13px}
  .coin-dot{width:7px;height:7px;border-radius:50%;flex-shrink:0;box-shadow:0 0 8px currentColor}
  .mode-spot{background:rgba(200,245,99,.12);color:var(--accent);border:1px solid rgba(200,245,99,.3);border-radius:999px;padding:2px 7px;font-size:10px;letter-spacing:.04em;font-family:var(--font-mono)}
  .mode-perp{background:rgba(91,156,246,.12);color:var(--blue);border:1px solid rgba(91,156,246,.3);border-radius:999px;padding:2px 7px;font-size:10px;letter-spacing:.04em;font-family:var(--font-mono)}
  .mode-perp-lev{background:rgba(245,166,35,.15);color:var(--amber);border:1px solid rgba(245,166,35,.4);border-radius:999px;padding:2px 7px;font-size:10px;letter-spacing:.04em;font-family:var(--font-mono);font-weight:600}
  .liq-warn{font-size:10px;color:var(--red);opacity:.8}
  .notional-row{font-size:10px;color:var(--muted);margin-top:2px}

  /* ── Signal allocations ── */
  .alloc-list{padding:6px 0}
  .alloc-row{display:flex;align-items:center;gap:10px;padding:10px 16px;border-bottom:1px solid var(--border);transition:background .2s}
  .alloc-row:last-child{border-bottom:none}
  .alloc-row:hover{background:rgba(255,255,255,.035)}
  .alloc-pct{font-family:var(--font-display);font-weight:700;font-size:17px;color:var(--accent);min-width:56px;letter-spacing:-.02em}
  .alloc-bar-wrap{flex:1;height:4px;background:rgba(255,255,255,.07);border-radius:2px;overflow:hidden}
  .alloc-bar{height:100%;background:var(--grad);border-radius:2px;box-shadow:0 0 10px -1px rgba(200,245,99,.5);
    animation:wosBarGrow 1s var(--ease) backwards .3s}
  @keyframes wosBarGrow{from{width:0 !important}}
  .alloc-asset{font-family:var(--font-display);font-weight:600;font-size:13px;min-width:52px;text-align:right}
  .alloc-type{font-size:10px;color:var(--muted);min-width:32px;text-align:right;letter-spacing:.06em;text-transform:uppercase}

  /* ── Actions ── */
  .actions{display:flex;gap:8px;flex-wrap:wrap;margin-bottom:18px}
  .btn-approve{background:var(--grad);border-color:transparent;color:#10130a;font-weight:500;box-shadow:0 0 18px rgba(200,245,99,.3)}
  .btn-approve:hover{box-shadow:0 0 28px rgba(200,245,99,.55);transform:translateY(-1px)}
  .btn-danger{background:var(--red-dim);border-color:rgba(255,92,92,.4);color:var(--red)}
  .btn-danger:hover{background:rgba(255,92,92,.2);box-shadow:0 0 18px -4px rgba(255,92,92,.5)}
  .btn-pause{background:rgba(245,166,35,.12);border-color:rgba(245,166,35,.4);color:var(--amber)}
  .btn-pause:hover{background:rgba(245,166,35,.2);box-shadow:0 0 18px -4px rgba(245,166,35,.5)}
  .btn-export{background:var(--blue-dim);border-color:rgba(91,156,246,.4);color:var(--blue)}
  .btn-export:hover{background:rgba(91,156,246,.2)}

  /* ── Leverage panel ── */
  .lev-row{display:flex;align-items:center;gap:12px;padding:9px 0;border-bottom:1px solid var(--border)}
  .lev-row:last-child{border-bottom:none}
  .lev-asset{font-family:var(--font-display);font-weight:600;min-width:60px;font-size:14px}
  .lev-toggle{position:relative;width:38px;height:21px;flex-shrink:0;cursor:pointer}
  .lev-toggle input{opacity:0;width:0;height:0;position:absolute}
  .lev-track{position:absolute;inset:0;border-radius:11px;background:rgba(255,255,255,.14);transition:.25s}
  .lev-toggle input:checked~.lev-track{background:var(--accent);box-shadow:0 0 12px -2px rgba(200,245,99,.6)}
  .lev-thumb{position:absolute;width:15px;height:15px;left:3px;top:3px;border-radius:50%;background:white;transition:.25s var(--ease);pointer-events:none}
  .lev-toggle input:checked~.lev-thumb{transform:translateX(17px)}
  .lev-slider{flex:1;accent-color:var(--accent);cursor:pointer;height:4px;min-width:80px}
  .lev-value{font-family:var(--font-display);font-size:16px;font-weight:700;min-width:36px;text-align:right}
  .lev-spot{color:var(--muted)}
  .lev-active{color:var(--accent)}
  .lev-mode-tag{font-size:10px;padding:2px 8px;border-radius:999px;min-width:44px;text-align:center}
  .lev-mode-spot{background:rgba(255,255,255,.06);color:var(--muted);border:1px solid var(--border)}
  .lev-mode-perp{background:var(--accent-dim);color:var(--accent);border:1px solid rgba(200,245,99,.3)}

  .no-pos{padding:22px 16px;color:var(--muted);font-size:12px;text-align:center}
  .toggle-pill{display:inline-flex;align-items:center;gap:6px;font-size:10px;font-family:var(--font-mono);letter-spacing:.06em;text-transform:uppercase;color:var(--muted);cursor:pointer;padding:4px 10px 4px 8px;border:1px solid var(--border);border-radius:999px;background:none;transition:all .25s var(--ease);user-select:none}
  .toggle-pill:hover{border-color:var(--border2);color:var(--text)}
  .toggle-pill.active{background:var(--accent-dim);border-color:rgba(200,245,99,.35);color:var(--accent)}
  .toggle-pill .pip{width:6px;height:6px;border-radius:50%;background:currentColor;opacity:.5;transition:opacity .2s}
  .toggle-pill.active .pip{opacity:1}
  .dust-count{font-size:10px;color:var(--muted);margin-left:2px}

  @media(max-width:600px){
    .header{padding:10px 14px}
    .main{padding:12px 14px}
    .metrics{grid-template-columns:1fr 1fr}
    .metric{padding:13px 14px}
    .metric-value{font-size:18px}
    .grid-2{grid-template-columns:1fr}
    .chart-wrap{height:190px}
    .pos-table .hide-mobile{display:none}
    .pending-actions .btn{flex:1;justify-content:center;padding:12px 8px;font-size:12px}
    .actions .btn{padding:10px 12px}
  }
  @media(max-width:480px){
    .logo{display:none}
    .header-badges{gap:4px}
    .badge{font-size:9px;padding:2px 6px}
  }
  @media(max-width:380px){
    .metrics{grid-template-columns:1fr}
    .header-badges{display:none}
  }
</style>
</head>
<body>
__NAV_PLACEHOLDER__
<div class="main">
  <div class="halt-banner" id="haltBanner" style="display:none">
    <span>⏸ BOT PAUSED — no new orders will be placed. Positions are kept as-is.</span>
    <span class="reason" id="haltReason"></span>
    <a class="btn btn-approve" id="resumeBtn" href="?action=resume" style="margin-left:auto" onclick="return confirm('Resume the bot? Auto-execution will re-enable.')">Resume bot</a>
  </div>
  <div class="pending-banner" id="pendingBanner" style="display:none">
    <div class="pending-label">Approval required</div>
    <div class="pending-allocs" id="pendingAllocs"></div>
    <div class="pending-actions">
      <a class="btn btn-approve" id="approveBtn" style="flex:1;justify-content:center;padding:12px 8px">Approve &amp; execute</a>
      <a class="btn" id="dismissBtn" style="color:var(--muted)">Dismiss</a>
    </div>
  </div>
  <div class="metrics">
    <div class="metric"><div class="metric-label">Account value</div><div class="metric-value" id="accountValue" data-count>—</div><div class="metric-sub">spot + perp unified</div></div>
    <div class="metric"><div class="metric-label">Unrealised PnL</div><div class="metric-value" id="totalPnl" data-count>—</div><div class="metric-sub">open positions</div></div>
    <div class="metric"><div class="metric-label">Positions</div><div class="metric-value" id="posCount" data-count>—</div><div class="metric-sub">open positions</div></div>
    <div class="metric"><div class="metric-label">All-time PnL</div><div class="metric-value" id="allTimePnl" data-count>—</div><div class="metric-sub" id="allTimePnlSub">since first record</div></div>

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
    <a href="?action=halt" class="btn btn-pause" id="killBtn" title="Stops new orders — keeps positions" onclick="return confirm('Pause the bot? No new orders will be placed — existing positions are KEPT.')" style="margin-left:auto">⏸ Pause bot</a>
    <a href="?action=stop_all" class="btn btn-danger" id="stopAllBtn" title="Pause the bot AND market-sell every position to USDC" onclick="return confirm('EMERGENCY STOP\n\nThis pauses the bot AND market-sells ALL open positions to USDC right now.\nReal orders will be placed. Continue?')">🛑 Stop &amp; sell all</a>
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
//   3. server-side on every dashboard page render (_render_dashboard)
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
    if(window.wosCountUp)wosCountUp();
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
function _driftLabel(){
  // Cumulative execution drift = daily-open equity minus actual, today.
  // Positive: filling at the 00:00 opens would have left you richer (drift
  // is your execution cost). Negative: you beat the opens.
  if(!fullA.length||!fullB.length)return'';
  const d=fullB[fullB.length-1].value-fullA[fullA.length-1].value;
  if(!isFinite(d))return'';
  if(Math.abs(d)<0.005)return' <span style="color:var(--muted);margin-left:6px">· no drift yet</span>';
  const col=d>0?'var(--red)':'var(--accent)';
  const txt=d>0?('execution cost $'+d.toFixed(2)):('beat the opens by $'+(-d).toFixed(2));
  return' <span style="color:'+col+';margin-left:6px">· '+txt+' all-time</span>';
}
function buildLegend(a,b){
  const el=document.getElementById('chartLegend');
  let h='';
  if(a)h+='<div class="legend-item"><div class="legend-dot" style="background:#c8f563"></div>Actual equity</div>';
  if(b)h+='<div class="legend-item"><div class="legend-dot" style="background:#c084fc"></div>Daily open equity'+_driftLabel()+'</div>';
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

    // Funding (perps only): hourly rate annualized; longs pay positive funding
    let fundStr = '';
    if (p.mode === 'perp' && typeof p.funding === 'number') {
      const apr    = p.funding * 24 * 365 * 100;
      const paying = (p.size >= 0 ? p.funding > 0 : p.funding < 0);
      const col    = paying ? 'var(--red)' : 'var(--accent)';
      fundStr = `<div style="font-size:10px;color:${col};margin-top:2px" title="current funding rate, annualized">${paying?'paying':'earning'} ${Math.abs(apr).toFixed(1)}% APR funding</div>`;
    }

    // PnL: dollar + percent
    const costBasis = p.entryPx > 0 ? parseFloat(p.size) * p.entryPx : p.value - p.pnl;
    const pnlPct    = costBasis > 0 ? (p.pnl / costBasis) * 100 : 0;
    const pnlStr    = (p.pnl>=0?'+':'')+fmt$(p.pnl)
      + (costBasis>0?` <span style="font-size:10px;opacity:.7">(${pnlPct>=0?'+':''}${pnlPct.toFixed(2)}%)</span>`:'');

    return`<tr>
      <td><span class="coin-badge"><span class="coin-dot" style="background:${dc[i%dc.length]}"></span>${p.coin}</span></td>
      <td class="hide-mobile">${modeTag}${liqStr}${fundStr}</td>
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
  const{account,positions,signal,pending,lastActedId,trwOk,hlOk,slackOk,isAuto,approvalToken,halt}=d;
  const halted=halt&&halt.halted;
  document.getElementById('haltBanner').style.display=halted?'flex':'none';
  document.getElementById('killBtn').style.display=halted?'none':'';
  if(halted){
    const since=halt.ts?new Date(halt.ts).toLocaleString('en-GB',{timeZone:'UTC'})+' UTC':'';
    document.getElementById('haltReason').textContent=(halt.reason?halt.reason+' · ':'')+(since?'since '+since:'');
  }
  document.getElementById('badges').innerHTML=`<span class="badge ${trwOk?'badge-ok':'badge-err'}">TRW ${trwOk?'OK':'ERR'}</span><span class="badge ${hlOk?'badge-ok':'badge-err'}">HL ${hlOk?'OK':'ERR'}</span><span class="badge ${slackOk?'badge-ok':'badge-manual'}" title="${slackOk?'Slack webhook configured':'Slack webhook not set (optional)'}">SLACK ${slackOk?'OK':'—'}</span>`+(halted?`<span class="badge badge-err">🛑 HALTED</span>`:`<span class="badge ${isAuto?'badge-auto':'badge-manual'}" title="${isAuto?'Autonomous 00:00–05:00 UK':'Approval required 05:00–00:00 UK'}">${isAuto?'Auto 00–05':'Approval'}</span>`);
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
  if(window.wosCountUp)wosCountUp();
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


def _perp_funding_rates() -> dict[str, float]:
    """Current hourly funding rate per perp coin (HL public API, read-only).
    Display-only: failures return {} and the dashboard omits funding info."""
    import requests as req
    try:
        resp = req.post("https://api.hyperliquid.xyz/info",
                        json={"type": "metaAndAssetCtxs"}, timeout=10)
        meta, ctxs = resp.json()
        out: dict[str, float] = {}
        for asset, ctx in zip(meta.get("universe", []), ctxs):
            f = ctx.get("funding")
            if f is not None:
                out[asset["name"]] = float(f)
        return out
    except Exception as e:
        print(f"[funding] fetch failed: {e}")
        return {}


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
        # Record the snapshot server-side (replaces the old equity_upsert
        # round-trip where the client echoed this value back to the server).
        record_equity_snapshot(state.get("account_value", 0))
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

    # Funding info for open perp positions (PAXG and any leveraged asset pays
    # or earns funding hourly — invisible until now)
    if any(p["mode"] == "perp" for p in positions_js):
        rates = _perp_funding_rates()
        for p in positions_js:
            if p["mode"] == "perp" and p["coin"] in rates:
                p["funding"] = rates[p["coin"]]

    signal_js = None
    if parsed and parsed.get("allocations"):
        signal_js = {
            "time": signal_time,
            "allocations": [
                {"percent": a["percent"], "asset": a["asset"], "type": a.get("type", "Spot")}
                for a in parsed["allocations"]
            ],
        }

    halt = {"halted": False, "reason": "", "ts": 0}
    try:
        h = json.loads(ds.get("halt") or "")
        if isinstance(h, dict):
            halt = {"halted": bool(h.get("halted")), "reason": h.get("reason", ""),
                    "ts": h.get("ts", 0)}
    except Exception:
        pass

    dashboard_data = {
        "trwOk":            trw_ok,
        "hlOk":             hl_ok,
        "slackOk":          bool(os.environ.get("SLACK_WEBHOOK_URL", "")),
        "isAuto":           is_autonomous_hours(),
        "halt":             halt,
        "account":          {"value": state.get("account_value", 0)},
        "positions":        positions_js,
        "signal":           signal_js,
        "pending":          pending_allocs,
        "approvalToken":    approval_token,
        "lastActedId":      last_acted_id,
        "leverageSettings": json.loads(ds.get("leverage_settings") or "{}"),
    }

    data_json = json.dumps(dashboard_data)
    nav = _nav_html(
        "rsps", None, main_open=False,   # RSPS keeps its own halt banner (resume button)
        left_extra='<div class="pulse-dot"></div>\n    ',
        right_extra='<div class="header-badges" id="badges"></div>',
    )
    return (_DASHBOARD_HTML
            .replace("__THEME_HEAD__", _theme_head())
            .replace("__NAV_PLACEHOLDER__", nav)
            .replace("init(DASHBOARD_DATA);",
                     f"const DASHBOARD_DATA = {data_json};\ninit(DASHBOARD_DATA);"))

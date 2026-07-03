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

__NAV_PLACEHOLDER__

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

"""Strategies tab — TradingView signal strategies (paper/live)."""
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

__all__ = ['_render_strategies', '_STRATEGIES_HTML']


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

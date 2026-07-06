"""WealthOS Terminal — ground-up single-page UI.

Design language: instrument-panel editorial. Pure-black canvas, precision
hairlines, serif display numerals (Instrument Serif) over mono data
(IBM Plex Mono), odometer numbers, view transitions, command palette.
No blur, no gradient washes — the opposite pole from the aurora-glass UI.

Consumes the same JSON actions as the classic UI (portfolio_data,
strategies_data, equity_history, benchmark_data) plus rsps_data (added
alongside this module). All trading paths are untouched.
"""
import os
import json
import time
from datetime import datetime, timezone

from signalbot.config import *
from signalbot.trw import *
from signalbot.hyperliquid import *
from signalbot.rebalance import *
from signalbot.strategies import *
from signalbot.ui.rsps import _perp_funding_rates

__all__ = ['_TERMINAL_HTML', 'collect_rsps_data']


def collect_rsps_data() -> dict:
    """RSPS state as JSON (read-only) — same data _render_dashboard embeds,
    for client-side fetching by the Terminal. Sync (call via to_thread)."""
    signal_msg, parsed, signal_time, trw_ok = None, None, "", False
    try:
        messages   = fetch_recent_messages(limit=20)
        signal_msg = find_latest_signal(messages)
        if signal_msg:
            parsed      = parse_signal(signal_msg["content"])
            signal_time = datetime.fromtimestamp(
                signal_msg["timestamp"] / 1000, tz=timezone.utc
            ).strftime("%d %b %H:%M UTC")
            trw_ok = True
    except Exception:
        pass

    state, hl_ok = {"account_value": 0, "positions": {}}, False
    try:
        info, _ = get_hl_clients()
        state   = get_account_state(info)
        hl_ok   = True
    except Exception as e:
        print(f"[terminal] HL error: {e}")

    lev = {}
    try:
        lev = json.loads(signal_state.get("leverage_settings", "{}"))
    except Exception:
        pass

    positions = [{
        "coin": c, "size": p.get("size", 0), "entryPx": p.get("entry_px", 0),
        "markPx": p.get("mark_px", p.get("entry_px", 0)),
        "value": p.get("value_usd", 0), "pnl": p.get("unrealized_pnl", 0),
        "mode": p.get("mode", "perp"), "leverage": lev.get(c, 1),
    } for c, p in state.get("positions", {}).items()]
    if any(p["mode"] == "perp" for p in positions):
        rates = _perp_funding_rates()
        for p in positions:
            if p["mode"] == "perp" and p["coin"] in rates:
                p["funding"] = rates[p["coin"]]

    pending, halt = None, {"halted": False, "reason": ""}
    try:
        raw = signal_state.get("pending_signal", "")
        if raw:
            pending = (json.loads(raw) or {}).get("allocations")
    except Exception:
        pass
    try:
        raw = signal_state.get("trading_halted", "")
        if raw:
            d = json.loads(raw)
            halt = {"halted": bool(d.get("halted")), "reason": str(d.get("reason", ""))}
    except Exception:
        pass
    try:
        last_acted = signal_state.get("last_signal_id", "none")
    except Exception:
        last_acted = "none"

    return {
        "trwOk": trw_ok, "hlOk": hl_ok,
        "slackOk": bool(os.environ.get("SLACK_WEBHOOK_URL", "")),
        "isAuto": is_autonomous_hours(), "halt": halt,
        "account": {"value": state.get("account_value", 0)},
        "positions": positions,
        "signal": ({"time": signal_time, "allocations": [
            {"percent": a["percent"], "asset": a["asset"], "type": a.get("type", "Spot")}
            for a in parsed["allocations"]]} if parsed and parsed.get("allocations") else None),
        "pending": pending, "lastActedId": last_acted,
    }


_TERMINAL_HTML = r"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>WealthOS Terminal</title>
<script src="https://cdnjs.cloudflare.com/ajax/libs/Chart.js/4.4.1/chart.umd.js"></script>
<style>
@import url('https://fonts.googleapis.com/css2?family=Instrument+Serif:ital@0;1&family=IBM+Plex+Mono:wght@400;500;600&display=swap');
*,*::before,*::after{box-sizing:border-box;margin:0;padding:0}
:root{
  --bg:#0a0b0c; --panel:#0f1113; --panel2:#14171a;
  --line:#1f2327; --line2:#2c3136;
  --ink:#e9e4d8; --dim:#8f8a7e; --faint:#4e4a44;
  --lime:#c8f563; --coral:#ff6b4a; --cyan:#6be5c8; --amber:#f0b445; --blue:#6f9ff0;
  --serif:'Instrument Serif',serif; --mono:'IBM Plex Mono',monospace;
  --ease:cubic-bezier(.16,1,.3,1);
}
html{scrollbar-color:var(--line2) transparent}
body{background:var(--bg);color:var(--ink);font-family:var(--mono);font-size:13px;line-height:1.6;
  display:grid;grid-template-columns:216px 1fr;min-height:100vh}
::selection{background:rgba(200,245,99,.28)}
a{color:inherit;text-decoration:none}
::-webkit-scrollbar{width:4px;height:4px}::-webkit-scrollbar-thumb{background:var(--line2)}

/* ── command rail ── */
#rail{border-right:1px solid var(--line);position:sticky;top:0;height:100vh;
  display:flex;flex-direction:column;padding:22px 12px 16px;background:var(--bg);z-index:50}
.brand{font-family:var(--serif);font-size:21px;letter-spacing:.01em;padding:0 12px 4px}
.brand i{color:var(--lime);font-style:normal}
.brand-sub{font-size:9px;letter-spacing:.34em;text-transform:uppercase;color:var(--faint);padding:0 12px 26px}
.nav-it{display:flex;align-items:center;gap:11px;padding:10px 12px;color:var(--dim);cursor:pointer;
  font-size:11px;letter-spacing:.14em;text-transform:uppercase;border-left:2px solid transparent;
  transition:color .2s,border-color .2s,background .2s}
.nav-it:hover{color:var(--ink)}
.nav-it.on{color:var(--ink);border-left-color:var(--lime);background:linear-gradient(90deg,rgba(200,245,99,.06),transparent 70%)}
.nav-it .k{margin-left:auto;color:var(--faint);font-size:10px}
.rail-foot{margin-top:auto;padding:12px;border-top:1px solid var(--line);font-size:10px;color:var(--faint);
  display:flex;flex-direction:column;gap:6px}
#railHalt{cursor:pointer;letter-spacing:.12em;text-transform:uppercase}
#railHalt.armed{color:var(--lime)} #railHalt.halted{color:var(--coral);animation:blink 1.6s step-end infinite}
@keyframes blink{50%{opacity:.35}}
.kbd{border:1px solid var(--line2);border-radius:4px;padding:0 5px;font-size:10px;color:var(--dim)}

/* ── status strip ── */
#strip{position:sticky;top:0;display:flex;align-items:center;gap:20px;padding:11px 26px;
  border-bottom:1px solid var(--line);background:rgba(10,11,12,.94);z-index:40;flex-wrap:wrap}
#viewTitle{font-family:var(--serif);font-style:italic;font-size:19px;min-width:110px}
.dotset{display:flex;gap:12px;align-items:center}
.dot{display:flex;align-items:center;gap:5px;font-size:10px;letter-spacing:.1em;color:var(--dim);text-transform:uppercase}
.dot::before{content:'';width:6px;height:6px;border-radius:50%;background:var(--faint)}
.dot.ok::before{background:var(--lime);box-shadow:0 0 7px rgba(200,245,99,.8)}
.dot.err::before{background:var(--coral);box-shadow:0 0 7px rgba(255,107,74,.8);animation:blink 1.4s step-end infinite}
#stripVal{margin-left:auto;font-size:15px;font-weight:600;font-variant-numeric:tabular-nums}
#modeTag{font-size:10px;letter-spacing:.14em;text-transform:uppercase;padding:3px 10px;border:1px solid var(--line2)}
#modeTag.auto{color:var(--lime);border-color:rgba(200,245,99,.4)}
#modeTag.approval{color:var(--amber);border-color:rgba(240,180,69,.4)}
#modeTag.halted{color:var(--coral);border-color:rgba(255,107,74,.5);animation:blink 1.4s step-end infinite}
#clock{font-size:11px;color:var(--dim);font-variant-numeric:tabular-nums}
#toast{font-size:11px;color:var(--cyan);opacity:0;transition:opacity .4s}
#toast.show{opacity:1}

/* ── stage / views ── */
#stage{padding:30px 28px 70px;max-width:1280px;width:100%}
section[data-view]{display:none}
section[data-view].on{display:block;animation:viewIn .5s var(--ease)}
@keyframes viewIn{from{opacity:0;transform:translateY(12px)}}
.vlabel{font-size:10px;letter-spacing:.3em;text-transform:uppercase;color:var(--faint);margin-bottom:10px}
.sec-title{font-family:var(--serif);font-style:italic;font-size:22px;margin:34px 0 12px;color:var(--ink)}
.hairline{border:0;border-top:1px solid var(--line);margin:26px 0}

/* ── overview ── */
.ov-top{display:grid;grid-template-columns:minmax(320px,5fr) 7fr;gap:40px;align-items:start}
.hero-num{font-family:var(--serif);font-size:78px;line-height:1.04;letter-spacing:.01em;white-space:nowrap}
.hero-sub{margin-top:8px;font-size:13px;color:var(--dim)}
.hero-sub b{font-weight:600}
.pos{color:var(--lime)} .neg{color:var(--coral)}
.statgrid{display:grid;grid-template-columns:repeat(3,1fr);margin-top:26px;border-top:1px solid var(--line)}
.stat{padding:13px 14px 12px 0;border-bottom:1px solid var(--line)}
.stat .l{font-size:9px;letter-spacing:.22em;text-transform:uppercase;color:var(--faint)}
.stat .v{font-size:19px;font-weight:600;font-variant-numeric:tabular-nums;margin-top:2px}
.stat .s{font-size:10px;color:var(--faint)}
.chart-card{border:1px solid var(--line);background:var(--panel)}
.chart-head{display:flex;align-items:center;gap:8px;padding:12px 16px;border-bottom:1px solid var(--line);flex-wrap:wrap}
.seg{display:flex;border:1px solid var(--line2)}
.seg button{background:none;border:0;color:var(--dim);font-family:var(--mono);font-size:10px;letter-spacing:.1em;
  text-transform:uppercase;padding:5px 12px;cursor:pointer;border-right:1px solid var(--line2)}
.seg button:last-child{border-right:0}
.seg button.on{background:var(--panel2);color:var(--lime)}
.seg button:hover:not(.on){color:var(--ink)}
.chart-body{padding:14px 16px 10px;height:330px;position:relative}
.ov-bottom{display:grid;grid-template-columns:1fr 1fr 1fr;gap:26px;margin-top:34px}
.mini h4{font-size:10px;letter-spacing:.24em;text-transform:uppercase;color:var(--faint);margin-bottom:12px;
  padding-bottom:8px;border-bottom:1px solid var(--line)}
.bar-row{display:flex;align-items:center;gap:10px;padding:7px 0;font-size:12px}
.bar-row .pct{width:52px;font-weight:600;color:var(--lime);font-variant-numeric:tabular-nums}
.bar-row .track{flex:1;height:2px;background:var(--line)}
.bar-row .fill{height:2px;background:var(--lime);transition:width 1s var(--ease)}
.bar-row .as{width:56px;text-align:right;color:var(--ink)}
.bar-row .ty{width:36px;text-align:right;color:var(--faint);font-size:10px;text-transform:uppercase}
.flow-line{display:flex;justify-content:space-between;padding:7px 0;font-size:12px;color:var(--dim);border-bottom:1px solid var(--line)}
.flow-line:last-child{border-bottom:0}

/* ── tables ── */
table{width:100%;border-collapse:collapse}
th{font-size:9px;letter-spacing:.22em;text-transform:uppercase;color:var(--faint);font-weight:500;
  text-align:left;padding:9px 12px;border-bottom:1px solid var(--line2)}
th:not(:first-child),td:not(:first-child){text-align:right}
td{padding:12px;border-bottom:1px solid var(--line);font-variant-numeric:tabular-nums;transition:background .15s;font-size:12.5px}
tbody tr{border-left:2px solid transparent}
tbody tr:hover td{background:var(--panel2)}
tbody tr:hover td:first-child{box-shadow:inset 2px 0 0 var(--lime)}
.sub{display:block;font-size:10px;color:var(--faint)}
.tag{font-size:9px;letter-spacing:.12em;text-transform:uppercase;padding:2px 8px;border:1px solid var(--line2);color:var(--dim)}
.tag.spot{color:var(--lime);border-color:rgba(200,245,99,.35)}
.tag.perp{color:var(--blue);border-color:rgba(111,159,240,.4)}
.tag.lev{color:var(--amber);border-color:rgba(240,180,69,.45)}
.tag.live{color:var(--lime);border-color:rgba(200,245,99,.35)}
.tag.paper{color:var(--blue);border-color:rgba(111,159,240,.4)}

/* ── buttons / banners ── */
.btnrow{display:flex;gap:10px;flex-wrap:wrap;margin-top:26px}
.tbtn{background:none;border:1px solid var(--line2);color:var(--ink);font-family:var(--mono);font-size:10.5px;
  letter-spacing:.14em;text-transform:uppercase;padding:10px 18px;cursor:pointer;transition:all .2s var(--ease)}
.tbtn:hover{border-color:var(--ink);transform:translateY(-1px)}
.tbtn.go{color:var(--lime);border-color:rgba(200,245,99,.45)} .tbtn.go:hover{border-color:var(--lime);box-shadow:0 0 16px -6px rgba(200,245,99,.6)}
.tbtn.no{color:var(--coral);border-color:rgba(255,107,74,.45)} .tbtn.no:hover{border-color:var(--coral);box-shadow:0 0 16px -6px rgba(255,107,74,.6)}
.banner{border:1px solid rgba(240,180,69,.5);background:rgba(240,180,69,.05);padding:16px 18px;margin-bottom:22px}
.banner.red{border-color:rgba(255,107,74,.5);background:rgba(255,107,74,.05)}
.banner h5{font-size:10px;letter-spacing:.24em;text-transform:uppercase;color:var(--amber);margin-bottom:8px}
.banner.red h5{color:var(--coral)}

/* ── strategies ── */
.strat-row{border:1px solid var(--line);background:var(--panel);margin-bottom:14px;padding:16px 18px;
  display:grid;grid-template-columns:minmax(150px,2fr) 3fr 1fr 1fr auto;gap:18px;align-items:center;cursor:pointer;
  transition:border-color .2s}
.strat-row:hover{border-color:var(--line2)}
.strat-row .nm{font-family:var(--serif);font-size:18px}
.strat-row canvas{width:100%;height:44px}
.strat-eq{font-size:17px;font-weight:600;font-variant-numeric:tabular-nums;text-align:right}
.strat-detail{border:1px solid var(--line);border-top:0;background:var(--panel2);padding:16px 18px;margin:-14px 0 14px;display:none}
.strat-detail.open{display:block;animation:viewIn .3s var(--ease)}
.code{background:var(--bg);border:1px solid var(--line);padding:10px;font-size:10.5px;color:var(--dim);
  white-space:pre-wrap;word-break:break-all;max-height:130px;overflow-y:auto;margin-top:8px}

/* ── odometer ── */
.odo{display:inline-flex;overflow:hidden}
.odo .cell{display:inline-block}
.odo .reel{display:inline-block;height:1.04em;overflow:hidden;vertical-align:bottom}
.odo .strip{display:flex;flex-direction:column;transition:transform 1.5s var(--ease)}
.odo .strip span{height:1.04em;line-height:1.04em}

/* ── command palette ── */
#pal{position:fixed;inset:0;background:rgba(5,6,7,.7);display:none;align-items:flex-start;justify-content:center;
  padding-top:16vh;z-index:100}
#pal.open{display:flex}
.pal-box{width:min(560px,92vw);background:var(--panel);border:1px solid var(--line2);box-shadow:0 30px 80px -20px #000}
#palIn{width:100%;background:none;border:0;border-bottom:1px solid var(--line);color:var(--ink);
  font-family:var(--mono);font-size:15px;padding:16px 18px;outline:none}
#palList{max-height:300px;overflow-y:auto}
.pal-it{display:flex;justify-content:space-between;padding:11px 18px;font-size:12px;color:var(--dim);cursor:pointer;
  letter-spacing:.06em}
.pal-it.sel{background:var(--panel2);color:var(--ink);box-shadow:inset 2px 0 0 var(--lime)}
.pal-it .hint{color:var(--faint);font-size:10px;text-transform:uppercase;letter-spacing:.14em}

/* ── responsive ── */
@media(max-width:900px){
  body{grid-template-columns:1fr}
  #rail{position:fixed;top:auto;bottom:0;left:0;right:0;height:54px;flex-direction:row;align-items:center;
    padding:0 8px;border-right:0;border-top:1px solid var(--line2);gap:0}
  .brand,.brand-sub,.rail-foot,.nav-it .k{display:none}
  .nav-it{flex:1;justify-content:center;border-left:0;border-top:2px solid transparent;padding:16px 4px;font-size:10px}
  .nav-it.on{border-top-color:var(--lime);border-left:0;background:none}
  #stage{padding:20px 16px 90px}
  .ov-top{grid-template-columns:1fr;gap:26px}
  .hero-num{font-size:54px}
  .ov-bottom{grid-template-columns:1fr;gap:20px}
  .strat-row{grid-template-columns:1fr 1fr;gap:10px}
  #strip{padding:10px 16px;gap:12px}
  #viewTitle{display:none}
}
@media (prefers-reduced-motion: reduce){*{animation:none!important;transition:none!important}}
</style>
</head>
<body>

<nav id="rail">
  <div class="brand">Wealth<i>OS</i></div>
  <div class="brand-sub">terminal</div>
  <div class="nav-it on" data-nav="overview">◈ Overview</div>
  <div class="nav-it" data-nav="rsps">⚡ RSPS</div>
  <div class="nav-it" data-nav="strategies">▤ Strategies</div>
  <a class="nav-it" href="?action=history">◷ History</a>
  <a class="nav-it" href="?">✦ Classic UI</a>
  <div class="rail-foot">
    <div id="railHalt" class="armed">● trading armed</div>
    <div><span class="kbd">⌘K</span> command palette</div>
  </div>
</nav>

<main>
  <div id="strip">
    <div id="viewTitle">Overview</div>
    <div class="dotset">
      <div class="dot" id="dTrw">trw</div>
      <div class="dot" id="dHl">hl</div>
      <div class="dot" id="dSlack">slack</div>
    </div>
    <span id="toast"></span>
    <div id="stripVal">—</div>
    <div id="modeTag">…</div>
    <div id="clock"></div>
  </div>

  <div id="stage">

  <!-- ═══ OVERVIEW ═══ -->
  <section data-view="overview" class="on">
    <div class="ov-top">
      <div>
        <div class="vlabel">Total portfolio value</div>
        <div class="hero-num odo" id="heroOdo">$0.00</div>
        <div class="hero-sub" id="heroSub">loading…</div>
        <div class="statgrid" id="statGrid"></div>
        <div class="hero-sub" id="bwDay" style="font-size:11px;color:var(--faint)"></div>
      </div>
      <div class="chart-card">
        <div class="chart-head">
          <div class="seg" id="segMode">
            <button class="on" data-m="value">Value</button>
            <button data-m="perf">Performance</button>
            <button data-m="dd">Drawdown</button>
          </div>
          <div class="seg" id="segBench" style="display:none">
            <button data-b="BTC">btc</button>
            <button data-b="ETH">eth</button>
          </div>
          <div class="seg" id="segRange" style="margin-left:auto">
            <button data-r="30">30d</button>
            <button data-r="90">90d</button>
            <button data-r="365">1y</button>
            <button class="on" data-r="0">All</button>
          </div>
        </div>
        <div class="chart-body"><canvas id="mainChart"></canvas></div>
      </div>
    </div>
    <div class="ov-bottom">
      <div class="mini"><h4>Signal now</h4><div id="ovSignal"></div></div>
      <div class="mini"><h4>Allocation</h4><div id="ovAlloc"></div></div>
      <div class="mini"><h4>Recent flows</h4><div id="ovFlows"></div></div>
    </div>
  </section>

  <!-- ═══ RSPS ═══ -->
  <section data-view="rsps">
    <div id="rspsBanners"></div>
    <div class="vlabel">Relative Strength Portfolio System</div>
    <div class="statgrid" style="grid-template-columns:repeat(4,1fr);margin-top:6px" id="rspsStats"></div>
    <div class="sec-title">Positions</div>
    <div id="posTable"></div>
    <div class="sec-title">Latest signal</div>
    <div id="rspsSignal" style="max-width:520px"></div>
    <div class="btnrow">
      <button class="tbtn go" onclick="actForce()">Force rebalance</button>
      <button class="tbtn" id="btnHalt" onclick="actHalt()">Halt trading</button>
      <button class="tbtn" onclick="window.open('?action=health')">Health check</button>
      <button class="tbtn" onclick="loadAll(true)">Refresh</button>
    </div>
  </section>

  <!-- ═══ STRATEGIES ═══ -->
  <section data-view="strategies">
    <div class="vlabel">Strategy lab — TradingView bridge</div>
    <div id="stratList" style="margin-top:14px"></div>
    <p style="color:var(--faint);font-size:11px;margin-top:18px">
      Click a strategy for its webhook &amp; signal log · manage strategies in the
      <a href="?action=strategies" style="color:var(--dim);border-bottom:1px solid var(--line2)">classic UI</a>
    </p>
  </section>

  </div>
</main>

<!-- ═══ COMMAND PALETTE ═══ -->
<div id="pal"><div class="pal-box">
  <input id="palIn" placeholder="Type a command…" autocomplete="off">
  <div id="palList"></div>
</div></div>

<script>
'use strict';
const $=s=>document.querySelector(s), $$=s=>[...document.querySelectorAll(s)];
const fmt$=v=>'$'+(+v).toLocaleString('en-US',{minimumFractionDigits:2,maximumFractionDigits:2});
const pct=(v,d=1)=>(v>=0?'+':'')+(v*100).toFixed(d)+'%';
const S={port:null,rsps:null,strats:null,bench:null,mode:'value',range:0,benchOn:{BTC:false,ETH:false}};

/* ── odometer ── */
function odo(el,text){
  el.innerHTML='';
  [...text].forEach((ch,i)=>{
    if(/\d/.test(ch)){
      const reel=document.createElement('span');reel.className='reel';
      const strip=document.createElement('span');strip.className='strip';
      for(let d=0;d<=9;d++){const s=document.createElement('span');s.textContent=d;strip.appendChild(s)}
      reel.appendChild(strip);el.appendChild(reel);
      requestAnimationFrame(()=>requestAnimationFrame(()=>{
        strip.style.transitionDelay=(i*70)+'ms';
        strip.style.transform='translateY(-'+(+ch*1.04)+'em)';
      }));
    }else{
      const c=document.createElement('span');c.className='cell';c.textContent=ch;el.appendChild(c);
    }
  });
}

/* ── data ── */
async function jget(u){const r=await fetch(u);if(!r.ok)throw new Error(u+' '+r.status);return r.json()}
async function loadAll(refresh){
  toast(refresh?'refreshing…':'connecting feeds…');
  const live=S.rsps?S.rsps.account.value:0;
  const [port,rsps,strats]=await Promise.all([
    jget('?action=portfolio_data&v='+live),
    jget('?action=rsps_data'),
    jget('?action=strategies_data'),
  ]);
  S.port=port;S.rsps=rsps;S.strats=strats.strategies||[];
  renderStrip();renderOverview();renderRsps();renderStrats();
  toast(refresh?'feeds refreshed':'');
}
async function loadBench(){
  if(S.bench)return S.bench;
  const s=(S.port.index_series||[]);
  S.bench=await jget('?action=benchmark_data&points='+encodeURIComponent(JSON.stringify({start:s.length?s[0].ts:0})));
  return S.bench;
}

/* ── strip ── */
function renderStrip(){
  const r=S.rsps;
  $('#dTrw').className='dot '+(r.trwOk?'ok':'err');
  $('#dHl').className='dot '+(r.hlOk?'ok':'err');
  $('#dSlack').className='dot '+(r.slackOk?'ok':'');
  $('#stripVal').textContent=fmt$(r.account.value);
  const m=$('#modeTag');
  if(r.halt.halted){m.textContent='halted';m.className='halted'}
  else if(r.isAuto){m.textContent='autonomous';m.className='auto'}
  else{m.textContent='approval';m.className='approval'}
  const rh=$('#railHalt');
  rh.className=r.halt.halted?'halted':'armed';
  rh.textContent=r.halt.halted?'● trading halted':'● trading armed';
}

/* ── overview ── */
function renderOverview(){
  const m=S.port.metrics, rk=m.risk||{};
  odo($('#heroOdo'),fmt$(m.current_value));
  $('#heroSub').innerHTML=
    '<b class="'+(m.true_pnl>=0?'pos':'neg')+'">'+(m.true_pnl>=0?'+':'')+fmt$(m.true_pnl)+'</b> true p&l'+
    ' · <b>'+fmt$(m.net_deposited)+'</b> deposited'+
    (m.net_deposited>0?' · <b class="'+(m.simple_return>=0?'pos':'neg')+'">'+pct(m.simple_return)+'</b> on capital':'');
  const st=[
    ['TWR',m.twr!=null?pct(m.twr):'—',''],
    ['XIRR',m.xirr!=null?pct(m.xirr):'—','annualized'],
    ['Sharpe',rk.sharpe!=null?rk.sharpe.toFixed(2):'—','sortino '+(rk.sortino!=null?rk.sortino.toFixed(2):'—')],
    ['Volatility',rk.vol_annual!=null?(rk.vol_annual*100).toFixed(1)+'%':'—','annualized'],
    ['Max drawdown',rk.max_drawdown!=null?(rk.max_drawdown*100).toFixed(1)+'%':'—','flow-adjusted'],
    ['CAGR',rk.cagr!=null?pct(rk.cagr):'—',''],
  ];
  $('#statGrid').innerHTML=st.map(([l,v,s])=>
    '<div class="stat"><div class="l">'+l+'</div><div class="v">'+v+'</div><div class="s">'+s+'</div></div>').join('');
  $('#bwDay').textContent=(rk.best_day&&rk.worst_day)
    ? 'best day '+pct(rk.best_day.r)+' · worst day '+pct(rk.worst_day.r) : '';
  drawChart();
  const sig=S.rsps.signal;
  $('#ovSignal').innerHTML=sig?sig.allocations.map(a=>barRow(a)).join('')
    :'<div class="flow-line">no signal</div>';
  $('#ovAlloc').innerHTML=(S.port.strategies||[]).map(s=>
    '<div class="flow-line"><span>'+s.name+'</span><span style="color:var(--ink)">'+(+s.target_pct).toFixed(1)+'%</span></div>').join('');
  $('#ovFlows').innerHTML=(S.port.flows||[]).slice(-4).reverse().map(f=>
    '<div class="flow-line"><span>'+new Date(f.ts).toLocaleDateString('en-GB',{day:'numeric',month:'short'})+
    ' '+(f.note||'')+'</span><span class="'+(f.amount>=0?'pos':'neg')+'">'+(f.amount>=0?'+':'')+fmt$(f.amount)+'</span></div>').join('')
    ||'<div class="flow-line">none yet</div>';
}
function barRow(a){
  return '<div class="bar-row"><span class="pct">'+a.percent+'%</span>'+
    '<span class="track"><span class="fill" style="width:'+Math.min(100,a.percent)+'%"></span></span>'+
    '<span class="as">'+a.asset+'</span><span class="ty">'+(a.type||'')+'</span></div>';
}

/* ── main chart ── */
let chart=null;
const dayKey=ts=>Math.floor(ts/86400000);
function daily(arr){const m=new Map();for(const p of arr)m.set(dayKey(p.ts),p);return[...m.values()].sort((a,b)=>a.ts-b.ts)}
function inRange(arr){if(!S.range)return arr;const cut=Date.now()-S.range*86400000;return arr.filter(p=>p.ts>=cut)}
async function drawChart(){
  const el=$('#mainChart');if(!el)return;
  const grid={color:'rgba(255,255,255,.04)'},ticks={color:'#54504a',font:{family:'IBM Plex Mono',size:10}};
  let labels=[],datasets=[],yFmt=v=>'$'+(+v).toLocaleString();
  if(S.mode==='value'){
    const snaps=inRange(daily(S.port.snapshots||[]));
    labels=snaps.map(p=>new Date(p.ts).toLocaleDateString('en-GB',{day:'numeric',month:'short'}));
    datasets=[{data:snaps.map(p=>p.v),borderColor:'#c8f563',borderWidth:1.6,pointRadius:0,tension:.25,fill:false}];
  }else{
    const idxAll=daily(S.port.index_series||[]),idx=inRange(idxAll);
    labels=idx.map(p=>new Date(p.ts).toLocaleDateString('en-GB',{day:'numeric',month:'short'}));
    if(S.mode==='dd'){
      let peak=0;const dd=new Map();
      for(const p of idxAll){peak=Math.max(peak,p.v);dd.set(p.ts,peak>0?(p.v/peak-1)*100:0)}
      datasets=[{data:idx.map(p=>dd.get(p.ts)??0),borderColor:'#ff6b4a',backgroundColor:'rgba(255,107,74,.07)',
        borderWidth:1.6,pointRadius:0,tension:.2,fill:'origin'}];
      yFmt=v=>v.toFixed(0)+'%';
    }else{
      const b0=idx.length?idx[0].v:1;
      datasets=[{data:idx.map(p=>p.v/b0*100),borderColor:'#c8f563',borderWidth:1.6,pointRadius:0,tension:.25,fill:false}];
      yFmt=v=>(+v).toFixed(0);
      if(S.benchOn.BTC||S.benchOn.ETH){
        const bench=await loadBench(),cols={BTC:'#f0b445',ETH:'#6f9ff0'};
        for(const c of['BTC','ETH']){
          if(!S.benchOn[c])continue;
          const by=new Map((bench[c]||[]).map(x=>[dayKey(x.ts),x.c]));let f=null;
          const data=idx.map(p=>{const v=by.get(dayKey(p.ts));if(v==null)return null;if(f===null)f=v;return v/f*100});
          datasets.push({data,borderColor:cols[c],borderWidth:1.1,borderDash:[4,4],pointRadius:0,tension:.2,fill:false,spanGaps:true});
        }
      }
    }
  }
  if(chart)chart.destroy();
  chart=new Chart(el,{type:'line',data:{labels,datasets},options:{
    responsive:true,maintainAspectRatio:false,interaction:{mode:'index',intersect:false},
    plugins:{legend:{display:false},tooltip:{backgroundColor:'#14171a',borderColor:'#2c3136',borderWidth:1,
      titleColor:'#54504a',bodyColor:'#e9e4d8',titleFont:{family:'IBM Plex Mono',size:10},
      bodyFont:{family:'IBM Plex Mono',size:11},callbacks:{label:c=>' '+yFmt(c.parsed.y)}}},
    scales:{x:{grid,ticks:{...ticks,maxTicksLimit:8},border:{display:false}},
            y:{position:'right',grid,ticks:{...ticks,callback:yFmt},border:{display:false}}}
  }});
}
$('#segMode').addEventListener('click',e=>{const b=e.target.closest('button');if(!b)return;
  $$('#segMode button').forEach(x=>x.classList.remove('on'));b.classList.add('on');
  S.mode=b.dataset.m==='perf'?'perf':b.dataset.m;
  $('#segBench').style.display=S.mode==='perf'?'':'none';drawChart()});
$('#segBench').addEventListener('click',e=>{const b=e.target.closest('button');if(!b)return;
  S.benchOn[b.dataset.b]=!S.benchOn[b.dataset.b];b.classList.toggle('on');drawChart()});
$('#segRange').addEventListener('click',e=>{const b=e.target.closest('button');if(!b)return;
  $$('#segRange button').forEach(x=>x.classList.remove('on'));b.classList.add('on');
  S.range=+b.dataset.r;drawChart()});

/* ── rsps view ── */
function renderRsps(){
  const r=S.rsps;
  let banners='';
  if(r.halt.halted)banners+='<div class="banner red"><h5>Trading halted</h5>'+
    '<span style="color:var(--dim)">'+(r.halt.reason||'kill switch engaged')+' — no signals will execute.</span></div>';
  if(r.pending)banners+='<div class="banner"><h5>Approval required</h5><span style="color:var(--dim)">'+
    r.pending.map(a=>a.percent+'% '+a.asset).join(' · ')+
    ' — approve from the Slack link or the classic UI.</span></div>';
  $('#rspsBanners').innerHTML=banners;
  const upnl=r.positions.reduce((s,p)=>s+(+p.pnl||0),0);
  $('#rspsStats').innerHTML=[
    ['Account value',fmt$(r.account.value),'spot + perp unified'],
    ['Unrealised pnl',(upnl>=0?'+':'')+fmt$(upnl),'open positions'],
    ['Positions',r.positions.filter(p=>p.value>=2).length,'open'],
    ['Signal',r.signal?r.signal.time:'—','last parsed'],
  ].map(([l,v,s])=>'<div class="stat"><div class="l">'+l+'</div><div class="v">'+v+'</div><div class="s">'+s+'</div></div>').join('');
  const rows=r.positions.filter(p=>p.value>=2).map(p=>{
    const lev=p.leverage>1;
    let modeTag='<span class="tag '+(p.mode==='spot'?'spot':lev?'lev':'perp')+'">'+
      (p.mode==='spot'?'spot':(lev?'perp '+p.leverage+'×':'perp 1×'))+'</span>';
    let fund='';
    if(p.mode==='perp'&&typeof p.funding==='number'){
      const apr=p.funding*24*365*100,paying=(p.size>=0?p.funding>0:p.funding<0);
      fund='<span class="sub" style="color:'+(paying?'var(--coral)':'var(--lime)')+'">'+
        (paying?'paying':'earning')+' '+Math.abs(apr).toFixed(1)+'% apr</span>';
    }
    const pnlPct=p.entryPx>0?(p.pnl/(Math.abs(p.size)*p.entryPx))*100:0;
    return '<tr><td style="font-weight:600">'+p.coin+'</td><td>'+modeTag+fund+'</td>'+
      '<td>'+(+p.size).toLocaleString('en-US',{maximumFractionDigits:6})+'</td>'+
      '<td><span style="color:var(--faint)">'+(+p.entryPx).toLocaleString()+'</span> → '+(+p.markPx).toLocaleString()+'</td>'+
      '<td>'+fmt$(p.value)+'</td>'+
      '<td class="'+(p.pnl>=0?'pos':'neg')+'">'+(p.pnl>=0?'+':'')+fmt$(p.pnl)+
      '<span class="sub">'+(pnlPct>=0?'+':'')+pnlPct.toFixed(2)+'%</span></td></tr>';
  }).join('');
  $('#posTable').innerHTML=rows
    ?'<table><thead><tr><th>Asset</th><th>Mode</th><th>Size</th><th>Entry → Mark</th><th>Value</th><th>PnL</th></tr></thead><tbody>'+rows+'</tbody></table>'
    :'<div class="flow-line">no open positions — off risk</div>';
  $('#rspsSignal').innerHTML=S.rsps.signal?S.rsps.signal.allocations.map(a=>barRow(a)).join(''):'';
  $('#btnHalt').textContent=r.halt.halted?'Resume trading':'Halt trading';
  $('#btnHalt').className='tbtn '+(r.halt.halted?'go':'no');
}
async function actForce(){
  if(!confirm('Force rebalance to the latest signal now?'))return;
  toast('rebalancing…');
  await fetch('?action=force');await loadAll(true);toast('rebalance dispatched — check Slack');
}
async function actHalt(){
  const h=S.rsps.halt.halted;
  if(!confirm(h?'Resume trading?':'HALT all trading?'))return;
  await fetch('?action='+(h?'resume':'halt'));await loadAll(true);
}

/* ── strategies view ── */
function renderStrats(){
  const wh=location.origin.replace('-web.','-tv-webhook.');
  $('#stratList').innerHTML=S.strats.map((s,i)=>{
    const ret=s.paper_return||0;
    return '<div class="strat-row" onclick="tglStrat('+i+')">'+
      '<div><div class="nm">'+s.name+'</div><div style="display:flex;gap:6px;margin-top:5px">'+
        '<span class="tag">'+s.asset+'</span><span class="tag '+(s.mode==='live'?'live':'paper')+'">'+s.mode+'</span>'+
        (s.leverage>1?'<span class="tag lev">'+s.leverage+'×</span>':'')+'</div></div>'+
      '<canvas id="spark'+i+'"></canvas>'+
      '<div class="strat-eq">'+fmt$(s.equity||0)+'<span class="sub">equity</span></div>'+
      '<div class="strat-eq '+(ret>=0?'pos':'neg')+'">'+pct(ret)+'<span class="sub">return</span></div>'+
      '<div style="color:var(--faint);font-size:11px">'+(s.position?('◉ '+s.position.side+' @ '+(+s.position.entry_px).toLocaleString()):'○ flat')+'</div>'+
      '</div>'+
      '<div class="strat-detail" id="sd'+i+'">'+
        '<div class="vlabel">Webhook</div><div class="code">'+wh+'\n{"token":"'+(s.token||'')+'","action":"long|short|flat","id":"{{time}}"}</div>'+
        '<div class="vlabel" style="margin-top:12px">Signal log</div>'+
        ((s.signal_log||[]).map(l=>'<div class="flow-line"><span>'+new Date(l.ts).toLocaleString('en-GB')+'</span><span>'+l.action+' '+(l.px?('@ '+l.px):'')+'</span></div>').join('')||'<div class="flow-line">no signals yet</div>')+
      '</div>';
  }).join('')||'<div class="flow-line">no strategies — add one in the classic UI</div>';
  S.strats.forEach((s,i)=>spark($('#spark'+i),(s.equity_curve||[]).map(p=>p.v)));
}
function tglStrat(i){$('#sd'+i).classList.toggle('open')}
function spark(cv,data){
  if(!cv||data.length<2)return;
  const dpr=devicePixelRatio||1,w=cv.clientWidth||300,h=44;
  cv.width=w*dpr;cv.height=h*dpr;
  const x=cv.getContext('2d');x.scale(dpr,dpr);
  const mn=Math.min(...data),mx=Math.max(...data),sp=mx-mn||1;
  const up=data[data.length-1]>=data[0];
  x.strokeStyle=up?'#c8f563':'#ff6b4a';x.lineWidth=1.4;x.beginPath();
  data.forEach((v,i)=>{const px=i/(data.length-1)*w,py=h-4-((v-mn)/sp)*(h-8);i?x.lineTo(px,py):x.moveTo(px,py)});
  x.stroke();
  x.fillStyle=x.strokeStyle;
  x.beginPath();x.arc(w-1.5,h-4-((data[data.length-1]-mn)/sp)*(h-8),2,0,7);x.fill();
}

/* ── router ── */
function go(v){
  $$('section[data-view]').forEach(s=>s.classList.toggle('on',s.dataset.view===v));
  $$('#rail .nav-it[data-nav]').forEach(n=>n.classList.toggle('on',n.dataset.nav===v));
  $('#viewTitle').textContent=v==='rsps'?'RSPS':v[0].toUpperCase()+v.slice(1);
  if(location.hash!=='#'+v)history.replaceState(null,'','#'+v);
  if(v==='overview')drawChart();
}
$$('#rail .nav-it[data-nav]').forEach(n=>n.addEventListener('click',()=>go(n.dataset.nav)));
addEventListener('hashchange',()=>go(location.hash.slice(1)||'overview'));

/* ── command palette ── */
const CMDS=[
  ['Go to Overview','view',()=>go('overview')],
  ['Go to RSPS','view',()=>go('rsps')],
  ['Go to Strategies','view',()=>go('strategies')],
  ['Open History lab','link',()=>location.href='?action=history'],
  ['Open Classic UI','link',()=>location.href='?'],
  ['Force rebalance','action',actForce],
  ['Halt / resume trading','action',actHalt],
  ['Health check','action',()=>window.open('?action=health')],
  ['Refresh feeds','action',()=>loadAll(true)],
];
let palSel=0;
function palOpen(){$('#pal').classList.add('open');$('#palIn').value='';palRender('');$('#palIn').focus()}
function palClose(){$('#pal').classList.remove('open')}
function palRender(q){
  const hits=CMDS.filter(c=>c[0].toLowerCase().includes(q.toLowerCase()));
  palSel=Math.min(palSel,Math.max(0,hits.length-1));
  $('#palList').innerHTML=hits.map((c,i)=>'<div class="pal-it'+(i===palSel?' sel':'')+'" data-i="'+CMDS.indexOf(c)+'">'+
    '<span>'+c[0]+'</span><span class="hint">'+c[1]+'</span></div>').join('');
}
addEventListener('keydown',e=>{
  if((e.metaKey||e.ctrlKey)&&e.key.toLowerCase()==='k'){e.preventDefault();palOpen()}
  if(!$('#pal').classList.contains('open'))return;
  const hits=CMDS.filter(c=>c[0].toLowerCase().includes($('#palIn').value.toLowerCase()));
  if(e.key==='Escape')palClose();
  if(e.key==='ArrowDown'){e.preventDefault();palSel=Math.min(palSel+1,hits.length-1);palRender($('#palIn').value)}
  if(e.key==='ArrowUp'){e.preventDefault();palSel=Math.max(palSel-1,0);palRender($('#palIn').value)}
  if(e.key==='Enter'&&hits[palSel]){palClose();hits[palSel][2]()}
});
$('#palIn').addEventListener('input',e=>{palSel=0;palRender(e.target.value)});
$('#pal').addEventListener('click',e=>{
  if(e.target.id==='pal')palClose();
  const it=e.target.closest('.pal-it');if(it){palClose();CMDS[+it.dataset.i][2]()}
});

/* ── misc ── */
function toast(t){const el=$('#toast');el.textContent=t;el.classList.toggle('show',!!t);
  if(t)setTimeout(()=>el.classList.remove('show'),4000)}
setInterval(()=>{$('#clock').textContent=new Date().toISOString().slice(11,19)+' UTC'},1000);
setInterval(()=>loadAll(false).catch(()=>{}),120000);

loadAll(false).then(()=>go(location.hash.slice(1)||'overview'))
  .catch(e=>{toast('feed error: '+e.message)});
</script>
</body>
</html>"""

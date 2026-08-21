"""SDCA tab — Investing Campus BTC Strategic Dollar Cost Averaging signal.

Ported from Tobiasz's standalone Railway app. The analysis engine is embedded
verbatim in sdca_engine.py (generated); everything here is WealthOS chrome:
markup, aurora-glass CSS, and a boundary wrapper that re-renders the EQM
Rainbow and Composite Risk charts natively in Chart.js (the site's chart
language) while leaving the engine's own code untouched.

Display & research only — execution wiring lands with the Phase-3 allocator.
"""
from signalbot.config import *
from signalbot.ui.shared import *
from signalbot.ui.sdca_engine import ENGINE_JS

__all__ = ['_render_sdca', '_SDCA_HTML']


# ── page shell: fonts/CSS/markup ─────────────────────────────────────────────
_TEMPLATE = r"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1, maximum-scale=1">
<title>WealthOS — SDCA</title>
<script src="https://cdnjs.cloudflare.com/ajax/libs/plotly.js/2.35.3/plotly.min.js"></script>
<script src="https://cdnjs.cloudflare.com/ajax/libs/Chart.js/4.4.1/chart.umd.js"></script>
__THEME_HEAD__
<style>

  .sdca-wrap{display:grid;grid-template-columns:300px minmax(0,1fr);gap:16px;align-items:start}
  @media(max-width:900px){.sdca-wrap{grid-template-columns:1fr}}
  .side{display:flex;flex-direction:column;gap:12px}
  .card{position:relative;background:var(--glass);border:1px solid var(--border);border-radius:14px;padding:14px 16px;
    backdrop-filter:blur(14px);-webkit-backdrop-filter:blur(14px);
    box-shadow:0 14px 34px -16px rgba(0,0,0,.6),inset 0 1px 0 rgba(255,255,255,.05);font-size:12px}
  .card b{font-family:var(--font-display);font-weight:700}
  .card label{font-size:10px;letter-spacing:.08em;text-transform:uppercase;color:var(--muted);display:block;margin:8px 0 4px}
  .card input[type=number],.card input[type=text],.backtestPanel input{width:100%;background:rgba(0,0,0,.35);
    border:1px solid var(--border2);border-radius:9px;color:var(--text);font-family:var(--font-mono);
    font-size:13px;padding:7px 10px;outline:none;transition:border-color .25s,box-shadow .25s}
  .card input:focus,.backtestPanel input:focus{border-color:rgba(200,245,99,.5);box-shadow:0 0 0 3px rgba(200,245,99,.1)}
  .card input[type=checkbox]{accent-color:var(--accent)}
  #todayCard{border:1px solid rgba(200,245,99,.4) !important;box-shadow:0 0 26px -8px rgba(200,245,99,.25),inset 0 1px 0 rgba(255,255,255,.05) !important}
  .row{display:flex;justify-content:space-between;gap:10px;margin-top:4px;font-variant-numeric:tabular-nums}
  .row span{color:var(--muted)}
  .small{font-size:11px;color:var(--muted);line-height:1.55}
  .warn{color:var(--red)}
  #loadBtn,.sideToggle,.sideShowToggle{display:none !important}
  .progressWrap{height:3px;background:rgba(255,255,255,.08);border-radius:2px;overflow:hidden;margin-top:8px}
  .progressBar{height:100%;width:0;background:var(--grad);border-radius:2px;transition:width .3s;box-shadow:0 0 10px rgba(200,245,99,.5)}
  .progressText{font-size:10px;color:var(--faint,#4e4a44);margin-top:3px}

  .chartbox{min-width:0}
  .tabbar{display:flex;gap:4px;background:rgba(255,255,255,.045);border:1px solid var(--border);
    border-radius:999px;padding:3px;width:max-content;max-width:100%;overflow-x:auto;margin-bottom:14px}
  .tabbtn{font-size:11px;font-family:var(--font-mono);letter-spacing:.07em;text-transform:uppercase;
    padding:6px 14px;border-radius:999px;cursor:pointer;color:var(--muted);border:none;background:none;
    transition:color .25s var(--ease);white-space:nowrap}
  .tabbtn:hover:not(.active){color:var(--text)}
  .tabbtn.active{color:#10130a;background:var(--grad);font-weight:500;box-shadow:0 0 18px rgba(200,245,99,.3)}
  .tabpane{display:none}
  .tabpane.active{display:block;animation:wosRise .5s var(--ease)}
  .eqmLegendControl{display:flex;align-items:center;gap:7px;font-size:11px;color:var(--muted);margin:0 0 6px;cursor:pointer}
  input[type=checkbox]{accent-color:var(--accent)}
  #chart,#cqmChart,#curveChart{width:100%;background:var(--glass);border:1px solid var(--border);border-radius:16px;overflow:hidden;
    box-shadow:0 20px 48px -20px rgba(0,0,0,.65),inset 0 1px 0 rgba(255,255,255,.05)}
  #chart{height:640px} #cqmChart{height:520px} #curveChart{height:460px}
  /* native aurora charts (Chart.js replacements for EQM + Composite) */
  #chart,#cqmChart{display:flex;flex-direction:column}
  .wosClegend{display:flex;gap:6px 16px;flex-wrap:wrap;padding:12px 16px 6px;font-size:10.5px;color:var(--muted);flex-shrink:0}
  .wosCli{display:inline-flex;align-items:center;gap:6px;white-space:nowrap}
  .wosCli i{width:8px;height:8px;border-radius:50%;flex-shrink:0;box-shadow:0 0 8px currentColor;display:inline-block}
  /* the canvas is absolutely positioned so it always has a definite box —
     Chart.js sizes on creation, and Composite is pre-warmed while its pane is
     still display:none (a flex-sized canvas would come out 0x0 there) */
  .wosCbody{flex:1;position:relative;min-height:0;padding:4px 10px 10px}
  .wosCbody canvas{position:absolute;inset:4px 10px 10px}

  .cqmHead h2,.backtestHead h2{font-family:var(--font-display);font-style:italic;font-size:20px;font-weight:700;margin:2px 0 4px}
  .desc{font-size:11px;color:var(--muted) !important;margin:2px 0 8px}
  .cqmBadges{display:flex;gap:6px;flex-wrap:wrap;margin:8px 0 10px;align-items:center}
  .cqmBadgeStack{display:flex;gap:6px;align-items:center}
  .cqmBadge{font-size:10px;letter-spacing:.06em;text-transform:uppercase;padding:2px 9px;border-radius:999px;border:1px solid var(--border2);color:var(--muted)}
  .cqmBadge.buy{color:#22c55e;border-color:rgba(34,197,94,.4)}
  .cqmBadge.acc{color:var(--accent);border-color:rgba(200,245,99,.4)}
  .cqmBadge.trim{color:var(--amber);border-color:rgba(245,166,35,.4)}
  .cqmBadge.sell{color:var(--red);border-color:rgba(255,92,92,.4)}
  .cqmBadge.z{color:var(--blue);border-color:rgba(91,156,246,.4);display:inline-flex;gap:6px;align-items:center;cursor:pointer}

  .curveEditorHead{display:flex;justify-content:space-between;align-items:center;gap:10px;flex-wrap:wrap;margin:10px 0 8px}
  .curveResetBtn{background:none;border:1px solid var(--border2);color:var(--text);font-family:var(--font-mono);
    font-size:10px;letter-spacing:.1em;text-transform:uppercase;padding:6px 13px;border-radius:999px;cursor:pointer;transition:all .25s var(--ease)}
  .curveResetBtn:hover{border-color:rgba(200,245,99,.45);color:var(--accent)}
  .curveEditorBox{background:var(--glass);border:1px solid var(--border);border-radius:16px;padding:10px;margin-bottom:12px;
    box-shadow:0 14px 34px -16px rgba(0,0,0,.6),inset 0 1px 0 rgba(255,255,255,.05)}
  #curveEditorSvg{width:100%;height:auto;display:block}
  /* retheme the SVG curve editor (engine sets presentation attributes; CSS wins) */
  #curveEditorSvg rect[fill="rgba(34,197,94,.07)"]{fill:rgba(200,245,99,.06)}
  #curveEditorSvg rect[fill="rgba(255,68,68,.07)"]{fill:rgba(255,92,92,.06)}
  #curveEditorSvg line[stroke="rgba(230,237,243,.55)"]{stroke:rgba(233,228,216,.5)}
  #curveEditorSvg path[stroke="#4ea6c9"]{stroke:var(--accent);filter:drop-shadow(0 0 5px rgba(200,245,99,.45))}
  #curveEditorSvg circle.curveNode{fill:var(--accent);stroke:#0a0b0c;cursor:grab}
  #curveEditorSvg circle.curveNode:active{cursor:grabbing}
  #curveEditorSvg text{fill:#8a877e}
  #curveEditorSvg text[fill="#e6edf3"]{fill:#e9e4d8}

  .backtestGrid{display:grid;grid-template-columns:230px minmax(0,1fr);gap:14px;margin:10px 0 6px}
  @media(max-width:760px){.backtestGrid{grid-template-columns:1fr}}
  .backtestPanel{background:var(--glass);border:1px solid var(--border);border-radius:14px;padding:14px}
  .backtestPanel label{font-size:10px;letter-spacing:.08em;text-transform:uppercase;color:var(--muted);display:block;margin:8px 0 4px}
  .backtestDateMeta label{margin:0 0 4px}
  .backtestResults{display:grid;grid-template-columns:repeat(auto-fill,minmax(150px,1fr));gap:8px}
  .backtestMetric{background:var(--glass);border:1px solid var(--border);border-radius:12px;padding:10px 12px;
    transition:transform .25s var(--ease),border-color .25s}
  .backtestMetric:hover{transform:translateY(-2px);border-color:rgba(200,245,99,.25)}
  .backtestMetric .k{font-size:9px;letter-spacing:.14em;text-transform:uppercase;color:var(--faint,#4e4a44)}
  .backtestMetric .v{font-family:var(--font-display);font-size:16px;font-weight:700;margin-top:2px;font-variant-numeric:tabular-nums}
  .backtestMetric .d{font-size:10px;color:var(--muted)}
  .backtestPlotBox{margin-top:8px}

  /* ── Mobile ── */
  @media(max-width:700px){
    .main{padding-left:14px;padding-right:14px}
    /* desktop chart heights eat several phone screens */
    #chart{height:400px} #cqmChart{height:330px} #curveChart{height:300px}
    .tabbar{width:100%;overflow-x:auto;-webkit-overflow-scrolling:touch;scrollbar-width:none}
    .tabbar::-webkit-scrollbar{display:none}
    .tabbtn{flex-shrink:0}
    .card{padding:13px 14px}
    .cqmHead h2,.backtestHead h2{font-size:17px}
    .cqmBadges{gap:5px}
    .cqmBadge{font-size:9.5px;padding:2px 7px}
    .backtestResults{grid-template-columns:1fr 1fr;gap:7px}
    .backtestMetric{padding:9px 10px}
    .backtestMetric .v{font-size:14px}
    .curveEditorHead{gap:8px}
    .curveEditorBox{padding:6px}
    .wosClegend{padding:10px 12px 4px;gap:5px 12px;font-size:10px}
    .wosCbody{padding:2px 6px 8px}
  }
  @media(max-width:480px){
    #chart{height:340px} #cqmChart{height:290px} #curveChart{height:260px}
    .backtestResults{grid-template-columns:1fr}
  }

</style>
</head>
<body>

__NAV_PLACEHOLDER__
  <div class="sdca-wrap">
    <aside class="side">
      <button id="sideToggleBtn" class="sideToggle" type="button">Hide menu</button>
      <button id="loadBtn">Load BTC Data</button>
      <div class="card small" id="status">Loading model…<div class="progressWrap"><div id="progressBar" class="progressBar"></div></div><div id="progressText" class="progressText">0%</div></div>
      <div class="card" id="todayCard">
        <b>Today's Model Action</b>
        <div class="small" style="margin:6px 0 8px">What the active Accum/Dist curve says to do today at today's Composite Risk. Enter your cash reserve for the exact amount.</div>
        <label>Your cash reserve, USD</label>
        <input id="todayCashInput" type="number" value="0" min="0" step="100"/>
        <div class="row" style="margin-top:10px"><span>Composite Risk today</span><b id="todayRisk">—</b></div>
        <div class="row"><span>Curve rate today</span><b id="todayRate">—</b></div>
        <div class="row" style="margin-top:6px;font-size:15px"><span>Action</span><b id="todayAction">—</b></div>
        <div class="small wos-money" id="todayAmount" style="margin-top:3px;color:var(--text);font-weight:700">—</div>
        <div class="small wos-money" id="todayPortfolio" style="margin-top:7px">—</div>
      </div>
      <div class="card">
        <div class="row"><b>Price</b><b id="mPrice">—</b></div>
        <div class="row"><span>Composite Median</span><b id="mEq">—</b></div>
        <div class="row"><span>Q1% rail</span><b id="mLowRail">—</b></div>
        <div class="row"><span>Q99% rail</span><b id="mHighRail">—</b></div>
        <div class="row"><span>EQM Risk</span><b id="mRisk">—</b></div>
        <div class="row"><span>Composite Risk</span><b id="mCqmRisk">—</b></div>
        <div class="row"><span>Composite Z-score</span><b id="mCqmZScore">—</b></div>
        <div class="row"><span>Blend Z-score</span><b id="mCompositeZScore">—</b></div>
        <div class="row"><span>Current band</span><b id="mBand">—</b></div>
      </div>
      <div class="card">
        <b>Indicators</b>
        <div class="small" style="margin:6px 0 8px">Signals blended into Composite Risk — each enabled indicator is an equal-weight vote.</div>
        <div class="row" style="align-items:center">
          <label style="display:flex;align-items:center;gap:7px;margin:0;font-size:12px;color:var(--text);text-transform:none;letter-spacing:0"><input id="indPriceToggle" type="checkbox" checked style="width:auto;margin:0"/> Asymmetric Tail Curvature (price)</label>
        </div>
        <div class="row" style="align-items:center;margin-top:8px">
          <label style="display:flex;align-items:center;gap:7px;margin:0;font-size:12px;color:var(--text);text-transform:none;letter-spacing:0"><input id="indSharpeToggle" type="checkbox" style="width:auto;margin:0"/> Sharpe (realized P/L, 14d EMA)</label>
        </div>
        <div class="row" style="align-items:center;margin-top:8px">
          <label style="display:flex;align-items:center;gap:7px;margin:0;font-size:12px;color:var(--text);text-transform:none;letter-spacing:0"><input id="indCbplToggle" type="checkbox" checked style="width:auto;margin:0"/> Cost Basis P/L Ratio (7d EMA)</label>
        </div>
        <div class="row" style="align-items:center;margin-top:8px">
          <label style="display:flex;align-items:center;gap:7px;margin:0;font-size:12px;color:var(--text);text-transform:none;letter-spacing:0"><input id="indOnchainToggle" type="checkbox" checked style="width:auto;margin:0"/> Onchain Risk Composite (7d EMA)</label>
        </div>
      </div>
      <div class="card">
        <b>Live band levels</b>
        <div id="bandList" class="small"></div>
      </div>
    </aside>
    <main class="chartbox">
      <div class="tabbar">
        <button id="sideShowBtn" class="sideShowToggle" type="button" title="Show menu" aria-label="Show menu">►</button>
        <button id="eqmTabBtn" class="tabbtn active" type="button">EQM Rainbow</button>
        <button id="cqmTabBtn" class="tabbtn" type="button">Composite Risk</button>
        <button id="curveTabBtn" class="tabbtn" type="button">Accum/Dist Curve</button>
      </div>
      <div id="eqmPane" class="tabpane active">
        <label class="eqmLegendControl"><input id="legendToggle" type="checkbox" checked/> Show legend</label>
        <div id="chart"></div>
      </div>
      <div id="cqmPane" class="tabpane">
        <div class="cqmWrap">
          <div class="cqmHead">
            <h2>Composite Risk</h2>
            <div class="desc">Valuation risk, not DCA allocation. Low = cheap / more buyable; high = expensive / less buyable.</div>
            <div class="cqmBadges">
              <div class="cqmBadgeStack">
                <span class="cqmBadge buy">0–25% Buy zone</span>
                <label class="cqmBadge z cqmZToggle"><input id="cqmZToggle" type="checkbox" checked style="width:auto;margin:0;accent-color:var(--blue)"/> Show Z line</label>
              </div>
              <span class="cqmBadge acc">25–50% Accumulate</span>
              <span class="cqmBadge trim">50–75% Trim</span>
              <span class="cqmBadge sell">75–100% Sell zone</span>
              <span id="cqmZBadge" class="cqmBadge z">Z-score</span>
            </div>
          </div>
          <div class="cqmPlotBox"><div id="cqmChart"></div></div>
        </div>
      </div>
      <div id="curvePane" class="tabpane">
        <div class="backtestWrap">
          <div class="backtestHead">
            <h2>Accumulation / Distribution Curve</h2>
            <div class="desc">Each day, the curve value at that day's Composite Risk is the % of cash bought (positive) or % of BTC sold (negative). Drag the nodes to shape it.</div>
          </div>
          <div class="curveEditorHead">
            <span class="small">X = Composite Risk %, Y = % of cash/BTC traded per day.</span>
            <div style="display:flex;gap:10px;align-items:center;flex-wrap:wrap">
              <button id="curveExportBtn" class="curveResetBtn" type="button">Export CSV</button>
              <button id="curveResetBtn" class="curveResetBtn" type="button">Reset curve</button>
            </div>
          </div>
          <div class="curveEditorBox">
            <svg id="curveEditorSvg" viewBox="0 0 760 300" preserveAspectRatio="xMidYMid meet"></svg>
          </div>
          <div class="backtestGrid">
            <div class="backtestPanel">
              <div class="backtestDates" style="grid-template-columns:1fr">
                <div class="backtestDateField">
                  <div class="backtestDateMeta"><label for="curveStartInput">Starting date</label></div>
                  <input id="curveStartInput" type="text" inputmode="numeric" autocomplete="off" maxlength="10" value="2015-01-01" placeholder="YYYY-MM-DD"/>
                </div>
              </div>
              <label>Starting capital, USD</label>
              <input id="curveCashInput" type="number" value="10000" min="0" step="100"/>
              <div id="curveStatus" class="small" style="margin-top:8px">Loading…</div>
            </div>
            <div class="backtestResults">
              <div class="backtestMetric"><div class="k">Backtest days</div><div id="cvDays" class="v">—</div><div id="cvBuyDays" class="d">—</div></div>
              <div class="backtestMetric"><div class="k">Starting capital</div><div id="cvStartingCash" class="v">—</div><div class="d"></div></div>
              <div class="backtestMetric"><div class="k">Net BTC position</div><div id="cvBtc" class="v">—</div><div id="cvAvgBuy" class="d">—</div></div>
              <div class="backtestMetric"><div class="k">Portfolio value</div><div id="cvBtcValue" class="v">—</div><div class="d">BTC+Cash</div></div>
              <div class="backtestMetric"><div class="k">P/L</div><div id="cvPnl" class="v">—</div><div id="cvReturn" class="d">—</div></div>
              <div class="backtestMetric"><div class="k">Avg daily rate</div><div id="cvAvgRate" class="v">—</div><div id="cvAvgRisk" class="d">—</div></div>
              <div class="backtestMetric"><div class="k">Lump sum value</div><div id="cvLumpValue" class="v">—</div><div id="cvLumpReturn" class="d">—</div></div>
              <div class="backtestMetric"><div class="k">vs lump sum</div><div id="cvVsLump" class="v">—</div><div id="cvVsLumpPct" class="d">—</div></div>
              <div class="backtestMetric"><div class="k">Cash reserve</div><div id="cvCash" class="v">—</div><div class="d">Includes curve sells</div></div>
              <div class="backtestMetric"><div class="k">Max DD — DCA</div><div id="cvMddDca" class="v">—</div><div class="d">Peak-to-trough</div></div>
              <div class="backtestMetric"><div class="k">Max DD — Hold</div><div id="cvMddBh" class="v">—</div><div class="d">Peak-to-trough</div></div>
            </div>
          </div>
          <div style="display:flex;justify-content:flex-end;padding:4px 8px 0">
            <label style="display:flex;align-items:center;gap:6px;font-size:12px;color:var(--muted);cursor:pointer;white-space:nowrap"><input id="curveLogToggle" type="checkbox" style="accent-color:var(--accent)"/> Log scale</label>
          </div>
          <div class="backtestPlotBox"><div id="curveChart"></div></div>
        </div>
      </div>
    </main>
  </div>
</div>
"""


# ── boundary wrapper: native aurora charts + Plotly theming fallback ─────────
_WRAPPER_JS = r"""
/* WealthOS: deep-theme Plotly at the boundary — every color the engine emits
   is translated to the aurora-glass palette. The engine itself is untouched. */
(function(){
  if(!window.Plotly) return;
  const MAP = {
    /* rainbow bands, cheap -> expensive — high enough alpha to stay luminous
       on the black canvas (low alpha reads as mud) */
    'rgba(23,60,112,0.58)':'rgba(91,156,246,.46)',
    'rgba(33,131,142,0.58)':'rgba(126,245,208,.40)',
    'rgba(56,160,75,0.58)':'rgba(200,245,99,.38)',
    'rgba(214,196,32,0.58)':'rgba(245,166,35,.36)',
    'rgba(228,116,28,0.58)':'rgba(255,138,74,.40)',
    'rgba(190,10,18,0.58)':'rgba(255,92,92,.44)',
    /* chrome + inks */
    '#060f1b':'rgba(12,14,16,.94)',
    '#0c1118':'#0a0b0c',
    '#12263a':'rgba(255,255,255,.06)',
    '#e8eef5':'#e9e4d8', '#e6edf3':'#e9e4d8',
    '#8ea0b3':'#8a877e',
    '#4ea6c9':'#c8f563',
    '#5fb8ff':'#5b9cf6',
    'rgba(78,166,201,.55)':'rgba(200,245,99,.5)',
    /* semantic greens/ambers/reds */
    '#22c55e':'#7ef5d0', '#95d81d':'#c8f563', '#24e572':'#7ef5d0',
    '#f59e0b':'#f0b445', '#d4a756':'#f0b445',
    '#ff4444':'#ff5c5c', '#ff5656':'#ff5c5c', '#ff5c61':'#ff5c5c',
    /* grids / axis tints */
    'rgba(232,238,245,.45)':'rgba(233,228,216,.45)',
    'rgba(232,238,245,.4)':'rgba(233,228,216,.4)',
    'rgba(232,238,245,.9)':'rgba(233,228,216,.9)',
    'rgba(232,238,245,.07)':'rgba(255,255,255,.06)',
    'rgba(232,238,245,.06)':'rgba(255,255,255,.055)',
    'rgba(232,238,245,.05)':'rgba(255,255,255,.05)',
    'rgba(80,90,105,.16)':'rgba(255,255,255,.06)',
    /* backtest zone tints */
    'rgba(15,94,72,.32)':'rgba(126,245,208,.12)',
    'rgba(43,113,63,.30)':'rgba(200,245,99,.12)',
    'rgba(117,92,40,.28)':'rgba(245,166,35,.12)'
  };
  const fix = v => (typeof v==='string' && MAP[v]) ? MAP[v] : v;
  /* Per-trace declutter: exactly one hero line (BTC price). The median becomes
     a dotted ghost, the rails go translucent-thin. Matched by name prefix so
     the engine stays untouched. */
  function dressTraces(data){
    if(!Array.isArray(data)) return;
    for(const t of data){
      const n = t && t.name || '';
      if(!t || !t.line) continue;
      if(n.indexOf('Q50% median')===0){ t.line=Object.assign({},t.line,{color:'rgba(233,228,216,.55)',width:1.3,dash:'dot'}); }
      else if(n.indexOf('Q99% rail')===0){ t.line=Object.assign({},t.line,{color:'rgba(255,92,92,.8)',width:1}); }
      else if(n.indexOf('Q1% rail')===0){ t.line=Object.assign({},t.line,{color:'rgba(91,156,246,.8)',width:1}); }
    }
  }
  function walk(o, depth){
    if(!o || typeof o!=='object' || depth>9) return;
    if(Array.isArray(o)){ o.forEach(x=>walk(x,depth+1)); return; }
    for(const k of Object.keys(o)){
      const v = o[k];
      if(typeof v==='string' && k.toLowerCase().includes('color')) o[k]=fix(v);
      else if(Array.isArray(v) && k.toLowerCase().includes('color')) o[k]=v.map(fix);
      else if(v && typeof v==='object') walk(v,depth+1);
    }
  }
  /* Aurora chart grammar: hairline y-grid only, no axis lines/ticks, y on the
     right, dim mono tick text, floaty legend, no modebar — the same voice as
     the Chart.js charts on the other tabs. */
  const TICKFONT = {family:"'DM Mono',monospace",size:10,color:'#54504a'};
  function styleAxis(ax, isY, allowRightSide){
    if(!ax) return;
    ax.showline=false; ax.mirror=false; ax.ticks='';
    ax.tickfont=Object.assign({},ax.tickfont||{},TICKFONT);   // ours wins
    ax.gridwidth=1;
    ax.zerolinecolor='rgba(255,255,255,.08)'; ax.zerolinewidth=1;
    if(isY){
      ax.gridcolor='rgba(255,255,255,.04)';
      if(allowRightSide && ax.side===undefined) ax.side='right';
    }else{
      if(ax.showgrid!==true) ax.showgrid=false;   // kill vertical grid unless engine insists
      if(ax.rangeslider){                          // slim the rangeslider if present
        ax.rangeslider=Object.assign(ax.rangeslider,{bgcolor:'rgba(255,255,255,.03)',
          bordercolor:'rgba(255,255,255,.08)',thickness:0.05});
      }
    }
    if(ax.title && typeof ax.title==='object'){
      ax.title.font=Object.assign({},TICKFONT,(ax.title.font||{}));
    }
  }
  function theme(layout){
    layout = layout || {};
    walk(layout,0);
    layout.paper_bgcolor = 'rgba(0,0,0,0)';
    layout.plot_bgcolor = 'rgba(0,0,0,0)';
    layout.font = Object.assign({family:"'DM Mono',monospace",size:11,color:'#8a877e'}, layout.font||{});
    layout.legend = Object.assign({}, layout.legend||{}, {bgcolor:'rgba(0,0,0,0)',
      borderwidth:0, bordercolor:'rgba(0,0,0,0)',
      orientation:'h', x:0, xanchor:'left', y:1.02, yanchor:'bottom',
      font:{family:"'DM Mono',monospace",size:10,color:'#8a877e'}});
    // legend lives ABOVE the plot as a quiet strip (matches the Chart.js
    // legends elsewhere) — never boxed inside the canvas over the ticks;
    // give it top-margin headroom so wrapped rows don't clip
    layout.margin = Object.assign({}, layout.margin||{},
      {t: Math.max(((layout.margin||{}).t)||0, 96)});
    layout.hoverlabel = Object.assign({bordercolor:'#2c3136',font:{family:"'DM Mono',monospace",size:11,color:'#e9e4d8'}}, layout.hoverlabel||{});
    if(layout.title) layout.title='';            // panes carry their own headings
    const hasY2 = Object.keys(layout).some(k=>/^yaxis\d+$/.test(k));
    if(!layout.xaxis) layout.xaxis={};
    if(!layout.yaxis) layout.yaxis={};
    for(const k of Object.keys(layout)){
      if(/^xaxis\d*$/.test(k)) styleAxis(layout[k],false,false);
      else if(k==='yaxis') styleAxis(layout[k],true,!hasY2);
      else if(/^yaxis\d+$/.test(k)) styleAxis(layout[k],true,false);
    }
    return layout;
  }
  function conf(cfg){ return Object.assign({displayModeBar:false,responsive:true}, cfg||{}); }
  /* ── Native aurora renderers ─────────────────────────────────────────────
     The EQM Rainbow and Composite Risk charts are re-drawn in Chart.js (the
     site's chart language) from the series the engine computed. The engine's
     Plotly calls for those two containers are hijacked; everything else
     (curve backtest chart) stays themed Plotly. On any extraction error we
     fall back to themed Plotly so nothing ever breaks. */
  const WOS_CHARTS = {};   // live Chart.js instances by container id
  const WOS_SOURCE = {};   // last series drawn, so a chart can be rebuilt
  function freshCanvas(container, legendHtml){
    (WOS_CHARTS[container.id]||{destroy(){}}).destroy();
    delete WOS_CHARTS[container.id];
    container.innerHTML =
      (legendHtml?'<div class="wosClegend">'+legendHtml+'</div>':'') +
      '<div class="wosCbody"><canvas></canvas></div>';
    return container.querySelector('canvas');
  }
  /* Build + register + self-heal. A chart constructed in the same frame a pane
     becomes visible (the engine re-renders on tab switch) can still measure a
     zero box; re-measure on the next frames instead of trusting the first. */
  function mount(container, cfg){
    const cv = container.querySelector('canvas');
    const ch = new Chart(cv, cfg);
    WOS_CHARTS[container.id] = ch;
    // timers, not rAF: a background/hidden tab pauses animation frames, and
    // a chart must still be correctly sized when its pane is finally shown
    const heal = tries => setTimeout(()=>{
      if(container.clientHeight && !cv.clientWidth){
        cv.style.width=''; cv.style.height='';
        try{ ch.resize(); }catch(e){}
      }
      if(tries > 0 && !cv.clientWidth) heal(tries - 1);
    }, 60);
    heal(6);
    return ch;
  }
  const GRID={color:'rgba(255,255,255,.04)'};
  const TICKS={color:'#54504a',font:{family:"'DM Mono',monospace",size:10}};
  const TIP={backgroundColor:'#14171a',borderColor:'#2c3136',borderWidth:1,
    titleColor:'#54504a',bodyColor:'#e9e4d8',
    titleFont:{family:"'DM Mono',monospace",size:10},
    bodyFont:{family:"'DM Mono',monospace",size:11}};
  const dot=(c,t)=>'<span class="wosCli"><i style="background:'+c+'"></i>'+t+'</span>';
  const fmtD=d=>new Date(d).toLocaleDateString('en-GB',{month:'short',year:'numeric'});

  function drawEqm(container, data){
    const price = data.find(t=>t.name==='BTC price');
    if(!price || !Array.isArray(price.x)) throw new Error('no price trace');
    const n = price.x.length, step = Math.max(1, Math.ceil(n/1200));
    const pick = arr => { const o=[]; for(let i=0;i<n;i+=step) o.push(arr[i]); if((n-1)%step) o.push(arr[n-1]); return o; };
    const labels = pick(price.x).map(fmtD);

    const bands=[];
    data.forEach((t,i)=>{ if(t.fill==='tonexty' && i>0) bands.push({lo:t, hi:data[i-1], color:t.fillcolor, name:t.name||''}); });
    const byName = p => data.find(t=>(t.name||'').indexOf(p)===0);
    const q99=byName('Q99% rail'), q1=byName('Q1% rail'), med=byName('Q50% median'), zt=byName('z-score');

    const ds=[];
    for(const b of bands){
      ds.push({data:pick(b.hi.y),borderWidth:0,pointRadius:0,fill:false,order:50});
      ds.push({data:pick(b.lo.y),borderWidth:0,pointRadius:0,fill:'-1',backgroundColor:b.color,order:50});
    }
    if(q99) ds.push({data:pick(q99.y),borderColor:'rgba(255,92,92,.8)',borderWidth:1,pointRadius:0,fill:false,order:20,tension:.2});
    if(q1)  ds.push({data:pick(q1.y), borderColor:'rgba(91,156,246,.8)',borderWidth:1,pointRadius:0,fill:false,order:20,tension:.2});
    if(med) ds.push({data:pick(med.y),borderColor:'rgba(233,228,216,.55)',borderWidth:1.2,borderDash:[2,4],pointRadius:0,fill:false,order:15,tension:.2});
    const py=pick(price.y);
    ds.push({label:'BTC price',data:py,borderColor:'#f4f1ea',borderWidth:1.7,pointRadius:0,fill:false,order:1,
      pointHoverRadius:4,pointHoverBackgroundColor:'#c8f563',tension:.2});
    ds.push({data:py.map((v,i)=>i===py.length-1?v:null),pointStyle:'rectRot',pointRadius:6,
      pointBackgroundColor:'#0a0b0c',pointBorderColor:'#c8f563',pointBorderWidth:1.6,showLine:false,order:0});

    let lg = dot('#f4f1ea','BTC price');
    if(zt && zt.name) lg += dot('#c8f563',zt.name.replace(/\s+/g,' '));
    if(q99) lg += dot('rgba(255,92,92,.9)',(q99.name||'Q99% rail'));
    if(q1)  lg += dot('rgba(91,156,246,.9)',(q1.name||'Q1% rail'));
    if(med) lg += dot('rgba(233,228,216,.8)',(med.name||'Q50% median'));
    for(const b of bands) lg += dot(b.color,(b.name||'').replace(/\s+/g,' '));

    freshCanvas(container, lg);
    return mount(container,{type:'line',
      data:{labels,datasets:ds},
      options:{responsive:true,maintainAspectRatio:false,animation:{duration:600},
        interaction:{mode:'index',intersect:false},
        plugins:{legend:{display:false},tooltip:Object.assign({},TIP,{
          filter:c=>c.dataset.label==='BTC price',
          callbacks:{label:c=>' $'+(+c.parsed.y).toLocaleString('en-US',{maximumFractionDigits:0})}})},
        scales:{
          x:{grid:{display:false},ticks:Object.assign({maxTicksLimit:8,maxRotation:0},TICKS),border:{display:false}},
          y:{type:'logarithmic',position:'right',grid:GRID,border:{display:false},
             ticks:Object.assign({callback:v=>{
               const l=Math.log10(v); if(Math.abs(l-Math.round(l))>1e-9) return null;
               return v>=1e6?'$'+(v/1e6)+'M':v>=1e3?'$'+(v/1e3)+'K':'$'+v;
             }},TICKS)}
        }}});
  }

  function drawCqm(container, data){
    const zTrace = data.find(t=>t.yaxis==='y3');
    const cands  = data.filter(t=>t!==zTrace && Array.isArray(t.y) && Array.isArray(t.x));
    const nMax   = Math.max(...cands.map(t=>t.y.length));
    const base   = cands.find(t=>t.y.length===nMax);
    if(!base) throw new Error('no risk series');
    const full   = cands.filter(t=>t.y.length===nMax);
    const risk   = []; for(let i=0;i<nMax;i++){ let v=null;
      for(const t of full){ const y=t.y[i]; if(y!=null && isFinite(y)){ v=y; break; } } risk.push(v); }
    const step = Math.max(1, Math.ceil(nMax/1200));
    const pick = arr => { const o=[]; for(let i=0;i<nMax;i+=step) o.push(arr[i]); if((nMax-1)%step) o.push(arr[nMax-1]); return o; };
    const labels = pick(base.x).map(fmtD);
    const zone = v => v==null?'#54504a': v<25?'#7ef5d0': v<50?'#c8f563': v<75?'#f0b445':'#ff5c5c';
    const showZ = !!(document.getElementById('cqmZToggle')||{}).checked && zTrace;

    const ds=[{label:'Composite Risk',data:pick(risk),borderWidth:1.6,pointRadius:0,fill:false,order:1,
      pointHoverRadius:4,tension:.25,
      segment:{borderColor:c=>zone(c.p1.parsed.y)},borderColor:'#c8f563'}];
    // Z-score is context, not a co-star: quiet solid ghost, never dashed
    // (dashes on a high-frequency series read as scribble).
    if(showZ) ds.push({label:'Z-score',data:pick(zTrace.y),borderColor:'rgba(91,156,246,.3)',
      borderWidth:1,pointRadius:0,fill:false,yAxisID:'y2',order:2,tension:.25});

    // No background zone tints — low-alpha fills over black read as mud. The
    // 25/50/75 gridlines mark the boundaries and the badges above the chart
    // already name each zone, so the legend carries only the two series.
    let lg = dot('#c8f563','Composite Risk');
    if(showZ) lg += dot('rgba(91,156,246,.7)','Z-score');

    freshCanvas(container, lg);
    return mount(container,{type:'line',
      data:{labels,datasets:ds},
      options:{responsive:true,maintainAspectRatio:false,animation:{duration:600},
        interaction:{mode:'index',intersect:false},
        plugins:{legend:{display:false},tooltip:Object.assign({},TIP,{callbacks:{
          label:c=>' '+c.dataset.label+': '+(+c.parsed.y).toFixed(c.dataset.label==='Z-score'?2:1)+(c.dataset.label==='Z-score'?'':'%')}})},
        scales:{
          x:{grid:{display:false},ticks:Object.assign({maxTicksLimit:8,maxRotation:0},TICKS),border:{display:false}},
          y:{min:0,max:100,position:'right',border:{display:false},
             grid:{color:'rgba(255,255,255,.055)'},
             ticks:Object.assign({stepSize:25,callback:v=>v+'%'},TICKS)},
          y2:{display:showZ,position:'left',grid:{display:false},border:{display:false},
              ticks:Object.assign({maxTicksLimit:7},TICKS)}
        }}});
  }

  const HIJACK = {chart:drawEqm, cqmChart:drawCqm};
  function target(el){ return typeof el==='string' ? document.getElementById(el) : el; }
  function plot(orig, el, data, layout, cfg){
    walk(data,0); dressTraces(data);
    const node = target(el);
    const h = node && HIJACK[node.id];
    if(h && window.Chart){
      try{ h(node, data||[]); WOS_SOURCE[node.id]=data||[]; return Promise.resolve(node); }
      catch(e){ console.error('[aurora-chart] fallback to Plotly:', e); }
    }
    return orig(el, data, theme(layout), conf(cfg));
  }
  const np = Plotly.newPlot.bind(Plotly), re = Plotly.react.bind(Plotly);
  Plotly.newPlot = (el,data,layout,cfg)=>plot(np,el,data,layout,cfg);
  Plotly.react   = (el,data,layout,cfg)=>plot(re,el,data,layout,cfg);

  /* A chart built while its pane was hidden measured a zero box — Chart.js
     then pins inline width/height:0 on the canvas, and inline styles beat the
     CSS stretch. Clear them, re-measure, and rebuild from the stored series if
     it is still empty. */
  window.wosResizeCharts = function(){
    for(const id in WOS_CHARTS){
      const host = document.getElementById(id);
      // only touch charts whose pane is on screen — "fixing" a hidden one
      // would just re-pin it to a zero box
      if(!host || !host.clientHeight) continue;
      const ch = WOS_CHARTS[id];
      try{
        const cv = ch.canvas;
        if(cv && !cv.clientWidth){ cv.style.width=''; cv.style.height=''; }
        ch.resize();
        if(ch.canvas && !ch.canvas.clientWidth && WOS_SOURCE[id]){
          HIJACK[id](host, WOS_SOURCE[id]);      // last resort: rebuild
        }
      }catch(e){}
    }
  };
  addEventListener('resize', ()=>wosResizeCharts());
  /* Watch the chart hosts themselves: a hidden pane has a zero box, so the
     switch to visible shows up here as a resize — no dependence on which
     element happens to own the tab click. */
  if(window.ResizeObserver){
    const ro = new ResizeObserver(entries=>{
      for(const en of entries){
        const host = en.target, ch = WOS_CHARTS[host.id];
        if(ch && host.clientHeight && ch.canvas && !ch.canvas.clientWidth){
          setTimeout(wosResizeCharts, 0);
          break;
        }
      }
    });
    ['chart','cqmChart'].forEach(id=>{ const el=document.getElementById(id); if(el) ro.observe(el); });
  }
  /* Watchdog: ResizeObserver and rAF are both frame-driven, so a background or
     hidden tab pauses them — a chart built there would stay zero-sized until
     the next interaction. A cheap timer (two property reads) catches the
     "visible host, empty canvas" case in every environment. */
  setInterval(function(){
    for(const id in WOS_CHARTS){
      const host = document.getElementById(id), ch = WOS_CHARTS[id];
      if(host && ch && ch.canvas && host.clientHeight && !ch.canvas.clientWidth){
        wosResizeCharts();
        return;
      }
    }
  }, 500);
})();
"""


# ── page init ────────────────────────────────────────────────────────────────
_INIT_JS = r"""
/* WealthOS: auto-load the model on open (the Load button is hidden chrome) */
setTimeout(function(){ var b=document.getElementById('loadBtn'); if(b) b.click(); }, 80);
/* "Show legend" drives our HTML legend strip (the engine's Plotly relayout is
   skipped because the container holds a Chart.js canvas now). */
document.getElementById('legendToggle').addEventListener('change', function(e){
  var lg = document.querySelector('#chart .wosClegend');
  if(lg) lg.style.display = e.target.checked ? '' : 'none';
});
/* Fallback: if the curve pane is opened but its rAF-scheduled backtest didn't
   land (timing), run it once the model exists. */
document.getElementById('curveTabBtn').addEventListener('click', function(){
  setTimeout(function(){
    try{
      if(modelState && document.getElementById('cvPnl').textContent === '\u2014'){
        runCurveBacktest();
      }
    }catch(e){}
  }, 900);
});
"""


_SDCA_HTML = (_TEMPLATE
              + "<script>" + _WRAPPER_JS + "</script>"
              + "<script>" + ENGINE_JS + "</script>"
              + "<script>" + _INIT_JS + "</script>"
              + "\\n</body>\\n</html>")


def _render_sdca(auth: str = "", halt: dict | None = None) -> str:
    html = _SDCA_HTML
    html = html.replace("__THEME_HEAD__", _theme_head())
    html = html.replace("__NAV_PLACEHOLDER__", _nav_html("sdca", halt))
    return html

"""Liquid Glass — an Apple-style alternative theme for WealthOS.

Every page already renders against the shared design tokens and component
classes, so a second token set plus component overrides re-skins the whole
app: RSPS, Portfolio, SDCA, History, Strategies, the shell, and the login
page. Nothing in the pages changes.

Design language (Apple, 2025 "Liquid Glass"):
  · material over decoration — translucent layers with specular top edges and
    real blur, no neon glow, no gradient washes
  · content first — chrome recedes to grey; colour appears only where it means
    something (blue = interactive, green/red = money moving)
  · SF Pro typography, sentence case, tabular figures for anything numeric
  · squircle-ish radii (continuous curvature approximated by generous rounding)
  · spring motion — short, damped, physical; nothing pulses forever

Rules are prefixed `html.ui-liquid` so they outrank each page's own class
selectors regardless of stylesheet order, which lets the theme retune
page-level styling (neon glows, lime gradients) without touching the pages.
"""

__all__ = ['LIQUID_STYLE', 'LIQUID_JS']


LIQUID_STYLE = r"""
<style>
@import url('https://fonts.googleapis.com/css2?family=Inter:wght@400;500;600;700&display=swap');
/* SF Pro when the device has it (Apple hardware), Inter as the stand-in
   elsewhere — same proportions, same neutral voice. */
*,*::before,*::after{box-sizing:border-box;margin:0;padding:0}
:root{
  --bg:#000000;
  --bg-elev:#0b0b0d;
  --glass:rgba(28,28,30,.72);
  --glass2:rgba(44,44,46,.68);
  --glass3:rgba(58,58,60,.6);
  --border:rgba(255,255,255,.10);
  --border2:rgba(255,255,255,.18);
  --text:#f5f5f7;
  --muted:#98989d;
  --muted2:#636366;
  --accent:#0a84ff;            /* system blue  — interactive */
  --accent2:#64d2ff;           /* system cyan  — secondary   */
  --green:#30d158;             /* system green — gains       */
  --red:#ff453a;               /* system red   — losses      */
  --amber:#ff9f0a;
  --blue:#0a84ff;
  --purple:#bf5af2;
  --accent-dim:rgba(10,132,255,.16);
  --red-dim:rgba(255,69,58,.16);
  --blue-dim:rgba(10,132,255,.16);
  --amber-dim:rgba(255,159,10,.16);
  --purple-dim:rgba(191,90,242,.16);
  --surface:var(--glass);--surface2:rgba(255,255,255,.06);--surface3:rgba(255,255,255,.10);
  --grad:linear-gradient(180deg,#0a84ff 0%,#0a6fd8 100%);
  --font-mono:'SF Mono',ui-monospace,SFMono-Regular,Menlo,monospace;
  --font-display:-apple-system,BlinkMacSystemFont,'SF Pro Display','Inter',system-ui,sans-serif;
  --ease:cubic-bezier(.32,.72,0,1);          /* Apple's standard spring-ish */
  --r-lg:22px; --r-md:16px; --r-sm:11px;
}
html{scrollbar-color:rgba(255,255,255,.18) transparent;-webkit-text-size-adjust:100%}
body{background:var(--bg);color:var(--text);
  font-family:-apple-system,BlinkMacSystemFont,'SF Pro Text','Inter',system-ui,sans-serif;
  font-size:14px;line-height:1.5;min-height:100vh;overflow-x:hidden;
  -webkit-font-smoothing:antialiased;-moz-osx-font-smoothing:grayscale;
  font-variant-numeric:tabular-nums;letter-spacing:-.01em}
::selection{background:rgba(10,132,255,.35);color:#fff}
a{color:inherit;text-decoration:none}

/* ── Backdrop: a single deep wash, far quieter than aurora ───────────────── */
html.ui-liquid .wos-aurora{position:fixed;inset:0;z-index:-2;pointer-events:none;filter:none;
  background:
    radial-gradient(120% 80% at 50% -20%,rgba(10,132,255,.10),transparent 60%),
    radial-gradient(90% 60% at 100% 100%,rgba(100,210,255,.05),transparent 65%),
    #000}
html.ui-liquid .wos-grid{display:none}

/* ── Glass material ──────────────────────────────────────────────────────── */
html.ui-liquid .header{position:sticky;top:0;z-index:50;display:flex;align-items:center;
  justify-content:space-between;gap:12px;flex-wrap:wrap;padding:14px 24px;
  background:rgba(10,10,12,.62);
  backdrop-filter:blur(34px) saturate(180%);-webkit-backdrop-filter:blur(34px) saturate(180%);
  border-bottom:.5px solid rgba(255,255,255,.10)}
html.ui-liquid .logo{font-family:var(--font-display);font-size:17px;font-weight:600;
  letter-spacing:-.02em;color:var(--text)}
html.ui-liquid .logo span{background:none;-webkit-background-clip:initial;background-clip:initial;
  color:var(--muted);font-weight:400}

/* Segmented control — the iOS one, down to the sliding capsule */
html.ui-liquid .tab-nav{display:flex;gap:2px;padding:2px;border-radius:999px;
  background:rgba(118,118,128,.24);border:none;backdrop-filter:blur(20px)}
html.ui-liquid .tab-btn{font-family:var(--font-display);font-size:13px;font-weight:500;
  letter-spacing:-.01em;text-transform:none;padding:6px 14px;border-radius:999px;
  color:var(--muted);transition:color .3s var(--ease),background .3s var(--ease),
  transform .3s var(--ease);box-shadow:none;background:none}
html.ui-liquid .tab-btn:hover:not(.active){color:var(--text);transform:none;background:rgba(255,255,255,.06)}
html.ui-liquid .tab-btn.active{color:var(--text);font-weight:600;
  background:rgba(99,99,102,.62);
  box-shadow:0 3px 8px rgba(0,0,0,.34),0 0 0 .5px rgba(255,255,255,.14),
             inset 0 .5px 0 rgba(255,255,255,.28)}
html.ui-liquid .tab-btn.active:active{transform:scale(.96)}

html.ui-liquid .theme-switch{border:.5px solid var(--border);color:var(--muted);
  background:rgba(118,118,128,.20);width:30px;height:30px}
html.ui-liquid .theme-switch:hover{color:var(--accent);background:rgba(118,118,128,.30);transform:none}
html.ui-liquid .pulse-dot{width:7px;height:7px;background:var(--green);box-shadow:none}
html.ui-liquid .pulse-dot::after{border-color:rgba(48,209,88,.35);animation:liqPing 2.6s var(--ease) infinite}

/* ── Cards ───────────────────────────────────────────────────────────────── */
html.ui-liquid .main{padding:24px;max-width:1180px}
html.ui-liquid .panel,
html.ui-liquid .metric,
html.ui-liquid .card,
html.ui-liquid .chart-section,
html.ui-liquid .kelly-section,
html.ui-liquid .table-section,
html.ui-liquid .config-panel,
html.ui-liquid .backtestPanel,
html.ui-liquid .backtestMetric,
html.ui-liquid .curveEditorBox{
  background:var(--glass);border:.5px solid var(--border);border-radius:var(--r-lg);
  backdrop-filter:blur(28px) saturate(180%);-webkit-backdrop-filter:blur(28px) saturate(180%);
  box-shadow:0 1px 0 rgba(255,255,255,.09) inset, 0 12px 34px -14px rgba(0,0,0,.9);
  transition:transform .4s var(--ease),background .4s var(--ease),box-shadow .4s var(--ease)}
html.ui-liquid .panel::before,
html.ui-liquid .chart-section::before,
html.ui-liquid .card::before,
html.ui-liquid .table-section::before,
html.ui-liquid .kelly-section::before{background:none}   /* no accent hairline */
html.ui-liquid .panel:hover,
html.ui-liquid .chart-section:hover{border-color:var(--border);box-shadow:0 1px 0 rgba(255,255,255,.09) inset,0 12px 34px -14px rgba(0,0,0,.9)}
html.ui-liquid .metric{border-radius:var(--r-md);padding:16px 18px}
html.ui-liquid .metric:hover{transform:none;border-color:var(--border);
  background:var(--glass2);box-shadow:0 1px 0 rgba(255,255,255,.09) inset,0 14px 36px -14px rgba(0,0,0,.9)}
html.ui-liquid .panel-header{padding:16px 20px;border-bottom:.5px solid var(--border)}
html.ui-liquid .panel-title{font-family:var(--font-display);font-size:15px;font-weight:600;
  letter-spacing:-.01em;text-transform:none;color:var(--text)}

/* ── Type: labels in sentence case, numbers tabular ──────────────────────── */
html.ui-liquid .metric-label,
html.ui-liquid .hero-label,
html.ui-liquid .hero-stat-label,
html.ui-liquid .windowbar-label,
html.ui-liquid .flow-field label,
html.ui-liquid .card label,
html.ui-liquid .config-label,
html.ui-liquid .backtestMetric .k,
html.ui-liquid .vlabel{
  font-family:var(--font-display);font-size:12px;font-weight:400;letter-spacing:0;
  text-transform:none;color:var(--muted)}
html.ui-liquid .metric-value,
html.ui-liquid .hero-stat-val,
html.ui-liquid .strat-pct,
html.ui-liquid .eq-val,
html.ui-liquid .backtestMetric .v,
html.ui-liquid .kelly-val,
html.ui-liquid .lev-value{
  font-family:var(--font-display);font-weight:600;letter-spacing:-.02em;
  font-variant-numeric:tabular-nums}
html.ui-liquid .metric-value{font-size:24px}
html.ui-liquid .metric-sub{font-size:12px;color:var(--muted2)}
html.ui-liquid .pos{color:var(--green)}
html.ui-liquid .neg{color:var(--red)}

/* Large title, iOS style: solid, tight, no shimmer */
html.ui-liquid .hero{padding:26px 0 30px}
html.ui-liquid .hero::before{display:none}
html.ui-liquid .hero-value{font-family:var(--font-display);font-size:56px;font-weight:600;
  letter-spacing:-.035em;line-height:1.05;background:none;-webkit-background-clip:initial;
  background-clip:initial;color:var(--text);animation:none;font-variant-numeric:tabular-nums}
html.ui-liquid .hero-sub{gap:26px;margin-top:20px}
html.ui-liquid .hero-stat-val{font-size:19px}

/* ── Controls ────────────────────────────────────────────────────────────── */
html.ui-liquid .ctrl-group{background:rgba(118,118,128,.24);border:none;border-radius:999px;padding:2px}
html.ui-liquid .ctrl-btn{font-family:var(--font-display);font-size:13px;font-weight:500;
  letter-spacing:-.01em;padding:5px 13px;border-radius:999px;color:var(--muted);
  transition:all .3s var(--ease)}
html.ui-liquid .ctrl-btn.active{background:rgba(99,99,102,.62);color:var(--text);font-weight:600;
  box-shadow:0 3px 8px rgba(0,0,0,.34),0 0 0 .5px rgba(255,255,255,.14),
             inset 0 .5px 0 rgba(255,255,255,.28)}
html.ui-liquid .ctrl-btn:active{transform:scale(.95)}
html.ui-liquid .btn{font-family:var(--font-display);font-size:14px;font-weight:500;
  letter-spacing:-.01em;text-transform:none;padding:9px 18px;border-radius:999px;
  background:rgba(118,118,128,.24);border:none;color:var(--accent);
  transition:transform .25s var(--ease),background .25s var(--ease),filter .25s var(--ease)}
html.ui-liquid .btn:hover{background:rgba(118,118,128,.34);transform:none;box-shadow:none}
html.ui-liquid .btn:active{transform:scale(.96)}
html.ui-liquid .btn-accent,
html.ui-liquid .btn-approve{background:var(--accent);color:#fff;font-weight:600;
  border:none;box-shadow:0 6px 18px -8px rgba(10,132,255,.9)}
html.ui-liquid .btn-accent:hover,
html.ui-liquid .btn-approve:hover{background:#409cff;box-shadow:0 8px 22px -8px rgba(10,132,255,1);transform:none}
html.ui-liquid .btn-danger{background:rgba(255,69,58,.18);color:var(--red)}
html.ui-liquid .btn-danger:hover{background:rgba(255,69,58,.28)}
html.ui-liquid .btn-pause{background:rgba(255,159,10,.18);color:var(--amber)}
html.ui-liquid .btn-export{background:rgba(10,132,255,.18);color:var(--accent)}
html.ui-liquid input,html.ui-liquid .flow-input,html.ui-liquid .inp,
html.ui-liquid .config-input,html.ui-liquid .strat-pct-input{
  font-family:var(--font-display);font-size:15px;border-radius:var(--r-sm);
  background:rgba(118,118,128,.20);border:none;color:var(--text);padding:10px 13px;
  transition:background .25s var(--ease),box-shadow .25s var(--ease)}
html.ui-liquid input:focus,html.ui-liquid .flow-input:focus,html.ui-liquid .inp:focus,
html.ui-liquid .config-input:focus,html.ui-liquid .strat-pct-input:focus{
  background:rgba(118,118,128,.30);box-shadow:0 0 0 3.5px rgba(10,132,255,.35);border:none}
html.ui-liquid input[type=checkbox]{accent-color:var(--accent)}

/* ── Tables: grouped-list feel, hairline separators ──────────────────────── */
html.ui-liquid .flow-table th,html.ui-liquid .pos-table th,html.ui-liquid .sig-table th{
  font-family:var(--font-display);font-size:12px;font-weight:400;letter-spacing:0;
  text-transform:none;color:var(--muted);border-bottom:.5px solid var(--border);padding:12px 20px}
html.ui-liquid .flow-table td,html.ui-liquid .pos-table td,html.ui-liquid .sig-table td{
  font-size:14px;border-bottom:.5px solid rgba(255,255,255,.07);padding:14px 20px;
  font-variant-numeric:tabular-nums}
html.ui-liquid .flow-table tr:hover td,html.ui-liquid .pos-table tr:hover td,
html.ui-liquid .sig-table tr:hover td{background:rgba(255,255,255,.045)}
html.ui-liquid .flow-badge,html.ui-liquid .badge,html.ui-liquid .tag,
html.ui-liquid .strat-status,html.ui-liquid .pill,html.ui-liquid .mode-spot,
html.ui-liquid .mode-perp,html.ui-liquid .mode-perp-lev,html.ui-liquid .cqmBadge{
  font-family:var(--font-display);font-size:11px;font-weight:500;letter-spacing:0;
  text-transform:none;border-radius:999px;padding:3px 9px;box-shadow:none;animation:none}
html.ui-liquid .badge-ok,html.ui-liquid .status-active{
  background:rgba(48,209,88,.18);color:var(--green);border:none}
html.ui-liquid .badge-err{background:rgba(255,69,58,.18);color:var(--red);border:none;animation:none}
html.ui-liquid .badge-auto,html.ui-liquid .mode-perp{background:rgba(10,132,255,.18);color:var(--accent);border:none}
html.ui-liquid .badge-manual,html.ui-liquid .mode-perp-lev{background:rgba(255,159,10,.18);color:var(--amber);border:none}
html.ui-liquid .mode-spot{background:rgba(48,209,88,.18);color:var(--green);border:none}

/* ── Progress / bars ─────────────────────────────────────────────────────── */
html.ui-liquid .strat-bar-track,html.ui-liquid .alloc-bar-wrap,
html.ui-liquid .kelly-bar-wrap,html.ui-liquid .progressWrap{
  background:rgba(118,118,128,.24);border-radius:999px;overflow:hidden}
html.ui-liquid .strat-bar-fill,html.ui-liquid .alloc-bar,
html.ui-liquid .kelly-bar,html.ui-liquid .progressBar{
  background:var(--accent);box-shadow:none;border-radius:999px}
html.ui-liquid .strat-bar-fill::after{display:none}      /* no shimmer sweep */
html.ui-liquid .alloc-pct{color:var(--accent);font-family:var(--font-display);font-weight:600}
html.ui-liquid .legend-dot{box-shadow:none}

/* ── Banners: iOS alert material ─────────────────────────────────────────── */
html.ui-liquid .wos-halt,html.ui-liquid .halt-banner{
  background:rgba(255,69,58,.14);border:.5px solid rgba(255,69,58,.28);color:var(--red);
  border-radius:var(--r-md);box-shadow:none;animation:liqIn .5s var(--ease) backwards;
  font-family:var(--font-display);font-weight:500}
html.ui-liquid .pending-banner{background:rgba(255,159,10,.13);
  border:.5px solid rgba(255,159,10,.30);border-radius:var(--r-md);box-shadow:none;
  animation:liqIn .5s var(--ease) backwards}
html.ui-liquid .pending-banner::before{display:none}
html.ui-liquid .pending-label{font-family:var(--font-display);font-size:13px;font-weight:600;
  letter-spacing:0;text-transform:none;color:var(--amber)}
html.ui-liquid #wosUpd{background:rgba(28,28,30,.82);border:.5px solid var(--border);
  border-radius:var(--r-md);color:var(--text);box-shadow:0 18px 44px -16px rgba(0,0,0,.95);
  backdrop-filter:blur(30px) saturate(180%);animation:liqIn .5s var(--ease) backwards}
html.ui-liquid #wosUpd button{background:rgba(118,118,128,.28);border:none;color:var(--accent);
  border-radius:999px;font-family:var(--font-display);font-size:12px;font-weight:500;
  letter-spacing:0;text-transform:none;padding:5px 12px}
html.ui-liquid #wosEye{background:rgba(28,28,30,.8);border:.5px solid var(--border);
  box-shadow:0 10px 26px -10px rgba(0,0,0,.9);backdrop-filter:blur(24px) saturate(180%)}
html.ui-liquid #wosEye svg{color:var(--muted)}
html.ui-liquid html.wos-private #wosEye svg,html.ui-liquid #wosEye:hover svg{color:var(--accent)}

html.ui-liquid .footer{border-top:.5px solid var(--border);color:var(--muted2);font-size:12px;padding:18px 24px}
html.ui-liquid .empty,html.ui-liquid .no-pos{color:var(--muted);font-size:14px}
html.ui-liquid .windowbar-note,html.ui-liquid .small,html.ui-liquid .desc,
html.ui-liquid .intro,html.ui-liquid .strat-desc{color:var(--muted);font-size:13px}

/* ── Motion: short, damped, physical ─────────────────────────────────────── */
@keyframes liqIn{from{opacity:0;transform:translateY(-8px) scale(.98)}}
@keyframes liqRise{from{opacity:0;transform:translateY(14px)}}
@keyframes liqPing{0%{transform:scale(.6);opacity:.9}80%,100%{transform:scale(2);opacity:0}}
@media (prefers-reduced-motion: no-preference){
  html.ui-liquid .main>*{animation:liqRise .55s var(--ease) backwards}
  html.ui-liquid .main>*:nth-child(1){animation-delay:.02s}
  html.ui-liquid .main>*:nth-child(2){animation-delay:.06s}
  html.ui-liquid .main>*:nth-child(3){animation-delay:.10s}
  html.ui-liquid .main>*:nth-child(4){animation-delay:.14s}
  html.ui-liquid .main>*:nth-child(5){animation-delay:.18s}
  html.ui-liquid .main>*:nth-child(n+6){animation-delay:.22s}
}
@media (prefers-reduced-motion: reduce){
  *,*::before,*::after{animation-duration:.01ms !important;animation-iteration-count:1 !important;
    transition-duration:.01ms !important}
}

/* privacy blur (same contract as aurora, scaled to this type) */
html.wos-private #heroValue,html.wos-private #heroPnl,html.wos-private #heroDeposited,
html.wos-private #mValue,html.wos-private #mDeposited,html.wos-private #mPnl,
html.wos-private #accountValue,html.wos-private #totalPnl,
html.wos-private #allTimePnl,html.wos-private #allTimePnlSub,html.wos-private #flowSummary,
html.wos-private .flow-table td:nth-child(3),html.wos-private .flow-table td:nth-child(4),
html.wos-private .pos-table td:nth-child(3),html.wos-private .pos-table td:nth-child(5),
html.wos-private .pos-table td:nth-child(6),
html.wos-private .strat-meta span:last-child,html.wos-private .eq-val,
html.wos-private .wos-money{filter:blur(9px);user-select:none;pointer-events:none}
html.wos-private #heroValue{filter:blur(26px)}
html.wos-private #mValue,html.wos-private #mDeposited,html.wos-private #mPnl,
html.wos-private #accountValue,html.wos-private #totalPnl,
html.wos-private #allTimePnl,html.wos-private .eq-val{filter:blur(13px)}

::-webkit-scrollbar{width:6px;height:6px}
::-webkit-scrollbar-thumb{background:rgba(255,255,255,.20);border-radius:3px}
::-webkit-scrollbar-thumb:hover{background:rgba(255,255,255,.32)}

/* ── Mobile ──────────────────────────────────────────────────────────────── */
@media(max-width:700px){
  html.ui-liquid .header{padding:11px 16px;gap:10px}
  html.ui-liquid .main{padding:18px 16px}
  html.ui-liquid .tab-nav{overflow-x:auto;-webkit-overflow-scrolling:touch;scrollbar-width:none;
    max-width:100%;flex-wrap:nowrap}
  html.ui-liquid .tab-nav::-webkit-scrollbar{display:none}
  html.ui-liquid .tab-btn{flex-shrink:0}
  html.ui-liquid .hero-value{font-size:40px}
  html.ui-liquid .metric-value{font-size:21px}
  html.ui-liquid .flow-table td,html.ui-liquid .pos-table td{padding:12px 16px}
  html.ui-liquid #wosEye{right:14px;bottom:14px;width:46px;height:46px}
}
@media(max-width:480px){
  html.ui-liquid .hero-value{font-size:34px}
}
</style>
<script>
/* Mark the document before first paint so the prefixed rules apply. */
document.documentElement.classList.add('ui-liquid');
</script>
"""


LIQUID_JS = r"""
<script>
/* Charts are drawn by the pages with the aurora palette baked in. Rather than
   edit every page, translate colours at the Chart.js/Plotly boundary — the
   same trick the SDCA tab uses to theme its engine. */
(function(){
  const MAP = {
    '#c8f563':'#0a84ff', '#7ef5d0':'#64d2ff', '#f4f1ea':'#f5f5f7', '#e9e4d8':'#f5f5f7',
    '#5b9cf6':'#0a84ff', '#f0b445':'#ff9f0a', '#ff5c5c':'#ff453a', '#54504a':'#8e8e93',
    '#f7931a':'#ff9f0a', '#627eea':'#5e5ce6', '#c084fc':'#bf5af2', '#22c55e':'#30d158',
    'rgba(200,245,99,0.06)':'rgba(10,132,255,.10)','rgba(200,245,99,.06)':'rgba(10,132,255,.10)',
    'rgba(200,245,99,.12)':'rgba(10,132,255,.16)','rgba(200,245,99,.16)':'rgba(10,132,255,.20)',
    'rgba(255,92,92,0.06)':'rgba(255,69,58,.10)','rgba(255,92,92,.06)':'rgba(255,69,58,.10)',
    'rgba(255,92,92,.07)':'rgba(255,69,58,.10)','rgba(255,92,92,.10)':'rgba(255,69,58,.14)',
    'rgba(233,228,216,.55)':'rgba(245,245,247,.5)','rgba(233,228,216,.8)':'rgba(245,245,247,.75)',
    'rgba(91,156,246,.8)':'rgba(10,132,255,.85)','rgba(255,92,92,.8)':'rgba(255,69,58,.85)',
    'rgba(91,156,246,.3)':'rgba(10,132,255,.35)','rgba(91,156,246,.35)':'rgba(10,132,255,.4)',
    'rgba(91,156,246,.65)':'rgba(10,132,255,.7)','rgba(91,156,246,.7)':'rgba(10,132,255,.75)',
    'rgba(126,245,208,.28)':'rgba(100,210,255,.30)','rgba(126,245,208,.40)':'rgba(100,210,255,.38)',
    'rgba(200,245,99,.38)':'rgba(10,132,255,.34)','rgba(200,245,99,.28)':'rgba(10,132,255,.26)',
    'rgba(245,166,35,.36)':'rgba(255,159,10,.34)','rgba(255,138,74,.40)':'rgba(255,105,97,.36)',
    'rgba(255,92,92,.44)':'rgba(255,69,58,.42)','rgba(91,156,246,.46)':'rgba(94,92,230,.42)',
    'rgba(255,255,255,.04)':'rgba(255,255,255,.06)','rgba(255,255,255,.055)':'rgba(255,255,255,.07)',
    '#14171a':'#1c1c1e', '#2c3136':'rgba(255,255,255,.14)'
  };
  const FONT = "-apple-system,BlinkMacSystemFont,'SF Pro Text',Inter,system-ui,sans-serif";
  const fix = v => (typeof v === 'string' && MAP[v]) ? MAP[v] : v;
  function walk(o, d){
    if(!o || typeof o !== 'object' || d > 9) return;
    if(Array.isArray(o)){ o.forEach(x => walk(x, d+1)); return; }
    for(const k of Object.keys(o)){
      const v = o[k], key = k.toLowerCase();
      if(typeof v === 'string' && (key.includes('color') || key === 'fill' || key === 'stroke')) o[k] = fix(v);
      else if(Array.isArray(v) && key.includes('color')) o[k] = v.map(fix);
      else if(v && typeof v === 'object'){
        if(key === 'font' && typeof v.family === 'string') v.family = FONT;
        walk(v, d+1);
      }
    }
  }
  function patchChart(){
    if(!window.Chart || window.Chart.__liquid) return;
    const Orig = window.Chart;
    const Wrapped = function(ctx, cfg){
      try{
        walk(cfg, 0);
        const sc = (cfg.options = cfg.options || {}).scales || {};
        for(const k of Object.keys(sc)){
          const ax = sc[k]; if(!ax) continue;
          ax.ticks = Object.assign({}, ax.ticks, {color:'#8e8e93',
            font:Object.assign({}, (ax.ticks||{}).font, {family:FONT, size:11})});
          if(ax.grid) ax.grid = Object.assign({}, ax.grid, {color:'rgba(255,255,255,.07)'});
        }
      }catch(e){}
      return new Orig(ctx, cfg);
    };
    Wrapped.prototype = Orig.prototype;
    Object.setPrototypeOf(Wrapped, Orig);
    Wrapped.__liquid = true;
    window.Chart = Wrapped;
    if(Orig.defaults){
      Orig.defaults.font.family = FONT;
      Orig.defaults.color = '#8e8e93';
    }
  }
  function patchPlotly(){
    if(!window.Plotly || window.Plotly.__liquid) return;
    const np = Plotly.newPlot.bind(Plotly), re = Plotly.react.bind(Plotly);
    const lay = l => { l = l || {}; walk(l, 0);
      l.font = Object.assign({}, l.font, {family:FONT, color:'#8e8e93'});
      l.paper_bgcolor = 'rgba(0,0,0,0)'; l.plot_bgcolor = 'rgba(0,0,0,0)';
      return l; };
    Plotly.newPlot = (el,d,l,c)=>{ walk(d,0); return np(el,d,lay(l),c); };
    Plotly.react   = (el,d,l,c)=>{ walk(d,0); return re(el,d,lay(l),c); };
    Plotly.__liquid = true;
  }
  patchChart(); patchPlotly();
  document.addEventListener('DOMContentLoaded', ()=>{ patchChart(); patchPlotly(); });
})();
</script>
"""

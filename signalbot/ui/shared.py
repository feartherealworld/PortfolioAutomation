"""Shared dashboard UI helpers (escaping, message page shell, unified nav)
and the WealthOS "aurora glass" design system: every tab injects _theme_head()
(design tokens + glass components + motion) via __THEME_HEAD__ and gets the
animated backdrop + nav from _nav_html() via __NAV_PLACEHOLDER__."""
from signalbot.config import *

__all__ = ['_html_escape', '_page', '_nav_html', '_theme_head']


# ── Design system ─────────────────────────────────────────────────────────────
# Aurora glass: near-black canvas with slow-drifting aurora light, faint grid,
# translucent blurred panels, one signature lime→mint gradient for anything
# alive. Motion: panels cascade up on load, numbers count up ([data-count]),
# active nav is a glowing pill. All motion sits behind prefers-reduced-motion.

_THEME_HEAD = r"""
<style>
  @import url('https://fonts.googleapis.com/css2?family=DM+Mono:wght@400;500&family=Syne:wght@400;600;700;800&display=swap');
  *,*::before,*::after{box-sizing:border-box;margin:0;padding:0}
  :root{
    --bg:#050607;
    --glass:rgba(17,20,21,.60);--glass2:rgba(28,32,30,.55);--glass3:rgba(40,45,42,.5);
    --border:rgba(255,255,255,.07);--border2:rgba(255,255,255,.14);
    --text:#f2efe9;--muted:#8a877e;--muted2:#4a4844;
    --accent:#c8f563;--accent2:#7ef5d0;
    --accent-dim:rgba(200,245,99,.12);
    --red:#ff5c5c;--red-dim:rgba(255,92,92,.12);
    --blue:#5b9cf6;--blue-dim:rgba(91,156,246,.12);
    --amber:#f5a623;--amber-dim:rgba(245,166,35,.12);
    --purple:#c084fc;--purple-dim:rgba(192,132,252,.12);
    /* legacy aliases still referenced by page styles */
    --surface:var(--glass);--surface2:rgba(255,255,255,.05);--surface3:rgba(255,255,255,.08);
    --grad:linear-gradient(92deg,#eef7d8 0%,var(--accent) 48%,var(--accent2) 100%);
    --font-mono:'DM Mono',monospace;--font-display:'Syne',sans-serif;
    --ease:cubic-bezier(.22,1,.36,1);
  }
  html{scrollbar-color:rgba(255,255,255,.16) transparent}
  body{background:var(--bg);color:var(--text);font-family:var(--font-mono);font-size:13px;line-height:1.6;min-height:100vh;overflow-x:hidden}
  ::selection{background:rgba(200,245,99,.25);color:#fff}
  a{color:inherit}

  /* ── Living backdrop ── */
  .wos-aurora{position:fixed;inset:-22%;z-index:-2;pointer-events:none;filter:blur(50px);
    background:
      radial-gradient(36% 30% at 16% 20%,rgba(200,245,99,.09),transparent 62%),
      radial-gradient(30% 26% at 84% 10%,rgba(126,245,208,.07),transparent 60%),
      radial-gradient(40% 34% at 72% 88%,rgba(91,156,246,.065),transparent 65%),
      radial-gradient(28% 24% at 6% 82%,rgba(192,132,252,.05),transparent 60%);
  }
  .wos-grid{position:fixed;inset:0;z-index:-1;pointer-events:none;
    background-image:linear-gradient(rgba(255,255,255,.024) 1px,transparent 1px),
                     linear-gradient(90deg,rgba(255,255,255,.024) 1px,transparent 1px);
    background-size:44px 44px;
    -webkit-mask-image:radial-gradient(80% 62% at 50% 34%,black,transparent 88%);
            mask-image:radial-gradient(80% 62% at 50% 34%,black,transparent 88%);
  }

  /* ── Header / nav ── */
  .header{position:sticky;top:0;z-index:50;display:flex;align-items:center;justify-content:space-between;
    gap:10px;flex-wrap:wrap;padding:13px 22px;
    background:rgba(5,6,7,.6);backdrop-filter:blur(18px) saturate(1.2);-webkit-backdrop-filter:blur(18px) saturate(1.2);
    border-bottom:1px solid var(--border)}
  .header-left{display:flex;align-items:center;gap:14px;min-width:0}
  .logo{font-family:var(--font-display);font-size:16px;font-weight:800;letter-spacing:-.02em;white-space:nowrap}
  .logo span{background:var(--grad);-webkit-background-clip:text;background-clip:text;color:transparent}
  .tab-nav{display:flex;gap:4px;background:rgba(255,255,255,.045);border:1px solid var(--border);border-radius:999px;padding:3px}
  .tab-btn{position:relative;font-size:11px;font-family:var(--font-mono);letter-spacing:.07em;text-transform:uppercase;
    padding:6px 14px;border-radius:999px;cursor:pointer;color:var(--muted);border:none;background:none;
    transition:color .25s var(--ease),transform .25s var(--ease);white-space:nowrap;text-decoration:none;display:inline-block}
  .tab-btn:hover:not(.active){color:var(--text);transform:translateY(-1px)}
  .tab-btn.active{color:#10130a;background:var(--grad);font-weight:500;
    box-shadow:0 0 20px rgba(200,245,99,.35),0 2px 10px rgba(0,0,0,.45)}
  .pulse-dot{position:relative;width:9px;height:9px;border-radius:50%;background:var(--accent);
    box-shadow:0 0 12px rgba(200,245,99,.9);flex-shrink:0}
  .pulse-dot::after{content:'';position:absolute;inset:-5px;border-radius:50%;
    border:1px solid rgba(200,245,99,.55);animation:wosPing 2.4s cubic-bezier(0,0,.2,1) infinite}

  /* ── Layout / glass panels ── */
  .main{padding:20px 22px;max-width:1200px;margin:0 auto}
  .panel{position:relative;background:var(--glass);border:1px solid var(--border);border-radius:16px;margin-bottom:18px;overflow:hidden;
    backdrop-filter:blur(16px) saturate(1.15);-webkit-backdrop-filter:blur(16px) saturate(1.15);
    box-shadow:0 20px 48px -20px rgba(0,0,0,.65),inset 0 1px 0 rgba(255,255,255,.05);
    transition:border-color .35s,box-shadow .35s}
  .panel::before{content:'';position:absolute;inset:0 0 auto 0;height:1px;pointer-events:none;
    background:linear-gradient(90deg,transparent,rgba(255,255,255,.14) 30%,rgba(200,245,99,.18) 50%,rgba(255,255,255,.14) 70%,transparent)}
  .panel:hover{border-color:var(--border2);box-shadow:0 26px 60px -22px rgba(0,0,0,.75),inset 0 1px 0 rgba(255,255,255,.07)}
  .panel-header{display:flex;align-items:center;justify-content:space-between;padding:13px 16px;border-bottom:1px solid var(--border);flex-wrap:wrap;gap:8px}
  .panel-title{font-size:10px;letter-spacing:.14em;text-transform:uppercase;color:var(--muted);font-weight:500}
  .empty{padding:44px 20px;text-align:center;color:var(--muted);font-size:12px}

  /* ── Controls ── */
  .ctrl-group{display:flex;gap:2px;background:rgba(0,0,0,.35);border:1px solid var(--border);border-radius:999px;padding:2px}
  .ctrl-btn{font-size:11px;font-family:var(--font-mono);padding:4px 11px;border-radius:999px;cursor:pointer;color:var(--muted);
    border:none;background:none;transition:all .25s var(--ease);letter-spacing:.04em;white-space:nowrap}
  .ctrl-btn.active{background:rgba(200,245,99,.16);color:var(--accent);box-shadow:inset 0 0 0 1px rgba(200,245,99,.3)}
  .ctrl-btn:hover:not(.active){color:var(--text)}
  .btn{font-family:var(--font-mono);font-size:11px;letter-spacing:.06em;text-transform:uppercase;padding:8px 15px;border-radius:9px;
    cursor:pointer;border:1px solid var(--border2);background:rgba(255,255,255,.04);color:var(--text);
    transition:all .25s var(--ease);text-decoration:none;display:inline-flex;align-items:center;gap:6px}
  .btn:hover{background:rgba(255,255,255,.08);transform:translateY(-1px);box-shadow:0 6px 18px -6px rgba(0,0,0,.6)}
  .btn-accent{background:var(--grad);border-color:transparent;color:#10130a;font-weight:500;
    box-shadow:0 0 18px rgba(200,245,99,.25)}
  .btn-accent:hover{background:var(--grad);box-shadow:0 0 26px rgba(200,245,99,.45);transform:translateY(-1px)}
  .pos{color:var(--accent)}.neg{color:var(--red)}

  /* ── Kill-switch banner ── */
  .wos-halt{display:flex;align-items:center;gap:10px;flex-wrap:wrap;
    background:rgba(255,92,92,.09);border:1px solid rgba(255,92,92,.4);color:var(--red);
    border-radius:13px;padding:12px 16px;margin-bottom:16px;font-size:12px;
    backdrop-filter:blur(12px);-webkit-backdrop-filter:blur(12px);
    box-shadow:0 0 34px -8px rgba(255,92,92,.3);
    animation:wosHaltIn .6s var(--ease) backwards,wosHaltPulse 3.2s ease-in-out .7s infinite}
  .wos-halt a{color:var(--red)}

  .footer{padding:16px 22px;border-top:1px solid var(--border);display:flex;justify-content:space-between;
    font-size:11px;color:var(--muted);flex-wrap:wrap;gap:6px}
  ::-webkit-scrollbar{width:5px;height:5px}
  ::-webkit-scrollbar-thumb{background:rgba(255,255,255,.14);border-radius:3px}
  ::-webkit-scrollbar-thumb:hover{background:rgba(200,245,99,.35)}

  /* ── Motion ── */
  @keyframes wosPing{0%{transform:scale(.55);opacity:1}80%,100%{transform:scale(2.3);opacity:0}}
  @keyframes wosRise{from{opacity:0;transform:translateY(26px) scale(.985)}to{opacity:1;transform:none}}
  @keyframes wosHaltIn{from{opacity:0;transform:translateY(-14px)}}
  @keyframes wosHaltPulse{50%{box-shadow:0 0 46px -6px rgba(255,92,92,.45)}}
  @keyframes wosShimmer{0%{background-position:130% 0}100%{background-position:-130% 0}}
  @keyframes wosBreath{0%,100%{opacity:.5;transform:scale(1)}50%{opacity:.9;transform:scale(1.12)}}
  @media (prefers-reduced-motion: no-preference){
    .header{animation:wosHaltIn .5s var(--ease) backwards}
    .main>*{animation:wosRise .75s var(--ease) backwards}
    .main>*:nth-child(1){animation-delay:.06s}.main>*:nth-child(2){animation-delay:.13s}
    .main>*:nth-child(3){animation-delay:.20s}.main>*:nth-child(4){animation-delay:.27s}
    .main>*:nth-child(5){animation-delay:.34s}.main>*:nth-child(6){animation-delay:.41s}
    .main>*:nth-child(n+7){animation-delay:.48s}
  }
  @media (prefers-reduced-motion: reduce){
    *,*::before,*::after{animation-duration:.01ms !important;animation-iteration-count:1 !important;transition-duration:.01ms !important}
  }

  /* ── Privacy mode: blur every absolute balance, keep curves/percents ── */
  html.wos-private #heroValue, html.wos-private #heroPnl, html.wos-private #heroDeposited,
  html.wos-private #mValue, html.wos-private #mDeposited, html.wos-private #mPnl,
  html.wos-private #accountValue, html.wos-private #totalPnl,
  html.wos-private #allTimePnl, html.wos-private #allTimePnlSub,
  html.wos-private #flowSummary,
  html.wos-private .flow-table td:nth-child(3), html.wos-private .flow-table td:nth-child(4),
  html.wos-private .pos-table td:nth-child(3), html.wos-private .pos-table td:nth-child(5),
  html.wos-private .pos-table td:nth-child(6),
  html.wos-private .strat-meta span:last-child,
  html.wos-private .eq-val,
  html.wos-private .wos-money{
    filter:blur(9px);user-select:none;pointer-events:none}
  /* blur must scale with font size — 9px on the 62px hero was readable */
  html.wos-private #heroValue{filter:blur(30px)}
  html.wos-private #heroPnl, html.wos-private #heroDeposited{filter:blur(12px)}
  html.wos-private #mValue, html.wos-private #mDeposited, html.wos-private #mPnl,
  html.wos-private #accountValue, html.wos-private #totalPnl,
  html.wos-private #allTimePnl, html.wos-private .eq-val{filter:blur(14px)}
  #wosUpd{position:fixed;top:14px;left:50%;transform:translateX(-50%);z-index:95;
    display:flex;align-items:center;gap:12px;flex-wrap:wrap;max-width:min(680px,94vw);
    background:rgba(245,166,35,.1);border:1px solid rgba(245,166,35,.5);border-radius:12px;
    padding:10px 16px;font-size:12px;color:var(--amber);
    backdrop-filter:blur(14px);box-shadow:0 14px 40px -12px rgba(0,0,0,.8),0 0 26px -8px rgba(245,166,35,.4);
    animation:wosHaltIn .5s var(--ease) backwards}
  #wosUpd .msg{color:var(--muted);font-size:11px}
  #wosUpd button{background:none;border:1px solid rgba(245,166,35,.5);color:var(--amber);
    font-family:var(--font-mono);font-size:10px;letter-spacing:.08em;text-transform:uppercase;
    padding:4px 11px;border-radius:999px;cursor:pointer;transition:all .2s}
  #wosUpd button:hover{background:rgba(245,166,35,.15)}
  #wosEye{position:fixed;right:16px;bottom:16px;z-index:90;width:40px;height:40px;border-radius:50%;
    display:flex;align-items:center;justify-content:center;cursor:pointer;font-size:17px;
    background:var(--glass);border:1px solid var(--border2);backdrop-filter:blur(12px);
    box-shadow:0 10px 26px -10px rgba(0,0,0,.7);transition:all .25s var(--ease);user-select:none}
  #wosEye:hover{border-color:rgba(200,245,99,.45);transform:translateY(-2px)}
  #wosEye svg{width:18px;height:18px;color:var(--muted);transition:color .25s}
  #wosEye:hover svg{color:var(--text)}
  html.wos-private #wosEye{border-color:rgba(245,166,35,.55);box-shadow:0 0 18px -6px rgba(245,166,35,.6)}
  html.wos-private #wosEye svg{color:var(--amber)}
</style>
<script>
/* Privacy mode boots BEFORE first paint so real values never flash. */
if(localStorage.getItem('wos_private')==='1')document.documentElement.classList.add('wos-private');
</script>
<script>
/* Count-up for [data-count] elements: parses the freshly rendered text
   (e.g. "$16,294.09", "+11.0%", "1.67") and animates the numeric part from 0.
   Runs once per element per page load; snaps to exact text at the end. */
window.wosCountUp=function(root){
  if(matchMedia('(prefers-reduced-motion: reduce)').matches)return;
  (root||document).querySelectorAll('[data-count]').forEach(el=>{
    if(el.dataset.counted)return;
    const txt=el.textContent;
    const m=txt.match(/^([^0-9\-]*)(-?[\d,]+(?:\.\d+)?)(.*)$/s);
    if(!m)return;
    const target=parseFloat(m[2].replace(/,/g,''));
    if(!isFinite(target))return;
    el.dataset.counted='1';
    const pre=m[1],suf=m[3];
    const dec=(m[2].split('.')[1]||'').length;
    const comma=m[2].includes(',');
    const t0=performance.now(),dur=1100;
    (function frame(t){
      const p=Math.min(1,(t-t0)/dur),e=1-Math.pow(1-p,4);
      let s=(target*e).toFixed(dec);
      if(comma)s=parseFloat(s).toLocaleString('en-US',{minimumFractionDigits:dec,maximumFractionDigits:dec});
      el.textContent=pre+s+suf;
      if(p<1)requestAnimationFrame(frame);else el.textContent=txt;
    })(t0);
  });
};

/* ── Privacy mode ────────────────────────────────────────────────────────────
   Blur handled by CSS (html.wos-private). Charts draw values on canvas, so a
   thin wrapper around Chart masks y-axis ticks and tooltip labels while
   private — the curve itself stays fully visible. State lives in
   localStorage per device and syncs live across shell frames via storage
   events. */
(function(){
  const priv=()=>document.documentElement.classList.contains('wos-private');
  const MASK='•••';

  if(window.Chart){
    const O=window.Chart;
    function wrapTicks(sc){
      if(!sc)return;
      sc.ticks=sc.ticks||{};
      const orig=sc.ticks.callback;
      sc.ticks.callback=function(v,i,t){
        if(priv())return MASK;
        return orig?orig.call(this,v,i,t):this.getLabelForValue?this.getLabelForValue(v):v;
      };
    }
    function wrapTip(cfg){
      const p=((cfg.options=cfg.options||{}).plugins=cfg.options.plugins||{});
      const tt=(p.tooltip=p.tooltip||{});
      const cb=(tt.callbacks=tt.callbacks||{});
      const orig=cb.label;
      cb.label=function(ctx){
        if(priv())return ' '+MASK;
        return orig?orig.call(this,ctx):undefined;
      };
    }
    const W=function(ctx,cfg){
      try{
        const sc=(cfg.options&&cfg.options.scales)||{};
        Object.keys(sc).forEach(k=>{if(k[0]==='y')wrapTicks(sc[k])});
        wrapTip(cfg);
      }catch(e){}
      return new O(ctx,cfg);
    };
    W.prototype=O.prototype;
    Object.setPrototypeOf(W,O);          // statics: getChart, register, defaults…
    window.Chart=W;
  }

  function refreshCharts(){
    try{
      document.querySelectorAll('canvas').forEach(c=>{
        const ch=window.Chart&&window.Chart.getChart&&window.Chart.getChart(c);
        if(ch)ch.update('none');
      });
    }catch(e){}
  }
  const EYE_OPEN='<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.7" stroke-linecap="round" stroke-linejoin="round"><path d="M1 12s4-7.5 11-7.5S23 12 23 12s-4 7.5-11 7.5S1 12 1 12z"/><circle cx="12" cy="12" r="3"/></svg>';
  const EYE_OFF='<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.7" stroke-linecap="round" stroke-linejoin="round"><path d="M17.9 17.9A10.9 10.9 0 0 1 12 19.5C5 19.5 1 12 1 12a20.4 20.4 0 0 1 5.1-5.9M9.9 4.7A10 10 0 0 1 12 4.5c7 0 11 7.5 11 7.5a20.5 20.5 0 0 1-3.2 4.2"/><path d="M9.9 9.9a3 3 0 1 0 4.2 4.2"/><line x1="2" y1="2" x2="22" y2="22"/></svg>';
  window.wosSetPrivate=function(on,store=true){
    document.documentElement.classList.toggle('wos-private',on);
    if(store)try{localStorage.setItem('wos_private',on?'1':'0')}catch(e){}
    const eye=document.getElementById('wosEye');
    if(eye){eye.innerHTML=on?EYE_OFF:EYE_OPEN;eye.title=(on?'Balances hidden':'Balances visible')+' — click to toggle'}
    refreshCharts();
  };
  addEventListener('storage',e=>{           // other tabs/frames toggled it
    if(e.key==='wos_private')wosSetPrivate(e.newValue==='1',false);
  });
  addEventListener('DOMContentLoaded',()=>{
    const eye=document.createElement('div');
    eye.id='wosEye';
    eye.addEventListener('click',()=>wosSetPrivate(!priv()));
    document.body.appendChild(eye);
    wosSetPrivate(priv(),false);
  });
})();

/* ── Update banner ───────────────────────────────────────────────────────────
   Top windows only (shell / standalone pages — not each shell frame). Asks
   the server whether GitHub main is ahead of the deployed commit; Ignore is
   stored server-side so it applies on every device. */
(function(){
  if(window.top!==window.self)return;
  addEventListener('DOMContentLoaded',async()=>{
    let d;
    try{
      const r=await fetch('?action=update_check');
      d=await r.json();
    }catch(e){return}
    if(!d||!d.behind||d.ignored)return;
    const b=document.createElement('div');
    b.id='wosUpd';
    b.innerHTML='<span>⬆ <b>Update available</b> — '+d.behind+' new commit'+(d.behind>1?'s':'')+'</span>'+
      '<span class="msg">'+((d.messages&&d.messages[0])||'').replace(/</g,'&lt;').slice(0,70)+'</span>'+
      '<button id="wosUpdHow">How to update</button>'+
      '<button id="wosUpdIgn">Ignore</button>';
    document.body.appendChild(b);
    document.getElementById('wosUpdHow').onclick=()=>alert(
      'On any computer with the repo + Modal access:\n\n'+
      '  double-click  update.py\n\n'+
      '(it pulls the latest main and redeploys — one click, ~30s)\n\n'+
      'Or manually:\n  git pull\n  modal deploy modal_signal_bot.py\n\n'+
      'Deployed: '+d.current+(d.built?'  ('+d.built+')':'')+'\nLatest:   '+d.latest);
    document.getElementById('wosUpdIgn').onclick=async()=>{
      b.remove();
      try{await fetch('?action=update_ignore&points='+encodeURIComponent(JSON.stringify({sha:d.latest})))}catch(e){}
    };
  });
})();
</script>
"""


def _theme_head() -> str:
    """Shared <head> payload: fonts, design tokens, glass components, motion."""
    return _THEME_HEAD


def _html_escape(s: str) -> str:
    """Escape HTML special characters to prevent reflected XSS."""
    return (s.replace("&", "&amp;").replace("<", "&lt;")
             .replace(">", "&gt;").replace('"', "&quot;"))

# One nav to rule all four tabs. Each tab's HTML carries a __NAV_PLACEHOLDER__
# that its renderer swaps for this. Styling relies on the .header/.tab-nav/.logo
# rules each tab already defines; the halt banner is self-styled (inline) so it
# renders identically everywhere.
_NAV_TABS = [
    ("portfolio",  "Portfolio",  "?action=portfolio"),
    ("rsps",       "RSPS",       "?"),
    ("history",    "History",    "?action=history"),
    ("strategies", "Strategies", "?action=strategies"),
    ("instant",    "⚡ Instant",  "?action=app"),   # app shell: kept-alive tabs
]


def _nav_html(active: str, halt: dict | None = None, main_open: bool = True,
              left_extra: str = "", right_extra: str = "") -> str:
    """Unified header for all tabs.

    active     : which tab gets the .active class
    halt       : kill-switch state {halted, reason}; renders a banner when
                 halted (pass None on the RSPS tab — it has its own banner
                 with a resume button)
    main_open  : also emit the `<div class="main">` opener so the banner sits
                 inside the page column (RSPS passes False and keeps its own)
    left_extra : markup before the logo (RSPS pulse-dot)
    right_extra: markup after .header-left (RSPS badges)
    """
    tabs = "\n      ".join(
        f'<a class="tab-btn{" active" if key == active else ""}" '
        f'id="nav-{key}" href="{href if key != active else "#"}">{label}</a>'
        for key, label, href in _NAV_TABS
    )
    html = f"""<div class="wos-aurora"></div>
<div class="wos-grid"></div>
<div class="header">
  <div class="header-left">
    {left_extra}<div class="logo">wealth<span>os</span></div>
    <div class="tab-nav">
      {tabs}
    </div>
  </div>
  {right_extra}
</div>"""
    if main_open:
        html += '\n<div class="main">'
        if halt and halt.get("halted"):
            reason = _html_escape(str(halt.get("reason", "")))
            html += f"""
  <div class="wos-halt">
    <span>⏸ <b>BOT PAUSED</b> — no new orders; positions kept.</span>
    <span style="opacity:.75">{reason}</span>
    <a href="?" style="margin-left:auto;text-decoration:underline">Manage on RSPS tab</a>
  </div>"""
    return html


def _page(title: str, body: str) -> str:
    t = _html_escape(title)
    b = _html_escape(body)
    return f"""<!DOCTYPE html>
<html>
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>{t}</title>
  {_THEME_HEAD}
  <style>
    body{{display:flex;align-items:center;justify-content:center;padding:28px}}
    .card{{position:relative;background:var(--glass);border:1px solid var(--border);border-radius:18px;
          backdrop-filter:blur(18px);-webkit-backdrop-filter:blur(18px);
          box-shadow:0 24px 60px -20px rgba(0,0,0,.7),inset 0 1px 0 rgba(255,255,255,.06);
          padding:34px 36px;max-width:560px;width:100%;
          animation:wosRise .7s var(--ease) backwards}}
    h2{{font-family:var(--font-display);font-size:22px;font-weight:800;margin-bottom:10px;
        background:var(--grad);-webkit-background-clip:text;background-clip:text;color:transparent}}
    p{{color:var(--muted);font-size:13px;margin-bottom:22px;white-space:pre-wrap}}
  </style>
</head>
<body>
  <div class="wos-aurora"></div>
  <div class="wos-grid"></div>
  <div class="card">
    <h2>{t}</h2>
    <p>{b}</p>
    <a class="btn" href="?">Back to dashboard</a>
  </div>
</body>
</html>"""

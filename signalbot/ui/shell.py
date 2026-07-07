"""Instant app shell — classic tabs without page reloads.

Served at ?action=app. Hosts the four classic pages in same-origin frames
that are loaded once and kept alive, so switching tabs is instant (charts
stay rendered, JS keeps running). Each page's own header is hidden by CSS
injected from the shell (same-origin), so the shell's tab bar is the only
nav. The classic full-page URLs keep working unchanged.
"""
from signalbot.config import *
from signalbot.ui.shared import *

__all__ = ['_render_shell']


_SHELL_HTML = r"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>WealthOS</title>
__THEME_HEAD__
<style>
  html,body{height:100%}
  body{display:flex;flex-direction:column;overflow:hidden}
  .header{flex-shrink:0}
  #frames{flex:1;position:relative;min-height:0}
  /* visibility (not display) keeps hidden frames at full size, so their pages
     lay out and paint completely offscreen — revealing them is instant */
  #frames iframe{position:absolute;inset:0;width:100%;height:100%;border:0;visibility:hidden;background:transparent}
  #frames iframe.on{visibility:visible}
  .tab-btn.pending{opacity:.45;cursor:progress}
  #loadbar{position:absolute;top:0;left:0;right:0;height:2px;z-index:5;background:var(--grad);
    transform:scaleX(0);transform-origin:left;opacity:0}
  #loadbar.busy{animation:wosLoad 1.2s var(--ease) infinite;opacity:1}
  @keyframes wosLoad{0%{transform:scaleX(0)}70%{transform:scaleX(.85)}100%{transform:scaleX(1);opacity:0}}
  #openFull{font-size:10px;letter-spacing:.08em;text-transform:uppercase;color:var(--muted);
    text-decoration:none;padding:6px 12px;border:1px solid var(--border);border-radius:999px;
    transition:all .25s var(--ease)}
  #openFull:hover{color:var(--text);border-color:var(--border2)}
  @media(max-width:480px){#openFull{display:none}}
</style>
</head>
<body>

<div class="wos-aurora"></div>
<div class="wos-grid"></div>

<div class="header">
  <div class="header-left">
    <div class="logo">wealth<span>os</span></div>
    <div class="tab-nav" id="tabs">
      <a class="tab-btn" data-t="portfolio">Portfolio</a>
      <a class="tab-btn" data-t="rsps">RSPS</a>
      <a class="tab-btn" data-t="history">History</a>
      <a class="tab-btn" data-t="strategies">Strategies</a>
    </div>
  </div>
  <a id="openFull" href="?" target="_blank" title="Open this tab as a full page">open ↗</a>
</div>

<div id="frames">
  <div id="loadbar"></div>
  <iframe data-t="portfolio" title="Portfolio"></iframe>
  <iframe data-t="rsps" title="RSPS"></iframe>
  <iframe data-t="history" title="History"></iframe>
  <iframe data-t="strategies" title="Strategies"></iframe>
</div>

<script>
'use strict';
// The frames load the real classic pages; their own headers are hidden so the
// shell's tab bar is the single nav. Frames are kept alive after first load —
// that's what makes switching instant.
const SRC = {
  portfolio:  '?action=portfolio',
  rsps:       '?',
  history:    '?action=history',
  strategies: '?action=strategies',
};
const frames = {}, tabs = {};
document.querySelectorAll('#frames iframe').forEach(f => frames[f.dataset.t] = f);
document.querySelectorAll('#tabs .tab-btn').forEach(t => {
  tabs[t.dataset.t] = t;
  t.addEventListener('click', () => activate(t.dataset.t));
});

function dress(f){
  // Same-origin: hide the embedded page's own header. Re-runs on every load
  // (survives in-frame navigation like approve/dismiss result pages).
  try{
    const d = f.contentDocument;
    if(!d || !d.head || d.getElementById('shellcss')) return;
    const st = d.createElement('style');
    st.id = 'shellcss';
    st.textContent = '.header{display:none!important}';
    d.head.appendChild(st);
  }catch(e){}
}

Object.values(frames).forEach(f => {
  f.addEventListener('load', () => {
    dress(f);
    f.dataset.loaded = '1';
    tabs[f.dataset.t].classList.remove('pending');
    if(f.classList.contains('on')) document.getElementById('loadbar').classList.remove('busy');
  });
});

function ensure(t){
  const f = frames[t];
  if(!f.getAttribute('src')) f.src = SRC[t];
  return f;
}

function replay(f){
  // Re-trigger the embedded page's own entrance cascade (.main>* wosRise).
  // Pages animate on load, but frames load offscreen now — so replay the
  // show each time the tab becomes visible. Uses the page's own keyframes,
  // so prefers-reduced-motion is respected automatically.
  try{
    const d = f.contentDocument;
    if(!d) return;
    const kids = d.querySelectorAll('.main > *');
    kids.forEach(k => k.style.animation = 'none');
    void d.body.offsetWidth;
    kids.forEach(k => k.style.animation = '');
  }catch(e){}
}

function activate(t){
  if(!frames[t]) t = 'portfolio';
  const f = ensure(t);
  const wasActive = f.classList.contains('on');
  Object.values(frames).forEach(x => x.classList.toggle('on', x === f));
  Object.entries(tabs).forEach(([k, el]) => el.classList.toggle('active', k === t));
  document.getElementById('openFull').href = SRC[t];
  document.getElementById('loadbar').classList.toggle('busy', !f.dataset.loaded);
  if(!wasActive && f.dataset.loaded) replay(f);
  if(location.hash !== '#' + t) history.replaceState(null, '', '#' + t);
}

addEventListener('hashchange', () => activate(location.hash.slice(1) || 'portfolio'));

// Boot: load ALL frames in parallel immediately — the server renders them
// concurrently, and hidden frames paint fully offscreen (visibility trick),
// so every tab is genuinely ready, not just requested. Tabs show dimmed
// until their page has loaded.
Object.values(tabs).forEach(t => t.classList.add('pending'));
Object.keys(frames).forEach(t => ensure(t));
activate(location.hash.slice(1) || 'portfolio');
</script>
</body>
</html>"""


def _render_shell() -> str:
    return _SHELL_HTML.replace("__THEME_HEAD__", _theme_head())

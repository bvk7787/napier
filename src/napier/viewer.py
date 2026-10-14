"""
napier.viewer
~~~~~~~~~~~~~
`napier rack view`: an interactive picture of the rack, as one self-contained HTML page.

It draws the actual rack (positions from napier's rack snapshot) and every napier scenario
(racks/scenarios/*.yaml, resolved in the export) at real HP widths, case by case,
with per-case power against the supply limits, what changed against the actual rack, and each
module's job, notes, open questions and challenge history on click.

No database and no optimizer: everything comes from `napier rack export`. Moved here from euclid,
which was archived on 2026-10-12.
"""
from __future__ import annotations

import datetime as _dt
import json
import re

RAILS = ("plus12", "minus12", "plus5")
_AT_RE = re.compile(r"row\s*(\d+)\s*,\s*hp\s*(\d+)", re.IGNORECASE)


def _draw(m: dict) -> dict:
    """Conservative per-rail draw: the larger of the rack source's and the manual's figure."""
    mg, man = m.get("power") or {}, m.get("power_manual") or {}
    return {k: max(int(mg.get(k) or 0), int(man.get(k) or 0)) for k in RAILS}


def build_data(export: dict, generated: str | None = None) -> dict:
    """The JSON the page renders from."""
    mods: dict[str, dict] = {}
    actual: list[dict] = []
    for m in export.get("modules") or []:
        slug = m["slug"]
        u = m.get("usage") or {}
        if slug not in mods or (m.get("at") and not mods[slug].get("_racked")):
            mods[slug] = dict(
                name=m.get("name"), vendor=m.get("vendor"), hp=int(m.get("hp") or 0),
                format=m.get("format"), role=m.get("role") or "utility", owned=bool(m.get("owned")),
                status=u.get("status"), job=u.get("job"), notes=u.get("notes") or [],
                open=u.get("open") or [], pairs_with=u.get("pairs_with") or [],
                keep_near=u.get("keep_near") or [], power=_draw(m),
                manual=bool(m.get("spec_source")), docs=len(m.get("docs") or []),
                _racked=bool(m.get("at")),
            )
        if m.get("racked") and m.get("owned") and m.get("at"):
            actual.append(dict(slug=slug, at=list(m["at"]), change="kept"))
    # scenario modules that napier only knows from the wishlist still need a card
    for s in (export.get("scenarios") or {}).values():
        for e in list(s.get("modules") or []) + list(s.get("removed") or []):
            if e["slug"] not in mods:
                mods[e["slug"]] = dict(name=e.get("name"), vendor=e.get("vendor"), hp=int(e.get("hp") or 0),
                                       format=e.get("format"), role=e.get("role") or "utility",
                                       owned=bool(e.get("owned")), status=e.get("status"), job=None,
                                       notes=[], open=[], pairs_with=[], keep_near=[],
                                       power={k: 0 for k in RAILS}, manual=False, docs=0, _racked=False)
    for v in mods.values():
        v.pop("_racked", None)
    rack = export.get("rack") or {}
    layouts = {"actual": dict(name="Actual rack", date=str(rack.get("modified") or ""),
                              description="What's in the cases now, from the rack snapshot.",
                              notes=[], modules=actual, removed=[], problems=[])}
    for sid, s in (export.get("scenarios") or {}).items():
        layouts[sid] = dict(name=s.get("name") or sid, date=s.get("date") or "",
                            description=s.get("description") or "", notes=s.get("notes") or [],
                            modules=[dict(slug=e["slug"], at=e["at"], change=e["change"]) for e in s["modules"]],
                            removed=[dict(slug=e["slug"], at=e["at"]) for e in s.get("removed") or []],
                            problems=s.get("problems") or [])
    geo = export.get("geometry")
    if not geo:
        from napier.scenarios import geometry
        geo = geometry(rack)
    cases = {}
    for name, c in (geo.get("cases") or {}).items():
        uc = (export.get("usage_cases") or {}).get(name) or {}
        cases[name] = dict(rows=c["rows"], hp=c["hp"], mode=uc.get("mode"), power=uc.get("power"),
                           limits=uc.get("limits") or {})
    challenges = [dict(id=c.get("id"), date=str(c.get("date") or ""), title=c.get("title"),
                       outcome=c.get("outcome"), modules=c.get("modules") or [],
                       response=c.get("response"), learned=c.get("learned"))
                  for c in export.get("challenges") or []]
    title = export.get("title") or (f"{rack.get('name')}" if rack.get("name") else "Rack")
    who = export.get("owner") or ""
    return dict(title=title, owner=(who[:1].upper() + who[1:]) if who else "",
                rack=dict(name=rack.get("name"), url=rack.get("url"), modified=str(rack.get("modified") or "")),
                geometry=dict(rows=geo["rows"], hp=geo["hp"], case_hp=geo["case_hp"], grid=geo.get("grid") or [1, 1],
                              order=geo.get("order") or list(geo.get("cases") or {}),
                              row_format={str(k): v for k, v in geo["row_format"].items()}),
                cases=cases, modules=mods, layouts=layouts, challenges=challenges,
                generated=generated or _dt.datetime.now().strftime("%Y-%m-%d %H:%M"))


def render(export: dict, standalone: bool = True, generated: str | None = None, web_fonts: bool = False) -> str:
    """The page. standalone=False leaves out <!doctype>/<html>/<head>/<body> (for hosts that add them).
    The page loads nothing from the network unless web_fonts is set (Google Fonts for the display faces;
    without them it uses the fallback system fonts)."""
    import html as _html
    d = build_data(export, generated)
    # JSON inside <script>: escape the characters HTML cares about, so no value can close the tag or
    # open a comment; then fill the placeholders in one pass, so a value can't smuggle in another one.
    data = (json.dumps(d, ensure_ascii=False)
            .replace("&", "\\u0026").replace("<", "\\u003c").replace(">", "\\u003e")
            .replace("\u2028", "\\u2028").replace("\u2029", "\\u2029"))
    fill = {"__TITLE__": _html.escape(d["title"]), "__DATA__": data, "__FONTS__": WEB_FONTS if web_fonts else ""}
    body = re.sub("__TITLE__|__DATA__|__FONTS__", lambda m: fill[m.group(0)], PAGE)
    if not standalone:
        return body
    return ("<!doctype html>\n<html lang=\"en\">\n<head>\n<meta charset=\"utf-8\">\n"
            "<meta name=\"viewport\" content=\"width=device-width, initial-scale=1, viewport-fit=cover\">\n"
            "</head>\n<body>\n" + body + "\n</body>\n</html>\n")


WEB_FONTS = """<link rel="preconnect" href="https://fonts.googleapis.com">
<link rel="preconnect" href="https://fonts.gstatic.com" crossorigin>
<link rel="stylesheet" href="https://fonts.googleapis.com/css2?family=IBM+Plex+Mono:wght@400;500&family=IBM+Plex+Sans+Condensed:wght@400;500;600&family=Saira+Condensed:wght@500;700&display=swap">
"""

PAGE = r"""<title>__TITLE__</title>
__FONTS__<style>
/* Layout: control strip, then the grid of cases drawn to HP scale; details open in a side panel (bottom sheet on phones). */
:root {
  --bg: #e9ecef; --surface: #f8f9fa; --case: #d5dade; --rail: #b3bac2; --slot: #e3e7ea;
  --ink: #1b2026; --muted: #59626c; --line: #c3c9cf;
  --accent: #b86a00; --new: #22814f; --moved: #b86a00; --bad: #c0362c; --focus: #2a6fdb;
  --r-voice: #f0c4b0; --r-filter: #f2d896; --r-effect: #cdbbe8; --r-rhythm: #f0b2c3; --r-sequencer: #a8d1e8;
  --r-modulation: #b3dec1; --r-utility: #d4d8dd; --r-mixer: #e8c897; --r-midi: #a6d9d3; --r-expander: #dfe2c2;
  --f-display: "Saira Condensed", "Arial Narrow", "Roboto Condensed", sans-serif;
  --f-body: "IBM Plex Sans Condensed", "Arial Narrow", system-ui, sans-serif;
  --f-mono: "IBM Plex Mono", ui-monospace, "SF Mono", Menlo, monospace;
  --u3: 132px; --u1: 46px;
}
@media (prefers-color-scheme: dark) { :root:not([data-theme="light"]) {
  --bg: #111418; --surface: #181c21; --case: #1f252c; --rail: #39424c; --slot: #161a1f;
  --ink: #e5e8eb; --muted: #97a1ab; --line: #2f363e;
  --accent: #f0a540; --new: #4cc483; --moved: #f0a540; --bad: #ff6b5e; --focus: #6aa2ff;
  --r-voice: #6e3a27; --r-filter: #6b5726; --r-effect: #463869; --r-rhythm: #6c2f43; --r-sequencer: #285269;
  --r-modulation: #2b5a3d; --r-utility: #353c45; --r-mixer: #61441f; --r-midi: #215752; --r-expander: #474b2c;
  color-scheme: dark } }
:root[data-theme="dark"] {
  --bg: #111418; --surface: #181c21; --case: #1f252c; --rail: #39424c; --slot: #161a1f;
  --ink: #e5e8eb; --muted: #97a1ab; --line: #2f363e;
  --accent: #f0a540; --new: #4cc483; --moved: #f0a540; --bad: #ff6b5e; --focus: #6aa2ff;
  --r-voice: #6e3a27; --r-filter: #6b5726; --r-effect: #463869; --r-rhythm: #6c2f43; --r-sequencer: #285269;
  --r-modulation: #2b5a3d; --r-utility: #353c45; --r-mixer: #61441f; --r-midi: #215752; --r-expander: #474b2c;
  color-scheme: dark }
* { box-sizing: border-box }
[hidden] { display: none !important }
body { background: var(--bg); color: var(--ink); font-family: var(--f-body); font-size: 14px; margin: 0 }
.wrap { padding-inline: 16px; padding-block: 16px 40px; max-width: 1500px; margin: 0 auto; display: grid; gap: 14px }
h1 { font-family: var(--f-display); font-weight: 700; font-size: 30px; letter-spacing: .01em; margin: 0; line-height: 1 }
.top { display: flex; flex-wrap: wrap; align-items: flex-end; justify-content: space-between; gap: 10px 20px }
.sub { color: var(--muted); font-size: 13px }
.sub a { color: inherit }
.controls { display: flex; flex-wrap: wrap; gap: 8px; align-items: center }
.seg { display: inline-flex; flex-wrap: wrap; border: 1px solid var(--line); border-radius: 8px; overflow: hidden; background: var(--surface) }
.seg button { font: inherit; font-size: 13px; padding: 7px 12px; border: 0; background: transparent; color: var(--ink); cursor: pointer }
.seg button + button { border-left: 1px solid var(--line) }
.seg button[aria-pressed="true"] { background: var(--ink); color: var(--bg) }
button:focus-visible, input:focus-visible, .mod:focus-visible { outline: 2px solid var(--focus); outline-offset: 2px }
.toggle { display: inline-flex; align-items: center; gap: 6px; font-size: 13px; color: var(--muted); cursor: pointer; user-select: none }
#q { font: inherit; font-size: 13px; padding: 7px 10px; border: 1px solid var(--line); border-radius: 8px; background: var(--surface); color: var(--ink); width: 190px; max-width: 100% }
.summary { display: flex; flex-wrap: wrap; gap: 8px 18px; align-items: baseline; font-size: 13px; color: var(--muted) }
.summary b { color: var(--ink); font-weight: 600; font-variant-numeric: tabular-nums }
.desc { max-width: 75ch; color: var(--muted); font-size: 13px; line-height: 1.45; margin: 0 }
.chip { display: inline-flex; align-items: center; gap: 5px; font-size: 12px; padding: 2px 8px; border-radius: 999px; border: 1px solid var(--line); background: var(--surface); color: var(--ink); white-space: nowrap }
.chip.bad { border-color: var(--bad); color: var(--bad) }
.chip.new { border-color: var(--new); color: var(--new) }
.chip.moved { border-color: var(--moved); color: var(--moved) }
.legend { display: flex; flex-wrap: wrap; gap: 6px }
.legend .sw { width: 10px; height: 10px; border-radius: 2px; display: inline-block; border: 1px solid var(--rail) }
.main { display: grid; grid-template-columns: minmax(0, 1fr); gap: 14px }
.rack { display: grid; grid-template-columns: repeat(var(--cols, 2), minmax(0, 1fr)); gap: 10px }
@media (max-width: 1050px) { .rack { grid-template-columns: minmax(0, 1fr) } }
.case { background: var(--case); border: 1px solid var(--line); border-radius: 6px; padding: 8px 8px 10px; display: grid; gap: 6px; min-width: 0 }
.case-head { display: flex; flex-wrap: wrap; justify-content: space-between; gap: 4px 12px; align-items: baseline }
.case-name { font-family: var(--f-display); font-weight: 700; font-size: 17px; letter-spacing: .04em; text-transform: uppercase }
.case-mode { color: var(--muted); font-size: 12px; flex: 1 1 220px; min-width: 0 }
.power { display: grid; grid-template-columns: repeat(3, minmax(0, 1fr)); gap: 8px }
.pw { display: grid; gap: 2px; font-family: var(--f-mono); font-size: 10.5px; color: var(--muted); font-variant-numeric: tabular-nums }
.pw .bar { height: 5px; border-radius: 3px; background: var(--slot); overflow: hidden; border: 1px solid var(--line) }
.pw .bar i { display: block; height: 100%; background: var(--ink); opacity: .55 }
.pw.warn .bar i { background: var(--moved); opacity: 1 }
.pw.over .bar i { background: var(--bad); opacity: 1 }
.pw.over { color: var(--bad) }
.row { position: relative; background: var(--slot); border-top: 2px solid var(--rail); border-bottom: 2px solid var(--rail) }
.row.u3 { height: var(--u3) }
.row.u1 { height: var(--u1) }
.rowwrap { display: grid; grid-template-columns: 22px minmax(0, 1fr); gap: 4px; align-items: center }
.rowlabel { font-family: var(--f-mono); font-size: 9.5px; color: var(--muted); line-height: 1.1; text-align: center }
.gap { position: absolute; top: 0; bottom: 0; display: flex; align-items: center; justify-content: center; font-family: var(--f-mono); font-size: 9.5px; color: var(--muted); background-image: repeating-linear-gradient(90deg, transparent 0 4px, var(--line) 4px 5px); opacity: .7 }
.mod { position: absolute; top: 2px; bottom: 2px; border-radius: 3px; border: 1px solid var(--rail); padding: 4px 3px 3px; overflow: hidden; cursor: pointer; display: flex; flex-direction: column; justify-content: space-between; color: var(--ink); text-align: left; font: inherit; transition: opacity .15s, outline-color .15s }
.mod .nm { font-weight: 600; font-size: 11.5px; line-height: 1.12; overflow-wrap: anywhere }
.mod .hp { font-family: var(--f-mono); font-size: 9.5px; color: var(--muted); align-self: flex-end }
.mod.narrow { padding: 3px 1px }
.mod.narrow .nm { writing-mode: vertical-rl; transform: rotate(180deg); font-size: 10.5px; white-space: nowrap; align-self: center; overflow: hidden; max-height: 100% }
.mod.narrow .hp { display: none }
.u1 .mod .nm { font-size: 10.5px }
.u1 .mod .hp { display: none }
.u1 .mod.narrow .nm { writing-mode: horizontal-tb; transform: none; font-size: 9px }
.mod.wish { border-style: dashed; border-color: var(--muted) }
.diff .mod.kept { opacity: .32 }
.diff .mod.new { outline: 2.5px solid var(--new); outline-offset: -2px; z-index: 1 }
.diff .mod.moved { outline: 2.5px dashed var(--moved); outline-offset: -2px; z-index: 1 }
.mod.dim { opacity: .16 !important }
.mod.hl { outline: 2.5px solid var(--focus) !important; outline-offset: -2px; z-index: 2; opacity: 1 !important }
.mod.sel { outline: 3px solid var(--focus) !important; outline-offset: -1px; z-index: 3; opacity: 1 !important; box-shadow: 0 0 0 4px color-mix(in srgb, var(--focus) 25%, transparent) }
.tray { display: grid; gap: 8px; background: var(--surface); border: 1px solid var(--line); border-radius: 6px; padding: 10px 12px }
.tray h3 { margin: 0; font-family: var(--f-display); font-size: 15px; letter-spacing: .05em; text-transform: uppercase; font-weight: 700 }
.tray ul { margin: 0; padding-left: 18px; display: grid; gap: 3px; font-size: 13px }
.chips { display: flex; flex-wrap: wrap; gap: 6px }
.chips button.chip { cursor: pointer; font: inherit; font-size: 12px }
.problems li { color: var(--bad) }
#panel { position: fixed; right: 0; top: 0; bottom: 0; width: min(420px, 100%); background: var(--surface); border-left: 1px solid var(--line); box-shadow: -8px 0 24px rgba(0,0,0,.12); padding: calc(16px + env(safe-area-inset-top, 0px)) 18px calc(20px + env(safe-area-inset-bottom, 0px)); overflow-y: auto; z-index: 20; display: grid; align-content: start; gap: 12px }
@media (max-width: 700px) { #panel { top: auto; height: 62vh; width: 100%; border-left: 0; border-top: 1px solid var(--line); border-radius: 12px 12px 0 0 } }
#panel h2 { margin: 0; font-family: var(--f-display); font-size: 24px; line-height: 1.05; text-wrap: balance }
#panel .vendor { color: var(--muted); font-size: 13px }
#panel .close { position: absolute; right: 12px; top: calc(10px + env(safe-area-inset-top, 0px)); font: inherit; font-size: 13px; background: transparent; color: var(--muted); border: 1px solid var(--line); border-radius: 6px; padding: 4px 9px; cursor: pointer }
#panel dl { margin: 0; display: grid; grid-template-columns: auto minmax(0, 1fr); gap: 5px 12px; font-size: 13px }
#panel dt { color: var(--muted); font-size: 11.5px; text-transform: uppercase; letter-spacing: .06em; padding-top: 1px }
#panel dd { margin: 0; font-variant-numeric: tabular-nums }
#panel section { display: grid; gap: 4px }
#panel section h4 { margin: 0; font-size: 11.5px; text-transform: uppercase; letter-spacing: .06em; color: var(--muted); font-weight: 500 }
#panel p, #panel li { margin: 0; line-height: 1.45; font-size: 13.5px }
#panel ul { margin: 0; padding-left: 18px; display: grid; gap: 4px }
.ch { border-left: 3px solid var(--line); padding-left: 8px; display: grid; gap: 2px }
.ch .meta { font-family: var(--f-mono); font-size: 11px; color: var(--muted) }
.foot { color: var(--muted); font-size: 12px }
@media (prefers-reduced-motion: reduce) { .mod { transition: none } }
</style>

<div class="wrap">
  <div class="top">
    <div style="display:grid;gap:6px;min-width:0">
      <h1 id="title">__TITLE__</h1>
      <div class="sub" id="sub"></div>
    </div>
    <div class="controls">
      <div class="seg" id="layouts" role="group" aria-label="Layout"></div>
      <label class="toggle"><input type="checkbox" id="diff"> Show changes</label>
      <input id="q" type="search" placeholder="Find a module" aria-label="Find a module">
    </div>
  </div>
  <p class="desc" id="desc"></p>
  <div class="summary" id="summary"></div>
  <div class="main">
    <div class="rack" id="rack"></div>
    <div class="tray" id="tray"></div>
  </div>
  <div class="legend" id="legend"></div>
  <div class="foot" id="foot"></div>
</div>
<aside id="panel" hidden aria-live="polite"></aside>

<script id="rack-data" type="application/json">__DATA__</script>
<script>
(function () {
  var D = JSON.parse(document.getElementById('rack-data').textContent);
  var G = D.geometry, M = D.modules;
  var ROLES = ['voice','filter','effect','rhythm','sequencer','modulation','utility','mixer','midi','expander'];
  var RAIL = {plus12: '+12V', minus12: '−12V', plus5: '+5V'};
  var CASE_ORDER = G.order || Object.keys(D.cases);
  var state = {layout: 'actual', diff: false, q: '', sel: null};
  try { var saved = localStorage.getItem('rackview.layout'); if (saved && D.layouts[saved]) state.layout = saved; } catch (e) {}
  var hash = (location.hash || '').slice(1);
  if (hash && D.layouts[hash]) state.layout = hash;

  function el(tag, attrs, kids) {
    var n = document.createElement(tag);
    for (var k in (attrs || {})) {
      if (k === 'text') n.textContent = attrs[k];
      else if (k === 'class') n.className = attrs[k];
      else if (k.slice(0, 2) === 'on') n.addEventListener(k.slice(2), attrs[k]);
      else n.setAttribute(k, attrs[k]);
    }
    (kids || []).forEach(function (c) { if (c != null) n.appendChild(typeof c === 'string' ? document.createTextNode(c) : c); });
    return n;
  }
  function parseAt(a) { var m = /row\s*(\d+)\s*,\s*hp\s*(\d+)/i.exec(a || ''); return m ? [+m[1], +m[2]] : null; }
  function caseOf(r, h) {
    for (var i = 0; i < CASE_ORDER.length; i++) { var c = D.cases[CASE_ORDER[i]]; if (c && c.rows.indexOf(r) >= 0 && h >= c.hp[0] && h <= c.hp[1]) return CASE_ORDER[i]; }
    return null;
  }
  function placed(layout) {
    var out = [];
    layout.modules.forEach(function (e) {
      e.at.forEach(function (a) { var p = parseAt(a); if (p) out.push({slug: e.slug, row: p[0], hp: p[1], change: e.change}); });
    });
    return out;
  }
  function actualPos(slug) {
    var e = D.layouts.actual.modules.filter(function (x) { return x.slug === slug; })[0];
    return e ? e.at : [];
  }
  function statusLabel(m) {
    var s = m.status || (m.owned ? 'owned' : 'wishlist');
    return s;
  }

  function renderLayoutButtons() {
    var seg = document.getElementById('layouts'); seg.textContent = '';
    Object.keys(D.layouts).forEach(function (id) {
      seg.appendChild(el('button', {type: 'button', 'aria-pressed': String(id === state.layout), text: D.layouts[id].name,
        onclick: function () { state.layout = id; state.sel = null; try { localStorage.setItem('rackview.layout', id); } catch (e) {} render(); }}));
    });
  }

  function render() {
    var L = D.layouts[state.layout];
    renderLayoutButtons();
    document.getElementById('sub').innerHTML = '';
    var sub = document.getElementById('sub');
    var nCases = CASE_ORDER.length, words = ['one', 'two', 'three', 'four', 'five', 'six', 'seven', 'eight', 'nine'];
    var desc = nCases === 1 ? 'one case, ' + G.hp + ' HP, ' + G.rows + ' rows'
      : (words[nCases - 1] || nCases) + ' cases, ' + G.case_hp + ' HP each';
    sub.appendChild(document.createTextNode((D.rack.name || 'Rack') + ' · ' + desc + ' · '));
    if (D.rack.url && /^https?:\/\//i.test(D.rack.url)) sub.appendChild(el('a', {href: D.rack.url, target: '_blank', rel: 'noopener', text: 'rack source'}));
    document.getElementById('desc').textContent = L.description || '';
    var P = placed(L);
    var counts = {moved: 0, new: 0};
    L.modules.forEach(function (e) { if (counts[e.change] != null) counts[e.change]++; });
    var hpUsed = P.reduce(function (s, p) { return s + (M[p.slug] ? M[p.slug].hp : 0); }, 0);
    var hpTotal = 0; for (var r = 1; r <= G.rows; r++) hpTotal += G.hp;
    var sum = document.getElementById('summary'); sum.textContent = '';
    sum.appendChild(el('span', {}, [el('b', {text: String(P.length)}), ' modules']));
    sum.appendChild(el('span', {}, [el('b', {text: hpUsed + ' / ' + hpTotal}), ' HP filled']));
    if (state.layout !== 'actual') {
      sum.appendChild(el('span', {class: 'chip moved', text: counts.moved + ' moved'}));
      sum.appendChild(el('span', {class: 'chip new', text: counts['new'] + ' new'}));
      sum.appendChild(el('span', {class: 'chip', text: L.removed.length + ' leaving'}));
      sum.appendChild(el('span', {class: 'chip' + (L.problems.length ? ' bad' : ''), text: L.problems.length ? L.problems.length + ' problems' : 'no conflicts'}));
    }
    if (L.date) sum.appendChild(el('span', {text: (state.layout === 'actual' ? 'snapshot ' : 'drafted ') + L.date}));
    var diffBox = document.getElementById('diff');
    diffBox.disabled = state.layout === 'actual';
    var rack = document.getElementById('rack'); rack.textContent = '';
    rack.style.setProperty('--cols', String((G.grid || [2])[0]));
    rack.classList.toggle('diff', state.diff && state.layout !== 'actual');
    CASE_ORDER.forEach(function (cn) { rack.appendChild(renderCase(cn, P)); });
    renderTray(L);
    applySearch();
    if (state.sel) openPanel(state.sel); else closePanel(true);
  }

  function renderCase(cn, P) {
    var c = D.cases[cn]; if (!c) return el('div');
    var mine = P.filter(function (p) { return caseOf(p.row, p.hp) === cn; });
    var load = {plus12: 0, minus12: 0, plus5: 0};
    mine.forEach(function (p) { var m = M[p.slug]; if (m) for (var k in load) load[k] += (m.power[k] || 0); });
    var power = el('div', {class: 'power'});
    Object.keys(RAIL).forEach(function (k) {
      var lim = (c.limits || {})[k], pct = lim ? Math.round(load[k] / lim * 100) : null;
      var box = el('div', {class: 'pw' + (pct >= 100 ? ' over' : pct >= 90 ? ' warn' : ''), title: RAIL[k] + ': ' + load[k] + ' mA of ' + (lim || '?') + ' mA'});
      box.appendChild(el('span', {text: RAIL[k] + ' ' + load[k] + (lim ? '/' + lim + ' mA · ' + pct + '%' : ' mA')}));
      var bar = el('div', {class: 'bar'}); var fill = el('i'); fill.style.width = Math.min(pct || 0, 100) + '%'; bar.appendChild(fill);
      box.appendChild(bar); power.appendChild(box);
    });
    var head = el('div', {class: 'case-head'}, [el('span', {class: 'case-name', text: cn.replace('-', ' ')}), el('span', {class: 'case-mode', text: c.mode || ''})]);
    var box = el('section', {class: 'case', 'aria-label': cn}, [head, power]);
    var width = c.hp[1] - c.hp[0] + 1;
    c.rows.forEach(function (r) {
      var fmt = (G.row_format[String(r)] || '3U');
      var row = el('div', {class: 'row ' + (fmt === '1U' ? 'u1' : 'u3')});
      var lab = el('div', {class: 'rowlabel', title: 'Row ' + r + ' (' + fmt + ')'}, ['R' + r, el('br'), fmt]);
      var inRow = mine.filter(function (p) { return p.row === r; }).sort(function (a, b) { return a.hp - b.hp; });
      var cursor = c.hp[0];
      inRow.forEach(function (p) {
        if (p.hp > cursor) row.appendChild(gapEl(cursor, p.hp - 1, c.hp[0], width));
        row.appendChild(modEl(p, c.hp[0], width));
        cursor = Math.max(cursor, p.hp + (M[p.slug] ? M[p.slug].hp : 0));
      });
      if (cursor <= c.hp[1]) row.appendChild(gapEl(cursor, c.hp[1], c.hp[0], width));
      box.appendChild(el('div', {class: 'rowwrap'}, [lab, row]));
    });
    return box;
  }
  function pct(x, width) { return (x / width * 100) + '%'; }
  function gapEl(from, to, start, width) {
    var n = to - from + 1;
    var g = el('div', {class: 'gap', title: n + ' HP free at ' + from + '–' + to, text: n >= 4 ? n + ' HP' : ''});
    g.style.left = pct(from - start, width); g.style.width = pct(n, width);
    return g;
  }
  function modEl(p, start, width) {
    var m = M[p.slug] || {name: p.slug, hp: 4, role: 'utility'};
    var narrow = m.hp <= 6;
    var b = el('button', {type: 'button', class: 'mod ' + p.change + (narrow ? ' narrow' : '') + (m.owned ? '' : ' wish'),
      'data-slug': p.slug, title: m.name + ' · ' + m.hp + ' HP · row ' + p.row + ', hp ' + p.hp + (p.change !== 'kept' && state.layout !== 'actual' ? ' · ' + p.change : ''),
      onclick: function () { state.sel = (state.sel === p.slug ? null : p.slug); if (state.sel) openPanel(p.slug); else closePanel(); }},
      [el('span', {class: 'nm', text: m.name}), el('span', {class: 'hp', text: m.hp + 'HP'})]);
    b.style.left = pct(p.hp - start, width); b.style.width = pct(m.hp, width);
    b.style.background = 'var(--r-' + (ROLES.indexOf(m.role) >= 0 ? m.role : 'utility') + ')';
    return b;
  }

  function renderTray(L) {
    var t = document.getElementById('tray'); t.textContent = '';
    t.hidden = false;
    var any = false;
    if (state.layout !== 'actual' && L.removed.length) {
      any = true;
      t.appendChild(el('h3', {text: 'Leaving the rack'}));
      var chips = el('div', {class: 'chips'});
      L.removed.forEach(function (r) {
        var m = M[r.slug] || {name: r.slug};
        chips.appendChild(el('button', {type: 'button', class: 'chip', text: m.name + ' (' + r.at.join('; ') + ')',
          onclick: function () { state.sel = r.slug; openPanel(r.slug); }}));
      });
      t.appendChild(chips);
    }
    var off = Object.keys(M).filter(function (s) {
      var m = M[s]; return !L.modules.some(function (e) { return e.slug === s; }) && !L.removed.some(function (e) { return e.slug === s; })
        && (m.owned ? state.layout === 'actual' : false);
    });
    if (off.length) {
      any = true;
      t.appendChild(el('h3', {text: 'Owned, not in the cases'}));
      var c2 = el('div', {class: 'chips'});
      off.forEach(function (s) { c2.appendChild(el('button', {type: 'button', class: 'chip', text: M[s].name + ' · ' + M[s].hp + ' HP', onclick: function () { state.sel = s; openPanel(s); }})); });
      t.appendChild(c2);
    }
    if (L.problems.length) {
      any = true;
      t.appendChild(el('h3', {text: 'Conflicts'}));
      var ul = el('ul', {class: 'problems'}); L.problems.forEach(function (p) { ul.appendChild(el('li', {text: p})); }); t.appendChild(ul);
    }
    if (L.notes && L.notes.length) {
      any = true;
      t.appendChild(el('h3', {text: 'Notes on this layout'}));
      var ul2 = el('ul'); L.notes.forEach(function (n) { ul2.appendChild(el('li', {text: n})); }); t.appendChild(ul2);
    }
    t.hidden = !any;
  }

  function applySearch() {
    var q = state.q.trim().toLowerCase();
    var related = [];
    if (state.sel && M[state.sel]) related = (M[state.sel].pairs_with || []).concat(M[state.sel].keep_near || []);
    document.querySelectorAll('.mod').forEach(function (b) {
      var s = b.getAttribute('data-slug'), m = M[s] || {};
      var hit = q && ((m.name || '').toLowerCase().indexOf(q) >= 0 || (m.vendor || '').toLowerCase().indexOf(q) >= 0 || (m.role || '') === q);
      b.classList.toggle('hl', !!hit || related.indexOf(s) >= 0);
      b.classList.toggle('dim', !!q && !hit);
    });
    markSel();
  }
  function markSel() {
    document.querySelectorAll('.mod').forEach(function (b) { b.classList.toggle('sel', b.getAttribute('data-slug') === state.sel); });
  }

  function openPanel(slug) {
    var m = M[slug]; if (!m) return;
    var L = D.layouts[state.layout];
    var p = document.getElementById('panel'); p.textContent = ''; p.hidden = false;
    p.appendChild(el('button', {type: 'button', class: 'close', text: 'Close', onclick: function () { state.sel = null; closePanel(); }}));
    p.appendChild(el('div', {style: 'display:grid;gap:4px;padding-right:64px'}, [el('h2', {text: m.name}), el('div', {class: 'vendor', text: (m.vendor || '') + ' · ' + m.hp + ' HP ' + (m.format || '')})]));
    var here = L.modules.filter(function (e) { return e.slug === slug; })[0];
    var gone = L.removed.filter(function (e) { return e.slug === slug; })[0];
    var chips = el('div', {class: 'chips'});
    chips.appendChild(el('span', {class: 'chip', text: m.role}));
    chips.appendChild(el('span', {class: 'chip', text: statusLabel(m)}));
    if (state.layout !== 'actual' && here && here.change !== 'kept') chips.appendChild(el('span', {class: 'chip ' + here.change, text: here.change}));
    if (gone) chips.appendChild(el('span', {class: 'chip bad', text: 'leaving'}));
    p.appendChild(chips);
    var dl = el('dl');
    function row(k, v) { if (v == null || v === '') return; dl.appendChild(el('dt', {text: k})); dl.appendChild(el('dd', {text: v})); }
    if (here) row('Position', here.at.join('; '));
    if (state.layout !== 'actual') { var a = actualPos(slug); row('Now at', a.length ? a.join('; ') : 'not in the cases'); }
    var pw = m.power || {};
    row('Power', '+12V ' + (pw.plus12 || 0) + ' mA · −12V ' + (pw.minus12 || 0) + ' mA · +5V ' + (pw.plus5 || 0) + ' mA' + (m.manual ? ' (manual)' : ''));
    if (m.docs) row('In napier', m.docs + (m.docs === 1 ? ' document' : ' documents'));
    p.appendChild(dl);
    if (m.job) p.appendChild(el('section', {}, [el('h4', {text: 'Job'}), el('p', {text: m.job})]));
    function list(title, items) { if (!items || !items.length) return; var ul = el('ul'); items.forEach(function (x) { ul.appendChild(el('li', {text: x})); }); p.appendChild(el('section', {}, [el('h4', {text: title}), ul])); }
    list('Notes', m.notes);
    list('Not settled yet', m.open);
    var rel = (m.pairs_with || []).concat(m.keep_near || []).filter(function (s, i, a) { return a.indexOf(s) === i; });
    if (rel.length) list('Keep near (outlined in the rack)', rel.map(function (s) { return M[s] ? M[s].name : s; }));
    var chs = D.challenges.filter(function (c) { return (c.modules || []).indexOf(slug) >= 0; });
    if (chs.length) {
      var sec = el('section', {}, [el('h4', {text: 'Challenge log'})]);
      chs.forEach(function (c) {
        var d = el('div', {class: 'ch'}, [el('span', {class: 'meta', text: c.id + ' · ' + c.date + ' · ' + c.outcome}), el('p', {text: c.title})]);
        if (c.response) d.appendChild(el('p', {style: 'color:var(--muted)', text: (D.owner || 'Owner') + ': ' + c.response}));
        sec.appendChild(d);
      });
      p.appendChild(sec);
    }
    applySearch();
  }
  function closePanel(silent) { var p = document.getElementById('panel'); p.hidden = true; p.textContent = ''; if (!silent) applySearch(); }

  document.getElementById('diff').addEventListener('change', function (e) { state.diff = e.target.checked; render(); });
  document.getElementById('q').addEventListener('input', function (e) { state.q = e.target.value; applySearch(); });
  document.addEventListener('keydown', function (e) { if (e.key === 'Escape' && state.sel) { state.sel = null; closePanel(); } });

  var lg = document.getElementById('legend');
  ROLES.forEach(function (r) {
    var sw = el('span', {class: 'sw'}); sw.style.background = 'var(--r-' + r + ')';
    lg.appendChild(el('button', {type: 'button', class: 'chip', title: 'Highlight ' + r + ' modules', onclick: function () { var q = document.getElementById('q'); q.value = (state.q === r ? '' : r); state.q = q.value; applySearch(); }}, [sw, r]));
  });
  lg.appendChild(el('span', {class: 'chip', style: 'border-style:dashed', text: 'dashed border = not owned yet'}));
  document.getElementById('foot').textContent = 'Drawn from napier on ' + D.generated + (D.rack.modified ? '. Rack last changed ' + D.rack.modified + '.' : '.') + ' Scenarios live in napier racks/scenarios.';
  render();
})();
</script>
"""

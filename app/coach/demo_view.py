"""The public "Watch the agent work" page and the step renderer shared with simulations.

The page plays back a trace produced by the real engine in a throwaway
database (see app/public_demo.py). The browser only animates it; every message,
decision and state shown was produced by the agent's own code.
"""

from __future__ import annotations

import json
from html import escape

KIND_CLASS = {
    "interpret": "k-interpret", "rule": "k-rule", "action": "k-action", "coach": "k-coach",
    "escalation": "k-escalation", "outcome": "k-outcome", "wait": "k-wait", "observe": "k-wait",
    "athlete": "k-athlete", "adapt": "k-rule", "clock": "k-wait",
}

LEGEND = (
    ("k-interpret", "Interpretation",
     "Free text becomes validated data. The live agent uses Gemini 2.5 Flash; this demo uses a "
     "built-in offline parser with the same data format, so nothing leaves the page."),
    ("k-rule", "Fixed rule",
     "Tested, repeatable rules score readiness and apply safety limits. Gemini is not involved."),
    ("k-action", "Agent action", "The agent sends a message or follows up on its own."),
    ("k-escalation", "Needs the coach", "Anything outside its authority is handed to the coach with evidence."),
    ("k-coach", "Coach decision", "The coach decides with one tap. The agent carries it out."),
    ("k-outcome", "Outcome", "The day closes only when the result is known."),
)

DEMO_STYLE = """
.k-interpret{--k:#8e44ad}.k-rule{--k:#0a64d6}.k-action{--k:#1f8a3a}.k-coach{--k:#c26a00}
.k-escalation{--k:#c9281e}.k-outcome{--k:#0f7f86}.k-wait{--k:#6e6e73}.k-athlete{--k:#3a3a3c}
.kind-chip{display:inline-flex;align-items:center;gap:.35rem;font-size:.72rem;font-weight:700;
  letter-spacing:.03em;text-transform:uppercase;color:var(--k)}
.kind-chip::before{content:"";width:.55rem;height:.55rem;border-radius:50%;background:var(--k)}
.step-list{list-style:none;margin:0;padding:0}
.step-item{display:grid;grid-template-columns:3.6rem 1fr;gap:.7rem;padding:.6rem .2rem;
  border-top:1px solid rgba(60,60,67,.12)}
.step-item:first-child{border-top:0}
.step-item time{font-variant-numeric:tabular-nums;color:var(--secondary-label,#6e6e73);font-size:.85rem}
.step-item .step-title{font-weight:600;margin:.1rem 0}
.step-item .step-who{color:var(--secondary-label,#6e6e73);font-weight:500}
.step-item pre{white-space:pre-wrap;font:inherit;font-size:.88rem;margin:.3rem 0 0;padding:.5rem .65rem;
  border-radius:10px;background:rgba(118,118,128,.08);border-left:3px solid var(--k)}
.step-item.k-interpret pre{font-family:ui-monospace,SFMono-Regular,Menlo,monospace;font-size:.8rem}
.step-options{display:flex;flex-wrap:wrap;gap:.35rem;margin-top:.35rem}
.step-options span{font-size:.78rem;border:1px solid rgba(60,60,67,.25);border-radius:999px;padding:.12rem .55rem}
.step-options span.chosen{background:#c26a00;border-color:#c26a00;color:#fff}
"""

PAGE_STYLE = """
body{background:var(--bg,#f2f2f7)}
.demo-top{position:sticky;top:0;z-index:5;display:flex;align-items:center;gap:1rem;justify-content:space-between;
  padding:.7rem 1.25rem;background:rgba(242,242,247,.85);backdrop-filter:saturate(180%) blur(20px);
  border-bottom:1px solid rgba(60,60,67,.12)}
.demo-top a{color:inherit;text-decoration:none;font-weight:600}
.sim-pill{font-size:.78rem;font-weight:700;border-radius:999px;padding:.25rem .7rem;background:#fff3cd;color:#7a5200}
.demo-wrap{max-width:1180px;margin:0 auto;padding:1.5rem 1.25rem 4rem}
.demo-intro h1{font-size:clamp(1.8rem,4vw,2.6rem);letter-spacing:-.03em;margin:.2rem 0 .5rem}
.demo-intro p{max-width:46rem;color:var(--secondary-label,#48484a);font-size:1.05rem;line-height:1.5}
.demo-controls{display:flex;flex-wrap:wrap;align-items:center;gap:.6rem;margin:1rem 0}
.demo-clock{font-variant-numeric:tabular-nums;font-weight:700;font-size:1.25rem;min-width:4.5rem}
.demo-progress{flex:1 1 12rem;height:6px;border-radius:999px;background:rgba(118,118,128,.2);overflow:hidden}
.demo-progress span{display:block;height:100%;width:0;background:#0a64d6;transition:width .4s}
.demo-legend{list-style:none;padding:0;margin:.5rem 0 1.25rem;display:grid;
  grid-template-columns:repeat(auto-fit,minmax(16rem,1fr));gap:.4rem 1rem}
.demo-legend li{font-size:.85rem;color:var(--secondary-label,#48484a)}
.demo-grid{display:grid;grid-template-columns:minmax(0,5fr) minmax(0,7fr);gap:1rem;align-items:start}
.demo-phones{display:grid;gap:1rem}
.phone{background:#fff;border-radius:22px;box-shadow:0 8px 30px rgba(0,0,0,.08);overflow:hidden}
.phone-head{display:flex;gap:.6rem;align-items:center;padding:.7rem .9rem;background:#517da2;color:#fff}
.phone-head small{display:block;opacity:.85;font-size:.72rem}
.phone-avatar{width:2rem;height:2rem;border-radius:50%;display:grid;place-items:center;background:rgba(255,255,255,.25);font-weight:700}
.phone-body{height:15rem;overflow-y:auto;padding:.7rem;display:flex;flex-direction:column;gap:.45rem;
  background:#dfe7ee}
.bubble-demo{max-width:85%;padding:.45rem .65rem;border-radius:14px;font-size:.86rem;line-height:1.35;white-space:pre-wrap;
  animation:pop .25s ease-out}
.bubble-demo.in{align-self:flex-end;background:#effdde}
.bubble-demo.out{align-self:flex-start;background:#fff}
.bubble-demo small{display:block;font-size:.66rem;color:#6e6e73;margin-top:.2rem}
.demo-coach{background:#fff;border-radius:22px;box-shadow:0 8px 30px rgba(0,0,0,.08);padding:1rem 1.1rem}
.demo-coach h2{font-size:1.1rem;margin:0 0 .6rem}
.demo-coach h3{font-size:.8rem;text-transform:uppercase;letter-spacing:.05em;color:#6e6e73;margin:1rem 0 .3rem}
.case-cards{display:grid;grid-template-columns:1fr 1fr;gap:.6rem}
.case-card-demo{border:1px solid rgba(60,60,67,.14);border-radius:14px;padding:.6rem .75rem}
.case-card-demo strong{display:block}
.case-card-demo .state{font-size:.8rem;font-weight:700;color:#0a64d6}
.case-card-demo[data-state=needs_coach]{border-color:#c9281e;background:#fff5f4}
.case-card-demo[data-state=needs_coach] .state{color:#c9281e}
.case-card-demo[data-state=closed]{border-color:#1f8a3a;background:#f3fbf5}
.case-card-demo[data-state=closed] .state{color:#1f8a3a}
.case-card-demo .waiting{font-size:.78rem;color:#6e6e73}
#demo-timeline{max-height:27rem;overflow-y:auto}
.step-item{animation:pop .25s ease-out}
@keyframes pop{from{opacity:0;transform:translateY(4px)}to{opacity:1;transform:none}}
.demo-report{margin-top:1.25rem;background:#fff;border-radius:22px;padding:1.3rem 1.4rem;box-shadow:0 8px 30px rgba(0,0,0,.08)}
.demo-report h2{margin:.1rem 0 .8rem;font-size:1.5rem;letter-spacing:-.02em}
.report-grid{display:grid;grid-template-columns:repeat(auto-fit,minmax(11rem,1fr));gap:.6rem}
.report-grid div{border-radius:14px;background:#f2f2f7;padding:.7rem .8rem}
.report-grid b{display:block;font-size:1.6rem;letter-spacing:-.02em}
.report-grid span{font-size:.84rem;color:#48484a}
.report-actions{display:flex;flex-wrap:wrap;gap:.6rem;margin-top:1rem}
.demo-truth{margin-top:1.25rem}
.demo-truth table{width:100%;border-collapse:collapse;background:#fff;border-radius:16px;overflow:hidden}
.demo-truth th,.demo-truth td{padding:.6rem .75rem;text-align:left;border-top:1px solid rgba(60,60,67,.12);font-size:.9rem;vertical-align:top}
@media (max-width:860px){.demo-grid{grid-template-columns:1fr}.case-cards{grid-template-columns:1fr}}
@media (prefers-color-scheme:dark){body{background:#000}.demo-top{background:rgba(0,0,0,.8)}
 .phone,.demo-coach,.demo-report,.demo-truth table{background:#1c1c1e;color:#f2f2f7}
 .phone-body{background:#101418}.bubble-demo.out{background:#2c2c2e}.bubble-demo.in{background:#2b5278}
 .report-grid div{background:#2c2c2e}.report-grid span,.demo-intro p,.demo-legend li{color:#aeaeb2}
 .case-card-demo[data-state=needs_coach]{background:#3a1d1b}.case-card-demo[data-state=closed]{background:#16301d}}
"""


def _names(trace: dict) -> dict[str, str]:
    return {athlete["key"]: athlete["first"] for athlete in trace["athletes"]}


def render_steps_static(trace: dict) -> str:
    """Every step as a readable list, for simulations and for visitors without JavaScript."""
    names = _names(trace)
    items = []
    for step in trace["steps"]:
        if step["kind"] == "clock":
            continue
        who = f'<span class="step-who">{escape(names.get(step.get("athlete") or "", ""))}</span> · ' \
            if step.get("athlete") else ""
        body = f"<pre>{escape(step['body'])}</pre>" if step.get("body") else ""
        options = ""
        if step.get("detail", {}).get("options"):
            options = '<div class="step-options">' + "".join(
                f"<span>{escape(label)}</span>" for _, label in step["detail"]["options"]
            ) + "</div>"
        items.append(
            f'<li class="step-item {KIND_CLASS.get(step["kind"], "k-wait")}"><time>{escape(step["clock"] or "")}</time>'
            f'<div><span class="kind-chip">{escape(step["label"])}</span>'
            f'<p class="step-title">{who}{escape(step["title"])}</p>{body}{options}</div></li>'
        )
    return f'<ol class="step-list">{"".join(items)}</ol>'


def report_html(report: dict, *, heading: str) -> str:
    tiles = (
        (report["days_owned"], "training days owned from check-in to outcome"),
        (report["days_closed"], "days closed with a known outcome"),
        (report["checkins"], "check-ins sent on time"),
        (report["follow_ups"], "follow-ups to a silent athlete"),
        (report["sessions_autonomous"], "sessions delivered without the coach"),
        (report["escalations"], "exceptions escalated with evidence"),
        (report["coach_decisions"], "coach decisions, one tap each"),
        (report["autonomous_messages"], "messages written and sent by the agent alone"),
        (report["coach_typed_messages"], "messages typed by the coach"),
    )
    outcomes = "".join(
        f"<li><b>{escape(item['name'])}</b>: {escape(item['outcome'] or item['state'])}</li>"
        for item in report["outcomes"]
    )
    grid = "".join(f"<div><b>{value}</b><span>{escape(label)}</span></div>" for value, label in tiles)
    return f'<h2>{escape(heading)}</h2><div class="report-grid">{grid}</div><ul>{outcomes}</ul>'


def render_public_demo(trace: dict) -> str:
    athletes = trace["athletes"]
    phones = "".join(
        f'<div class="phone"><div class="phone-head"><span class="phone-avatar">{escape(a["first"][0])}</span>'
        f'<div><strong>{escape(a["name"])}</strong><small>Telegram · simulated · {escape(a["autopilot"])}</small></div></div>'
        f'<div class="phone-body" id="chat-{escape(a["key"])}" aria-live="polite" '
        f'aria-label="Conversation with {escape(a["first"])}"></div></div>'
        for a in athletes
    )
    cards = "".join(
        f'<div class="case-card-demo" id="case-{escape(a["key"])}" data-state="none">'
        f'<strong>{escape(a["name"])}</strong><span class="state">No case yet</span>'
        f'<div class="waiting">{escape(a["plan"])}</div></div>'
        for a in athletes
    )
    legend = "".join(
        f'<li class="{cls}"><span class="kind-chip">{escape(label)}</span> {escape(text)}</li>'
        for cls, label, text in LEGEND
    )
    trace_json = json.dumps(trace).replace("</", "<\\/")
    report = report_html(trace["report"], heading="Day complete: here is the work the agent did")
    return f"""<!doctype html>
<html lang="en"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>Watch the agent work · Power AI</title>
<meta name="color-scheme" content="light dark">
<link rel="icon" href="data:image/svg+xml,<svg xmlns=%22http://www.w3.org/2000/svg%22 viewBox=%220 0 100 100%22><text y=%22.9em%22 font-size=%2290%22>⚡</text></svg>">
<link rel="preconnect" href="https://fonts.googleapis.com">
<link href="https://fonts.googleapis.com/css2?family=Inter:opsz,wght@14..32,400..800&display=swap" rel="stylesheet">
<link rel="stylesheet" href="/static/tokens.css"><link rel="stylesheet" href="/static/app.css">
<style>{DEMO_STYLE}{PAGE_STYLE}</style></head>
<body>
<header class="demo-top"><a href="/">⚡ Power AI</a>
<span class="sim-pill">Fictional simulation · nothing is sent · no login</span>
<a href="/#how-it-works">How it works</a></header>
<main class="demo-wrap">
<section class="demo-intro">
  <h1>Watch the agent run a training day</h1>
  <p>Two fictional athletes, one Monday, about 90 seconds. The agent checks in, reads the replies,
  decides with fixed rules, acts on its own, follows up when someone goes quiet, hands an injury
  to the coach and closes both days only when it knows what happened.</p>
  <div class="demo-controls">
    <button id="demo-play" class="btn btn-mac-primary" type="button">▶ Play</button>
    <button id="demo-restart" class="btn btn-ghost" type="button">↺ Restart</button>
    <button id="demo-speed" class="btn btn-ghost" type="button">Speed 1×</button>
    <button id="demo-skip" class="btn btn-ghost" type="button">Skip to report</button>
    <span id="demo-clock" class="demo-clock" aria-live="polite">06:59</span>
    <div class="demo-progress" aria-hidden="true"><span id="demo-bar"></span></div>
  </div>
  <ul class="demo-legend">{legend}</ul>
</section>
<div class="demo-grid">
  <section class="demo-phones" aria-label="Athlete conversations">{phones}</section>
  <section class="demo-coach" aria-label="Coach console">
    <h2>Coach console · {escape(trace["coach"])}</h2>
    <div class="case-cards">{cards}</div>
    <h3>What the agent observed, decided and did</h3>
    <ol id="demo-timeline" class="step-list" aria-live="polite"></ol>
  </section>
</div>
<section id="demo-report" class="demo-report" hidden>
  {report}
  <div class="report-actions">
    <button id="demo-replay" class="btn btn-mac-primary" type="button">↺ Replay the day</button>
    <a class="btn btn-ghost" href="/#how-it-works">How the real agent works</a>
    <a class="btn btn-ghost" href="https://github.com/Shlok-K-ps/training-log-agent" target="_blank" rel="noopener">Source on GitHub ↗</a>
  </div>
</section>
<section class="demo-truth" id="demo-truth">
  <h2>Simulation or real agent?</h2>
  <table><thead><tr><th></th><th>This public demo</th><th>The real agent</th></tr></thead><tbody>
  <tr><td>Engine, rules, templates</td><td>The real ones</td><td>The same</td></tr>
  <tr><td>Athletes</td><td>Fictional, in a temporary in-memory SQLite database</td><td>The coach's invited athletes, in Neon Postgres</td></tr>
  <tr><td>Messages</td><td>Shown on this page only</td><td>Sent on Telegram</td></tr>
  <tr><td>Clock</td><td>A scripted Monday, compressed to about 90 seconds</td><td>Real time, woken by a recurring GitHub Actions tick</td></tr>
  <tr><td>Interpretation</td><td>Built-in offline parser, same data format</td><td>Gemini 2.5 Flash, restricted to six validated actions</td></tr>
  <tr><td>Coach decision</td><td>Scripted tap</td><td>The coach's own Telegram buttons</td></tr>
  </tbody></table>
</section>
<noscript><section class="demo-coach" style="margin-top:1rem"><h2>The whole day</h2>{render_steps_static(trace)}</section></noscript>
</main>
<script type="application/json" id="demo-trace">{trace_json}</script>
<script>
(() => {{
  const trace = JSON.parse(document.getElementById('demo-trace').textContent);
  const steps = trace.steps;
  const names = Object.fromEntries(trace.athletes.map(a => [a.key, a.first]));
  const kindClass = {json.dumps(KIND_CLASS)};
  // Weight the moments people need to read most heavily, then normalize the
  // whole walkthrough to a comfortable 90 seconds at 1x speed.
  const base = {{clock: 700, athlete: 1800, interpret: 2200, rule: 2200, action: 1800, wait: 800,
    observe: 800, escalation: 2800, coach: 3600, outcome: 2200, adapt: 2200}};
  const total = steps.reduce((sum, step) => sum + (base[step.kind] || 1000), 0);
  const scale = 90000 / total;
  const params = new URLSearchParams(location.search);
  let speed = Math.max(1, Number(params.get('speed')) || 1);
  let index = 0, timer = null, playing = false;
  const $ = (id) => document.getElementById(id);
  const playButton = $('demo-play'), timeline = $('demo-timeline');

  function el(tag, cls, text) {{
    const node = document.createElement(tag);
    if (cls) node.className = cls;
    if (text !== undefined) node.textContent = text;
    return node;
  }}
  function bubble(key, text, direction, meta) {{
    const box = $('chat-' + key);
    if (!box) return;
    const node = el('div', 'bubble-demo ' + direction, text);
    node.appendChild(el('small', '', meta));
    box.appendChild(node);
    box.scrollTop = box.scrollHeight;
  }}
  function render(step) {{
    if (step.kind === 'clock') {{ $('demo-clock').textContent = step.title; return; }}
    if (step.from_athlete) bubble(step.athlete, step.body, 'in', step.clock);
    if (step.to_athlete) bubble(step.athlete, step.body, 'out',
      step.clock + (step.authority === 'coach' ? ' · agent, after the coach decided' : ' · sent by the agent on its own'));
    const item = el('li', 'step-item ' + (kindClass[step.kind] || 'k-wait'));
    item.appendChild(el('time', '', step.clock || ''));
    const content = el('div');
    content.appendChild(el('span', 'kind-chip', step.label));
    const title = el('p', 'step-title');
    if (step.athlete) title.appendChild(el('span', 'step-who', names[step.athlete] + ' · '));
    title.appendChild(document.createTextNode(step.title));
    content.appendChild(title);
    if (step.body && !step.from_athlete) content.appendChild(el('pre', '', step.body));
    if (step.detail && step.detail.options && step.detail.options.length) {{
      const row = el('div', 'step-options');
      step.detail.options.forEach(([code, label]) => row.appendChild(el('span', '', label)));
      content.appendChild(row);
    }}
    if (step.kind === 'coach') {{
      const previous = [...timeline.querySelectorAll('.step-options span')];
      previous.forEach(span => {{ if (step.title.includes(span.textContent)) span.classList.add('chosen'); }});
    }}
    item.appendChild(content);
    timeline.appendChild(item);
    timeline.scrollTop = timeline.scrollHeight;
    if (step.cases) {{
      Object.entries(step.cases).forEach(([key, info]) => {{
        const card = $('case-' + key);
        if (!card) return;
        card.dataset.state = info.state_code;
        card.querySelector('.state').textContent = info.outcome ? info.state + ' · ' + info.outcome : info.state;
        card.querySelector('.waiting').textContent = info.waiting || (info.state_code === 'closed' ? 'Outcome known' : '');
      }});
    }}
  }}
  function progress() {{ $('demo-bar').style.width = (100 * index / steps.length) + '%'; }}
  function finish() {{
    playing = false; clearTimeout(timer);
    playButton.textContent = '▶ Play'; playButton.disabled = true;
    $('demo-report').hidden = false;
    document.body.dataset.demoState = 'finished';
    $('demo-report').scrollIntoView({{behavior: speed > 5 ? 'auto' : 'smooth', block: 'start'}});
  }}
  function next() {{
    if (!playing) return;
    if (index >= steps.length) {{ finish(); return; }}
    const step = steps[index++];
    render(step); progress();
    timer = setTimeout(next, (base[step.kind] || 1000) * scale / speed);
  }}
  function play() {{
    if (index >= steps.length) return;
    playing = true; playButton.textContent = '❚❚ Pause';
    document.body.dataset.demoState = 'playing';
    next();
  }}
  function pause() {{ playing = false; clearTimeout(timer); playButton.textContent = '▶ Play'; document.body.dataset.demoState = 'paused'; }}
  function reset() {{
    pause(); index = 0; progress();
    timeline.replaceChildren();
    document.querySelectorAll('.phone-body').forEach(box => box.replaceChildren());
    trace.athletes.forEach(a => {{
      const card = $('case-' + a.key);
      card.dataset.state = 'none';
      card.querySelector('.state').textContent = 'No case yet';
      card.querySelector('.waiting').textContent = a.plan;
    }});
    $('demo-clock').textContent = '06:59';
    $('demo-report').hidden = true; playButton.disabled = false;
    document.body.dataset.demoState = 'ready';
  }}
  function skip() {{ pause(); while (index < steps.length) {{ render(steps[index++]); }} progress(); finish(); }}
  function setSpeed(value) {{ speed = value; $('demo-speed').textContent = 'Speed ' + value + '×'; }}

  playButton.addEventListener('click', () => (playing ? pause() : play()));
  $('demo-restart').addEventListener('click', () => {{ reset(); play(); }});
  $('demo-replay').addEventListener('click', () => {{ reset(); window.scrollTo({{top: 0}}); play(); }});
  $('demo-skip').addEventListener('click', skip);
  $('demo-speed').addEventListener('click', () => setSpeed(speed >= 4 ? 1 : speed * 2));
  setSpeed(speed);
  document.body.dataset.demoState = 'ready';
  window.powerDemo = {{ play, pause, reset, skip, setSpeed, get index() {{ return index; }}, total: steps.length }};
  if (params.get('autoplay') !== '0') setTimeout(play, 600);
}})();
</script>
</body></html>"""

"""Getting a coach from an empty console to a working agent without learning its internals.

Setup is a checklist detected from stored state, registration asks only for a
name and usual times, and every athlete page opens with plain answers: is
Telegram connected, is there a plan, is autopilot on, what happens next and
what is in the way.
"""

from __future__ import annotations

from datetime import date
from html import escape
from urllib.parse import quote

from app.casework.status import AthleteStatus
from app.coach.demo_view import DEMO_STYLE, render_steps_static, report_html
from app.coach.view import banner, coach_frame

TIMEZONES = (
    ("Asia/Kolkata", "India (Asia/Kolkata)"),
    ("Asia/Dubai", "Gulf (Asia/Dubai)"),
    ("Asia/Singapore", "Singapore (Asia/Singapore)"),
    ("Australia/Sydney", "Sydney (Australia/Sydney)"),
    ("Europe/London", "UK (Europe/London)"),
    ("Europe/Berlin", "Central Europe (Europe/Berlin)"),
    ("Africa/Johannesburg", "South Africa (Africa/Johannesburg)"),
    ("America/New_York", "US Eastern (America/New_York)"),
    ("America/Chicago", "US Central (America/Chicago)"),
    ("America/Denver", "US Mountain (America/Denver)"),
    ("America/Los_Angeles", "US Pacific (America/Los_Angeles)"),
    ("UTC", "UTC"),
)

ONBOARDING_STYLE = """
.setup-card,.empty-hero,.agent-status,.invite-card,.new-athlete{background:var(--card,#fff);border-radius:22px;
  padding:1.2rem 1.3rem;margin:0 0 1rem;box-shadow:0 1px 0 rgba(0,0,0,.04),0 8px 24px rgba(0,0,0,.05)}
.setup-eyebrow{font-size:.74rem;font-weight:700;letter-spacing:.05em;text-transform:uppercase;color:#0a64d6}
.setup-card h2,.empty-hero h2,.agent-status h2,.invite-card h2,.new-athlete h2{margin:.15rem 0 .35rem;letter-spacing:-.02em}
.setup-head{display:flex;justify-content:space-between;gap:1rem;align-items:flex-end;flex-wrap:wrap}
.setup-meter{flex:0 0 10rem;height:8px;border-radius:999px;background:rgba(118,118,128,.18);overflow:hidden}
.setup-meter span{display:block;height:100%;background:#34c759}
.setup-steps{list-style:none;margin:.8rem 0 0;padding:0}
.setup-step{display:grid;grid-template-columns:2rem 1fr auto;gap:.75rem;align-items:center;padding:.65rem 0;
  border-top:1px solid rgba(60,60,67,.12)}
.setup-step p{margin:.1rem 0 0;font-size:.88rem;color:var(--secondary-label,#6e6e73)}
.setup-mark{width:1.8rem;height:1.8rem;border-radius:50%;display:grid;place-items:center;font-weight:700;
  background:rgba(118,118,128,.14);color:#48484a}
.setup-step.done .setup-mark{background:#34c759;color:#fff}
.setup-step.done strong{color:var(--secondary-label,#6e6e73)}
.setup-foot{margin:.7rem 0 0;font-size:.88rem}
.empty-hero{text-align:center;padding:2.2rem 1.4rem}
.empty-hero p{font-size:1.08rem;max-width:36rem;margin:.4rem auto}
.empty-actions{display:flex;flex-wrap:wrap;gap:.7rem;justify-content:center;margin:1.1rem 0 .6rem}
.empty-note{font-size:.85rem;color:var(--secondary-label,#6e6e73)}
.status-head{display:flex;justify-content:space-between;align-items:center;gap:.8rem;flex-wrap:wrap}
.status-badge{font-size:.8rem;font-weight:700;border-radius:999px;padding:.25rem .75rem;background:rgba(255,149,0,.16);color:#9a5b00}
.status-badge.ready{background:rgba(52,199,89,.16);color:#1f8a3a}
.status-badge.blocked{background:rgba(255,59,48,.14);color:#c9281e}
.status-grid{display:grid;grid-template-columns:repeat(auto-fit,minmax(11rem,1fr));gap:.6rem;margin:.8rem 0}
.status-grid div{border-radius:14px;background:rgba(118,118,128,.08);padding:.6rem .75rem}
.status-grid dt{font-size:.74rem;text-transform:uppercase;letter-spacing:.04em;color:var(--secondary-label,#6e6e73)}
.status-grid dd{margin:.15rem 0 0;font-weight:600}
.status-grid dd.no{color:#c9281e}.status-grid dd.yes{color:#1f8a3a}
.status-blockers{margin:.2rem 0 .7rem;padding:.6rem .9rem .6rem 1.9rem;border-radius:14px;background:#fff5f4;color:#8f1d15}
.status-notes{margin:.2rem 0 .7rem;padding-left:1.1rem;font-size:.9rem;color:var(--secondary-label,#48484a)}
.status-actions{display:flex;flex-wrap:wrap;gap:.5rem;align-items:center}
.status-actions form{margin:0}
.btn-disabled{opacity:.5;pointer-events:none}
.invite-card.welcome{border:2px solid #0a64d6}
.invite-steps{margin:.4rem 0 .9rem;padding-left:1.2rem;line-height:1.6}
.invite-actions{display:flex;flex-wrap:wrap;gap:.6rem;align-items:center}
.invite-link{width:100%;margin:.7rem 0 .3rem;font-size:.82rem;padding:.45rem .6rem;border-radius:10px;
  border:1px solid rgba(60,60,67,.2);background:rgba(118,118,128,.06)}
.invite-status{font-weight:600;margin:.4rem 0}
.invite-status.connected{color:#1f8a3a}
.new-athlete form{display:grid;gap:.9rem;max-width:34rem}
.new-athlete label{display:flex;flex-direction:column;gap:.3rem;font-weight:600}
.new-athlete input,.new-athlete select{font:inherit;padding:.55rem .65rem;border-radius:12px;border:1px solid rgba(60,60,67,.25)}
.new-athlete .times{display:grid;grid-template-columns:1fr 1fr;gap:.8rem}
.new-athlete details{border-top:1px solid rgba(60,60,67,.12);padding-top:.6rem}
.new-athlete .onboarding-grid{display:grid;grid-template-columns:repeat(auto-fit,minmax(12rem,1fr));gap:.7rem;margin-top:.7rem}
.new-athlete .hint{font-weight:400;font-size:.86rem;color:var(--secondary-label,#6e6e73)}
.advanced{margin:1rem 0;border-radius:16px;padding:.7rem 1rem;background:rgba(118,118,128,.06)}
.advanced summary{cursor:pointer;font-weight:600}
.sim-note{border-radius:16px;padding:.8rem 1rem;background:#fff8e1;color:#5f4300;margin-bottom:1rem}
.report-grid{display:grid;grid-template-columns:repeat(auto-fit,minmax(11rem,1fr));gap:.6rem}
.report-grid div{border-radius:14px;background:rgba(118,118,128,.08);padding:.7rem .8rem}
.report-grid b{display:block;font-size:1.5rem}
.report-grid span{font-size:.84rem;color:var(--secondary-label,#48484a)}
@media (max-width:640px){.setup-step{grid-template-columns:2rem 1fr}.setup-step .btn{grid-column:2}}
""" + DEMO_STYLE

COPY_SCRIPT = """<script>
document.querySelectorAll('[data-copy]').forEach((button) => {
  button.addEventListener('click', async () => {
    const text = button.dataset.copy;
    window.__powerCopied = text;
    let copied = false;
    try { await navigator.clipboard.writeText(text); copied = true; } catch (error) {
      const field = document.createElement('textarea');
      field.value = text; document.body.appendChild(field); field.select();
      try { copied = document.execCommand('copy'); } catch (ignored) {}
      field.remove();
    }
    const label = button.dataset.label || button.textContent;
    button.dataset.label = label;
    button.textContent = copied ? 'Copied ✓ Now send it to the athlete' : 'Select the link below and copy it';
    setTimeout(() => { button.textContent = label; }, 4000);
  });
});
</script>"""


def setup_checklist(steps: list[dict], *, compact: bool = True) -> str:
    done = sum(1 for step in steps if step["done"])
    if compact and done == len(steps):
        return ""
    first_open = next((index for index, step in enumerate(steps) if not step["done"]), None)
    items = []
    for index, step in enumerate(steps):
        button = "" if step["done"] else (
            f'<a class="btn {"btn-primary" if index == first_open else "btn-ghost"} btn-sm" '
            f'href="{escape(step["href"])}" data-step="{escape(step["key"])}">{escape(step["action"])}</a>'
        )
        items.append(
            f'<li class="setup-step {"done" if step["done"] else "todo"}" data-step-state="{escape(step["key"])}:'
            f'{"done" if step["done"] else "todo"}"><span class="setup-mark">{"✓" if step["done"] else index + 1}</span>'
            f'<div><strong>{escape(step["label"])}</strong><p>{escape(step["detail"])}</p></div>{button}</li>'
        )
    percent = round(100 * done / len(steps))
    return (
        '<section class="setup-card" id="setup">'
        f'<div class="setup-head"><div><span class="setup-eyebrow">{done} of {len(steps)} done</span>'
        '<h2>Set up your agent</h2><p>Each step unlocks the next. Everything is detected automatically.</p></div>'
        f'<div class="setup-meter" aria-hidden="true"><span style="width:{percent}%"></span></div></div>'
        f'<ol class="setup-steps">{"".join(items)}</ol>'
        '<p class="setup-foot">Want to see what it does first? <a href="/demo">Watch the safe demo</a>. '
        "It is fictional and never touches this console.</p></section>"
    )


def empty_state() -> str:
    return (
        '<section class="empty-hero" id="empty-console">'
        '<span class="setup-eyebrow">Nothing is running yet</span>'
        '<h2>Welcome to your coach console</h2>'
        "<p>This is your private real-agent console. Start by inviting an athlete, or watch the fictional demo first.</p>"
        '<div class="empty-actions">'
        '<a class="btn btn-primary btn-lg" href="/coach/athletes/new">Set up a real athlete</a>'
        '<a class="btn btn-ghost btn-lg" href="/demo">Watch the safe demo</a></div>'
        '<p class="empty-note">The demo is a self-contained simulation with fictional athletes. It sends nothing '
        "and never reads or changes this console's data.</p></section>"
    )


def setup_page(
    steps: list[dict], *, coach: str, today: date, pending_count: int, bot_username: str,
    telegram_available: bool, message: tuple[str, str] | None,
) -> str:
    coach_linked = next(step["done"] for step in steps if step["key"] == "coach")
    bot = bot_username.lstrip("@")
    if coach_linked:
        telegram = "<p><b>Linked.</b> Escalations reach your Telegram with one-tap decision buttons. " \
            "Send <b>/console</b> to the bot whenever you need a fresh console link.</p>"
    elif telegram_available and bot:
        telegram = (
            "<ol class='invite-steps'>"
            f"<li>On your phone, open Telegram and start a chat with <a href='https://t.me/{escape(quote(bot))}' "
            f"target='_blank' rel='noopener'>@{escape(bot)}</a>.</li>"
            "<li>Send <b>/coach</b> followed by your setup code. The code is the <code>COACH_SETUP_CODE</code> "
            "value in your hosting settings.</li>"
            "<li>The bot replies <b>Linked</b> and sends a console link. This step then turns green.</li></ol>"
        )
    else:
        telegram = (
            "<p>The Telegram bot is not configured on this deployment yet. Create a bot with @BotFather, then set "
            "<code>TELEGRAM_BOT_TOKEN</code>, <code>TELEGRAM_BOT_USERNAME</code>, <code>TELEGRAM_WEBHOOK_SECRET</code>, "
            "<code>TELEGRAM_LINK_SECRET</code> and <code>PUBLIC_BASE_URL</code>, and redeploy.</p>"
        )
    body = (
        f"{banner(message)}{setup_checklist(steps, compact=False)}"
        '<section class="setup-card" id="coach-telegram"><span class="setup-eyebrow">Step 1</span>'
        f"<h2>Link your own Telegram</h2>{telegram}</section>"
    )
    return coach_frame(
        body, active="overview", coach=coach, title="Set up your agent",
        subtitle="Six steps from an empty console to a training day the agent runs on its own.",
        today=today.isoformat(), pending_count=pending_count, extra_style=ONBOARDING_STYLE,
        back=("/coach", "Today"),
    )


def new_athlete_page(*, coach: str, today: date, pending_count: int, message: tuple[str, str] | None) -> str:
    zones = "".join(f'<option value="{escape(value)}">{escape(label)}</option>' for value, label in TIMEZONES)
    earliest_goal = today.isoformat()
    latest_goal = date(today.year + 10, 12, 31).isoformat()
    body = f"""{banner(message)}
<section class="new-athlete">
<span class="setup-eyebrow">Add an athlete</span>
<h2>Who will the agent look after?</h2>
<p class="hint">Four details. You'll get a Telegram invite to send them straight after.</p>
<form method="post" action="/coach/athletes/register">
  <label>Athlete name<input type="text" name="name" required maxlength="60" autocomplete="off" placeholder="e.g. Priya Nair"></label>
  <label>Timezone<select name="timezone" id="athlete-timezone" required>{zones}</select>
    <span class="hint">The agent checks in at their local time.</span></label>
  <div class="times">
    <label>Usual check-in<input type="time" name="checkin_time" value="07:30" required></label>
    <label>Usual training<input type="time" name="training_time" value="18:00" required></label>
  </div>
  <details><summary>Optional coaching details</summary>
    <div class="onboarding-grid">
      <label>Bodyweight (kg)<input type="number" name="bodyweight_kg" min="30" max="400" step="0.1"></label>
      <label>Squat 1RM (kg)<input type="number" name="squat_1rm_kg" min="1" max="600" step="0.5"></label>
      <label>Bench 1RM (kg)<input type="number" name="bench_1rm_kg" min="1" max="400" step="0.5"></label>
      <label>Deadlift 1RM (kg)<input type="number" name="deadlift_1rm_kg" min="1" max="600" step="0.5"></label>
      <label>Training days / week<input type="number" name="training_days" min="1" max="7"></label>
      <label>Experience<select name="experience"><option value="">Not set</option><option value="novice">Novice</option><option value="intermediate">Intermediate</option><option value="advanced">Advanced</option></select></label>
      <label>Goal lift<select name="goal_lift"><option value="">No numeric goal yet</option><option value="squat">Squat</option><option value="bench press">Bench press</option><option value="deadlift">Deadlift</option></select></label>
      <label>Goal 1RM (kg)<input type="number" name="goal_target_kg" min="1" max="700" step="0.5"></label>
      <label>Goal / meet date<span class="calendar-control">
        <input id="goal-target-date" type="date" name="goal_target_date" min="{earliest_goal}" max="{latest_goal}" aria-label="Goal or meet date">
        <button class="calendar-trigger" type="button"
          onclick="const field=document.getElementById('goal-target-date'); if(field.showPicker){{field.showPicker();}} else {{field.focus();}}">Choose date</button>
      </span></label>
      <label>Current injury or restriction<input type="text" name="injury_note" maxlength="240" placeholder="Leave blank if none"></label>
    </div>
  </details>
  <button class="btn btn-primary btn-lg" type="submit">Add athlete and create Telegram invite</button>
</form>
</section>
<script>
(() => {{
  const select = document.getElementById('athlete-timezone');
  let zone = '';
  try {{ zone = Intl.DateTimeFormat().resolvedOptions().timeZone || ''; }} catch (error) {{}}
  if (!zone) return;
  const aliases = {{'Asia/Calcutta': 'Asia/Kolkata', 'Asia/Saigon': 'Asia/Ho_Chi_Minh',
    'Asia/Katmandu': 'Asia/Kathmandu', 'Europe/Kiev': 'Europe/Kyiv', 'US/Eastern': 'America/New_York',
    'US/Central': 'America/Chicago', 'US/Mountain': 'America/Denver', 'US/Pacific': 'America/Los_Angeles'}};
  zone = aliases[zone] || zone;
  if (![...select.options].some(option => option.value === zone)) select.add(new Option(zone + ' (this device)', zone), 0);
  select.value = zone;
}})();
</script>"""
    return coach_frame(
        body, active="athletes", coach=coach, title="Add an athlete",
        subtitle="Name and usual times. The agent handles the rest.",
        today=today.isoformat(), pending_count=pending_count, extra_style=ONBOARDING_STYLE,
        back=("/coach/athletes", "Athletes"),
    )


def athlete_status_header(status: AthleteStatus, *, next_step: tuple[str, str], simulate_href: str) -> str:
    quoted = escape(quote(status.athlete_id))
    if status.blockers:
        badge = '<span class="status-badge blocked">Blocked</span>'
    elif status.ready:
        badge = '<span class="status-badge ready">Ready</span>'
    else:
        badge = '<span class="status-badge">Needs setup</span>'
    if status.demo:
        telegram = ("Simulator (demo athlete)", "yes")
    elif status.telegram_connected:
        telegram = ("Connected", "yes")
    else:
        telegram = ("Not connected", "no")
    plan = (f"{', '.join(status.plan_days)} · {len(status.plan)} lift{'s' if len(status.plan) != 1 else ''}", "yes") \
        if status.plan else ("Not configured", "no")
    autopilot = ("On", "yes") if status.autopilot_decided and status.autopilot else (
        ("Off, sessions wait for you", "") if status.autopilot_decided else ("Not decided", "no"))
    blocking = (f"{len(status.blockers)} item{'s' if len(status.blockers) != 1 else ''}", "no") \
        if status.blockers else ("Nothing", "yes")
    rows = (
        ("Telegram", telegram), ("Training plan", plan), ("Autopilot", autopilot),
        ("Next action", (status.next_action, "")), ("Blocking", blocking),
    )
    grid = "".join(
        f'<div><dt>{escape(label)}</dt><dd class="{cls}" data-status="{escape(label.lower().replace(" ", "-"))}">'
        f"{escape(value)}</dd></div>"
        for label, (value, cls) in rows
    )
    blockers = (
        '<ul class="status-blockers">' + "".join(f"<li>{escape(item)}</li>" for item in status.blockers) + "</ul>"
        if status.blockers else ""
    )
    notes = (
        '<ul class="status-notes">' + "".join(f"<li>{escape(item)}</li>" for item in status.notes) + "</ul>"
        if status.notes else ""
    )

    def button(label: str, href: str) -> str:
        primary = label == next_step[0]
        return f'<a class="btn {"btn-primary" if primary else "btn-ghost"} btn-sm" href="{escape(href)}">{escape(label)}</a>'

    actions = []
    if not status.demo:
        actions.append(button("Invite on Telegram", "#telegram") if not status.telegram_connected
                       else button("Reconnect on Telegram", "#advanced"))
    actions.append(button("Add a training plan" if not status.plan else "Add today's plan", "#agent-plan"))
    if status.autopilot_decided:
        actions.append(
            f'<form method="post" action="/coach/athlete/{quoted}/autopilot">'
            f'<input type="hidden" name="enabled" value="{"off" if status.autopilot else "on"}">'
            f'<button class="btn btn-ghost btn-sm" type="submit">{"Disable autopilot" if status.autopilot else "Enable autopilot"}</button></form>'
        )
    elif status.plan:
        primary = next_step[0] == "Decide on autopilot"
        actions.append(
            f'<form method="post" action="/coach/athlete/{quoted}/autopilot"><input type="hidden" name="enabled" value="on">'
            f'<button class="btn {"btn-primary" if primary else "btn-ghost"} btn-sm" type="submit">Enable autopilot</button></form>'
            f'<form method="post" action="/coach/athlete/{quoted}/autopilot"><input type="hidden" name="enabled" value="off">'
            '<button class="btn btn-ghost btn-sm" type="submit">Keep autopilot off</button></form>'
        )
    actions.append(
        button("Run a safe simulated test", simulate_href) if status.plan
        else '<span class="btn btn-ghost btn-sm btn-disabled" title="Add a plan first">Run a safe simulated test</span>'
    )
    if status.waiting_case_id or status.latest_case_id:
        actions.append(button("View the agent's timeline", f"/coach/case/{status.waiting_case_id or status.latest_case_id}"))
    else:
        actions.append('<span class="btn btn-ghost btn-sm btn-disabled" title="No training days yet">View the agent\'s timeline</span>')
    return (
        f'<section class="agent-status" id="agent-status" data-ready="{"yes" if status.ready else "no"}">'
        f'<div class="status-head"><h2>Agent status</h2>{badge}</div>'
        f'<dl class="status-grid">{grid}</dl>{blockers}{notes}'
        f'<div class="status-actions">{"".join(actions)}</div></section>'
    )


def invite_section(
    status: AthleteStatus, *, pairing_url: str | None, telegram_ready: bool, welcome: bool,
    next_step: tuple[str, str],
) -> str:
    first = escape(status.first_name)
    if status.demo:
        return ""
    added = f'<span class="setup-eyebrow">{escape(status.name)} added</span>' if welcome else \
        '<span class="setup-eyebrow">Athlete channel</span>'
    if status.telegram_connected:
        return (
            f'<section id="telegram" class="invite-card connected">{added}<h2>Telegram connected</h2>'
            f"<p>{first} receives the agent's messages in their private Telegram chat.</p>"
            f'<p class="invite-next">Next: <a href="{escape(next_step[1])}">{escape(next_step[0])}</a></p></section>'
        )
    poll = f"""<script>
(() => {{
  const status = document.querySelector('[data-telegram-status]');
  const next = document.querySelector('[data-next-step]');
  if (!status) return;
  const timer = setInterval(async () => {{
    try {{
      const response = await fetch('/coach/athlete/{escape(quote(status.athlete_id))}/status.json', {{credentials: 'same-origin'}});
      if (!response.ok) return;
      const data = await response.json();
      if (!data.telegram_connected) return;
      clearInterval(timer);
      status.textContent = 'Connected ✓ {first} can now receive the agent\\'s messages.';
      status.classList.add('connected');
      next.querySelector('a').textContent = data.next_step.label;
      next.querySelector('a').href = data.next_step.href;
      next.hidden = false;
    }} catch (error) {{}}
  }}, 4000);
}})();
</script>"""
    if not pairing_url:
        return (
            f'<section id="telegram" class="invite-card{" welcome" if welcome else ""}">{added}'
            "<h2>Telegram isn't set up on this deployment</h2>"
            f"<p>The agent reaches athletes on Telegram, so {first} can't be invited until the bot is configured "
            "(<code>TELEGRAM_BOT_TOKEN</code>, <code>TELEGRAM_BOT_USERNAME</code>, <code>TELEGRAM_WEBHOOK_SECRET</code>, "
            "<code>TELEGRAM_LINK_SECRET</code>, <code>PUBLIC_BASE_URL</code>).</p>"
            f'<p class="invite-status">Telegram: not connected</p>'
            f'<p class="invite-next">Meanwhile: <a href="{escape(next_step[1])}">{escape(next_step[0])}</a></p></section>'
        )
    warning = "" if telegram_ready else (
        '<p class="msg warn">The Telegram webhook has not been verified yet. The invite may not connect until it is.</p>'
    )
    return (
        f'<section id="telegram" class="invite-card{" welcome" if welcome else ""}">{added}'
        "<h2>Connect this athlete to Telegram</h2>"
        "<ol class='invite-steps'>"
        f"<li>Copy the invite and send it to {first} however you normally message them.</li>"
        f"<li>{first} taps it, Telegram opens, and they press <b>Start</b>.</li>"
        f"<li>This page shows <b>Connected</b> as soon as they do. The link only works for {first}.</li></ol>"
        '<div class="invite-actions">'
        f'<button type="button" class="btn btn-primary btn-lg" data-copy="{escape(pairing_url)}">Copy Telegram invite</button>'
        f'<a class="btn btn-ghost" href="{escape(pairing_url)}" target="_blank" rel="noopener">Connect Telegram</a></div>'
        f'<input class="invite-link" readonly value="{escape(pairing_url)}" aria-label="Telegram invite link" onfocus="this.select()">'
        f'{warning}<p class="invite-status" data-telegram-status>Waiting for {first} to press Start…</p>'
        f'<p class="invite-next" data-next-step hidden>Next: <a href="{escape(next_step[1])}">{escape(next_step[0])}</a></p>'
        f"</section>{COPY_SCRIPT}{poll}"
    )


def advanced_section(athlete_id: str, *, telegram_connected: bool) -> str:
    unlink = (
        f'<form method="post" action="/coach/athlete/{escape(quote(athlete_id))}/telegram/unlink">'
        "<p>Disconnecting lets you send a fresh invite, for example after the athlete changes phone.</p>"
        '<button class="danger" type="submit">Disconnect Telegram</button></form>'
        if telegram_connected else ""
    )
    return (
        '<details class="advanced" id="advanced"><summary>Advanced settings and identifiers</summary>'
        f"<p>Internal athlete ID: <code>{escape(athlete_id)}</code>. You never need to enter it anywhere.</p>"
        f"{unlink}</details>"
    )


def simulate_page(
    trace: dict | None, status: AthleteStatus, *, coach: str, today: date, pending_count: int
) -> str:
    first = escape(status.first_name)
    back = (status.url, status.name or "Athlete")
    if trace is None:
        body = (
            '<section class="setup-card"><h2>Add a training plan first</h2>'
            f"<p>The simulation replays {first}'s next planned day, so it needs at least one planned lift.</p>"
            f'<a class="btn btn-primary" href="{escape(status.url)}#agent-plan">Add a training plan</a></section>'
        )
    else:
        messages = "".join(
            f'<div class="bubble-demo {"in" if step.get("from_athlete") else "out"}" '
            'style="max-width:34rem;margin:.3rem 0;padding:.5rem .7rem;border-radius:14px;'
            f'background:{"#effdde" if step.get("from_athlete") else "rgba(118,118,128,.1)"};white-space:pre-wrap">'
            f'{escape(step["body"])}<small style="display:block;color:#6e6e73">{escape(step["clock"] or "")} · '
            f'{"sample reply from " + first if step.get("from_athlete") else "would be sent by the agent"}</small></div>'
            for step in trace["steps"] if step.get("from_athlete") or step.get("to_athlete")
        )
        body = (
            f'<div class="sim-note"><b>Safe simulated test. Nothing was sent and nothing was saved.</b> '
            f"This plays {first}'s next planned day ({escape(trace['day'].replace(' (fictional)', ''))}) through the real "
            "agent in a throwaway database, using their current plan, schedule, autopilot and injury state and a sample "
            "reply. Any coach decision is simulated so the day can finish.</div>"
            f'<section class="setup-card">{report_html(trace["report"], heading="What the agent would do")}</section>'
            f'<section class="setup-card"><h2>{first}\'s conversation</h2>{messages or "<p>No messages.</p>"}</section>'
            f'<section class="setup-card"><h2>Reasoning and actions</h2>{render_steps_static(trace)}</section>'
        )
    return coach_frame(
        body, active="athletes", coach=coach, title=f"Simulated test · {status.name}",
        subtitle="What the agent would do on this athlete's next training day.",
        today=today.isoformat(), pending_count=pending_count, extra_style=ONBOARDING_STYLE,
        athlete_id=status.athlete_id, back=back,
    )

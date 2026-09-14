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

from app.casework.status import WAITING_FOR_DECISION, AthleteStatus
from app.coach.demo_view import DEMO_STYLE, render_steps_static, report_html
from app.coach.view import banner, coach_frame

# Pairing outcomes that mean the athlete tried to connect and it did not work.
PAIRING_FAILURE_OUTCOMES = frozenset({"link_replaced", "athlete_connected_elsewhere", "chat_connected_elsewhere"})

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
.setup-card,.empty-hero,.agent-status,.invite-card,.new-athlete{background:var(--card);border-radius:var(--r-xl);
  padding:1.2rem 1.3rem;margin:0;box-shadow:var(--shadow-card)}
.setup-card,.empty-hero,.new-athlete{margin:0 0 1rem}
.setup-eyebrow{font-size:.74rem;font-weight:700;letter-spacing:.05em;text-transform:uppercase;color:var(--tint-text)}
.setup-card h2,.empty-hero h2,.agent-status h2,.invite-card h2,.new-athlete h2{margin:.15rem 0 .35rem;letter-spacing:-.02em}
.setup-head{display:flex;justify-content:space-between;gap:1rem;align-items:flex-end;flex-wrap:wrap}
.setup-meter{flex:0 0 10rem;height:8px;border-radius:999px;background:var(--fill-strong);overflow:hidden}
.setup-meter span{display:block;height:100%;background:var(--green)}
.setup-steps{list-style:none;margin:.8rem 0 0;padding:0}
.setup-step{display:grid;grid-template-columns:2rem 1fr auto;gap:.75rem;align-items:center;padding:.65rem 0;
  border-top:1px solid var(--separator)}
.setup-step p{margin:.1rem 0 0;font-size:.88rem;color:var(--text-2)}
.setup-mark{width:1.8rem;height:1.8rem;border-radius:50%;display:grid;place-items:center;font-weight:700;
  background:var(--fill-strong);color:var(--text)}
.setup-step.done .setup-mark{background:var(--green);color:#fff}
.setup-step.done strong{color:var(--text-2)}
.setup-foot{margin:.7rem 0 0;font-size:.88rem}
.empty-hero{text-align:center;padding:2.2rem 1.4rem}
.empty-hero p{font-size:1.08rem;max-width:36rem;margin:.4rem auto}
.empty-actions{display:flex;flex-wrap:wrap;gap:.7rem;justify-content:center;margin:1.1rem 0 .6rem}
.empty-note{font-size:.85rem;color:var(--text-2)}
.status-head{display:flex;justify-content:space-between;align-items:flex-start;gap:.8rem;flex-wrap:wrap}
.status-badge{display:inline-block;font-size:.8rem;font-weight:700;border-radius:999px;padding:.25rem .75rem;
  background:var(--orange-soft);color:var(--orange-text);white-space:nowrap}
.status-badge.ready{background:var(--green-soft);color:var(--green-text)}
.status-badge.blocked{background:var(--red-soft);color:var(--red-text)}
.status-badge.waiting{background:var(--tint-soft);color:var(--tint-text)}
.status-badge.off{background:var(--fill);color:var(--text-2)}
.status-blockers{margin:.8rem 0 0;padding:.6rem .9rem .6rem 1.9rem;border-radius:var(--r-md);background:var(--red-soft);color:var(--red-text)}
.status-notes{margin:.6rem 0 0;padding-left:1.1rem;font-size:.9rem;color:var(--text-2)}
.status-actions{display:flex;flex-wrap:wrap;gap:.5rem;align-items:center}
.status-actions form{margin:0}
.status-idle{margin:.8rem 0 0}
.stepper{list-style:none;display:grid;grid-template-columns:repeat(4,minmax(0,1fr));gap:.6rem;margin:.9rem 0 0;padding:0}
.stepper-step{display:grid;grid-template-columns:1.75rem minmax(0,1fr);gap:.6rem;align-items:start;padding:.7rem .75rem;
  border-radius:var(--r-md);background:var(--fill-2);border:1px solid transparent;min-width:0}
.stepper-step strong{display:block;font-size:.9rem;line-height:1.3}
.stepper-step [data-status]{display:block;margin-top:.1rem;font-size:.84rem;color:var(--text-2);overflow-wrap:anywhere}
.stepper-mark{width:1.75rem;height:1.75rem;border-radius:50%;display:grid;place-items:center;font-size:.8rem;font-weight:700;
  background:var(--fill-strong);color:var(--text)}
.stepper-step.is-done .stepper-mark{background:var(--green);color:#fff}
.stepper-step.is-done [data-status]{color:var(--green-text)}
.stepper-step.is-current{background:var(--tint-soft);border-color:var(--tint)}
.stepper-step.is-current .stepper-mark{background:var(--tint);color:#fff}
.stepper-step.is-current [data-status]{color:var(--text)}
.stepper-step.is-blocked{background:var(--red-soft);border-color:var(--red)}
.stepper-step.is-blocked .stepper-mark{background:var(--red);color:#fff}
.stepper-step.is-blocked [data-status]{color:var(--red-text)}
.stepper-step.is-todo strong{color:var(--text-2)}
.status-next{display:flex;flex-wrap:wrap;justify-content:space-between;align-items:center;gap:.8rem;margin-top:.9rem;
  padding-top:.9rem;border-top:1px solid var(--separator)}
.status-next .k{font-size:.74rem;font-weight:700;text-transform:uppercase;letter-spacing:.04em;color:var(--text-2)}
.status-next p{margin:.1rem 0 0;font-weight:600}
.invite-card.welcome{box-shadow:0 0 0 2px var(--tint),var(--shadow-card)}
.invite-head{display:flex;justify-content:space-between;gap:.8rem;align-items:flex-start;flex-wrap:wrap}
.invite-steps{margin:.6rem 0 .9rem;padding-left:1.3rem;line-height:1.55}
.invite-steps li{margin:.25rem 0}
.invite-callouts{display:grid;grid-template-columns:repeat(2,minmax(0,1fr));gap:.6rem;margin:0 0 1rem}
.invite-note,.invite-warning{margin:0;padding:.65rem .8rem;border-radius:var(--r-md);font-size:.9rem;line-height:1.45;color:var(--text)}
.invite-note{background:var(--tint-soft)}
.invite-warning{background:var(--orange-soft)}
.invite-actions{display:flex;flex-wrap:wrap;gap:.6rem;align-items:center}
.invite-status{font-weight:600;margin:.8rem 0 0}
.invite-status.connected{color:var(--green-text)}
.invite-attempt{margin:.2rem 0 0;font-size:.88rem;color:var(--text-2)}
.invite-help,.invite-raw{margin-top:.9rem;border-top:1px solid var(--separator);padding-top:.7rem}
.invite-help summary,.invite-raw summary{cursor:pointer;font-weight:600;color:var(--tint-text)}
.trouble{display:grid;gap:.7rem;margin:.8rem 0}
.trouble dt{font-weight:600}
.trouble dd{margin:.15rem 0 0;color:var(--text-2);font-size:.9rem}
.invite-refresh{display:flex;flex-wrap:wrap;gap:.6rem;align-items:center;margin:0}
.invite-refresh span{font-size:.84rem;color:var(--text-2)}
.invite-link{width:100%;margin:.6rem 0 .2rem;font-size:.82rem;padding:.45rem .6rem;border-radius:var(--r-sm);
  border:1px solid var(--separator-strong);background:var(--fill-2);color:var(--text)}
.new-athlete form{display:grid;gap:.9rem;max-width:34rem}
.new-athlete label{display:flex;flex-direction:column;gap:.3rem;font-weight:600}
.new-athlete input,.new-athlete select{font:inherit;padding:.55rem .65rem;border-radius:12px;
  border:1px solid var(--separator-strong);background:var(--card);color:var(--text)}
.new-athlete .times{display:grid;grid-template-columns:1fr 1fr;gap:.8rem}
.new-athlete details{border-top:1px solid var(--separator);padding-top:.6rem}
.new-athlete .onboarding-grid{display:grid;grid-template-columns:repeat(auto-fit,minmax(12rem,1fr));gap:.7rem;margin-top:.7rem}
.new-athlete .hint{font-weight:400;font-size:.86rem;color:var(--text-2)}
.advanced{margin:0;border-radius:var(--r-lg);padding:.7rem 1rem;background:var(--fill-2)}
.advanced summary{cursor:pointer;font-weight:600}
.advanced p{margin:.5rem 0;color:var(--text-2)}
.sim-note{border-radius:16px;padding:.8rem 1rem;background:var(--orange-soft);color:var(--text);margin-bottom:1rem}
.report-grid{display:grid;grid-template-columns:repeat(auto-fit,minmax(11rem,1fr));gap:.6rem}
.report-grid div{border-radius:14px;background:var(--fill-2);padding:.7rem .8rem}
.report-grid b{display:block;font-size:1.5rem}
.report-grid span{font-size:.84rem;color:var(--text-2)}
@media (max-width:760px){.stepper{grid-template-columns:repeat(2,minmax(0,1fr))}.invite-callouts{grid-template-columns:1fr}}
@media (max-width:640px){.setup-step{grid-template-columns:2rem 1fr}.setup-step .btn{grid-column:2}
  .invite-actions .btn,.status-actions .btn,.status-actions form,.status-actions form .btn{width:100%}
  .agent-status,.invite-card{padding:1rem}}
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
    if (!copied) {
      const raw = button.closest('section') && button.closest('section').querySelector('.invite-raw');
      if (raw) raw.open = true;
    }
    button.textContent = copied ? 'Copied ✓ Now send it privately' : 'Copy the link shown below';
    setTimeout(() => { button.textContent = label; }, 4000);
  });
});
</script>"""

# Watches the athlete's status while the coach waits, and on success reloads the
# whole page so every section (setup, plan, messages) reflects the connection.
INVITE_SCRIPT = """<script>
(() => {
  const card = document.getElementById('telegram');
  if (!card || !card.dataset.statusUrl) return;
  const status = card.querySelector('[data-telegram-status]');
  const attempt = card.querySelector('[data-last-attempt]');
  const check = card.querySelector('[data-check-connection]');
  const first = card.dataset.first;
  const waiting = 'Waiting for ' + first + ' to press Start. This page checks automatically.';
  let busy = false, polls = 0, timer = null;
  async function refresh(manual) {
    if (busy) return;
    busy = true;
    if (manual) { check.disabled = true; status.textContent = 'Checking…'; }
    try {
      const response = await fetch(card.dataset.statusUrl, {credentials: 'same-origin', cache: 'no-store'});
      if (!response.ok) throw new Error('status ' + response.status);
      const data = await response.json();
      if (data.last_attempt && attempt) {
        attempt.hidden = false;
        attempt.textContent = 'Last attempt: ' + data.last_attempt.label + ' (' + data.last_attempt.when + ')';
      }
      if (data.telegram_connected) {
        clearInterval(timer);
        card.dataset.connected = 'yes';
        status.classList.add('connected');
        status.textContent = 'Connected ✓ Updating the page…';
        location.replace(location.pathname + '?connected=1#agent-status');
        return;
      }
      status.textContent = manual
        ? 'Not connected yet. ' + first + ' has not pressed Start using the current invite.'
        : waiting;
    } catch (error) {
      if (manual) status.textContent = "Couldn't check just now. Try again in a moment.";
    } finally {
      busy = false;
      if (manual) check.disabled = false;
    }
  }
  check.addEventListener('click', () => refresh(true));
  timer = setInterval(() => {
    polls += 1;
    if (polls > 450) {
      clearInterval(timer);
      status.textContent = 'Stopped checking automatically. Use Check connection after ' + first + ' presses Start.';
      return;
    }
    if (!document.hidden) refresh(false);
  }, 4000);
})();
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
    steps_html = f'<ol class="setup-steps">{"".join(items)}</ol>'
    meter = f'<div class="setup-meter" aria-hidden="true"><span style="width:{percent}%"></span></div>'
    if not compact:
        return (
            '<section class="setup-card" id="setup">'
            f'<div class="setup-head"><div><span class="setup-eyebrow">{done} of {len(steps)} done</span>'
            f'<h2>Set up your agent</h2></div>{meter}</div>{steps_html}'
            '<p class="setup-foot"><a href="/demo">Watch the safe demo</a></p></section>'
        )
    # On Today, setup is one line with the next step; the full list folds away once started.
    upcoming = steps[first_open]
    expanded = done <= 1
    next_button = "" if expanded else (
        f'<a class="btn btn-primary btn-sm" href="{escape(upcoming["href"])}" data-step-next>'
        f'{escape(upcoming["action"])}</a>'
    )
    return (
        '<section class="setup-card setup-compact" id="setup">'
        '<div class="setup-line"><div class="setup-line-text">'
        f'<span class="setup-eyebrow">{done} of {len(steps)} done</span><h2>Set up your agent</h2>'
        f'<span class="setup-next">Next: {escape(upcoming["label"])}</span></div>{meter}{next_button}</div>'
        f'<details class="setup-all"{" open" if expanded else ""}><summary>All setup steps</summary>'
        f"{steps_html}</details></section>"
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


def setup_steps(status: AthleteStatus) -> list[dict]:
    """Connect Telegram → create plan → choose autopilot → agent ready, each done, current, blocked or to do."""
    problems = [b for b in status.blockers if b not in status.setup_gaps]
    if status.demo:
        telegram = "Simulator (demo athlete)"
    elif status.telegram_connected:
        telegram = "Connected"
    elif not status.telegram_available:
        telegram = "Bot not configured on this deployment"
    else:
        telegram = "Not connected"
    lifts = len(status.plan)
    plan = f"{', '.join(status.plan_days)} · {lifts} lift{'s' if lifts != 1 else ''}" if status.plan else "Not created"
    if not status.autopilot_decided:
        autopilot = "Not decided"
    elif status.autopilot:
        autopilot = "On" if status.plan else "On, but idle"
    else:
        autopilot = "Off, sessions wait for you"
    if status.ready:
        ready = "Ready"
    elif problems == [WAITING_FOR_DECISION]:
        ready = "Waiting for your decision"
    elif problems:
        ready = "Blocked"
    else:
        ready = "Not yet"
    steps = [
        {"key": "telegram", "title": "Connect Telegram", "detail": telegram, "done": status.reachable,
         "blocked": not status.reachable and not status.telegram_available},
        {"key": "training-plan", "title": "Create weekly plan", "detail": plan, "done": bool(status.plan),
         "blocked": False},
        {"key": "autopilot", "title": "Choose autopilot", "detail": autopilot, "done": status.autopilot_decided,
         "blocked": False},
        {"key": "agent-ready", "title": "Agent ready", "detail": ready, "done": status.ready,
         "blocked": bool(problems)},
    ]
    current = next((index for index, step in enumerate(steps) if not step["done"]), None)
    for index, step in enumerate(steps):
        step["state"] = (
            "done" if step["done"] else "blocked" if step["blocked"] else "current" if index == current else "todo"
        )
    return steps


def athlete_status_header(status: AthleteStatus, *, next_step: tuple[str, str], simulate_href: str) -> str:
    """Current status and the agent's next action first; the setup checklist only while setup is unfinished."""
    first = escape(status.first_name)
    steps = setup_steps(status)
    problems = [b for b in status.blockers if b not in status.setup_gaps]
    complete = all(step["done"] for step in steps[:3])
    if status.ready:
        state, badge = "ready", '<span class="status-badge ready">Ready</span>'
        headline = "Running automatically" if status.autopilot else "Ready · you approve each session"
    elif problems == [WAITING_FOR_DECISION]:
        state, badge, headline = "waiting", '<span class="status-badge waiting">Waiting for you</span>', \
            f"{first} needs a decision"
    elif problems:
        state, badge, headline = "blocked", '<span class="status-badge blocked">Blocked</span>', \
            "The agent is blocked"
    else:
        done = sum(1 for step in steps[:3] if step["done"])
        state, badge, headline = "setup", '<span class="status-badge">Setup needed</span>', \
            f"Setup · {done} of 3 done"

    if complete:
        facts = "".join(
            f'<li><span class="fact-label">{label}</span>'
            f'<span data-status="{step["key"]}">{escape(step["detail"])}</span></li>'
            for label, step in zip(("Telegram", "Plan", "Autopilot"), steps[:3])
        )
        progress = f'<ul class="status-facts">{facts}</ul>'
    else:
        items = []
        for index, step in enumerate(steps):
            mark = {"done": "✓", "blocked": "!"}.get(step["state"], str(index + 1))
            current = ' aria-current="step"' if step["state"] == "current" else ""
            items.append(
                f'<li class="stepper-step is-{step["state"]}" data-step-key="{step["key"]}"{current}>'
                f'<span class="stepper-mark" aria-hidden="true">{mark}</span>'
                f'<div><strong>{escape(step["title"])}</strong>'
                f'<span data-status="{step["key"]}">{escape(step["detail"])}</span></div></li>'
            )
        progress = f'<ol class="stepper" aria-label="Setup checklist">{"".join(items)}</ol>'
    idle = (
        '<p class="msg warn status-idle" data-idle>Autopilot is on but idle—there is no approved plan to run.</p>'
        if status.autopilot_decided and status.autopilot and not status.plan else ""
    )
    listed = [item for item in problems if item != WAITING_FOR_DECISION]
    blockers = (
        '<ul class="status-blockers" data-status="blocking">'
        + "".join(f"<li>{escape(item)}</li>" for item in listed) + "</ul>"
        if listed else ""
    )
    notes = [note for note in status.notes if not note.startswith("Autopilot")]
    notes_html = (
        '<ul class="status-notes">' + "".join(f"<li>{escape(note)}</li>" for note in notes) + "</ul>"
        if notes else ""
    )

    def link(label: str, href: str, primary: bool = True) -> str:
        return (f'<a class="btn {"btn-primary" if primary else "btn-ghost"} btn-sm" '
                f'href="{escape(href)}">{escape(label)}</a>')

    actions = []
    if status.waiting_case_id:
        actions.append(link("Review today's decision", f"/coach/case/{status.waiting_case_id}"))
    elif status.ready:
        actions.append(link("Run a safe simulated test", simulate_href, primary=False))
        if status.latest_case_id:
            actions.append(link("View the agent's timeline", f"/coach/case/{status.latest_case_id}", primary=False))
    elif status.reachable and not (status.plan and status.autopilot_decided):
        # Telegram still to connect is handled by the invite card straight below.
        actions.append(link(*next_step))
    return (
        f'<section class="agent-status" id="agent-status" data-state="{state}" '
        f'data-ready="{"yes" if status.ready else "no"}">'
        f'<div class="status-head"><h2>{headline}</h2>{badge}</div>'
        '<p class="status-next-line"><span class="k">Next</span>'
        f'<span data-status="next-action">{escape(status.next_action)}</span></p>'
        f'{progress}{idle}{blockers}{notes_html}'
        f'<div class="status-actions">{"".join(actions)}</div></section>'
    )


def invite_section(
    status: AthleteStatus, *, pairing_url: str | None, telegram_ready: bool, welcome: bool,
    next_step: tuple[str, str], last_attempt: dict | None = None,
) -> str:
    """How the coach gets this athlete connected. Nothing once they are: the setup steps say so."""
    if status.demo or status.telegram_connected:
        return ""
    first = escape(status.first_name)
    name = escape(status.name or status.first_name)
    eyebrow = f'<span class="setup-eyebrow">{name} added</span>' if welcome else \
        '<span class="setup-eyebrow">Telegram</span>'
    welcome_class = " welcome" if welcome else ""
    if not pairing_url:
        # No invite can exist yet, so point at work that is possible meanwhile, never back at this card.
        meanwhile = (
            f'<p class="invite-next">Meanwhile you can <a href="{escape(status.url)}#agent-plan">create the weekly '
            "plan</a>.</p>" if not status.plan else ""
        )
        return (
            f'<section id="telegram" class="invite-card{welcome_class}">{eyebrow}'
            "<h2>Telegram isn't set up on this deployment</h2>"
            f"<p>The agent reaches athletes on Telegram, so {first} can't be invited until the bot is configured "
            "(<code>TELEGRAM_BOT_TOKEN</code>, <code>TELEGRAM_BOT_USERNAME</code>, <code>TELEGRAM_WEBHOOK_SECRET</code>, "
            "<code>TELEGRAM_LINK_SECRET</code>, <code>PUBLIC_BASE_URL</code>).</p>"
            f'<p class="invite-status">Telegram: not connected</p>{meanwhile}</section>'
        )
    quoted = escape(quote(status.athlete_id))
    url = escape(pairing_url)
    warning = "" if telegram_ready else (
        '<p class="msg warn">The Telegram webhook has not been verified yet. The invite may not connect until it is.</p>'
    )
    # Troubleshooting stays folded away unless the last pairing attempt actually failed.
    help_open = " open" if last_attempt and last_attempt.get("outcome") in PAIRING_FAILURE_OUTCOMES else ""
    attempt = (
        f'<p class="invite-attempt" data-last-attempt>Last attempt: {escape(last_attempt["label"])} '
        f'({escape(last_attempt["when"])})</p>'
        if last_attempt else '<p class="invite-attempt" data-last-attempt hidden></p>'
    )
    return (
        f'<section id="telegram" class="invite-card{welcome_class}" data-connected="no" data-first="{first}" '
        f'data-status-url="/coach/athlete/{quoted}/status.json">'
        f'<div class="invite-head"><div>{eyebrow}<h2>{first} is not connected yet</h2></div>'
        f'<span class="status-badge waiting">Waiting for {first}</span></div>'
        '<ol class="invite-steps">'
        f"<li><b>You copy the private invite</b> and send it to {first} the way you normally message them.</li>"
        f"<li><b>{first} opens it with their own Telegram</b> and presses <b>Start</b>.</li>"
        f"<li><b>The bot replies “Connected to Power AI as {name}.”</b> This page updates by itself.</li></ol>"
        '<div class="invite-callouts">'
        f'<p class="invite-note"><b>Opening the bot or typing /start is not enough.</b> Only the invite tells the '
        f"bot who {first} is, so {first} must tap the invite itself.</p>"
        f'<p class="invite-warning"><b>Don’t open the invite with your own Telegram.</b> The first account to press '
        f"Start is connected as {first}, and the invite then stops working.</p></div>"
        f"{warning}"
        '<div class="invite-actions">'
        f'<button type="button" class="btn btn-primary btn-lg" data-copy="{url}">Copy invite for {first}</button>'
        '<button type="button" class="btn btn-ghost" data-check-connection>Check connection</button></div>'
        f'<p class="invite-status" data-telegram-status role="status" aria-live="polite">Waiting for {first} to press '
        "Start. This page checks automatically.</p>"
        f"{attempt}"
        f'<details class="invite-help"{help_open}><summary>Invite not working?</summary><dl class="trouble">'
        f"<div><dt>The bot asked for the private invite</dt><dd>{first} opened the bot or typed /start instead of "
        f"tapping the invite. Send the invite again and ask {first} to tap it, then press Start.</dd></div>"
        "<div><dt>The bot said the invite isn’t valid</dt><dd>The link was cut short or changed while it was being "
        "shared. Copy it again and send it in one piece, or replace it below.</dd></div>"
        "<div><dt>The bot said the invite was already used or replaced</dt><dd>Each invite works once. Creating a new "
        "invite, or disconnecting Telegram, turns off every earlier one. Copy the current invite above and send that."
        "</dd></div>"
        "<div><dt>The invite seems to have expired</dt><dd>Invites don’t expire with time; they stop working only when "
        f"used or replaced. If you’re not sure which invite {first} has, replace it below and send the new one.</dd></div>"
        "<div><dt>The bot said this Telegram account is connected to another athlete</dt><dd>Each Telegram account "
        f"belongs to one athlete only. {first} must use their own account. If an account was connected to the wrong "
        "athlete, disconnect it on that athlete’s page first.</dd></div></dl>"
        f'<form class="invite-refresh" method="post" action="/coach/athlete/{quoted}/telegram/refresh-invite">'
        '<button class="btn btn-ghost btn-sm" type="submit">Replace with a fresh invite</button>'
        f"<span>Every earlier invite for {first} stops working immediately.</span></form></details>"
        '<details class="invite-raw"><summary>Show the raw invite link</summary>'
        f'<input class="invite-link" readonly value="{url}" aria-label="Telegram invite link for {first}" '
        'onfocus="this.select()"></details>'
        f"</section>{COPY_SCRIPT}{INVITE_SCRIPT}"
    )


def advanced_section(athlete_id: str, *, telegram_connected: bool) -> str:
    unlink = (
        f'<form method="post" action="/coach/athlete/{escape(quote(athlete_id))}/telegram/unlink">'
        "<p>Disconnecting stops messages to this athlete and turns off every earlier invite. Use it if they "
        "changed Telegram account, then send the new invite.</p>"
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

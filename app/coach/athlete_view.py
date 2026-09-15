"""The athlete page: current status and the agent's next action first, then tabs.

Anything the coach must decide sits at the top. Setup shows as a short checklist
until it is finished and then collapses to a few facts. Plan, Evidence, Messages
and Profile are separate tabs, each opening on the latest useful information
with older history one tap away. The page adds no coaching of its own.
"""

from __future__ import annotations

from html import escape

from app.coach.agent_view import AGENT_STYLE
from app.coach.athlete import AthleteDetail, progress_series
from app.coach.view import coach_frame, conversation_bubbles
from app.decision.injury_pivot import InjuryPivot, pivot_message
from app.scheduling.outbox import message_kind_label
from app.storage.db import normalized_message

TABS = (("plan", "Plan"), ("evidence", "Evidence"), ("messages", "Messages"), ("profile", "Profile"))
_FLAG_TONE = {
    "clearance_requested": "red", "injured": "red", "silent": "orange", "deload": "orange",
    "stalled": "orange", "regressed": "orange", "meet": "blue",
}
LATEST_SESSIONS = 3
LATEST_MESSAGES = 10
LATEST_OUTBOX = 5


def _current_plan(detail: AthleteDetail) -> InjuryPivot | None:
    """The pivot the coach approved for this injury, if it still applies."""
    decision = detail.injury_plan_decision
    if (
        not decision
        or detail.injury_entry_id is None
        or int(decision.get("injury_entry_id", -1)) != detail.injury_entry_id
    ):
        return None
    code = str(decision.get("option_code"))
    return next((option for option in detail.injury_pivots if option.code == code), None)


def _first_name(detail: AthleteDetail) -> str:
    return detail.display_name.split()[0] if detail.name else "This athlete"


def _attention_strip(detail: AthleteDetail, *, plan: InjuryPivot | None, awaiting: int) -> str:
    """One line when the coach owes this athlete a decision; nothing otherwise."""
    if detail.clearance_requested:
        problem, href, label = "Asked to be cleared after an injury", "#clearance-review", "Review clearance"
    elif detail.injured and detail.injury_pivots and plan is None:
        note = f": {detail.injury_note}" if detail.injury_note else ""
        problem, href, label = f"Injury reported{note}", "#injury-plan", "Choose injury plan"
    elif awaiting:
        problem = f"{awaiting} message{'s' if awaiting != 1 else ''} waiting for approval"
        href, label = "/coach/whatsapp?tab=approval", "Review messages"
    else:
        return ""
    return (
        '<section class="attention-strip" id="attention">'
        '<span class="chip chip-red">Needs you</span>'
        f"<strong>{escape(_first_name(detail))} needs a decision</strong>"
        f'<span class="attention-problem">{escape(problem)}</span>'
        f'<a class="btn btn-primary btn-sm" href="{escape(href)}">{escape(label)}</a></section>'
    )


def _injury_plan_panel(detail: AthleteDetail, *, coach: str, plan: InjuryPivot | None) -> str:
    """Four bounded plans, each with the message it sends. The coach picks one,
    checks or edits the wording, and approves both together."""
    if not detail.injured or detail.injury_entry_id is None or not detail.injury_pivots:
        return ""
    recommended = next((o for o in detail.injury_pivots if o.recommended), detail.injury_pivots[0])
    selected = plan or recommended
    first_name = detail.display_name.split()[0] if detail.name else "the athlete"
    options = []
    for option in detail.injury_pivots:
        badges = ""
        if option.recommended:
            badges += '<span class="badge badge-blue">Recommended</span>'
        if plan is not None and option.code == plan.code:
            badges += '<span class="badge tag-fine">Current plan ✓</span>'
        checked = " checked" if option.code == selected.code else ""
        options.append(
            f'<label class="plan-option{" selected" if checked else ""}">'
            f'<input type="radio" name="option_code" value="{escape(option.code)}"{checked} required '
            f'data-message="{escape(pivot_message(option, coach=coach), quote=True)}">'
            '<span class="plan-option-body">'
            f'<span class="plan-option-top"><strong>{escape(option.title)}</strong>{badges}</span>'
            f'<span class="plan-option-text">{escape(option.plan)}</span>'
            f'<span class="plan-option-why">{escape(option.rationale)}</span>'
            '</span></label>'
        )
    note = f" ({detail.injury_note})" if detail.injury_note else ""
    if plan is None:
        head = f"<h2>Choose an injury plan</h2><p>New injury{escape(note)}.</p>"
        state = '<span class="clearance-state">Decision needed</span>'
        submit = "Approve plan and schedule message"
    else:
        head = f"<h2>Injury plan: {escape(plan.title)}</h2><p>Current injury{escape(note)}.</p>"
        state = '<span class="badge tag-fine">Plan approved</span>'
        submit = "Switch to the selected plan"
    return (
        f'<section id="injury-plan" class="injury-plan{" decided" if plan else ""}">'
        f'<div class="plan-head"><div>{head}</div>{state}</div>'
        f'<form id="injury-plan-form" method="post" action="/coach/athlete/{escape(detail.athlete_id)}/injury-plan">'
        f'<input type="hidden" name="injury_entry_id" value="{detail.injury_entry_id}">'
        f'<div class="plan-options" role="radiogroup" aria-label="Injury plans">{"".join(options)}</div>'
        f'<label class="plan-message">Message to {escape(first_name)}'
        f'<textarea name="body" maxlength="1400">{escape(pivot_message(selected, coach=coach))}</textarea></label>'
        '<div class="plan-actions"><small>The injury flag stays open until an independent clearance.</small>'
        f'<button class="btn btn-primary" type="submit">{submit}</button></div>'
        '</form></section>'
        """<script>
(() => {
  const form = document.getElementById('injury-plan-form');
  if (!form) return;
  const box = form.querySelector('textarea[name=body]');
  let generated = box.value;
  form.querySelectorAll('input[name=option_code]').forEach((radio) => {
    radio.addEventListener('change', () => {
      if (box.value === generated) box.value = radio.dataset.message;
      generated = radio.dataset.message;
      form.querySelectorAll('.plan-option').forEach((option) => {
        option.classList.toggle('selected', option.querySelector('input').checked);
      });
    });
  });
})();
</script>"""
    )


def _injury_clearance_panel(detail: AthleteDetail) -> str:
    """A deliberate safety review, shown only after the athlete requests clearance."""
    if not detail.injured or not detail.clearance_requested:
        return ""
    days = (
        f"Open {detail.injury_days_open} days"
        if detail.injury_days_open is not None else "Injury gate open"
    )
    return (
        '<section id="clearance-review" class="clearance-panel">'
        '<div class="clearance-head"><div><h2>Injury clearance review</h2>'
        '<p>Record who cleared the athlete before normal programming reopens.</p></div>'
        f'<span class="clearance-state">{escape(days)}</span></div>'
        '<details class="why"><summary>Why?</summary><ul>'
        '<li>A named coach, physio or clinician, not the athlete, must have assessed readiness.</li>'
        '<li>The source and basis are recorded with your name and the time.</li>'
        '<li>Only then can normal load suggestions resume.</li></ul></details>'
        '<form class="clearance-form" method="post" action="/coach/clear-injury">'
        f'<input type="hidden" name="athlete_id" value="{escape(detail.athlete_id)}">'
        '<label>Named clearance source'
        '<input type="text" name="clearance_source" required maxlength="100" '
        'placeholder="e.g. Dr Mehta, sports physio"></label>'
        '<label>Basis for clearance'
        '<textarea name="reason" required maxlength="400" '
        'placeholder="What was assessed, and what return-to-training limits apply?"></textarea></label>'
        '<label class="clearance-confirm"><input type="checkbox" name="independent_confirmation" '
        'value="confirmed" required><span>This clearance came from someone other '
        'than the athlete. Remove the injury safety gate.</span></label>'
        '<div class="clearance-actions"><small>Not a diagnosis by Power AI.</small>'
        '<button type="submit">Record clearance and reopen programming</button></div>'
        '</form></section>'
    )


def _chart(lift: str, points: tuple[tuple[str, float], ...]) -> str:
    """One lift, top set over time. One series, so the heading names it and
    there is no legend; only the latest point carries a number."""
    w, h = 560, 150
    pad_l, pad_r, pad_t, pad_b = 44, 46, 14, 26
    weights = [p[1] for p in points]
    lo, hi = min(weights), max(weights)
    if hi == lo:                      # a flat run still needs a band to draw in
        lo, hi = lo - 5, hi + 5
    span = hi - lo
    inner_w, inner_h = w - pad_l - pad_r, h - pad_t - pad_b

    def x(i: int) -> float:
        return pad_l + (inner_w * i / max(1, len(points) - 1))

    def y(v: float) -> float:
        return pad_t + inner_h - (inner_h * (v - lo) / span)

    grid = "".join(
        f'<line x1="{pad_l}" y1="{y(v):.1f}" x2="{w - pad_r}" y2="{y(v):.1f}" '
        f'style="stroke:var(--separator)" stroke-width="1"/>'
        f'<text x="{pad_l - 8}" y="{y(v) + 4:.1f}" text-anchor="end">{v:g}</text>'
        for v in (lo, (lo + hi) / 2, hi)
    )
    gradient_id = "area-" + "".join(c if c.isalnum() else "-" for c in lift)
    defs = (
        f'<defs><linearGradient id="{gradient_id}" x1="0" y1="0" x2="0" y2="1">'
        '<stop offset="0%" style="stop-color:var(--tint);stop-opacity:0.26"/>'
        '<stop offset="100%" style="stop-color:var(--tint);stop-opacity:0"/>'
        '</linearGradient></defs>'
    )
    path = " ".join(
        f"{'M' if i == 0 else 'L'}{x(i):.1f},{y(v):.1f}"
        for i, (_, v) in enumerate(points)
    )
    baseline = pad_t + inner_h
    area = f"{path} L{x(len(points) - 1):.1f},{baseline:.1f} L{x(0):.1f},{baseline:.1f} Z"
    dots = "".join(
        f'<circle cx="{x(i):.1f}" cy="{y(v):.1f}" r="3" style="fill:var(--card);stroke:var(--tint)" '
        f'stroke-width="1.8"><title>{escape(d)} · {v:g} kg</title></circle>'
        for i, (d, v) in enumerate(points)
    )
    last_d, last_v = points[-1]
    active_dot = (
        f'<circle cx="{x(len(points) - 1):.1f}" cy="{y(last_v):.1f}" r="5" '
        'style="fill:var(--tint);stroke:var(--card)" stroke-width="2.5"/>'
    )
    label = (
        f'<text class="last-label" x="{x(len(points) - 1) + 11:.1f}" y="{y(last_v) + 4:.1f}">{last_v:g} kg</text>'
    )
    axis = (
        f'<text x="{pad_l}" y="{h - 6}">{escape(points[0][0])}</text>'
        f'<text x="{w - pad_r}" y="{h - 6}" text-anchor="end">{escape(last_d)}</text>'
    )
    return (
        f'<div class="chart"><h3>{escape(lift.title())}</h3>'
        f'<p class="cap">Top set per session &middot; {len(points)} sessions</p>'
        f'<svg viewBox="0 0 {w} {h}" role="img" '
        f'aria-label="{escape(lift)} top set over {len(points)} sessions, '
        f'latest {last_v:g} kilograms">'
        f"{defs}{grid}"
        f'<path d="{area}" fill="url(#{gradient_id})" stroke="none"/>'
        f'<path d="{path}" fill="none" style="stroke:var(--tint)" stroke-width="2.5" '
        f'stroke-linejoin="round" stroke-linecap="round"/>'
        f"{dots}{active_dot}{label}{axis}</svg></div>"
    )


def _telegram_panel(
    detail: AthleteDetail, pairing_url: str | None, linked: bool, ready: bool
) -> str:
    if linked and ready:
        return (
            '<section class="channel-callout"><div><span class="channel-label">Telegram · Connected</span>'
            '<h2>Telegram connected</h2></div><form method="post" action="/coach/athlete/'
            f'{escape(detail.athlete_id)}/telegram/unlink">'
            '<button class="danger" type="submit">Disconnect Telegram</button>'
            '</form></section>'
        )
    if pairing_url and ready:
        # No link to open here: whoever opens an invite and presses Start becomes this athlete.
        return (
            '<section class="channel-callout"><div><span class="channel-label">Telegram · Action needed</span>'
            '<h2>This athlete is not connected yet</h2></div></section>'
        )
    if pairing_url:
        return (
            '<section class="channel-callout"><div><span class="channel-label">Telegram · Reconnecting</span>'
            '<h2>Telegram webhook is not ready</h2><p>Check the deployment log before pairing.</p></div></section>'
        )
    return ""


def _row_value(row, key: str):
    try:
        return row[key]
    except (IndexError, KeyError):
        return None


def _delivery_state(row, today: str, stale_reason: str | None = None) -> tuple[str, str]:
    """(label, tone) for one outbound message: scheduled, awaiting approval, sent, failed or cancelled."""
    status = str(row["status"])
    resolution = _row_value(row, "resolution")
    if stale_reason and status in {"pending", "approved"}:
        return ("Outdated—new athlete information received", "failed")
    if resolution == "superseded":
        return ("Outdated, not sent", "cancelled")
    if status == "sent":
        return ("Sent", "sent")
    if status == "pending":
        return ("Awaiting approval", "pending")
    if status == "approved":
        local_date = str(row["local_date"])
        return (f"Scheduled for {local_date}" if local_date > today else "Scheduled", "scheduled")
    if resolution == "failed":
        return ("Failed", "failed")
    if resolution == "duplicate":
        return ("Duplicate, not sent", "cancelled")
    if resolution == "cancelled":
        return ("Cancelled", "cancelled")
    return ("Skipped", "cancelled")


def _outbox(rows, *, athlete_id: str, first_name: str, today: str, stale: dict | None = None) -> str:
    """Recent outbound messages with their delivery state. Identical duplicates collapse into one line."""
    def identity(row) -> tuple[str, str, str]:
        kind = str(row["message_kind"]).split(":", 1)[0]
        return (str(row["local_date"]), kind, normalized_message(str(row["body"])))

    originals = {identity(row) for row in rows if _row_value(row, "resolution") != "duplicate"}
    duplicates: dict[tuple[str, str, str], int] = {}
    kept = []
    for row in rows:
        key = identity(row)
        if _row_value(row, "resolution") == "duplicate" and key in originals:
            duplicates[key] = duplicates.get(key, 0) + 1
        else:
            kept.append((key, row))

    items = []
    noted: set[tuple[str, str, str]] = set()
    stale = stale or {}
    for key, row in kept:
        stale_reason = stale.get((str(row["message_kind"]), str(row["local_date"])))
        label, tone = _delivery_state(row, today, stale_reason)
        notes = []
        if duplicates.get(key) and key not in noted:
            count = duplicates[key]
            notes.append(f"{count} identical duplicate{'s' if count != 1 else ''} blocked, not sent.")
            noted.add(key)
        if stale_reason:
            notes.append(f"{stale_reason} It will not be sent.")
        elif _row_value(row, "resolution") == "superseded" and _row_value(row, "reason"):
            notes.append(str(_row_value(row, "reason")))
        elif tone == "failed":
            notes.append("Not retried automatically. Queue it again if it should still go out.")
        cancel = (
            f'<form class="outbox-cancel" method="post" action="/coach/athlete/{escape(athlete_id)}/messages/cancel">'
            f'<input type="hidden" name="message_kind" value="{escape(str(row["message_kind"]))}">'
            f'<input type="hidden" name="local_date" value="{escape(str(row["local_date"]))}">'
            '<button class="btn btn-ghost btn-sm" type="submit">Cancel message</button></form>'
            if str(row["status"]) in {"pending", "approved"} else ""
        )
        note_html = "".join(f"<span>{escape(note)}</span>" for note in notes)
        foot = f'<div class="outbox-foot"><div class="outbox-notes">{note_html}</div>{cancel}</div>' \
            if note_html or cancel else ""
        items.append(
            f'<li class="outbox-item" data-delivery="{tone}">'
            f'<div class="outbox-top"><span>{escape(message_kind_label(str(row["message_kind"])))} · '
            f'{escape(str(row["local_date"]))}</span><span class="delivery-badge {tone}">{escape(label)}</span></div>'
            f'<p class="outbox-body">{escape(str(row["body"]))}</p>{foot}</li>'
        )
    visible, older = items[:LATEST_OUTBOX], items[LATEST_OUTBOX:]
    content = (
        f'<ul class="outbox">{"".join(visible)}</ul>'
        + (f'<details class="older"><summary>Older messages ({len(older)})</summary>'
           f'<ul class="outbox">{"".join(older)}</ul></details>' if older else "")
        if items else f'<p class="empty">Nothing scheduled or sent to {escape(first_name)} yet.</p>'
    )
    return (
        '<section class="context-card outbox-card" id="outbox"><h3>Scheduled and sent</h3>'
        f"{content}</section>"
    )


def _facts(items: list[tuple[str, object]]) -> str:
    usable = [(label, value) for label, value in items if value not in (None, "", ())]
    if not usable:
        return '<p class="empty">Not configured yet.</p>'
    return '<dl class="facts">' + "".join(
        f'<div><dt>{escape(label)}</dt><dd>{escape(str(value))}</dd></div>'
        for label, value in usable
    ) + '</dl>'


def _session_table(sessions) -> str:
    return (
        '<table><thead><tr><th>Date</th><th>Lift</th><th>Set</th></tr></thead><tbody>'
        + "".join(
            f"<tr><td>{escape(s.session_date)}</td><td>{escape(s.lift)}</td><td>{escape(s.summary)}</td></tr>"
            for s in sessions
        )
        + "</tbody></table>"
    )


def _evidence(detail: AthleteDetail) -> str:
    """The latest useful evidence first; charts and older sessions behind History."""
    tiles = [
        ("Readiness", f"{detail.readiness_score}/100" if detail.readiness_score is not None else "No check-in",
         detail.readiness_band in {"orange", "red"}),
        ("Sleep", f"{detail.checkin.sleep_hours:g} h" if detail.checkin and detail.checkin.sleep_hours is not None
         else "—", False),
        ("Last logged", detail.last_activity or "Never", False),
        ("Phase", detail.phase, False),
    ]
    if detail.injured:
        tiles.append(("Injury", f"{detail.injury_days_open}d" if detail.injury_days_open is not None else "Open", True))
    if detail.roster.weeks_to_meet is not None:
        tiles.append(("Meet in", f"{detail.roster.weeks_to_meet}w", False))
    tile_html = "".join(
        f'<div class="tile"><div class="k">{escape(k)}</div>'
        f'<div class="v{" warn" if warn else ""}">{escape(v)}</div></div>'
        for k, v, warn in tiles
    )
    signals = "".join(
        f'<span class="chip chip-{_FLAG_TONE.get(flag.kind, "grey")}">{escape(flag.detail)}</span>'
        for flag in detail.roster.flags
    )
    verdicts = "".join(
        f"<tr><td>{escape(a.lift)}</td><td>{escape(a.verdict.value)}</td>"
        + (f"<td>{a.current_weight:g} kg</td>" if a.current_weight is not None else "<td>—</td>")
        + "</tr>"
        for a in detail.assessments
    )
    verdict_table = (
        '<h3 class="sub-head">By lift</h3><table><thead><tr><th>Lift</th><th>Trend</th>'
        f"<th>Latest top set</th></tr></thead><tbody>{verdicts}</tbody></table>"
        if verdicts else ""
    )
    sessions = list(detail.sessions[:15])
    latest = (
        f'<h3 class="sub-head">Latest sessions</h3>{_session_table(sessions[:LATEST_SESSIONS])}'
        if sessions else '<p class="empty">Nothing logged yet.</p>'
    )
    charts = "".join(_chart(lift, pts) for lift, pts in progress_series(detail).items())
    older = sessions[LATEST_SESSIONS:]
    history_parts = charts + (
        f'<h3 class="sub-head">Earlier sessions</h3>{_session_table(older)}' if older else ""
    )
    history = (
        f'<details class="history"><summary>History</summary>{history_parts}</details>'
        if history_parts else ""
    )
    return (
        '<section id="evidence" class="profile-section"><h2 class="visually-hidden">Evidence</h2>'
        + (f'<div class="signal-chips">{signals}</div>' if signals else "")
        + f'<div class="grid">{tile_html}</div>{latest}{verdict_table}{history}</section>'
    )


def _profile(detail: AthleteDetail, plan: InjuryPivot | None) -> str:
    recovery = _facts([
        ("Readiness band", detail.readiness_band),
        ("Self-rating", detail.checkin.readiness if detail.checkin else None),
        ("Soreness", detail.checkin.soreness if detail.checkin else None),
        ("Stress", detail.checkin.stress if detail.checkin else None),
        ("Bodyweight", f"{detail.checkin.bodyweight_kg:g} kg" if detail.checkin and detail.checkin.bodyweight_kg is not None else None),
    ])
    reasons = "".join(f"<li>{escape(reason)}</li>" for reason in detail.readiness_reasons)
    recovery_panel = (
        '<div class="context-card"><h3>Recovery today</h3>' + recovery
        + (f'<details class="why"><summary>Why?</summary><ul>{reasons}</ul></details>' if reasons else "")
        + '</div>'
    )
    program_panel = '<div class="context-card"><h3>Programming</h3>' + _facts([
        ("Method", str(detail.program.get("methodology", "")).replace("_", " ")),
        ("Suggested starting method", detail.suggested_method),
        ("Inputs still needed", ", ".join(detail.suggested_method_inputs)),
        ("Injury plan", plan.title if plan else None),
        ("Experience", detail.program.get("experience")),
        ("Training days", detail.program.get("days_per_week")),
        ("Starting bodyweight", f'{detail.profile.get("bodyweight_kg")} kg' if detail.profile.get("bodyweight_kg") else None),
        ("Squat 1RM", f'{detail.profile.get("squat_1rm_kg")} kg' if detail.profile.get("squat_1rm_kg") else None),
        ("Bench 1RM", f'{detail.profile.get("bench_1rm_kg")} kg' if detail.profile.get("bench_1rm_kg") else None),
        ("Deadlift 1RM", f'{detail.profile.get("deadlift_1rm_kg")} kg' if detail.profile.get("deadlift_1rm_kg") else None),
        ("Meet date", detail.program.get("meet_date")),
    ]) + (
        f'<details class="why"><summary>Why this method?</summary><p>{escape(detail.suggested_method_reason)}</p></details>'
        if detail.suggested_method_reason else ""
    ) + (
        '<div class="goal-signal"><strong>Goal pace:</strong> '
        f'{escape(detail.goal_pace.status.replace("_", " ").title())} · '
        f'{detail.goal_pace.current_kg:g} of {detail.goal_pace.expected_kg:g} kg expected · '
        f'{detail.goal_pace.target_kg:g} kg by {escape(detail.goal_pace.target_date)}</div>'
        if detail.goal_pace else ""
    ) + '</div>'
    schedule_panel = '<div class="context-card"><h3>Schedule</h3>' + _facts([
        ("Calendar", "Connected" if detail.calendar_connected else "Not connected"),
        ("Timezone", detail.schedule.get("timezone")),
        ("Morning check-in", detail.schedule.get("morning_checkin_time")),
        ("Usual training", detail.schedule.get("training_time")),
        ("Bedtime", detail.schedule.get("bedtime")),
    ]) + '</div>'
    supplement_text = "; ".join(detail.supplements) if detail.supplements else None
    nutrition_panel = '<div class="context-card"><h3>Nutrition & supplements</h3>' + _facts([
        ("Diet", detail.nutrition.get("diet_style")),
        ("Foods available", detail.nutrition.get("foods_available")),
        ("Allergies", detail.nutrition.get("allergies")),
        ("Meals", detail.nutrition.get("meals_per_day")),
        ("Protein target", f'{detail.nutrition.get("protein_target_g")} g' if detail.nutrition.get("protein_target_g") else None),
        ("Approved supplements", supplement_text),
    ]) + '</div>'
    return (
        '<section id="profile" class="profile-section"><h2 class="visually-hidden">Profile</h2>'
        f'<div class="context-grid">{recovery_panel}{program_panel}{schedule_panel}{nutrition_panel}</div>'
        '</section>'
    )


TAB_SCRIPT = """<script>
(() => {
  const tabs = [...document.querySelectorAll('[data-tab]')];
  const panels = [...document.querySelectorAll('[data-panel]')];
  if (!tabs.length) return;
  function show(key) {
    tabs.forEach((tab) => {
      const on = tab.dataset.tab === key;
      tab.setAttribute('aria-selected', on ? 'true' : 'false');
      tab.tabIndex = on ? 0 : -1;
      tab.classList.toggle('active', on);
    });
    panels.forEach((panel) => { panel.hidden = panel.dataset.panel !== key; });
  }
  function panelForHash() {
    const id = decodeURIComponent(location.hash.slice(1));
    const target = id && document.getElementById(id);
    const panel = target && target.closest('[data-panel]');
    return panel ? panel.dataset.panel : null;
  }
  tabs.forEach((tab, index) => {
    tab.addEventListener('click', (event) => {
      event.preventDefault();
      show(tab.dataset.tab);
      history.replaceState(null, '', '#' + tab.getAttribute('aria-controls'));
    });
    tab.addEventListener('keydown', (event) => {
      if (event.key !== 'ArrowRight' && event.key !== 'ArrowLeft') return;
      event.preventDefault();
      const next = tabs[(index + (event.key === 'ArrowRight' ? 1 : tabs.length - 1)) % tabs.length];
      next.click();
      next.focus();
    });
  });
  function followHash() {
    const key = panelForHash();
    if (!key) return;
    show(key);
    const target = document.getElementById(decodeURIComponent(location.hash.slice(1)));
    if (target && !target.matches('[data-panel]')) requestAnimationFrame(() => target.scrollIntoView());
  }
  window.addEventListener('hashchange', followHash);
  show(panelForHash() || 'plan');
  followHash();
})();
</script>"""


def render_athlete(
    detail: AthleteDetail,
    *,
    coach: str,
    suggested: str,
    message: tuple[str, str] | None = None,
    telegram_pairing_url: str | None = None,
    telegram_linked: bool = False,
    telegram_ready: bool | None = None,
    conversation=(),
    scheduled=(),
    outbox=None,
    outbox_stale: dict | None = None,
    today: str | None = None,
    awaiting: int = 0,
    pending_count: int = 0,
    agent_panel: str = "",
    status_html: str = "",
    invite_html: str | None = None,
    advanced_html: str = "",
    welcome: bool = False,
) -> str:
    banner = ""
    if message:
        kind, text = message
        banner = f'<div class="msg {escape(kind)}">{escape(text)}</div>'
    if telegram_ready is None:
        telegram_ready = bool(telegram_linked or telegram_pairing_url)
    plan = _current_plan(detail)
    first_name = detail.display_name.split()[0] if detail.name else "the athlete"

    # --- Messages: write, what is scheduled, then the conversation ---
    outbox_html = _outbox(
        list(scheduled) if outbox is None else list(outbox),
        athlete_id=detail.athlete_id, first_name=first_name,
        today=today or detail.reviewed_on.isoformat(), stale=outbox_stale,
    )
    history = list(conversation)
    latest, earlier = history[:LATEST_MESSAGES], history[LATEST_MESSAGES:]
    thread = (
        '<section class="context-card thread-card"><h3>Conversation</h3>'
        + (f'<details class="older"><summary>Earlier messages ({len(earlier)})</summary>'
           f'<div class="chat-stream">{conversation_bubbles(earlier)}</div></details>' if earlier else "")
        + (
            f'<div class="chat-stream">{conversation_bubbles(latest)}</div>'
            if latest else f'<p class="empty">No messages with {escape(first_name)} yet.</p>'
        )
        + "</section>"
    )
    compose = (
        '<div class="context-card compose coach-draft">'
        f'<h3>Message {escape(first_name)}</h3>'
        '<form method="post" action="/coach/athlete/'
        f'{escape(detail.athlete_id)}/message">'
        f'<label class="visually-hidden" for="draft-composer">Message for {escape(first_name)}</label>'
        f'<textarea name="body" id="draft-composer" maxlength="1400">{escape(suggested)}</textarea>'
        '<div class="btns"><button class="btn btn-primary" type="submit">Queue message</button>'
        '<p class="hint">Sent once, exactly as written.</p></div>'
        "</form></div>"
    )
    messages = (
        '<section id="messages" class="profile-section messages-section"><h2 class="visually-hidden">Messages</h2>'
        f'<div class="messages-grid"><div class="messages-col">{compose}{outbox_html}</div>'
        f'<div class="messages-col">{thread}</div></div></section>'
    )

    channel = (
        invite_html if invite_html is not None
        else _telegram_panel(detail, telegram_pairing_url, telegram_linked, telegram_ready)
    )
    plan_tab = agent_panel or '<p class="empty">No plan tools on this page.</p>'
    panels = {
        "plan": plan_tab,
        "evidence": _evidence(detail),
        "messages": messages,
        "profile": _profile(detail, plan) + advanced_html,
    }
    tabbar = (
        '<div class="athlete-tabs" role="tablist" aria-label="Athlete sections">'
        + "".join(
            f'<a class="athlete-tab" role="tab" id="tab-{key}" href="#panel-{key}" '
            f'aria-controls="panel-{key}" data-tab="{key}">{label}</a>'
            for key, label in TABS
        )
        + "</div>"
    )
    tab_panels = "".join(
        f'<div class="tab-panel" id="panel-{key}" role="tabpanel" aria-labelledby="tab-{key}" '
        f'data-panel="{key}">{panels[key]}</div>'
        for key, _ in TABS
    )
    # Status and what the agent does next come first, then anything the coach must
    # decide, then setup while it is unfinished, and only then the detail tabs.
    body = (
        f"{banner}"
        f'<div class="athlete-top">{_attention_strip(detail, plan=plan, awaiting=awaiting)}{status_html}'
        f"{_injury_clearance_panel(detail)}"
        f"{'' if detail.clearance_requested else _injury_plan_panel(detail, coach=coach, plan=plan)}"
        f"{channel}{tabbar}</div>"
        f'<div class="athlete-lower">{tab_panels}</div>{TAB_SCRIPT}'
    )
    if status_html:
        from app.coach.onboarding_view import ONBOARDING_STYLE

        style = AGENT_STYLE + ONBOARDING_STYLE
    else:
        style = AGENT_STYLE if agent_panel else ""
    return coach_frame(
        body, active="athletes", coach=coach, title=detail.display_name,
        subtitle="", today=detail.reviewed_on.isoformat(), back=("/coach/athletes", "Athletes"),
        athlete_id=detail.athlete_id, pending_count=pending_count,
        extra_style=style,
    )

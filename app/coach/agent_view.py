"""The training-day agent in the coach console.

Today leads with the agent's own work: what needs the coach, what it is waiting
for, what it finished, what it did step by step, and what it has adapted.
"""

from __future__ import annotations

import json
from datetime import datetime
from html import escape
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from app.casework.board import Board
from app.casework.engine import OUTCOME_LABELS, STATE_LABELS

WEEKDAYS = ("Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday", "Sunday")

KIND_LABELS = {
    "observation": "Observed",
    "decision": "Decided",
    "action": "Did",
    "expectation": "Expects",
    "outcome": "Outcome",
    "escalation": "Escalated",
    "adaptation": "Adapted",
    "coach": "Coach",
}

AGENT_STYLE = """
.agent-strip{display:grid;grid-template-columns:repeat(4,minmax(0,1fr));gap:.75rem;margin:0 0 1.25rem}
.agent-stat{background:var(--card,#fff);border-radius:16px;padding:.9rem 1rem;box-shadow:0 1px 0 rgba(0,0,0,.04)}
.agent-stat span{display:block;font-size:.75rem;color:var(--secondary-label,#6e6e73);text-transform:uppercase;letter-spacing:.04em}
.agent-stat strong{display:block;font-size:1.6rem;letter-spacing:-.02em;margin-top:.15rem}
.case-card{background:var(--card,#fff);border-radius:18px;padding:1rem 1.1rem;margin:0 0 .75rem;box-shadow:0 1px 0 rgba(0,0,0,.04)}
.case-card.needs{border-left:4px solid #ff3b30}
.case-head{display:flex;justify-content:space-between;gap:.75rem;align-items:baseline;flex-wrap:wrap}
.case-head a{font-weight:650;color:inherit;text-decoration:none}
.case-meta{font-size:.82rem;color:var(--secondary-label,#6e6e73)}
.case-evidence{margin:.55rem 0 .7rem;padding-left:1.1rem;font-size:.9rem}
.case-evidence li{margin:.15rem 0}
.option-row{display:flex;flex-wrap:wrap;gap:.5rem}
.option-row form{margin:0}
.state-pill{display:inline-block;font-size:.75rem;font-weight:600;border-radius:999px;padding:.15rem .6rem;background:rgba(0,122,255,.12);color:#0a64d6}
.state-pill.closed{background:rgba(52,199,89,.14);color:#1f8a3a}
.state-pill.needs_coach{background:rgba(255,59,48,.12);color:#c9281e}
.timeline{list-style:none;margin:0;padding:0}
.timeline li{display:grid;grid-template-columns:5.5rem 5.5rem 1fr;gap:.6rem;padding:.55rem 0;border-top:1px solid rgba(60,60,67,.12);font-size:.88rem}
.timeline li:first-child{border-top:0}
.timeline time{color:var(--secondary-label,#6e6e73);font-variant-numeric:tabular-nums}
.kind{font-size:.72rem;font-weight:650;text-transform:uppercase;letter-spacing:.04em;color:#0a64d6}
.kind.escalation{color:#c9281e}.kind.outcome{color:#1f8a3a}.kind.adaptation{color:#8e44ad}.kind.coach{color:#b8620b}
.timeline .who{font-weight:600}
.timeline pre{white-space:pre-wrap;font:inherit;background:rgba(118,118,128,.08);border-radius:10px;padding:.5rem .65rem;margin:.35rem 0 0}
.learned{background:linear-gradient(135deg,rgba(142,68,173,.08),rgba(0,122,255,.06));border-radius:18px;padding:1rem 1.1rem;margin:0 0 .75rem}
.learned b{font-variant-numeric:tabular-nums}
.plan-table{width:100%;border-collapse:collapse;font-size:.9rem}
.plan-table th,.plan-table td{text-align:left;padding:.45rem .3rem;border-top:1px solid var(--separator)}
@media (max-width:720px){.agent-strip{grid-template-columns:repeat(2,minmax(0,1fr))}
.timeline li{grid-template-columns:4.5rem 1fr}.timeline li .kind{grid-column:2}}
"""


def _zone(name: str | None) -> ZoneInfo:
    try:
        return ZoneInfo(name or "UTC")
    except (ZoneInfoNotFoundError, ValueError):
        return ZoneInfo("UTC")


def when(stamp: str | None, tz: str | None, fmt: str = "%a %H:%M") -> str:
    if not stamp:
        return "—"
    try:
        return datetime.fromisoformat(str(stamp)).astimezone(_zone(tz)).strftime(fmt)
    except ValueError:
        return str(stamp)


def _pill(state: str) -> str:
    return f'<span class="state-pill {escape(state)}">{escape(STATE_LABELS.get(state, state))}</span>'


def decision_forms(case_id: int, options, *, return_to: str) -> str:
    forms = []
    for index, (code, label) in enumerate(options):
        style = "btn btn-primary" if index == 0 else "btn btn-ghost"
        forms.append(
            f'<form method="post" action="/coach/case/{int(case_id)}/decide">'
            f'<input type="hidden" name="option" value="{escape(code)}">'
            f'<input type="hidden" name="return_to" value="{escape(return_to)}">'
            f'<button class="{style} btn-sm" type="submit">{escape(label)}</button></form>'
        )
    return f'<div class="option-row">{"".join(forms)}</div>'


def _needs_card(case: dict, *, return_to: str) -> str:
    escalation = case["escalation"]
    evidence = "".join(f"<li>{escape(str(line))}</li>" for line in escalation.get("evidence", []))
    return (
        '<article class="case-card needs">'
        '<div class="case-head">'
        f'<a href="/coach/case/{int(case["id"])}">{escape(case["athlete_name"])} · '
        f'{escape(str(escalation.get("title", "Needs your decision")))}</a>'
        f'<span class="case-meta">{escape(case["local_date"])}</span></div>'
        f'<ul class="case-evidence">{evidence}</ul>'
        f'{decision_forms(case["id"], escalation.get("options", []), return_to=return_to)}'
        '</article>'
    )


def _open_row(case: dict) -> str:
    return (
        '<article class="case-card"><div class="case-head">'
        f'<a href="/coach/case/{int(case["id"])}">{escape(case["athlete_name"])}</a>{_pill(case["state"])}</div>'
        f'<div class="case-meta">Waiting for: {escape(case["waiting_for"] or "its first step")} · '
        f'next step {escape(when(case["next_action_at"], case["timezone"]))} ({escape(case["timezone"])})</div>'
        '</article>'
    )


def _completed_row(case: dict) -> str:
    outcome = OUTCOME_LABELS.get(case["outcome"] or "", case["outcome"] or "Closed")
    return (
        '<article class="case-card"><div class="case-head">'
        f'<a href="/coach/case/{int(case["id"])}">{escape(case["athlete_name"])}</a>'
        f'<span class="state-pill closed">{escape(outcome)}</span></div>'
        f'<div class="case-meta">{escape(case["local_date"])} · closed '
        f'{escape(when(case["closed_at"], case["timezone"]))}</div></article>'
    )


def timeline_items(events, *, with_names: bool, full: bool = False) -> str:
    rows = []
    for event in events:
        kind = str(event["kind"])
        detail = json.loads(event["detail_json"]) if event["detail_json"] else {}
        extra = ""
        if full and kind == "action" and isinstance(detail, dict) and detail.get("message"):
            status = f' · {escape(str(event["status"]))}' if event["status"] else ""
            extra = f'<pre>{escape(str(detail["message"]))}</pre><span class="case-meta">delivery{status}</span>'
        who = (
            f'<span class="who">{escape(event["athlete_name"])}</span> · ' if with_names else ""
        )
        link = (
            f' <a href="/coach/case/{int(event["case_id"])}">case</a>'
            if with_names and event["case_id"] is not None else ""
        )
        rows.append(
            f'<li><time>{escape(when(event["occurred_at"], event.get("timezone") if hasattr(event, "get") else None))}</time>'
            f'<span class="kind {escape(kind)}">{escape(KIND_LABELS.get(kind, kind))}</span>'
            f'<div>{who}{escape(str(event["summary"]))}{link}{extra}</div></li>'
        )
    return f'<ul class="timeline">{"".join(rows)}</ul>'


def demo_day_panel(board: Board, *, return_to: str = "/coach#demo-day") -> str:
    """The scripted demo day: clearly a simulation, separate from the real agent."""

    def step(action: str, label: str, style: str) -> str:
        return (
            f'<form method="post" action="/coach/demo/day/{action}">'
            f'<input type="hidden" name="return_to" value="{escape(return_to)}">'
            f'<button class="btn {style} btn-sm" type="submit">{escape(label)}</button></form>'
        )

    rows = []
    for case in board.simulated:
        if case["state"] == "needs_coach":
            rows.append(_needs_card(case, return_to=return_to))
        elif case["state"] == "closed":
            rows.append(_completed_row(case))
        else:
            rows.append(_open_row(case))
    cases = "".join(rows) or (
        '<div class="empty-card"><span>Not started. Play the morning to watch the agent run a '
        "whole training day.</span></div>"
    )
    return (
        '<section class="today-section" id="demo-day"><div class="section-head-row">'
        '<h2>Simulated demo day <span class="state-pill">Simulation</span></h2></div>'
        f'<p class="section-note">A scripted <b>{escape(board.demo_label)}</b> for the fictional '
        "demo squad. The simulation moves its own clock, so it works at any hour. It never touches "
        "real cases, real athletes or the real-time rules, and its messages go only to the in-app "
        "simulator. Play the morning, decide its exceptions below, then play the evening.</p>"
        f'<div class="option-row">{step("morning", "1. Play the morning", "btn-primary")}'
        f'{step("evening", "2. Play the evening", "btn-ghost")}'
        f'{step("reset", "Reset simulation", "btn-ghost")}</div>{cases}</section>'
    )


def render_case_body(case, events, *, athlete_name: str, message_banner: str) -> str:
    escalation = json.loads(case["escalation_json"]) if case["escalation_json"] else {}
    plan = json.loads(case["plan_json"]) if case["plan_json"] else []
    session = json.loads(case["session_json"]) if case["session_json"] else None
    readiness = (json.loads(case["readiness_json"]) or {}).get("checkin", {}) if case["readiness_json"] else {}

    def lifts(items) -> str:
        if isinstance(items, dict):
            return escape(str(items.get("title", "Coach-approved plan")))
        return escape("; ".join(
            f"{item['lift'].title()} {item['sets']}×{item['reps']} @ RPE {item['rpe']:g}" for item in items
        )) or "—"

    facts = (
        ("State", STATE_LABELS.get(case["state"], case["state"])),
        ("Waiting for", case["waiting_for"] or "—"),
        ("Next step", f"{when(case['next_action_at'], case['timezone'], '%a %d %b %H:%M')} ({case['timezone']})"),
        ("Outcome", OUTCOME_LABELS.get(case["outcome"] or "", case["outcome"] or "Not known yet")),
        ("Check-in time", case["checkin_time"]),
        ("Follow-ups sent", str(case["follow_ups"])),
    )
    fact_html = "".join(
        f"<div><span>{escape(label)}</span><strong>{escape(str(value))}</strong></div>"
        for label, value in facts
    )
    checkin = ", ".join(f"{key.replace('_', ' ')} {value:g}" if isinstance(value, (int, float)) else f"{key} {value}"
                        for key, value in readiness.items()) or "No check-in yet"
    decide = ""
    if case["state"] == "needs_coach" and escalation:
        evidence = "".join(f"<li>{escape(str(line))}</li>" for line in escalation.get("evidence", []))
        case_url = "/coach/case/" + str(int(case["id"]))
        forms = decision_forms(case["id"], escalation.get("options", []), return_to=case_url)
        decide = (
            '<article class="case-card needs">'
            f'<div class="case-head"><strong>{escape(str(escalation.get("title", "")))}</strong></div>'
            f'<ul class="case-evidence">{evidence}</ul>{forms}'
            '</article>'
        )
    return (
        f"{message_banner}{decide}"
        '<section class="today-section"><div class="evidence-grid">'
        f"{fact_html}</div>"
        f'<p class="evidence-reason"><b>Coach-approved plan:</b> {lifts(plan)}</p>'
        f'<p class="evidence-reason"><b>Delivered session:</b> {lifts(session) if session else "Not sent"}</p>'
        f'<p class="evidence-reason"><b>Check-in:</b> {escape(checkin)}</p></section>'
        '<section class="today-section"><div class="section-head-row"><h2>Reasoning and actions</h2></div>'
        f'<div class="list-card">{timeline_items([dict(e, timezone=case["timezone"]) for e in events], with_names=False, full=True)}</div>'
        "</section>"
    )


def athlete_agent_panel(
    athlete_id: str, state: dict, *, default_weekday: int | None = None, autopilot_decided: bool = True
) -> str:
    """The weekly plan, read-only until the coach chooses Edit plan, and the autopilot choice."""
    quoted = escape(athlete_id)
    settings = state["settings"]
    autopilot = bool(settings["autopilot"])
    plan_rows = state["plan"]

    def day(row) -> str:
        return WEEKDAYS[int(row["weekday"])]

    def lift(row) -> str:
        return escape(str(row["lift"]).title())

    def dose(row) -> str:
        return f"{int(row['sets'])}×{int(row['reps'])} · RPE {float(row['rpe']):g}"

    readonly = "".join(
        f"<li><span class='plan-day'>{day(row)}</span><span class='plan-lift'>{lift(row)}</span>"
        f"<span class='plan-dose'>{dose(row)}</span></li>"
        for row in plan_rows
    )
    editable = "".join(
        f"<li><span class='plan-day'>{day(row)}</span><span class='plan-lift'>{lift(row)}</span>"
        f"<span class='plan-dose'>{dose(row)}</span>"
        f"<form method='post' action='/coach/athlete/{quoted}/plan/retire'>"
        f"<input type='hidden' name='session_id' value='{int(row['id'])}'>"
        f"<button class='btn btn-ghost btn-sm' type='submit' aria-label='Remove {lift(row)} on {day(row)}'>"
        "Remove</button></form></li>"
        for row in plan_rows
    )
    current = (
        f"<ul class='plan-list'>{readonly}</ul>" if plan_rows else
        "<p class='plan-empty'>No approved plan yet, so the agent has no training days to run.</p>"
    )
    weekday_options = "".join(
        f"<option value='{i}'{' selected' if i == default_weekday else ''}>"
        f"{name}{' (today)' if i == default_weekday else ''}</option>"
        for i, name in enumerate(WEEKDAYS)
    )
    add_form = (
        f"<form class='plan-form' method='post' action='/coach/athlete/{quoted}/plan'>"
        "<h3>Add a session</h3><div class='plan-fields'>"
        f"<div class='field field-day'><label for='plan-weekday'>Day</label>"
        f"<select id='plan-weekday' name='weekday'>{weekday_options}</select></div>"
        "<div class='field field-lift'><label for='plan-lift'>Lift</label>"
        "<input id='plan-lift' name='lift' type='text' required maxlength='40' placeholder='e.g. Squat' "
        "autocomplete='off'></div>"
        "<div class='field field-num'><label for='plan-sets'>Sets</label>"
        "<input id='plan-sets' name='sets' type='number' inputmode='numeric' min='1' max='20' value='3' required></div>"
        "<div class='field field-num'><label for='plan-reps'>Reps</label>"
        "<input id='plan-reps' name='reps' type='number' inputmode='numeric' min='1' max='30' value='5' required></div>"
        "<div class='field field-num'><label for='plan-rpe'>RPE</label>"
        "<input id='plan-rpe' name='rpe' type='number' inputmode='decimal' min='5' max='10' step='0.5' value='7' "
        "required></div></div>"
        "<div class='plan-form-foot'><p>Only sessions you add here can ever be delivered.</p>"
        "<button class='btn btn-primary' type='submit'>Add to weekly plan</button></div></form>"
    )
    editor = (
        f"<details class='plan-editor'{'' if plan_rows else ' open'}>"
        "<summary class='btn btn-ghost btn-sm'>Edit plan</summary><div class='plan-editor-body'>"
        + (f"<ul class='plan-list plan-list-edit'>{editable}</ul>" if plan_rows else "")
        + f"{add_form}</div></details>"
    )

    def autopilot_form(value: str, label: str, primary: bool) -> str:
        return (
            f"<form method='post' action='/coach/athlete/{quoted}/autopilot'>"
            f"<input type='hidden' name='enabled' value='{value}'>"
            f"<button class='btn {'btn-primary' if primary else 'btn-ghost'} btn-sm' type='submit'>{label}</button></form>"
        )

    if not autopilot_decided:
        badge = "<span class='status-badge'>Not decided</span>"
        summary = "<b>Autopilot not decided.</b> Every session waits for your approval."
        controls = autopilot_form("on", "Turn autopilot on", True) + autopilot_form("off", "Keep autopilot off", False)
    elif autopilot:
        badge = ("<span class='status-badge ready'>On</span>" if plan_rows
                 else "<span class='status-badge'>On, idle</span>")
        summary = "<b>Autopilot on.</b> Routine days go out without you."
        controls = autopilot_form("off", "Turn autopilot off", False)
    else:
        badge = "<span class='status-badge off'>Off</span>"
        summary = "<b>Autopilot off.</b> Every session waits for your approval."
        controls = autopilot_form("on", "Turn autopilot on", False)
    adaptation = state["adaptation"]
    checkin_note = (
        f"Check-in moved to {escape(adaptation['new_value'])} (was {escape(adaptation['old_value'])}). "
        f"{escape(adaptation['explanation'])}"
        if adaptation is not None else "Check-in at the athlete's usual time."
    )
    cases = "".join(
        f"<li><a href='/coach/case/{int(case['id'])}'>{escape(case['local_date'])}</a> · "
        f"{escape(OUTCOME_LABELS.get(case['outcome'] or '', STATE_LABELS.get(case['state'], case['state'])))}</li>"
        for case in state["cases"]
    ) or "<li>No training days yet.</li>"
    return (
        "<div class='agent-panels'>"
        "<section class='panel agent-panel' id='agent-plan'>"
        "<div class='panel-head'><h2>Weekly plan</h2>"
        "<details class='why'><summary>Why?</summary><p>Only sessions you approve here are ever sent. "
        "On a bad day the agent can hold or reduce one; it never adds training.</p></details></div>"
        f"{current}{editor}</section>"
        "<section class='panel agent-panel' id='autopilot'>"
        f"<div class='panel-head'><h2>Autopilot</h2>{badge}</div>"
        f"<p class='section-note'>{summary}</p><div class='status-actions'>{controls}</div>"
        "<details class='recent-days'><summary>Recent training days</summary>"
        f"<p class='case-meta autopilot-checkin'>{checkin_note}</p>"
        f"<ul class='case-evidence'>{cases}</ul></details></section>"
        "</div>"
    )

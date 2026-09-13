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
.plan-table th,.plan-table td{text-align:left;padding:.45rem .3rem;border-top:1px solid rgba(60,60,67,.12)}
.plan-form{display:grid;grid-template-columns:repeat(auto-fit,minmax(7rem,1fr));gap:.5rem;align-items:end;margin-top:.75rem}
.plan-form label{display:flex;flex-direction:column;font-size:.75rem;gap:.2rem}
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


def _learned_card(item: dict) -> str:
    after = (
        f"Since then: median <b>{item['after_median']} min</b> over {item['after_samples']} day(s)."
        if item["after_median"] is not None else "Measuring the effect: no replies at the new time yet."
    )
    return (
        '<div class="learned">'
        f'<strong>{escape(item["athlete_name"])}: check-in {escape(item["old_value"])} → '
        f'{escape(item["new_value"])}</strong>'
        f'<p>{escape(item["explanation"])}</p>'
        f'<p class="case-meta">Before: median <b>{escape(str(item["before_median"]))} min</b> to reply. '
        f'{after}</p></div>'
    )


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


def agent_board(board: Board, *, return_to: str = "/coach", blocker: str | None = None) -> str:
    stats = (
        ("Needs you", len(board.needs_coach)),
        ("In progress", len(board.open_cases)),
        ("Closed today", len(board.completed)),
        ("Messages sent", board.messages_sent),
    )
    strip = '<div class="agent-strip">' + "".join(
        f'<div class="agent-stat"><span>{label}</span><strong>{value}</strong></div>'
        for label, value in stats
    ) + "</div>"

    if not board.planned_athletes:
        intro = (
            '<div class="empty-card"><strong>The agent has no training days to own yet.</strong>'
            "<span>Open an athlete, add their coach-approved weekly plan (sets, reps, RPE) and "
            "the agent will run each training day from check-in to outcome.</span></div>"
        )
    else:
        intro = ""
    coach_notice = (
        "" if board.coach_linked else
        '<div class="msg warn">Escalations wait here only: link your Telegram by sending '
        "<b>/coach &lt;setup code&gt;</b> to the bot to get them with decision buttons.</div>"
    )

    needs = (
        '<section class="today-section"><div class="section-head-row">'
        f'<h2>Exceptions for you <span class="n">{len(board.needs_coach)}</span></h2></div>'
        + "".join(_needs_card(case, return_to=return_to) for case in board.needs_coach)
        + "</section>"
        if board.needs_coach else ""
    )
    waiting = (
        '<section class="today-section"><div class="section-head-row">'
        f'<h2>Open cases <span class="n">{len(board.open_cases)}</span></h2></div>'
        + ("".join(_open_row(case) for case in board.open_cases)
           or '<div class="empty-card"><span>No training day is in progress.</span></div>')
        + "</section>"
    )
    done = (
        '<section class="today-section"><div class="section-head-row">'
        f'<h2>Completed by the agent <span class="n">{len(board.completed)}</span></h2></div>'
        + ("".join(_completed_row(case) for case in board.completed)
           or '<div class="empty-card"><span>Nothing closed in the last 24 hours.</span></div>')
        + "</section>"
    )
    learned = (
        '<section class="today-section"><div class="section-head-row"><h2>What the agent adapted</h2></div>'
        + ("".join(_learned_card(item) for item in board.learned)
           or '<div class="empty-card"><span>No adaptations yet. After four late check-in replies '
              "the agent may move that athlete's check-in later, within fixed limits.</span></div>")
        + "</section>"
    )
    timeline = (
        '<section class="today-section"><div class="section-head-row"><h2>Agent timeline</h2>'
        '<form method="post" action="/coach/agent/run">'
        f'<input type="hidden" name="return_to" value="{escape(return_to)}">'
        '<button class="btn btn-ghost btn-sm" type="submit">Run agent now (real time)</button></form></div>'
        + (f'<div class="list-card">{timeline_items(board.timeline, with_names=True)}</div>'
           if board.timeline else '<div class="empty-card"><span>No agent activity yet.</span></div>')
        + "</section>"
    )
    blocked = (
        f'<div class="msg err" role="alert"><b>Agent blocked.</b> {escape(blocker)}</div>'
        if blocker else ""
    )
    return (
        f"{blocked}{strip}{coach_notice}{intro}{needs}{waiting}{done}{timeline}{learned}"
        f"{demo_day_panel(board)}"
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


def athlete_agent_panel(athlete_id: str, state: dict) -> str:
    quoted = escape(athlete_id)
    settings = state["settings"]
    autopilot = settings["autopilot"]
    rows = "".join(
        f"<tr><td>{WEEKDAYS[int(row['weekday'])]}</td><td>{escape(str(row['lift']).title())}</td>"
        f"<td>{int(row['sets'])}×{int(row['reps'])}</td><td>RPE {float(row['rpe']):g}</td>"
        f"<td><form method='post' action='/coach/athlete/{quoted}/plan/retire'>"
        f"<input type='hidden' name='session_id' value='{int(row['id'])}'>"
        "<button class='btn btn-ghost btn-sm' type='submit'>Remove</button></form></td></tr>"
        for row in state["plan"]
    )
    table = (
        f"<table class='plan-table'><thead><tr><th>Day</th><th>Lift</th><th>Sets×reps</th><th>Target</th><th></th></tr></thead>"
        f"<tbody>{rows}</tbody></table>"
        if rows else "<p class='section-note'>No approved plan yet, so the agent will not open training days.</p>"
    )
    weekday_options = "".join(f"<option value='{i}'>{name}</option>" for i, name in enumerate(WEEKDAYS))
    add_form = (
        f"<form class='plan-form' method='post' action='/coach/athlete/{quoted}/plan'>"
        f"<label>Day<select name='weekday'>{weekday_options}</select></label>"
        "<label>Lift<input name='lift' required maxlength='40' placeholder='squat'></label>"
        "<label>Sets<input name='sets' type='number' min='1' max='20' value='3' required></label>"
        "<label>Reps<input name='reps' type='number' min='1' max='30' value='5' required></label>"
        "<label>RPE<input name='rpe' type='number' min='5' max='10' step='0.5' value='7' required></label>"
        "<button class='btn btn-primary btn-sm' type='submit'>Approve lift</button></form>"
    )
    toggle = (
        f"<form method='post' action='/coach/athlete/{quoted}/autopilot'>"
        f"<input type='hidden' name='enabled' value='{'off' if autopilot else 'on'}'>"
        f"<button class='btn {'btn-ghost' if autopilot else 'btn-primary'} btn-sm' type='submit'>"
        f"{'Turn autopilot off' if autopilot else 'Turn autopilot on'}</button></form>"
    )
    adaptation = state["adaptation"]
    checkin_note = (
        f"Check-in adapted to {escape(adaptation['new_value'])} (was {escape(adaptation['old_value'])}). "
        f"{escape(adaptation['explanation'])}"
        if adaptation is not None else "Check-in uses the athlete's configured time."
    )
    cases = "".join(
        f"<li><a href='/coach/case/{int(case['id'])}'>{escape(case['local_date'])}</a> · "
        f"{escape(OUTCOME_LABELS.get(case['outcome'] or '', STATE_LABELS.get(case['state'], case['state'])))}</li>"
        for case in state["cases"]
    ) or "<li>No training days yet.</li>"
    return (
        "<section class='panel' id='agent-plan'>"
        "<div class='panel-head'><h2>Training-day agent</h2></div>"
        f"<p class='section-note'><b>Autopilot {'on' if autopilot else 'off'}.</b> "
        + ("Routine days are delivered without you; the session is only ever held or reduced. "
           if autopilot else "Every session waits for your approval before it is sent. ")
        + f"{checkin_note}</p>{toggle}"
        f"<h3>Approved weekly plan</h3>{table}{add_form}"
        f"<h3>Recent training days</h3><ul class='case-evidence'>{cases}</ul></section>"
    )

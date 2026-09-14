"""The coach console: what needs the coach, what the agent handled, what happens next.

Today leads with the coach's decisions. Routine work the agent finished is a
compact feed, upcoming work is a short list, and the squad is summarised by
state. Explanations of how the agent works belong on the public site and in the
README, not here; anything longer than a label sits behind a "Why?" disclosure.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from html import escape
from urllib.parse import quote

from app.casework.board import Board
from app.casework.engine import STATE_LABELS
from app.casework.status import WAITING_FOR_DECISION, AthleteStatus, next_setup_step
from app.coach.agent_view import decision_forms, demo_day_panel, when
from app.coach.onboarding_view import PAIRING_FAILURE_OUTCOMES
from app.coach.roster import PendingMessage, RosterEntry
from app.coach.view import banner, coach_frame, initials
from app.scheduling.outbox import message_kind_label

__all__ = [
    "AthleteRow", "PAIRING_FAILURE_OUTCOMES", "athlete_state", "connection_state",
    "render_roster", "render_today",
]

# Routine work only: escalations already sit in Needs you, and coach notifications are plumbing.
FEED_KINDS = {"action", "outcome", "adaptation", "coach"}
FEED_HIDDEN_CODES = {"coach_notified"}
FEED_VISIBLE = 6
NEXT_VISIBLE = 8

STATE_ORDER = ("attention", "blocked", "setup", "running", "ready")
STATE_LABELS_SHORT = {
    "attention": ("Needs you", "red"),
    "blocked": ("Blocked", "red"),
    "setup": ("Awaiting setup", "orange"),
    "running": ("Running", "green"),
    "ready": ("Ready", "blue"),
}


@dataclass
class AthleteRow:
    """One athlete as the console sees them: roster signals plus agent readiness."""

    entry: RosterEntry
    status: AthleteStatus
    pairing_failed: bool = False
    pairing_label: str | None = None

    @property
    def athlete_id(self) -> str:
        return self.entry.athlete_id

    @property
    def name(self) -> str:
        return self.entry.display_name

    @property
    def first_name(self) -> str:
        return self.name.split()[0] if self.entry.name else self.name

    @property
    def url(self) -> str:
        return f"/coach/athlete/{quote(self.athlete_id)}"


def athlete_state(row: AthleteRow) -> tuple[str, str, str]:
    """(key, label, tone): the one status an athlete has in the console."""
    status, entry = row.status, row.entry
    problems = [b for b in status.blockers if b not in status.setup_gaps and b != WAITING_FOR_DECISION]
    if status.waiting_case_id or entry.needs_action or row.pairing_failed:
        key = "attention"
    elif problems:
        key = "blocked"
    elif status.setup_gaps or not status.autopilot_decided:
        key = "setup"
    elif status.autopilot:
        key = "running"
    else:
        key = "ready"
    label, tone = STATE_LABELS_SHORT[key]
    return key, label, tone


def connection_state(row: AthleteRow) -> tuple[str, str]:
    status = row.status
    if status.demo:
        return "Demo", "grey"
    if status.telegram_connected:
        return "Connected", "green"
    if not status.telegram_available:
        return "No bot", "grey"
    if row.pairing_failed:
        return "Invite failed", "red"
    return "Not connected", "orange"


def _next_short(row: AthleteRow) -> str:
    key, _, _ = athlete_state(row)
    status = row.status
    if row.pairing_failed:
        return "Send a fresh invite"
    if status.waiting_case_id:
        return "Decide today's session"
    if row.entry.needs_action:
        return "Review clearance"
    if key == "blocked":
        return "Fix the blocker"
    if key == "setup":
        return next_setup_step(status)[0]
    return status.next_action


def _chip(label: str, tone: str, *, title: str = "") -> str:
    title_attr = f' title="{escape(title)}"' if title else ""
    return f'<span class="chip chip-{tone}"{title_attr}>{escape(label)}</span>'


def _why(lines: list[str]) -> str:
    lines = [line for line in lines if line]
    if not lines:
        return ""
    return (
        '<details class="why"><summary>Why?</summary><ul>'
        + "".join(f"<li>{escape(line)}</li>" for line in lines)
        + "</ul></details>"
    )


def _link(label: str, href: str, *, primary: bool = False) -> str:
    return (
        f'<a class="btn {"btn-primary" if primary else "btn-ghost"} btn-sm" href="{escape(href)}">'
        f"{escape(label)}</a>"
    )


def _card(
    *, kind: str, row: AthleteRow | None, name: str, href: str, problem: str, chip: tuple[str, str],
    evidence: list[str], why: list[str], recommended: str | None, controls: str, extra: str = "",
    timeline_href: str | None = None,
) -> str:
    shown = [line for line in evidence if line][:2]
    hidden = [line for line in evidence if line][2:] + why
    timeline = (
        f' · <a class="decision-timeline" href="{escape(timeline_href)}">Timeline</a>' if timeline_href else ""
    )
    return (
        f'<article class="decision" data-kind="{kind}">'
        '<header class="decision-head">'
        f'<span class="avatar" aria-hidden="true">{escape(initials(name))}</span>'
        f'<div><h3><a href="{escape(href)}">{escape(name)}</a></h3>'
        f'<p class="decision-problem">{escape(problem)}{timeline}</p></div>'
        f"{_chip(*chip)}</header>"
        + (f'<ul class="decision-evidence">{"".join(f"<li>{escape(line)}</li>" for line in shown)}</ul>'
           if shown else "")
        + extra
        + _why(hidden)
        + (f'<p class="rec"><span class="rec-label">Recommended</span>{escape(recommended)}</p>'
           if recommended else "")
        + f'<div class="decision-controls">{controls}</div></article>'
    )


def _pause_control(row: AthleteRow | None) -> str:
    if row is None or not row.status.autopilot or row.status.demo:
        return ""
    return (
        f'<form method="post" action="{escape(row.url)}/autopilot">'
        '<input type="hidden" name="enabled" value="off">'
        '<button class="btn btn-ghost btn-sm" type="submit">Pause autopilot</button></form>'
    )


def _message_control(row: AthleteRow | None, href: str) -> str:
    if row is not None and not (row.status.telegram_connected or row.status.demo):
        return ""
    return _link("Message", f"{href}#messages")


_MODIFY_ANCHOR = {"injury_open": "injury-plan", "autopilot_off": "agent-plan", "readiness_red": "agent-plan"}


def _case_card(case: dict, row: AthleteRow | None) -> str:
    escalation = case.get("escalation") or {}
    code = str(escalation.get("code") or "")
    options = [tuple(option) for option in escalation.get("options", [])]
    href = row.url if row else f"/coach/athlete/{quote(str(case['athlete_id']))}"
    anchor = _MODIFY_ANCHOR.get(code)
    modify = _link("Modify", f"{href}#{anchor}") if anchor else ""
    controls = (
        decision_forms(int(case["id"]), options, return_to="/coach")
        + modify + _pause_control(row) + _message_control(row, href)
    )
    return _card(
        kind="case", row=row, name=str(case["athlete_name"]), href=href,
        problem=str(escalation.get("title", "Needs your decision")),
        chip=("Needs a decision", "red"),
        evidence=[str(line) for line in escalation.get("evidence", [])],
        why=[f"Training day {case['local_date']}"],
        recommended=str(options[0][1]) if options else None, controls=controls,
        timeline_href=f"/coach/case/{int(case['id'])}",
    )


def _flag(entry: RosterEntry, kind: str) -> str:
    return next((flag.detail for flag in entry.flags if flag.kind == kind), "")


def _clearance_card(row: AthleteRow) -> str:
    return _card(
        kind="clearance", row=row, name=row.name, href=row.url, problem="Asked to be cleared",
        chip=("Needs a decision", "red"), evidence=[_flag(row.entry, "clearance_requested")], why=[],
        recommended="Review the clearance with a named source",
        controls=_link("Review clearance", f"{row.url}#clearance-review", primary=True)
        + _message_control(row, row.url),
    )


def _injury_card(row: AthleteRow) -> str:
    return _card(
        kind="injury", row=row, name=row.name, href=row.url, problem="Injury reported",
        chip=("Needs a decision", "red"), evidence=[_flag(row.entry, "injured")], why=[],
        recommended="Choose an injury plan",
        controls=_link("Choose plan", f"{row.url}#injury-plan", primary=True)
        + _pause_control(row) + _message_control(row, row.url),
    )


def _pairing_card(row: AthleteRow) -> str:
    return _card(
        kind="setup", row=row, name=row.name, href=row.url, problem="Telegram invite didn't work",
        chip=("Invite failed", "red"), evidence=[row.pairing_label or ""], why=[],
        recommended="Send a fresh invite",
        controls=_link("Fix invite", f"{row.url}#telegram", primary=True),
    )


def _failure_card(failure: dict, row: AthleteRow | None) -> str:
    athlete_id = str(failure["athlete_id"])
    href = row.url if row else f"/coach/athlete/{quote(athlete_id)}"
    zone = row.status.timezone if row else "UTC"
    body = " ".join(str(failure.get("body") or "").split())
    excerpt = body if len(body) <= 110 else body[:107].rstrip() + "…"
    connection = (
        _link("Check connection", f"{href}#telegram")
        if row is not None and not (row.status.telegram_connected or row.status.demo) else ""
    )
    return _card(
        kind="failure", row=row, name=row.name if row else athlete_id, href=href,
        problem="Message not delivered", chip=("Failed", "red"),
        evidence=[
            f"{message_kind_label(str(failure.get('message_kind') or ''))} · "
            f"{when(str(failure.get('occurred_at') or ''), zone, '%d %b %H:%M')}",
            f"“{excerpt}”" if excerpt else "",
        ],
        why=[f"Error: {failure['error']}" if failure.get("error") else ""],
        recommended="Check the connection, then resend from Messages",
        controls=_link("Open messages", f"{href}#messages", primary=True) + connection,
    )


def _approval_card(item: PendingMessage, row: AthleteRow | None) -> str:
    athlete = item.athlete
    href = f"/coach/athlete/{quote(item.athlete_id)}"
    readiness = (
        f"Readiness {athlete.readiness_score}/100 ({athlete.readiness_band})"
        if athlete.readiness_score is not None else "No check-in today"
    )
    why = [
        " · ".join(flag.detail for flag in athlete.flags) or "Nothing flagged",
        readiness, f"Latest session: {athlete.latest_session or 'nothing logged'}",
    ]
    form = (
        '<form class="decision-form" method="post" action="/coach/whatsapp/review">'
        f'<input type="hidden" name="athlete_id" value="{escape(item.athlete_id)}">'
        f'<input type="hidden" name="message_kind" value="{escape(item.message_kind)}">'
        f'<input type="hidden" name="local_date" value="{escape(item.local_date)}">'
        '<input type="hidden" name="return_to" value="/coach">'
        '<details class="edit"><summary class="btn btn-ghost btn-sm">Modify</summary>'
        f'<label class="visually-hidden" for="draft-{escape(item.athlete_id)}-{escape(item.local_date)}">Message</label>'
        f'<textarea id="draft-{escape(item.athlete_id)}-{escape(item.local_date)}" name="body" maxlength="1400">'
        f"{escape(item.body)}</textarea></details>"
        '<div class="decision-controls">'
        '<button class="btn btn-primary btn-sm" type="submit" name="decision" value="approved">Approve</button>'
        '<button class="btn btn-ghost btn-sm" type="submit" name="decision" value="skipped">Hold</button>'
        f"{_message_control(row, href)}</div></form>"
    )
    return (
        _card(
            kind="approval", row=row, name=athlete.display_name, href=href,
            problem=f"{message_kind_label(item.message_kind)} waiting for approval",
            chip=("Approval", "orange"), evidence=[], why=why, recommended=None, controls="",
            extra=f'<blockquote class="decision-quote">{escape(item.body)}</blockquote>',
        ).replace('<div class="decision-controls"></div></article>', f"{form}</article>")
    )


def _feed_item(event: dict) -> str:
    kind = str(event["kind"])
    tone = {"escalation": " is-alert", "outcome": " is-done"}.get(kind, "")
    return (
        f'<li class="feed-item{tone}"><time>{escape(when(event["occurred_at"], event.get("timezone"), "%H:%M"))}</time>'
        f'<div><b>{escape(str(event["athlete_name"]))}</b> · '
        f'<span class="feed-text">{escape(str(event["summary"]))}</span></div></li>'
    )


def _adaptation_item(item: dict) -> str:
    before = item.get("before_median")
    after = (
        f"Since then: median {item['after_median']} min over {item['after_samples']} day(s)."
        if item.get("after_median") is not None else "No replies at the new time yet."
    )
    return (
        f'<li class="feed-item is-adapted"><time>{escape(when(item.get("created_at"), None, "%d %b"))}</time>'
        f'<div><span class="feed-text">{escape(item["athlete_name"])}: check-in '
        f'{escape(item["old_value"])} → {escape(item["new_value"])}</span>'
        + _why([str(item["explanation"]),
                f"Before: median {before} min to reply." if before is not None else "", after])
        + "</div></li>"
    )


def _activity(board: Board) -> str:
    events = [
        event for event in board.timeline
        if str(event["kind"]) in FEED_KINDS and str(event.get("code") or "") not in FEED_HIDDEN_CODES
    ]
    visible, older = events[:FEED_VISIBLE], events[FEED_VISIBLE:]
    adapted = "".join(_adaptation_item(item) for item in board.learned)
    if not events and not adapted:
        content = '<p class="ops-empty">Nothing handled in the last day.</p>'
    else:
        content = (
            f'<ul class="feed">{adapted}{"".join(_feed_item(event) for event in visible)}</ul>'
            + (f'<details class="feed-more"><summary>Show {len(older)} more</summary>'
               f'<ul class="feed">{"".join(_feed_item(event) for event in older)}</ul></details>'
               if older else "")
        )
    return (
        '<section id="activity" class="ops-section" aria-labelledby="activity-title">'
        '<div class="ops-head"><h2 id="activity-title">Handled by the agent</h2>'
        f'<span class="n">{board.messages_sent} sent in 24h</span></div>{content}</section>'
    )


_CLOCK = re.compile(r"\b(\d{2}:\d{2})\b")


def _next_up(board: Board, rows: list[AthleteRow]) -> tuple[str, int, str | None]:
    """The work coming next, how many check-ins that is, and the soonest item's label."""
    items: list[str] = []
    labels: list[str] = []
    upcoming = 0
    busy = set()
    for case in sorted(board.open_cases, key=lambda c: str(c["next_action_at"] or "~")):
        busy.add(str(case["athlete_id"]))
        waiting = str(case["waiting_for"] or STATE_LABELS.get(str(case["state"]), "Working"))
        waiting = waiting[:1].lower() + waiting[1:]
        at = when(case["next_action_at"], case["timezone"], "%H:%M") if case["next_action_at"] else ""
        if case["state"] in {"scheduled", "awaiting_checkin"}:
            upcoming += 1
        text = f"Waiting for {waiting}"
        items.append(
            f'<li class="feed-item"><time>{escape(at)}</time><div><b>{escape(str(case["athlete_name"]))}</b> · '
            f'<span class="feed-text">{escape(text)}</span></div></li>'
        )
        labels.append(f"{case['athlete_name']} · {text}" + (f" at {at}" if at else ""))
    for row in rows:
        if row.athlete_id in busy or not row.status.next_action.startswith("Check-in"):
            continue
        upcoming += 1
        clock = _CLOCK.search(row.status.next_action)
        items.append(
            f'<li class="feed-item"><time>{escape(clock.group(1) if clock else "")}</time>'
            f'<div><b>{escape(row.name)}</b> · <span class="feed-text">{escape(row.status.next_action)}</span></div></li>'
        )
        labels.append(f"{row.name} · {row.status.next_action}")
    visible, older = items[:NEXT_VISIBLE], items[NEXT_VISIBLE:]
    content = (
        f'<ul class="feed">{"".join(visible)}</ul>'
        + (f'<details class="feed-more"><summary>Show {len(older)} more</summary>'
           f'<ul class="feed">{"".join(older)}</ul></details>' if older else "")
        if items else '<p class="ops-empty">Nothing scheduled.</p>'
    )
    html = (
        '<section id="next" class="ops-section" aria-labelledby="next-title">'
        f'<div class="ops-head"><h2 id="next-title">What happens next</h2></div>{content}</section>'
    )
    return html, upcoming, labels[0] if labels else None


def _squad(rows: list[AthleteRow]) -> str:
    groups: dict[str, list[str]] = {key: [] for key in STATE_ORDER}
    for row in rows:
        groups[athlete_state(row)[0]].append(row.name)
    watch = [row.name for row in rows if row.entry.bucket.value == "watch"]
    chips = [
        f'<a href="/coach/athletes?state={key}" data-squad="{key}">'
        f'{_chip(f"{STATE_LABELS_SHORT[key][0]} {len(names)}", STATE_LABELS_SHORT[key][1], title=", ".join(names))}</a>'
        for key, names in groups.items() if names
    ]
    if watch:
        chips.append(
            f'<a href="/coach/athletes?state=watch" data-squad="watch">'
            f'{_chip(f"Watch {len(watch)}", "orange", title=", ".join(watch))}</a>'
        )
    return (
        '<section id="squad" class="ops-section" aria-labelledby="squad-title">'
        '<div class="ops-head"><h2 id="squad-title">Squad</h2>'
        '<a href="/coach/athletes">Open roster →</a></div>'
        f'<div class="squad-chips">{"".join(chips)}</div></section>'
    )


def _tools(board: Board, has_demo: bool) -> str:
    demo = (
        '<form method="post" action="/coach/demo/clear"><input type="hidden" name="return_to" value="/coach">'
        '<button class="btn btn-ghost btn-sm" type="submit">Remove demo athletes</button></form>'
        if has_demo else
        '<form method="post" action="/coach/demo/seed"><input type="hidden" name="return_to" value="/coach">'
        '<button class="btn btn-ghost btn-sm" type="submit">Load a demo squad</button></form>'
    )
    return (
        '<details id="tools" class="console-tools"><summary>Tools and simulation</summary>'
        '<div class="tools-row">'
        '<form method="post" action="/coach/agent/run"><input type="hidden" name="return_to" value="/coach">'
        '<button class="btn btn-ghost btn-sm" type="submit">Run agent now (real time)</button></form>'
        f"{demo}</div>{demo_day_panel(board)}</details>"
        "<script>(()=>{const t=document.getElementById('tools');const h=location.hash;"
        "if(t&&(h==='#tools'||h==='#demo-day')){t.open=true;const el=document.querySelector(h);"
        "if(el)el.scrollIntoView();}})();</script>"
    )


def render_today(
    *,
    rows: list[AthleteRow],
    board: Board,
    pending: tuple[PendingMessage, ...],
    injury_plan_titles: dict[str, str | None],
    failures: list[dict],
    setup_html: str,
    empty_html: str,
    has_demo: bool,
    blocker: str | None,
    coach: str,
    today: str,
    message: tuple[str, str] | None,
    extra_style: str,
) -> str:
    """Today: counts, the coach's decisions, the agent's finished work, what comes next, the squad."""
    frame = dict(active="overview", coach=coach, title="Today", subtitle="", today=today,
                 pending_count=len(pending), extra_style=extra_style)
    if empty_html:
        return coach_frame(f"{banner(message)}{empty_html}{setup_html}{_tools(board, has_demo)}", **frame)

    by_id = {row.athlete_id: row for row in rows}
    cards: list[str] = []
    decided_elsewhere = set()
    for case in board.needs_coach:
        cards.append(_case_card(case, by_id.get(str(case["athlete_id"]))))
        decided_elsewhere.add(str(case["athlete_id"]))
    for row in rows:
        if any(flag.kind == "clearance_requested" for flag in row.entry.flags):
            cards.append(_clearance_card(row))
        elif (row.athlete_id in injury_plan_titles and injury_plan_titles[row.athlete_id] is None
              and row.athlete_id not in decided_elsewhere):
            cards.append(_injury_card(row))
        if row.pairing_failed:
            cards.append(_pairing_card(row))
    undeliverable = {
        str(case["athlete_id"]) for case in board.needs_coach
        if (case.get("escalation") or {}).get("code") == "delivery_failed"
    }
    for failure in failures:
        if str(failure["athlete_id"]) not in undeliverable:
            cards.append(_failure_card(failure, by_id.get(str(failure["athlete_id"]))))
    for item in pending:
        cards.append(_approval_card(item, by_id.get(item.athlete_id)))

    next_html, upcoming, soonest = _next_up(board, rows)
    running = sum(1 for row in rows if row.status.ready and row.status.autopilot)
    counts = (
        ("decisions", "Decisions needed", len(cards), "#needs-you"),
        ("running", "Running automatically", running, "/coach/athletes?state=running"),
        ("upcoming", "Upcoming check-ins", upcoming, "#next"),
    )
    count_strip = '<nav class="ops-counts" aria-label="At a glance">' + "".join(
        f'<a class="count{" is-hot" if key == "decisions" and value else ""}" href="{href}" data-count="{key}">'
        f'<span class="count-num">{value}</span><span class="count-label">{label}</span></a>'
        for key, label, value, href in counts
    ) + "</nav>"

    needs = (
        '<section id="needs-you" class="ops-section" aria-labelledby="needs-title">'
        f'<div class="ops-head"><h2 id="needs-title">Needs you</h2><span class="n">{len(cards)}</span></div>'
        + ("".join(cards) if cards else
           '<div class="caught-up" data-caught-up><span class="check" aria-hidden="true">✓</span>'
           f'<div><strong>All caught up</strong><span>Next: {escape(soonest or "nothing scheduled")}</span></div></div>')
        + "</section>"
    )
    blocked = (
        f'<div class="msg err" role="alert"><b>Agent blocked.</b> {escape(blocker)}</div>' if blocker else ""
    )
    body = (
        f"{banner(message)}{blocked}{setup_html}{count_strip}"
        '<div class="ops-grid">'
        f'<div class="ops-main">{needs}</div>'
        f'<div class="ops-side">{_activity(board)}{next_html}{_squad(rows)}</div>'
        f"</div>{_tools(board, has_demo)}"
    )
    return coach_frame(body, **frame)


def render_roster(
    rows: list[AthleteRow],
    *,
    coach: str,
    today: str,
    message: tuple[str, str] | None = None,
    has_demo: bool = False,
    pending_count: int = 0,
    telegram_configured: bool = False,
    telegram_ready: bool = False,
    telegram_error: str | None = None,
) -> str:
    """One dense row per athlete: connection, readiness, next action and status."""
    ordered = sorted(rows, key=lambda row: (STATE_ORDER.index(athlete_state(row)[0]), row.name.lower()))
    records = []
    for row in ordered:
        key, label, tone = athlete_state(row)
        connection, connection_tone = connection_state(row)
        entry = row.entry
        signal = " · ".join(flag.detail for flag in entry.flags)
        readiness = (
            f'<span class="readiness-num {escape(entry.readiness_band or "")}" '
            f'title="{escape(entry.readiness_band or "")}">{entry.readiness_score}</span>'
            if entry.readiness_score is not None else '<span class="muted" title="No check-in today">—</span>'
        )
        next_action = _next_short(row)
        search = f"{row.name} {label} {connection} {signal} {next_action}".lower()
        records.append(
            f'<tr class="athlete-record" data-state="{key}" data-bucket="{entry.bucket.value}" '
            f'data-search="{escape(search)}">'
            f'<td data-col="athlete"><a class="roster-name" href="{escape(row.url)}">{escape(row.name)}</a>'
            + (f'<span class="roster-signal">{escape(signal)}</span>' if signal else "")
            + "</td>"
            f'<td data-col="connection">{_chip(connection, connection_tone)}</td>'
            f'<td data-col="readiness" data-label="Readiness">{readiness}</td>'
            f'<td data-col="next" data-label="Next">{escape(next_action)}</td>'
            f'<td data-col="status">{_chip(label, tone)}</td></tr>'
        )
    table = (
        '<table class="roster-table"><thead><tr><th scope="col">Athlete</th><th scope="col">Telegram</th>'
        '<th scope="col">Readiness</th><th scope="col">Next</th><th scope="col">Status</th></tr></thead>'
        f'<tbody>{"".join(records)}</tbody></table>'
        if records else '<p class="ops-empty">No athletes yet.</p>'
    )
    if telegram_ready:
        bot = _chip("Telegram bot connected", "green")
    elif telegram_configured:
        bot = (
            '<details class="why bot-why"><summary>'
            f'{_chip("Telegram webhook not ready", "orange")}</summary>'
            f"<p>{escape(telegram_error or 'Check the latest deployment log.')}</p></details>"
        )
    else:
        bot = ""
    filters = "".join(
        f'<option value="{value}">{label}</option>'
        for value, label in (("all", "All"), ("attention", "Needs you"), ("blocked", "Blocked"),
                             ("setup", "Awaiting setup"), ("running", "Running"), ("ready", "Ready"),
                             ("watch", "Watch"))
    )
    body = (
        f"{banner(message)}"
        '<div class="roster-bar"><div class="roster-tools">'
        '<input id="athlete-search" type="search" placeholder="Search" aria-label="Search athletes">'
        f'<select id="athlete-filter" aria-label="Filter by status">{filters}</select></div>'
        f'<div class="roster-actions">{bot}<a class="btn btn-primary btn-sm" href="/coach/athletes/new">Add athlete</a></div></div>'
        f"{table}"
        '<details class="console-tools"><summary>Demo squad</summary><div class="tools-row">'
        + (
            '<form method="post" action="/coach/demo/clear"><input type="hidden" name="return_to" value="/coach/athletes">'
            '<button class="btn btn-ghost btn-sm" type="submit">Remove demo athletes</button></form>'
            if has_demo else
            '<form method="post" action="/coach/demo/seed"><input type="hidden" name="return_to" value="/coach/athletes">'
            '<button class="btn btn-ghost btn-sm" type="submit">Load a demo squad</button></form>'
        )
        + "</div></details>"
        """<script>
(() => {
  const search = document.getElementById('athlete-search');
  const filter = document.getElementById('athlete-filter');
  const rows = [...document.querySelectorAll('.athlete-record')];
  const legacy = {needs_you: 'attention', fine: 'running', meet_prep: 'all'};
  function apply() {
    const q = search.value.trim().toLowerCase();
    const f = filter.value;
    rows.forEach((row) => {
      const matches = f === 'all' || row.dataset.state === f || (f === 'watch' && row.dataset.bucket === 'watch');
      row.hidden = !row.dataset.search.includes(q) || !matches;
    });
  }
  search.addEventListener('input', apply);
  filter.addEventListener('change', apply);
  const params = new URLSearchParams(location.search);
  let preset = params.get('state') || params.get('status');
  preset = legacy[preset] || preset;
  if (preset && [...filter.options].some((option) => option.value === preset)) { filter.value = preset; apply(); }
})();
</script>"""
    )
    return coach_frame(
        body, active="athletes", coach=coach, title="Athletes", subtitle="", today=today,
        pending_count=pending_count,
    )

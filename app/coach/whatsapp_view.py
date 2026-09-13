"""The coach's daily cross-channel messaging workspace.

This is deliberately a view over recorded messages and guarded drafts. It does
not infer intent, approve coaching, or send anything by itself.
"""

from __future__ import annotations

from datetime import date
from html import escape
from urllib.parse import quote

from app.coach.roster import PendingMessage
from app.coach.view import approval_card, banner, coach_frame, conversation_bubbles, initials
from app.scheduling.outbox import message_kind_label


def _tabs(active: str, counts: dict[str, int]) -> str:
    labels = (("inbox", "Inbox"), ("approval", "Needs approval"),
              ("scheduled", "Scheduled"), ("sent", "Sent"))
    return '<nav class="desk-tabs" aria-label="Messaging work states">' + "".join(
        f'<a class="{"active" if active == key else ""}" href="/coach/whatsapp?tab={key}">'
        f'{label} <b>{counts.get(key, 0)}</b></a>'
        for key, label in labels
    ) + "</nav>"


def _thread_list(conversations, selected: str | None, tab: str) -> str:
    if not conversations:
        return '<div class="desk-empty">No athlete conversations yet.</div>'
    rows = []
    for row in conversations:
        athlete_id = str(row["athlete_id"])
        name = str(row["athlete_name"] or athlete_id)
        body = str(row["body"])
        unread = int(row["unread_count"] or 0)
        direction = f"{unread} new" if unread else str(row["work_state"]).replace("_", " ").title()
        rows.append(
            f'<a class="thread-link {"active" if athlete_id == selected else ""}" '
            f'href="/coach/whatsapp?tab={quote(tab)}&athlete={quote(athlete_id)}">'
            f'<span class="avatar" aria-hidden="true">{escape(initials(name))}</span>'
            f'<div class="thread-name"><span>{escape(name)}</span>'
            f'<small class="{"unread" if unread else ""}">{escape(direction)}</small></div>'
            f'<div class="thread-preview">{escape(body)}</div></a>'
        )
    return "".join(rows)


def _conversation(messages, athlete_name: str, athlete_id: str) -> str:
    if not messages:
        return '<div class="desk-empty">Choose an athlete to open their conversation.</div>'
    return (
        '<div class="thread-panel-head">'
        f'<h2>{escape(athlete_name)}</h2>'
        f'<a href="/coach/athlete/{escape(athlete_id)}">Open profile →</a></div>'
        f'<div class="chat-stream">{conversation_bubbles(messages)}</div>'
        '<form class="thread-actions" method="post" action="/coach/whatsapp/reviewed">'
        f'<input type="hidden" name="athlete_id" value="{escape(athlete_id)}">'
        '<button class="skip" type="submit">Mark feedback reviewed</button></form>'
    )


def _who(athlete_id: str, names: dict[str, str], when: str) -> str:
    name = names.get(athlete_id, athlete_id)
    return (
        f'<div class="delivery-who"><span class="avatar" aria-hidden="true">{escape(initials(name))}</span>'
        f'<div><a class="athlete-name" href="/coach/athlete/{escape(athlete_id)}">{escape(name)}</a>'
        f'<p>{escape(when)}</p></div></div>'
    )


def _scheduled_list(rows, names: dict[str, str]) -> str:
    if not rows:
        return '<div class="desk-empty">No approved messages are waiting to send.</div>'
    return '<div class="delivery-list">' + "".join(
        '<div class="delivery-row">'
        f'{_who(str(row["athlete_id"]), names, str(row["local_date"]))}'
        f'<div><strong>{escape(message_kind_label(str(row["message_kind"])))}</strong>'
        f'<p>{escape(str(row["body"]))}</p></div>'
        '<span class="delivery-state tag-fine">Approved</span></div>'
        for row in rows
    ) + "</div>"


def _sent_list(rows, names: dict[str, str]) -> str:
    if not rows:
        return '<div class="desk-empty">No outbound delivery history yet.</div>'
    items = []
    for row in rows:
        status = str(row["status"])
        channel = str(row["channel"] or "whatsapp").capitalize()
        error = f' · error {row["error_code"]}' if row["error_code"] else ""
        items.append(
            '<div class="delivery-row">'
            f'{_who(str(row["athlete_id"]), names, str(row["occurred_at"]).replace("T", " ")[:16])}'
            f'<div><strong>{escape(message_kind_label(str(row["message_kind"])))}</strong>'
            f'<p>{escape(str(row["body"]))}</p></div>'
            f'<span class="delivery-state">{escape(channel)} · {escape(status + error)}</span></div>'
        )
    return '<div class="delivery-list">' + "".join(items) + "</div>"


def _simulator(demo_athletes: tuple[tuple[str, str], ...]) -> str:
    if not demo_athletes:
        return (
            '<details class="simulator"><summary>Test the messaging workflow</summary>'
            '<div style="padding:0 18px 18px" class="muted">Load the demo squad from '
            'Today first. Simulations are restricted to fictional demo numbers.</div></details>'
        )
    options = "".join(
        f'<option value="{escape(athlete_id)}">{escape(name)}</option>'
        for athlete_id, name in demo_athletes
    )
    return (
        '<details class="simulator"><summary>Test the messaging workflow</summary>'
        '<form method="post" action="/coach/whatsapp/simulate">'
        f'<select name="athlete_id">{options}</select>'
        '<textarea name="body" required maxlength="800" '
        'placeholder="Try: slept 5h, readiness 4, knee feels sore"></textarea>'
        '<button type="submit">Simulate message</button>'
        '<p>This writes a real demo conversation and approval draft, but sends no external message.</p>'
        '</form></details>'
    )


def render_whatsapp_desk(
    *,
    conversations,
    messages,
    pending: tuple[PendingMessage, ...],
    scheduled,
    sent,
    selected_athlete: str | None,
    selected_name: str,
    demo_athletes: tuple[tuple[str, str], ...],
    tab: str,
    coach: str,
    today: date,
    transport_ready: bool,
    transport_name: str = "Simulator",
    message: tuple[str, str] | None = None,
    names: dict[str, str] | None = None,
) -> str:
    """Render inbox, approval, schedule and delivery states in one daily desk."""
    names = names or {}
    counts = {
        "inbox": sum(int(row["unread_count"] or 0) for row in conversations),
        "approval": len(pending),
        "scheduled": len(scheduled),
        "sent": len(sent),
    }
    stats = (
        '<div class="desk-stats">'
        f'<div class="desk-stat"><strong>{counts["inbox"]}</strong><span>New feedback</span></div>'
        f'<div class="desk-stat"><strong>{counts["approval"]}</strong><span>Need approval</span></div>'
        f'<div class="desk-stat"><strong>{counts["scheduled"]}</strong><span>Scheduled</span></div>'
        f'<div class="desk-stat"><strong>{sum(1 for row in sent if row["status"] == "failed")}</strong><span>Delivery failed</span></div>'
        '</div>'
    )
    if tab == "approval":
        eligible = sum(1 for item in pending if item.bulk_eligible)
        bulk = (
            '<div class="approval-bar"><div><strong>Safe unchanged check-ins</strong>'
            f'<p>Untouched morning check-ins whose evidence has not changed: {eligible}.</p></div>'
            '<form method="post" action="/coach/whatsapp/bulk-approve">'
            f'<button id="bulk-approve" class="approve" type="submit" data-bulk-approve data-eligible="{eligible}"'
            f'{"" if eligible else " disabled"}>Approve unchanged ({eligible})</button></form></div>'
        )
        content = bulk + (
            '<div class="draft-stack">' + "".join(approval_card(item) for item in pending) + "</div>"
            if pending else '<div class="desk-empty">Nothing is waiting for approval.</div>'
        )
    elif tab == "scheduled":
        content = _scheduled_list(scheduled, names)
    elif tab == "sent":
        content = _sent_list(sent, names)
    else:
        if transport_ready:
            telegram_help = (
                ' <a href="/coach/athletes">Open an athlete profile to connect their Telegram chat →</a>'
                if "Telegram" in transport_name else ""
            )
            transport = (
                f'<div class="msg ok"><strong>{escape(transport_name)} is active.</strong> '
                "Approved messages use the athlete's connected channel."
                f'{telegram_help}</div>'
            )
        else:
            transport = (
                '<div class="msg warn"><strong>No live messaging channel is connected.</strong> '
                'Approvals and the audit trail still work; use the simulator below to test them.</div>'
            )
        content = (
            transport + _simulator(demo_athletes) +
            '<div class="desk-grid"><section class="thread-list"><h2>Conversations</h2>'
            f'{_thread_list(conversations, selected_athlete, tab)}</section>'
            f'<section class="thread-panel">{_conversation(messages, selected_name, selected_athlete or "")}</section></div>'
        )
    body = f"{banner(message)}{stats}{_tabs(tab, counts)}{content}"
    return coach_frame(
        body, active="whatsapp", coach=coach, title="Messaging Desk",
        subtitle="Every conversation, approval and delivery in one place.",
        today=today.isoformat(), pending_count=len(pending),
    )

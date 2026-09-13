"""The coach's daily cross-channel messaging workspace.

This is deliberately a view over recorded messages and guarded drafts. It does
not infer intent, approve coaching, or send anything by itself.
"""

from __future__ import annotations

from datetime import date
from html import escape
from urllib.parse import quote

from app.coach.roster import PendingMessage
from app.coach.view import coach_frame


def _initials(name: str) -> str:
    parts = [part for part in name.split() if part[:1].isalpha()]
    return "".join(part[0] for part in parts[:2]).upper() or "#"


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
            f'<span class="avatar" aria-hidden="true">{escape(_initials(name))}</span>'
            f'<div class="thread-name"><span>{escape(name)}</span>'
            f'<small class="{"unread" if unread else ""}">{escape(direction)}</small></div>'
            f'<div class="thread-preview">{escape(body)}</div></a>'
        )
    return "".join(rows)


def _conversation(messages, athlete_name: str, athlete_id: str) -> str:
    if not messages:
        return '<div class="desk-empty">Choose an athlete to open their conversation.</div>'
    bubbles = []
    for row in reversed(messages):
        direction = str(row["direction"])
        status = str(row["status"])
        timestamp = str(row["occurred_at"]).replace("T", " ")[:16]
        channel = str(row["channel"] or "whatsapp")
        error = f' · error {escape(str(row["error_code"]))}' if row["error_code"] else ""
        bubbles.append(
            f'<div class="bubble {escape(direction)}">{escape(str(row["body"]))}'
            f'<span class="bubble-meta">{escape(channel)} · {escape(timestamp)} · '
            f'{escape(status)}{error}</span></div>'
        )
    return (
        f'<h2>Conversation with {escape(athlete_name)}</h2><div class="chat-stream">'
        f'{"".join(bubbles)}</div><form method="post" action="/coach/whatsapp/reviewed" '
        'style="padding:0 14px 14px">'
        f'<input type="hidden" name="athlete_id" value="{escape(athlete_id)}">'
        '<button class="skip" type="submit">Mark feedback reviewed</button></form>'
    )


def _draft_card(item: PendingMessage) -> str:
    athlete = item.athlete
    reasons = " · ".join(escape(flag.detail) for flag in athlete.flags) or "No changes or safety flags"
    eligibility = (
        '<span class="safe-mark">Eligible for safe bulk approval</span>'
        if item.bulk_eligible else
        '<span class="manual-mark">Individual review required</span>'
    )
    return (
        f'<div class="card {athlete.bucket.value} message-card"><div class="panel-head"><div>'
        f'<a class="athlete-name" href="/coach/whatsapp?tab=approval&athlete={quote(item.athlete_id)}">'
        f'{escape(athlete.display_name)}</a><div class="muted">{escape(item.local_date)} · '
        f'{escape(item.message_kind.replace("_", " "))}</div></div>{eligibility}</div>'
        f'<p class="evidence-reason"><b>Evidence:</b> {reasons}</p>'
        '<form method="post" action="/coach/whatsapp/review">'
        f'<input type="hidden" name="athlete_id" value="{escape(item.athlete_id)}">'
        f'<input type="hidden" name="message_kind" value="{escape(item.message_kind)}">'
        f'<input type="hidden" name="local_date" value="{escape(item.local_date)}">'
        f'<textarea name="body" maxlength="1400">{escape(item.body)}</textarea>'
        '<div class="card-actions">'
        '<button class="approve" name="decision" value="approved">Approve</button>'
        '<button class="skip" name="decision" value="skipped">Hold</button></div></form></div>'
    )


def _scheduled_list(rows) -> str:
    if not rows:
        return '<div class="desk-empty">No approved messages are waiting to send.</div>'
    items = []
    for row in rows:
        items.append(
            '<div class="delivery-row">'
            f'<div><strong>{escape(str(row["athlete_id"]))}</strong>'
            f'<p>{escape(str(row["local_date"]))}</p></div>'
            f'<div><strong>{escape(str(row["message_kind"]).replace("_", " ").title())}</strong>'
            f'<p>{escape(str(row["body"]))}</p></div>'
            '<span class="delivery-state">Approved</span></div>'
        )
    return '<div class="delivery-list">' + "".join(items) + "</div>"


def _sent_list(rows) -> str:
    if not rows:
        return '<div class="desk-empty">No outbound delivery history yet.</div>'
    items = []
    for row in rows:
        status = str(row["status"])
        channel = str(row["channel"] or "whatsapp")
        error = f' · error {row["error_code"]}' if row["error_code"] else ""
        items.append(
            '<div class="delivery-row">'
            f'<div><strong>{escape(str(row["athlete_id"]))}</strong>'
            f'<p>{escape(str(row["occurred_at"]).replace("T", " ")[:16])}</p></div>'
            f'<div><strong>{escape(str(row["message_kind"]).replace("_", " ").title())}</strong>'
            f'<p>{escape(str(row["body"]))}</p></div>'
            f'<span class="delivery-state">{escape(channel)} · '
            f'{escape(status + error)}</span></div>'
        )
    return '<div class="delivery-list">' + "".join(items) + "</div>"


def _simulator(demo_athletes: tuple[tuple[str, str], ...]) -> str:
    if not demo_athletes:
        return (
            '<details class="simulator"><summary>Test the messaging workflow</summary>'
            '<div style="padding:0 14px 14px" class="muted">Load the demo squad from '
            'Overview first. Simulations are restricted to fictional demo numbers.</div></details>'
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
) -> str:
    """Render inbox, approval, schedule and delivery states in one daily desk."""
    counts = {
        "inbox": sum(int(row["unread_count"] or 0) for row in conversations),
        "approval": len(pending),
        "scheduled": len(scheduled),
        "sent": len(sent),
    }
    banner = ""
    if message:
        banner = f'<div class="msg {escape(message[0])}">{escape(message[1])}</div>'
    if transport_ready:
        telegram_help = (
            ' <a href="/coach/athletes">Open an athlete profile to connect their Telegram chat →</a>'
            if "Telegram" in transport_name else ""
        )
        transport = (
            f'<div class="msg ok"><strong>{escape(transport_name)} is active.</strong> '
            'Approved messages use the athlete\'s connected channel.'
            f'{telegram_help}</div>'
        )
    else:
        transport = (
            '<div class="msg warn"><strong>Demo simulator is ready.</strong> '
            'Configure Telegram to enable permanent real messaging. The inbox, '
            'approval and audit workflow already works here.</div>'
        )
    stats = (
        '<div class="desk-stats">'
        f'<div class="desk-stat"><strong>{counts["inbox"]}</strong><span>New feedback</span></div>'
        f'<div class="desk-stat"><strong>{counts["approval"]}</strong><span>Need approval</span></div>'
        f'<div class="desk-stat"><strong>{counts["scheduled"]}</strong><span>Scheduled</span></div>'
        f'<div class="desk-stat"><strong>{sum(1 for row in sent if row["status"] == "failed")}</strong><span>Delivery failed</span></div>'
        '</div>'
    )
    content = ""
    if tab == "approval":
        eligible = sum(1 for item in pending if item.bulk_eligible)
        bulk = (
            '<div class="approval-bar"><div><strong>Safe unchanged messages</strong>'
            f'<p>{eligible} untouched morning check-in(s) still match their original evidence.</p></div>'
            '<form method="post" action="/coach/whatsapp/bulk-approve">'
            f'<button id="bulk-approve" class="approve" type="submit" {"" if eligible else "disabled"}>'
            f'Approve unchanged ({eligible})</button></form></div>'
        )
        content = bulk + '<div class="draft-stack">' + (
            "".join(_draft_card(item) for item in pending)
            if pending else '<div class="desk-empty">Nothing is waiting for approval.</div>'
        ) + "</div>" + f"""<script>
const safeEligible={eligible};
const bulk=document.getElementById('bulk-approve');
if(bulk){{document.querySelectorAll('.message-card textarea').forEach(field=>{{
field.addEventListener('input',()=>{{bulk.disabled=safeEligible===0||[...document.querySelectorAll('.message-card textarea')]
.some(item=>item.value!==item.defaultValue);}});}});}}
</script>"""
    elif tab == "scheduled":
        content = _scheduled_list(scheduled)
    elif tab == "sent":
        content = _sent_list(sent)
    else:
        content = (
            _simulator(demo_athletes) +
            '<div class="desk-grid"><section class="thread-list"><h2>Conversations</h2>'
            f'{_thread_list(conversations, selected_athlete, tab)}</section>'
            f'<section class="thread-panel">{_conversation(messages, selected_name, selected_athlete or "")}</section></div>'
        )
    body = f'{banner}{transport}{stats}{_tabs(tab, counts)}{content}'
    return coach_frame(
        body, active="whatsapp", coach=coach, title="Messaging Desk",
        subtitle="Review WhatsApp or Telegram feedback, approve messages, and verify delivery.",
        today=today.isoformat(), pending_count=len(pending),
    )

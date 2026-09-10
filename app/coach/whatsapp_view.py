"""The coach's daily WhatsApp workspace.

This is deliberately a view over recorded messages and guarded drafts. It does
not infer intent, approve coaching, or send anything by itself.
"""

from __future__ import annotations

from datetime import date
from html import escape
from urllib.parse import quote

from app.coach.roster import PendingMessage
from app.coach.view import coach_frame


_DESK_CSS = """
.desk-stats{display:grid;grid-template-columns:repeat(4,1fr);gap:10px;margin:0 0 18px}
.desk-stat{background:var(--surface);border:1px solid var(--border);padding:12px;border-radius:6px}
.desk-stat strong{display:block;font-size:22px;line-height:1.1}.desk-stat span{font-size:12px;color:var(--ink-faint)}
.desk-tabs{display:flex;gap:6px;border-bottom:1px solid var(--border);margin-bottom:14px;overflow:auto}
.desk-tabs a{padding:9px 12px;color:var(--ink-soft);text-decoration:none;white-space:nowrap;border-bottom:2px solid transparent}
.desk-tabs a.active{color:var(--ink);font-weight:700;border-bottom-color:var(--plate-green)}
.desk-grid{display:grid;grid-template-columns:minmax(210px,.75fr) minmax(360px,1.35fr);gap:14px;align-items:start}
.thread-list,.thread-panel{background:var(--surface);border:1px solid var(--border);border-radius:6px;overflow:hidden}
.thread-list h2,.thread-panel h2{padding:12px 14px;margin:0;border-bottom:1px solid var(--border)}
.thread-link{display:block;padding:12px 14px;border-bottom:1px solid var(--border);text-decoration:none;color:var(--ink)}
.thread-link:last-child{border-bottom:0}.thread-link.active{background:var(--plate-green-bg);box-shadow:inset 3px 0 var(--plate-green)}
.thread-name{display:flex;justify-content:space-between;gap:8px;font-weight:700}.thread-preview{font-size:12.5px;color:var(--ink-soft);white-space:nowrap;overflow:hidden;text-overflow:ellipsis;margin-top:4px}
.chat-stream{padding:16px;background:var(--surface-inset);min-height:260px;display:flex;flex-direction:column;gap:10px}
.bubble{max-width:82%;padding:9px 11px;border-radius:9px;background:var(--surface);border:1px solid var(--border);font-size:14px;white-space:pre-wrap;word-break:break-word}
.bubble.outbound{align-self:flex-end;background:var(--plate-green-bg);border-color:var(--plate-green-border)}
.bubble-meta{display:block;font-size:10.5px;color:var(--ink-faint);margin-top:5px;text-align:right;text-transform:uppercase;letter-spacing:.04em}
.approval-bar{background:var(--plate-green-bg);border:1px solid var(--plate-green-border);padding:13px 15px;margin-bottom:14px;border-radius:6px;display:flex;justify-content:space-between;gap:12px;align-items:center}
.approval-bar form{margin:0}.approval-bar p{margin:2px 0 0;color:var(--ink-soft);font-size:13px}
.safe-mark{color:var(--plate-green-text);font-weight:700;font-size:12px}.manual-mark{color:var(--plate-yellow-text);font-weight:700;font-size:12px}
.draft-stack .message-card{margin-bottom:12px}.draft-stack textarea{background:var(--surface)}
.delivery-list{background:var(--surface);border:1px solid var(--border);border-radius:6px;overflow:hidden}
.delivery-row{display:grid;grid-template-columns:minmax(140px,.7fr) minmax(260px,1.7fr) auto;gap:14px;align-items:center;padding:13px 15px;border-bottom:1px solid var(--border)}
.delivery-row:last-child{border-bottom:0}.delivery-row p{margin:2px 0 0;color:var(--ink-soft);font-size:13px}.delivery-state{font:700 11px ui-monospace,monospace;text-transform:uppercase;color:var(--ink-faint)}
.desk-empty{padding:28px 16px;text-align:center;color:var(--ink-faint)}
.simulator{background:var(--surface);border:1px solid var(--border);border-radius:6px;margin-bottom:14px}.simulator summary{padding:12px 14px;font-weight:700;cursor:pointer}.simulator form{display:grid;grid-template-columns:180px 1fr auto;gap:8px;padding:0 14px 14px;margin:0}.simulator textarea{min-height:42px}.simulator p{grid-column:1/-1;margin:0;color:var(--ink-faint);font-size:12px}
@media(max-width:760px){.desk-stats{grid-template-columns:1fr 1fr}.desk-grid{grid-template-columns:1fr}.thread-panel{min-height:0}.approval-bar{align-items:flex-start;flex-direction:column}.delivery-row{grid-template-columns:1fr auto}.delivery-row>div:nth-child(2){grid-column:1/-1;grid-row:2}.simulator form{grid-template-columns:1fr}.simulator p{grid-column:auto}}
"""


def _tabs(active: str, counts: dict[str, int]) -> str:
    labels = (("inbox", "Inbox"), ("approval", "Needs approval"),
              ("scheduled", "Scheduled"), ("sent", "Sent"))
    return '<nav class="desk-tabs" aria-label="WhatsApp work states">' + "".join(
        f'<a class="{"active" if active == key else ""}" href="/coach/whatsapp?tab={key}">'
        f'{label} <b>{counts.get(key, 0)}</b></a>'
        for key, label in labels
    ) + "</nav>"


def _thread_list(conversations, selected: str | None, tab: str) -> str:
    if not conversations:
        return '<div class="desk-empty">No WhatsApp conversations yet.</div>'
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
            f'<div class="thread-name"><span>{escape(name)}</span><small>{escape(direction)}</small></div>'
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
        error = f' · error {escape(str(row["error_code"]))}' if row["error_code"] else ""
        bubbles.append(
            f'<div class="bubble {escape(direction)}">{escape(str(row["body"]))}'
            f'<span class="bubble-meta">{escape(timestamp)} · {escape(status)}{error}</span></div>'
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
        error = f' · error {row["error_code"]}' if row["error_code"] else ""
        items.append(
            '<div class="delivery-row">'
            f'<div><strong>{escape(str(row["athlete_id"]))}</strong>'
            f'<p>{escape(str(row["occurred_at"]).replace("T", " ")[:16])}</p></div>'
            f'<div><strong>{escape(str(row["message_kind"]).replace("_", " ").title())}</strong>'
            f'<p>{escape(str(row["body"]))}</p></div>'
            f'<span class="delivery-state">{escape(status + error)}</span></div>'
        )
    return '<div class="delivery-list">' + "".join(items) + "</div>"


def _simulator(demo_athletes: tuple[tuple[str, str], ...]) -> str:
    if not demo_athletes:
        return (
            '<details class="simulator"><summary>Test the WhatsApp workflow</summary>'
            '<div style="padding:0 14px 14px" class="muted">Load the demo squad from '
            'Overview first. Simulations are restricted to fictional demo numbers.</div></details>'
        )
    options = "".join(
        f'<option value="{escape(athlete_id)}">{escape(name)}</option>'
        for athlete_id, name in demo_athletes
    )
    return (
        '<details class="simulator"><summary>Test the WhatsApp workflow</summary>'
        '<form method="post" action="/coach/whatsapp/simulate">'
        f'<select name="athlete_id">{options}</select>'
        '<textarea name="body" required maxlength="800" '
        'placeholder="Try: slept 5h, readiness 4, knee feels sore"></textarea>'
        '<button type="submit">Simulate message</button>'
        '<p>This writes a real demo conversation and approval draft, but sends no external WhatsApp message.</p>'
        '</form></details>'
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
        '<div style="display:flex;gap:8px;margin-top:9px;flex-wrap:wrap">'
        '<button class="approve" name="decision" value="approved">Approve</button>'
        '<button class="skip" name="decision" value="skipped">Hold</button></div></form></div>'
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
    transport = (
        '<div class="msg ok"><strong>Live WhatsApp connected.</strong> Approved messages can be sent through Twilio.</div>'
        if transport_ready else
        '<div class="msg warn"><strong>Simulator mode.</strong> Twilio is not configured; the approval workflow works, but no real WhatsApp message can be sent.</div>'
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
        body, active="whatsapp", coach=coach, title="WhatsApp Desk",
        subtitle="Review athlete feedback, approve today’s messages, and verify delivery.",
        today=today.isoformat(), pending_count=len(pending), extra_style=_DESK_CSS,
    )

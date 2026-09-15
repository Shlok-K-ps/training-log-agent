
"""HTML views for the coach console, landing page, and legal notices.

Rendered server-side as pure strings with zero build step, no npm, and no JS framework.
Mobile-first layout designed for a coach on a phone at the gym or on a laptop.
"""

from __future__ import annotations

from datetime import date
from html import escape

from app.coach.roster import BUCKET_ORDER, Bucket, PendingMessage, Roster, RosterEntry
from app.scheduling.outbox import message_kind_label


def _vt_athlete(athlete_id: str | None) -> str:
    if not athlete_id:
        return ""
    digits = "".join(c for c in athlete_id if c.isdigit())
    return f"athlete-{digits}" if digits else ""


# Line glyphs drawn on a 24px grid in the manner of SF Symbols.
_NAV_ICONS = {
    "overview": '<rect x="3.5" y="5" width="17" height="15.5" rx="3.5"/><path d="M3.5 10.5h17M8.5 3v4M15.5 3v4"/>'
                '<path d="m9 15.5 2 2 4-4"/>',
    "athletes": '<circle cx="9" cy="8" r="3.5"/><path d="M2.5 19.5c.6-3.3 3.2-5.5 6.5-5.5s5.9 2.2 6.5 5.5"/>'
                '<path d="M15.5 4.8a3.3 3.3 0 0 1 0 6.4"/><path d="M18 14.4c1.9.7 3.2 2.5 3.5 5.1"/>',
    "whatsapp": '<path d="M20.5 11.5c0 4.1-3.8 7.5-8.5 7.5a9.6 9.6 0 0 1-3.3-.6L4 19.8l1.3-3.6a7 7 0 0 1-1.8-4.7'
                'C3.5 7.4 7.3 4 12 4s8.5 3.4 8.5 7.5Z"/>',
    "analytics": '<path d="M3.5 17.5 9 12l3.5 3.5 8-8"/><path d="M15 7.5h5.5V13"/>',
}

_BOLT = '<svg viewBox="0 0 24 24" aria-hidden="true"><path d="M13.5 2 4 13.5h7L10 22l10-12h-7z"/></svg>'

_HEAD_ASSETS = (
    "<meta name='color-scheme' content='light dark'>"
    "<meta name='theme-color' content='#F2F2F7' media='(prefers-color-scheme: light)'>"
    "<meta name='theme-color' content='#000000' media='(prefers-color-scheme: dark)'>"
    "<link rel='preconnect' href='https://fonts.googleapis.com'>"
    "<link rel='preconnect' href='https://fonts.gstatic.com' crossorigin>"
    "<link href='https://fonts.googleapis.com/css2?family=Inter:opsz,wght@14..32,400..800&display=swap' rel='stylesheet'>"
    "<link rel='stylesheet' href='/static/tokens.css'>"
    "<link rel='stylesheet' href='/static/app.css'>"
    "<link rel='stylesheet' href='/static/console.css'>"
)


def _long_date(today) -> str:
    """The dateline iOS sets above a large title, e.g. 'Sunday 13 September'."""
    try:
        day = today if isinstance(today, date) else date.fromisoformat(str(today))
    except ValueError:
        return str(today)
    return f"{day:%A} {day.day} {day:%B}"


def _coach_nav(*, active: str, coach: str, pending_count: int = 0) -> str:
    """Stable product navigation shared by every coach page.

    A sidebar on wide screens and a tab bar on phones. The tab bar carries short
    labels so all four destinations fit without wrapping.
    """
    links = (
        ("overview", "/coach", "Today", "Today"),
        ("athletes", "/coach/athletes", "Athletes", "Athletes"),
        ("whatsapp", "/coach/whatsapp", "Messaging Desk", "Messages"),
        ("analytics", "/coach/analytics", "Goal Analytics", "Goals"),
    )
    side_nav = []
    bottom_nav = []
    for key, href, label, short_label in links:
        is_active = key == active
        active_attrs = ' active" aria-current="page' if is_active else ""
        icon = f'<svg class="nav-icon" viewBox="0 0 24 24" aria-hidden="true">{_NAV_ICONS[key]}</svg>'
        # One badge for one queue: approvals are worked from the Messaging Desk.
        badge = (
            f'<span class="nav-count">{pending_count}</span>'
            if key == "whatsapp" and pending_count else ""
        )
        side_nav.append(
            f'<a class="nav-item{active_attrs}" href="{href}">'
            f'{icon}<span class="nav-label">{label}</span>{badge}</a>'
        )
        bottom_nav.append(
            f'<a class="bottom-item{active_attrs}" href="{href}">'
            f'{icon}<span>{short_label}</span>{badge}</a>'
        )
    initial = escape((coach.strip()[:1] or "C").upper())
    return (
        '<aside class="side-nav">'
        '<div class="side-brand-wrap">'
        '<a class="side-brand" href="/coach">'
        f'<span class="mac-app-icon" aria-hidden="true">{_BOLT}</span>'
        '<span class="brand-name">Power AI</span><span class="brand-badge">Coach Desk</span>'
        '</a>'
        '</div>'
        '<div class="side-section-label">Workspace</div>'
        f'<nav class="side-links" aria-label="Roster navigation">{"".join(side_nav)}</nav>'
        '<div class="side-meta">'
        f'<div class="coach-profile"><span class="avatar" aria-hidden="true">{initial}</span>'
        f'<div>Head coach<strong>{escape(coach)}</strong></div></div>'
        '</div>'
        '</aside>'
        f'<nav class="bottom-bar" aria-label="Mobile navigation">{"".join(bottom_nav)}</nav>'
    )


def coach_frame(
    body: str,
    *,
    active: str,
    coach: str,
    title: str,
    subtitle: str,
    today,
    pending_count: int = 0,
    extra_style: str = "",
    athlete_id: str | None = None,
    back: tuple[str, str] | None = None,
) -> str:
    """The application shell: navigation stays put while the work changes."""
    vt_name = _vt_athlete(athlete_id) if athlete_id else "page-title"
    h1_style = f"style='view-transition-name: {vt_name};'" if vt_name else ""
    back_link = (
        f'<p class="back"><a href="{escape(back[0])}">'
        '<svg viewBox="0 0 24 24" aria-hidden="true"><path d="M15 5l-7 7 7 7"/></svg>'
        f'{escape(back[1])}</a></p>'
        if back else ""
    )
    style = f"<style>{extra_style}</style>" if extra_style else ""
    return (
        "<!doctype html><html lang='en'><head><meta charset='utf-8'>"
        "<meta name='viewport' content='width=device-width,initial-scale=1,viewport-fit=cover'>"
        f"<title>{escape(title)} — Power AI Coach Desk</title>"
        "<link rel='icon' href='data:image/svg+xml,<svg xmlns=%22http://www.w3.org/2000/svg%22 viewBox=%220 0 100 100%22><text y=%22.9em%22 font-size=%2290%22>⚡</text></svg>'>"
        f"{_HEAD_ASSETS}{style}"
        "<script src='/static/motion.js' defer></script>"
        "</head><body>"
        f"<header class='compact-bar' aria-hidden='true'><span class='compact-title'>{escape(title)}</span></header>"
        "<div class='app-shell'>"
        f"{_coach_nav(active=active, coach=coach, pending_count=pending_count)}"
        "<main class='workspace'><div class='workspace-head'>"
        f"{back_link}<div class='workspace-eyebrow'>{escape(_long_date(today))}</div>"
        f"<h1 {h1_style}>{escape(title)}</h1>"
        + (f"<p class='workspace-sub'>{escape(subtitle)}</p>" if subtitle else "")
        + f"</div>{body}<footer>Power AI &middot; Coach Desk</footer></main></div></body></html>"
    )

def initials(name: str) -> str:
    """Up to two initials for an avatar, e.g. 'Priya Kulkarni' -> 'PK'."""
    parts = [part for part in name.split() if part[:1].isalpha()]
    return "".join(part[0] for part in parts[:2]).upper() or "#"


def banner(message: tuple[str, str] | None) -> str:
    if not message:
        return ""
    kind, text = message
    return f'<div class="msg {escape(kind)}">{escape(text)}</div>'


def conversation_bubbles(messages) -> str:
    """A conversation oldest first: the athlete on the left, outbound on the right."""
    bubbles = []
    for row in reversed(list(messages)):
        direction = str(row["direction"])
        status = str(row["status"])
        timestamp = str(row["occurred_at"]).replace("T", " ")[:16]
        channel = str(row["channel"] or "whatsapp").capitalize()
        error = f' · error {escape(str(row["error_code"]))}' if row["error_code"] else ""
        bubbles.append(
            f'<div class="bubble {escape(direction)}">{escape(str(row["body"]))}'
            f'<span class="bubble-meta">{escape(channel)} · {escape(timestamp)} · '
            f'{escape(status)}{error}</span></div>'
        )
    return "".join(bubbles)


def _demo_controls(roster: Roster, has_demo: bool, *, return_to: str = "/coach") -> str:
    """Keep demo controls available, even with a real roster."""
    hidden = f'<input type="hidden" name="return_to" value="{escape(return_to)}">'
    if has_demo:
        return (
            '<div class="demo">'
            "<p>This roster includes demo athletes.</p>"
            f'<form method="post" action="/coach/demo/clear">{hidden}'
            '<button class="skip" type="submit">Remove demo athletes</button></form>'
            "</div>"
        )
    message = (
        "Nothing has been logged yet. Load a mixed fictional squad to explore every screen."
        if roster.total == 0 else
        "Add a mixed fictional squad alongside the roster to preview check-ins, injuries, goals and messaging states."
    )
    return (
        '<div class="demo"><p>' + escape(message) + '</p>'
        f'<form method="post" action="/coach/demo/seed">{hidden}'
        '<button type="submit">Load a demo squad</button></form></div>'
    )


def _tutorial() -> str:
    return """
<div class="panel">
  <div class="panel-head"><h2>New here?</h2></div>
  <p class="section-note">Take a two-minute tour of the coach approval loop.</p>
  <button class="skip" type="button" onclick="document.getElementById('tutorial').showModal()">Open tutorial</button>
</div>
<dialog id="tutorial">
  <h1>How to use Coach Desk</h1>
  <ol>
    <li><strong>Start on Today:</strong> injury decisions and clearance requests come first, then the messages the agent has drafted.</li>
    <li><strong>Approve or hold:</strong> every card shows the evidence and the exact wording. Edit it before approving if it reads wrong.</li>
    <li><strong>Handle injuries:</strong> pick one of the four plans, check the message it will send, and approve. The injury flag stays open until independent clearance.</li>
    <li><strong>Add athletes:</strong> record bodyweight, 1RMs, training frequency, current injuries and a dated goal.</li>
    <li><strong>Check Goals:</strong> ahead, on track or lagging is a prompt to review, not an automatic programme change.</li>
  </ol>
  <p>For a safe walkthrough, load the demo squad and use “Test the messaging workflow” in Messages.</p>
  <form method="dialog"><button type="submit">Got it</button></form>
</dialog>
"""


def _flag_text(entry: RosterEntry, kind: str) -> str:
    return next((flag.detail for flag in entry.flags if flag.kind == kind), "")


def _decision_card(entry: RosterEntry, *, kind: str, detail: str, href: str, action: str) -> str:
    return (
        '<article class="decision-card">'
        f'<span class="avatar ring-act" aria-hidden="true">{escape(initials(entry.display_name))}</span>'
        '<div class="decision-body">'
        f'<span class="decision-kind">{escape(kind)}</span>'
        f'<a class="athlete-name" href="/coach/athlete/{escape(entry.athlete_id)}">{escape(entry.display_name)}</a>'
        f'<p>{escape(detail)}</p></div>'
        f'<a class="btn btn-primary decision-action" href="{href}">{escape(action)}</a>'
        '</article>'
    )


def _athlete_row(entry: RosterEntry, note: str = "") -> str:
    signal = " · ".join(f.detail for f in entry.flags) or "On track"
    readiness = (
        f'<span class="readiness-pill {escape(entry.readiness_band or "")}">'
        f'<span class="dot">●</span> {entry.readiness_score}/100</span>'
        if entry.readiness_score is not None else '<span class="muted">No check-in</span>'
    )
    note_html = f'<div class="plan-note">{escape(note)}</div>' if note else ""
    return (
        '<div class="athlete-line">'
        f'<div><a class="athlete-name" href="/coach/athlete/{escape(entry.athlete_id)}">{escape(entry.display_name)}</a>'
        f'<div class="muted">{escape(entry.latest_session or "No session logged")}</div></div>'
        f'<div class="signal">{escape(signal)}{note_html}</div>{readiness}</div>'
    )


def approval_card(item: PendingMessage, *, return_to: str = "/coach/whatsapp?tab=approval") -> str:
    """One drafted message with the evidence behind it and the controls to decide."""
    a = item.athlete
    if item.stale_reason:
        # Overtaken by newer athlete information: it can be retired, never approved.
        return (
            '<article class="message-card approval-card is-stale" data-stale>'
            '<header class="approval-head">'
            f'<span class="avatar" aria-hidden="true">{escape(initials(a.display_name))}</span>'
            '<div class="approval-who">'
            f'<a class="athlete-name" href="/coach/athlete/{escape(item.athlete_id)}">{escape(a.display_name)}</a>'
            f'<span class="muted">{escape(message_kind_label(item.message_kind))} · for {escape(item.local_date)}</span></div>'
            '<div class="approval-state"><span class="readiness-pill red">Outdated</span></div>'
            '</header>'
            '<p class="stale-note"><strong>Outdated—new athlete information received.</strong> '
            f'{escape(item.stale_reason)} It cannot be approved.</p>'
            f'<blockquote class="stale-body">{escape(item.body)}</blockquote>'
            '<form method="post" action="/coach/whatsapp/review">'
            f'<input type="hidden" name="athlete_id" value="{escape(item.athlete_id)}">'
            f'<input type="hidden" name="message_kind" value="{escape(item.message_kind)}">'
            f'<input type="hidden" name="local_date" value="{escape(item.local_date)}">'
            f'<input type="hidden" name="return_to" value="{escape(return_to)}">'
            '<div class="card-actions">'
            '<button class="btn btn-ghost" type="submit" name="decision" value="skipped">Retire unsent</button>'
            f'<a class="btn btn-ghost" href="/coach/athlete/{escape(item.athlete_id)}#messages">Open conversation</a>'
            '</div></form></article>'
        )
    reasons = " · ".join(f.detail for f in a.flags) or "Nothing flagged"
    readiness = (
        f"{a.readiness_score}/100 · {a.readiness_band}"
        if a.readiness_score is not None else "No same-day check-in"
    )
    marks = ""
    if item.bulk_eligible:
        marks += '<span class="safe-mark">Safe to bulk approve</span>'
    if item.edited:
        marks += '<span class="manual-mark">Edited</span>'
    return (
        '<article class="message-card approval-card">'
        '<header class="approval-head">'
        f'<span class="avatar" aria-hidden="true">{escape(initials(a.display_name))}</span>'
        '<div class="approval-who">'
        f'<a class="athlete-name" href="/coach/athlete/{escape(item.athlete_id)}">{escape(a.display_name)}</a>'
        f'<span class="muted">{escape(message_kind_label(item.message_kind))} · for {escape(item.local_date)}</span></div>'
        f'<div class="approval-state">{marks}<span class="readiness-pill yellow">Awaiting approval</span></div>'
        '</header>'
        '<div class="evidence-grid">'
        f'<div><span>Training trend</span><strong>{escape(a.training_summary or "No baseline")}</strong></div>'
        f'<div><span>Latest session</span><strong>{escape(a.latest_session or "Nothing logged")}</strong></div>'
        f'<div><span>Readiness</span><strong>{escape(readiness)}</strong></div>'
        '</div>'
        f'<p class="evidence-reason"><b>Why surfaced:</b> {escape(reasons)}</p>'
        '<form method="post" action="/coach/whatsapp/review">'
        f'<input type="hidden" name="athlete_id" value="{escape(item.athlete_id)}">'
        f'<input type="hidden" name="message_kind" value="{escape(item.message_kind)}">'
        f'<input type="hidden" name="local_date" value="{escape(item.local_date)}">'
        f'<input type="hidden" name="return_to" value="{escape(return_to)}">'
        '<label class="draft-label">Message the athlete will receive'
        f'<textarea name="body" maxlength="1400">{escape(item.body)}</textarea></label>'
        '<div class="card-actions">'
        '<button class="btn btn-primary" type="submit" name="decision" value="approved">Approve</button>'
        '<button class="btn btn-ghost" type="submit" name="decision" value="skipped">Hold</button>'
        '</div></form></article>'
    )


def render(
    roster: Roster,
    *,
    coach: str,
    message: tuple[str, str] | None = None,
    has_demo: bool = False,
    pending_count: int = 0,
    pending: tuple[PendingMessage, ...] = (),
    injury_plans: tuple[tuple[RosterEntry, str | None], ...] = (),
    agent_board: str = "",
    extra_style: str = "",
    setup_html: str = "",
    empty_html: str = "",
) -> str:
    """Today: setup if unfinished, the agent's work and exceptions, then the legacy approvals."""
    if empty_html:
        return coach_frame(
            f"{banner(message)}{empty_html}{setup_html}", active="overview", coach=coach, title="Today",
            subtitle="Your private training-day agent console.",
            today=roster.reviewed_on.isoformat(), pending_count=pending_count, extra_style=extra_style,
        )
    counts = {bucket: len(roster.bucket(bucket)) for bucket in BUCKET_ORDER}
    tiles = (
        ("act", "Needs you", Bucket.NEEDS_YOU),
        ("watch", "Watch", Bucket.WATCH),
        ("meet", "Meet prep", Bucket.MEET_PREP),
        ("fine", "On track", Bucket.FINE),
    )
    summary_tiles = '<div class="summary-tiles">' + "".join(
        f'<a class="summary-tile {cls}" href="/coach/athletes?status={bucket.value}">'
        f'<span class="summary-label">{label}</span>'
        f'<span class="summary-num" data-counter data-target="{counts[bucket]}">{counts[bucket]}</span>'
        f'<span class="summary-caption">{"athlete" if counts[bucket] == 1 else "athletes"}</span></a>'
        for cls, label, bucket in tiles
    ) + "</div>"

    # 1. Decisions only the coach can make: clearance requests, then new injuries.
    plan_titles = {entry.athlete_id: title for entry, title in injury_plans}
    decisions: list[str] = []
    in_decisions: set[str] = set()
    for entry in roster.entries:
        if any(flag.kind == "clearance_requested" for flag in entry.flags):
            decisions.append(_decision_card(
                entry, kind="Clearance requested",
                detail=_flag_text(entry, "clearance_requested"),
                href=f"/coach/athlete/{escape(entry.athlete_id)}#clearance-review",
                action="Review injury clearance",
            ))
            in_decisions.add(entry.athlete_id)
    for entry, title in injury_plans:
        if title is None and entry.athlete_id not in in_decisions:
            decisions.append(_decision_card(
                entry, kind="Injury plan needed", detail=_flag_text(entry, "injured"),
                href=f"/coach/athlete/{escape(entry.athlete_id)}#injury-plan",
                action="Choose injury plan",
            ))
            in_decisions.add(entry.athlete_id)
    decision_section = (
        '<section class="today-section" aria-labelledby="decisions-title">'
        '<div class="section-head-row">'
        f'<h2 id="decisions-title">Needs your decision <span class="n">{len(decisions)}</span></h2></div>'
        f'<div class="decision-list">{"".join(decisions)}</div></section>'
        if decisions else ""
    )

    # 2. Messages the agent drafted, with the evidence and the exact wording.
    eligible = sum(1 for item in pending if item.bulk_eligible)
    bulk = (
        '<form method="post" action="/coach/whatsapp/bulk-approve">'
        '<input type="hidden" name="return_to" value="/coach">'
        f'<button class="btn btn-ghost btn-sm" type="submit" data-bulk-approve data-eligible="{eligible}">'
        f'Approve unchanged check-ins ({eligible})</button></form>'
        if eligible else ""
    )
    approval_section = (
        '<section class="today-section" aria-labelledby="approvals-title">'
        '<div class="section-head-row">'
        f'<h2 id="approvals-title">Approval queue <span class="n">{len(pending)}</span></h2>{bulk}</div>'
        + (
            "".join(approval_card(item, return_to="/coach") for item in pending)
            if pending else
            '<div class="empty-card"><strong>Nothing waiting for approval.</strong>'
            "<span>Replies to athletes and tomorrow's check-ins appear here as soon as the agent drafts them.</span></div>"
        )
        + "</section>"
    )

    # 3. What the agent noticed, then who is fine.
    watch = [e for e in roster.bucket(Bucket.WATCH) if e.athlete_id not in in_decisions]
    meet = roster.bucket(Bucket.MEET_PREP)
    fine = roster.bucket(Bucket.FINE)

    def plan_note(entry: RosterEntry) -> str:
        title = plan_titles.get(entry.athlete_id)
        return f"Injury plan: {title}" if title else ""

    def listed(title: str, entries, status: str) -> str:
        if not entries:
            return ""
        return (
            '<section class="today-section"><div class="section-head-row">'
            f'<h2>{escape(title)} <span class="n">{len(entries)}</span></h2>'
            f'<a href="/coach/athletes?status={status}">See in roster →</a></div>'
            f'<div class="list-card">{"".join(_athlete_row(e, plan_note(e)) for e in entries)}</div></section>'
        )

    fine_section = (
        '<details class="fine-collapse list-card"><summary class="fine-summary">'
        f'<span>On track ({len(fine)})</span><span>&darr;</span></summary>'
        f'<div class="fine-rows">{"".join(_athlete_row(e) for e in fine)}</div></details>'
        if fine else ""
    )
    all_clear = (
        '<div class="all-clear"><span class="check" aria-hidden="true">✓</span>'
        "<div><strong>All clear.</strong><p>Nothing needs a decision right now. "
        "New athlete messages will land here.</p></div></div>"
        if roster.entries and not decisions and not pending and not watch else ""
    )
    empty_roster = (
        '<div class="empty-card"><strong>No athletes yet.</strong>'
        "<span>Add athletes from the Athletes page, or load the demo squad to explore the workflow.</span></div>"
        if not roster.entries else ""
    )

    workflow = (
        '<div class="panel"><div class="panel-head"><h2>Daily agent loop</h2></div>'
        '<div class="flow-step"><b>01</b><div><strong>Check in</strong><p>On each planned training day the agent sends the check-in and follows up twice at most.</p></div></div>'
        '<div class="flow-step"><b>02</b><div><strong>Decide</strong><p>Fixed rules hold or reduce your approved session. Injuries, red recovery and autopilot-off days come to you.</p></div></div>'
        '<div class="flow-step"><b>03</b><div><strong>Close</strong><p>It asks whether training happened and closes the day only when the outcome is known.</p></div></div>'
        '</div>'
    )
    legacy_title = (
        '<div class="section-head-row"><h2>Roster signals and manual approvals</h2></div>'
        if agent_board else ""
    )

    body = (
        f"{banner(message)}"
        '<div class="today-grid"><div class="today-main">'
        f"{setup_html}{agent_board}{legacy_title}{summary_tiles}"
        f"{empty_roster}{all_clear}{decision_section}{approval_section}"
        f'{listed("Watch", watch, "watch")}{listed("Meet prep", meet, "meet_prep")}{fine_section}'
        '</div><aside class="today-side">'
        f"{workflow}{_tutorial()}{_demo_controls(roster, has_demo)}"
        "</aside></div>"
    )
    return coach_frame(
        body, active="overview", coach=coach, title="Today",
        subtitle="What the agent needs from you, what it is waiting for, and what it has already done.",
        today=roster.reviewed_on.isoformat(), pending_count=pending_count or len(pending),
        extra_style=extra_style,
    )


def render_athletes(
    roster: Roster,
    *,
    coach: str,
    message: tuple[str, str] | None = None,
    has_demo: bool = False,
    pending_count: int = 0,
    telegram_configured: bool = False,
    telegram_ready: bool = False,
    telegram_error: str | None = None,
    telegram_linked_ids: set[str] | None = None,
) -> str:
    """Searchable squad directory with current readiness and training context."""
    rows = []
    telegram_linked_ids = telegram_linked_ids or set()
    for entry in roster.entries:
        status = " · ".join(f.detail for f in entry.flags) or "On track"
        readiness = (
            f'<span class="readiness-pill {escape(entry.readiness_band or "")}">{entry.readiness_score}/100</span>'
            if entry.readiness_score is not None else '<span class="muted">Not checked in</span>'
        )
        haystack = f"{entry.display_name} {entry.athlete_id} {entry.bucket.value} {status}".lower()
        dot_cls = {
            Bucket.NEEDS_YOU: "act", Bucket.WATCH: "watch", Bucket.MEET_PREP: "meet",
        }.get(entry.bucket, "fine")
        if telegram_ready and entry.athlete_id in telegram_linked_ids:
            channel = '<span class="channel-mini connected">Telegram connected</span>'
        elif telegram_ready:
            channel = (
                f'<a class="channel-mini" href="/coach/athlete/{escape(entry.athlete_id)}">'
                'Connect Telegram →</a>'
            )
        elif telegram_configured:
            channel = '<span class="channel-mini warning">Telegram webhook not ready</span>'
        else:
            channel = ""
        rows.append(
            f'<div class="directory-row athlete-record" data-bucket="{entry.bucket.value}" '
            f'data-search="{escape(haystack)}">'
            f'<div><span class="dot-count {dot_cls}">●</span> <a class="athlete-name" href="/coach/athlete/{escape(entry.athlete_id)}">{escape(entry.display_name)}</a>'
            f'{channel}</div>'
            f'<div><strong>{escape(entry.training_summary or "No training baseline")}</strong>'
            f'<div class="muted">{escape(status)}</div></div>{readiness}'
            f'<div class="muted row-last"><span class="mobile-label">Last log </span>'
            f'{escape(entry.last_activity or "Never")}</div></div>'
        )
    directory = (
        '<div class="directory"><div class="directory-row directory-head">'
        '<span>Athlete</span><span>Current status</span><span>Readiness</span><span>Last log</span></div>'
        + ("".join(rows) if rows else '<p class="empty" style="padding:16px">No athletes yet.</p>')
        + '</div>'
    )
    tools = (
        '<div class="directory-tools"><input id="athlete-search" type="text" '
        'placeholder="Search athletes or status…" aria-label="Search athletes">'
        '<select id="athlete-filter" aria-label="Filter athlete status">'
        '<option value="all">All statuses</option><option value="needs_you">Needs you</option>'
        '<option value="watch">Watch</option><option value="meet_prep">Meet prep</option>'
        '<option value="fine">On track</option></select></div>'
    )
    script = """<script>
const search=document.getElementById('athlete-search');
const filter=document.getElementById('athlete-filter');
function filterAthletes(){const q=search.value.trim().toLowerCase();const f=filter.value;
document.querySelectorAll('.athlete-record').forEach(row=>{row.hidden=!row.dataset.search.includes(q)||(f!=='all'&&row.dataset.bucket!==f);});}
search.addEventListener('input',filterAthletes);filter.addEventListener('change',filterAthletes);
const preset=new URLSearchParams(location.search).get('status');
if(preset&&[...filter.options].some(option=>option.value===preset)){filter.value=preset;filterAthletes();}
</script>"""
    if telegram_ready:
        telegram_notice = (
            '<div class="msg ok"><strong>Telegram bot is connected.</strong> '
            'Use the connection shown under each athlete to pair their private chat.</div>'
        )
    elif telegram_configured:
        reason = f" Reason: {escape(telegram_error)}." if telegram_error else ""
        telegram_notice = (
            '<div class="msg warn"><strong>Telegram is configured but its webhook is not verified.</strong> '
            f'Check the latest Render deployment log before pairing an athlete.{reason}</div>'
        )
    else:
        telegram_notice = ""
    body = (
        f"{banner(message)}{telegram_notice}"
        '<div class="directory-add" style="display:flex;justify-content:space-between;align-items:center;'
        'gap:1rem;flex-wrap:wrap;margin:0 0 1rem"><p class="muted" style="margin:0">Add an athlete with a name '
        'and their usual times. You get a Telegram invite straight away.</p>'
        '<a class="btn btn-primary" href="/coach/athletes/new">Add an athlete</a></div>'
        f"{tools}{directory}"
        f"{_demo_controls(roster, has_demo, return_to='/coach/athletes')}{script}"
    )
    return coach_frame(
        body, active="athletes", coach=coach, title="Athletes",
        subtitle="Current status, recent progress and readiness across the full squad.",
        today=roster.reviewed_on.isoformat(), pending_count=pending_count,
    )


def render_landing() -> str:
    """Compatibility wrapper for the focused public landing page."""
    from app.coach.landing_view import render_landing as render_lean_landing

    return render_lean_landing()

def render_privacy() -> str:
    """Render the styled privacy policy."""
    return f"""<!doctype html>
<html lang="en">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>Power AI — Privacy Policy</title>
  <link rel="preconnect" href="https://fonts.googleapis.com">
  <link rel="preconnect" href="https://fonts.gstatic.com" crossorigin>
  <meta name="color-scheme" content="light dark">
  <link href="https://fonts.googleapis.com/css2?family=Inter:opsz,wght@14..32,400..800&display=swap" rel="stylesheet">
  <link rel="stylesheet" href="/static/tokens.css">
  <link rel="stylesheet" href="/static/app.css">
</head>
<body>
  <div class="noise-overlay" aria-hidden="true"></div>
  <header class="site-header">
    <div class="site-header-inner">
      <a class="brand-link" href="/">
        <div class="mac-app-icon" aria-hidden="true">
          <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.5" stroke-linecap="round" stroke-linejoin="round">
            <polygon points="13 2 3 14 12 14 11 22 21 10 12 10 13 2"></polygon>
          </svg>
        </div>
        <span class="brand-name" style="white-space:nowrap">Power AI</span>
        <span class="brand-badge" style="white-space:nowrap">Training Log Agent</span>
      </a>
      <nav class="site-nav">
        <a class="nav-link" href="/">&larr; Return to Home</a>
        <a class="nav-link" href="/terms">Terms of Service</a>
      </nav>
    </div>
  </header>

  <div class="wrapper">
    <div class="legal-container">
      <div class="mac-eyebrow">Data Privacy &amp; Encryption Boundaries</div>
      <h1>Privacy Policy</h1>
      <p>Calendar connection is optional and is not enabled on the hosted deployment. Where it is enabled, the service reads event start/end times and usable locations only to plan travel and training. It does not retain event titles, descriptions, attendees or meeting content.</p>
      <p>OAuth tokens and saved places are encrypted at rest with Fernet cryptography when the calendar integration is configured. Confirmed workout references are stored until the athlete asks to delete them. Calendar data is never sold and is never sent to the language model.</p>
      <p>Athlete messages sent to the Telegram bot are passed to Google's Gemini 2.5 Flash only to turn them into structured data. Coaching and safety decisions are made by fixed, tested rules in the application, not by that model.</p>
      <p>The public demo uses fictional, temporary data and sends nothing. Real athlete data is stored in the deployment's Postgres database.</p>
      <p>Where calendar planning is enabled, athletes can send <em>“disconnect calendar”</em> to the bot to delete stored calendar tokens, or <em>“forget my locations”</em> to erase saved home, office and gym places.</p>
      <div class="legal-actions">
        <a href="/" class="btn btn-ghost">&larr; Return to Home</a>
      </div>
    </div>
  </div>
</body>
</html>"""


def render_terms() -> str:
    """Render the styled terms of service."""
    return f"""<!doctype html>
<html lang="en">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>Power AI — Terms of Service</title>
  <link rel="preconnect" href="https://fonts.googleapis.com">
  <link rel="preconnect" href="https://fonts.gstatic.com" crossorigin>
  <meta name="color-scheme" content="light dark">
  <link href="https://fonts.googleapis.com/css2?family=Inter:opsz,wght@14..32,400..800&display=swap" rel="stylesheet">
  <link rel="stylesheet" href="/static/tokens.css">
  <link rel="stylesheet" href="/static/app.css">
</head>
<body>
  <div class="noise-overlay" aria-hidden="true"></div>
  <header class="site-header">
    <div class="site-header-inner">
      <a class="brand-link" href="/">
        <div class="mac-app-icon" aria-hidden="true">
          <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.5" stroke-linecap="round" stroke-linejoin="round">
            <polygon points="13 2 3 14 12 14 11 22 21 10 12 10 13 2"></polygon>
          </svg>
        </div>
        <span class="brand-name" style="white-space:nowrap">Power AI</span>
        <span class="brand-badge" style="white-space:nowrap">Training Log Agent</span>
      </a>
      <nav class="site-nav">
        <a class="nav-link" href="/">&larr; Return to Home</a>
        <a class="nav-link" href="/privacy">Privacy Policy</a>
      </nav>
    </div>
  </header>

  <div class="wrapper">
    <div class="legal-container">
      <div class="mac-eyebrow">Medical Boundaries &amp; Liability</div>
      <h1>Terms of Service</h1>
      <p>This service is a training-log and planning aid, not medical care or clinical diagnostic software. Athletes remain responsible for confirming calendar changes and following medical advice from their coach, clinician, or registered dietitian.</p>
      <p>Injury flags immediately suppress all load progression advice. The agent never prescribes load to an injured athlete; clearance requires explicit authorization by a named human coach or medical practitioner.</p>
      <div class="legal-actions">
        <a href="/" class="btn btn-ghost">&larr; Return to Home</a>
      </div>
    </div>
  </div>
</body>
</html>"""

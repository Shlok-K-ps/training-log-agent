
"""HTML views for the coach console, landing page, and legal notices.

Rendered server-side as pure strings with zero build step, no npm, and no JS framework.
Mobile-first layout designed for a coach on a phone at the gym or on a laptop.
"""

from __future__ import annotations

from datetime import date
from html import escape

from app.coach.roster import BUCKET_LABEL, BUCKET_ORDER, Bucket, PendingMessage, Roster


def _vt_athlete(athlete_id: str | None) -> str:
    if not athlete_id:
        return ""
    digits = "".join(c for c in athlete_id if c.isdigit())
    return f"athlete-{digits}" if digits else ""


def _vt_draft(athlete_id: str | None) -> str:
    if not athlete_id:
        return ""
    digits = "".join(c for c in athlete_id if c.isdigit())
    return f"draft-{digits}" if digits else ""


# ------------------------------------------------------------------------------
# Base CSS: Powerlifting visual identity (calibrated plates palette, mobile-first)
# Red 25kg (Action/Deload), Yellow 15kg (Watch/Stall), Blue 20kg (Meet/Nav), Green 10kg (On track)
# ------------------------------------------------------------------------------
_BASE_CSS = ""

def _card(entry) -> str:
    """Render an individual athlete card."""
    items = "".join(
        f'<li class="{"act" if f.action else ""}">{escape(f.detail)}</li>'
        for f in entry.flags
    )
    meta = []
    if entry.latest_session:
        meta.append(entry.latest_session)
    if entry.readiness_score is not None:
        meta.append(f"readiness {entry.readiness_score}/100")
    if entry.last_activity:
        meta.append(f"last log {entry.last_activity}")
    meta_html = (
        f'<p class="muted" style="margin:6px 0 0">{escape(" · ".join(meta))}</p>'
        if meta else ""
    )
    body = f"{meta_html}<ul>{items}</ul>" if items else meta_html
    form = ""
    if entry.needs_action and entry.injury_days_open is not None:
        form = (
            f'<p><a class="clearance-link" href="/coach/athlete/{escape(entry.athlete_id)}#clearance-review">'
            'Review injury clearance →</a></p>'
        )

    # Semantic badge label to guarantee severity is clear without color alone
    badge_markup = ""
    if entry.bucket is Bucket.NEEDS_YOU:
        badge_markup = '<span class="badge badge-red">[!] Needs Action</span>'
    elif entry.bucket is Bucket.WATCH:
        badge_markup = '<span class="badge badge-yellow">[!] Watch</span>'
    elif entry.bucket is Bucket.MEET_PREP:
        badge_markup = '<span class="badge badge-blue">[#] Meet Prep</span>'

    return (
        f'<div class="card {entry.bucket.value}">'
        f'<div class="who"><div><a class="name" href="/coach/athlete/{escape(entry.athlete_id)}">{escape(entry.display_name)}</a> {badge_markup}</div>'
        f'<span class="id">{escape(entry.athlete_id)}</span></div>'
        f"{body}{form}</div>"
    )


def _coach_nav(*, active: str, coach: str, pending_count: int = 0) -> str:
    """Stable product navigation shared by every authenticated coach page."""
    links = (
        ("overview", "/coach", "Overview"),
        ("athletes", "/coach/athletes", "Athletes"),
        ("whatsapp", "/coach/whatsapp", "WhatsApp Desk"),
        ("analytics", "/coach/analytics", "Goal Analytics"),
        ("outbox", "/coach/outbox", "Outbox"),
    )
    side_nav = []
    bottom_nav = []
    for key, href, label in links:
        is_active = key == active
        active_cls = " active" if is_active else ""
        badge = (
            f'<span class="nav-count">{pending_count}</span>'
            if (key == "whatsapp" or key == "outbox") and pending_count else ""
        )
        side_nav.append(
            f'<a class="nav-item{active_cls}" href="{href}">'
            f'<span>{label}</span>{badge}</a>'
        )
        bottom_nav.append(
            f'<a class="bottom-item{active_cls}" href="{href}">'
            f'<span>{label}</span>{badge}</a>'
        )
    return (
        '<aside class="side-nav">'
        '<div class="side-brand-wrap">'
        '<a class="side-brand" href="/coach">'
        '<div class="mac-app-icon" aria-hidden="true" style="width:24px;height:24px;border-radius:6px;">'
        '<svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.5"><polygon points="13 2 3 14 12 14 11 22 21 10 12 10 13 2"></polygon></svg>'
        '</div>'
        '<span class="brand-name">Power AI</span> <span class="brand-badge">Coach Desk</span>'
        '</a>'
        '</div>'
        f'<nav class="side-links" aria-label="Roster navigation">{"".join(side_nav)}</nav>'
        f'<div class="side-meta">'
        f'<div class="coach-profile">Signed in as <strong>{escape(coach)}</strong></div>'
        '<a class="signout-link" href="/coach/logout">&times; Sign out</a>'
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
) -> str:
    """The application shell: navigation stays put while the work changes."""
    vt_name = _vt_athlete(athlete_id) if athlete_id else "page-title"
    h1_style = f"style='view-transition-name: {vt_name};'" if vt_name else ""
    return (
        "<!doctype html><html lang='en'><head><meta charset='utf-8'>"
        "<meta name='viewport' content='width=device-width,initial-scale=1'>"
        f"<title>{escape(title)} — Power AI Coach Desk</title>"
        "<link rel='icon' href='data:image/svg+xml,<svg xmlns=%22http://www.w3.org/2000/svg%22 viewBox=%220 0 100 100%22><text y=%22.9em%22 font-size=%2290%22>⚡</text></svg>'>"
        "<link rel='preconnect' href='https://fonts.googleapis.com'>"
        "<link rel='preconnect' href='https://fonts.gstatic.com' crossorigin>"
        "<link href='https://fonts.googleapis.com/css2?family=Inter:wght@300;400;500;600;700&display=swap' rel='stylesheet'>"
        "<link rel='stylesheet' href='/static/tokens.css'>"
        "<link rel='stylesheet' href='/static/app.css'>"
        f"<style>{extra_style}</style>"
        "<script src='/static/motion.js' defer></script>"
        "</head><body>"
        "<canvas id='hero-canvas' class='mesh-canvas mesh-band' aria-hidden='true'></canvas>"
        "<div class='noise-overlay' aria-hidden='true'></div>"
        "<div class='app-shell'>"
        f"{_coach_nav(active=active, coach=coach, pending_count=pending_count)}"
        "<main class='workspace'><div class='workspace-head'><div>"
        f"<div class='workspace-eyebrow'>Power AI &middot; Coach Workspace</div><h1 {h1_style}>{escape(title)}</h1>"
        f"<p class='workspace-sub'>{escape(subtitle)}</p></div>"
        f"<span class='workspace-date'>{escape(str(today))}</span></div>"
        f"{body}<footer>Power AI &middot; Training Log Agent &middot; Recommendations shown here are assembled from the athlete's "
        "record and deterministic coaching rules. The coach remains the approval gate."
        "</footer></main></div></body></html>"
    )

def _register_form(today: date) -> str:
    days = '<option value="">Day</option>' + "".join(
        f'<option value="{value}">{value:02d}</option>' for value in range(1, 32)
    )
    months = (
        '<option value="">Month</option>' + "".join(
            f'<option value="{number}">{name}</option>'
            for number, name in enumerate(
                ("January", "February", "March", "April", "May", "June",
                 "July", "August", "September", "October", "November", "December"),
                start=1,
            )
        )
    )
    years = '<option value="">Year</option>' + "".join(
        f'<option value="{value}">{value}</option>'
        for value in range(today.year, today.year + 11)
    )
    return f"""
<section class="register"><h2>Add an athlete</h2>
<details class="onboarding" open><summary>Initial coaching profile</summary>
<form class="onboarding-form" method="post" action="/coach/athletes/register">
  <div class="onboarding-grid">
    <label>Name<input type="text" name="name" required maxlength="60" placeholder="Athlete name"></label>
    <label>WhatsApp number<input type="text" name="athlete_id" required maxlength="20" placeholder="+919812340001"></label>
    <label>Bodyweight (kg)<input type="number" name="bodyweight_kg" min="30" max="400" step="0.1" required></label>
    <label>Squat 1RM (kg)<input type="number" name="squat_1rm_kg" min="1" max="600" step="0.5" required></label>
    <label>Bench 1RM (kg)<input type="number" name="bench_1rm_kg" min="1" max="400" step="0.5" required></label>
    <label>Deadlift 1RM (kg)<input type="number" name="deadlift_1rm_kg" min="1" max="600" step="0.5" required></label>
    <label>Training days / week<input type="number" name="training_days" min="1" max="7" required></label>
    <label>Experience<select name="experience" required><option value="novice">Novice</option><option value="intermediate">Intermediate</option><option value="advanced">Advanced</option></select></label>
    <label>Goal lift<select name="goal_lift"><option value="">No numeric goal yet</option><option value="squat">Squat</option><option value="bench press">Bench press</option><option value="deadlift">Deadlift</option></select></label>
    <label>Goal 1RM (kg)<input type="number" name="goal_target_kg" min="1" max="700" step="0.5"></label>
    <label>Goal / meet date<span class="date-fields">
      <select name="goal_day" aria-label="Goal day">{days}</select>
      <select name="goal_month" aria-label="Goal month">{months}</select>
      <select name="goal_year" aria-label="Goal year">{years}</select>
    </span></label>
    <label class="onboarding-wide">Current injury or restriction<input type="text" name="injury_note" maxlength="240" placeholder="Leave blank if none; any entry opens the injury safety gate"></label>
  </div>
  <button type="submit">Create athlete profile</button>
  <p class="hint">These are coach-entered starting facts. They create the baseline for programme selection and goal pacing; they do not clear or diagnose injuries.</p>
</form></details></section>
"""


def _demo_controls(roster: Roster, has_demo: bool) -> str:
    """Keep demo controls available from Overview, even with a real roster."""
    if has_demo:
        return (
            '<div class="demo">'
            "<p>This roster includes demo athletes.</p>"
            '<form method="post" action="/coach/demo/clear">'
            '<button class="skip" type="submit">Remove demo athletes</button></form>'
            "</div>"
        )
    message = (
        "Nothing has been logged yet. Load a mixed fictional squad to explore every screen."
        if roster.total == 0 else
        "Add a mixed fictional squad alongside the roster to preview check-ins, injuries, goals and WhatsApp states."
    )
    return (
        '<div class="demo"><p>' + escape(message) + '</p>'
        '<form method="post" action="/coach/demo/seed">'
        '<button type="submit">Load a demo squad</button></form></div>'
    )


def _tutorial() -> str:
    return """
<div class="panel">
  <div class="panel-head"><h2>New here?</h2></div>
  <p class="section-note">Take a two-minute tour of the coach approval loop.</p>
  <button class="skip" type="button" onclick="document.getElementById('tutorial').showModal()">Open tutorial</button>
</div>
<dialog id="tutorial" style="max-width:620px;border:1px solid var(--border);border-radius:8px;background:var(--surface);color:var(--ink);padding:22px">
  <h1>How to use Coach Desk</h1>
  <ol>
    <li><strong>Add athletes:</strong> record bodyweight, 1RMs, training frequency, current injuries and a dated goal.</li>
    <li><strong>Read Overview:</strong> start with exceptions rather than checking every athlete manually.</li>
    <li><strong>Open WhatsApp:</strong> review new feedback, inspect the prepared change, and approve or hold the exact message.</li>
    <li><strong>Handle injuries:</strong> choose a bounded training pivot; the injury gate stays open until independent clearance.</li>
    <li><strong>Check Analytics:</strong> use ahead/on-track/lagging as a prompt to review—not an automatic programme change.</li>
  </ol>
  <p>For a safe walkthrough, load the demo squad and use “Test the WhatsApp workflow” inside WhatsApp.</p>
  <form method="dialog"><button type="submit">Got it</button></form>
</dialog>
"""


def render(
    roster: Roster,
    *,
    token: str = "",
    coach: str,
    message: tuple[str, str] | None = None,
    has_demo: bool = False,
    pending_count: int = 0,
) -> str:
    """Render the operating overview: one big thing, counts sentence, and grouped buckets."""
    banner = ""
    if message:
        kind, text = message
        banner = f'<div class="msg {escape(kind)}">{escape(text)}</div>'

    # 1. Counts sentence replacing the stat tiles
    needs_you_count = sum(1 for e in roster.entries if e.bucket is Bucket.NEEDS_YOU)
    watch_count = sum(1 for e in roster.entries if e.bucket is Bucket.WATCH)
    meet_prep_count = sum(1 for e in roster.entries if e.bucket is Bucket.MEET_PREP)
    fine_count = sum(1 for e in roster.entries if e.bucket is Bucket.FINE)

    counts_sentence = (
        f'<div class="counts-sentence">'
        f'<span class="dot-count act">● <span data-counter data-target="{needs_you_count}">{needs_you_count}</span> need attention</span> · '
        f'<span class="dot-count watch">● <span data-counter data-target="{watch_count}">{watch_count}</span> on watch</span> · '
        f'<span class="dot-count meet">● <span data-counter data-target="{meet_prep_count}">{meet_prep_count}</span> in meet prep</span> · '
        f'<span class="dot-count fine">● <span data-counter data-target="{fine_count}">{fine_count}</span> on track</span>'
        f'</div>'
    )

    # 2. One Big Thing panel: single most urgent Needs You athlete
    most_urgent = next((e for e in roster.entries if e.bucket is Bucket.NEEDS_YOU), None)
    if not most_urgent and roster.entries:
        most_urgent = next((e for e in roster.entries if e.bucket is Bucket.WATCH), None)

    one_big_thing = ""
    if most_urgent:
        signal = " · ".join(f.detail for f in most_urgent.flags) or "Urgent coach action required"
        action_btn = (
            f'<a class="btn btn-primary" href="/coach/athlete/{escape(most_urgent.athlete_id)}#clearance-review">'
            'Review injury clearance &rarr;</a>'
            if (most_urgent.needs_action and most_urgent.injury_days_open is not None) else
            f'<a class="btn btn-primary" href="/coach/athlete/{escape(most_urgent.athlete_id)}">'
            'Open athlete file &rarr;</a>'
        )
        obt_badge = (
            '<span class="obt-bucket tag-act">Needs You</span>'
            if most_urgent.bucket is Bucket.NEEDS_YOU else
            '<span class="obt-bucket tag-watch">Watch</span>'
        )
        one_big_thing = (
            f'<section class="one-big-thing" aria-label="Most urgent exception">'
            f'<div class="obt-header">'
            f'<span class="tag-mono" style="color:var(--plate-red-text)">PRIORITY 01 // IMMEDIATE ATTENTION</span>'
            f'{obt_badge}'
            f'</div>'
            f'<div class="obt-body">'
            f'<div class="obt-info">'
            f'<h2 class="obt-name"><a style="view-transition-name: { _vt_athlete(most_urgent.athlete_id) };" href="/coach/athlete/{escape(most_urgent.athlete_id)}">{escape(most_urgent.display_name)}</a></h2>'
            f'<div class="obt-meta">{escape(most_urgent.athlete_id)} &middot; Latest: {escape(most_urgent.latest_session or "No recent session")}</div>'
            f'<p class="obt-reason">{escape(signal)}</p>'
            f'</div>'
            f'<div class="obt-action">{action_btn}</div>'
            f'</div>'
            f'</section>'
        )

    # 3. Rest of the queue as glass rows grouped by bucket, Fine collapsed
    def render_row(entry) -> str:
        signal = " · ".join(f.detail for f in entry.flags) or "On track"
        readiness = (
            f'<span class="readiness-pill {escape(entry.readiness_band or "")}">'
            f'<span class="dot">●</span> {entry.readiness_score}/100</span>'
            if entry.readiness_score is not None else '<span class="muted">No check-in</span>'
        )
        action = ""
        if entry.needs_action and entry.injury_days_open is not None:
            action = (
                f'<div><a class="clearance-link" href="/coach/athlete/{escape(entry.athlete_id)}#clearance-review">'
                'Clearance &rarr;</a></div>'
            )
        return (
            '<div class="athlete-line">'
            f'<div><a class="athlete-name" style="view-transition-name: { _vt_athlete(entry.athlete_id) };" href="/coach/athlete/{escape(entry.athlete_id)}">{escape(entry.display_name)}</a>'
            f'<div class="muted">{escape(entry.latest_session or "No session logged")}</div></div>'
            f'<div class="signal">{escape(signal)}</div>{readiness}{action}</div>'
        )

    # Buckets: Needs you, Watch, Meet prep
    bucket_sections = []
    bucket_groups = [
        ("Needs you", [e for e in roster.entries if e.bucket is Bucket.NEEDS_YOU and e != most_urgent], "tag-act"),
        ("Watch", [e for e in roster.entries if e.bucket is Bucket.WATCH and e != most_urgent], "tag-watch"),
        ("Meet prep", [e for e in roster.entries if e.bucket is Bucket.MEET_PREP], "tag-meet"),
    ]
    for title, entries, tag_cls in bucket_groups:
        if entries:
            bucket_sections.append(
                f'<div class="bucket-group">'
                f'<div class="bucket-group-title"><span class="badge {tag_cls}">{escape(title)}</span> '
                f'<span class="muted">({len(entries)})</span></div>'
                f'{"".join(render_row(e) for e in entries)}'
                f'</div>'
            )

    fine_entries = [e for e in roster.entries if e.bucket is Bucket.FINE]
    fine_markup = ""
    if fine_entries:
        fine_markup = (
            f'<details class="fine-collapse">'
            f'<summary class="fine-summary">'
            f'<span>Fine ({len(fine_entries)}) &mdash; athletes on track</span>'
            f'<span>&darr;</span>'
            f'</summary>'
            f'<div class="fine-rows">{"".join(render_row(e) for e in fine_entries)}</div>'
            f'</details>'
        )

    priority_body = (
        "".join(bucket_sections) + fine_markup
        if (bucket_sections or fine_markup)
        else '<p class="empty">No athletes in squad.</p>'
    )

    # 4. Daily agent loop: fixed numbering 01, 02, 03, no emoji/symbols in headings
    workflow = (
        '<div class="panel"><div class="panel-head"><h2>Daily agent loop</h2></div>'
        '<div class="flow-step"><b>01</b><div><strong>Observe</strong><p>Sleep, readiness, training and nutrition arrive through WhatsApp.</p></div></div>'
        '<div class="flow-step"><b>02</b><div><strong>Prepare</strong><p>Rules combine today\'s check-in with history and current trends.</p></div></div>'
        '<div class="flow-step"><b>03</b><div><strong>Verify</strong><p>You edit or approve; only your approved wording can leave the queue.</p></div></div>'
        '</div>'
    )

    squad_links = ", ".join(
        f'<a class="athlete-name" href="/coach/athlete/{escape(entry.athlete_id)}">{escape(entry.display_name)}</a>'
        for entry in roster.entries
    ) or '<span class="empty">No athletes yet.</span>'
    squad_panel = (
        '<div class="panel"><div class="panel-head"><h2>Squad directory</h2>'
        '<a href="/coach/athletes">Open directory &rarr;</a></div>'
        f'<p style="font-size:13px;line-height:1.8;margin:0">{squad_links}</p></div>'
    )

    body = (
        f"{banner}"
        f"{one_big_thing}"
        f"{counts_sentence}"
        '<div class="dashboard-grid">'
        '<div>'
        '<div class="panel"><div class="panel-head"><h2>Roster priorities</h2>'
        '<a href="/coach/athletes">View all athletes &rarr;</a></div>'
        f'{priority_body}</div>'
        '</div>'
        '<div>'
        '<div class="panel"><div class="panel-head"><h2>Approval queue</h2>'
        '<a href="/coach/whatsapp?tab=approval">Open queue &rarr;</a></div>'
        f'<p style="font-size:32px;font-weight:800;letter-spacing:-0.02em;margin:2px 0"><span data-counter data-target="{pending_count}">{pending_count}</span></p>'
        '<p class="section-note">Prepared messages waiting for a human decision.</p></div>'
        f'{workflow}{_tutorial()}{squad_panel}'
        '</div>'
        '</div>'
        + _demo_controls(roster, has_demo)
    )
    return coach_frame(
        body, active="overview", coach=coach, title="Overview",
        subtitle="The decisions and exceptions that need a coach today.",
        today=roster.reviewed_on.isoformat(), pending_count=pending_count,
    )


def render_athletes(
    roster: Roster,
    *,
    coach: str,
    message: tuple[str, str] | None = None,
    has_demo: bool = False,
    pending_count: int = 0,
) -> str:
    """Searchable squad directory with current readiness and training context."""
    banner = ""
    if message:
        kind, text = message
        banner = f'<div class="msg {escape(kind)}">{escape(text)}</div>'
    rows = []
    for entry in roster.entries:
        status = " · ".join(f.detail for f in entry.flags) or "On track"
        readiness = (
            f'<span class="readiness-pill {escape(entry.readiness_band or "")}">{entry.readiness_score}/100</span>'
            if entry.readiness_score is not None else '<span class="muted">Not checked in</span>'
        )
        haystack = f"{entry.display_name} {entry.athlete_id} {entry.bucket.value} {status}".lower()
        dot_cls = "act" if entry.bucket is Bucket.NEEDS_YOU else ("watch" if entry.bucket is Bucket.WATCH else ("meet" if entry.bucket is Bucket.MEET_PREP else "fine"))
        rows.append(
            f'<div class="directory-row athlete-record" data-bucket="{entry.bucket.value}" '
            f'data-search="{escape(haystack)}">'
            f'<div><span class="dot-count {dot_cls}">●</span> <a class="athlete-name" style="view-transition-name: { _vt_athlete(entry.athlete_id) };" href="/coach/athlete/{escape(entry.athlete_id)}">{escape(entry.display_name)}</a>'
            f'<div class="muted">{escape(entry.athlete_id)}</div></div>'
            f'<div><strong style="font-size:13px">{escape(entry.training_summary or "No training baseline")}</strong>'
            f'<div class="muted">{escape(status)}</div></div>{readiness}'
            f'<div class="muted">{escape(entry.last_activity or "Never")}</div></div>'
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
</script>"""
    body = (
        f"{banner}{_demo_controls(roster, has_demo)}{tools}{directory}"
        f"{_register_form(roster.reviewed_on)}{script}"
    )
    return coach_frame(
        body, active="athletes", coach=coach, title="Athletes",
        subtitle="Current status, recent progress and readiness across the full squad.",
        today=roster.reviewed_on.isoformat(), pending_count=pending_count,
    )


def _outbox_card(item: PendingMessage) -> str:
    a = item.athlete
    reasons = " · ".join(escape(f.detail) for f in a.flags) or "nothing flagged"
    readiness = (
        f"{a.readiness_score}/100 · {a.readiness_band}"
        if a.readiness_score is not None else "No same-day check-in"
    )
    return (
        f'<div class="card {a.bucket.value} message-card" style="view-transition-name: { _vt_draft(item.athlete_id) };">'
        '<div class="panel-head"><div>'
        f'<a class="athlete-name" href="/coach/athlete/{escape(item.athlete_id)}">'
        f'{escape(a.display_name)}</a>'
        f'<div class="muted">{escape(item.message_kind.replace("_", " ").title())} &middot; '
        f'{escape(item.local_date)}</div></div>'
        '<span class="readiness-pill yellow">Awaiting approval</span></div>'
        '<div class="evidence-grid">'
        f'<div><span>Training trend</span><strong>{escape(a.training_summary or "No baseline")}</strong></div>'
        f'<div><span>Latest session</span><strong>{escape(a.latest_session or "Nothing logged")}</strong></div>'
        f'<div><span>Readiness</span><strong>{escape(readiness)}</strong></div>'
        '</div>'
        f'<p class="evidence-reason"><b>Why surfaced:</b> {reasons}</p>'
        '<form method="post" action="/coach/outbox/review">'
        f'<input type="hidden" name="athlete_id" value="{escape(item.athlete_id)}">'
        f'<input type="hidden" name="message_kind" value="{escape(item.message_kind)}">'
        f'<input type="hidden" name="local_date" value="{escape(item.local_date)}">'
        '<label class="draft-label">Message the athlete will receive (editable in place)</label>'
        f'<textarea name="body" maxlength="1400">{escape(item.body)}</textarea>'
        '<div style="display:flex;gap:10px;margin-top:12px;flex-wrap:wrap;">'
        '<button class="btn btn-primary" type="submit" name="decision" value="approved">&check; '
        f'Approve for {escape(item.local_date)}</button>'
        '<button class="btn btn-ghost" type="submit" name="decision" value="skipped">'
        "&times; Hold / Don’t send</button></div></form></div>"
    )


def render_outbox(
    pending: tuple[PendingMessage, ...],
    *,
    token: str = "",
    coach: str,
    today,
    message: tuple[str, str] | None = None,
) -> str:
    """Render the outbox review queue."""
    banner = ""
    if message:
        kind, text = message
        banner = f'<div class="msg {escape(kind)}">{escape(text)}</div>'

    if not pending:
        body = (
            '<p class="empty">Nothing is queued. Drafts appear the evening before '
            "each athlete's morning, in their own timezone.</p>"
        )
    else:
        cards = [_outbox_card(item) for item in pending]
        body = (
            f"<section><h2>Queued for tomorrow <span class='n'>{len(pending)}</span></h2>"
            + "".join(cards)
            + "</section>"
        )

    intro = (
        '<div class="review-note"><div><strong>Human approval is the final step.</strong> '
        'The agent prepared each draft from recorded history and current status. '
        'Edit freely, approve it, or hold it back. <strong>Nothing below has been sent.</strong></div></div>'
    )
    return coach_frame(
        f"{banner}{intro}{body}", active="outbox", coach=coach,
        title="Outbox",
        subtitle="Verify the evidence, edit the wording, then approve what goes to each athlete.",
        today=today.isoformat(), pending_count=len(pending),
    )


def render_login(error: str | None = None, message: str | None = None) -> str:
    """Render the coach sign-in page."""
    error_markup = f'<div class="msg err">{escape(error)}</div>' if error else ""
    msg_markup = f'<div class="msg ok">{escape(message)}</div>' if message else ""

    return f"""<!doctype html>
<html lang="en">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>Power AI — Coach Sign In</title>
  <link rel="preconnect" href="https://fonts.googleapis.com">
  <link rel="preconnect" href="https://fonts.gstatic.com" crossorigin>
  <link href="https://fonts.googleapis.com/css2?family=Inter:wght@300;400;500;600;700&display=swap" rel="stylesheet">
  <link rel="stylesheet" href="/static/tokens.css">
  <link rel="stylesheet" href="/static/app.css">
  <script src="/static/motion.js" defer></script>
</head>
<body>
  <canvas id="hero-canvas" class="mesh-canvas" aria-hidden="true"></canvas>
  <div class="noise-overlay" aria-hidden="true"></div>
  <div class="wrapper" style="min-height: 100vh; display: flex; align-items: center; justify-content: center;">
    <div class="login-box">
      <div class="brand-link" style="margin-bottom: 20px;">
        <div class="mac-app-icon" aria-hidden="true" style="width:28px;height:28px;border-radius:7px;">
          <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.5"><polygon points="13 2 3 14 12 14 11 22 21 10 12 10 13 2"></polygon></svg>
        </div>
        <span class="brand-name">Power AI</span>
        <span class="brand-badge">Coach Access</span>
      </div>
      <h1>Coach Sign In</h1>
      <p>Enter your coach access token. Authenticating sets a secure HTTP-only cookie so your token is never exposed in page URLs.</p>
      {error_markup}
      {msg_markup}
      <form method="post" action="/coach/login">
        <label class="mac-eyebrow" for="token" style="margin-bottom: 8px; display: block;">Coach Access Token</label>
        <input type="password" id="token" name="token" required autofocus autocomplete="current-password" placeholder="Paste coach token here">
        <button type="submit" class="btn btn-mac-primary" style="margin-top: 12px; width: 100%; padding: 10px 18px;">Authenticate &rarr;</button>
      </form>
      <div style="margin-top: 24px; text-align: center;">
        <a class="back-link" href="/">&larr; Back to Public Overview</a>
      </div>
    </div>
  </div>
</body>
</html>"""


def render_landing(*, is_logged_in: bool = False) -> str:
    """Render the public landing page with Power AI design system."""
    coach_link = "/coach" if is_logged_in else "/coach/login"
    coach_text = "Open Coach Desk" if is_logged_in else "Coach Sign In"
    arrow_svg = (
        '<svg width="14" height="14" viewBox="0 0 24 24" fill="none" '
        'stroke="currentColor" stroke-width="2.5" stroke-linecap="round" stroke-linejoin="round">'
        '<line x1="7" y1="17" x2="17" y2="7"></line>'
        '<polyline points="7 7 17 7 17 17"></polyline></svg>'
    )

    return f"""<!doctype html>
<html lang="en">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>Power AI — WhatsApp Powerlifting Coach</title>
  <link rel="icon" href="data:image/svg+xml,<svg xmlns=%22http://www.w3.org/2000/svg%22 viewBox=%220 0 100 100%22><text y=%22.9em%22 font-size=%2290%22>⚡</text></svg>">
  <link rel="preconnect" href="https://fonts.googleapis.com">
  <link rel="preconnect" href="https://fonts.gstatic.com" crossorigin>
  <link href="https://fonts.googleapis.com/css2?family=Inter:wght@300;400;500;600;700&display=swap" rel="stylesheet">
  <link rel="stylesheet" href="/static/tokens.css">
  <link rel="stylesheet" href="/static/app.css">
  <script src="/static/motion.js" defer></script>
</head>
<body>
  <!-- Fixed WebGL Mesh Canvas & Noise Grain -->
  <canvas id="hero-canvas" class="mesh-canvas" aria-hidden="true"></canvas>
  <div class="noise-overlay" aria-hidden="true"></div>

  <!-- Header Navigation -->
  <header class="site-header">
    <div class="site-header-inner">
      <a class="brand-link" href="/">
        <div class="mac-app-icon" aria-hidden="true">
          <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.5" stroke-linecap="round" stroke-linejoin="round">
            <polygon points="13 2 3 14 12 14 11 22 21 10 12 10 13 2"></polygon>
          </svg>
        </div>
        <span class="brand-name">Power AI</span>
        <span class="brand-badge">Training Log Agent</span>
      </a>
      <div class="header-status">
        <span class="pulse-dot"></span>
        <span>Active &middot; Deterministic</span>
      </div>
      <nav class="site-nav">
        <a class="nav-link" href="#protocols">Protocols</a>
        <a class="nav-link" href="#architecture">Architecture</a>
        <a class="nav-link" href="#boundaries">Boundaries</a>
        <a class="nav-link" href="https://github.com/Shlok-K-ps/training-log-agent" target="_blank" rel="noopener">GitHub &nearr;</a>
        <a class="btn btn-mac-primary" href="{coach_link}">
          <span>{coach_text}</span>
          {arrow_svg}
        </a>
      </nav>
    </div>
  </header>

  <main class="wrapper">
    <!-- Hero Section -->
    <section class="hero">
      <div class="mac-pill-eyebrow"><span class="mac-pill-icon">⚡</span> WhatsApp Powerlifting Intelligence</div>
      <h1 class="hero-h1">
        The coach reads exceptions,<br>
        <span class="serif">not twenty WhatsApp texts a day.</span>
      </h1>
      <p class="hero-lead">
        A WhatsApp agent for a 20-athlete powerlifting squad. Athletes text their sessions, sleep, and soreness; deterministic Python evaluates progress and readiness; the coach triages exceptions and approves drafted morning messages.
      </p>
      <div class="cta-row">
        <a class="btn btn-mac-primary btn-lg" href="{coach_link}">
          <span>{coach_text} &rarr;</span>
        </a>
        <a class="btn btn-ghost btn-lg" href="https://github.com/Shlok-K-ps/training-log-agent" target="_blank" rel="noopener">
          <span>Read Source on GitHub &nearr;</span>
        </a>
      </div>

      <!-- Studio Specs Strip (Twilio) -->
      <div class="specs-strip">
        <div class="spec-col">
          <span class="spec-num">01</span>
          <span class="spec-name">INGESTION</span>
          <span class="spec-detail">Twilio &middot; Vonage Sandbox</span>
        </div>
        <div class="spec-col">
          <span class="spec-num">02</span>
          <span class="spec-name">SCHEMA PARSER</span>
          <span class="spec-detail">Gemini Flash</span>
        </div>
        <div class="spec-col">
          <span class="spec-num">03</span>
          <span class="spec-name">DECISION ENGINE</span>
          <span class="spec-detail">Pure Python Rules</span>
        </div>
        <div class="spec-col">
          <span class="spec-num">04</span>
          <span class="spec-name">GROUND TRUTH</span>
          <span class="spec-detail">Top 300 All-Time Dots</span>
        </div>
      </div>

      <!-- WhatsApp Simulation Showcase (macOS Window with traffic lights & segmented control) -->
      <div id="protocols" class="showcase-container">
        <div class="mac-window-titlebar">
          <div class="mac-traffic-lights" aria-hidden="true">
            <span class="mac-light mac-close"></span>
            <span class="mac-light mac-min"></span>
            <span class="mac-light mac-max"></span>
          </div>
          <span class="mac-window-title">WhatsApp Lifter Console</span>
          <div class="mac-window-dummy"></div>
        </div>
        <div class="showcase-body">
          <div class="showcase-header">
            <div>
              <span class="mac-eyebrow">WhatsApp Conversation Protocol</span>
              <h3 style="font-size: 18px; margin-top: 4px; font-weight: 600;">Raw Lifter Notes &rarr; Structured Verdicts</h3>
            </div>
            <div class="scenario-pills">
              <button class="scenario-btn active" data-scenario="stall" onclick="switchScenario('stall')">Stalled Squat (140kg)</button>
              <button class="scenario-btn" data-scenario="injury" onclick="switchScenario('injury')">Acute Shoulder Pain</button>
              <button class="scenario-btn" data-scenario="pr" onclick="switchScenario('pr')">Bench Press PR</button>
            </div>
          </div>

          <div class="chat-box">
            <div id="chat-athlete-msg" class="chat-bubble chat-athlete">
              squat 3x5 at 140 today, felt way harder than tuesday, rpe 9
              <span class="chat-meta">17:42 &check;&check;</span>
            </div>
            <div id="chat-agent-msg" class="chat-bubble chat-agent">
              <div class="chat-reply-header">
                <span class="chat-verdict tag-watch">Squat — Stalled</span>
                <span class="chat-meta">17:42</span>
              </div>
              <div class="chat-logged-line">&check; Logged: Squat 3x5 @ 140 kg RPE 9</div>
              <div class="chat-body-line">Flat at 140 kg for 2 sessions with RPE climbing &mdash; same bar, more effort.</div>
            </div>
          </div>
        </div>
      </div>
    </section>

    <!-- 3-Layers Section -->
    <section id="architecture" class="content-section">
      <div class="section-head">
        <span class="mac-eyebrow">Architectural Separation</span>
        <h2 class="section-title">The Core Separation <span class="serif">3 Layers</span></h2>
        <p class="section-desc">
          Messy input needs a language model; coaching advice real humans lift under must be provable, repeatable, and deterministic. The split is the whole design:
        </p>
      </div>

      <div class="grid-3">
        <div class="feature-card">
          <span class="feature-badge badge-blue">LAYER 1 &middot; PARSE</span>
          <h3>Gemini Flash</h3>
          <p>Extracts unstructured English into 20 typed function schemas. Ceilings and ratios are range-checked. <em>The model cannot write reply text.</em></p>
        </div>
        <div class="feature-card">
          <span class="feature-badge badge-yellow">LAYER 2 &middot; STORE</span>
          <h3>Single SQLite Timeline</h3>
          <p>Every message is an immutable observation. Phone numbers serve as tenant identity. Calendar tokens and locations are encrypted at rest.</p>
        </div>
        <div class="feature-card">
          <span class="feature-badge badge-red">LAYER 3 &middot; DECIDE</span>
          <h3>Pure Python Rules</h3>
          <p>Zero model. Zero API calls. Zero randomness. Evaluates session deltas, RPE slides, deloads, and sleep recovery deterministically.</p>
        </div>
      </div>
    </section>

    <!-- Authority Boundaries Section -->
    <section id="boundaries" class="content-section">
      <div class="section-head">
        <span class="mac-eyebrow">Safety Governance &amp; Boundaries</span>
        <h2 class="section-title">Authority Boundaries <span class="serif">Who Decides What</span></h2>
        <p class="section-desc">
          Safety is enforced by immutable software boundaries, not system prompt guidelines. Neither the lifter nor the LLM has permission to override coaching gates.
        </p>
      </div>

      <div class="table-container">
        <table class="data-table">
          <thead>
            <tr>
              <th>Action</th>
              <th>Athlete</th>
              <th>Agent</th>
              <th>Coach</th>
            </tr>
          </thead>
          <tbody>
            <tr>
              <td>Report session, pain, sleep, food</td>
              <td><strong>&check; Allowed</strong></td>
              <td>&mdash;</td>
              <td>&mdash;</td>
            </tr>
            <tr>
              <td>Parse message into structured data</td>
              <td>&mdash;</td>
              <td><strong>&check; Allowed</strong></td>
              <td>&mdash;</td>
            </tr>
            <tr>
              <td>Judge progressing / stalled / deload</td>
              <td>&mdash;</td>
              <td><strong>&check; Deterministic</strong></td>
              <td>&mdash;</td>
            </tr>
            <tr>
              <td>Open an injury flag</td>
              <td>&check; Allowed</td>
              <td>&check; Allowed</td>
              <td>&check; Allowed</td>
            </tr>
            <tr>
              <td><strong>Close an injury flag</strong></td>
              <td><span style="color:var(--plate-red); font-weight:600;">&cross; Enforced in code</span></td>
              <td><span style="color:var(--plate-red); font-weight:600;">&cross; Enforced in code</span></td>
              <td><strong style="color:var(--plate-green);">&check; Coach Only</strong></td>
            </tr>
            <tr>
              <td>Approve supplement regimen</td>
              <td>&cross;</td>
              <td>&cross;</td>
              <td><strong style="color:var(--plate-green);">&check; Coach Only</strong></td>
            </tr>
          </tbody>
        </table>
      </div>
    </section>

    <!-- Grounded in Meet Data Section -->
    <section id="benchmarks" class="content-section">
      <div class="section-head">
        <span class="mac-eyebrow">Empirical Ground Truth</span>
        <h2 class="section-title">Grounded in Meet Data <span class="serif">Top 300 All-Time</span></h2>
        <p class="section-desc">
          Validation bounds and plausibility checks are derived directly from OpenPowerlifting competition results (top 300 lifters by Dots, Raw+Wraps), recomputed by the test suite on every run so code cannot drift from empirical evidence.
        </p>
      </div>

      <div class="stats-grid">
        <div class="stat-tile">
          <span class="stat-val">300</span>
          <span class="stat-lbl">All-Time Top Lifters</span>
        </div>
        <div class="stat-tile">
          <span class="stat-val">500 kg</span>
          <span class="stat-lbl">Max Plausible Squat</span>
        </div>
        <div class="stat-tile">
          <span class="stat-val">365 kg</span>
          <span class="stat-lbl">Max Plausible Bench</span>
        </div>
        <div class="stat-tile">
          <span class="stat-val">460 kg</span>
          <span class="stat-lbl">Max Plausible Deadlift</span>
        </div>
      </div>
    </section>

    <!-- Agentic product difference -->
    <section id="agentic" class="content-section">
      <div class="section-head">
        <span class="mac-eyebrow">WHY THIS IS AN AGENT, NOT A CHAT WINDOW</span>
        <h2 class="section-title">Conversation answers once. <span class="serif">This system keeps working.</span></h2>
        <p class="section-desc">
          A normal Claude or ChatGPT conversation can discuss a programme, but it does not own the squad workflow. Power AI observes new athlete events, preserves longitudinal state, proposes bounded actions, waits for authority, executes approved messages, and verifies delivery.
        </p>
      </div>
      <div class="grid-3">
        <div class="feature-card"><span class="feature-badge badge-blue">PERSISTENT STATE</span><h3>Remembers the actual journey</h3><p>Sessions, sleep, nutrition, injuries, goals, calendar constraints, approvals and delivery events remain connected to the athlete—not to one chat transcript.</p></div>
        <div class="feature-card"><span class="feature-badge badge-yellow">EVENT-DRIVEN</span><h3>Acts when facts change</h3><p>A morning check-in, missed log, fresh injury or new schedule conflict recomputes the relevant plan and opens a coach decision.</p></div>
        <div class="feature-card"><span class="feature-badge badge-red">CONTROLLED ACTION</span><h3>Closes the loop</h3><p>The coach approves exact wording; the system schedules it, sends through WhatsApp, records who approved it, and tracks delivered, read or failed.</p></div>
      </div>
      <div class="table-container"><table class="data-table"><thead><tr><th>Capability</th><th>Normal chat</th><th>Power AI</th></tr></thead><tbody>
        <tr><td>Twenty-athlete longitudinal state</td><td>Manually supplied context</td><td><strong>Stored and continuously updated</strong></td></tr>
        <tr><td>Proactive daily workflow</td><td>Waits for a prompt</td><td><strong>Drafts, schedules and surfaces exceptions</strong></td></tr>
        <tr><td>Safety authority</td><td>Prompt instruction</td><td><strong>Code-enforced injury and supplement gates</strong></td></tr>
        <tr><td>External action</td><td>Produces prose</td><td><strong>Coach-approved WhatsApp and calendar execution</strong></td></tr>
        <tr><td>Audit</td><td>Read the transcript</td><td><strong>Evidence version, approver and delivery state</strong></td></tr>
      </tbody></table></div>
    </section>

    <!-- Transparent Engineering Note -->
    <div class="mac-note-wrap">
      <div class="mac-note">
        <span class="mac-note-badge">Pure Python &amp; SQLite</span>
        <span class="mac-note-text">
          <strong>Transparent Note:</strong> This is a student-built engineering project for a 20-athlete powerlifting squad, not a venture-backed commercial SaaS. Zero trackers, zero analytics cookies, and no runtime framework beyond Python and SQLite.
        </span>
      </div>
    </div>

    <!-- Squad Deployment CTA Section (Completely frameless, seamless Apple CTA) -->
    <section class="mac-cta-section">
      <div class="mac-eyebrow">Ready for Squad Deployment</div>
      <h2 class="mac-cta-headline">
        The squad on WhatsApp.<br>
        <span class="mac-cta-accent">The coach in control.</span>
      </h2>
      <p class="mac-cta-sub">Deterministic rules, instant athlete triage, coach approval required for every message.</p>
      <div class="mac-cta-actions">
        <a class="btn btn-mac-primary btn-lg" href="{coach_link}">
          <span>{coach_text}</span>
          {arrow_svg}
        </a>
      </div>
    </section>
  </main>

  <!-- Full-Width Seamless Footer -->
  <footer class="site-footer">
    <div class="wrapper">
      <div class="footer-bottom">
        <div>Training Log Agent &middot; Built for Powerlifting Teams</div>
        <div>
          <a href="/privacy">Privacy Policy</a> &middot;
          <a href="/terms">Terms of Service</a> &middot;
          <a href="https://github.com/Shlok-K-ps/training-log-agent" target="_blank" rel="noopener">GitHub</a>
        </div>
        <div class="footer-clock">
          <span id="utc-clock">00:00:00 UTC</span> &middot; HOSTED ON RENDER
        </div>
        <div>
          <a href="#" class="back-to-top">Back to Top &uarr;</a>
        </div>
      </div>
    </div>
  </footer>
</body>
</html>"""


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
  <link href="https://fonts.googleapis.com/css2?family=Inter:wght@300;400;500;600;700&display=swap" rel="stylesheet">
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
        <span class="brand-name">Power AI</span>
        <span class="brand-badge">Training Log Agent</span>
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
      <p>Calendar connection is optional. The service reads event start/end times and usable locations only to plan travel and training. It does not retain event titles, descriptions, attendees or meeting content.</p>
      <p>OAuth tokens and saved places are encrypted at rest with Fernet cryptography when the calendar integration is configured. Confirmed workout references are stored until the athlete asks to delete them. Calendar data is never sold and is never sent to the language model.</p>
      <p>Training, sleep, readiness and nutrition messages may be sent to the configured language-model provider for structured parsing. Coaching decisions are made by deterministic application rules in pure Python, not by that model.</p>
      <p>Athletes can send <em>“disconnect calendar”</em> in WhatsApp to delete stored calendar tokens, or <em>“forget my locations”</em> to erase saved home, office and gym places.</p>
      <div style="margin-top:32px;padding-top:20px;border-top:1px solid var(--border);">
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
  <link href="https://fonts.googleapis.com/css2?family=Inter:wght@300;400;500;600;700&display=swap" rel="stylesheet">
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
        <span class="brand-name">Power AI</span>
        <span class="brand-badge">Training Log Agent</span>
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
      <div style="margin-top:32px;padding-top:20px;border-top:1px solid var(--border);">
        <a href="/" class="btn btn-ghost">&larr; Return to Home</a>
      </div>
    </div>
  </div>
</body>
</html>"""

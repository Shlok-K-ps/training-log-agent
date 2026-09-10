"""HTML views for the coach console, landing page, and legal notices.

Rendered server-side as pure strings with zero build step, no npm, and no JS framework.
Mobile-first layout designed for a coach on a phone at the gym or on a laptop.
"""

from __future__ import annotations

from html import escape

from app.coach.roster import BUCKET_LABEL, BUCKET_ORDER, Bucket, PendingMessage, Roster


# ------------------------------------------------------------------------------
# Base CSS: Powerlifting visual identity (calibrated plates palette, mobile-first)
# Red 25kg (Action/Deload), Yellow 15kg (Watch/Stall), Blue 20kg (Meet/Nav), Green 10kg (On track)
# ------------------------------------------------------------------------------
_BASE_CSS = """
.who a.name{color:inherit;text-decoration:none;border-bottom:1px solid var(--line)}
.who a.name:hover{border-bottom-color:currentColor}
.register form{display:flex;gap:7px;flex-wrap:wrap;align-items:center}
.register .hint{font-size:12.5px;color:var(--faint);margin:9px 0 0}
.demo{background:var(--card);border:1px solid var(--line);border-radius:3px;
padding:14px 16px;margin-bottom:22px}
.demo p{margin:0 0 9px;font-size:14.5px;color:var(--soft)}
:root {
  --bg: #f4f5f6;
  --surface: #ffffff;
  --surface-raised: #fbfcfc;
  --surface-inset: #eef1f3;
  --ink: #111827;
  --ink-soft: #4b5563;
  --ink-faint: #6b7280;
  --border: #d1d5db;
  --border-strong: #9ca3af;
  
  /* Competition Calibrated Plates */
  --plate-red: #dc2626;
  --plate-red-bg: #fef2f2;
  --plate-red-border: #fca5a5;
  --plate-red-text: #991b1b;

  --plate-yellow: #d97706;
  --plate-yellow-bg: #fffbeb;
  --plate-yellow-border: #fcd34d;
  --plate-yellow-text: #92400e;

  --plate-blue: #2563eb;
  --plate-blue-bg: #eff6ff;
  --plate-blue-border: #93c5fd;
  --plate-blue-text: #1e40af;

  --plate-green: #16a34a;
  --plate-green-bg: #f0fdf4;
  --plate-green-border: #86efac;
  --plate-green-text: #166534;
}

@media (prefers-color-scheme: dark) {
  :root {
    --bg: #0d1117;
    --surface: #161b22;
    --surface-raised: #1c2128;
    --surface-inset: #090d12;
    --ink: #f3f4f6;
    --ink-soft: #9ca3af;
    --ink-faint: #6b7280;
    --border: #30363d;
    --border-strong: #484f58;

    --plate-red: #ef4444;
    --plate-red-bg: #291215;
    --plate-red-border: #7f1d1d;
    --plate-red-text: #fca5a5;

    --plate-yellow: #f59e0b;
    --plate-yellow-bg: #26190b;
    --plate-yellow-border: #78350f;
    --plate-yellow-text: #fde68a;

    --plate-blue: #3b82f6;
    --plate-blue-bg: #111d33;
    --plate-blue-border: #1e3a8a;
    --plate-blue-text: #93c5fd;

    --plate-green: #22c55e;
    --plate-green-bg: #0f2415;
    --plate-green-border: #14532d;
    --plate-green-text: #86efac;
  }
}

* { box-sizing: border-box; }
body {
  margin: 0;
  background: var(--bg);
  color: var(--ink);
  font-family: ui-sans-serif, system-ui, -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, "Helvetica Neue", Arial, sans-serif;
  font-size: 15px;
  line-height: 1.55;
  -webkit-font-smoothing: antialiased;
}

.wrap {
  max-width: 780px;
  margin: 0 auto;
  padding: 24px 16px 64px;
}

.wrap-wide {
  max-width: 880px;
  margin: 0 auto;
  padding: 28px 20px 80px;
}

/* Nav & Header */
header {
  border-bottom: 2px solid var(--ink);
  padding-bottom: 14px;
  margin-bottom: 20px;
}
.header-top {
  display: flex;
  justify-content: space-between;
  align-items: center;
  flex-wrap: wrap;
  gap: 12px;
}
.brand {
  display: flex;
  align-items: center;
  gap: 10px;
  font-weight: 700;
  font-size: 18px;
  letter-spacing: -0.01em;
  color: var(--ink);
  text-decoration: none;
}
.brand-badge {
  font-size: 10.5px;
  font-weight: 800;
  letter-spacing: 0.08em;
  text-transform: uppercase;
  background: var(--ink);
  color: var(--bg);
  padding: 2px 7px;
  border-radius: 3px;
  font-family: ui-monospace, monospace;
}
.header-nav {
  display: flex;
  align-items: center;
  gap: 12px;
  font-size: 13.5px;
}
.header-nav a {
  color: var(--ink-soft);
  text-decoration: none;
  font-weight: 500;
  padding: 4px 8px;
  border-radius: 3px;
  transition: all 0.15s ease;
}
.header-nav a:hover {
  color: var(--ink);
  background: var(--surface-inset);
}
.header-nav a.active {
  color: var(--ink);
  background: var(--surface);
  border: 1px solid var(--border);
  font-weight: 600;
}
.header-nav a.danger {
  color: var(--plate-red);
}
.when {
  font-size: 13px;
  color: var(--ink-faint);
  font-family: ui-monospace, monospace;
  font-variant-numeric: tabular-nums;
}

/* Typography & Badges */
h1 {
  font-size: 20px;
  margin: 0;
  letter-spacing: -0.01em;
  font-weight: 700;
}
h2 {
  font-size: 11.5px;
  letter-spacing: 0.12em;
  text-transform: uppercase;
  color: var(--ink-faint);
  margin: 0 0 10px;
  display: flex;
  align-items: center;
  gap: 8px;
  font-weight: 700;
}
h2 .n {
  color: var(--ink);
  font-family: ui-monospace, monospace;
}
.summary {
  margin: 14px 0 22px;
  font-size: 15px;
  color: var(--ink-soft);
}
.summary b { color: var(--ink); }

.badge {
  display: inline-flex;
  align-items: center;
  gap: 4px;
  font-size: 11px;
  font-weight: 700;
  letter-spacing: 0.05em;
  text-transform: uppercase;
  padding: 2px 7px;
  border-radius: 3px;
  font-family: ui-monospace, monospace;
  border: 1px solid transparent;
}
.badge-red {
  background: var(--plate-red-bg);
  border-color: var(--plate-red-border);
  color: var(--plate-red-text);
}
.badge-yellow {
  background: var(--plate-yellow-bg);
  border-color: var(--plate-yellow-border);
  color: var(--plate-yellow-text);
}
.badge-blue {
  background: var(--plate-blue-bg);
  border-color: var(--plate-blue-border);
  color: var(--plate-blue-text);
}
.badge-green {
  background: var(--plate-green-bg);
  border-color: var(--plate-green-border);
  color: var(--plate-green-text);
}

/* Cards & Sections */
section { margin-bottom: 26px; }

.card {
  background: var(--surface);
  border: 1px solid var(--border);
  border-left: 5px solid var(--edge, var(--border));
  border-radius: 4px;
  padding: 14px 16px;
  margin-bottom: 10px;
}
.card.needs_you { --edge: var(--plate-red); }
.card.watch { --edge: var(--plate-yellow); }
.card.meet_prep { --edge: var(--plate-blue); }
.card.fine { --edge: var(--border); }

.who {
  font-weight: 600;
  font-size: 16px;
  display: flex;
  justify-content: space-between;
  align-items: center;
  gap: 10px;
  flex-wrap: wrap;
}
.who .id {
  font-weight: 400;
  font-size: 12px;
  color: var(--ink-faint);
  font-family: ui-monospace, monospace;
  background: var(--surface-inset);
  padding: 2px 6px;
  border-radius: 3px;
  white-space: nowrap;
}

ul {
  margin: 8px 0 0;
  padding-left: 18px;
  color: var(--ink-soft);
  font-size: 14px;
}
li { margin: 3px 0; }
li.act {
  color: var(--plate-red);
  font-weight: 600;
}

/* Forms & Interactive controls */
form {
  margin: 12px 0 0;
  display: flex;
  gap: 8px;
  flex-wrap: wrap;
  align-items: center;
}
input[type=text], input[type=password], textarea {
  flex: 1 1 200px;
  min-width: 0;
  padding: 8px 11px;
  font: inherit;
  font-size: 14px;
  border: 1px solid var(--border);
  border-radius: 3px;
  background: var(--bg);
  color: var(--ink);
  transition: border-color 0.15s ease;
}
textarea {
  width: 100%;
  min-height: 96px;
  line-height: 1.5;
  resize: vertical;
}
input:focus, textarea:focus {
  outline: none;
  border-color: var(--plate-blue);
  box-shadow: 0 0 0 2px var(--plate-blue-bg);
}
button {
  padding: 8px 15px;
  font: inherit;
  font-size: 13.5px;
  font-weight: 600;
  cursor: pointer;
  border-radius: 3px;
  border: 1px solid var(--plate-red);
  background: var(--plate-red);
  color: #ffffff;
  display: inline-flex;
  align-items: center;
  justify-content: center;
  gap: 6px;
  transition: opacity 0.15s ease;
}
button:hover { opacity: 0.92; }
button.btn-primary {
  background: var(--ink);
  color: var(--bg);
  border-color: var(--ink);
}
button.approve {
  background: var(--plate-green);
  border-color: var(--plate-green);
  color: #ffffff;
}
button.skip {
  background: transparent;
  color: var(--ink-soft);
  border-color: var(--border);
}
button.skip:hover {
  background: var(--surface-inset);
  color: var(--ink);
}

.fine-list {
  background: var(--surface);
  border: 1px solid var(--border);
  border-radius: 4px;
  padding: 12px 16px;
  color: var(--ink-soft);
  font-size: 14px;
}
.empty {
  color: var(--ink-faint);
  font-size: 14px;
  font-style: italic;
  margin: 6px 0;
}

/* Alerts and banners */
.msg {
  padding: 12px 16px;
  border-radius: 4px;
  margin-bottom: 20px;
  font-size: 14px;
  border: 1px solid var(--border);
  background: var(--surface);
}
.msg.ok {
  border-left: 4px solid var(--plate-green);
  background: var(--plate-green-bg);
  color: var(--plate-green-text);
  border-color: var(--plate-green-border);
}
.msg.err {
  border-left: 4px solid var(--plate-red);
  background: var(--plate-red-bg);
  color: var(--plate-red-text);
  border-color: var(--plate-red-border);
}

footer {
  margin-top: 36px;
  padding-top: 16px;
  border-top: 1px solid var(--border);
  font-size: 12.5px;
  color: var(--ink-faint);
  line-height: 1.6;
}
footer a {
  color: var(--ink-soft);
  text-decoration: none;
}
footer a:hover {
  color: var(--ink);
  text-decoration: underline;
}

/* WhatsApp Mockup Component */
.chat-container {
  background: #0b141a;
  border-radius: 8px;
  padding: 18px 14px;
  color: #e9edef;
  font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, Helvetica, Arial, sans-serif;
  box-shadow: 0 4px 16px rgba(0, 0, 0, 0.15);
  border: 1px solid var(--border);
  margin: 20px 0;
}
.chat-header {
  font-size: 12px;
  text-transform: uppercase;
  letter-spacing: 0.08em;
  color: #8696a0;
  margin-bottom: 12px;
  display: flex;
  justify-content: space-between;
  border-bottom: 1px solid #222d34;
  padding-bottom: 8px;
}
.chat-bubble {
  max-width: 88%;
  padding: 9px 12px;
  border-radius: 7.5px;
  margin-bottom: 10px;
  font-size: 14px;
  line-height: 1.45;
  position: relative;
  word-break: break-word;
}
.chat-athlete {
  background: #005c4b;
  color: #e9edef;
  margin-left: auto;
  border-top-right-radius: 0;
}
.chat-agent {
  background: #202c33;
  color: #d1d7db;
  margin-right: auto;
  border-top-left-radius: 0;
}
.chat-meta {
  display: block;
  font-size: 11px;
  color: #8696a0;
  margin-top: 4px;
  text-align: right;
  font-family: ui-monospace, monospace;
}
.chat-agent .chat-verdict {
  color: #f59e0b;
  font-weight: 700;
  display: block;
  margin: 4px 0 2px;
}

/* Table styles */
.table-wrap {
  overflow-x: auto;
  margin: 18px 0;
  border: 1px solid var(--border);
  border-radius: 4px;
}
table {
  width: 100%;
  border-collapse: collapse;
  font-size: 13.5px;
  text-align: left;
  background: var(--surface);
}
th {
  background: var(--surface-inset);
  color: var(--ink);
  font-weight: 600;
  padding: 10px 14px;
  border-bottom: 1px solid var(--border);
  font-size: 12px;
  letter-spacing: 0.04em;
  text-transform: uppercase;
}
td {
  padding: 10px 14px;
  border-bottom: 1px solid var(--border);
  color: var(--ink-soft);
}
tr:last-child td { border-bottom: none; }
td strong { color: var(--ink); }

/* Landing specifics */
.hero {
  margin: 24px 0 32px;
}
.hero h1 {
  font-size: 30px;
  line-height: 1.25;
  letter-spacing: -0.02em;
  margin-bottom: 12px;
  font-weight: 800;
}
.hero p.lead {
  font-size: 17px;
  color: var(--ink-soft);
  margin: 0 0 20px;
  line-height: 1.55;
}
.cta-row {
  display: flex;
  gap: 12px;
  flex-wrap: wrap;
  align-items: center;
  margin-bottom: 24px;
}
.btn-cta {
  padding: 10px 20px;
  font-size: 15px;
  font-weight: 700;
  background: var(--ink);
  color: var(--bg);
  border: 1px solid var(--ink);
  border-radius: 4px;
  text-decoration: none;
  display: inline-flex;
  align-items: center;
  gap: 8px;
}
.btn-cta:hover {
  opacity: 0.9;
}
.btn-secondary {
  padding: 10px 18px;
  font-size: 15px;
  font-weight: 600;
  color: var(--ink);
  background: var(--surface);
  border: 1px solid var(--border);
  border-radius: 4px;
  text-decoration: none;
}
.btn-secondary:hover {
  background: var(--surface-inset);
}
.grid-3 {
  display: grid;
  grid-template-columns: repeat(auto-fit, minmax(230px, 1fr));
  gap: 14px;
  margin: 20px 0;
}
.feature-card {
  background: var(--surface);
  border: 1px solid var(--border);
  border-radius: 4px;
  padding: 18px 16px;
}
.feature-card h3 {
  margin: 0 0 6px;
  font-size: 15px;
  font-weight: 700;
  display: flex;
  align-items: center;
  gap: 8px;
}
.feature-card p {
  margin: 0;
  font-size: 13.5px;
  color: var(--ink-soft);
  line-height: 1.5;
}
.note-box {
  background: var(--surface-inset);
  border-left: 3px solid var(--ink);
  padding: 12px 16px;
  font-size: 13.5px;
  color: var(--ink-soft);
  border-radius: 0 4px 4px 0;
  margin: 20px 0;
}

/* Login card */
.login-box {
  max-width: 420px;
  margin: 40px auto;
  background: var(--surface);
  border: 1px solid var(--border);
  border-radius: 6px;
  padding: 28px 24px;
  box-shadow: 0 4px 12px rgba(0, 0, 0, 0.05);
}
.login-box h1 {
  font-size: 21px;
  margin-bottom: 6px;
}
.login-box p {
  color: var(--ink-soft);
  font-size: 14px;
  margin: 0 0 20px;
}
.login-box form {
  display: flex;
  flex-direction: column;
  gap: 14px;
}
.login-box input[type=password], .login-box input[type=text] {
  width: 100%;
}
.login-box button {
  width: 100%;
  padding: 10px;
  font-size: 14.5px;
}
.back-link {
  display: inline-block;
  margin-top: 18px;
  font-size: 13.5px;
  color: var(--plate-blue);
  text-decoration: none;
}
.back-link:hover { text-decoration: underline; }
"""


# ------------------------------------------------------------------------------
# Roster View & Outbox Card Helpers
# ------------------------------------------------------------------------------
def _card(entry) -> str:
    """Render an individual athlete card."""
    items = "".join(
        f'<li class="{"act" if f.action else ""}">{escape(f.detail)}</li>'
        for f in entry.flags
    )
    body = f"<ul>{items}</ul>" if items else ""
    form = ""
    if entry.needs_action and entry.injury_days_open is not None:
        form = (
            '<form method="post" action="/coach/clear-injury">'
            f'<input type="hidden" name="athlete_id" value="{escape(entry.athlete_id)}">'
            '<input type="text" name="reason" required maxlength="200" '
            'placeholder="Who cleared them, and on what basis">'
            '<button type="submit">Clear injury</button>'
            '</form>'
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


_REGISTER_FORM = (
    '<section class="register"><h2>Add an athlete</h2>'
    '<div class="card">'
    '<form method="post" action="/coach/athletes/register">'
    '<input type="text" name="name" required maxlength="60" placeholder="Name">'
    '<input type="text" name="athlete_id" required maxlength="20" '
    'placeholder="WhatsApp number, e.g. +919812340001">'
    '<button type="submit">Add</button>'
    '</form>'
    '<p class="hint">The number is their identity - it is how the agent knows who '
    'is texting. They appear on the roster straight away and fill in as they log.</p>'
    '</div></section>'
)


def _demo_controls(roster: Roster, has_demo: bool) -> str:
    """Offer the demo squad on an empty console, and a way to remove it after."""
    if roster.total == 0:
        return (
            '<div class="demo">'
            "<p>Nothing has been logged yet. On a live team this fills up as "
            "athletes text their sessions.</p>"
            '<form method="post" action="/coach/demo/seed">'
            '<button type="submit">Load a demo squad</button></form>'
            "</div>"
        )
    if has_demo:
        return (
            '<div class="demo">'
            "<p>This roster includes demo athletes.</p>"
            '<form method="post" action="/coach/demo/clear">'
            '<button class="skip" type="submit">Remove demo athletes</button></form>'
            "</div>"
        )
    return ""


def render(
    roster: Roster,
    *,
    token: str,
    coach: str,
    message: tuple[str, str] | None = None,
    has_demo: bool = False,
) -> str:
    """Render the full coach roster console."""
    banner = ""
    if message:
        kind, text = message
        banner = f'<div class="msg {escape(kind)}">{escape(text)}</div>'

    sections = []
    for bucket in BUCKET_ORDER:
        entries = roster.bucket(bucket)
        if not entries:
            if bucket is Bucket.NEEDS_YOU:
                sections.append(
                    f"<section><h2>{BUCKET_LABEL[bucket]} <span class='n'>0</span></h2>"
                    '<p class="empty">Nothing is waiting on you.</p></section>'
                )
            continue
        if bucket is Bucket.FINE:
            names = ", ".join(escape(e.display_name) for e in entries)
            sections.append(
                f"<section><h2>{BUCKET_LABEL[bucket]} <span class='n'>{len(entries)}</span></h2>"
                f'<div class="fine-list">{names}</div></section>'
            )
            continue
        cards = "".join(_card(e) for e in entries)
        sections.append(
            f"<section><h2>{BUCKET_LABEL[bucket]} <span class='n'>{len(entries)}</span></h2>"
            f"{cards}</section>"
        )

    attention = roster.needing_attention
    summary = (
        f"<b>{attention}</b> of <b>{roster.total}</b> athletes need a look today."
        if attention
        else f"All <b>{roster.total}</b> athletes are on track."
    )

    token_param = f"?token={escape(token)}" if token else ""

    return (
        "<!doctype html><html lang='en'><head><meta charset='utf-8'>"
        "<meta name='viewport' content='width=device-width,initial-scale=1'>"
        "<title>Coach Console — Roster</title>"
        f"<style>{_BASE_CSS}</style></head><body><div class='wrap'>"
        "<header><div class='header-top'>"
        f"<div class='brand'><span class='brand-badge'>COACH</span> {escape(coach)}</div>"
        f"<nav class='header-nav'>"
        f"<a class='active' href='/coach{token_param}'>Roster</a>"
        f"<a href='/coach/outbox{token_param}'>Outbox</a>"
        f"<a class='danger' href='/coach/logout'>Sign Out</a>"
        f"</nav></div>"
        f"<div style='margin-top:8px;'><span class='when'>{roster.reviewed_on.isoformat()}</span></div>"
        "</header>"
        f"<p class='summary'>{summary}</p>"
        f"{banner}{_demo_controls(roster, has_demo)}{''.join(sections)}{_REGISTER_FORM}"
        "<footer>Every line here is computed by the same rules that answer the "
        "athlete. This page decides nothing on its own.</footer>"
        "</div></body></html>"
    )


def _outbox_card(item: PendingMessage) -> str:
    a = item.athlete
    reasons = " · ".join(escape(f.detail) for f in a.flags) or "nothing flagged"
    return (
        f'<div class="card {a.bucket.value}">'
        f'<div class="who"><span>{escape(a.display_name)}</span>'
        f'<span class="id">{escape(item.athlete_id)}</span></div>'
        f'<p style="margin:6px 0 10px;font-size:13.5px;color:var(--ink-soft);">'
        f'<b>Where they are:</b> {reasons}</p>'
        '<form method="post" action="/coach/outbox/review">'
        f'<input type="hidden" name="athlete_id" value="{escape(item.athlete_id)}">'
        f'<input type="hidden" name="message_kind" value="{escape(item.message_kind)}">'
        f'<input type="hidden" name="local_date" value="{escape(item.local_date)}">'
        f'<textarea name="body" maxlength="1400">{escape(item.body)}</textarea>'
        '<div style="display:flex;gap:8px;margin-top:10px;flex-wrap:wrap;">'
        '<button class="approve" type="submit" name="decision" value="approved">'
        f'Approve for {escape(item.local_date)}</button>'
        '<button class="skip" type="submit" name="decision" value="skipped">'
        "Don\u2019t send</button></div></form></div>"
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

    token_param = f"?token={escape(token)}" if token else ""

    return (
        "<!doctype html><html lang='en'><head><meta charset='utf-8'>"
        "<meta name='viewport' content='width=device-width,initial-scale=1'>"
        "<title>Coach Console — Outbox</title>"
        f"<style>{_BASE_CSS}</style></head><body><div class='wrap'>"
        "<header><div class='header-top'>"
        f"<div class='brand'><span class='brand-badge'>COACH</span> {escape(coach)}</div>"
        f"<nav class='header-nav'>"
        f"<a href='/coach{token_param}'>&larr; Roster</a>"
        f"<a class='active' href='/coach/outbox{token_param}'>Outbox</a>"
        f"<a class='danger' href='/coach/logout'>Sign Out</a>"
        f"</nav></div>"
        f"<div style='margin-top:8px;'><span class='when'>{today.isoformat()}</span></div>"
        "</header>"
        f"{banner}{body}"
        "<footer>Nothing here has been sent. Unreviewed messages are not sent at "
        "all — silence, never an unsupervised broadcast.</footer>"
        "</div></body></html>"
    )


# ------------------------------------------------------------------------------
# Login Page
# ------------------------------------------------------------------------------
def render_login(error: str | None = None, message: str | None = None) -> str:
    """Render the coach sign-in page."""
    error_markup = f'<div class="msg err">{escape(error)}</div>' if error else ""
    msg_markup = f'<div class="msg ok">{escape(message)}</div>' if message else ""

    return f"""<!doctype html>
<html lang="en">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>Coach Access — Training Log Agent</title>
  <style>{_BASE_CSS}</style>
</head>
<body>
  <div class="wrap">
    <div class="login-box">
      <div class="brand" style="margin-bottom:12px;">
        <span class="brand-badge">AUTH</span> Power Coach Console
      </div>
      <h1>Coach Sign In</h1>
      <p>Enter the coach access token configured for this team. Signing in sets an HTTP-only secure cookie so credentials don't leak into URLs or screenshots.</p>
      {error_markup}
      {msg_markup}
      <form method="post" action="/coach/login">
        <label style="font-size:13px;font-weight:600;color:var(--ink-soft);" for="token">ACCESS TOKEN</label>
        <input type="password" id="token" name="token" required autofocus autocomplete="current-password" placeholder="Paste token here">
        <button type="submit" class="btn-primary">Authenticate</button>
      </form>
      <div style="margin-top:20px;text-align:center;">
        <a class="back-link" href="/">&larr; Back to Overview</a>
      </div>
    </div>
  </div>
</body>
</html>"""


# ------------------------------------------------------------------------------
# Landing Page (GET /) & Public Legal Views — Unseen Studio Redesign
# ------------------------------------------------------------------------------

_UNSEEN_LANDING_CSS = """
@import url('https://fonts.googleapis.com/css2?family=Plus+Jakarta+Sans:ital,wght@0,300;0,400;0,500;0,600;0,700;0,800;1,400&family=Newsreader:ital,opsz,wght@1,6..72,300;1,6..72,400;1,6..72,500&family=JetBrains+Mono:wght@400;500;600&display=swap');

:root {
  --bg: #09090b;
  --bg-surface: #101014;
  --bg-card: #131318;
  --bg-card-hover: #181820;
  --border: rgba(255, 255, 255, 0.08);
  --border-strong: rgba(255, 255, 255, 0.16);
  --border-subtle: rgba(255, 255, 255, 0.04);
  --ink: #ffffff;
  --ink-secondary: #e4e4e7;
  --ink-soft: #a1a1aa;
  --ink-faint: #71717a;
  
  --unseen-blush: #f6c8c3;
  --unseen-sand: #efded9;
  
  --plate-red: #ef4444;
  --plate-red-bg: rgba(239, 68, 68, 0.12);
  --plate-yellow: #f59e0b;
  --plate-yellow-bg: rgba(245, 158, 11, 0.12);
  --plate-blue: #3b82f6;
  --plate-blue-bg: rgba(59, 130, 246, 0.12);
  --plate-green: #10b981;
  --plate-green-bg: rgba(16, 185, 129, 0.12);

  --font-sans: 'Plus Jakarta Sans', -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, Helvetica, Arial, sans-serif;
  --font-serif: 'Newsreader', 'Saol Display', 'Playfair Display', Georgia, serif;
  --font-mono: 'JetBrains Mono', ui-monospace, SFMono-Regular, Menlo, Monaco, Consolas, monospace;
}

*, *::before, *::after {
  box-sizing: border-box;
}

html {
  background: var(--bg);
  color: var(--ink);
  scroll-behavior: smooth;
  font-size: 16px;
  -webkit-text-size-adjust: 100%;
}

body {
  margin: 0;
  background: var(--bg);
  color: var(--ink);
  font-family: var(--font-sans);
  line-height: 1.6;
  -webkit-font-smoothing: antialiased;
  -moz-osx-font-smoothing: grayscale;
  overflow-x: hidden;
}

.unseen-ambient {
  position: fixed;
  top: 0;
  left: 50%;
  transform: translateX(-50%);
  width: 100vw;
  height: 650px;
  background: radial-gradient(circle at 50% 10%, rgba(246, 200, 195, 0.04) 0%, rgba(59, 130, 246, 0.02) 40%, transparent 70%);
  pointer-events: none;
  z-index: 0;
}

.unseen-wrapper {
  position: relative;
  z-index: 1;
  max-width: 1200px;
  margin: 0 auto;
  padding: 0 28px 80px;
}

/* Header & Nav */
.unseen-header {
  position: sticky;
  top: 0;
  z-index: 100;
  background: rgba(9, 9, 11, 0.82);
  backdrop-filter: blur(20px);
  -webkit-backdrop-filter: blur(20px);
  border-bottom: 1px solid var(--border);
  padding: 18px 0;
  margin-bottom: 48px;
}

.unseen-header-inner {
  max-width: 1200px;
  margin: 0 auto;
  padding: 0 28px;
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 20px;
}

.unseen-brand {
  display: flex;
  align-items: center;
  gap: 12px;
  text-decoration: none;
  color: var(--ink);
  font-weight: 700;
  font-size: 15px;
  letter-spacing: 0.06em;
  text-transform: uppercase;
}

.unseen-brand .reg {
  font-size: 11px;
  opacity: 0.6;
  vertical-align: super;
}

.unseen-status-badge {
  display: inline-flex;
  align-items: center;
  gap: 8px;
  padding: 4px 12px;
  border-radius: 9999px;
  background: rgba(255, 255, 255, 0.04);
  border: 1px solid var(--border);
  font-family: var(--font-mono);
  font-size: 11px;
  color: var(--ink-soft);
  letter-spacing: 0.05em;
}

.pulse-dot {
  width: 7px;
  height: 7px;
  border-radius: 50%;
  background: var(--plate-green);
  box-shadow: 0 0 8px var(--plate-green);
  animation: pulse 2s infinite;
}

@keyframes pulse {
  0% { transform: scale(0.95); opacity: 0.8; }
  50% { transform: scale(1.15); opacity: 1; }
  100% { transform: scale(0.95); opacity: 0.8; }
}

.unseen-nav {
  display: flex;
  align-items: center;
  gap: 20px;
}

.unseen-nav a.nav-link {
  color: var(--ink-soft);
  text-decoration: none;
  font-size: 13.5px;
  font-weight: 500;
  letter-spacing: 0.02em;
  transition: color 0.2s ease;
}

.unseen-nav a.nav-link:hover {
  color: var(--ink);
}

/* Pill Buttons */
.unseen-btn {
  display: inline-flex;
  align-items: center;
  justify-content: center;
  gap: 8px;
  padding: 10px 22px;
  border-radius: 9999px;
  text-decoration: none;
  font-size: 13.5px;
  font-weight: 600;
  letter-spacing: 0.02em;
  transition: all 0.25s cubic-bezier(0.16, 1, 0.3, 1);
  cursor: pointer;
  border: 1px solid transparent;
}

.unseen-btn-primary {
  background: #ffffff;
  color: #09090b;
}

.unseen-btn-primary:hover {
  background: #f4f4f5;
  transform: translateY(-1px);
  box-shadow: 0 8px 24px rgba(255, 255, 255, 0.15);
}

.unseen-btn-ghost {
  background: transparent;
  color: #ffffff;
  border: 1px solid var(--border-strong);
}

.unseen-btn-ghost:hover {
  border-color: rgba(255, 255, 255, 0.4);
  background: rgba(255, 255, 255, 0.05);
  transform: translateY(-1px);
}

.unseen-btn-lg {
  padding: 16px 36px;
  font-size: 15px;
}

.unseen-btn .arrow {
  transition: transform 0.25s ease;
}

.unseen-btn:hover .arrow {
  transform: translate(2px, -2px);
}

/* Hero Section */
.unseen-hero {
  padding: 40px 0 60px;
}

.unseen-hero-tag {
  font-family: var(--font-mono);
  font-size: 11px;
  text-transform: uppercase;
  letter-spacing: 0.16em;
  color: var(--unseen-blush);
  margin-bottom: 24px;
}

.unseen-hero-h1 {
  font-size: clamp(2.6rem, 6.2vw, 4.8rem);
  line-height: 1.04;
  letter-spacing: -0.035em;
  font-weight: 700;
  color: var(--ink);
  margin: 0 0 28px 0;
  max-width: 1040px;
}

.unseen-serif {
  font-family: var(--font-serif);
  font-style: italic;
  font-weight: 300;
  color: var(--unseen-blush);
  letter-spacing: -0.01em;
}

.unseen-hero-lead {
  font-size: clamp(1.1rem, 2vw, 1.35rem);
  line-height: 1.55;
  color: var(--ink-soft);
  max-width: 820px;
  margin: 0 0 36px 0;
}

.unseen-cta-row {
  display: flex;
  align-items: center;
  flex-wrap: wrap;
  gap: 16px;
  margin-bottom: 56px;
}

/* Metadata / Specs Strip */
.unseen-specs-strip {
  display: grid;
  grid-template-columns: repeat(4, 1fr);
  gap: 24px;
  border-top: 1px solid var(--border);
  border-bottom: 1px solid var(--border);
  padding: 28px 0;
  margin: 40px 0 64px;
}

.spec-col {
  display: flex;
  flex-direction: column;
  gap: 4px;
}

.spec-num {
  font-family: var(--font-mono);
  font-size: 11px;
  color: var(--ink-faint);
  letter-spacing: 0.08em;
}

.spec-name {
  font-family: var(--font-mono);
  font-size: 11px;
  text-transform: uppercase;
  letter-spacing: 0.12em;
  color: var(--ink-soft);
}

.spec-detail {
  font-size: 14.5px;
  font-weight: 600;
  color: var(--ink);
}

/* Sections */
.unseen-section {
  margin-bottom: 80px;
}

.section-meta {
  display: flex;
  align-items: center;
  gap: 12px;
  margin-bottom: 12px;
}

.section-idx {
  font-family: var(--font-mono);
  font-size: 12px;
  color: var(--unseen-blush);
  font-weight: 600;
}

.section-label {
  font-family: var(--font-mono);
  font-size: 11px;
  text-transform: uppercase;
  letter-spacing: 0.16em;
  color: var(--ink-faint);
}

.section-title {
  font-size: clamp(1.8rem, 4vw, 2.6rem);
  line-height: 1.15;
  letter-spacing: -0.025em;
  font-weight: 700;
  color: var(--ink);
  margin: 0 0 24px 0;
}

.section-lead {
  font-size: 16px;
  color: var(--ink-soft);
  max-width: 780px;
  margin: 0 0 32px 0;
}

/* Filter Bar */
.unseen-filters {
  display: flex;
  align-items: center;
  gap: 8px;
  flex-wrap: wrap;
  margin-bottom: 36px;
}

.filter-pill {
  background: var(--bg-surface);
  border: 1px solid var(--border);
  color: var(--ink-soft);
  padding: 8px 18px;
  border-radius: 9999px;
  font-family: var(--font-mono);
  font-size: 12px;
  letter-spacing: 0.04em;
  cursor: pointer;
  transition: all 0.2s ease;
}

.filter-pill:hover {
  color: var(--ink);
  border-color: var(--border-strong);
}

.filter-pill.active {
  background: #ffffff;
  color: #09090b;
  border-color: #ffffff;
  font-weight: 600;
}

/* Project / Case Card */
.case-item {
  background: var(--bg-card);
  border: 1px solid var(--border);
  border-radius: 20px;
  padding: 44px;
  margin-bottom: 40px;
  transition: border-color 0.25s ease, background-color 0.25s ease;
}

.case-item:hover {
  border-color: var(--border-strong);
}

.case-header {
  display: flex;
  justify-content: space-between;
  align-items: flex-start;
  flex-wrap: wrap;
  gap: 16px;
  margin-bottom: 24px;
  border-bottom: 1px solid var(--border);
  padding-bottom: 20px;
}

.case-tag {
  font-family: var(--font-mono);
  font-size: 11px;
  letter-spacing: 0.12em;
  text-transform: uppercase;
  color: var(--unseen-blush);
}

.case-badge-group {
  display: flex;
  gap: 8px;
}

.tag-badge {
  font-family: var(--font-mono);
  font-size: 11px;
  letter-spacing: 0.05em;
  padding: 3px 8px;
  border-radius: 4px;
  background: rgba(255, 255, 255, 0.04);
  border: 1px solid var(--border);
  color: var(--ink-soft);
}

.case-title {
  font-size: 26px;
  font-weight: 700;
  letter-spacing: -0.02em;
  color: var(--ink);
  margin: 0 0 12px 0;
}

.case-desc {
  font-size: 15px;
  color: var(--ink-soft);
  max-width: 820px;
  margin: 0 0 28px 0;
}

/* WhatsApp Interactive Simulator */
.scenario-selector {
  display: flex;
  gap: 10px;
  flex-wrap: wrap;
  margin-bottom: 20px;
}

.scenario-btn {
  background: rgba(255, 255, 255, 0.03);
  border: 1px solid var(--border);
  color: var(--ink-soft);
  padding: 7px 14px;
  border-radius: 8px;
  font-size: 13px;
  cursor: pointer;
  transition: all 0.2s ease;
}

.scenario-btn:hover {
  color: var(--ink);
  border-color: var(--border-strong);
}

.scenario-btn.active {
  background: rgba(246, 200, 195, 0.1);
  border-color: var(--unseen-blush);
  color: #ffffff;
}

.chat-container {
  background: #0d1117;
  border: 1px solid var(--border);
  border-radius: 16px;
  padding: 24px;
  max-width: 660px;
}

.chat-header {
  display: flex;
  justify-content: space-between;
  font-size: 11px;
  font-family: var(--font-mono);
  letter-spacing: 0.08em;
  text-transform: uppercase;
  color: var(--ink-faint);
  border-bottom: 1px solid rgba(255, 255, 255, 0.06);
  padding-bottom: 12px;
  margin-bottom: 20px;
}

.chat-bubble {
  max-width: 82%;
  padding: 12px 16px;
  border-radius: 12px;
  font-size: 14px;
  line-height: 1.5;
  margin-bottom: 14px;
  position: relative;
}

.chat-athlete {
  background: #1e2633;
  color: #e6edf3;
  margin-left: auto;
  border-bottom-right-radius: 4px;
}

.chat-agent {
  background: #161b22;
  color: #c9d1d9;
  border: 1px solid rgba(255, 255, 255, 0.08);
  margin-right: auto;
  border-bottom-left-radius: 4px;
}

.chat-meta {
  display: block;
  font-size: 11px;
  color: #8b949e;
  text-align: right;
  margin-top: 4px;
  font-family: var(--font-mono);
}

.chat-verdict {
  display: inline-block;
  font-weight: 700;
  font-size: 12px;
  padding: 2px 8px;
  border-radius: 4px;
  background: var(--plate-yellow-bg);
  color: var(--plate-yellow);
  border: 1px solid var(--plate-yellow);
  margin: 6px 0;
}

/* 3-Layer Architecture Grid */
.grid-3 {
  display: grid;
  grid-template-columns: repeat(3, 1fr);
  gap: 20px;
  margin-top: 24px;
}

.feature-card {
  background: rgba(255, 255, 255, 0.02);
  border: 1px solid var(--border);
  border-radius: 14px;
  padding: 28px 24px;
  position: relative;
  transition: all 0.25s ease;
}

.feature-card:hover {
  background: rgba(255, 255, 255, 0.04);
  border-color: var(--border-strong);
  transform: translateY(-2px);
}

.feature-card h3 {
  font-size: 18px;
  font-weight: 700;
  letter-spacing: -0.01em;
  color: var(--ink);
  margin: 12px 0 8px 0;
}

.feature-card p {
  font-size: 13.5px;
  line-height: 1.6;
  color: var(--ink-soft);
  margin: 0;
}

.badge {
  font-family: var(--font-mono);
  font-size: 10.5px;
  font-weight: 600;
  letter-spacing: 0.1em;
  text-transform: uppercase;
  padding: 3px 8px;
  border-radius: 4px;
  display: inline-block;
}

.badge-blue {
  background: var(--plate-blue-bg);
  color: var(--plate-blue);
  border: 1px solid rgba(59, 130, 246, 0.3);
}

.badge-yellow {
  background: var(--plate-yellow-bg);
  color: var(--plate-yellow);
  border: 1px solid rgba(245, 158, 11, 0.3);
}

.badge-red {
  background: var(--plate-red-bg);
  color: var(--plate-red);
  border: 1px solid rgba(239, 68, 68, 0.3);
}

/* Authority Table */
.table-wrap {
  overflow-x: auto;
  border: 1px solid var(--border);
  border-radius: 14px;
  margin-top: 24px;
}

table {
  width: 100%;
  border-collapse: collapse;
  text-align: left;
  font-size: 14px;
}

th {
  background: rgba(255, 255, 255, 0.03);
  padding: 14px 18px;
  font-family: var(--font-mono);
  font-size: 11px;
  letter-spacing: 0.1em;
  text-transform: uppercase;
  color: var(--ink-soft);
  border-bottom: 1px solid var(--border);
}

td {
  padding: 14px 18px;
  border-bottom: 1px solid var(--border-subtle);
  color: var(--ink-secondary);
}

tr:last-child td {
  border-bottom: none;
}

tr:hover td {
  background: rgba(255, 255, 255, 0.015);
}

/* Meet Data Metrics */
.stats-grid {
  display: grid;
  grid-template-columns: repeat(4, 1fr);
  gap: 16px;
  margin-top: 24px;
}

.stat-tile {
  background: rgba(255, 255, 255, 0.02);
  border: 1px solid var(--border);
  border-radius: 12px;
  padding: 20px;
}

.stat-val {
  font-size: 28px;
  font-weight: 700;
  letter-spacing: -0.03em;
  color: var(--ink);
  display: block;
}

.stat-lbl {
  font-family: var(--font-mono);
  font-size: 11px;
  text-transform: uppercase;
  letter-spacing: 0.08em;
  color: var(--ink-faint);
  margin-top: 4px;
  display: block;
}

/* Manifesto Callout */
.unseen-manifesto {
  background: rgba(255, 255, 255, 0.02);
  border: 1px solid var(--border);
  border-left: 3px solid var(--unseen-blush);
  border-radius: 12px;
  padding: 24px 28px;
  margin: 56px 0;
}

.manifesto-tag {
  font-family: var(--font-mono);
  font-size: 11px;
  letter-spacing: 0.14em;
  text-transform: uppercase;
  color: var(--unseen-blush);
  margin-bottom: 8px;
}

.manifesto-text {
  font-size: 14.5px;
  color: var(--ink-secondary);
  line-height: 1.6;
  margin: 0;
}

/* Oversized Unseen Footer */
.unseen-footer {
  border-top: 1px solid var(--border);
  padding-top: 80px;
  margin-top: 100px;
}

.unseen-footer-hero {
  margin-bottom: 64px;
}

.footer-kicker {
  font-family: var(--font-mono);
  font-size: 11px;
  letter-spacing: 0.16em;
  text-transform: uppercase;
  color: var(--unseen-blush);
  margin-bottom: 16px;
}

.footer-headline {
  font-size: clamp(2.4rem, 5.5vw, 4.2rem);
  line-height: 1.05;
  letter-spacing: -0.03em;
  font-weight: 700;
  color: var(--ink);
  margin: 0 0 32px 0;
}

.unseen-footer-bottom {
  display: flex;
  justify-content: space-between;
  align-items: center;
  flex-wrap: wrap;
  gap: 20px;
  padding-top: 32px;
  border-top: 1px solid var(--border);
  font-size: 13px;
  color: var(--ink-faint);
}

.unseen-footer-bottom a {
  color: var(--ink-soft);
  text-decoration: none;
  transition: color 0.2s ease;
}

.unseen-footer-bottom a:hover {
  color: var(--ink);
}

.footer-clock {
  font-family: var(--font-mono);
  font-size: 12px;
  color: var(--ink-faint);
}

.back-to-top {
  display: inline-flex;
  align-items: center;
  gap: 6px;
  font-family: var(--font-mono);
  font-size: 12px;
  text-transform: uppercase;
  letter-spacing: 0.08em;
  color: var(--ink-soft);
  text-decoration: none;
}

.back-to-top:hover {
  color: var(--ink);
}

/* Legal view container */
.unseen-legal-container {
  max-width: 780px;
  margin: 40px auto 80px;
  background: var(--bg-card);
  border: 1px solid var(--border);
  border-radius: 16px;
  padding: 48px;
}

.unseen-legal-container h1 {
  font-size: 32px;
  letter-spacing: -0.02em;
  margin: 0 0 24px 0;
}

.unseen-legal-container p {
  font-size: 15px;
  line-height: 1.7;
  color: var(--ink-secondary);
  margin-bottom: 20px;
}

/* Responsive adjustments */
@media (max-width: 900px) {
  .unseen-specs-strip {
    grid-template-columns: repeat(2, 1fr);
  }
  .grid-3 {
    grid-template-columns: 1fr;
  }
  .stats-grid {
    grid-template-columns: repeat(2, 1fr);
  }
}

@media (max-width: 640px) {
  .unseen-wrapper {
    padding: 0 18px 60px;
  }
  .unseen-header-inner {
    padding: 0 18px;
  }
  .unseen-nav {
    display: none;
  }
  .unseen-specs-strip {
    grid-template-columns: 1fr;
  }
  .stats-grid {
    grid-template-columns: 1fr;
  }
  .case-item {
    padding: 24px 18px;
  }
  .unseen-legal-container {
    padding: 28px 20px;
  }
}
"""

_LANDING_JS = """
  const scenarios = {
    stall: {
      athlete: 'squat 3x5 at 140 today, felt way harder than tuesday, rpe 9',
      time: '17:42',
      verdictText: 'Squat — Stalled',
      detail: 'Flat at 140 kg for 2 sessions with RPE climbing &mdash; same bar, more effort.'
    },
    injury: {
      athlete: 'bench 100kg 3x5 sharp pain in front left shoulder on rep 4',
      time: '18:15',
      verdictText: '🚨 Injury Flag: Left Shoulder',
      detail: 'Acute pain logged. Progression immediately locked until cleared by Coach.'
    },
    pr: {
      athlete: 'deadlift 220 1x5 moved like butter rpe 7',
      time: '19:04',
      verdictText: 'Deadlift — Progressing',
      detail: '+5kg progression verified. RPE in target band (7.0 &le; 8.0).'
    }
  };

  function switchScenario(key) {
    const data = scenarios[key];
    if (!data) return;

    document.querySelectorAll('.scenario-btn').forEach(btn => btn.classList.remove('active'));
    if (window.event && window.event.target) {
      window.event.target.classList.add('active');
    }

    const athleteBubble = document.getElementById('chat-athlete-msg');
    const agentBubble = document.getElementById('chat-agent-msg');

    athleteBubble.innerHTML = data.athlete + '<span class="chat-meta">' + data.time + ' &check;&check;</span>';
    agentBubble.innerHTML = '&check; Logged: ' + (key === 'stall' ? 'Squat 3x5 @ 140 kg RPE 9' : (key === 'injury' ? 'Bench 100 kg 3x5 RPE 8' : 'Deadlift 220 kg 1x5 RPE 7')) + '<br>' +
      '<span class="chat-verdict">' + data.verdictText + '</span><br>' +
      data.detail +
      '<span class="chat-meta">' + data.time + '</span>';
  }

  function filterCase(category) {
    document.querySelectorAll('.filter-pill').forEach(btn => btn.classList.remove('active'));
    if (window.event && window.event.target) {
      window.event.target.classList.add('active');
    }

    document.querySelectorAll('.case-item').forEach(item => {
      if (category === 'all' || item.getAttribute('data-case') === category) {
        item.style.display = 'block';
      } else {
        item.style.display = 'none';
      }
    });
  }

  function updateClock() {
    const el = document.getElementById('utc-clock');
    if (!el) return;
    const now = new Date();
    el.textContent = now.toUTCString().split(' ')[4] + ' UTC';
  }
  setInterval(updateClock, 1000);
  updateClock();
"""


def render_landing(*, is_logged_in: bool = False) -> str:
    """Render the public landing page styled like Unseen Studio (unseen.co/projects)."""
    coach_link = "/coach" if is_logged_in else "/coach/login"
    coach_text = "Open Console" if is_logged_in else "Coach Sign In"

    arrow_svg = '<svg class="arrow" width="14" height="14" viewBox="0 0 16 16"><path fill="none" stroke="currentColor" stroke-width="2" d="M3 13L13 3M13 3H5M13 3V11"/></svg>'

    return f"""<!doctype html>
<html lang="en">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>Training Log Agent — WhatsApp Powerlifting Coach</title>
  <style>{_UNSEEN_LANDING_CSS}</style>
</head>
<body>
  <div class="unseen-ambient"></div>

  <!-- Header Navigation (Unseen Studio style) -->
  <header class="unseen-header">
    <div class="unseen-header-inner">
      <a class="unseen-brand" href="/">
        Training Log Agent<span class="reg">&reg;</span>
      </a>
      <div class="unseen-status-badge">
        <span class="pulse-dot"></span>
        <span>AGENT ONLINE &middot; DETERMINISTIC</span>
      </div>
      <nav class="unseen-nav">
        <a class="nav-link" href="#protocols">01 Protocols</a>
        <a class="nav-link" href="#architecture">02 Architecture</a>
        <a class="nav-link" href="#boundaries">03 Boundaries</a>
        <a class="nav-link" href="https://github.com/Shlok-K-ps/training-log-agent" target="_blank" rel="noopener">GitHub &nearr;</a>
        <a class="unseen-btn unseen-btn-primary" href="{coach_link}">
          <span>{coach_text}</span>
          {arrow_svg}
        </a>
      </nav>
    </div>
  </header>

  <div class="unseen-wrapper">
    <!-- Hero Section -->
    <section class="unseen-hero">
      <div class="unseen-hero-tag">[ PROTOCOL 01 // WHATSAPP POWERLIFTING INTELLIGENCE ]</div>
      <h1 class="unseen-hero-h1">
        The coach reads exceptions,<br>
        <span class="unseen-serif">not twenty WhatsApp texts a day.</span>
      </h1>
      <p class="unseen-hero-lead">
        A powerlifting coach's real bottleneck isn't writing programs &mdash; it's copying workout numbers from messages, remembering who's hurt, spotting lifters who stalled a month ago, and noticing when an athlete goes silent.
      </p>
      <div class="unseen-cta-row">
        <a class="unseen-btn unseen-btn-primary unseen-btn-lg" href="{coach_link}">
          <span>{coach_text}</span>
          {arrow_svg}
        </a>
        <a class="unseen-btn unseen-btn-ghost unseen-btn-lg" href="https://github.com/Shlok-K-ps/training-log-agent" target="_blank" rel="noopener">
          <span>Read Source on GitHub</span>
          {arrow_svg}
        </a>
      </div>

      <!-- Studio Specs Strip -->
      <div class="unseen-specs-strip">
        <div class="spec-col">
          <span class="spec-num">01</span>
          <span class="spec-name">INGESTION</span>
          <span class="spec-detail">WhatsApp Cloud API</span>
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
    </section>

    <!-- Showcase Projects Section (Unseen Studio projects/ layout) -->
    <section id="protocols" class="unseen-section">
      <div class="section-meta">
        <span class="section-idx">01</span>
        <span class="section-label">SHOWCASE PROJECTS &amp; PROTOCOLS</span>
      </div>
      <h2 class="section-title">Curated Systems <span class="unseen-serif">&amp; Case Studies</span></h2>
      <p class="section-lead">
        Explore the four deterministic mechanisms that power the squad &mdash; from raw incoming athlete WhatsApp streams to zero-hallucination verdict rules.
      </p>

      <!-- Category Filter Tabs -->
      <div class="unseen-filters" role="tablist">
        <button class="filter-pill active" onclick="filterCase('all')">All Protocols (04)</button>
        <button class="filter-pill" onclick="filterCase('chat')">01 WhatsApp Simulation</button>
        <button class="filter-pill" onclick="filterCase('arch')">02 Three-Layer Split</button>
        <button class="filter-pill" onclick="filterCase('bound')">03 Authority Boundaries</button>
        <button class="filter-pill" onclick="filterCase('data')">04 Meet Benchmarks</button>
      </div>

      <!-- Case 01: Interactive WhatsApp Conversation -->
      <article class="case-item" data-case="chat">
        <div class="case-header">
          <div>
            <div class="case-tag">[ PROJECT 01 // REALISTIC WHATSAPP CONVERSATION ]</div>
            <h3 class="case-title">Raw Lifter Notes &rarr; Structured Verdicts</h3>
          </div>
          <div class="case-badge-group">
            <span class="tag-badge">PARSING</span>
            <span class="tag-badge">DETERMINISTIC</span>
          </div>
        </div>
        <p class="case-desc">
          Lifters text raw shorthand notes straight from the squat rack. Gemini Flash extracts the workout into typed function schemas, but <em>never drafts advice</em>. Pure Python evaluates the sets and assigns an immediate deterministic verdict.
        </p>

        <!-- Interactive Scenario Switcher -->
        <div class="scenario-selector">
          <button class="scenario-btn active" onclick="switchScenario('stall')">Scenario A: Stalled Squat (140kg)</button>
          <button class="scenario-btn" onclick="switchScenario('injury')">Scenario B: Acute Shoulder Pain</button>
          <button class="scenario-btn" onclick="switchScenario('pr')">Scenario C: Bench Press PR</button>
        </div>

        <div class="chat-container">
          <div class="chat-header">
            <span>WhatsApp Conversation</span>
            <span>Deterministic Reply</span>
          </div>
          <div id="chat-athlete-msg" class="chat-bubble chat-athlete">
            squat 3x5 at 140 today, felt way harder than tuesday, rpe 9
            <span class="chat-meta">17:42 &check;&check;</span>
          </div>
          <div id="chat-agent-msg" class="chat-bubble chat-agent">
            &check; Logged: Squat 3x5 @ 140 kg RPE 9<br>
            <span class="chat-verdict">Squat — Stalled</span><br>
            Flat at 140 kg for 2 sessions with RPE climbing &mdash; same bar, more effort.
            <span class="chat-meta">17:42</span>
          </div>
        </div>
      </article>

      <!-- Case 02: 3-Layer Architecture -->
      <article id="architecture" class="case-item" data-case="arch">
        <div class="case-header">
          <div>
            <div class="case-tag">[ PROJECT 02 // ARCHITECTURAL PROTOCOL ]</div>
            <h3 class="case-title">The Core Separation <span class="n">3 LAYERS</span></h3>
          </div>
          <div class="case-badge-group">
            <span class="tag-badge">ZERO DRIFT</span>
            <span class="tag-badge">PYTHON 3.11</span>
          </div>
        </div>
        <p class="case-desc">
          Messy input needs a language model; coaching advice real humans lift under must be provable, repeatable, and deterministic. The split is the whole design:
        </p>
        <div class="grid-3">
          <div class="feature-card">
            <span class="badge badge-blue">LAYER 1 &middot; PARSE</span>
            <h3>Gemini Flash</h3>
            <p>Extracts unstructured English into 20 typed function schemas. Ceilings and ratios are range-checked. <em>The model cannot write reply text.</em></p>
          </div>
          <div class="feature-card">
            <span class="badge badge-yellow">LAYER 2 &middot; STORE</span>
            <h3>Single SQLite Timeline</h3>
            <p>Every message is an immutable observation. Phone numbers serve as tenant identity. Calendar tokens and locations are encrypted at rest.</p>
          </div>
          <div class="feature-card">
            <span class="badge badge-red">LAYER 3 &middot; DECIDE</span>
            <h3>Pure Python Rules</h3>
            <p>Zero model. Zero API calls. Zero randomness. Evaluates session deltas, RPE slides, deloads, and sleep recovery deterministically.</p>
          </div>
        </div>
      </article>

      <!-- Case 03: Authority Boundaries -->
      <article id="boundaries" class="case-item" data-case="bound">
        <div class="case-header">
          <div>
            <div class="case-tag">[ PROJECT 03 // SAFETY GOVERNANCE ]</div>
            <h3 class="case-title">Authority Boundaries <span class="n">WHO DECIDES WHAT</span></h3>
          </div>
          <div class="case-badge-group">
            <span class="tag-badge">HARDENED GATES</span>
            <span class="tag-badge">COACH SAFETY</span>
          </div>
        </div>
        <p class="case-desc">
          Safety is enforced by immutable software boundaries, not system prompt guidelines. Neither the lifter nor the LLM has permission to override coaching gates.
        </p>
        <div class="table-wrap">
          <table>
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
      </article>

      <!-- Case 04: Grounded in Meet Data -->
      <article id="benchmarks" class="case-item" data-case="data">
        <div class="case-header">
          <div>
            <div class="case-tag">[ PROJECT 04 // EMPIRICAL VALIDATION ]</div>
            <h3 class="case-title">Grounded in Meet Data <span class="n">TOP 300 ALL-TIME</span></h3>
          </div>
          <div class="case-badge-group">
            <span class="tag-badge">OPENPOWERLIFTING</span>
            <span class="tag-badge">CI TESTED</span>
          </div>
        </div>
        <p class="case-desc">
          Validation bounds and plausibility checks are derived directly from OpenPowerlifting competition results (top 300 lifters by Dots, Raw+Wraps). Recomputed in continuous integration so code cannot drift from empirical evidence.
        </p>
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
      </article>
    </section>

    <!-- Transparent Engineering Note -->
    <div class="unseen-manifesto">
      <div class="manifesto-tag">[ MANIFESTO // ZERO TRACKERS &middot; PURE PYTHON ]</div>
      <p class="manifesto-text">
        <strong>Transparent Note:</strong> This is a student-built engineering project for a 20-athlete powerlifting squad, not a venture-backed commercial SaaS. Zero trackers, zero analytics cookies, and no runtime framework beyond Python and SQLite.
      </p>
    </div>

    <!-- Oversized Unseen Studio Footer -->
    <footer class="unseen-footer">
      <div class="unseen-footer-hero">
        <div class="footer-kicker">READY FOR SQUAD DEPLOYMENT</div>
        <h2 class="footer-headline">
          The squad on WhatsApp.<br>
          <span class="unseen-serif">The coach in control.</span>
        </h2>
        <div class="footer-cta-wrap">
          <a class="unseen-btn unseen-btn-primary unseen-btn-lg" href="{coach_link}">
            <span>{coach_text}</span>
            {arrow_svg}
          </a>
        </div>
      </div>

      <div class="unseen-footer-bottom">
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
    </footer>
  </div>

  <!-- Interactive Client Script -->
  <script>{_LANDING_JS}</script>
</body>
</html>"""


# ------------------------------------------------------------------------------
# Privacy and Terms Pages (Styled in Unseen Studio aesthetic)
# ------------------------------------------------------------------------------
def render_privacy() -> str:
    """Render the styled privacy policy."""
    return f"""<!doctype html>
<html lang="en">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>Privacy Policy — Training Log Agent</title>
  <style>{_UNSEEN_LANDING_CSS}</style>
</head>
<body>
  <div class="unseen-ambient"></div>
  <header class="unseen-header">
    <div class="unseen-header-inner">
      <a class="unseen-brand" href="/">
        Training Log Agent<span class="reg">&reg;</span>
      </a>
      <nav class="unseen-nav">
        <a class="nav-link" href="/">&larr; Return to Home</a>
        <a class="nav-link" href="/terms">Terms of Service</a>
      </nav>
    </div>
  </header>

  <div class="unseen-wrapper">
    <div class="unseen-legal-container">
      <div class="unseen-hero-tag">[ LEGAL // TRANSPARENCY &amp; DATA PRIVACY ]</div>
      <h1>Privacy Policy</h1>
      <p>Calendar connection is optional. The service reads event start/end times and usable locations only to plan travel and training. It does not retain event titles, descriptions, attendees or meeting content.</p>
      <p>OAuth tokens and saved places are encrypted at rest with Fernet cryptography when the calendar integration is configured. Confirmed workout references are stored until the athlete asks to delete them. Calendar data is never sold and is never sent to the language model.</p>
      <p>Training, sleep, readiness and nutrition messages may be sent to the configured language-model provider for structured parsing. Coaching decisions are made by deterministic application rules in pure Python, not by that model.</p>
      <p>Athletes can send <em>“disconnect calendar”</em> in WhatsApp to delete stored calendar tokens, or <em>“forget my locations”</em> to erase saved home, office and gym places.</p>
      <div style="margin-top:32px;padding-top:20px;border-top:1px solid var(--border);">
        <a href="/" class="unseen-btn unseen-btn-ghost">&larr; Return to Home</a>
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
  <title>Terms of Service — Training Log Agent</title>
  <style>{_UNSEEN_LANDING_CSS}</style>
</head>
<body>
  <div class="unseen-ambient"></div>
  <header class="unseen-header">
    <div class="unseen-header-inner">
      <a class="unseen-brand" href="/">
        Training Log Agent<span class="reg">&reg;</span>
      </a>
      <nav class="unseen-nav">
        <a class="nav-link" href="/">&larr; Return to Home</a>
        <a class="nav-link" href="/privacy">Privacy Policy</a>
      </nav>
    </div>
  </header>

  <div class="unseen-wrapper">
    <div class="unseen-legal-container">
      <div class="unseen-hero-tag">[ LEGAL // BOUNDARIES &amp; MEDICAL DISCLAIMER ]</div>
      <h1>Terms of Service</h1>
      <p>This service is a training-log and planning aid, not medical care or clinical diagnostic software. Athletes remain responsible for confirming calendar changes and following medical advice from their coach, clinician, or registered dietitian.</p>
      <p>Injury flags immediately suppress all load progression advice. The agent never prescribes load to an injured athlete; clearance requires explicit authorization by a named human coach or medical practitioner.</p>
      <div style="margin-top:32px;padding-top:20px;border-top:1px solid var(--border);">
        <a href="/" class="unseen-btn unseen-btn-ghost">&larr; Return to Home</a>
      </div>
    </div>
  </div>
</body>
</html>"""

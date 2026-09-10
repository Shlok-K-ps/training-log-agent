"""HTML for the coach console.

One page, rendered server-side, no build step and no JavaScript framework. The
coach opens it on a phone at the gym as often as on a laptop, so it is a single
readable column that works without any of that.
"""

from __future__ import annotations

from html import escape

from app.coach.roster import BUCKET_LABEL, BUCKET_ORDER, Bucket, Roster

_STYLE = """
:root{--bg:#f1f4f5;--card:#fff;--ink:#12171a;--soft:#55616a;--faint:#7f8a91;
--line:#d7dee1;--act:#be3229;--watch:#c29216;--meet:#2a5b9e;--ok:#3a7346}
@media(prefers-color-scheme:dark){:root{--bg:#111619;--card:#181f23;--ink:#e9eef0;
--soft:#a3b0b7;--faint:#78868d;--line:#2a343a;--act:#e2685c;--watch:#e0b443;
--meet:#6e9bdd;--ok:#66af77}}
*{box-sizing:border-box}
body{margin:0;background:var(--bg);color:var(--ink);
font:16px/1.5 ui-sans-serif,system-ui,-apple-system,"Segoe UI",sans-serif}
.wrap{max-width:720px;margin:0 auto;padding:28px 18px 64px}
header{display:flex;justify-content:space-between;align-items:baseline;
gap:12px;flex-wrap:wrap;border-bottom:2px solid var(--ink);padding-bottom:12px}
h1{font-size:19px;margin:0;letter-spacing:-.01em}
.when{font-size:13px;color:var(--faint);font-variant-numeric:tabular-nums}
.summary{margin:16px 0 26px;font-size:15px;color:var(--soft)}
.summary b{color:var(--ink)}
section{margin-bottom:26px}
h2{font-size:11px;letter-spacing:.13em;text-transform:uppercase;color:var(--faint);
margin:0 0 10px;display:flex;gap:8px;align-items:center}
h2 .n{color:var(--ink)}
.card{background:var(--card);border:1px solid var(--line);border-left:4px solid var(--edge);
border-radius:3px;padding:13px 15px;margin-bottom:9px}
.needs_you{--edge:var(--act)}.watch{--edge:var(--watch)}
.meet_prep{--edge:var(--meet)}.fine{--edge:var(--line)}
.who{font-weight:600;font-size:16px;display:flex;justify-content:space-between;gap:10px}
.who .id{font-weight:400;font-size:12px;color:var(--faint);
font-family:ui-monospace,monospace;white-space:nowrap}
ul{margin:7px 0 0;padding-left:17px;color:var(--soft);font-size:14.5px}
li{margin:2px 0}
li.act{color:var(--act);font-weight:500}
form{margin:11px 0 0;display:flex;gap:7px;flex-wrap:wrap;align-items:center}
input[type=text]{flex:1 1 190px;min-width:0;padding:7px 9px;font:inherit;font-size:14px;
border:1px solid var(--line);border-radius:3px;background:var(--bg);color:var(--ink)}
button{padding:7px 13px;font:inherit;font-size:14px;font-weight:600;cursor:pointer;
border:1px solid var(--act);background:var(--act);color:#fff;border-radius:3px}
button:focus-visible,input:focus-visible{outline:2px solid var(--meet);outline-offset:2px}
.fine-list{background:var(--card);border:1px solid var(--line);border-radius:3px;
padding:12px 15px;color:var(--soft);font-size:14.5px}
.empty{color:var(--faint);font-size:14.5px;font-style:italic}
.msg{padding:11px 14px;border-radius:3px;margin-bottom:18px;font-size:14.5px;
border:1px solid var(--line);background:var(--card)}
.msg.ok{border-left:4px solid var(--ok)}
.msg.err{border-left:4px solid var(--act)}
footer{margin-top:34px;padding-top:14px;border-top:1px solid var(--line);
font-size:12.5px;color:var(--faint)}
"""


def _card(entry, token: str) -> str:
    items = "".join(
        f'<li class="{"act" if f.action else ""}">{escape(f.detail)}</li>'
        for f in entry.flags
    )
    body = f"<ul>{items}</ul>" if items else ""
    form = ""
    if entry.needs_action and entry.injury_days_open is not None:
        form = (
            '<form method="post" action="/coach/clear-injury">'
            f'<input type="hidden" name="token" value="{escape(token)}">'
            f'<input type="hidden" name="athlete_id" value="{escape(entry.athlete_id)}">'
            '<input type="text" name="reason" required maxlength="200" '
            'placeholder="Who cleared them, and on what basis">'
            "<button type=\"submit\">Clear injury</button>"
            "</form>"
        )
    return (
        f'<div class="card {entry.bucket.value}">'
        f'<div class="who"><span>{escape(entry.display_name)}</span>'
        f'<span class="id">{escape(entry.athlete_id)}</span></div>'
        f"{body}{form}</div>"
    )


def render(roster: Roster, *, token: str, coach: str, message: tuple[str, str] | None = None) -> str:
    """Full page. `message` is an optional (kind, text) banner from a POST."""
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
        cards = "".join(_card(e, token) for e in entries)
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

    return (
        "<!doctype html><html lang='en'><head><meta charset='utf-8'>"
        "<meta name='viewport' content='width=device-width,initial-scale=1'>"
        "<title>Coach console</title>"
        f"<style>{_STYLE}</style></head><body><div class='wrap'>"
        f"<header><h1>{escape(coach)} — roster</h1>"
        f"<span class='when'>{roster.reviewed_on.isoformat()}</span></header>"
        f"<p class='summary'>{summary}</p>"
        f"{banner}{''.join(sections)}"
        "<footer>Every line here is computed by the same rules that answer the "
        "athlete. This page decides nothing on its own.</footer>"
        "</div></body></html>"
    )

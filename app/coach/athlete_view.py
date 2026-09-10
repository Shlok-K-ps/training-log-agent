"""The athlete page: what they did, what the rules make of it, what to say back.

Kept separate from `view.py` so the roster and outbox markup stays as it is. The
shared stylesheet is imported rather than duplicated.
"""

from __future__ import annotations

from html import escape

from app.coach.athlete import AthleteDetail, progress_series
from app.coach.view import _BASE_CSS as _STYLE

_ATHLETE_STYLE = """
.back{margin:0 0 18px;font-size:14px}
.back a{color:var(--meet)}
.grid{display:grid;gap:9px;grid-template-columns:repeat(auto-fit,minmax(132px,1fr));
margin-bottom:22px}
.tile{background:var(--card);border:1px solid var(--line);border-radius:3px;
padding:11px 13px}
.tile .k{font-size:10.5px;letter-spacing:.12em;text-transform:uppercase;
color:var(--faint)}
.tile .v{font-size:19px;font-weight:600;margin-top:3px;
font-variant-numeric:tabular-nums}
.tile .v.warn{color:var(--act)}
table{border-collapse:collapse;width:100%;font-size:14px;margin-top:4px}
th,td{padding:7px 9px;text-align:right;border-bottom:1px solid var(--line)}
th:first-child,td:first-child{text-align:left}
thead th{font-size:10.5px;letter-spacing:.11em;text-transform:uppercase;
color:var(--faint);font-weight:600}
tbody td{font-variant-numeric:tabular-nums;color:var(--soft)}
tbody td:first-child{color:var(--ink);font-family:ui-monospace,monospace;font-size:12.5px}
.chart{background:var(--card);border:1px solid var(--line);border-radius:3px;
padding:14px 15px;margin-bottom:10px}
.chart h3{margin:0 0 2px;font-size:14.5px;font-weight:600}
.chart .cap{margin:0 0 9px;font-size:12.5px;color:var(--faint)}
.chart svg{display:block;width:100%;height:auto;overflow:visible}
.compose textarea{width:100%;min-height:150px;padding:10px;font:inherit;
font-size:14.5px;line-height:1.5;border:1px solid var(--line);border-radius:3px;
background:var(--bg);color:var(--ink);resize:vertical}
.compose .hint{font-size:12.5px;color:var(--faint);margin:7px 0 0}
"""


def _chart(lift: str, points: tuple[tuple[str, float], ...]) -> str:
    """One lift, top set over time. One series, so the heading names it and
    there is no legend; only the latest point carries a number."""
    w, h = 560, 150
    pad_l, pad_r, pad_t, pad_b = 44, 46, 14, 26
    weights = [p[1] for p in points]
    lo, hi = min(weights), max(weights)
    if hi == lo:                      # a flat run still needs a band to draw in
        lo, hi = lo - 5, hi + 5
    span = hi - lo
    inner_w, inner_h = w - pad_l - pad_r, h - pad_t - pad_b

    def x(i: int) -> float:
        return pad_l + (inner_w * i / max(1, len(points) - 1))

    def y(v: float) -> float:
        return pad_t + inner_h - (inner_h * (v - lo) / span)

    grid = "".join(
        f'<line x1="{pad_l}" y1="{y(v):.1f}" x2="{w - pad_r}" y2="{y(v):.1f}" '
        f'stroke="var(--line)" stroke-width="1"/>'
        f'<text x="{pad_l - 8}" y="{y(v) + 4:.1f}" text-anchor="end" font-size="11" '
        f'fill="var(--faint)">{v:g}</text>'
        for v in (lo, (lo + hi) / 2, hi)
    )
    path = " ".join(
        f"{'M' if i == 0 else 'L'}{x(i):.1f},{y(v):.1f}"
        for i, (_, v) in enumerate(points)
    )
    dots = "".join(
        f'<circle cx="{x(i):.1f}" cy="{y(v):.1f}" r="4.5" fill="var(--card)" '
        f'stroke="var(--meet)" stroke-width="2"><title>{escape(d)} · {v:g} kg</title></circle>'
        for i, (d, v) in enumerate(points)
    )
    last_d, last_v = points[-1]
    label = (
        f'<text x="{x(len(points) - 1) + 9:.1f}" y="{y(last_v) + 4:.1f}" font-size="12" '
        f'font-weight="600" fill="var(--ink)">{last_v:g} kg</text>'
    )
    axis = (
        f'<text x="{pad_l}" y="{h - 6}" font-size="11" fill="var(--faint)">{escape(points[0][0])}</text>'
        f'<text x="{w - pad_r}" y="{h - 6}" text-anchor="end" font-size="11" '
        f'fill="var(--faint)">{escape(last_d)}</text>'
    )
    return (
        f'<div class="chart"><h3>{escape(lift.title())}</h3>'
        f'<p class="cap">Top set per session, {len(points)} sessions</p>'
        f'<svg viewBox="0 0 {w} {h}" role="img" '
        f'aria-label="{escape(lift)} top set over {len(points)} sessions, '
        f'latest {last_v:g} kilograms">'
        f"{grid}"
        f'<path d="{path}" fill="none" stroke="var(--meet)" stroke-width="2" '
        f'stroke-linejoin="round" stroke-linecap="round"/>'
        f"{dots}{label}{axis}</svg></div>"
    )


def render_athlete(
    detail: AthleteDetail,
    *,
    coach: str,
    suggested: str,
    message: tuple[str, str] | None = None,
) -> str:
    banner = ""
    if message:
        kind, text = message
        banner = f'<div class="msg {escape(kind)}">{escape(text)}</div>'

    tiles = [
        ("Last logged", escape(detail.last_activity or "never"), False),
        ("Phase", escape(detail.phase), False),
    ]
    if detail.injured:
        days = f"{detail.injury_days_open}d" if detail.injury_days_open is not None else "open"
        tiles.append(("Injury", days, True))
    if detail.roster.days_silent:
        tiles.append(("Silent", f"{detail.roster.days_silent}d", detail.roster.days_silent >= 7))
    if detail.roster.weeks_to_meet is not None:
        tiles.append(("Meet in", f"{detail.roster.weeks_to_meet}w", False))
    tile_html = "".join(
        f'<div class="tile"><div class="k">{k}</div>'
        f'<div class="v{" warn" if warn else ""}">{v}</div></div>'
        for k, v, warn in tiles
    )

    verdicts = "".join(
        f"<tr><td>{escape(a.lift)}</td><td>{escape(a.verdict.value)}</td>"
        f"<td>{a.current_weight:g} kg</td><td>{a.sessions_considered}</td></tr>"
        if a.current_weight is not None else
        f"<tr><td>{escape(a.lift)}</td><td>{escape(a.verdict.value)}</td>"
        f"<td>—</td><td>{a.sessions_considered}</td></tr>"
        for a in detail.assessments
    )
    verdict_table = (
        "<h2>What the rules say</h2><table><thead><tr><th>Lift</th><th>Verdict</th>"
        "<th>Latest top set</th><th>Sessions</th></tr></thead>"
        f"<tbody>{verdicts}</tbody></table>"
        if verdicts else ""
    )

    charts = "".join(_chart(lift, pts) for lift, pts in progress_series(detail).items())
    charts = f"<h2>Progress</h2>{charts}" if charts else ""

    rows = "".join(
        f"<tr><td>{escape(s.session_date)}</td><td>{escape(s.lift)}</td>"
        f"<td>{escape(s.summary)}</td></tr>"
        for s in detail.sessions[:15]
    )
    log = (
        "<h2>Recent sessions</h2><table><thead><tr><th>Date</th><th>Lift</th>"
        f"<th>Set</th></tr></thead><tbody>{rows}</tbody></table>"
        if rows else '<h2>Recent sessions</h2><p class="empty">Nothing logged yet.</p>'
    )

    compose = (
        '<h2>Message this athlete</h2>'
        '<div class="card compose">'
        '<form method="post" action="/coach/athlete/'
        f'{escape(detail.athlete_id)}/message">'
        f'<textarea name="body" maxlength="1400">{escape(suggested)}</textarea>'
        '<div class="btns"><button class="approve" type="submit">Queue this message</button></div>'
        '<p class="hint">Drafted from this athlete\'s own log. Edit it freely — '
        "the athlete receives exactly what you send, and nothing goes out that you "
        "have not written or approved.</p>"
        "</form></div>"
    )

    return (
        "<!doctype html><html lang='en'><head><meta charset='utf-8'>"
        "<meta name='viewport' content='width=device-width,initial-scale=1'>"
        f"<title>{escape(detail.display_name)} — coach</title>"
        f"<style>{_STYLE}{_ATHLETE_STYLE}</style></head><body><div class='wrap'>"
        f"<header><h1>{escape(detail.display_name)}</h1>"
        f"<span class='when'>{escape(detail.athlete_id)}</span></header>"
        '<p class="back"><a href="/coach">&larr; roster</a></p>'
        f"{banner}"
        f'<div class="grid">{tile_html}</div>'
        f"{verdict_table}{charts}{log}{compose}"
        "<footer>Every verdict here comes from the same rules that answer the "
        "athlete. The draft is a starting point, not a decision.</footer>"
        "</div></body></html>"
    )

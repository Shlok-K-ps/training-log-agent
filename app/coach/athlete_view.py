"""The athlete page: what they did, what the rules make of it, what to say back.

Kept separate from `view.py` so the roster and outbox markup stays as it is. The
shared stylesheet is imported rather than duplicated.
"""

from __future__ import annotations

from html import escape

from app.coach.athlete import AthleteDetail, progress_series
from app.coach.view import coach_frame

_ATHLETE_STYLE = """
:root{--card:var(--surface);--line:var(--border);--meet:var(--plate-blue);
--faint:var(--ink-faint);--soft:var(--ink-soft);--act:var(--plate-red)}
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
.profile-grid{display:grid;grid-template-columns:minmax(0,1.3fr) minmax(290px,.8fr);gap:20px}
.context-grid{display:grid;grid-template-columns:repeat(2,minmax(0,1fr));gap:12px;margin:18px 0 24px}
.context-card{background:var(--surface);border:1px solid var(--border);border-radius:6px;padding:15px}
.context-card h2{margin-bottom:10px;color:var(--ink)}
.facts{margin:0;display:grid;gap:7px}
.facts div{display:flex;justify-content:space-between;gap:12px;border-top:1px solid var(--border);padding-top:7px}
.facts div:first-child{border-top:0;padding-top:0}
.facts dt{font-size:12.5px;color:var(--ink-faint)}
.facts dd{margin:0;text-align:right;font-size:12.5px;font-weight:600}
.coach-draft{position:sticky;top:22px}
.coach-draft .draft-state{font-size:11px;font-weight:700;text-transform:uppercase;
letter-spacing:.08em;color:var(--plate-yellow-text);margin-bottom:8px}
.coach-draft form{display:block}.coach-draft textarea{width:100%}.coach-draft .btns{margin-top:10px}
.recovery-reasons{margin:8px 0 0;padding-left:18px;font-size:12.5px;color:var(--ink-soft)}
.status-strip{padding:11px 13px;border-radius:5px;margin-bottom:15px;background:var(--surface-inset);
font-size:13px;color:var(--ink-soft)}
@media(max-width:820px){.profile-grid{grid-template-columns:1fr}.coach-draft{position:static}}
@media(max-width:540px){.context-grid{grid-template-columns:1fr}}
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
        ("Last logged", detail.last_activity or "never", False),
        ("Readiness", f"{detail.readiness_score}/100" if detail.readiness_score is not None else "not checked in", detail.readiness_band in {"orange", "red"}),
        ("Sleep", f"{detail.checkin.sleep_hours:g} h" if detail.checkin and detail.checkin.sleep_hours is not None else "not reported", False),
        ("Phase", detail.phase, False),
    ]
    if detail.injured:
        days = f"{detail.injury_days_open}d" if detail.injury_days_open is not None else "open"
        tiles.append(("Injury", days, True))
    if any(f.kind == "silent" for f in detail.roster.flags):
        tiles.append(("Silent", f"{detail.roster.days_silent}d", True))
    if detail.roster.weeks_to_meet is not None:
        tiles.append(("Meet in", f"{detail.roster.weeks_to_meet}w", False))
    tile_html = "".join(
        f'<div class="tile"><div class="k">{escape(k)}</div>'
        f'<div class="v{" warn" if warn else ""}">{escape(v)}</div></div>'
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
        '<div class="context-card compose coach-draft">'
        '<div class="draft-state">Prepared · requires coach approval</div>'
        '<h2>Message for the athlete</h2>'
        '<form method="post" action="/coach/athlete/'
        f'{escape(detail.athlete_id)}/message">'
        f'<textarea name="body" maxlength="1400">{escape(suggested)}</textarea>'
        '<div class="btns"><button class="approve" type="submit">Approve and queue</button></div>'
        '<p class="hint">Built from this athlete\'s record and current trend. Edit freely. '
        "The exact approved wording is what will be sent.</p>"
        "</form></div>"
    )

    def facts(items: list[tuple[str, object]]) -> str:
        usable = [(label, value) for label, value in items if value not in (None, "", ())]
        if not usable:
            return '<p class="empty">Not configured yet.</p>'
        return '<dl class="facts">' + "".join(
            f'<div><dt>{escape(label)}</dt><dd>{escape(str(value))}</dd></div>'
            for label, value in usable
        ) + '</dl>'

    recovery = facts([
        ("Readiness band", detail.readiness_band),
        ("Self-rating", detail.checkin.readiness if detail.checkin else None),
        ("Soreness", detail.checkin.soreness if detail.checkin else None),
        ("Stress", detail.checkin.stress if detail.checkin else None),
        ("Bodyweight", f"{detail.checkin.bodyweight_kg:g} kg" if detail.checkin and detail.checkin.bodyweight_kg is not None else None),
    ])
    reasons = "".join(f"<li>{escape(reason)}</li>" for reason in detail.readiness_reasons)
    recovery_panel = (
        '<div class="context-card"><h2>Recovery today</h2>' + recovery
        + (f'<ul class="recovery-reasons">{reasons}</ul>' if reasons else "") + '</div>'
    )
    program_panel = '<div class="context-card"><h2>Programming</h2>' + facts([
        ("Method", str(detail.program.get("methodology", "")).replace("_", " ")),
        ("Experience", detail.program.get("experience")),
        ("Training days", detail.program.get("days_per_week")),
        ("Meet date", detail.program.get("meet_date")),
    ]) + '</div>'
    schedule_panel = '<div class="context-card"><h2>Schedule & logistics</h2>' + facts([
        ("Calendar", "Connected" if detail.calendar_connected else "Not connected"),
        ("Timezone", detail.schedule.get("timezone")),
        ("Morning check-in", detail.schedule.get("morning_checkin_time")),
        ("Usual training", detail.schedule.get("training_time")),
        ("Bedtime", detail.schedule.get("bedtime")),
    ]) + '</div>'
    supplement_text = "; ".join(detail.supplements) if detail.supplements else None
    nutrition_panel = '<div class="context-card"><h2>Nutrition & supplements</h2>' + facts([
        ("Diet", detail.nutrition.get("diet_style")),
        ("Foods available", detail.nutrition.get("foods_available")),
        ("Allergies", detail.nutrition.get("allergies")),
        ("Meals", detail.nutrition.get("meals_per_day")),
        ("Protein target", f'{detail.nutrition.get("protein_target_g")} g' if detail.nutrition.get("protein_target_g") else None),
        ("Approved supplements", supplement_text),
    ]) + '</div>'
    status = " · ".join(f.detail for f in detail.roster.flags) or "No active flags — current trend is within policy."
    body = (
        f"{banner}<p class='back'><a href='/coach/athletes'>← All athletes</a></p>"
        f'<div class="status-strip"><strong>Current status:</strong> {escape(status)}</div>'
        f'<div class="grid">{tile_html}</div>'
        '<div class="profile-grid"><div>'
        f'<div class="context-grid">{recovery_panel}{program_panel}{schedule_panel}{nutrition_panel}</div>'
        f"{verdict_table}{charts}{log}</div>{compose}</div>"
    )
    return coach_frame(
        body, active="athletes", coach=coach, title=detail.display_name,
        subtitle=f"{detail.athlete_id} · complete training, recovery and plan history",
        today=detail.reviewed_on.isoformat(), extra_style=_ATHLETE_STYLE,
    )

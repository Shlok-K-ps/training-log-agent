"""The athlete page: what they did, what the rules make of it, what to say back.

Kept separate from `view.py` so the roster and outbox markup stays as it is. The
shared stylesheet is imported rather than duplicated.
"""

from __future__ import annotations

from html import escape

from app.coach.athlete import AthleteDetail, progress_series
from app.coach.view import coach_frame

_ATHLETE_STYLE = """
:root {
  --card: var(--surface);
  --line: var(--border);
  --meet: var(--plate-blue);
  --faint: var(--ink-faint);
  --soft: var(--ink-soft);
  --act: var(--plate-red);
}

.back {
  margin: 0 0 20px;
  font-size: 13.5px;
}

.back a {
  color: var(--accent-cyan);
  text-decoration: none;
  font-family: var(--font-mono);
  font-size: 12.5px;
  letter-spacing: 0.04em;
  display: inline-flex;
  align-items: center;
  gap: 6px;
  padding: 6px 14px;
  border-radius: 9999px;
  background: rgba(255, 255, 255, 0.03);
  border: 1px solid var(--border);
  transition: all 0.2s ease;
}

.back a:hover {
  background: rgba(255, 255, 255, 0.07);
  border-color: var(--border-strong);
  color: #ffffff;
}

.status-strip {
  padding: 12px 18px;
  border-radius: 12px;
  margin-bottom: 22px;
  background: var(--surface-inset);
  border: 1px solid var(--border);
  font-size: 13.5px;
  color: var(--ink-soft);
  display: flex;
  align-items: center;
  gap: 10px;
}

.status-strip strong {
  color: var(--ink);
  font-family: var(--font-mono);
  font-size: 11px;
  letter-spacing: 0.08em;
  text-transform: uppercase;
  display: inline-flex;
  align-items: center;
  gap: 5px;
}

.status-strip strong .sym {
  color: var(--accent-cyan);
}

.grid {
  display: grid;
  gap: 12px;
  grid-template-columns: repeat(auto-fit, minmax(140px, 1fr));
  margin-bottom: 28px;
}

.tile {
  background: var(--card);
  border: 1px solid var(--border);
  border-radius: 12px;
  padding: 14px 16px;
  transition: all 0.2s ease;
}

.tile:hover {
  border-color: var(--border-strong);
  transform: translateY(-1px);
}

.tile .k {
  font-size: 11px;
  font-family: var(--font-mono);
  letter-spacing: 0.08em;
  text-transform: uppercase;
  color: var(--ink-faint);
  display: flex;
  align-items: center;
  gap: 6px;
}

.tile .k .sym {
  color: var(--accent-cyan);
  font-size: 12px;
}

.tile .v {
  font-size: 22px;
  font-weight: 700;
  margin-top: 5px;
  letter-spacing: -0.02em;
  color: var(--ink);
  font-variant-numeric: tabular-nums;
}

.tile .v.warn {
  color: var(--plate-red);
}

.profile-grid {
  display: grid;
  grid-template-columns: minmax(0, 1.35fr) minmax(320px, 0.85fr);
  gap: 24px;
}

.context-grid {
  display: grid;
  grid-template-columns: repeat(2, minmax(0, 1fr));
  gap: 14px;
  margin: 0 0 24px;
}

.context-card {
  background: var(--surface);
  border: 1px solid var(--border);
  border-radius: 14px;
  padding: 18px 20px;
}

.context-card h2 {
  margin: 0 0 14px;
  font-size: 13.5px;
  font-weight: 600;
  letter-spacing: 0.05em;
  text-transform: uppercase;
  font-family: var(--font-mono);
  color: var(--ink-secondary);
  display: flex;
  align-items: center;
  gap: 7px;
}

.context-card h2 .sym {
  color: var(--accent-cyan);
  font-size: 13px;
}

.facts {
  margin: 0;
  display: grid;
  gap: 8px;
}

.facts div {
  display: flex;
  justify-content: space-between;
  gap: 12px;
  border-top: 1px solid var(--border);
  padding-top: 8px;
}

.facts div:first-child {
  border-top: 0;
  padding-top: 0;
}

.facts dt {
  font-size: 12.5px;
  color: var(--ink-faint);
}

.facts dd {
  margin: 0;
  text-align: right;
  font-size: 13px;
  font-weight: 600;
  color: var(--ink-secondary);
}

.recovery-reasons {
  margin: 12px 0 0;
  padding-left: 18px;
  font-size: 12.5px;
  color: var(--ink-soft);
  line-height: 1.5;
}

.coach-draft {
  position: sticky;
  top: 24px;
  align-self: start;
}

.coach-draft .draft-state {
  font-size: 10.5px;
  font-weight: 700;
  font-family: var(--font-mono);
  text-transform: uppercase;
  letter-spacing: 0.08em;
  color: var(--plate-yellow-text);
  margin-bottom: 10px;
  display: inline-flex;
  align-items: center;
  gap: 5px;
  background: var(--plate-yellow-bg);
  border: 1px solid var(--plate-yellow-border);
  padding: 3px 10px;
  border-radius: 9999px;
}

.coach-draft form {
  display: block;
}

.coach-draft textarea {
  width: 100%;
  min-height: 160px;
  padding: 12px 14px;
  font-family: inherit;
  font-size: 14px;
  line-height: 1.6;
  border: 1px solid var(--border);
  border-radius: 12px;
  background: var(--surface-inset);
  color: var(--ink);
  resize: vertical;
}

.coach-draft textarea:focus {
  outline: none;
  border-color: var(--accent-cyan);
  box-shadow: 0 0 0 3px rgba(56, 189, 248, 0.12);
}

.coach-draft .btns {
  margin-top: 14px;
}

.coach-draft .btns button.approve {
  width: 100%;
  padding: 12px 18px;
  font-size: 14px;
  font-weight: 600;
  background: #ffffff;
  color: #070709;
  border: 1px solid #ffffff;
  border-radius: 9999px;
  cursor: pointer;
  transition: all 0.2s ease;
  display: flex;
  align-items: center;
  justify-content: center;
  gap: 8px;
}

.coach-draft .btns button.approve:hover {
  opacity: 0.92;
  transform: translateY(-1px);
}

.compose .hint {
  font-size: 12px;
  color: var(--ink-faint);
  margin: 10px 0 0;
  line-height: 1.5;
}

.chart {
  background: var(--surface);
  border: 1px solid var(--border);
  border-radius: 14px;
  padding: 18px 20px;
  margin-bottom: 16px;
}

.chart h3 {
  margin: 0 0 4px;
  font-size: 15px;
  font-weight: 600;
  color: var(--ink);
  display: flex;
  align-items: center;
  gap: 6px;
}

.chart h3 .sym {
  color: var(--accent-cyan);
}

.chart .cap {
  margin: 0 0 12px;
  font-size: 12.5px;
  font-family: var(--font-mono);
  color: var(--ink-faint);
}

.chart svg {
  display: block;
  width: 100%;
  height: auto;
  overflow: visible;
}

.pivot-panel { border: 1px solid var(--plate-red-border); background: var(--plate-red-bg); border-radius: 14px; padding: 18px; margin-bottom: 22px; }
.pivot-panel > p { font-size: 13px; color: var(--plate-red-text); }
.pivot-grid { display: grid; grid-template-columns: repeat(2, minmax(0, 1fr)); gap: 12px; }
.pivot-option { background: var(--surface); border: 1px solid var(--border); border-radius: 12px; padding: 15px; }
.pivot-option.recommended { border-color: var(--accent-cyan); }
.pivot-option h3 { font-size: 14px; margin: 8px 0 6px; }
.pivot-option p { font-size: 12.5px; color: var(--ink-soft); margin: 6px 0; }
.pivot-option form { margin-top: 10px; }
.goal-signal { padding: 11px 13px; border-radius: 10px; background: var(--plate-blue-bg); border: 1px solid var(--plate-blue-border); font-size: 12.5px; margin-top: 12px; }
.clearance-panel { border: 1px solid var(--plate-red-border); background: linear-gradient(135deg, var(--plate-red-bg), var(--surface)); border-radius: 16px; padding: 20px; margin-bottom: 22px; }
.clearance-head { display: flex; justify-content: space-between; gap: 16px; align-items: flex-start; margin-bottom: 15px; }
.clearance-head h2 { margin: 0 0 5px; font-size: 19px; }
.clearance-head p { margin: 0; color: var(--ink-soft); font-size: 13px; }
.clearance-state { flex: 0 0 auto; color: var(--plate-red-text); background: var(--plate-red-bg); border: 1px solid var(--plate-red-border); border-radius: 9999px; padding: 5px 10px; font: 700 10.5px var(--font-mono); text-transform: uppercase; letter-spacing: .06em; }
.clearance-boundary { display: grid; grid-template-columns: repeat(3, 1fr); gap: 8px; margin: 0 0 16px; }
.clearance-boundary div { border: 1px solid var(--border); background: var(--surface-inset); border-radius: 10px; padding: 11px; }
.clearance-boundary b { display: block; color: var(--ink); font-size: 12px; margin-bottom: 3px; }
.clearance-boundary span { color: var(--ink-faint); font-size: 11.5px; line-height: 1.4; }
.clearance-form { display: grid; grid-template-columns: 1fr 1fr; gap: 12px; border-top: 1px solid var(--border); padding-top: 16px; }
.clearance-form label { color: var(--ink-soft); font-size: 12.5px; font-weight: 600; }
.clearance-form input[type="text"], .clearance-form textarea { display: block; width: 100%; margin-top: 6px; color: var(--ink); background: var(--surface-inset); border: 1px solid var(--border); border-radius: 10px; padding: 11px 12px; font: inherit; }
.clearance-form textarea { min-height: 84px; resize: vertical; }
.clearance-form input:focus, .clearance-form textarea:focus { outline: none; border-color: var(--accent-cyan); box-shadow: 0 0 0 3px rgba(56,189,248,.1); }
.clearance-confirm { grid-column: 1 / -1; display: flex; align-items: flex-start; gap: 9px; padding: 11px 12px; border-radius: 10px; background: var(--plate-yellow-bg); border: 1px solid var(--plate-yellow-border); color: var(--plate-yellow-text) !important; }
.clearance-confirm input { margin-top: 3px; }
.clearance-actions { grid-column: 1 / -1; display: flex; align-items: center; justify-content: space-between; gap: 12px; }
.clearance-actions small { color: var(--ink-faint); max-width: 560px; }
.clearance-actions button { background: var(--plate-red); color: #fff; border: 0; border-radius: 9999px; padding: 10px 17px; font-weight: 700; cursor: pointer; }

@media(max-width:860px){
  .profile-grid { grid-template-columns: 1fr; }
  .coach-draft { position: static; }
}

@media(max-width:540px){
  .context-grid, .pivot-grid, .clearance-boundary, .clearance-form { grid-template-columns: 1fr; }
  .clearance-confirm, .clearance-actions { grid-column: auto; }
  .clearance-head, .clearance-actions { flex-direction: column; }
}
"""


def _injury_pivot_panel(detail: AthleteDetail) -> str:
    if not detail.injured or detail.injury_entry_id is None:
        return ""
    selected = detail.injury_plan_decision
    selected_note = ""
    if selected and int(selected.get("injury_entry_id", -1)) == detail.injury_entry_id:
        selected_note = (
            '<div class="msg ok"><strong>Current coach-approved pivot:</strong> '
            f'{escape(str(selected.get("plan_text", "")))}</div>'
        )
    options = []
    for option in detail.injury_pivots:
        marker = '<span class="badge badge-blue">Recommended starting path</span>' if option.recommended else ""
        options.append(
            f'<div class="pivot-option {"recommended" if option.recommended else ""}">{marker}'
            f'<h3>{escape(option.title)}</h3><p>{escape(option.plan)}</p>'
            f'<p><strong>Why consider it:</strong> {escape(option.rationale)}</p>'
            f'<form method="post" action="/coach/athlete/{escape(detail.athlete_id)}/injury-plan">'
            f'<input type="hidden" name="injury_entry_id" value="{detail.injury_entry_id}">'
            f'<input type="hidden" name="option_code" value="{escape(option.code)}">'
            '<button type="submit">Approve this training pivot</button></form></div>'
        )
    return (
        '<section class="pivot-panel"><h2>Fresh injury · coach decision required</h2>'
        '<p>The injury gate remains open in every path. These options change training only; '
        'they do not diagnose the injury or clear the athlete.</p>'
        f'{selected_note}<div class="pivot-grid">{"".join(options)}</div></section>'
    )


def _injury_clearance_panel(detail: AthleteDetail) -> str:
    """A deliberate safety review, shown only after the athlete requests clearance."""
    if not detail.injured or not detail.clearance_requested:
        return ""
    days = (
        f"Open {detail.injury_days_open} days"
        if detail.injury_days_open is not None else "Injury gate open"
    )
    return (
        '<section id="clearance-review" class="clearance-panel">'
        '<div class="clearance-head"><div><h2>Injury clearance review</h2>'
        '<p>The athlete has asked to resume normal programming. Record the independent '
        'basis before removing the software safety gate.</p></div>'
        f'<span class="clearance-state">{escape(days)}</span></div>'
        '<div class="clearance-boundary">'
        '<div><b>1 · Verify</b><span>A named coach, physio or clinician—not the athlete—has assessed readiness.</span></div>'
        '<div><b>2 · Record</b><span>Capture who provided clearance and the concrete basis for it.</span></div>'
        '<div><b>3 · Reopen</b><span>Only then can normal load suggestions resume.</span></div>'
        '</div><form class="clearance-form" method="post" action="/coach/clear-injury">'
        f'<input type="hidden" name="athlete_id" value="{escape(detail.athlete_id)}">'
        '<label>Named clearance source'
        '<input type="text" name="clearance_source" required maxlength="100" '
        'placeholder="e.g. Dr Mehta, sports physio"></label>'
        '<label>Basis for clearance'
        '<textarea name="reason" required maxlength="400" '
        'placeholder="What was assessed, and what return-to-training limits apply?"></textarea></label>'
        '<label class="clearance-confirm"><input type="checkbox" name="independent_confirmation" '
        'value="confirmed" required><span>I confirm this clearance came from someone other '
        'than the athlete and I want to remove the injury safety gate.</span></label>'
        '<div class="clearance-actions"><small>This records the signed-in coach, source, basis '
        'and timestamp. It does not represent a diagnosis by Power AI.</small>'
        '<button type="submit">Record clearance and reopen programming</button></div>'
        '</form></section>'
    )


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
    gradient_id = f"grad-{escape(lift)}"
    defs = (
        f'<defs>'
        f'<linearGradient id="{gradient_id}" x1="0" y1="0" x2="1" y2="0">'
        '<stop offset="0%" stop-color="var(--gradient-color-1)"/>'
        '<stop offset="50%" stop-color="var(--gradient-color-2)"/>'
        '<stop offset="100%" stop-color="var(--gradient-color-3)"/>'
        '</linearGradient>'
        f'<filter id="glow-{gradient_id}" x="-40%" y="-40%" width="180%" height="180%">'
        '<feGaussianBlur in="SourceGraphic" stdDeviation="3.5" result="blur"/>'
        '<feMerge><feMergeNode in="blur"/><feMergeNode in="SourceGraphic"/></feMerge>'
        '</filter>'
        '</defs>'
    )
    path = " ".join(
        f"{'M' if i == 0 else 'L'}{x(i):.1f},{y(v):.1f}"
        for i, (_, v) in enumerate(points)
    )
    dots = "".join(
        f'<circle cx="{x(i):.1f}" cy="{y(v):.1f}" r="3.5" fill="var(--surface)" '
        f'stroke="var(--accent-cyan)" stroke-width="2"><title>{escape(d)} · {v:g} kg</title></circle>'
        for i, (d, v) in enumerate(points)
    )
    last_d, last_v = points[-1]
    active_dot = (
        f'<circle cx="{x(len(points) - 1):.1f}" cy="{y(last_v):.1f}" r="5.5" fill="#ffffff" '
        f'stroke="var(--gradient-color-1)" stroke-width="2.5" filter="url(#glow-{gradient_id})"/>'
    )
    label = (
        f'<text x="{x(len(points) - 1) + 11:.1f}" y="{y(last_v) + 4:.1f}" font-size="12" '
        f'font-family="var(--font-mono)" font-weight="700" fill="#ffffff">{last_v:g} kg</text>'
    )
    axis = (
        f'<text x="{pad_l}" y="{h - 6}" font-size="11" font-family="var(--font-mono)" fill="var(--faint)">{escape(points[0][0])}</text>'
        f'<text x="{w - pad_r}" y="{h - 6}" text-anchor="end" font-size="11" font-family="var(--font-mono)" '
        f'fill="var(--faint)">{escape(last_d)}</text>'
    )
    return (
        f'<div class="chart"><h3>{escape(lift.title())}</h3>'
        f'<p class="cap">Top set per session &middot; {len(points)} sessions recorded</p>'
        f'<svg viewBox="0 0 {w} {h}" role="img" '
        f'aria-label="{escape(lift)} top set over {len(points)} sessions, '
        f'latest {last_v:g} kilograms">'
        f"{defs}{grid}"
        f'<path d="{path}" fill="none" stroke="url(#{gradient_id})" stroke-width="2.5" '
        f'stroke-linejoin="round" stroke-linecap="round"/>'
        f"{dots}{active_dot}{label}{axis}</svg></div>"
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
        ("Last logged", detail.last_activity or "never", False, ""),
        ("Readiness", f"{detail.readiness_score}/100" if detail.readiness_score is not None else "not checked in", detail.readiness_band in {"orange", "red"}, ""),
        ("Sleep", f"{detail.checkin.sleep_hours:g} h" if detail.checkin and detail.checkin.sleep_hours is not None else "not reported", False, ""),
        ("Phase", detail.phase, False, ""),
    ]
    if detail.injured:
        days = f"{detail.injury_days_open}d" if detail.injury_days_open is not None else "open"
        tiles.append(("Injury", days, True, ""))
    if any(f.kind == "silent" for f in detail.roster.flags):
        tiles.append(("Silent", f"{detail.roster.days_silent}d", True, ""))
    if detail.roster.weeks_to_meet is not None:
        tiles.append(("Meet in", f"{detail.roster.weeks_to_meet}w", False, ""))
    tile_html = "".join(
        f'<div class="tile"><div class="k">{escape(k)}</div>'
        f'<div class="v{" warn" if warn else ""}">{escape(v)}</div></div>'
        for k, v, warn, sym in tiles
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
        f'<textarea name="body" id="draft-composer" maxlength="1400" '
        f'oninput="document.getElementById(\'live-preview-bubble\').textContent=this.value">{escape(suggested)}</textarea>'
        '<div class="draft-preview-wrap" style="margin: 12px 0;">'
        '<div class="tag-mono" style="font-size:10px;margin-bottom:6px;">LIVE WHATSAPP PREVIEW</div>'
        f'<div id="live-preview-bubble" class="chat-bubble chat-agent" style="max-width:100%;">{escape(suggested)}</div>'
        '</div>'
        '<div class="btns"><button class="btn btn-primary" style="width:100%;" type="submit">Approve and queue</button></div>'
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
        ("Suggested starting method", detail.suggested_method),
        ("Why", detail.suggested_method_reason),
        ("Inputs still needed", ", ".join(detail.suggested_method_inputs)),
        ("Experience", detail.program.get("experience")),
        ("Training days", detail.program.get("days_per_week")),
        ("Starting bodyweight", f'{detail.profile.get("bodyweight_kg")} kg' if detail.profile.get("bodyweight_kg") else None),
        ("Squat 1RM", f'{detail.profile.get("squat_1rm_kg")} kg' if detail.profile.get("squat_1rm_kg") else None),
        ("Bench 1RM", f'{detail.profile.get("bench_1rm_kg")} kg' if detail.profile.get("bench_1rm_kg") else None),
        ("Deadlift 1RM", f'{detail.profile.get("deadlift_1rm_kg")} kg' if detail.profile.get("deadlift_1rm_kg") else None),
        ("Meet date", detail.program.get("meet_date")),
    ]) + (
        '<div class="goal-signal"><strong>Goal pace:</strong> '
        f'{escape(detail.goal_pace.status.replace("_", " ").title())} · '
        f'{detail.goal_pace.current_kg:g} kg current e1RM vs '
        f'{detail.goal_pace.expected_kg:g} kg expected today, targeting '
        f'{detail.goal_pace.target_kg:g} kg by {escape(detail.goal_pace.target_date)}.</div>'
        if detail.goal_pace else ""
    ) + '</div>'
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
        f"{banner}<p class='back'><a href='/coach/athletes'>← All athletes / Roster</a></p>"
        f'<div class="status-strip"><strong>Current status:</strong> {escape(status)}</div>'
        f'{_injury_clearance_panel(detail)}{_injury_pivot_panel(detail)}'
        f'<div class="grid">{tile_html}</div>'
        '<div class="profile-grid"><div>'
        f'<div class="context-grid">{recovery_panel}{program_panel}{schedule_panel}{nutrition_panel}</div>'
        f"{verdict_table}{charts}{log}</div>{compose}</div>"
    )
    bucket_tints = {
        "needs_you": ":root { --gradient-color-1: #B8323A; --gradient-color-2: #5B2A86; --gradient-color-3: #15171C; }",
        "watch": ":root { --gradient-color-1: #B8860B; --gradient-color-2: #5B2A86; --gradient-color-3: #15171C; }",
        "meet_prep": ":root { --gradient-color-1: #1D3FA8; --gradient-color-2: #5B2A86; --gradient-color-3: #15171C; }",
        "fine": ":root { --gradient-color-1: #1E6B48; --gradient-color-2: #1D3FA8; --gradient-color-3: #15171C; }",
    }
    tint_style = bucket_tints.get(detail.roster.bucket.value, "") + _ATHLETE_STYLE
    return coach_frame(
        body, active="athletes", coach=coach, title=detail.display_name,
        subtitle=f"{detail.athlete_id} · complete training, recovery and plan history",
        today=detail.reviewed_on.isoformat(), extra_style=tint_style,
    )

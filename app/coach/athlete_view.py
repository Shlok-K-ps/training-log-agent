"""The athlete page: what they did, what the rules make of it, what to say back.

Kept separate from `view.py` so the roster and outbox markup stays as it is. The
shared stylesheet is imported rather than duplicated.
"""

from __future__ import annotations

from html import escape

from app.coach.athlete import AthleteDetail, progress_series
from app.coach.view import coach_frame

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
        f'style="stroke:var(--separator)" stroke-width="1"/>'
        f'<text x="{pad_l - 8}" y="{y(v) + 4:.1f}" text-anchor="end">{v:g}</text>'
        for v in (lo, (lo + hi) / 2, hi)
    )
    gradient_id = "area-" + "".join(c if c.isalnum() else "-" for c in lift)
    defs = (
        f'<defs><linearGradient id="{gradient_id}" x1="0" y1="0" x2="0" y2="1">'
        '<stop offset="0%" style="stop-color:var(--tint);stop-opacity:0.26"/>'
        '<stop offset="100%" style="stop-color:var(--tint);stop-opacity:0"/>'
        '</linearGradient></defs>'
    )
    path = " ".join(
        f"{'M' if i == 0 else 'L'}{x(i):.1f},{y(v):.1f}"
        for i, (_, v) in enumerate(points)
    )
    baseline = pad_t + inner_h
    area = f"{path} L{x(len(points) - 1):.1f},{baseline:.1f} L{x(0):.1f},{baseline:.1f} Z"
    dots = "".join(
        f'<circle cx="{x(i):.1f}" cy="{y(v):.1f}" r="3" style="fill:var(--card);stroke:var(--tint)" '
        f'stroke-width="1.8"><title>{escape(d)} · {v:g} kg</title></circle>'
        for i, (d, v) in enumerate(points)
    )
    last_d, last_v = points[-1]
    active_dot = (
        f'<circle cx="{x(len(points) - 1):.1f}" cy="{y(last_v):.1f}" r="5" '
        'style="fill:var(--tint);stroke:var(--card)" stroke-width="2.5"/>'
    )
    label = (
        f'<text class="last-label" x="{x(len(points) - 1) + 11:.1f}" y="{y(last_v) + 4:.1f}">{last_v:g} kg</text>'
    )
    axis = (
        f'<text x="{pad_l}" y="{h - 6}">{escape(points[0][0])}</text>'
        f'<text x="{w - pad_r}" y="{h - 6}" text-anchor="end">{escape(last_d)}</text>'
    )
    return (
        f'<div class="chart"><h3>{escape(lift.title())}</h3>'
        f'<p class="cap">Top set per session &middot; {len(points)} sessions recorded</p>'
        f'<svg viewBox="0 0 {w} {h}" role="img" '
        f'aria-label="{escape(lift)} top set over {len(points)} sessions, '
        f'latest {last_v:g} kilograms">'
        f"{defs}{grid}"
        f'<path d="{area}" fill="url(#{gradient_id})" stroke="none"/>'
        f'<path d="{path}" fill="none" style="stroke:var(--tint)" stroke-width="2.5" '
        f'stroke-linejoin="round" stroke-linecap="round"/>'
        f"{dots}{active_dot}{label}{axis}</svg></div>"
    )


def render_athlete(
    detail: AthleteDetail,
    *,
    coach: str,
    suggested: str,
    message: tuple[str, str] | None = None,
    telegram_pairing_url: str | None = None,
    telegram_linked: bool = False,
    telegram_ready: bool | None = None,
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
        '<div class="draft-preview-wrap">'
        '<div class="section-caption">Preview</div>'
        f'<div id="live-preview-bubble" class="chat-bubble">{escape(suggested)}</div>'
        '</div>'
        '<div class="btns"><button class="btn btn-primary" type="submit">Approve and queue</button></div>'
        '<p class="hint">Built from this athlete\'s record and current trend. Edit freely. '
        "The exact approved wording is what will be sent.</p>"
        "</form></div>"
    )
    telegram_panel = ""
    if telegram_ready is None:
        telegram_ready = bool(telegram_linked or telegram_pairing_url)
    if telegram_linked and telegram_ready:
        telegram_panel = (
            '<section class="channel-callout"><div><span class="channel-label">Athlete channel · Connected</span>'
            '<h2>Telegram connected</h2><p>This athlete receives approved messages '
            'through the permanent Telegram channel.</p></div><form method="post" action="/coach/athlete/'
            f'{escape(detail.athlete_id)}/telegram/unlink">'
            '<button class="danger" type="submit">Disconnect Telegram</button>'
            '</form></section>'
        )
    elif telegram_pairing_url and telegram_ready:
        telegram_panel = (
            '<section class="channel-callout"><div><span class="channel-label">Athlete channel · Action needed</span>'
            '<h2>Connect this athlete to Telegram</h2>'
            '<p>Open the signed link, press Start in Telegram, and this private chat '
            'will be paired to the athlete profile.</p></div>'
            f'<a class="approve" href="{escape(telegram_pairing_url)}" '
            'target="_blank" rel="noopener">Connect Telegram</a></section>'
        )
    elif telegram_pairing_url:
        telegram_panel = (
            '<section class="channel-callout"><div><span class="channel-label">Athlete channel · Reconnecting</span>'
            '<h2>Telegram webhook is not ready</h2><p>The bot settings exist, but '
            'Render has not confirmed its webhook. Check the deployment log before pairing.</p></div></section>'
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
        f"{banner}"
        f'<div class="status-strip"><strong>Current status:</strong> {escape(status)}</div>'
        f'{telegram_panel}'
        f'{_injury_clearance_panel(detail)}{_injury_pivot_panel(detail)}'
        f'<div class="grid">{tile_html}</div>'
        '<div class="profile-grid"><div>'
        f'<div class="context-grid">{recovery_panel}{program_panel}{schedule_panel}{nutrition_panel}</div>'
        f"{verdict_table}{charts}{log}</div>{compose}</div>"
    )
    return coach_frame(
        body, active="athletes", coach=coach, title=detail.display_name,
        subtitle=f"{detail.athlete_id} · complete training, recovery and plan history",
        today=detail.reviewed_on.isoformat(), back=("/coach/athletes", "Athletes"),
        athlete_id=detail.athlete_id,
    )

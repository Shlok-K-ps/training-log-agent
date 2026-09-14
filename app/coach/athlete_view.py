"""The athlete page: what they did, what the rules make of it, what to say back.

It opens on the decision the coach owes this athlete, then the evidence, the plan
and the conversation. Everything shown comes from the same rules and records the
agent used; the page adds no coaching of its own.
"""

from __future__ import annotations

from html import escape

from app.coach.agent_view import AGENT_STYLE
from app.coach.athlete import AthleteDetail, progress_series
from app.coach.view import coach_frame, conversation_bubbles, initials
from app.decision.injury_pivot import InjuryPivot, pivot_message
from app.scheduling.outbox import message_kind_label

_BUCKET_TONE = {"needs_you": "act", "watch": "watch", "meet_prep": "meet", "fine": "fine"}
_BUCKET_BADGE = {
    "needs_you": ("tag-act", "Needs you"),
    "watch": ("tag-watch", "Watch"),
    "meet_prep": ("tag-meet", "Meet prep"),
    "fine": ("tag-fine", "On track"),
}


def _current_plan(detail: AthleteDetail) -> InjuryPivot | None:
    """The pivot the coach approved for this injury, if it still applies."""
    decision = detail.injury_plan_decision
    if (
        not decision
        or detail.injury_entry_id is None
        or int(decision.get("injury_entry_id", -1)) != detail.injury_entry_id
    ):
        return None
    code = str(decision.get("option_code"))
    return next((option for option in detail.injury_pivots if option.code == code), None)


def _hero(detail: AthleteDetail, *, plan: InjuryPivot | None, awaiting: int) -> str:
    bucket = detail.roster.bucket.value
    badge_cls, badge_text = _BUCKET_BADGE.get(bucket, ("tag-fine", "On track"))
    status = " · ".join(f.detail for f in detail.roster.flags) or "No active flags — current trend is within policy."
    athlete = escape(detail.athlete_id)
    if detail.clearance_requested:
        action = (f"/coach/athlete/{athlete}#clearance-review", "Review clearance")
    elif detail.injured and detail.injury_pivots and plan is None:
        action = (f"/coach/athlete/{athlete}#injury-plan", "Choose injury plan")
    elif awaiting:
        action = ("/coach/whatsapp?tab=approval", f"Approve {awaiting} message{'s' if awaiting != 1 else ''}")
    else:
        action = (f"/coach/athlete/{athlete}#messages", "Message athlete")
    meta = [
        ("Readiness", f"{detail.readiness_score}/100" if detail.readiness_score is not None else "not checked in"),
        ("Last log", detail.last_activity or "never"),
        ("Phase", detail.phase),
    ]
    if plan is not None:
        meta.append(("Injury plan", plan.title))
    meta_html = "".join(f"<span>{escape(k)} <b>{escape(str(v))}</b></span>" for k, v in meta)
    return (
        '<section class="athlete-hero">'
        f'<span class="avatar lg ring-{_BUCKET_TONE.get(bucket, "fine")}" aria-hidden="true">'
        f'{escape(initials(detail.display_name))}</span>'
        '<div class="hero-copy">'
        f'<span class="badge {badge_cls}">{badge_text}</span>'
        f'<p class="hero-status">{escape(status)}</p>'
        f'<div class="hero-meta">{meta_html}</div></div>'
        f'<div class="hero-action"><a class="btn btn-primary" href="{action[0]}">{escape(action[1])}</a></div>'
        '</section>'
    )


def _injury_plan_panel(detail: AthleteDetail, *, coach: str, plan: InjuryPivot | None) -> str:
    """Four bounded plans, each with the message it sends. The coach picks one,
    checks or edits the wording, and approves both together."""
    if not detail.injured or detail.injury_entry_id is None or not detail.injury_pivots:
        return ""
    recommended = next((o for o in detail.injury_pivots if o.recommended), detail.injury_pivots[0])
    selected = plan or recommended
    first_name = detail.display_name.split()[0] if detail.name else "the athlete"
    options = []
    for option in detail.injury_pivots:
        badges = ""
        if option.recommended:
            badges += '<span class="badge badge-blue">Recommended</span>'
        if plan is not None and option.code == plan.code:
            badges += '<span class="badge tag-fine">Current plan ✓</span>'
        checked = " checked" if option.code == selected.code else ""
        options.append(
            f'<label class="plan-option{" selected" if checked else ""}">'
            f'<input type="radio" name="option_code" value="{escape(option.code)}"{checked} required '
            f'data-message="{escape(pivot_message(option, coach=coach), quote=True)}">'
            '<span class="plan-option-body">'
            f'<span class="plan-option-top"><strong>{escape(option.title)}</strong>{badges}</span>'
            f'<span class="plan-option-text">{escape(option.plan)}</span>'
            f'<span class="plan-option-why">{escape(option.rationale)}</span>'
            '</span></label>'
        )
    note = f" ({detail.injury_note})" if detail.injury_note else ""
    if plan is None:
        head = (
            '<h2>Choose an injury plan</h2>'
            f'<p>New injury{escape(note)}. Pick how training changes, check the message '
            f'{escape(first_name)} will receive, then approve.</p>'
        )
        state = '<span class="clearance-state">Decision needed</span>'
        submit = "Approve plan and schedule message"
    else:
        head = (
            f'<h2>Injury plan: {escape(plan.title)}</h2>'
            f'<p>Current injury{escape(note)}. You can switch plans; the new message replaces '
            "any that has not been sent yet.</p>"
        )
        state = '<span class="badge tag-fine">Plan approved</span>'
        submit = "Switch to the selected plan"
    return (
        f'<section id="injury-plan" class="injury-plan{" decided" if plan else ""}">'
        f'<div class="plan-head"><div>{head}</div>{state}</div>'
        f'<form id="injury-plan-form" method="post" action="/coach/athlete/{escape(detail.athlete_id)}/injury-plan">'
        f'<input type="hidden" name="injury_entry_id" value="{detail.injury_entry_id}">'
        f'<div class="plan-options" role="radiogroup" aria-label="Injury plans">{"".join(options)}</div>'
        f'<label class="plan-message">Message to {escape(first_name)}'
        f'<textarea name="body" maxlength="1400">{escape(pivot_message(selected, coach=coach))}</textarea></label>'
        '<div class="plan-actions"><small>Every plan keeps the injury flag open. Only a recorded '
        'independent clearance reopens normal programming.</small>'
        f'<button class="btn btn-primary" type="submit">{submit}</button></div>'
        '</form></section>'
        """<script>
(() => {
  const form = document.getElementById('injury-plan-form');
  if (!form) return;
  const box = form.querySelector('textarea[name=body]');
  let generated = box.value;
  form.querySelectorAll('input[name=option_code]').forEach((radio) => {
    radio.addEventListener('change', () => {
      if (box.value === generated) box.value = radio.dataset.message;
      generated = radio.dataset.message;
      form.querySelectorAll('.plan-option').forEach((option) => {
        option.classList.toggle('selected', option.querySelector('input').checked);
      });
    });
  });
})();
</script>"""
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
        '<div class="clearance-actions"><small>This records the coach, source, basis '
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


def _telegram_panel(
    detail: AthleteDetail, pairing_url: str | None, linked: bool, ready: bool
) -> str:
    if linked and ready:
        return (
            '<section class="channel-callout"><div><span class="channel-label">Athlete channel · Connected</span>'
            '<h2>Telegram connected</h2><p>This athlete receives approved messages '
            'through the permanent Telegram channel.</p></div><form method="post" action="/coach/athlete/'
            f'{escape(detail.athlete_id)}/telegram/unlink">'
            '<button class="danger" type="submit">Disconnect Telegram</button>'
            '</form></section>'
        )
    if pairing_url and ready:
        return (
            '<section class="channel-callout"><div><span class="channel-label">Athlete channel · Action needed</span>'
            '<h2>Connect this athlete to Telegram</h2>'
            '<p>Open the signed link, press Start in Telegram, and this private chat '
            'will be paired to the athlete profile.</p></div>'
            f'<a class="approve" href="{escape(pairing_url)}" '
            'target="_blank" rel="noopener">Connect Telegram</a></section>'
        )
    if pairing_url:
        return (
            '<section class="channel-callout"><div><span class="channel-label">Athlete channel · Reconnecting</span>'
            '<h2>Telegram webhook is not ready</h2><p>The bot settings exist, but '
            'Render has not confirmed its webhook. Check the deployment log before pairing.</p></div></section>'
        )
    return ""


def _facts(items: list[tuple[str, object]]) -> str:
    usable = [(label, value) for label, value in items if value not in (None, "", ())]
    if not usable:
        return '<p class="empty">Not configured yet.</p>'
    return '<dl class="facts">' + "".join(
        f'<div><dt>{escape(label)}</dt><dd>{escape(str(value))}</dd></div>'
        for label, value in usable
    ) + '</dl>'


def render_athlete(
    detail: AthleteDetail,
    *,
    coach: str,
    suggested: str,
    message: tuple[str, str] | None = None,
    telegram_pairing_url: str | None = None,
    telegram_linked: bool = False,
    telegram_ready: bool | None = None,
    conversation=(),
    scheduled=(),
    awaiting: int = 0,
    pending_count: int = 0,
    agent_panel: str = "",
    status_html: str = "",
    invite_html: str | None = None,
    advanced_html: str = "",
    welcome: bool = False,
) -> str:
    banner = ""
    if message:
        kind, text = message
        banner = f'<div class="msg {escape(kind)}">{escape(text)}</div>'
    if telegram_ready is None:
        telegram_ready = bool(telegram_linked or telegram_pairing_url)
    plan = _current_plan(detail)

    # --- Evidence: what happened and what the rules make of it ---
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
        + (f"<td>{a.current_weight:g} kg</td>" if a.current_weight is not None else "<td>—</td>")
        + f"<td>{a.sessions_considered}</td></tr>"
        for a in detail.assessments
    )
    verdict_table = (
        '<h3 class="sub-head">What the rules say</h3><table><thead><tr><th>Lift</th><th>Verdict</th>'
        "<th>Latest top set</th><th>Sessions</th></tr></thead>"
        f"<tbody>{verdicts}</tbody></table>"
        if verdicts else ""
    )
    charts = "".join(_chart(lift, pts) for lift, pts in progress_series(detail).items())
    charts = f'<h3 class="sub-head">Progress</h3>{charts}' if charts else ""
    rows = "".join(
        f"<tr><td>{escape(s.session_date)}</td><td>{escape(s.lift)}</td>"
        f"<td>{escape(s.summary)}</td></tr>"
        for s in detail.sessions[:15]
    )
    log = (
        '<h3 class="sub-head">Recent sessions</h3><table><thead><tr><th>Date</th><th>Lift</th>'
        f"<th>Set</th></tr></thead><tbody>{rows}</tbody></table>"
        if rows else '<h3 class="sub-head">Recent sessions</h3><p class="empty">Nothing logged yet.</p>'
    )
    evidence = (
        '<section id="evidence" class="profile-section"><h2>Evidence</h2>'
        f'<div class="grid">{tile_html}</div>{verdict_table}{charts}{log}</section>'
    )

    # --- Plan: the context the rules work from ---
    recovery = _facts([
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
    program_panel = '<div class="context-card"><h2>Programming</h2>' + _facts([
        ("Method", str(detail.program.get("methodology", "")).replace("_", " ")),
        ("Suggested starting method", detail.suggested_method),
        ("Why", detail.suggested_method_reason),
        ("Inputs still needed", ", ".join(detail.suggested_method_inputs)),
        ("Injury plan", plan.title if plan else None),
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
    schedule_panel = '<div class="context-card"><h2>Schedule & logistics</h2>' + _facts([
        ("Calendar", "Connected" if detail.calendar_connected else "Not connected"),
        ("Timezone", detail.schedule.get("timezone")),
        ("Morning check-in", detail.schedule.get("morning_checkin_time")),
        ("Usual training", detail.schedule.get("training_time")),
        ("Bedtime", detail.schedule.get("bedtime")),
    ]) + '</div>'
    supplement_text = "; ".join(detail.supplements) if detail.supplements else None
    nutrition_panel = '<div class="context-card"><h2>Nutrition & supplements</h2>' + _facts([
        ("Diet", detail.nutrition.get("diet_style")),
        ("Foods available", detail.nutrition.get("foods_available")),
        ("Allergies", detail.nutrition.get("allergies")),
        ("Meals", detail.nutrition.get("meals_per_day")),
        ("Protein target", f'{detail.nutrition.get("protein_target_g")} g' if detail.nutrition.get("protein_target_g") else None),
        ("Approved supplements", supplement_text),
    ]) + '</div>'
    plan_section = (
        '<section id="plan" class="profile-section"><h2>Plan</h2>'
        f'<div class="context-grid">{recovery_panel}{program_panel}{schedule_panel}{nutrition_panel}</div>'
        '</section>'
    )

    # --- Messages: the conversation, what is scheduled, and a note to send ---
    first_name = detail.display_name.split()[0] if detail.name else "the athlete"
    scheduled_html = "".join(
        f'<div><span>{escape(message_kind_label(str(row["message_kind"])))} · '
        f'{escape(str(row["local_date"]))}</span>{escape(str(row["body"]))}</div>'
        for row in scheduled
    )
    thread = (
        '<section class="context-card thread-card"><h2>Conversation</h2>'
        + (
            f'<div class="chat-stream">{conversation_bubbles(conversation)}</div>'
            if conversation else f'<p class="empty">No messages with {escape(first_name)} yet.</p>'
        )
        + (f'<div class="scheduled-mini"><h3>Scheduled to send</h3>{scheduled_html}</div>' if scheduled else "")
        + "</section>"
    )
    compose = (
        '<div class="context-card compose coach-draft">'
        '<div class="draft-state">Prepared · requires coach approval</div>'
        f'<h2>Message for {escape(first_name)}</h2>'
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

    channel = (
        invite_html if invite_html is not None
        else _telegram_panel(detail, telegram_pairing_url, telegram_linked, telegram_ready)
    )
    body = (
        # Straight after registration the invite comes first; otherwise the readiness answers do.
        f"{banner}{channel + status_html if welcome else status_html + channel}"
        f"{_hero(detail, plan=plan, awaiting=awaiting)}"
        '<nav class="section-nav" aria-label="Athlete sections">'
        '<a href="#agent-status">Status</a><a href="#agent-plan">Agent plan</a>'
        '<a href="#evidence">Evidence</a><a href="#plan">Profile</a>'
        '<a href="#messages">Messages</a></nav>'
        f"{_injury_clearance_panel(detail)}"
        f"{'' if detail.clearance_requested else _injury_plan_panel(detail, coach=coach, plan=plan)}"
        f"{agent_panel}"
        '<div class="profile-grid">'
        f'<div class="profile-main">{evidence}{plan_section}</div>'
        f'<aside id="messages" class="profile-side">{thread}{compose}</aside>'
        '</div>'
        f"{advanced_html}"
    )
    if status_html:
        from app.coach.onboarding_view import ONBOARDING_STYLE

        style = AGENT_STYLE + ONBOARDING_STYLE
    else:
        style = AGENT_STYLE if agent_panel else ""
    return coach_frame(
        body, active="athletes", coach=coach, title=detail.display_name,
        subtitle="Agent status, evidence, profile and conversation",
        today=detail.reviewed_on.isoformat(), back=("/coach/athletes", "Athletes"),
        athlete_id=detail.athlete_id, pending_count=pending_count,
        extra_style=style,
    )

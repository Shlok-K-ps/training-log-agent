"""Reply text, assembled in Python from a finished Assessment.

The model does not write these. It never sees them. Two athletes whose logs are
identical get byte-identical replies, and any line an athlete quotes back can be
traced to a branch in `rules.py` and a row in the database.
"""

from __future__ import annotations

from app.decision.rules import Assessment, Verdict
from app.decision.prescribe import Prescription
from app.decision.readiness import DailyCheckIn, ReadinessAssessment
from app.decision.sleep import NapPlan

PHASE_LABEL = {"cut": "cut", "maintain": "maintenance", "bulk": "bulk"}

INJURY_LINE = (
    "⚠️ You have an open injury flag, so I'm not suggesting loads. "
    "Log is still being kept. Talk to a physio before adding weight."
)

HEADLINE = {
    Verdict.NO_DATA: "No history yet",
    Verdict.BASELINE: "Baseline logged",
    Verdict.PROGRESSING: "Progressing",
    Verdict.REGRESSED: "Down on last session",
    Verdict.FLAT: "Flat — watching",
    Verdict.HOLDING: "Holding",
    Verdict.STALLED: "Stalled",
    Verdict.DELOAD: "Deload",
}

NEXT_STEP = {
    Verdict.PROGRESSING: "Keep the current progression.",
    Verdict.FLAT: "Nothing to change yet — log the next session.",
    Verdict.HOLDING: "Nothing to change. Holding load through a cut is the win.",
    Verdict.REGRESSED: "Logged. If that was planned, ignore me.",
    Verdict.STALLED: "Hold the weight and check sleep, food and bar speed before the next jump.",
}


def format_assessment(assessment: Assessment, athlete_name: str | None = None) -> str:
    """Render an Assessment as a WhatsApp message."""
    lift = assessment.lift
    who = f"{athlete_name}, " if athlete_name else ""
    lines: list[str] = [f"*{lift.title()} — {HEADLINE[assessment.verdict]}*"]

    if assessment.verdict is Verdict.NO_DATA:
        lines.append(f"{who}nothing logged for {lift} yet. Send me a session and I'll start tracking.")
        return "\n".join(lines)

    if assessment.current_weight is not None:
        detail = f"Latest top set: {assessment.current_weight:g} kg"
        if assessment.sessions_considered:
            detail += f"  ·  {assessment.sessions_considered} session"
            detail += "s" if assessment.sessions_considered != 1 else ""
            detail += " on record"
        lines.append(detail)

    lines.extend(assessment.reasons)

    if assessment.phase != "maintain":
        lines.append(f"Phase: {PHASE_LABEL.get(assessment.phase, assessment.phase)}.")

    if not assessment.actionable:
        lines.append("")
        lines.append(INJURY_LINE)
        if assessment.injury_note:
            lines.append(f"Flagged: {assessment.injury_note}")
        return "\n".join(lines)

    if assessment.verdict is Verdict.DELOAD and assessment.deload_target_kg is not None:
        lines.append("")
        lines.append(
            f"➡️ Next session: {assessment.deload_target_kg:g} kg, then build back up."
        )
    elif assessment.verdict in NEXT_STEP:
        lines.append("")
        lines.append(f"➡️ {NEXT_STEP[assessment.verdict]}")

    return "\n".join(lines)


def format_logged(
    lift: str,
    sets: int | None,
    reps: int | None,
    weight_kg: float | None,
    rpe: float | None,
    session_date: str,
) -> str:
    """One-line confirmation of what was parsed and stored, so mistakes are visible."""
    parts = [lift.title()]
    if sets and reps:
        parts.append(f"{sets}x{reps}")
    elif reps:
        parts.append(f"{reps} reps")
    if weight_kg is not None:
        parts.append(f"@ {weight_kg:g} kg")
    if rpe is not None:
        parts.append(f"RPE {rpe:g}")
    return f"✅ Logged: {' '.join(parts)}  ({session_date})"


def format_status(
    phase: str | None, injured: bool | None, injury_note: str | None
) -> str:
    bits: list[str] = []
    if phase:
        bits.append(f"Phase set to *{PHASE_LABEL.get(phase, phase)}*.")
    if injured is True:
        note = f" ({injury_note})" if injury_note else ""
        bits.append(
            f"Injury flag on{note}. I'll keep logging your sessions but I won't "
            "suggest loads until it's cleared. Please see a physio."
        )
    elif injured is False:
        bits.append("Injury flag cleared. Load suggestions are back on.")
    return "✅ " + " ".join(bits) if bits else "✅ Noted."


def format_checkin(checkin: DailyCheckIn, assessment: ReadinessAssessment) -> str:
    """Confirm exactly what was tracked and expose the deterministic readiness result."""
    tracked: list[str] = []
    if checkin.sleep_hours is not None:
        tracked.append(f"sleep {checkin.sleep_hours:g}h")
    if checkin.sleep_quality is not None:
        tracked.append(f"sleep quality {checkin.sleep_quality}/5")
    if checkin.readiness is not None:
        tracked.append(f"readiness {checkin.readiness}/10")
    if checkin.soreness is not None:
        tracked.append(f"soreness {checkin.soreness}/10")
    if checkin.stress is not None:
        tracked.append(f"stress {checkin.stress}/10")
    if checkin.bodyweight_kg is not None:
        tracked.append(f"bodyweight {checkin.bodyweight_kg:g} kg")
    if checkin.protein_g is not None:
        tracked.append(f"protein {checkin.protein_g:g} g")
    if checkin.calories is not None:
        tracked.append(f"calories {checkin.calories:g}")
    if checkin.nutrition_adherence is not None:
        tracked.append(f"nutrition adherence {checkin.nutrition_adherence}/10")
    lines = [f"✅ Check-in: {', '.join(tracked)}.", f"Readiness: {assessment.band.value} ({assessment.score}/100)."]
    lines.extend(assessment.reasons)
    if assessment.nutrition.protein_g_per_kg is not None:
        lines.extend(assessment.nutrition.notes)
    return "\n".join(lines)


def format_nap_plan(plan: NapPlan) -> str:
    if not plan.recommended:
        return "Nap: not scheduled. " + " ".join(plan.reasons)
    if plan.start_time is None:
        return "Nap: recommended, but no safe configured window is available. " + " ".join(
            plan.reasons
        )
    return (
        f"Nap: {plan.duration_minutes} minutes at {plan.start_time}. "
        "Reply after waking with the minutes slept and readiness 1–10. "
        "The workout will be recalculated, never raised above the original plan."
    )


def format_nap_logged(
    minutes: int, checkin: DailyCheckIn, assessment: ReadinessAssessment
) -> str:
    lines = [
        f"✅ Nap logged: {minutes} minutes.",
        f"Updated readiness: {assessment.band.value} ({assessment.score}/100).",
        "The original night's sleep remains part of today's readiness calculation.",
    ]
    lines.extend(assessment.reasons)
    return "\n".join(lines)


def format_prescription(prescription: Prescription) -> str:
    method = (
        prescription.methodology.value.replace("_", " ")
        if prescription.methodology is not None
        else "unselected"
    )
    lines = [f"*{prescription.lift.title()} — next session*", f"Method: {method}."]
    if prescription.session is not None:
        lines.append(f"Slot: {prescription.session.slot}.")
    if not prescription.actionable:
        lines.extend(prescription.reasons)
        if prescription.required_inputs:
            lines.append("Needed: " + ", ".join(prescription.required_inputs) + ".")
        return "\n".join(lines)
    work = ""
    if prescription.sets and prescription.reps:
        work = f"{prescription.sets}x{prescription.reps} @ "
    lines.append(f"➡️ {work}{prescription.adjusted_weight_kg:g} kg")
    if prescription.base_weight_kg != prescription.adjusted_weight_kg:
        lines.append(f"Base load {prescription.base_weight_kg:g} kg, reduced by same-day readiness.")
    lines.extend(prescription.reasons)
    return "\n".join(lines)

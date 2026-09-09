"""Deterministic next-session load suggestions.

The prescriber is deliberately narrower than the methodology catalog. Linear
and RPE-autoregulated loads can be derived from ordinary session history. The
other strategies stay gated until their method-specific inputs are captured;
the assistant must not pretend a random top set is a training max.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from typing import Sequence

from app.decision.readiness import DailyCheckIn, ReadinessAssessment, evaluate_readiness
from app.decision.rules import Assessment, Verdict, round_to_increment, to_session_points
from app.programming import Methodology, MethodologyChoice, SessionStructure, session_structure
from app.storage.db import Entry

LOWER_INCREMENT_KG = 5.0
UPPER_INCREMENT_KG = 2.5
HIGH_RPE_GATE = 9.0
UPPER_LIFTS = {"bench press", "overhead press", "row"}


@dataclass(frozen=True)
class Prescription:
    lift: str
    methodology: Methodology | None
    session: SessionStructure | None
    sets: int | None
    reps: int | None
    base_weight_kg: float | None
    adjusted_weight_kg: float | None
    readiness: ReadinessAssessment | None
    actionable: bool
    reasons: tuple[str, ...]
    required_inputs: tuple[str, ...] = ()


def prescribe_next(
    assessment: Assessment,
    entries: Sequence[Entry],
    choice: MethodologyChoice,
    *,
    session_number: int,
    today: date,
    checkin: DailyCheckIn | None = None,
    block_phase: str | None = None,
) -> Prescription:
    """Return the next load only when the history and method support one."""
    if choice.methodology is None or not choice.actionable or assessment.injured:
        return Prescription(
            lift=assessment.lift,
            methodology=choice.methodology,
            session=None,
            sets=None,
            reps=None,
            base_weight_kg=None,
            adjusted_weight_kg=None,
            readiness=None,
            actionable=False,
            reasons=("Programming is suppressed while an injury flag is open.",),
        )

    method = choice.methodology
    structure = session_structure(
        method,
        session_number,
        block_phase=block_phase,
        injured=assessment.injured,
    )
    points = to_session_points(entries, default_phase=assessment.phase)
    latest = points[-1] if points else None

    if not structure.actionable:
        return Prescription(
            lift=assessment.lift,
            methodology=method,
            session=structure,
            sets=latest.sets if latest else None,
            reps=latest.reps if latest else None,
            base_weight_kg=None,
            adjusted_weight_kg=None,
            readiness=None,
            actionable=False,
            reasons=(structure.main_work,),
            required_inputs=choice.required_inputs,
        )

    if method not in {Methodology.LINEAR_PROGRESSION, Methodology.AUTOREGULATED_RPE}:
        return Prescription(
            lift=assessment.lift,
            methodology=method,
            session=structure,
            sets=latest.sets if latest else None,
            reps=latest.reps if latest else None,
            base_weight_kg=None,
            adjusted_weight_kg=None,
            readiness=None,
            actionable=False,
            reasons=("Exact load is withheld until the method-specific inputs are verified.",),
            required_inputs=choice.required_inputs,
        )

    if latest is None or assessment.verdict is Verdict.NO_DATA:
        return Prescription(
            lift=assessment.lift,
            methodology=method,
            session=structure,
            sets=None,
            reps=None,
            base_weight_kg=None,
            adjusted_weight_kg=None,
            readiness=None,
            actionable=False,
            reasons=("A completed session is required before a load can be prescribed.",),
            required_inputs=choice.required_inputs,
        )

    reasons: list[str] = []
    increment = UPPER_INCREMENT_KG if assessment.lift in UPPER_LIFTS else LOWER_INCREMENT_KG
    base = latest.weight_kg
    if assessment.verdict is Verdict.DELOAD and assessment.deload_target_kg is not None:
        base = assessment.deload_target_kg
        reasons.append("The existing stall rule supplied the deload target.")
    elif assessment.verdict in {Verdict.BASELINE, Verdict.PROGRESSING}:
        if latest.rpe is not None and latest.rpe >= HIGH_RPE_GATE:
            reasons.append(f"RPE {latest.rpe:g} reached the high-effort gate, so load is held.")
        else:
            base = latest.weight_kg + increment
            reasons.append(f"Successful work allows the configured {increment:g} kg increment.")
    else:
        reasons.append("Load is held until the existing verdict returns to progressing.")

    readiness_result: ReadinessAssessment | None = None
    adjusted = base
    if checkin is not None:
        if checkin.checked_on == today.isoformat():
            readiness_result = evaluate_readiness(checkin)
            if not readiness_result.actionable:
                return Prescription(
                    lift=assessment.lift,
                    methodology=method,
                    session=structure,
                    sets=latest.sets,
                    reps=latest.reps,
                    base_weight_kg=round_to_increment(base),
                    adjusted_weight_kg=None,
                    readiness=readiness_result,
                    actionable=False,
                    reasons=tuple(reasons + list(readiness_result.reasons)),
                )
            adjusted = base * readiness_result.load_factor
            if readiness_result.load_factor < 1:
                reasons.append(
                    f"Same-day readiness applies a {readiness_result.load_factor:.3f} load factor."
                )
        else:
            reasons.append("A stale check-in was ignored; only same-day readiness may change load.")

    return Prescription(
        lift=assessment.lift,
        methodology=method,
        session=structure,
        sets=latest.sets,
        reps=latest.reps,
        base_weight_kg=round_to_increment(base),
        adjusted_weight_kg=round_to_increment(adjusted),
        readiness=readiness_result,
        actionable=True,
        reasons=tuple(reasons),
    )

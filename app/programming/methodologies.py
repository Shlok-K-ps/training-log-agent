"""Deterministic programming-method selection and session structure.

This module is policy, not evidence. The five strategies are represented by
their load-selection and periodisation ideas; they are not copied templates.
The language model may parse an athlete's answers, but it must never choose a
method or invent a working weight.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum


class Methodology(str, Enum):
    LINEAR_PROGRESSION = "linear_progression"
    FIVE_THREE_ONE = "five_three_one"
    BLOCK_PERIODIZATION = "block_periodization"
    AUTOREGULATED_RPE = "autoregulated_rpe"
    CONJUGATE = "conjugate"


class Experience(str, Enum):
    NOVICE = "novice"
    INTERMEDIATE = "intermediate"
    ADVANCED = "advanced"


@dataclass(frozen=True)
class MethodologySpec:
    label: str
    cadence: str
    best_fit: str
    required_inputs: tuple[str, ...]
    structure: tuple[str, ...]
    source_url: str


METHODOLOGIES: dict[Methodology, MethodologySpec] = {
    Methodology.LINEAR_PROGRESSION: MethodologySpec(
        label="Novice linear progression",
        cadence="Increase the load after each successful exposure.",
        best_fit="Novices who can still recover and improve between sessions.",
        required_inputs=("last successful working load", "completed reps", "load increment"),
        structure=("full-body A/B sessions", "repeat or reset after failed work"),
        source_url="https://startingstrength.com/get-started/programs",
    ),
    Methodology.FIVE_THREE_ONE: MethodologySpec(
        label="5/3/1-style training-max progression",
        cadence="Multi-week waves based on a conservative training max.",
        best_fit="Lifters who want simple, submaximal, long-horizon progression.",
        required_inputs=("coach-approved training max", "cycle week", "main lift"),
        structure=("percentage-based main work", "supplemental work", "assistance work"),
        source_url="https://www.jimwendler.com/blogs/jimwendler-com/101065094-5-3-1-for-a-beginner",
    ),
    Methodology.BLOCK_PERIODIZATION: MethodologySpec(
        label="Block periodization",
        cadence="Move from accumulation to intensification, realization, and deload.",
        best_fit="Intermediate or advanced lifters preparing for a dated competition.",
        required_inputs=("meet date", "current block", "verified strength baseline"),
        structure=("accumulation", "intensification", "realization", "deload"),
        source_url="https://www.jtsstrength.com/the-terms-of-the-deal/",
    ),
    Methodology.AUTOREGULATED_RPE: MethodologySpec(
        label="RPE-autoregulated programming",
        cadence="Adjust the planned load from the athlete's observed performance that day.",
        best_fit="Experienced lifters who log RPE consistently and reliably.",
        required_inputs=("target reps", "target RPE", "recent RPE history"),
        structure=("RPE-capped top work", "fatigue-managed back-off work"),
        source_url="https://store.reactivetrainingsystems.com/products/rts-manual-digital",
    ),
    Methodology.CONJUGATE: MethodologySpec(
        label="Conjugate",
        cadence="Rotate max-, dynamic-, and repeated-effort exposures each week.",
        best_fit="Advanced four-day lifters with a coached exercise-variation library.",
        required_inputs=("day slot", "approved lift variations", "available equipment"),
        structure=("max effort", "dynamic effort", "repeated effort"),
        source_url="https://www.westside-barbell.com/pages/conjugate-method",
    ),
}


@dataclass(frozen=True)
class ProgrammingProfile:
    """Only declared or measured inputs; no model-inferred training facts."""

    experience: Experience
    days_per_week: int
    weeks_to_meet: int | None = None
    rpe_logging_ratio: float = 0.0
    has_specialty_equipment: bool = False
    preferred: Methodology | None = None
    injured: bool = False

    def __post_init__(self) -> None:
        if not 1 <= self.days_per_week <= 7:
            raise ValueError("days_per_week must be between 1 and 7")
        if self.weeks_to_meet is not None and self.weeks_to_meet < 0:
            raise ValueError("weeks_to_meet cannot be negative")
        if not 0.0 <= self.rpe_logging_ratio <= 1.0:
            raise ValueError("rpe_logging_ratio must be between 0 and 1")


@dataclass(frozen=True)
class MethodologyChoice:
    methodology: Methodology | None
    reasons: tuple[str, ...]
    required_inputs: tuple[str, ...] = ()
    actionable: bool = True


def choose_methodology(profile: ProgrammingProfile) -> MethodologyChoice:
    """Choose one strategy using visible, ordered policy rules."""
    if profile.injured:
        return MethodologyChoice(
            methodology=None,
            reasons=("Programming is suppressed while an injury flag is open.",),
            actionable=False,
        )

    if profile.preferred is not None:
        chosen = profile.preferred
        reason = "Athlete or coach selected this strategy explicitly."
    elif profile.experience is Experience.NOVICE:
        chosen = Methodology.LINEAR_PROGRESSION
        reason = "Novices who recover between sessions can use session-to-session progression."
    elif profile.weeks_to_meet is not None and profile.weeks_to_meet <= 16:
        chosen = Methodology.BLOCK_PERIODIZATION
        reason = "A dated meet inside 16 weeks needs an accumulation-to-realization path."
    elif (
        profile.experience is Experience.ADVANCED
        and profile.days_per_week >= 4
        and profile.has_specialty_equipment
    ):
        chosen = Methodology.CONJUGATE
        reason = "Advanced four-day training with specialty equipment supports planned variation."
    elif profile.rpe_logging_ratio >= 0.6:
        chosen = Methodology.AUTOREGULATED_RPE
        reason = "At least 60% of recent work has RPE data, so effort-based adjustment is auditable."
    else:
        chosen = Methodology.FIVE_THREE_ONE
        reason = "A conservative training-max wave is the fallback when no narrower fit is proven."

    spec = METHODOLOGIES[chosen]
    return MethodologyChoice(
        methodology=chosen,
        reasons=(reason,),
        required_inputs=spec.required_inputs,
    )


@dataclass(frozen=True)
class SessionStructure:
    methodology: Methodology
    slot: str
    main_work: str
    progression_rule: str
    required_inputs: tuple[str, ...]
    actionable: bool = True


def session_structure(
    methodology: Methodology,
    session_number: int,
    *,
    block_phase: str | None = None,
    injured: bool = False,
) -> SessionStructure:
    """Return the shape of the next session, never an invented working weight."""
    if session_number < 1:
        raise ValueError("session_number must be at least 1")

    required = METHODOLOGIES[methodology].required_inputs
    if injured:
        return SessionStructure(
            methodology=methodology,
            slot="suppressed",
            main_work="No load-bearing session is generated while the injury flag is open.",
            progression_rule="Keep logging; resume programming only after the flag is cleared.",
            required_inputs=required,
            actionable=False,
        )

    if methodology is Methodology.LINEAR_PROGRESSION:
        slot = ("A", "B")[(session_number - 1) % 2]
        return SessionStructure(
            methodology=methodology,
            slot=f"full-body {slot}",
            main_work="Primary competition-pattern lifts with a small number of work sets.",
            progression_rule="Add the configured increment only after every prescribed rep succeeds.",
            required_inputs=required,
        )

    if methodology is Methodology.FIVE_THREE_ONE:
        week = ((session_number - 1) // 4) % 4 + 1
        lift = ("squat", "bench press", "deadlift", "overhead press")[(session_number - 1) % 4]
        return SessionStructure(
            methodology=methodology,
            slot=f"cycle week {week} · {lift}",
            main_work="Three main-work sets calculated from the approved training max.",
            progression_rule="Advance the training max only at the cycle boundary.",
            required_inputs=required,
        )

    if methodology is Methodology.BLOCK_PERIODIZATION:
        phases = {"accumulation", "intensification", "realization", "deload"}
        if block_phase not in phases:
            return SessionStructure(
                methodology=methodology,
                slot="block phase required",
                main_work="No session is generated until the current block is declared.",
                progression_rule="Select accumulation, intensification, realization, or deload.",
                required_inputs=required,
                actionable=False,
            )
        return SessionStructure(
            methodology=methodology,
            slot=block_phase,
            main_work=f"Work matching the {block_phase} objective for the competition lifts.",
            progression_rule="Progress only the volume or intensity variable assigned to this block.",
            required_inputs=required,
        )

    if methodology is Methodology.AUTOREGULATED_RPE:
        return SessionStructure(
            methodology=methodology,
            slot="readiness-calibrated",
            main_work="RPE-capped top work followed by fatigue-managed back-off work.",
            progression_rule="Adjust load from observed RPE; never translate vague feelings into a number.",
            required_inputs=required,
        )

    slots = (
        "max-effort lower",
        "max-effort upper",
        "dynamic-effort lower",
        "dynamic-effort upper",
    )
    slot = slots[(session_number - 1) % len(slots)]
    return SessionStructure(
        methodology=methodology,
        slot=slot,
        main_work="Use a coach-approved variation, then repeated-effort work for named weak points.",
        progression_rule="Rotate variations deliberately; do not substitute random exercise novelty.",
        required_inputs=required,
    )

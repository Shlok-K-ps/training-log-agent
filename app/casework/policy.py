"""Fixed rules for one training day: what counts as routine and how a session may change.

Nothing here calls a model. The agent may keep or reduce a session the coach
approved; it can never add a set, a rep or effort, and it never names a load.
Anything these rules cannot settle becomes a decision for the coach.
"""

from __future__ import annotations

from dataclasses import dataclass, fields, replace
from datetime import time

from app.decision.injury_pivot import injury_pivot_options
from app.decision.readiness import (
    DailyCheckIn,
    ReadinessAssessment,
    ReadinessBand,
    evaluate_readiness,
)

DEFAULT_CHECKIN_TIME = "07:30"
DEFAULT_TRAINING_TIME = "18:00"
# No new training day is opened this late in the athlete's local evening.
LAST_CASE_OPENING = time(21, 0)
MAX_CHECKIN_FOLLOW_UPS = 2
# Consecutive training days without a check-in before the coach is told.
SILENT_STREAK_DAYS = 2
RPE_FLOOR = 5.0


@dataclass(frozen=True)
class Timing:
    """Minutes between the agent's steps.

    `AGENT_TIME_SCALE` shrinks every interval proportionally so a live
    demonstration can show a whole day in minutes; the order never changes.
    """

    first_follow_up: float = 90
    second_follow_up: float = 120
    checkin_window: float = 360
    outcome_question_after_training: float = 150
    outcome_reminder: float = 180
    outcome_escalation: float = 720

    def scaled(self, scale: float) -> "Timing":
        factor = max(0.001, float(scale))
        return Timing(**{f.name: getattr(self, f.name) * factor for f in fields(self)})


@dataclass(frozen=True)
class PlannedLift:
    """One lift in a coach-authored session: sets, reps and a target RPE, never a load."""

    lift: str
    sets: int
    reps: int
    rpe: float

    def describe(self) -> str:
        return f"{self.lift.title()} {self.sets}×{self.reps} @ RPE {self.rpe:g}"

    def as_dict(self) -> dict[str, object]:
        return {"lift": self.lift, "sets": self.sets, "reps": self.reps, "rpe": self.rpe}

    @classmethod
    def from_dict(cls, raw: dict[str, object]) -> "PlannedLift":
        return cls(
            lift=str(raw["lift"]), sets=int(raw["sets"]), reps=int(raw["reps"]),
            rpe=float(raw["rpe"]),
        )


def _lower_rpe(rpe: float, amount: float) -> float:
    reduced = round((rpe - amount) * 2) / 2
    return min(rpe, max(RPE_FLOOR, reduced))


def never_increases(plan: tuple[PlannedLift, ...], session: tuple[PlannedLift, ...]) -> bool:
    """True when every lift keeps or reduces the approved sets, reps and effort."""
    approved = {lift.lift: lift for lift in plan}
    return len(session) <= len(plan) and all(
        item.lift in approved
        and item.sets <= approved[item.lift].sets
        and item.reps <= approved[item.lift].reps
        and item.rpe <= approved[item.lift].rpe
        for item in session
    )


def adjust_for_band(
    plan: tuple[PlannedLift, ...], band: ReadinessBand
) -> tuple[tuple[PlannedLift, ...], tuple[str, ...]]:
    """The approved session after same-day readiness. Hold or reduce only."""
    if band is ReadinessBand.GREEN:
        session = plan
        changes = ("Readiness is green, so the approved session stands unchanged.",)
    elif band is ReadinessBand.YELLOW:
        session = tuple(replace(item, rpe=_lower_rpe(item.rpe, 0.5)) for item in plan)
        changes = ("Readiness is yellow, so each RPE target drops by 0.5.",)
    elif band is ReadinessBand.ORANGE:
        session = tuple(
            replace(item, sets=max(1, item.sets - 1), rpe=_lower_rpe(item.rpe, 1.0))
            for item in plan
        )
        changes = ("Readiness is orange, so each lift loses one set and its RPE target drops by 1.",)
    else:
        session = tuple(
            replace(
                item,
                sets=max(1, (item.sets + 1) // 2),
                rpe=min(item.rpe, 6.0, _lower_rpe(item.rpe, 1.5)),
            )
            for item in plan
        )
        changes = ("Readiness is red. A half-volume session capped at RPE 6 is offered to the coach only.",)
    if not never_increases(plan, session):
        raise ValueError("a readiness adjustment tried to exceed the approved session")
    return session, changes


def missing_fields(checkin: DailyCheckIn) -> tuple[str, ...]:
    """The two values a routine decision needs. Everything else is optional."""
    missing = []
    if checkin.sleep_hours is None:
        missing.append("hours slept")
    if checkin.readiness is None:
        missing.append("readiness 1–10")
    return tuple(missing)


@dataclass(frozen=True)
class Triage:
    routine: bool
    readiness: ReadinessAssessment
    session: tuple[PlannedLift, ...]
    changes: tuple[str, ...]
    escalation: str | None


def triage(
    plan: tuple[PlannedLift, ...],
    checkin: DailyCheckIn,
    *,
    injured: bool,
    autopilot: bool,
) -> Triage:
    """Decide whether today is routine. The first failing condition is the escalation."""
    readiness = evaluate_readiness(checkin)
    session, changes = adjust_for_band(plan, readiness.band)
    if injured:
        escalation: str | None = "injury_open"
    elif not readiness.actionable:
        escalation = "readiness_red"
    elif not autopilot:
        escalation = "autopilot_off"
    else:
        escalation = None
    return Triage(
        routine=escalation is None, readiness=readiness, session=session,
        changes=changes, escalation=escalation,
    )


ESCALATION_TITLES = {
    "injury_open": "Injury reported",
    "readiness_red": "Recovery in the red",
    "autopilot_off": "Session waiting for approval",
    "no_session_report": "No session report",
    "silent_streak": "Silent on consecutive training days",
    "delivery_failed": "Message could not be delivered",
}


def coach_options(code: str, *, injury_note: str | None = None) -> tuple[tuple[str, str], ...]:
    """The decisions a coach can take on an escalation, as (code, label)."""
    if code == "injury_open":
        pivots = tuple((option.code, option.title) for option in injury_pivot_options(injury_note))
        return pivots + (("rest", "Rest today"),)
    if code == "readiness_red":
        return (("light", "Send the light session"), ("rest", "Rest today"))
    if code == "autopilot_off":
        return (("send", "Send the adjusted session"), ("rest", "Rest today"))
    if code == "no_session_report":
        return (("done", "Mark as trained"), ("missed", "Mark as missed"))
    return (("ack", "Acknowledge and close"),)

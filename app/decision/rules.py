"""The rules. Deterministic, inspectable, testable.

The language model is not consulted here and must never be. Parsing messy human
text is a judgement call, so a model does it. Telling an athlete to strip 15% off
their squat is not a judgement call — it is a rule the coach signed off on, and it
has to produce the same answer today that it produced last week from the same log.

The rules, in one place:

    weight up vs. last session                      -> PROGRESSING
    weight down vs. last session                    -> REGRESSED (backoff, not a stall)
    flat for 3+ sessions                            -> STALLED
    flat for 2+ sessions with RPE climbing          -> STALLED (earlier trigger)
    flat during a cut                               -> HOLDING (not a stall)
    second stall episode on the same lift           -> DELOAD to 85%
    an open injury flag                             -> no progression advice at all
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Sequence

from app.storage.db import Entry

# --- Tunable constants. Changing one of these changes coaching policy, so they
# --- live together, named, at the top of the file rather than inline as magic numbers.

STALL_FLAT_SESSIONS = 3
"""Sessions at the same top weight before we call it a stall."""

STALL_FLAT_WITH_RPE = 2
"""Sessions at the same top weight, with RPE climbing, before we call it a stall.

Same weight for the same reps at RPE 7 then 8 then 9 is not a plateau, it is a
slide. The bar says nothing changed; the athlete says it got harder. Believe the
athlete, and call the stall a session earlier than the numbers alone would.
"""

DELOAD_STALL_EPISODES = 2
"""Distinct stall episodes on one lift before prescribing a deload."""

DELOAD_FACTOR = 0.85
"""Deload target as a fraction of the current top weight."""

BAR_INCREMENT = 2.5
"""Smallest practical plate jump, in kg. Prescriptions round to this."""

RPE_CLIMB_TOLERANCE = 0.0
"""How much RPE must rise across a flat run to count as climbing."""


class Verdict(str, Enum):
    NO_DATA = "no_data"
    BASELINE = "baseline"
    PROGRESSING = "progressing"
    REGRESSED = "regressed"
    FLAT = "flat"
    HOLDING = "holding"
    STALLED = "stalled"
    DELOAD = "deload"


@dataclass(frozen=True)
class SessionPoint:
    """One session's top set for one lift — the unit the rules reason over."""

    session_date: str
    weight_kg: float
    rpe: float | None = None
    sets: int | None = None
    reps: int | None = None
    phase: str = "maintain"


@dataclass(frozen=True)
class Assessment:
    """The engine's output. Everything the reply needs, and nothing generated."""

    athlete_id: str
    lift: str
    verdict: Verdict
    sessions_considered: int
    current_weight: float | None = None
    previous_weight: float | None = None
    flat_sessions: int = 0
    rpe_trend: str = "unknown"  # "climbing" | "steady" | "easing" | "unknown"
    stall_episodes: int = 0
    phase: str = "maintain"
    injured: bool = False
    injury_note: str | None = None
    deload_target_kg: float | None = None
    reasons: list[str] = field(default_factory=list)

    @property
    def actionable(self) -> bool:
        """False when an injury flag is open — we track, we do not prescribe."""
        return not self.injured


def round_to_increment(weight: float, increment: float = BAR_INCREMENT) -> float:
    """Round a prescription down-to-nearest loadable weight."""
    return round(round(weight / increment) * increment, 2)


def to_session_points(
    entries: Sequence[Entry], default_phase: str = "maintain"
) -> list[SessionPoint]:
    """Collapse raw rows into one point per session date.

    An athlete may log several sets for the same lift in one session. The series
    the rules care about is the *top set*: the heaviest weight moved that day. RPE
    is taken from the heaviest set, since that is the one that reports effort.
    Phase carries forward from the last session that declared one.
    """
    by_date: dict[str, list[Entry]] = {}
    for entry in entries:
        if entry.kind != "set" or entry.weight_kg is None:
            continue
        by_date.setdefault(entry.session_date, []).append(entry)

    points: list[SessionPoint] = []
    phase = default_phase
    for session_date in sorted(by_date):
        rows = by_date[session_date]
        for row in rows:
            if row.phase:
                phase = row.phase
        top = max(rows, key=lambda r: (r.weight_kg or 0.0, r.rpe or 0.0))
        candidates = [r for r in rows if r.weight_kg == top.weight_kg]
        rpes = [r.rpe for r in candidates if r.rpe is not None]
        points.append(
            SessionPoint(
                session_date=session_date,
                weight_kg=float(top.weight_kg or 0.0),
                rpe=max(rpes) if rpes else None,
                sets=top.sets,
                reps=top.reps,
                phase=phase,
            )
        )
    return points


def _trailing_flat_run(points: Sequence[SessionPoint]) -> list[SessionPoint]:
    """The most recent consecutive sessions sharing the latest top weight."""
    if not points:
        return []
    target = points[-1].weight_kg
    run: list[SessionPoint] = []
    for point in reversed(points):
        if point.weight_kg != target:
            break
        run.append(point)
    return list(reversed(run))


def _rpe_trend(run: Sequence[SessionPoint]) -> str:
    """Direction of effort across a flat run of sessions."""
    rpes = [p.rpe for p in run if p.rpe is not None]
    if len(rpes) < 2:
        return "unknown"
    delta = rpes[-1] - rpes[0]
    if delta > RPE_CLIMB_TOLERANCE:
        return "climbing"
    if delta < -RPE_CLIMB_TOLERANCE:
        return "easing"
    return "steady"


def _run_is_stall(run: Sequence[SessionPoint]) -> bool:
    """Would this flat run, on its own, be called a stall?

    A run during a cut never is: holding a number while losing bodyweight is the
    goal of the block, not a failure of it. Same data, different meaning.
    """
    if not run:
        return False
    if run[-1].phase == "cut":
        return False
    if len(run) >= STALL_FLAT_SESSIONS:
        return True
    return len(run) >= STALL_FLAT_WITH_RPE and _rpe_trend(run) == "climbing"


def _flat_runs(points: Sequence[SessionPoint]) -> list[list[SessionPoint]]:
    """Split the series into maximal runs of equal top weight."""
    runs: list[list[SessionPoint]] = []
    for point in points:
        if runs and runs[-1][-1].weight_kg == point.weight_kg:
            runs[-1].append(point)
        else:
            runs.append([point])
    return runs


def count_stall_episodes(points: Sequence[SessionPoint]) -> int:
    """How many distinct stalls this lift has been through, including the current one.

    An episode is a maximal flat run that meets the stall criteria. Four sessions
    at the same weight is one stall, not two — otherwise an athlete who simply
    stopped logging heavier would be deloaded on a technicality.
    """
    return sum(1 for run in _flat_runs(points) if _run_is_stall(run))


def evaluate(
    athlete_id: str,
    lift: str,
    entries: Sequence[Entry],
    *,
    phase: str = "maintain",
    injured: bool = False,
    injury_note: str | None = None,
) -> Assessment:
    """Turn one athlete's history of one lift into a verdict.

    Pure: same arguments in, same Assessment out, no I/O, no clock, no model.
    """
    points = to_session_points(entries, default_phase=phase)
    current_phase = points[-1].phase if points else phase

    base = dict(
        athlete_id=athlete_id,
        lift=lift,
        phase=current_phase,
        injured=injured,
        injury_note=injury_note,
        sessions_considered=len(points),
    )

    if not points:
        return Assessment(verdict=Verdict.NO_DATA, reasons=["Nothing logged for this lift yet."], **base)

    current = points[-1]

    if len(points) == 1:
        return Assessment(
            verdict=Verdict.BASELINE,
            current_weight=current.weight_kg,
            reasons=["First session on record — this is the baseline to measure against."],
            **base,
        )

    previous = points[-2]
    run = _trailing_flat_run(points)
    trend = _rpe_trend(run)

    common = dict(
        current_weight=current.weight_kg,
        previous_weight=previous.weight_kg,
        flat_sessions=len(run),
        rpe_trend=trend,
        **base,
    )

    if current.weight_kg > previous.weight_kg:
        gain = round(current.weight_kg - previous.weight_kg, 2)
        return Assessment(
            verdict=Verdict.PROGRESSING,
            reasons=[f"Top set up {gain:g} kg on the last session."],
            **common,
        )

    if current.weight_kg < previous.weight_kg:
        drop = round(previous.weight_kg - current.weight_kg, 2)
        return Assessment(
            verdict=Verdict.REGRESSED,
            reasons=[
                f"Top set down {drop:g} kg on the last session — logged as a backoff, not a stall."
            ],
            **common,
        )

    # Flat from here on.
    if current_phase == "cut":
        return Assessment(
            verdict=Verdict.HOLDING,
            reasons=[
                f"Flat at {current.weight_kg:g} kg for {len(run)} sessions, but the phase is a cut — "
                "holding strength while cutting is the goal, not a stall."
            ],
            **common,
        )

    if not _run_is_stall(run):
        return Assessment(
            verdict=Verdict.FLAT,
            reasons=[
                f"Flat at {current.weight_kg:g} kg for {len(run)} sessions — under the "
                f"{STALL_FLAT_SESSIONS}-session threshold, and RPE is {trend}."
            ],
            **common,
        )

    episodes = count_stall_episodes(points)
    reasons = []
    if len(run) >= STALL_FLAT_SESSIONS:
        reasons.append(f"Flat at {current.weight_kg:g} kg for {len(run)} sessions.")
    else:
        reasons.append(
            f"Flat at {current.weight_kg:g} kg for {len(run)} sessions with RPE climbing "
            "— same bar, more effort."
        )

    if episodes >= DELOAD_STALL_EPISODES:
        target = round_to_increment(current.weight_kg * DELOAD_FACTOR)
        reasons.append(
            f"Stall number {episodes} on this lift — the rule is a deload at "
            f"{int(DELOAD_FACTOR * 100)}%."
        )
        return Assessment(
            verdict=Verdict.DELOAD,
            stall_episodes=episodes,
            deload_target_kg=target,
            reasons=reasons,
            **common,
        )

    return Assessment(
        verdict=Verdict.STALLED,
        stall_episodes=episodes,
        reasons=reasons,
        **common,
    )

"""One bounded, explainable adaptation: when the morning check-in is sent.

Storing history is memory; learning means behaviour changes because of
measured outcomes. The agent measures how long each athlete takes to answer the
check-in. When they consistently answer late, the next check-in moves later in
small, capped steps. It never moves earlier than the coach's own time, never
closer than three hours before training, and it never touches safety,
readiness or training rules.
"""

from __future__ import annotations

import statistics
from dataclasses import dataclass
from datetime import datetime

from app.casework import store

MIN_SAMPLES = 4
WINDOW = 7
TRIGGER_MEDIAN_MINUTES = 60
MAX_STEP_MINUTES = 30
MAX_LATER_THAN_BASE_MINUTES = 90
MIN_GAP_BEFORE_TRAINING_MINUTES = 180
RULE = (
    "Move the check-in later only when the median reply delay is at least 60 minutes "
    "over at least 4 training days; at most 30 minutes per change, at most 90 minutes "
    "after the coach's time, and never within 3 hours of training."
)


def _minutes(clock: str) -> int:
    hour, minute = (int(piece) for piece in clock.split(":"))
    return hour * 60 + minute


def _clock(minutes: int) -> str:
    return f"{minutes // 60:02d}:{minutes % 60:02d}"


@dataclass(frozen=True)
class Proposal:
    new_time: str
    step_minutes: int
    ceiling: str
    median_minutes: float


def propose(samples: list[float], *, current: str, base: str, training: str) -> Proposal | None:
    """A later check-in time justified by the samples, or None."""
    if len(samples) < MIN_SAMPLES:
        return None
    median = float(statistics.median(samples))
    if median < TRIGGER_MEDIAN_MINUTES:
        return None
    step = min(MAX_STEP_MINUTES, int((median - 30) // 15) * 15)
    ceiling = min(
        _minutes(base) + MAX_LATER_THAN_BASE_MINUTES,
        _minutes(training) - MIN_GAP_BEFORE_TRAINING_MINUTES,
    )
    new = min(_minutes(current) + step, ceiling)
    if step <= 0 or new <= _minutes(current):
        return None
    return Proposal(_clock(new), new - _minutes(current), _clock(ceiling), median)


def maybe_adapt_checkin_time(
    conn, athlete_id: str, *, now: datetime, base_time: str, training_time: str,
    first_name: str,
) -> dict[str, object] | None:
    """Apply and record one adaptation if the evidence supports it."""
    current = store.agent_settings(conn, athlete_id)["checkin_time"] or base_time
    last = store.latest_adaptation(conn, athlete_id, "checkin_time")
    samples = store.checkin_latencies(
        conn, athlete_id, checkin_time=current,
        since=str(last["created_at"]) if last is not None else None, limit=WINDOW,
    )
    proposal = propose(samples, current=current, base=base_time, training=training_time)
    if proposal is None:
        return None
    explanation = (
        f"{first_name} answered the {current} check-in a median {proposal.median_minutes:.0f} "
        f"minutes after it was sent over the last {len(samples)} training days "
        f"({min(samples):.0f}–{max(samples):.0f} min). The check-in moves "
        f"{proposal.step_minutes} minutes later to {proposal.new_time}. It will never be "
        f"earlier than the coach's {base_time} or later than {proposal.ceiling}."
    )
    evidence = {
        "samples_minutes": [round(sample) for sample in samples],
        "median_minutes": round(proposal.median_minutes),
        "previous_time": current,
        "coach_time": base_time,
        "ceiling": proposal.ceiling,
        "training_time": training_time,
        "rule": RULE,
    }
    store.set_checkin_time(
        conn, athlete_id, proposal.new_time, updated_by="Power AI adaptation", now=now
    )
    store.record_adaptation(
        conn, athlete_id=athlete_id, parameter="checkin_time", old_value=current,
        new_value=proposal.new_time, evidence=evidence, explanation=explanation, now=now,
    )
    return {
        "parameter": "checkin_time", "old": current, "new": proposal.new_time,
        "explanation": explanation, "evidence": evidence,
    }

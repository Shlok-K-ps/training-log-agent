"""Transparent goal pacing for coach analytics."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date
import sqlite3

from app.storage import db


@dataclass(frozen=True)
class GoalPace:
    athlete_id: str
    athlete_name: str
    lift: str
    start_kg: float
    current_kg: float
    expected_kg: float
    target_kg: float
    target_date: str
    status: str


def _profile_start(profile: dict[str, object], lift: str) -> float | None:
    key = {"squat": "squat_1rm_kg", "bench press": "bench_1rm_kg", "deadlift": "deadlift_1rm_kg"}.get(lift)
    value = profile.get(key or "")
    return float(value) if value is not None else None


def _estimated_current(
    conn: sqlite3.Connection, athlete_id: str, lift: str, *, since: str
) -> float | None:
    values = []
    for entry in db.session_history(conn, athlete_id, lift):
        if entry.weight_kg is None or entry.session_date < since:
            continue
        reps = min(12, max(1, int(entry.reps or 1)))
        values.append(float(entry.weight_kg) * (1 + reps / 30))
    return max(values) if values else None


def goal_pace(
    conn: sqlite3.Connection, athlete_id: str, *, today: date
) -> GoalPace | None:
    row = db.latest_athlete_profile(conn, athlete_id)
    if row is None:
        return None
    profile = dict(row)
    lift = str(profile.get("goal_lift") or "")
    target = profile.get("goal_target_kg")
    target_date = profile.get("goal_target_date")
    start_date = profile.get("goal_start_date")
    start = _profile_start(profile, lift)
    if not (lift and target is not None and target_date and start_date and start is not None):
        return None
    try:
        began = date.fromisoformat(str(start_date))
        deadline = date.fromisoformat(str(target_date))
    except ValueError:
        return None
    duration = (deadline - began).days
    if duration <= 0 or float(target) <= 0:
        return None
    elapsed = min(1.0, max(0.0, (today - began).days / duration))
    expected = start + (float(target) - start) * elapsed
    observed = _estimated_current(conn, athlete_id, lift, since=str(start_date))
    current = max(start, observed or start)
    tolerance = max(2.5, abs(float(target) - start) * 0.08)
    status = "on_track"
    if current > expected + tolerance:
        status = "ahead"
    elif current < expected - tolerance:
        status = "lagging"
    return GoalPace(
        athlete_id=athlete_id,
        athlete_name=db.athlete_name(conn, athlete_id) or athlete_id,
        lift=lift,
        start_kg=start,
        current_kg=round(current, 1),
        expected_kg=round(expected, 1),
        target_kg=float(target),
        target_date=str(target_date),
        status=status,
    )


def squad_goal_paces(conn: sqlite3.Connection, *, today: date) -> tuple[GoalPace, ...]:
    paces = [goal_pace(conn, athlete_id, today=today) for athlete_id in db.list_athletes(conn)]
    order = {"lagging": 0, "on_track": 1, "ahead": 2}
    return tuple(sorted((pace for pace in paces if pace), key=lambda pace: (order[pace.status], pace.athlete_name.casefold())))

from __future__ import annotations

from datetime import date, timedelta
from typing import Any

import pytest

from app.storage import db


@pytest.fixture()
def conn():
    connection = db.connect(":memory:")
    db.init_db(connection)
    yield connection
    connection.close()


@pytest.fixture()
def today() -> date:
    return date(2026, 9, 8)


def entry(
    day: str,
    weight: float,
    rpe: float | None = None,
    *,
    lift: str = "squat",
    phase: str | None = None,
    athlete_id: str = "+911",
    sets: int | None = 3,
    reps: int | None = 5,
) -> db.Entry:
    """Compact constructor so the rule tests read like a training log."""
    return db.Entry(
        athlete_id=athlete_id,
        kind="set",
        lift=lift,
        sets=sets,
        reps=reps,
        weight_kg=weight,
        rpe=rpe,
        phase=phase,
        session_date=day,
    )


def days(*weights: float) -> list[str]:
    base = date(2026, 8, 1)
    return [(base + timedelta(days=3 * i)).isoformat() for i in range(len(weights))]


def series(
    weights: list[float],
    rpes: list[float | None] | None = None,
    phase: str | None = None,
    lift: str = "squat",
) -> list[db.Entry]:
    dates = days(*weights)
    rpes = rpes or [None] * len(weights)
    return [
        entry(d, w, r, lift=lift, phase=phase if i == 0 else None)
        for i, (d, w, r) in enumerate(zip(dates, weights, rpes))
    ]


class FakeClient:
    """A ModelClient that replays a fixed script — no network in the suite."""

    def __init__(self, calls: list[tuple[str, dict[str, Any]]]):
        self.calls = calls
        self.seen: list[str] = []

    def call(self, text: str, system_instruction: str):
        self.seen.append(text)
        return self.calls

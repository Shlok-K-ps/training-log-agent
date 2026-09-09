"""The Safety Guardian: the only thing that may open the gate to load advice.

Authority
---------
Owns injury state. Can veto training. Cannot diagnose, cannot name a condition,
cannot author a rehab protocol. It answers exactly one question — *may this
athlete be given a load today?* — and it answers it from the log, not from a
model's reading of a message.

Why a token
-----------
Before this module, every caller that computed a load repeated `if
assessment.injured: return`. A convention repeated at N call sites is a
convention that fails at the N+1th. `SafetyClearance` cannot be constructed
without a module-private token, so the only way to obtain one is to ask the
Guardian, and the only way the Guardian issues one is if the log says the
athlete is clear. Skipping the gate is now a TypeError at the call site rather
than a missing branch nobody noticed.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date

import sqlite3

from app.config import settings
from app.storage import db

# Module-private. Holding a reference to this is what proves a clearance came
# from assess() rather than from a caller that wanted to skip the gate.
_ISSUER = object()


class ClearanceForged(RuntimeError):
    """Raised when something tries to build a clearance without the Guardian."""


@dataclass(frozen=True)
class SafetyClearance:
    """Proof that the Guardian checked the log and found no open injury."""

    athlete_id: str
    issued_on: date
    _token: object = field(repr=False, compare=False)

    def __post_init__(self) -> None:
        if self._token is not _ISSUER:
            raise ClearanceForged(
                "SafetyClearance must be obtained from guardian.assess(); "
                "constructing one directly would bypass the injury gate"
            )


@dataclass(frozen=True)
class InjuryVeto:
    """The gate is shut. Carries why, and whether it needs a human's attention."""

    athlete_id: str
    note: str | None
    open_since: str | None
    days_open: int | None
    clearance_requested: bool
    stale: bool

    @property
    def reason(self) -> str:
        return "Programming is suppressed while an injury flag is open."


def assess(
    conn: sqlite3.Connection, athlete_id: str, *, today: date
) -> SafetyClearance | InjuryVeto:
    """The single gate. Returns a clearance, or a veto explaining the block."""
    injured, note = db.injury_state(conn, athlete_id)
    if not injured:
        return SafetyClearance(athlete_id, today, _ISSUER)

    opened = db.injury_opened_on(conn, athlete_id)
    days_open: int | None = None
    if opened:
        try:
            days_open = (today - date.fromisoformat(opened)).days
        except ValueError:
            days_open = None
    threshold = max(1, int(settings.injury_stale_after_days))
    return InjuryVeto(
        athlete_id=athlete_id,
        note=note,
        open_since=opened,
        days_open=days_open,
        clearance_requested=db.clearance_requested_on(conn, athlete_id) is not None,
        stale=days_open is not None and days_open >= threshold,
    )


def is_cleared(outcome: SafetyClearance | InjuryVeto) -> bool:
    return isinstance(outcome, SafetyClearance)


def clearance_for_tests(athlete_id: str = "test", on: date | None = None) -> SafetyClearance:
    """Build a clearance without consulting the log. TESTS ONLY.

    Application code must never call this — it is the one door around the gate,
    left deliberately visible so that its use is obvious in review.
    `tests/test_guardian.py::test_no_application_module_imports_the_test_door`
    fails if anything under `app/` references it.
    """
    return SafetyClearance(athlete_id, on or date.today(), _ISSUER)

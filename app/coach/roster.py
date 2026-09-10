"""The roster view: who needs the coach today.

This module decides nothing new. Every line it produces comes from a rule that
already exists — `decision.rules` for verdicts, `decision.guardian` for the
injury gate. It is a window over the log, not another opinion about it.

The ordering is the product. Twenty athletes is too many to read every morning,
so the console sorts by who needs attention and collapses everyone who doesn't.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date
from enum import Enum

import sqlite3

from app.config import settings
from app.decision.guardian import InjuryVeto, assess
from app.decision.rules import Verdict, evaluate
from app.storage import db


class Bucket(str, Enum):
    """Why this athlete is on the screen. Ordered by how much it needs a human."""

    NEEDS_YOU = "needs_you"   # blocked on a coach decision
    WATCH = "watch"           # the agent noticed something
    MEET_PREP = "meet_prep"   # a date is approaching
    FINE = "fine"             # collapse this one


BUCKET_ORDER = (Bucket.NEEDS_YOU, Bucket.WATCH, Bucket.MEET_PREP, Bucket.FINE)

BUCKET_LABEL = {
    Bucket.NEEDS_YOU: "Needs you",
    Bucket.WATCH: "Watch",
    Bucket.MEET_PREP: "Meet prep",
    Bucket.FINE: "Fine",
}


@dataclass(frozen=True)
class Flag:
    """One reason an athlete is surfaced. `action` marks a coach decision."""

    kind: str
    detail: str
    action: bool = False


@dataclass(frozen=True)
class RosterEntry:
    athlete_id: str
    name: str | None
    bucket: Bucket
    flags: tuple[Flag, ...] = ()
    days_silent: int | None = None
    injury_days_open: int | None = None
    weeks_to_meet: int | None = None

    @property
    def display_name(self) -> str:
        return self.name or self.athlete_id

    @property
    def needs_action(self) -> bool:
        return any(flag.action for flag in self.flags)


def _weeks_to_meet(conn: sqlite3.Connection, athlete_id: str, today: date) -> int | None:
    meet = db.latest_program_settings(conn, athlete_id).get("meet_date")
    if meet is None:
        return None
    try:
        days = (date.fromisoformat(str(meet)) - today).days
    except ValueError:
        return None
    return None if days < 0 else days // 7


def review_athlete(
    conn: sqlite3.Connection, athlete_id: str, *, today: date
) -> RosterEntry:
    """Everything the coach needs to know about one athlete, in one pass."""
    flags: list[Flag] = []

    # 1. Blocked on the coach. The injury gate needs a named human, so an athlete
    #    who has asked to be cleared is stuck until someone acts.
    safety = assess(conn, athlete_id, today=today)
    injury_days: int | None = None
    if isinstance(safety, InjuryVeto):
        injury_days = safety.days_open
        days = f"{safety.days_open}d" if safety.days_open is not None else "unknown"
        note = f" ({safety.note})" if safety.note else ""
        if safety.clearance_requested:
            flags.append(
                Flag(
                    "clearance_requested",
                    f"injury open {days}{note} · has asked to be cleared",
                    action=True,
                )
            )
        else:
            stale = " · STALE, no update" if safety.stale else ""
            flags.append(Flag("injured", f"injury open {days}{note}{stale}"))

    # 2. Silence. Nobody texts to say they have stopped texting.
    last = db.last_activity(conn, athlete_id)
    days_silent: int | None = None
    if last:
        try:
            days_silent = (today - date.fromisoformat(last)).days
        except ValueError:
            days_silent = None
    threshold = max(1, int(settings.coach_silent_after_days))
    if days_silent is not None and days_silent >= threshold:
        flags.append(Flag("silent", f"no logs in {days_silent} days"))

    # 3. Training signal, from the same rules the athlete's reply uses.
    phase = db.latest_phase(conn, athlete_id)
    injured, injury_note = db.injury_state(conn, athlete_id)
    for lift in db.list_lifts(conn, athlete_id):
        history = db.session_history(conn, athlete_id, lift)
        assessment = evaluate(
            athlete_id, lift, history, phase=phase, injured=injured,
            injury_note=injury_note,
        )
        if assessment.verdict is Verdict.DELOAD:
            flags.append(Flag("deload", f"{lift} — deload due"))
        elif assessment.verdict is Verdict.STALLED:
            flags.append(Flag("stalled", f"{lift} — stalled"))
        elif assessment.verdict is Verdict.REGRESSED:
            flags.append(Flag("regressed", f"{lift} — down on last session"))

    weeks = _weeks_to_meet(conn, athlete_id, today)
    if weeks is not None and weeks <= 8:
        flags.append(Flag("meet", f"meet in {weeks} weeks"))

    if any(flag.action for flag in flags):
        bucket = Bucket.NEEDS_YOU
    elif any(flag.kind in {"injured", "silent", "stalled", "deload", "regressed"} for flag in flags):
        bucket = Bucket.WATCH
    elif any(flag.kind == "meet" for flag in flags):
        bucket = Bucket.MEET_PREP
    else:
        bucket = Bucket.FINE

    return RosterEntry(
        athlete_id=athlete_id,
        name=db.athlete_name(conn, athlete_id),
        bucket=bucket,
        flags=tuple(flags),
        days_silent=days_silent,
        injury_days_open=injury_days,
        weeks_to_meet=weeks,
    )


@dataclass(frozen=True)
class Roster:
    reviewed_on: date
    entries: tuple[RosterEntry, ...] = field(default_factory=tuple)

    def bucket(self, bucket: Bucket) -> tuple[RosterEntry, ...]:
        return tuple(e for e in self.entries if e.bucket is bucket)

    @property
    def total(self) -> int:
        return len(self.entries)

    @property
    def needing_attention(self) -> int:
        return sum(1 for e in self.entries if e.bucket is not Bucket.FINE)


def build_roster(conn: sqlite3.Connection, *, today: date) -> Roster:
    """The whole squad, sorted by who needs a human first."""
    entries = [
        review_athlete(conn, athlete_id, today=today)
        for athlete_id in db.list_athletes(conn)
    ]
    order = {bucket: i for i, bucket in enumerate(BUCKET_ORDER)}
    entries.sort(key=lambda e: (order[e.bucket], -len(e.flags), e.display_name.lower()))
    return Roster(reviewed_on=today, entries=tuple(entries))

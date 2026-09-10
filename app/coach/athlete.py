"""One athlete, everything the coach needs before writing to them.

The roster answers *who* needs attention. This answers *what do I say to them*,
which is the other half of the coach's day and the half that currently happens
in twenty separate WhatsApp threads.

Like the roster, this module computes no new coaching. Verdicts come from
`decision.rules`, readiness from `decision.readiness`, injury state from
`decision.guardian`. The one thing it adds is a *suggested* message — a draft
assembled from those existing outputs, offered to the coach as a starting point.
The coach edits it, and what the athlete receives is whatever the coach sends.
"""

from __future__ import annotations

import sqlite3
from dataclasses import dataclass
from datetime import date, timedelta

from app.coach.roster import RosterEntry, review_athlete
from app.decision.guardian import InjuryVeto, assess
from app.decision.readiness import DailyCheckIn, evaluate_readiness
from app.decision.rules import Assessment, Verdict, evaluate
from app.storage import db

# How far back "recently" reaches on the detail page.
WINDOW_DAYS = 28


@dataclass(frozen=True)
class LoggedSet:
    session_date: str
    lift: str
    sets: int | None
    reps: int | None
    weight_kg: float | None
    rpe: float | None

    @property
    def summary(self) -> str:
        shape = ""
        if self.sets and self.reps:
            shape = f"{self.sets}x{self.reps} "
        weight = f"@ {self.weight_kg:g} kg" if self.weight_kg is not None else ""
        rpe = f"  RPE {self.rpe:g}" if self.rpe is not None else ""
        return f"{shape}{weight}{rpe}".strip()


@dataclass(frozen=True)
class AthleteDetail:
    athlete_id: str
    name: str | None
    roster: RosterEntry
    sessions: tuple[LoggedSet, ...]
    assessments: tuple[Assessment, ...]
    checkin: DailyCheckIn | None
    readiness_note: str | None
    injured: bool
    injury_note: str | None
    injury_days_open: int | None
    clearance_requested: bool
    last_activity: str | None
    phase: str
    reviewed_on: date

    @property
    def display_name(self) -> str:
        return self.name or self.athlete_id

    @property
    def logged_today(self) -> tuple[LoggedSet, ...]:
        """Only sessions actually dated today.

        The newest row is not the same thing: an athlete who last trained a
        fortnight ago still has a newest row, and a draft that opens "saw your
        session" to someone who has gone quiet reads as if nobody is paying
        attention — which is the exact failure this console exists to prevent.
        """
        stamp = self.reviewed_on.isoformat()
        return tuple(s for s in self.sessions if s.session_date == stamp)


_VERDICT_PHRASE = {
    Verdict.PROGRESSING: "moving up",
    Verdict.STALLED: "stalled",
    Verdict.DELOAD: "due a deload",
    Verdict.REGRESSED: "down on the last session",
    Verdict.HOLDING: "holding through the cut",
    Verdict.FLAT: "flat",
    Verdict.BASELINE: "just getting a baseline",
    Verdict.NO_DATA: "not logged yet",
}


def athlete_detail(
    conn: sqlite3.Connection, athlete_id: str, *, today: date
) -> AthleteDetail:
    """Everything about one athlete, gathered in a single pass."""
    cutoff = (today - timedelta(days=WINDOW_DAYS)).isoformat()
    sessions = tuple(
        LoggedSet(
            session_date=e.session_date,
            lift=e.lift or "",
            sets=e.sets,
            reps=e.reps,
            weight_kg=e.weight_kg,
            rpe=e.rpe,
        )
        for e in db.recent_entries(conn, athlete_id, limit=40)
        if e.session_date >= cutoff
    )

    phase = db.latest_phase(conn, athlete_id)
    injured, injury_note = db.injury_state(conn, athlete_id)
    assessments = tuple(
        evaluate(
            athlete_id, lift, db.session_history(conn, athlete_id, lift),
            phase=phase, injured=injured, injury_note=injury_note,
        )
        for lift in db.list_lifts(conn, athlete_id)
    )

    row = db.latest_checkin(conn, athlete_id, today.isoformat())
    checkin = readiness_note = None
    if row is not None:
        checkin = DailyCheckIn(
            checked_on=row.session_date,
            sleep_hours=row.sleep_hours,
            sleep_quality=row.sleep_quality,
            readiness=row.readiness,
            soreness=row.soreness,
            stress=row.stress,
            bodyweight_kg=row.bodyweight_kg,
            protein_g=row.protein_g,
            calories=row.calories,
            nutrition_adherence=row.nutrition_adherence,
        )
        try:
            band = evaluate_readiness(checkin)
            readiness_note = f"{band.band.value} · load factor {band.load_factor:g}"
        except Exception:  # noqa: BLE001 - a missing field must not break the page
            readiness_note = None

    safety = assess(conn, athlete_id, today=today)
    veto = safety if isinstance(safety, InjuryVeto) else None

    return AthleteDetail(
        athlete_id=athlete_id,
        name=db.athlete_name(conn, athlete_id),
        roster=review_athlete(conn, athlete_id, today=today),
        sessions=sessions,
        assessments=assessments,
        checkin=checkin,
        readiness_note=readiness_note,
        injured=injured,
        injury_note=injury_note,
        injury_days_open=veto.days_open if veto else None,
        clearance_requested=bool(veto and veto.clearance_requested),
        last_activity=db.last_activity(conn, athlete_id),
        phase=phase,
        reviewed_on=today,
    )


def suggest_message(detail: AthleteDetail, *, coach: str) -> str:
    """A first draft for the coach to edit. Never sent as-is without approval.

    Deliberately plain and short. It states what the log says and asks one
    question — it does not prescribe a load, because that is the deterministic
    layer's job and it is suppressed entirely while an injury is open.
    """
    first_name = detail.display_name.split()[0] if detail.name else "there"
    lines: list[str] = []

    today_sets = detail.logged_today
    if today_sets:
        what = "; ".join(f"{s.lift} {s.summary}" for s in today_sets[:3])
        lines.append(f"Hi {first_name} — saw your session: {what}.")
    elif any(f.kind == "silent" for f in detail.roster.flags):
        # The roster flag, not the raw day count: an athlete who trains every
        # third day is not silent, and telling them so reads as nagging.
        lines.append(
            f"Hi {first_name} — nothing logged for {detail.roster.days_silent} days. "
            "How's training going?"
        )
    elif detail.sessions:
        last = detail.sessions[0]
        lines.append(
            f"Hi {first_name} — last I have is {last.lift} {last.summary} "
            f"on {last.session_date}."
        )
    else:
        lines.append(f"Hi {first_name} —")

    if detail.injured:
        note = f" ({detail.injury_note})" if detail.injury_note else ""
        lines.append(
            f"I've still got your injury flag open{note}, so no load suggestions "
            "from me until a physio clears you. How is it feeling?"
        )
    else:
        notable = [
            a for a in detail.assessments
            if a.verdict in {Verdict.STALLED, Verdict.DELOAD, Verdict.REGRESSED}
        ]
        for a in notable[:2]:
            phrase = _VERDICT_PHRASE.get(a.verdict, a.verdict.value)
            weight = f" at {a.current_weight:g} kg" if a.current_weight else ""
            trend = (
                " and RPE is climbing" if a.rpe_trend == "climbing" else ""
            )
            lines.append(f"Your {a.lift} is {phrase}{weight}{trend}.")

    weeks = detail.roster.weeks_to_meet
    if weeks is not None:
        when = "this week" if weeks == 0 else f"in {weeks} weeks"
        lines.append(f"Meet {when} — worth a word about how you want to peak.")

    if detail.readiness_note:
        lines.append(f"Today's check-in: {detail.readiness_note}.")

    lines.append(f"— {coach}")
    return "\n".join(lines)


def progress_series(detail: AthleteDetail) -> dict[str, tuple[tuple[str, float], ...]]:
    """Top set per session, per lift, oldest first — the shape of their progress.

    The top set is the honest single number for a session: it is what the rules
    already compare, so the chart and the verdict can never disagree.
    """
    by_lift: dict[str, dict[str, float]] = {}
    for s in detail.sessions:
        if s.weight_kg is None or not s.lift:
            continue
        day = by_lift.setdefault(s.lift, {})
        day[s.session_date] = max(day.get(s.session_date, 0.0), s.weight_kg)
    return {
        lift: tuple(sorted(days.items()))
        for lift, days in by_lift.items()
        if len(days) >= 2
    }

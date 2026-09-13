"""A simulated training day for demonstrations, independent of the real clock.

The real agent refuses to open a training day once training time has passed,
which is correct and also means a live demo in the evening shows nothing. This
module plays a scripted day for the fictional demo squad on its own clock, on a
fixed past date, through the real engine, parser and rules:

* its cases are flagged `simulated`, so real ticks never see them and it never
  sees real cases;
* it only messages demo athletes, and only through the in-app simulator;
* it never notifies the coach's Telegram and never feeds adaptation;
* the production time rules are unchanged; the simulation simply chooses times.
"""

from __future__ import annotations

import uuid
from datetime import date, datetime, timedelta, timezone

from app.agent.offline import OfflineClient
from app.agent.schemas import LOOP_TOOL_NAMES
from app.casework import engine, store
from app.casework.transport import DeliveryFailed
from app.coach.demo import DEMO_PREFIX, is_demo, seed_demo_squad
from app.router import handle_message_with_actions
from app.storage import db

# A Monday that is already in the past, so it can never collide with a real day.
DEMO_DATE = date(2026, 1, 5)
DEMO_LABEL = "Monday 5 January 2026"
SOURCE = "demo-day"

# (step, athlete suffix, message, simulated UTC clock). Demo athletes use UTC.
MORNING = (
    ("tick", None, None, "07:31"),
    ("say", "006", "slept 8h readiness 8, soreness 3", "08:02"),    # routine: session goes out alone
    ("say", "007", "slept 7h readiness 7, soreness 4", "08:10"),    # routine
    ("say", "002", "slept 7h readiness 7", "08:15"),                # autopilot off: waits for coach
    ("say", "001", "slept 7h readiness 7", "08:20"),                # open injury: coach decides
    ("tick", None, None, "09:02"),                                   # first follow-ups
    ("tick", None, None, "11:02"),                                   # second follow-ups
    ("say", "008", "slept 8h readiness 9", "11:30"),                # late but within the window
    ("tick", None, None, "13:32"),                                   # silent athlete's day closes
)
EVENING = (
    ("tick", None, None, "20:31"),                                   # did training happen?
    ("say", "006", "squat 4x5 at 140kg rpe 7", "21:00"),
    ("say", "007", "done", "21:05"),
    ("say", "008", "skipped, work ran late", "21:10"),
)


class SimulatorTransport:
    """Messages stay inside the app; the coach decides simulated cases in the console."""

    def send_athlete(self, conn, athlete_id: str, body: str, *, kind: str) -> str:
        if not is_demo(athlete_id):
            raise DeliveryFailed("The simulated demo day only messages demo athletes.")
        provider_id = f"{SOURCE}:out:{uuid.uuid4().hex}"
        db.record_whatsapp_message(
            conn, athlete_id=athlete_id, direction="outbound", body=body, status="sent",
            provider_sid=provider_id, message_kind=f"agent:{kind}", channel="simulator",
        )
        return provider_id

    def notify_coach(self, conn, **_) -> None:
        return None


def at(clock: str) -> datetime:
    hour, minute = (int(piece) for piece in clock.split(":"))
    return datetime(DEMO_DATE.year, DEMO_DATE.month, DEMO_DATE.day, hour, minute, tzinfo=timezone.utc)


def decision_time(case) -> datetime:
    """A coach decision on a simulated case happens just after its last step."""
    return datetime.fromisoformat(str(case["updated_at"])) + timedelta(minutes=2)


def _athletes(conn) -> list[str]:
    return [athlete for athlete in store.planned_athletes(conn) if is_demo(athlete)]


def _say(conn, suffix: str, text: str, clock: str, *, coach_name: str) -> None:
    athlete_id = f"{DEMO_PREFIX}{suffix}"
    provider_id = f"{SOURCE}:in:{DEMO_DATE.isoformat()}:{suffix}:{clock}"
    if db.whatsapp_message_by_sid(conn, provider_id) is not None:
        return  # already played; replaying the script repeats nothing
    db.record_whatsapp_message(
        conn, athlete_id=athlete_id, direction="inbound", body=text, status="received",
        provider_sid=provider_id, message_kind="athlete_feedback", channel="simulator",
    )
    _, actions = handle_message_with_actions(
        conn, athlete_id, text, OfflineClient(), today=DEMO_DATE, allowed=LOOP_TOOL_NAMES
    )
    engine.observe_message(
        conn, athlete_id, actions, raw_text=text, now=at(clock),
        transport=SimulatorTransport(), coach_name=coach_name,
    )


def play(conn, phase: str, *, coach_name: str) -> tuple[str, str]:
    if phase == "evening" and not store.simulated_cases(conn):
        return ("err", "Play the simulated morning first.")
    if not _athletes(conn):
        seed_demo_squad(conn)
    athletes = _athletes(conn)
    for step, suffix, text, clock in MORNING if phase == "morning" else EVENING:
        if step == "tick":
            engine.tick(
                conn, now=at(clock), transport=SimulatorTransport(), coach_name=coach_name,
                athlete_ids=athletes, simulated=True,
            )
        elif f"{DEMO_PREFIX}{suffix}" in athletes:
            _say(conn, suffix, text, clock, coach_name=coach_name)
    cases = store.simulated_cases(conn)
    waiting = sum(1 for case in cases if case["state"] == "needs_coach")
    closed = sum(1 for case in cases if case["state"] == "closed")
    return (
        "ok",
        f"Simulated {phase} of {DEMO_LABEL} played: {len(cases)} case(s), {waiting} waiting for "
        f"you, {closed} closed.",
    )


def reset(conn) -> int:
    cases = store.simulated_cases(conn)
    for case in cases:
        conn.execute("DELETE FROM agent_events WHERE case_id = ?", (int(case["id"]),))
    conn.execute("DELETE FROM agent_cases WHERE simulated = 1")
    conn.execute("DELETE FROM whatsapp_messages WHERE provider_sid LIKE ?", (f"{SOURCE}:%",))
    conn.execute(
        "DELETE FROM entries WHERE athlete_id LIKE ? AND session_date = ?",
        (DEMO_PREFIX + "%", DEMO_DATE.isoformat()),
    )
    conn.commit()
    return len(cases)

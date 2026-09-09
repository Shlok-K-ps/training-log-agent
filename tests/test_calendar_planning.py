from __future__ import annotations

from datetime import date, datetime
from zoneinfo import ZoneInfo

from app.decision.readiness import DailyCheckIn
from app.scheduling.planner import (
    BusyEvent,
    SchedulingPreferences,
    plan_training_slots,
)
from app.scheduling.service import SchedulingService
from app.storage import db


ZONE = ZoneInfo("Asia/Kolkata")
DAY = date(2026, 9, 9)
ATHLETE = "+919000000001"


class Routes:
    def __init__(self, minutes: int = 20):
        self.minutes = minutes
        self.calls: list[tuple[str, str]] = []

    def duration_minutes(self, origin, destination, departure, mode):
        self.calls.append((origin, destination))
        return self.minutes


def at(hour: int, minute: int = 0) -> datetime:
    return datetime(2026, 9, 9, hour, minute, tzinfo=ZONE)


def test_calendar_gaps_include_both_commutes_and_buffers():
    result = plan_training_slots(
        day=DAY,
        gym_location="Iron Gym",
        events=(
            BusyEvent(at(9), at(10), "Office"),
            BusyEvent(at(14), at(15), "Office"),
        ),
        preferences=SchedulingPreferences(
            timezone="Asia/Kolkata",
            preferred_start="08:00",
            preferred_end="18:00",
            session_minutes=90,
            default_location="Home",
        ),
        travel_provider=Routes(20),
    )
    assert result.actionable
    best = result.candidates[0]
    assert best.start >= at(10, 35)
    assert best.end <= at(13, 10)
    assert (best.travel_before_minutes, best.travel_after_minutes) == (20, 20)


def test_sleep_loss_ranks_a_slot_after_the_nap_and_recovery_buffer():
    result = plan_training_slots(
        day=DAY,
        gym_location="Iron Gym",
        events=(),
        preferences=SchedulingPreferences(
            timezone="Asia/Kolkata",
            preferred_start="08:00",
            preferred_end="20:00",
            default_location="Home",
        ),
        travel_provider=Routes(10),
        checkin=DailyCheckIn(
            checked_on=DAY.isoformat(), sleep_hours=5, readiness=5, soreness=4
        ),
    )
    assert (result.nap_start, result.nap_minutes) == ("13:00", 45)
    assert result.candidates[0].start >= at(14, 45)


def test_severe_recovery_blocks_scheduling_even_when_calendar_is_empty():
    result = plan_training_slots(
        day=DAY,
        gym_location="Iron Gym",
        events=(),
        preferences=SchedulingPreferences(timezone="Asia/Kolkata"),
        travel_provider=Routes(),
        checkin=DailyCheckIn(checked_on=DAY.isoformat(), sleep_hours=3, readiness=2),
    )
    assert not result.actionable
    assert "severe recovery" in result.reasons[0].lower()


def test_missing_event_location_uses_a_privacy_buffer_instead_of_guessing():
    result = plan_training_slots(
        day=DAY,
        gym_location="Iron Gym",
        events=(BusyEvent(at(9), at(10), None),),
        preferences=SchedulingPreferences(
            timezone="Asia/Kolkata",
            preferred_start="10:00",
            preferred_end="15:00",
            unknown_location_buffer_minutes=45,
        ),
        travel_provider=Routes(),
    )
    assert result.actionable
    assert result.candidates[0].start >= at(11)
    assert any("privacy buffer" in reason for reason in result.candidates[0].reasons)


class Calendar:
    def __init__(self):
        self.created: list[dict] = []

    def connected(self, athlete_id):
        return True

    def list_events(self, athlete_id, *, day, timezone_name):
        return (BusyEvent(at(10), at(11), "Office"),)

    def create_or_update_workout_event(self, athlete_id, **kwargs):
        self.created.append(kwargs)
        return kwargs.get("event_id") or "google-event-1"

    def disconnect(self, athlete_id):
        pass


def configured_service(conn):
    db.insert_entry(
        conn,
        db.Entry(
            athlete_id=ATHLETE,
            kind="status",
            timezone="Asia/Kolkata",
            bedtime="23:00",
            nap_window_start="13:00",
            nap_window_end="16:00",
            session_date=DAY.isoformat(),
        ),
    )
    db.save_place(conn, ATHLETE, "gym", "Iron Gym")
    db.save_place(conn, ATHLETE, "home", "Athlete Home")
    db.save_scheduling_preferences(
        conn,
        ATHLETE,
        preferred_start="06:00",
        preferred_end="21:00",
        default_location_label="home",
    )
    calendar = Calendar()
    return SchedulingService(calendar, Routes(15), clock=lambda: at(5)), calendar


def test_service_persists_options_and_writes_only_after_confirmation(conn):
    service, calendar = configured_service(conn)
    result = service.propose(conn, ATHLETE, day=DAY, lift="squat")
    assert result.actionable and len(result.slots) == 3
    assert calendar.created == []
    proposal = db.schedule_proposal(conn, ATHLETE, result.slots[0].proposal_id)
    assert proposal is not None and proposal["status"] == "pending"

    confirmed = service.confirm(conn, ATHLETE, result.slots[0].proposal_id)
    assert confirmed.event_id == "google-event-1"
    assert len(calendar.created) == 1
    assert db.schedule_proposal(conn, ATHLETE, result.slots[0].proposal_id)["status"] == "confirmed"


def test_a_later_confirmed_plan_updates_the_existing_calendar_event(conn):
    service, calendar = configured_service(conn)
    first = service.propose(conn, ATHLETE, day=DAY)
    service.confirm(conn, ATHLETE, first.slots[0].proposal_id)
    second = service.propose(conn, ATHLETE, day=DAY)
    service.confirm(conn, ATHLETE, second.slots[-1].proposal_id)
    assert calendar.created[-1]["event_id"] == "google-event-1"
    assert db.schedule_proposal(conn, ATHLETE, first.slots[0].proposal_id)["status"] == "superseded"

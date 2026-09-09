from __future__ import annotations

import re
from datetime import date
from datetime import datetime
from zoneinfo import ZoneInfo

from app.router import handle_message
from app.scheduling.service import SchedulingService
from tests.conftest import FakeClient


ATHLETE = "+91911"
TODAY = date(2026, 9, 9)


class Calendar:
    def __init__(self):
        self.writes = []

    def connected(self, athlete_id):
        return True

    def list_events(self, athlete_id, *, day, timezone_name):
        return ()

    def create_or_update_workout_event(self, athlete_id, **kwargs):
        self.writes.append(kwargs)
        return "workout-event"

    def disconnect(self, athlete_id):
        pass


class Routes:
    def duration_minutes(self, origin, destination, departure, mode):
        return 15


def send(conn, service, calls):
    return handle_message(
        conn,
        ATHLETE,
        "message",
        FakeClient(calls),
        today=TODAY,
        scheduling=service,
    )


def test_whatsapp_proposes_then_confirms_and_retimes_nutrition(conn):
    calendar = Calendar()
    service = SchedulingService(
        calendar,
        Routes(),
        clock=lambda: datetime(2026, 9, 9, 8, tzinfo=ZoneInfo("Asia/Kolkata")),
    )
    send(
        conn,
        service,
        [
            ("configure_schedule", {"timezone": "Asia/Kolkata", "bedtime": "23:00"}),
            ("configure_place", {"label": "gym", "location": "Iron Gym"}),
            ("configure_place", {"label": "home", "location": "Athlete Home"}),
            (
                "configure_calendar_planning",
                {
                    "preferred_start": "16:00",
                    "preferred_end": "20:00",
                    "session_minutes": 90,
                    "default_location_label": "home",
                },
            ),
            (
                "configure_nutrition",
                {
                    "diet_style": "vegetarian",
                    "foods_available": ["rice", "dal", "paneer", "banana"],
                },
            ),
        ],
    )
    proposal = send(conn, service, [("ask_training_schedule", {})])
    assert "Calendar-aware training options" in proposal
    assert "Today's food and approved supplements" in proposal
    assert calendar.writes == []

    code = re.search(r"code \*([A-F0-9]+)\*", proposal).group(1)
    confirmed = send(conn, service, [("confirm_training_schedule", {"proposal_id": code})])
    assert "Workout scheduled" in confirmed
    assert "pre-training meal" in confirmed
    assert len(calendar.writes) == 1


def test_deleting_saved_locations_is_explicit_and_complete(conn):
    calendar = Calendar()
    service = SchedulingService(
        calendar,
        Routes(),
        clock=lambda: datetime(2026, 9, 9, 8, tzinfo=ZoneInfo("Asia/Kolkata")),
    )
    send(conn, service, [("configure_place", {"label": "gym", "location": "Iron Gym"})])
    reply = send(conn, service, [("forget_places", {})])
    assert "locations were deleted" in reply
    assert conn.execute("SELECT COUNT(*) FROM saved_places").fetchone()[0] == 0

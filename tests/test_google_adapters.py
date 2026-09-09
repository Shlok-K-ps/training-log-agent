from __future__ import annotations

from datetime import date, datetime

import httpx
from cryptography.fernet import Fernet

from app.integrations.google_calendar import (
    GoogleCalendarClient,
    GoogleCalendarOAuth,
    TokenCipher,
)
from app.integrations.google_routes import GoogleRoutesClient
from app.storage import db


ATHLETE = "+91999"


def calendar_client(conn, handler):
    cipher = TokenCipher(Fernet.generate_key().decode())
    db.save_oauth_connection(
        conn,
        athlete_id=ATHLETE,
        provider="google_calendar",
        access_token=cipher.encrypt("access"),
        refresh_token=cipher.encrypt("refresh"),
        expires_at="2099-01-01T00:00:00+00:00",
        scopes="calendar",
    )
    http = httpx.Client(transport=httpx.MockTransport(handler))
    oauth = GoogleCalendarOAuth(
        client_id="client",
        client_secret="secret",
        redirect_uri="https://coach.example/callback",
        http=http,
    )
    return GoogleCalendarClient(conn, oauth=oauth, cipher=cipher, http=http)


def test_calendar_adapter_exposes_only_time_and_location_facts(conn):
    requests = []

    def handler(request):
        requests.append(request)
        if request.url.path.endswith("/users/me/calendarList"):
            return httpx.Response(
                200,
                json={"items": [{"id": "athlete@example.com", "primary": True}]},
            )
        return httpx.Response(
            200,
            json={
                "items": [
                    {
                        "summary": "Confidential board meeting",
                        "description": "must never leave adapter",
                        "attendees": [{"email": "person@example.com"}],
                        "location": "Main Office",
                        "start": {"dateTime": "2026-09-09T10:00:00+05:30"},
                        "end": {"dateTime": "2026-09-09T11:00:00+05:30"},
                    }
                ]
            },
        )

    client = calendar_client(conn, handler)
    events = client.list_events(
        ATHLETE, day=date(2026, 9, 9), timezone_name="Asia/Kolkata"
    )
    assert len(events) == 1
    assert events[0].location == "Main Office"
    assert set(events[0].__dict__) == {"start", "end", "location", "all_day"}
    event_request = requests[-1]
    assert event_request.url.params["fields"] == "items(start,end,location,status,transparency)"


def test_workouts_are_created_then_updated_on_the_app_calendar(conn):
    calls = []

    def handler(request):
        calls.append((request.method, request.url.path))
        if request.method == "POST" and request.url.path.endswith("/calendars"):
            return httpx.Response(200, json={"id": "coach@group.calendar.google.com"})
        return httpx.Response(200, json={"id": "event-1"})

    client = calendar_client(conn, handler)
    start = datetime.fromisoformat("2026-09-09T18:00:00+05:30")
    end = datetime.fromisoformat("2026-09-09T19:30:00+05:30")
    event_id = client.create_or_update_workout_event(
        ATHLETE,
        start=start,
        end=end,
        timezone_name="Asia/Kolkata",
        gym_location="Iron Gym",
        lift="squat",
    )
    assert event_id == "event-1"
    client.create_or_update_workout_event(
        ATHLETE,
        start=start,
        end=end,
        timezone_name="Asia/Kolkata",
        gym_location="Iron Gym",
        lift="squat",
        event_id="event-1",
    )
    assert any(method == "PUT" and path.endswith("/events/event-1") for method, path in calls)


def test_routes_adapter_turns_google_duration_into_rounded_up_minutes():
    def handler(request):
        assert request.headers["X-Goog-FieldMask"] == "routes.duration,routes.distanceMeters"
        return httpx.Response(200, json={"routes": [{"duration": "1250s"}]})

    routes = GoogleRoutesClient(
        "maps-key", http=httpx.Client(transport=httpx.MockTransport(handler))
    )
    minutes = routes.duration_minutes(
        "Office",
        "Iron Gym",
        datetime.fromisoformat("2026-09-09T17:00:00+05:30"),
        "DRIVE",
    )
    assert minutes == 21

"""Application service joining calendar facts to the pure slot planner."""

from __future__ import annotations

import json
import secrets
import sqlite3
from dataclasses import dataclass
from datetime import date, datetime, timezone
from typing import Callable, Protocol
from zoneinfo import ZoneInfo

from app.decision.readiness import DailyCheckIn
from app.scheduling.planner import (
    BusyEvent,
    SchedulingPreferences,
    SlotPlan,
    TravelTimeProvider,
    plan_training_slots,
)
from app.storage import db


class CalendarBackend(Protocol):
    def connected(self, athlete_id: str) -> bool: ...

    def list_events(
        self, athlete_id: str, *, day: date, timezone_name: str
    ) -> tuple[BusyEvent, ...]: ...

    def create_or_update_workout_event(
        self,
        athlete_id: str,
        *,
        start: datetime,
        end: datetime,
        timezone_name: str,
        gym_location: str,
        lift: str | None,
        event_id: str | None = None,
    ) -> str: ...

    def disconnect(self, athlete_id: str) -> None: ...


@dataclass(frozen=True)
class ProposedSlot:
    proposal_id: str
    starts_at: datetime
    ends_at: datetime
    gym_label: str
    reasons: tuple[str, ...]


@dataclass(frozen=True)
class ProposalResult:
    actionable: bool
    slots: tuple[ProposedSlot, ...]
    reasons: tuple[str, ...]
    nap_start: str | None = None
    nap_minutes: int | None = None
    busy_windows: tuple[tuple[str, str], ...] = ()


@dataclass(frozen=True)
class ConfirmationResult:
    proposal_id: str
    starts_at: datetime
    ends_at: datetime
    gym_label: str
    lift: str | None
    event_id: str
    busy_windows: tuple[tuple[str, str], ...] = ()


class SchedulingService:
    def __init__(
        self,
        calendar: CalendarBackend,
        routing: TravelTimeProvider,
        *,
        clock: Callable[[], datetime] | None = None,
    ) -> None:
        self.calendar = calendar
        self.routing = routing
        self.clock = clock or (lambda: datetime.now(timezone.utc))

    def propose(
        self,
        conn: sqlite3.Connection,
        athlete_id: str,
        *,
        day: date,
        lift: str | None = None,
        gym_label: str = "gym",
    ) -> ProposalResult:
        if not self.calendar.connected(athlete_id):
            return ProposalResult(False, (), ("Google Calendar is not connected.",))
        places = db.saved_places(conn, athlete_id)
        gym_location = places.get(gym_label.lower()) or (
            places.get("gym") if gym_label.lower() != "gym" else None
        )
        if not gym_location:
            return ProposalResult(
                False,
                (),
                (f"Save a location for '{gym_label}' before scheduling.",),
            )
        schedule = db.latest_schedule_settings(conn, athlete_id)
        timezone_name = str(schedule.get("timezone") or "")
        if not timezone_name:
            return ProposalResult(False, (), ("Set your timezone before scheduling.",))
        stored = db.scheduling_preferences(conn, athlete_id)
        default_label = str(stored.get("default_location_label") or "home").lower()
        preferences = SchedulingPreferences(
            timezone=timezone_name,
            preferred_start=str(stored.get("preferred_start", "06:00")),
            preferred_end=str(stored.get("preferred_end", "21:00")),
            session_minutes=int(stored.get("session_minutes", 90)),
            pre_training_buffer_minutes=int(stored.get("pre_buffer_minutes", 15)),
            post_training_buffer_minutes=int(stored.get("post_buffer_minutes", 30)),
            unknown_location_buffer_minutes=int(
                stored.get("unknown_location_buffer_minutes", 30)
            ),
            bedtime=str(schedule["bedtime"]) if schedule.get("bedtime") else None,
            bedtime_buffer_minutes=int(stored.get("bedtime_buffer_minutes", 90)),
            travel_mode=str(stored.get("travel_mode", "DRIVE")),
            default_location=places.get(default_label),
            nap_window_start=str(schedule.get("nap_window_start", "13:00")),
            nap_window_end=str(schedule.get("nap_window_end", "16:00")),
        )
        row = db.latest_checkin(conn, athlete_id, day.isoformat())
        checkin = (
            DailyCheckIn(
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
            if row
            else None
        )
        events = self.calendar.list_events(
            athlete_id, day=day, timezone_name=timezone_name
        )
        busy_windows = _busy_windows(events, timezone_name)
        plan: SlotPlan = plan_training_slots(
            day=day,
            gym_location=gym_location,
            events=events,
            preferences=preferences,
            travel_provider=self.routing,
            checkin=checkin,
            now=self.clock(),
        )
        if not plan.actionable:
            return ProposalResult(
                False,
                (),
                plan.reasons,
                plan.nap_start,
                plan.nap_minutes,
                busy_windows,
            )
        proposals: list[ProposedSlot] = []
        for slot in plan.candidates:
            proposal_id = secrets.token_hex(3).upper()
            db.create_schedule_proposal(
                conn,
                proposal_id=proposal_id,
                athlete_id=athlete_id,
                local_date=day.isoformat(),
                starts_at=slot.start.isoformat(),
                ends_at=slot.end.isoformat(),
                gym_label=gym_label.lower(),
                lift=lift,
                reasons=json.dumps(slot.reasons),
            )
            proposals.append(
                ProposedSlot(
                    proposal_id,
                    slot.start,
                    slot.end,
                    gym_label.lower(),
                    slot.reasons,
                )
            )
        return ProposalResult(
            True,
            tuple(proposals),
            plan.reasons,
            plan.nap_start,
            plan.nap_minutes,
            busy_windows,
        )

    def confirm(
        self, conn: sqlite3.Connection, athlete_id: str, proposal_id: str
    ) -> ConfirmationResult:
        row = db.schedule_proposal(conn, athlete_id, proposal_id)
        if row is None:
            raise ValueError("That schedule option does not exist.")
        if row["status"] != "pending":
            raise ValueError(f"That schedule option is already {row['status']}.")
        places = db.saved_places(conn, athlete_id)
        gym_label = str(row["gym_label"])
        gym_location = places.get(gym_label)
        if not gym_location:
            raise ValueError("The saved gym location is no longer available.")
        timezone_name = str(
            db.latest_schedule_settings(conn, athlete_id).get("timezone") or "UTC"
        )
        starts_at = datetime.fromisoformat(str(row["starts_at"]))
        ends_at = datetime.fromisoformat(str(row["ends_at"]))
        existing = db.confirmed_schedule_for_date(
            conn, athlete_id, str(row["local_date"])
        )
        existing_event_id = str(existing["calendar_event_id"]) if existing else None
        event_id = self.calendar.create_or_update_workout_event(
            athlete_id,
            start=starts_at,
            end=ends_at,
            timezone_name=timezone_name,
            gym_location=gym_location,
            lift=row["lift"],
            event_id=existing_event_id,
        )
        db.confirm_schedule_proposal(conn, athlete_id, proposal_id, event_id)
        events = self.calendar.list_events(
            athlete_id,
            day=date.fromisoformat(str(row["local_date"])),
            timezone_name=timezone_name,
        )
        return ConfirmationResult(
            str(row["id"]),
            starts_at,
            ends_at,
            gym_label,
            row["lift"],
            event_id,
            _busy_windows(events, timezone_name),
        )


def _busy_windows(
    events: tuple[BusyEvent, ...], timezone_name: str
) -> tuple[tuple[str, str], ...]:
    zone = ZoneInfo(timezone_name)
    return tuple(
        (event.start.astimezone(zone).strftime("%H:%M"), event.end.astimezone(zone).strftime("%H:%M"))
        for event in events
        if not event.all_day
    )

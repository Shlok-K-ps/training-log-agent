"""Deterministic, location-aware training-slot planning.

Calendar and routing adapters provide facts.  This module alone decides whether
a slot is feasible and how candidates are ranked.  It never reads event titles
or asks a language model to reason about private calendar data.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime, time, timedelta
from typing import Protocol
from zoneinfo import ZoneInfo

from app.decision.readiness import DailyCheckIn, ReadinessBand, evaluate_readiness
from app.decision.sleep import SleepSchedule, plan_nap


class TravelTimeProvider(Protocol):
    def duration_minutes(
        self, origin: str, destination: str, departure: datetime, mode: str
    ) -> int:
        """Return an estimated one-way journey duration."""


@dataclass(frozen=True)
class BusyEvent:
    start: datetime
    end: datetime
    location: str | None = None
    all_day: bool = False


@dataclass(frozen=True)
class SchedulingPreferences:
    timezone: str
    preferred_start: str = "06:00"
    preferred_end: str = "21:00"
    session_minutes: int = 90
    pre_training_buffer_minutes: int = 15
    post_training_buffer_minutes: int = 30
    unknown_location_buffer_minutes: int = 30
    bedtime: str | None = None
    bedtime_buffer_minutes: int = 90
    travel_mode: str = "DRIVE"
    default_location: str | None = None
    nap_window_start: str = "13:00"
    nap_window_end: str = "16:00"


@dataclass(frozen=True)
class TrainingSlot:
    start: datetime
    end: datetime
    travel_before_minutes: int
    travel_after_minutes: int
    score: int
    reasons: tuple[str, ...]


@dataclass(frozen=True)
class SlotPlan:
    actionable: bool
    candidates: tuple[TrainingSlot, ...]
    reasons: tuple[str, ...]
    nap_start: str | None = None
    nap_minutes: int | None = None


def _clock(day: date, value: str, zone: ZoneInfo) -> datetime:
    parsed = time.fromisoformat(value)
    return datetime.combine(day, parsed, tzinfo=zone)


def _travel(
    provider: TravelTimeProvider,
    origin: str | None,
    destination: str | None,
    departure: datetime,
    preferences: SchedulingPreferences,
    cache: dict[tuple[str, str, str, str], int],
) -> tuple[int, bool]:
    if not origin or not destination:
        return preferences.unknown_location_buffer_minutes, True
    if origin.strip().casefold() == destination.strip().casefold():
        return 0, False
    key = (origin, destination, departure.strftime("%Y-%m-%dT%H:%M"), preferences.travel_mode)
    if key not in cache:
        try:
            cache[key] = max(
                0,
                int(provider.duration_minutes(origin, destination, departure, preferences.travel_mode)),
            )
        except RuntimeError:
            return preferences.unknown_location_buffer_minutes, True
    return cache[key], False


def plan_training_slots(
    *,
    day: date,
    gym_location: str,
    events: tuple[BusyEvent, ...],
    preferences: SchedulingPreferences,
    travel_provider: TravelTimeProvider,
    checkin: DailyCheckIn | None = None,
    limit: int = 3,
    step_minutes: int = 30,
    now: datetime | None = None,
) -> SlotPlan:
    """Return the best feasible slots after sleep, readiness and travel gates."""
    zone = ZoneInfo(preferences.timezone)
    window_start = _clock(day, preferences.preferred_start, zone)
    window_end = _clock(day, preferences.preferred_end, zone)
    if preferences.bedtime:
        bedtime = _clock(day, preferences.bedtime, zone)
        if bedtime <= window_start:
            bedtime += timedelta(days=1)
        window_end = min(
            window_end,
            bedtime - timedelta(minutes=preferences.bedtime_buffer_minutes),
        )
    if now is not None:
        local_now = now.astimezone(zone)
        if day == local_now.date():
            rounded_now = local_now.replace(second=0, microsecond=0)
            if local_now > rounded_now:
                rounded_now += timedelta(minutes=1)
            remainder = rounded_now.minute % step_minutes
            if remainder:
                rounded_now += timedelta(minutes=step_minutes - remainder)
            window_start = max(window_start, rounded_now)

    readiness = evaluate_readiness(checkin) if checkin else None
    if readiness and (not readiness.actionable or readiness.band is ReadinessBand.RED):
        return SlotPlan(
            False,
            (),
            (
                "Today's severe recovery gate suppresses training scheduling.",
                *readiness.reasons,
            ),
        )

    nap_start: str | None = None
    nap_minutes: int | None = None
    recovery_floor: datetime | None = None
    if checkin and checkin.sleep_hours is not None:
        nap = plan_nap(
            checkin,
            SleepSchedule(
                timezone=preferences.timezone,
                nap_window_start=preferences.nap_window_start,
                nap_window_end=preferences.nap_window_end,
            ),
        )
        if nap.recommended and nap.start_time and nap.duration_minutes:
            nap_start = nap.start_time
            nap_minutes = nap.duration_minutes
            recovery_floor = (
                _clock(day, nap.start_time, zone)
                + timedelta(minutes=nap.duration_minutes + 60)
            )

    local_events = tuple(
        sorted(
            (
                BusyEvent(
                    event.start.astimezone(zone),
                    event.end.astimezone(zone),
                    event.location,
                    event.all_day,
                )
                for event in events
                if event.end > event.start
            ),
            key=lambda item: item.start,
        )
    )
    if any(event.all_day for event in local_events):
        return SlotPlan(False, (), ("An all-day busy event leaves no schedulable window.",))

    cache: dict[tuple[str, str, str, str], int] = {}
    candidates: list[TrainingSlot] = []
    cursor = window_start
    duration = timedelta(minutes=preferences.session_minutes)
    preferred_midpoint = window_start + (window_end - window_start) / 2

    while cursor + duration <= window_end:
        finish = cursor + duration
        overlapping = [event for event in local_events if event.start < finish and event.end > cursor]
        if overlapping:
            cursor += timedelta(minutes=step_minutes)
            continue

        previous = max(
            (event for event in local_events if event.end <= cursor),
            key=lambda item: item.end,
            default=None,
        )
        following = min(
            (event for event in local_events if event.start >= finish),
            key=lambda item: item.start,
            default=None,
        )
        origin = previous.location if previous else preferences.default_location
        destination = following.location if following else preferences.default_location
        travel_before, before_unknown = _travel(
            travel_provider,
            origin,
            gym_location,
            previous.end if previous else cursor,
            preferences,
            cache,
        )
        travel_after, after_unknown = _travel(
            travel_provider,
            gym_location,
            destination,
            finish,
            preferences,
            cache,
        )
        earliest = window_start + timedelta(
            minutes=travel_before + preferences.pre_training_buffer_minutes
        )
        if previous:
            earliest = previous.end + timedelta(
                minutes=travel_before + preferences.pre_training_buffer_minutes
            )
        latest = window_end - timedelta(
            minutes=travel_after + preferences.post_training_buffer_minutes
        )
        if following:
            latest = following.start - timedelta(
                minutes=travel_after + preferences.post_training_buffer_minutes
            )
        if cursor < earliest or finish > latest:
            cursor += timedelta(minutes=step_minutes)
            continue

        reasons: list[str] = []
        score = 1000
        score -= int(abs((cursor - preferred_midpoint).total_seconds()) // 60)
        score -= 2 * (travel_before + travel_after)
        if recovery_floor:
            if cursor >= recovery_floor:
                score += 180
                reasons.append("Leaves the configured nap and a 60-minute pre-training buffer.")
            else:
                score -= 300
                reasons.append("Occurs before the suggested recovery nap; later options rank higher.")
        if readiness and readiness.band in {ReadinessBand.YELLOW, ReadinessBand.ORANGE}:
            reasons.append(
                f"Readiness is {readiness.band.value}; workout load remains reduced by the readiness rules."
            )
        if before_unknown or after_unknown:
            reasons.append(
                f"A {preferences.unknown_location_buffer_minutes}-minute safety/privacy buffer covers missing location or route data."
            )
        else:
            reasons.append(
                f"Travel allowance: {travel_before} minutes before and {travel_after} minutes after."
            )
        candidates.append(
            TrainingSlot(cursor, finish, travel_before, travel_after, score, tuple(reasons))
        )
        cursor += timedelta(minutes=step_minutes)

    candidates.sort(key=lambda candidate: (-candidate.score, candidate.start))
    selected = tuple(candidates[: max(1, limit)])
    if not selected:
        return SlotPlan(
            False,
            (),
            (
                "No calendar gap can fit the workout, travel, buffers, and bedtime boundary.",
            ),
            nap_start,
            nap_minutes,
        )
    return SlotPlan(
        True,
        selected,
        ("Slots are ranked by sleep protection, feasibility, commute, and preferred time.",),
        nap_start,
        nap_minutes,
    )

"""Deterministic morning sleep and nap planning.

This is recovery policy, not medical advice. A nap can create another same-day
check-in opportunity; it never erases the original sleep deficit, overrides an
injury flag, or raises a prescription above its unadjusted base load.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, time, timedelta

from app.decision.readiness import DailyCheckIn

NAP_SHORT_MINUTES = 30
NAP_RECOVERY_MINUTES = 45
MIN_PRE_TRAINING_BUFFER_MINUTES = 60


@dataclass(frozen=True)
class SleepSchedule:
    timezone: str = "UTC"
    morning_checkin_time: str = "08:00"
    training_time: str | None = None
    bedtime: str | None = None
    nap_window_start: str = "13:00"
    nap_window_end: str = "16:00"


@dataclass(frozen=True)
class NapPlan:
    recommended: bool
    start_time: str | None
    duration_minutes: int | None
    reasons: tuple[str, ...]
    requires_post_nap_checkin: bool = False


def _clock(value: str) -> time:
    return time.fromisoformat(value)


def _minutes(value: str) -> int:
    parsed = _clock(value)
    return parsed.hour * 60 + parsed.minute


def plan_nap(checkin: DailyCheckIn, schedule: SleepSchedule) -> NapPlan:
    """Offer a nap only when reported sleep/readiness supports one and time fits."""
    if checkin.sleep_hours is None:
        return NapPlan(False, None, None, ("Sleep hours are needed before scheduling a nap.",))

    low_readiness = checkin.readiness is not None and checkin.readiness <= 6
    if checkin.sleep_hours >= 7 and not low_readiness:
        return NapPlan(
            False,
            None,
            None,
            ("Reported sleep and readiness do not trigger a recovery nap.",),
        )

    duration = NAP_RECOVERY_MINUTES if checkin.sleep_hours < 6 else NAP_SHORT_MINUTES
    start = _minutes(schedule.nap_window_start)
    end_limit = _minutes(schedule.nap_window_end)
    if schedule.training_time:
        end_limit = min(
            end_limit,
            _minutes(schedule.training_time) - MIN_PRE_TRAINING_BUFFER_MINUTES,
        )

    if start + duration > end_limit:
        return NapPlan(
            True,
            None,
            duration,
            (
                "Recovery supports a nap, but the configured window does not leave "
                "enough time before training.",
            ),
            True,
        )

    reasons = [
        f"Reported sleep was {checkin.sleep_hours:g} hours.",
        "A post-nap check-in is required before today's training plan is recalculated.",
    ]
    if checkin.sleep_hours < 4 or (checkin.readiness is not None and checkin.readiness <= 2):
        reasons.append("A severe recovery flag remains active even if the nap is completed.")
    return NapPlan(
        True,
        f"{start // 60:02d}:{start % 60:02d}",
        duration,
        tuple(reasons),
        True,
    )


def is_morning_prompt_due(
    local_now: datetime,
    checkin_time: str,
    *,
    catchup_minutes: int = 120,
) -> bool:
    """True during the bounded delivery window after the configured local time."""
    target = datetime.combine(local_now.date(), _clock(checkin_time), tzinfo=local_now.tzinfo)
    return target <= local_now < target + timedelta(minutes=catchup_minutes)

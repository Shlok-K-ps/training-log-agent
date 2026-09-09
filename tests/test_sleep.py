from __future__ import annotations

from datetime import datetime
from zoneinfo import ZoneInfo

from app.decision.readiness import DailyCheckIn
from app.decision.sleep import SleepSchedule, is_morning_prompt_due, plan_nap


def checkin(hours: float, readiness: int = 8) -> DailyCheckIn:
    return DailyCheckIn(checked_on="2026-09-09", sleep_hours=hours, readiness=readiness)


def test_well_recovered_athlete_is_not_assigned_a_nap():
    assert plan_nap(checkin(8), SleepSchedule()).recommended is False


def test_moderate_sleep_loss_gets_a_short_nap_and_recheck():
    result = plan_nap(checkin(6.5), SleepSchedule())
    assert (result.start_time, result.duration_minutes) == ("13:00", 30)
    assert result.requires_post_nap_checkin is True


def test_larger_sleep_loss_gets_a_recovery_nap():
    assert plan_nap(checkin(5), SleepSchedule()).duration_minutes == 45


def test_nap_is_not_scheduled_without_a_pre_training_buffer():
    result = plan_nap(
        checkin(5),
        SleepSchedule(training_time="13:30", nap_window_start="13:00", nap_window_end="16:00"),
    )
    assert result.recommended is True and result.start_time is None


def test_severe_sleep_flag_survives_the_nap_recommendation():
    result = plan_nap(checkin(3, readiness=2), SleepSchedule())
    assert any("severe" in reason for reason in result.reasons)


def test_morning_prompt_has_a_bounded_catchup_window():
    zone = ZoneInfo("Asia/Kolkata")
    assert is_morning_prompt_due(datetime(2026, 9, 9, 8, 15, tzinfo=zone), "07:30")
    assert not is_morning_prompt_due(datetime(2026, 9, 9, 10, 0, tzinfo=zone), "07:30")

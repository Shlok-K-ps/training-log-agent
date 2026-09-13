"""The fixed rules behind the training-day agent: hold or reduce, never increase."""

from __future__ import annotations

import pytest

from app.casework import adaptation, policy
from app.casework.policy import PlannedLift
from app.decision.readiness import DailyCheckIn, ReadinessBand

PLAN = (PlannedLift("squat", 4, 5, 7.0), PlannedLift("bench press", 3, 8, 8.0))


@pytest.mark.parametrize("band", list(ReadinessBand))
def test_no_readiness_band_can_increase_the_approved_session(band):
    session, changes = policy.adjust_for_band(PLAN, band)
    assert changes
    assert policy.never_increases(PLAN, session)


def test_bands_hold_or_reduce_by_fixed_amounts():
    green, _ = policy.adjust_for_band(PLAN, ReadinessBand.GREEN)
    yellow, _ = policy.adjust_for_band(PLAN, ReadinessBand.YELLOW)
    orange, _ = policy.adjust_for_band(PLAN, ReadinessBand.ORANGE)
    red, _ = policy.adjust_for_band(PLAN, ReadinessBand.RED)
    assert green == PLAN
    assert [item.rpe for item in yellow] == [6.5, 7.5]
    assert [(item.sets, item.rpe) for item in orange] == [(3, 6.0), (2, 7.0)]
    assert [(item.sets, item.rpe) for item in red] == [(2, 5.5), (2, 6.0)]


def test_rpe_never_drops_below_the_floor_or_rises_above_the_plan():
    easy = (PlannedLift("squat", 2, 5, 5.0),)
    for band in ReadinessBand:
        session, _ = policy.adjust_for_band(easy, band)
        assert session[0].rpe == 5.0


def test_a_session_that_adds_work_is_detected():
    assert not policy.never_increases(PLAN, (PlannedLift("squat", 5, 5, 7.0),))
    assert not policy.never_increases(PLAN, (PlannedLift("deadlift", 1, 1, 6.0),))


def test_triage_escalates_injury_before_recovery_before_autopilot():
    poor = DailyCheckIn(checked_on="2026-09-14", sleep_hours=3.5, readiness=2)
    good = DailyCheckIn(checked_on="2026-09-14", sleep_hours=8, readiness=8)
    assert policy.triage(PLAN, poor, injured=True, autopilot=True).escalation == "injury_open"
    assert policy.triage(PLAN, poor, injured=False, autopilot=True).escalation == "readiness_red"
    assert policy.triage(PLAN, good, injured=False, autopilot=False).escalation == "autopilot_off"
    routine = policy.triage(PLAN, good, injured=False, autopilot=True)
    assert routine.routine and routine.session == PLAN


def test_missing_fields_asks_for_sleep_and_readiness_only():
    assert policy.missing_fields(DailyCheckIn(checked_on="x", soreness=3)) == (
        "hours slept", "readiness 1–10",
    )
    assert policy.missing_fields(DailyCheckIn(checked_on="x", sleep_hours=7, readiness=6)) == ()


def test_adaptation_needs_enough_late_replies():
    assert adaptation.propose([100, 100, 100], current="07:30", base="07:30", training="18:00") is None
    assert adaptation.propose([20, 25, 30, 15], current="07:30", base="07:30", training="18:00") is None
    proposal = adaptation.propose([100, 95, 110, 90], current="07:30", base="07:30", training="18:00")
    assert proposal is not None
    assert (proposal.new_time, proposal.step_minutes) == ("08:00", 30)


def test_adaptation_is_capped_by_the_coach_time_and_training_time():
    capped = adaptation.propose([200] * 5, current="08:45", base="07:30", training="18:00")
    assert capped is not None and capped.new_time == "09:00"
    assert adaptation.propose([200] * 5, current="09:00", base="07:30", training="18:00") is None
    early_training = adaptation.propose([200] * 5, current="07:30", base="07:30", training="10:45")
    assert early_training is not None and early_training.new_time == "07:45"

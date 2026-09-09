from __future__ import annotations

from datetime import date

from app.decision.prescribe import prescribe_next
from app.decision.readiness import DailyCheckIn
from app.decision.rules import evaluate
from app.programming import Experience, Methodology, ProgrammingProfile, choose_methodology
from tests.conftest import series

TODAY = date(2026, 9, 9)


def choice(method: Methodology, *, injured: bool = False):
    return choose_methodology(
        ProgrammingProfile(
            experience=Experience.INTERMEDIATE,
            days_per_week=4,
            preferred=method,
            injured=injured,
        )
    )


def prescription(weights, *, rpes=None, method=Methodology.LINEAR_PROGRESSION, checkin=None, injured=False):
    entries = series(weights, rpes)
    assessment = evaluate("athlete", "squat", entries, injured=injured)
    return prescribe_next(
        assessment,
        entries,
        choice(method, injured=injured),
        session_number=len(weights) + 1,
        today=TODAY,
        checkin=checkin,
    )


def test_successful_lower_body_work_adds_five_kg():
    result = prescription([140, 145], rpes=[8, 8])
    assert result.base_weight_kg == 150


def test_rpe_nine_holds_the_load_even_when_progressing():
    result = prescription([140, 145], rpes=[8, 9])
    assert result.base_weight_kg == 145
    assert "high-effort gate" in result.reasons[0]


def test_stalled_work_is_held_not_blindly_increased():
    result = prescription([140, 140, 140], rpes=[8, 8, 8])
    assert result.base_weight_kg == 140


def test_a_deload_comes_from_the_existing_stall_rule():
    weights = [130, 130, 130, 135, 140, 140, 140]
    result = prescription(weights, rpes=[8] * len(weights))
    assert result.base_weight_kg == 120


def test_same_day_readiness_can_reduce_but_not_increase_load():
    checkin = DailyCheckIn(
        checked_on=TODAY.isoformat(), sleep_hours=6.5, readiness=6, soreness=5
    )
    result = prescription([140, 145], rpes=[8, 8], checkin=checkin)
    assert result.adjusted_weight_kg <= result.base_weight_kg


def test_stale_readiness_is_ignored():
    stale = DailyCheckIn(checked_on="2026-09-08", sleep_hours=3, readiness=1, soreness=10)
    result = prescription([140, 145], rpes=[8, 8], checkin=stale)
    assert result.actionable is True
    assert result.adjusted_weight_kg == result.base_weight_kg
    assert any("stale" in reason for reason in result.reasons)


def test_a_red_readiness_day_suppresses_the_load():
    red = DailyCheckIn(checked_on=TODAY.isoformat(), sleep_hours=3, readiness=2, soreness=9)
    result = prescription([140, 145], rpes=[8, 8], checkin=red)
    assert result.actionable is False
    assert result.adjusted_weight_kg is None


def test_injury_suppresses_the_prescription_before_readiness():
    result = prescription([140], injured=True)
    assert result.actionable is False
    assert result.methodology is None


def test_training_max_method_withholds_load_until_inputs_are_verified():
    result = prescription([140, 145], method=Methodology.FIVE_THREE_ONE)
    assert result.actionable is False
    assert result.adjusted_weight_kg is None
    assert "coach-approved training max" in result.required_inputs


def test_block_and_conjugate_do_not_reuse_a_random_top_set_as_a_max():
    for method in (Methodology.BLOCK_PERIODIZATION, Methodology.CONJUGATE):
        result = prescription([140, 145], method=method)
        assert result.actionable is False
        assert result.base_weight_kg is None

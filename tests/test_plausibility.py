"""Plausibility checks: catch parse errors without ever losing a real session."""

from __future__ import annotations

import pytest

from app.agent.schemas import ValidationError, validate_call
from app.decision.plausibility import check_ceiling, check_jump, check_ratio, review
from datetime import date

TODAY = date(2026, 9, 8)


# --- ceilings, enforced at the validator ---------------------------------------


def test_a_bench_above_the_world_record_is_rejected():
    """The case a single global cap missed: 400 kg is under the old 600 kg limit
    but is well over the heaviest bench ever recorded."""
    with pytest.raises(ValidationError, match="bench press"):
        validate_call("log_set", {"lift": "bench", "weight": 400}, TODAY)


def test_the_same_weight_is_fine_for_a_squat():
    action = validate_call("log_set", {"lift": "squat", "weight": 400}, TODAY)
    assert action.weight_kg == 400.0


def test_a_real_world_record_is_never_rejected():
    """Daniel Bell's 1102.3 lb squat — the heaviest in the sample."""
    action = validate_call(
        "log_set", {"lift": "squat", "weight": 1102.3, "unit": "lb"}, TODAY
    )
    assert action.weight_kg == pytest.approx(500.0, abs=0.1)


def test_ceiling_check_is_silent_on_a_missing_weight():
    assert check_ceiling("squat", None) is None


def test_an_unknown_lift_still_has_a_finite_ceiling():
    with pytest.raises(ValidationError):
        validate_call("log_set", {"lift": "cable fly", "weight": 500}, TODAY)


# --- ratios -------------------------------------------------------------------


def test_a_bench_heavier_than_the_squat_is_flagged():
    """Almost always two numbers swapped during parsing."""
    flag = check_ratio("bench press", 180.0, 140.0)
    assert flag is not None
    assert flag.code == "ratio_high"


def test_an_ordinary_bench_is_not_flagged():
    assert check_ratio("bench press", 90.0, 140.0) is None


def test_a_strong_puller_is_not_flagged():
    """Deadlift well above squat is common and must not produce noise."""
    assert check_ratio("deadlift", 220.0, 140.0) is None


def test_the_ratio_check_does_nothing_without_a_squat_on_record():
    assert check_ratio("bench press", 300.0, None) is None


def test_lifts_outside_the_big_three_have_no_ratio_rule():
    assert check_ratio("barbell row", 200.0, 140.0) is None


# --- session-to-session jumps -------------------------------------------------


def test_a_huge_jump_from_the_last_session_is_flagged():
    flag = check_jump("squat", 200.0, 140.0)
    assert flag is not None and flag.code == "big_jump"


def test_normal_progression_is_not_flagged():
    assert check_jump("squat", 142.5, 140.0) is None


def test_a_deload_is_not_flagged():
    """85% of the last session is the system's own prescription. It must not
    then flag the athlete for following it."""
    assert check_jump("squat", 119.0, 140.0) is None


def test_the_jump_check_scales_to_the_individual():
    """140 kg is suspicious for a 100 kg squatter and routine for a 200 kg one."""
    assert check_jump("squat", 140.0, 100.0) is not None
    assert check_jump("squat", 140.0, 160.0) is None


def test_the_jump_check_does_nothing_on_a_first_session():
    assert check_jump("squat", 140.0, None) is None


# --- review orders flags by how actionable they are ---------------------------


def test_history_is_reported_before_population_statistics():
    flags = review("bench press", 300.0, last_weight_kg=100.0, best_squat_kg=140.0)
    assert [f.code for f in flags] == ["big_jump", "ratio_high"]


def test_a_clean_lift_produces_no_flags():
    assert review("bench press", 100.0, last_weight_kg=97.5, best_squat_kg=140.0) == []

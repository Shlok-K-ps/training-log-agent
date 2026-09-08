"""Layer 1 tests: everything the model returns is validated before it is stored.

The model is the least trustworthy component in the system. These tests pin the
boundary that keeps its mistakes out of the database.
"""

from __future__ import annotations

from datetime import date

import pytest

from app.agent.schemas import (
    Clarify,
    LogSet,
    LogStatus,
    QueryProgress,
    ValidationError,
    validate_call,
)

TODAY = date(2026, 9, 8)


def call(name: str, **args):
    return validate_call(name, args, TODAY)


# --- log_set ------------------------------------------------------------------


def test_a_clean_set_validates():
    action = call("log_set", lift="squat", sets=3, reps=5, weight=140, rpe=8)
    assert action == LogSet(
        lift="squat", sets=3, reps=5, weight_kg=140.0, rpe=8.0,
        session_date="2026-09-08", phase=None,
    )


def test_lift_aliases_fold_to_one_canonical_series():
    assert call("log_set", lift="BP", weight=100).lift == "bench press"
    assert call("log_set", lift="Bench Press", weight=100).lift == "bench press"
    assert call("log_set", lift="squats", weight=100).lift == "squat"


def test_pounds_are_converted_in_python_not_by_the_model():
    action = call("log_set", lift="bench", weight=225, unit="lb")
    assert action.weight_kg == pytest.approx(102.06, abs=0.01)


def test_unknown_unit_is_rejected():
    with pytest.raises(ValidationError):
        call("log_set", lift="squat", weight=140, unit="stone")


def test_a_hallucinated_bar_load_is_rejected():
    with pytest.raises(ValidationError):
        call("log_set", lift="squat", weight=900)


def test_zero_weight_is_rejected():
    with pytest.raises(ValidationError):
        call("log_set", lift="squat", weight=0)


def test_rpe_outside_the_scale_is_rejected():
    with pytest.raises(ValidationError):
        call("log_set", lift="squat", weight=140, rpe=14)


def test_missing_lift_is_rejected():
    with pytest.raises(ValidationError):
        call("log_set", weight=140)


def test_fractional_reps_are_rejected():
    with pytest.raises(ValidationError):
        call("log_set", lift="squat", weight=140, reps=5.5)


def test_a_missing_weight_is_allowed_and_stays_missing():
    """Better a row with a null weight than a row with an invented one."""
    assert call("log_set", lift="squat", sets=3, reps=5).weight_kg is None


def test_dates_in_the_future_are_rejected():
    with pytest.raises(ValidationError):
        call("log_set", lift="squat", weight=140, session_date="2027-01-01")


def test_absurdly_old_dates_are_rejected():
    with pytest.raises(ValidationError):
        call("log_set", lift="squat", weight=140, session_date="1999-01-01")


def test_a_malformed_date_is_rejected():
    with pytest.raises(ValidationError):
        call("log_set", lift="squat", weight=140, session_date="last tuesday")


def test_a_past_date_is_kept():
    assert call("log_set", lift="squat", weight=140, session_date="2026-09-01").session_date == "2026-09-01"


def test_date_defaults_to_today():
    assert call("log_set", lift="squat", weight=140).session_date == "2026-09-08"


def test_invalid_phase_is_rejected():
    with pytest.raises(ValidationError):
        call("log_set", lift="squat", weight=140, phase="recomp")


# --- log_status ---------------------------------------------------------------


def test_status_records_phase_and_injury():
    action = call("log_status", phase="cut", injured=True, injury_note="left knee")
    assert action == LogStatus(phase="cut", injured=True, injury_note="left knee", athlete_name=None)


def test_an_empty_status_is_rejected():
    with pytest.raises(ValidationError):
        call("log_status")


def test_injury_can_be_cleared():
    assert call("log_status", injured=False).injured is False


def test_long_injury_notes_are_truncated():
    assert len(call("log_status", injured=True, injury_note="x" * 500).injury_note) == 200


# --- query_progress and clarify -----------------------------------------------


def test_query_without_a_lift_means_every_lift():
    assert call("query_progress") == QueryProgress(lift=None)


def test_query_normalises_the_lift_name():
    assert call("query_progress", lift="DL") == QueryProgress(lift="deadlift")


def test_clarify_needs_a_question():
    assert isinstance(call("clarify", question="What weight?"), Clarify)
    with pytest.raises(ValidationError):
        call("clarify", question="   ")


# --- the closed world ---------------------------------------------------------


def test_a_tool_the_model_invented_is_rejected():
    with pytest.raises(ValidationError):
        call("delete_all_athletes", confirm=True)

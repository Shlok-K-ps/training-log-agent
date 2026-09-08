"""Layer 3 tests.

These are the tests that matter. Athletes act on this layer's output, so every
branch of it is pinned here — and because the layer is pure Python with no model
and no clock, every one of these runs in microseconds and never flakes.
"""

from __future__ import annotations

import pytest

from app.decision.rules import (
    DELOAD_FACTOR,
    Verdict,
    count_stall_episodes,
    evaluate,
    round_to_increment,
    to_session_points,
)
from tests.conftest import series


def verdict(weights, rpes=None, phase=None, **kwargs) -> Verdict:
    return evaluate("+911", "squat", series(weights, rpes, phase), **kwargs).verdict


# --- the basic direction of travel -------------------------------------------


def test_no_history_is_no_data():
    assert verdict([]) is Verdict.NO_DATA


def test_single_session_is_a_baseline_not_a_verdict():
    assert verdict([140]) is Verdict.BASELINE


def test_weight_up_is_progressing():
    assert verdict([140, 142.5]) is Verdict.PROGRESSING


def test_weight_down_is_a_backoff_not_a_stall():
    assert verdict([140, 130]) is Verdict.REGRESSED


def test_two_flat_sessions_is_not_yet_a_stall():
    assert verdict([140, 140], [8, 8]) is Verdict.FLAT


# --- the stall rules ----------------------------------------------------------


def test_three_flat_sessions_is_a_stall():
    assert verdict([140, 140, 140], [8, 8, 8]) is Verdict.STALLED


def test_two_flat_sessions_with_rpe_climbing_stalls_early():
    """The bar says nothing changed; the athlete says it got harder."""
    assert verdict([140, 140], [7, 9]) is Verdict.STALLED


def test_rpe_easing_on_flat_weight_is_not_a_stall():
    assert verdict([140, 140], [9, 7]) is Verdict.FLAT


def test_missing_rpe_cannot_trigger_the_early_stall():
    assert verdict([140, 140], [None, None]) is Verdict.FLAT


def test_progressing_beats_a_long_flat_run_before_it():
    assert verdict([140, 140, 140, 145], [8, 8, 9, 8]) is Verdict.PROGRESSING


# --- phase --------------------------------------------------------------------


def test_flat_weight_during_a_cut_is_holding_not_stalling():
    assert verdict([140, 140, 140], [8, 8, 8], phase="cut") is Verdict.HOLDING


def test_cut_suppresses_the_rpe_early_stall_too():
    assert verdict([140, 140], [7, 9], phase="cut") is Verdict.HOLDING


def test_bulk_behaves_like_maintenance():
    assert verdict([140, 140, 140], [8, 8, 8], phase="bulk") is Verdict.STALLED


def test_a_cut_stall_does_not_count_toward_a_deload():
    """Three flat sessions in a cut are not an episode, so a later stall is the first."""
    entries = series([140, 140, 140], [8, 8, 8], phase="cut")
    assert count_stall_episodes(to_session_points(entries)) == 0


# --- deload -------------------------------------------------------------------


def test_second_stall_episode_prescribes_a_deload():
    weights = [130, 130, 130, 135, 140, 140, 140]
    rpes = [8, 8, 8, 8, 8, 8, 8]
    assessment = evaluate("+911", "squat", series(weights, rpes))
    assert assessment.verdict is Verdict.DELOAD
    assert assessment.stall_episodes == 2


def test_deload_target_is_85_percent_rounded_to_the_nearest_plate():
    weights = [130, 130, 130, 135, 140, 140, 140]
    assessment = evaluate("+911", "squat", series(weights, [8] * 7))
    assert assessment.deload_target_kg == round_to_increment(140 * DELOAD_FACTOR)
    assert assessment.deload_target_kg == 120.0


def test_one_long_flat_run_is_a_single_episode_not_several():
    """Four sessions at one weight is one stall. Otherwise athletes get deloaded
    for the crime of logging consistently."""
    points = to_session_points(series([140, 140, 140, 140], [8] * 4))
    assert count_stall_episodes(points) == 1
    assert evaluate("+911", "squat", series([140] * 4, [8] * 4)).verdict is Verdict.STALLED


def test_a_first_stall_is_never_a_deload():
    assessment = evaluate("+911", "squat", series([140, 140, 140], [8, 8, 8]))
    assert assessment.verdict is Verdict.STALLED
    assert assessment.deload_target_kg is None


# --- injury -------------------------------------------------------------------


def test_injury_flag_makes_the_assessment_non_actionable():
    assessment = evaluate(
        "+911", "squat", series([140, 140, 140], [8, 8, 8]), injured=True, injury_note="knee"
    )
    assert assessment.verdict is Verdict.STALLED  # tracking continues
    assert assessment.actionable is False  # prescribing does not


def test_injury_flag_does_not_change_the_verdict_itself():
    healthy = evaluate("+911", "squat", series([140, 142.5]))
    hurt = evaluate("+911", "squat", series([140, 142.5]), injured=True)
    assert healthy.verdict is hurt.verdict


# --- session collapsing -------------------------------------------------------


def test_multiple_sets_in_one_session_collapse_to_the_top_set():
    from tests.conftest import entry

    entries = [
        entry("2026-09-01", 100, 6),
        entry("2026-09-01", 140, 9),
        entry("2026-09-01", 120, 7),
    ]
    points = to_session_points(entries)
    assert len(points) == 1
    assert points[0].weight_kg == 140
    assert points[0].rpe == 9


def test_sessions_are_ordered_by_date_not_insertion():
    from tests.conftest import entry

    entries = [entry("2026-09-08", 145), entry("2026-09-01", 140)]
    points = to_session_points(entries)
    assert [p.weight_kg for p in points] == [140, 145]
    assert evaluate("+911", "squat", entries).verdict is Verdict.PROGRESSING


@pytest.mark.parametrize(
    "raw,expected",
    [(119.0, 120.0), (118.0, 117.5), (100.0, 100.0), (101.24, 100.0), (101.26, 102.5)],
)
def test_rounding_lands_on_loadable_weights(raw, expected):
    assert round_to_increment(raw) == expected


# --- determinism --------------------------------------------------------------


def test_same_log_gives_the_same_answer_every_time():
    entries = series([130, 130, 130, 135, 140, 140, 140], [8] * 7)
    first = evaluate("+911", "squat", entries)
    for _ in range(50):
        assert evaluate("+911", "squat", entries) == first

"""The methodology layer is deterministic policy, never model output."""

from __future__ import annotations

import pytest

from app.programming import (
    METHODOLOGIES,
    Experience,
    Methodology,
    ProgrammingProfile,
    choose_methodology,
    session_structure,
)


def profile(**overrides) -> ProgrammingProfile:
    values = {"experience": Experience.INTERMEDIATE, "days_per_week": 4}
    values.update(overrides)
    return ProgrammingProfile(**values)


def test_catalog_contains_exactly_five_distinct_strategies():
    assert set(METHODOLOGIES) == set(Methodology)
    assert len(METHODOLOGIES) == 5


def test_novices_start_with_linear_progression():
    assert choose_methodology(profile(experience=Experience.NOVICE)).methodology is Methodology.LINEAR_PROGRESSION


def test_a_nearby_meet_selects_block_periodization_for_a_non_novice():
    assert choose_methodology(profile(weeks_to_meet=12, rpe_logging_ratio=0.9)).methodology is Methodology.BLOCK_PERIODIZATION


def test_an_advanced_equipped_four_day_lifter_selects_conjugate():
    choice = choose_methodology(profile(experience=Experience.ADVANCED, has_specialty_equipment=True))
    assert choice.methodology is Methodology.CONJUGATE


def test_consistent_rpe_data_selects_autoregulation():
    assert choose_methodology(profile(rpe_logging_ratio=0.6)).methodology is Methodology.AUTOREGULATED_RPE


def test_training_max_progression_is_the_conservative_fallback():
    choice = choose_methodology(profile(days_per_week=3))
    assert choice.methodology is Methodology.FIVE_THREE_ONE
    assert "coach-approved training max" in choice.required_inputs


def test_explicit_athlete_or_coach_choice_wins():
    choice = choose_methodology(profile(experience=Experience.NOVICE, preferred=Methodology.CONJUGATE))
    assert choice.methodology is Methodology.CONJUGATE
    assert "explicitly" in choice.reasons[0]


def test_an_open_injury_suppresses_programming_entirely():
    choice = choose_methodology(profile(injured=True))
    assert choice.methodology is None
    assert choice.actionable is False


def test_profile_bounds_are_validated():
    with pytest.raises(ValueError):
        profile(days_per_week=0)
    with pytest.raises(ValueError):
        profile(rpe_logging_ratio=1.1)


def test_linear_and_conjugate_sessions_rotate_deterministically():
    assert session_structure(Methodology.LINEAR_PROGRESSION, 1).slot == "full-body A"
    assert session_structure(Methodology.LINEAR_PROGRESSION, 2).slot == "full-body B"
    assert session_structure(Methodology.CONJUGATE, 3).slot == "dynamic-effort lower"
    assert session_structure(Methodology.CONJUGATE, 5).slot == "max-effort lower"


def test_531_requires_an_approved_training_max_instead_of_inventing_one():
    session = session_structure(Methodology.FIVE_THREE_ONE, 6)
    assert session.slot == "cycle week 2 · bench press"
    assert "approved training max" in session.main_work


def test_block_sessions_require_an_explicit_phase():
    missing = session_structure(Methodology.BLOCK_PERIODIZATION, 1)
    ready = session_structure(Methodology.BLOCK_PERIODIZATION, 1, block_phase="accumulation")
    assert missing.actionable is False
    assert ready.actionable is True


def test_session_output_is_suppressed_when_injured():
    session = session_structure(Methodology.AUTOREGULATED_RPE, 1, injured=True)
    assert session.actionable is False
    assert "No load-bearing session" in session.main_work


def test_same_inputs_always_return_the_same_objects():
    p = profile(rpe_logging_ratio=0.8)
    assert len({choose_methodology(p) for _ in range(50)}) == 1
    assert len({session_structure(Methodology.AUTOREGULATED_RPE, 7) for _ in range(50)}) == 1

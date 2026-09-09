from __future__ import annotations

from app.decision.readiness import (
    DailyCheckIn,
    ReadinessBand,
    evaluate_readiness,
    summarize_nutrition,
)


def checkin(**overrides) -> DailyCheckIn:
    values = {
        "checked_on": "2026-09-09",
        "sleep_hours": 8,
        "sleep_quality": 4,
        "readiness": 8,
        "soreness": 2,
        "stress": 3,
        "bodyweight_kg": 80,
        "protein_g": 144,
        "nutrition_adherence": 8,
    }
    values.update(overrides)
    return DailyCheckIn(**values)


def test_a_good_checkin_never_adds_load():
    result = evaluate_readiness(checkin())
    assert result.band is ReadinessBand.GREEN
    assert result.load_factor == 1.0


def test_readiness_can_only_hold_or_reduce_load():
    cases = [
        checkin(),
        checkin(sleep_hours=6.5),
        checkin(sleep_hours=5, readiness=4),
        checkin(sleep_hours=3),
    ]
    assert all(0 < evaluate_readiness(case).load_factor <= 1 for case in cases)


def test_extreme_soreness_suppresses_a_load_bearing_prescription():
    result = evaluate_readiness(checkin(soreness=9))
    assert result.band is ReadinessBand.RED
    assert result.actionable is False


def test_sleep_below_seven_is_visible_in_the_reason_trace():
    result = evaluate_readiness(checkin(sleep_hours=6.5))
    assert any("7-hour" in reason for reason in result.reasons)


def test_nutrition_summary_uses_reported_bodyweight_and_protein():
    summary = summarize_nutrition(checkin(bodyweight_kg=80, protein_g=144))
    assert summary.protein_g_per_kg == 1.8
    assert summary.protein_band == "within_general_sport_range"


def test_nutrition_summary_does_not_invent_missing_inputs():
    summary = summarize_nutrition(checkin(protein_g=None))
    assert summary.protein_g_per_kg is None
    assert summary.protein_band == "unknown"


def test_calories_are_tracked_but_not_judged_without_a_target():
    low = summarize_nutrition(checkin(calories=800))
    high = summarize_nutrition(checkin(calories=5000))
    assert low == high


def test_same_checkin_is_deterministic():
    item = checkin(sleep_hours=5.5, soreness=7, stress=8)
    assert len({evaluate_readiness(item) for _ in range(50)}) == 1

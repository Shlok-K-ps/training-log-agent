from __future__ import annotations

from app.config import Settings
from app.nutrition import NutritionProfile, Supplement, build_daily_plan


def profile(**overrides):
    values = {
        "diet_style": "vegetarian",
        "foods_available": ("rice", "dal", "paneer", "banana", "chicken"),
        "meals_per_day": 4,
    }
    values.update(overrides)
    return NutritionProfile(**values)


def test_plan_uses_only_accessible_diet_compatible_foods():
    plan = build_daily_plan(profile(), training_time="18:30")
    used = {food for meal in plan.meals for food in meal.foods}
    assert plan.actionable is True
    assert used <= {"rice", "dal", "paneer", "banana"}
    assert "chicken" not in used


def test_allergies_remove_matching_foods():
    plan = build_daily_plan(
        profile(
            allergies=("dairy",),
            foods_available=("rice", "milk", "curd", "paneer", "whey", "dal"),
        ),
        training_time="18:30",
    )
    used = {food for meal in plan.meals for food in meal.foods}
    assert used.isdisjoint({"milk", "curd", "paneer", "whey"})


def test_unknown_allergy_label_fails_closed_for_manual_review():
    plan = build_daily_plan(
        profile(allergies=("unmapped allergy",)), training_time="18:30"
    )
    assert plan.actionable is False
    assert "manual review" in plan.missing[0]


def test_no_cooking_access_filters_out_foods_that_require_preparation():
    plan = build_daily_plan(
        profile(
            cooking_access="none",
            foods_available=("rice", "dal", "bread", "paneer", "banana"),
        ),
        training_time="18:30",
    )
    used = {food for meal in plan.meals for food in meal.foods}
    assert "rice" not in used and "dal" not in used
    assert {"bread", "paneer"} <= used


def test_training_day_needs_both_protein_and_carbohydrate_access():
    no_protein = build_daily_plan(
        profile(foods_available=("rice", "banana")), training_time="18:30"
    )
    no_carb = build_daily_plan(
        profile(foods_available=("dal", "paneer")), training_time="18:30"
    )
    assert no_protein.actionable is False
    assert no_carb.actionable is False


def test_meals_are_placed_around_training():
    plan = build_daily_plan(profile(), training_time="18:30")
    schedule = {(meal.label, meal.time) for meal in plan.meals}
    assert ("pre-training meal", "16:30") in schedule
    assert ("post-training meal", "19:30") in schedule


def test_only_approved_supplements_are_scheduled():
    approved = Supplement(
        "creatine", 5, "g", "post_training", "team coach", True, True
    )
    unapproved = Supplement("mystery blend", 1, "scoop", "pre_training", None)
    plan = build_daily_plan(
        profile(), training_time="18:30", supplements=(approved, unapproved)
    )
    descriptions = " ".join(slot.description for slot in plan.supplements)
    assert "creatine 5 g" in descriptions
    assert "mystery blend" not in descriptions
    assert any("team-controlled approval list" in note for note in plan.notes)


def test_self_reported_or_unverified_regimens_fail_closed():
    self_reported = Supplement(
        "creatine", 5, "g", "post_training", "me", True, False
    )
    untested = Supplement(
        "creatine", 5, "g", "post_training", "team coach", False, True
    )
    plan = build_daily_plan(
        profile(), training_time="18:30", supplements=(self_reported, untested)
    )
    assert plan.supplements == ()
    notes = " ".join(plan.notes)
    assert "team-controlled approval list" in notes
    assert "batch-testing" in notes


def test_wada_guard_overrides_even_a_team_allowlist_mistake():
    prohibited = Supplement(
        "Ostarine", 25, "mg", "breakfast", "team coach", True, True
    )
    plan = build_daily_plan(
        profile(), training_time="18:30", supplements=(prohibited,)
    )
    assert plan.supplements == ()
    assert any("2026 prohibited-substance" in note for note in plan.notes)


def test_team_approval_requires_exact_regimen_and_verified_batch_marker():
    config = Settings()
    config.team_approved_supplement_regimens_raw = (
        "creatine|5|g|post_training|team coach|batch_verified;"
        "caffeine|200|mg|pre_training|team coach|unverified"
    )
    assert config.approved_supplement_source(
        "Creatine", 5, "G", "post_training"
    ) == "team coach"
    assert config.approved_supplement_source("creatine", 10, "g", "post_training") is None
    assert config.approved_supplement_source("caffeine", 200, "mg", "pre_training") is None


def test_planner_is_deterministic():
    first = build_daily_plan(profile(), training_time="18:30")
    second = build_daily_plan(profile(), training_time="18:30")
    assert first == second


def test_unreviewed_targets_are_not_described_as_approved():
    plan = build_daily_plan(
        profile(protein_target_g=160, calorie_target=4200, approved_by=None),
        training_time="18:30",
    )
    notes = " ".join(plan.notes)
    assert "no professional review is recorded" in notes
    assert "approved calorie target" not in notes


def test_meals_and_supplements_move_out_of_calendar_events_and_use_bedtime():
    plan = build_daily_plan(
        profile(),
        training_time="18:30",
        busy_windows=(("16:00", "17:00"),),
        bedtime="22:45",
        supplements=(
            Supplement("approved pre", 1, "serving", "pre_training", "coach", True, True),
            Supplement("approved night", 1, "serving", "bedtime", "clinician", True, True),
        ),
    )
    meal_times = {meal.label: meal.time for meal in plan.meals}
    assert meal_times["pre-training meal"] == "15:45"
    assert any(
        slot.description.startswith("approved night") and slot.time == "22:45"
        for slot in plan.supplements
    )

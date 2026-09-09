from __future__ import annotations

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
        profile(allergies=("dairy", "paneer"), foods_available=("rice", "paneer", "dal")),
        training_time="18:30",
    )
    assert all("paneer" not in meal.foods for meal in plan.meals)


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
    approved = Supplement("creatine", 5, "g", "post_training", "coach")
    unapproved = Supplement("mystery blend", 1, "scoop", "pre_training", None)
    plan = build_daily_plan(
        profile(), training_time="18:30", supplements=(approved, unapproved)
    )
    descriptions = " ".join(slot.description for slot in plan.supplements)
    assert "creatine 5 g" in descriptions
    assert "mystery blend" not in descriptions
    assert any("Unapproved" in note for note in plan.notes)


def test_planner_is_deterministic():
    first = build_daily_plan(profile(), training_time="18:30")
    second = build_daily_plan(profile(), training_time="18:30")
    assert first == second

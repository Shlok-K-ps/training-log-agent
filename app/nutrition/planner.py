"""Food-access meal timing and approved supplement scheduling.

This module chooses only from foods the athlete says they can access. It never
creates a calorie target, diagnoses a deficiency, or recommends a supplement.
Supplement reminders require a recorded dose and named approval source.
"""

from __future__ import annotations

from dataclasses import dataclass


DIET_STYLES = {"omnivore", "vegetarian", "vegan", "pescatarian", "halal"}
COOKING_ACCESS = {"none", "basic", "full"}
SUPPLEMENT_TIMINGS = {
    "breakfast",
    "with_food",
    "pre_training",
    "post_training",
    "bedtime",
}

PROTEIN_FOODS = {
    "chicken": {"omnivore", "halal"},
    "fish": {"omnivore", "pescatarian", "halal"},
    "eggs": {"omnivore", "pescatarian", "halal"},
    "milk": {"omnivore", "vegetarian", "pescatarian", "halal"},
    "curd": {"omnivore", "vegetarian", "pescatarian", "halal"},
    "yogurt": {"omnivore", "vegetarian", "pescatarian", "halal"},
    "paneer": {"omnivore", "vegetarian", "pescatarian", "halal"},
    "tofu": DIET_STYLES,
    "soy chunks": DIET_STYLES,
    "dal": DIET_STYLES,
    "lentils": DIET_STYLES,
    "chickpeas": DIET_STYLES,
    "rajma": DIET_STYLES,
    "beans": DIET_STYLES,
    "whey": {"omnivore", "vegetarian", "pescatarian", "halal"},
    "plant protein": DIET_STYLES,
}

CARB_FOODS = {
    "rice", "roti", "bread", "oats", "potatoes", "pasta", "banana", "fruit"
}

PRODUCE_FOODS = {"vegetables", "fruit", "banana", "apple", "orange", "salad"}
NO_COOK_FOODS = {
    "bread", "banana", "fruit", "apple", "orange", "salad", "milk", "curd",
    "yogurt", "paneer", "tofu", "whey", "plant protein",
}


@dataclass(frozen=True)
class NutritionProfile:
    diet_style: str
    foods_available: tuple[str, ...]
    allergies: tuple[str, ...] = ()
    cooking_access: str = "basic"
    meals_per_day: int = 4
    protein_target_g: float | None = None
    calorie_target: float | None = None
    approved_by: str | None = None


@dataclass(frozen=True)
class Supplement:
    name: str
    dose: float
    unit: str
    timing: str
    approved_by: str | None
    batch_tested: bool | None = None


@dataclass(frozen=True)
class MealSlot:
    label: str
    time: str
    foods: tuple[str, ...]
    purpose: str


@dataclass(frozen=True)
class SupplementSlot:
    label: str
    time: str
    description: str


@dataclass(frozen=True)
class NutritionPlan:
    actionable: bool
    meals: tuple[MealSlot, ...]
    supplements: tuple[SupplementSlot, ...]
    notes: tuple[str, ...]
    missing: tuple[str, ...] = ()


def _minute(value: str) -> int:
    hour, minute = (int(piece) for piece in value.split(":"))
    return hour * 60 + minute


def _clock(minutes: int) -> str:
    minutes %= 24 * 60
    return f"{minutes // 60:02d}:{minutes % 60:02d}"


def _outside_busy(
    target: str,
    busy_windows: tuple[tuple[str, str], ...],
    *,
    prefer_earlier: bool,
) -> str:
    """Move a food/supplement time out of a busy event without changing the day."""
    minute = _minute(target)
    windows = sorted((_minute(start), _minute(end)) for start, end in busy_windows)
    for _ in range(len(windows) + 1):
        conflict = next(((start, end) for start, end in windows if start <= minute < end), None)
        if conflict is None:
            break
        start, end = conflict
        earlier = max(0, start - 15)
        later = min(23 * 60 + 59, end + 15)
        minute = earlier if prefer_earlier else later
    return _clock(minute)


def _allowed(food: str, diet_style: str, allergies: tuple[str, ...]) -> bool:
    normalized = food.lower().strip()
    if any(allergen.lower().strip() in normalized for allergen in allergies):
        return False
    styles = PROTEIN_FOODS.get(normalized)
    return styles is None or diet_style in styles


def _pick(available: tuple[str, ...], candidates: set[str], count: int = 2) -> tuple[str, ...]:
    return tuple(food for food in available if food.lower() in candidates)[:count]


def build_daily_plan(
    profile: NutritionProfile,
    *,
    training_time: str | None,
    supplements: tuple[Supplement, ...] = (),
    busy_windows: tuple[tuple[str, str], ...] = (),
    bedtime: str | None = None,
) -> NutritionPlan:
    """Build timing and choices without inventing foods, targets, or doses."""
    available = tuple(
        dict.fromkeys(
            food.strip().lower()
            for food in profile.foods_available
            if food.strip() and _allowed(food, profile.diet_style, profile.allergies)
        )
    )
    if profile.cooking_access == "none":
        available = tuple(food for food in available if food in NO_COOK_FOODS)
    proteins = _pick(available, set(PROTEIN_FOODS))
    carbs = _pick(available, CARB_FOODS)
    produce = _pick(available, PRODUCE_FOODS, 1)
    missing: list[str] = []
    if not proteins:
        missing.append("at least one accessible protein food compatible with the diet")
    if training_time and not carbs:
        missing.append("at least one accessible carbohydrate food for the training window")
    if missing:
        return NutritionPlan(False, (), (), (), tuple(missing))

    base_meal = tuple(dict.fromkeys(proteins[:1] + carbs[:1] + produce))
    baseline_meals: list[MealSlot] = [
        MealSlot("breakfast", "08:00", base_meal, "Start the day with available protein and food."),
        MealSlot("main meal", "13:00", base_meal, "Use only foods recorded as accessible."),
    ]
    training_meals: list[MealSlot] = []
    if training_time:
        training = _minute(training_time)
        training_meals.extend(
            [
                MealSlot(
                    "pre-training meal",
                    _clock(training - 120),
                    tuple(dict.fromkeys(carbs[:1] + proteins[:1])),
                    "Food before training; adjust comfort and portion with the athlete's professional.",
                ),
                MealSlot(
                    "post-training meal",
                    _clock(training + 60),
                    tuple(dict.fromkeys(proteins[:1] + carbs[:1] + produce)),
                    "Recovery meal from available foods.",
                ),
            ]
        )
    if training_meals:
        optional_count = max(0, profile.meals_per_day - len(training_meals))
        meals = baseline_meals[:optional_count] + training_meals
        if profile.meals_per_day == 1:
            meals = training_meals[-1:]
    else:
        meals = baseline_meals[: profile.meals_per_day]
    meals = [
        MealSlot(
            meal.label,
            _outside_busy(
                meal.time,
                busy_windows,
                prefer_earlier=meal.label == "pre-training meal",
            ),
            meal.foods,
            meal.purpose,
        )
        for meal in meals
    ]
    meals = sorted(meals, key=lambda meal: _minute(meal.time))
    meal_times = {meal.label: meal.time for meal in meals}

    supplement_slots: list[SupplementSlot] = []
    skipped_unapproved = False
    for supplement in supplements:
        if not supplement.approved_by:
            skipped_unapproved = True
            continue
        if supplement.timing in {"breakfast", "with_food"}:
            when = meal_times.get("breakfast", meals[0].time if meals else "08:00")
        elif supplement.timing == "pre_training" and training_time:
            when = _outside_busy(
                _clock(_minute(training_time) - 60), busy_windows, prefer_earlier=True
            )
        elif supplement.timing == "post_training" and training_time:
            when = meal_times.get(
                "post-training meal", _clock(_minute(training_time) + 60)
            )
        elif supplement.timing == "bedtime":
            when = bedtime or "21:30"
        else:
            continue
        supplement_slots.append(
            SupplementSlot(
                supplement.timing.replace("_", " "),
                when,
                f"{supplement.name} {supplement.dose:g} {supplement.unit} "
                f"(approved by {supplement.approved_by})",
            )
        )

    notes = ["Meal choices are limited to the athlete's recorded food access and exclusions."]
    if busy_windows:
        notes.append("Meal and approved-supplement times were moved outside calendar busy windows.")
    if profile.protein_target_g is not None:
        notes.append(f"Recorded professional/athlete protein target: {profile.protein_target_g:g} g/day.")
    if profile.calorie_target is not None:
        notes.append(f"Recorded approved calorie target: {profile.calorie_target:g} kcal/day.")
    if skipped_unapproved:
        notes.append("Unapproved supplements were not scheduled.")
    notes.append("This plan does not diagnose deficiencies or replace a dietitian or clinician.")
    return NutritionPlan(True, tuple(meals), tuple(supplement_slots), tuple(notes))

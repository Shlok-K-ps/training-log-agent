"""Pure daily-readiness and nutrition summaries.

The score is an explicit coaching policy, not a clinical instrument. It can
hold or reduce training load; it can never increase it. A check-in is useful
only on the day it was recorded, which the caller must enforce.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum


ADULT_SLEEP_FLOOR_HOURS = 7.0
PROTEIN_RANGE_G_PER_KG = (1.4, 2.0)


class ReadinessBand(str, Enum):
    GREEN = "green"
    YELLOW = "yellow"
    ORANGE = "orange"
    RED = "red"


@dataclass(frozen=True)
class DailyCheckIn:
    checked_on: str
    sleep_hours: float | None = None
    sleep_quality: int | None = None
    readiness: int | None = None
    soreness: int | None = None
    stress: int | None = None
    bodyweight_kg: float | None = None
    protein_g: float | None = None
    calories: float | None = None
    nutrition_adherence: int | None = None


@dataclass(frozen=True)
class NutritionSummary:
    protein_g_per_kg: float | None
    protein_band: str
    notes: tuple[str, ...]


@dataclass(frozen=True)
class ReadinessAssessment:
    score: int
    band: ReadinessBand
    load_factor: float
    actionable: bool
    reasons: tuple[str, ...]
    nutrition: NutritionSummary


def summarize_nutrition(checkin: DailyCheckIn) -> NutritionSummary:
    """Summarize reported intake without inventing calorie or macro targets."""
    if checkin.protein_g is None or checkin.bodyweight_kg is None:
        return NutritionSummary(
            protein_g_per_kg=None,
            protein_band="unknown",
            notes=("Protein per kg needs both bodyweight and protein intake.",),
        )

    ratio = round(checkin.protein_g / checkin.bodyweight_kg, 2)
    low, high = PROTEIN_RANGE_G_PER_KG
    if ratio < low:
        band = "below_general_sport_range"
        note = f"Reported protein is {ratio:g} g/kg, below the general {low:g}-{high:g} g/kg sport range."
    elif ratio <= high:
        band = "within_general_sport_range"
        note = f"Reported protein is {ratio:g} g/kg, within the general {low:g}-{high:g} g/kg sport range."
    else:
        band = "above_general_sport_range"
        note = (
            f"Reported protein is {ratio:g} g/kg, above the general {low:g}-{high:g} g/kg range; "
            "this assistant does not assess medical suitability."
        )
    return NutritionSummary(protein_g_per_kg=ratio, protein_band=band, notes=(note,))


def evaluate_readiness(checkin: DailyCheckIn) -> ReadinessAssessment:
    """Convert self-reported recovery data into a non-increasing load factor."""
    score = 100
    reasons: list[str] = []

    if checkin.sleep_hours is not None:
        if checkin.sleep_hours < 4:
            score -= 40
            reasons.append("Under 4 hours of sleep is a severe recovery flag.")
        elif checkin.sleep_hours < 6:
            score -= 25
            reasons.append("Under 6 hours of sleep substantially lowers today's readiness.")
        elif checkin.sleep_hours < ADULT_SLEEP_FLOOR_HOURS:
            score -= 15
            reasons.append("Sleep is below the adult 7-hour consensus floor.")

    if checkin.sleep_quality is not None:
        if checkin.sleep_quality <= 2:
            score -= 15
            reasons.append("Reported sleep quality is low.")
        elif checkin.sleep_quality == 3:
            score -= 5

    if checkin.readiness is not None:
        if checkin.readiness <= 2:
            score -= 35
            reasons.append("Self-rated readiness is extremely low.")
        elif checkin.readiness <= 4:
            score -= 20
            reasons.append("Self-rated readiness is low.")
        elif checkin.readiness <= 6:
            score -= 10

    if checkin.soreness is not None:
        if checkin.soreness >= 9:
            score -= 35
            reasons.append("Reported soreness is extremely high.")
        elif checkin.soreness >= 7:
            score -= 20
            reasons.append("Reported soreness is high.")
        elif checkin.soreness >= 5:
            score -= 10

    if checkin.stress is not None:
        if checkin.stress >= 8:
            score -= 15
            reasons.append("Reported stress is very high.")
        elif checkin.stress >= 6:
            score -= 5

    if checkin.nutrition_adherence is not None:
        if checkin.nutrition_adherence <= 3:
            score -= 15
            reasons.append("Nutrition adherence is very low today.")
        elif checkin.nutrition_adherence <= 5:
            score -= 5

    score = max(0, min(100, score))
    severe = (
        (checkin.sleep_hours is not None and checkin.sleep_hours < 4)
        or (checkin.readiness is not None and checkin.readiness <= 2)
        or (checkin.soreness is not None and checkin.soreness >= 9)
    )
    if severe or score < 45:
        band, factor, actionable = ReadinessBand.RED, 0.90, False
    elif score < 60:
        band, factor, actionable = ReadinessBand.ORANGE, 0.95, True
    elif score < 75:
        band, factor, actionable = ReadinessBand.YELLOW, 0.975, True
    else:
        band, factor, actionable = ReadinessBand.GREEN, 1.0, True

    if not reasons:
        reasons.append("No readiness reduction was triggered by the reported check-in.")
    return ReadinessAssessment(
        score=score,
        band=band,
        load_factor=factor,
        actionable=actionable,
        reasons=tuple(reasons),
        nutrition=summarize_nutrition(checkin),
    )

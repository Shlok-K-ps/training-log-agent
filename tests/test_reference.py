"""The empirical constants are re-derived from the source data on every run.

`app/reference.py` hard-codes numbers so the runtime never parses a CSV. These
tests are what stop those numbers from quietly becoming folklore: they recompute
each one from `reference/openpowerlifting_top_lifters.csv` and fail if the code
and the data have parted ways.
"""

from __future__ import annotations

import csv
from pathlib import Path

import pytest

from app.reference import (
    CEILING_HEADROOM,
    DEFAULT_CEILING_KG,
    ELITE_RATIO_RANGE,
    LB_TO_KG,
    LIFT_CEILING_KG,
    OBSERVED_MAX_KG,
    RATIO_BAND_VS_SQUAT,
    ceiling_for,
)

CSV_PATH = Path(__file__).resolve().parents[1] / "reference" / "openpowerlifting_top_lifters.csv"


@pytest.fixture(scope="module")
def lifters() -> list[dict[str, float | str]]:
    with CSV_PATH.open() as handle:
        rows = list(csv.DictReader(line for line in handle if not line.startswith("#")))
    for row in rows:
        for column in ("bodyweight_lb", "squat_lb", "bench_lb", "deadlift_lb", "total_lb", "dots"):
            row[column] = float(row[column])
    return rows


def kg(pounds: float) -> float:
    return pounds * LB_TO_KG


# --- the data itself ----------------------------------------------------------


def test_the_sample_is_large_enough_to_bound_anything(lifters):
    assert len(lifters) >= 100


def test_every_row_is_internally_consistent(lifters):
    """squat + bench + deadlift must equal the recorded total.

    This is a transcription check. The sample was read off screenshots by hand,
    and a mistyped digit that survives here would silently move a ceiling.
    """
    for row in lifters:
        parts = row["squat_lb"] + row["bench_lb"] + row["deadlift_lb"]
        assert parts == pytest.approx(row["total_lb"], abs=0.35), row["lifter"]


def test_both_sexes_are_represented(lifters):
    sexes = {row["sex"] for row in lifters}
    assert sexes == {"M", "F"}


# --- the derived maxima -------------------------------------------------------


@pytest.mark.parametrize(
    "lift,column",
    [("squat", "squat_lb"), ("bench press", "bench_lb"), ("deadlift", "deadlift_lb")],
)
def test_observed_maxima_match_the_data(lifters, lift, column):
    observed = max(kg(row[column]) for row in lifters)
    assert OBSERVED_MAX_KG[lift] == pytest.approx(observed, abs=0.1)


@pytest.mark.parametrize("lift", ["squat", "bench press", "deadlift"])
def test_every_ceiling_sits_above_the_best_lift_ever_recorded(lift):
    """A validator that rejects a real lift is worse than one that lets a fake through."""
    assert LIFT_CEILING_KG[lift] > OBSERVED_MAX_KG[lift]


@pytest.mark.parametrize("lift", ["squat", "bench press", "deadlift"])
def test_ceilings_are_not_absurdly_loose(lift):
    """Headroom, but not so much that the ceiling stops catching parse errors."""
    assert LIFT_CEILING_KG[lift] <= OBSERVED_MAX_KG[lift] * CEILING_HEADROOM * 1.2


def test_the_bench_ceiling_is_far_below_the_squat_ceiling():
    """The whole point of per-lift ceilings. A single global cap cannot do this."""
    assert LIFT_CEILING_KG["bench press"] < LIFT_CEILING_KG["squat"] * 0.7


def test_unknown_lifts_fall_back_to_a_loose_but_finite_ceiling():
    assert ceiling_for("zercher shrug") == DEFAULT_CEILING_KG
    assert ceiling_for(None) == DEFAULT_CEILING_KG
    assert ceiling_for("squat") == LIFT_CEILING_KG["squat"]


# --- the derived ratios -------------------------------------------------------


@pytest.mark.parametrize(
    "lift,column", [("bench press", "bench_lb"), ("deadlift", "deadlift_lb")]
)
def test_elite_ratio_envelope_matches_the_data(lifters, lift, column):
    ratios = [row[column] / row["squat_lb"] for row in lifters]
    low, high = ELITE_RATIO_RANGE[lift]
    assert low == pytest.approx(min(ratios), abs=0.01)
    assert high == pytest.approx(max(ratios), abs=0.01)


@pytest.mark.parametrize("lift", ["bench press", "deadlift"])
def test_the_flagging_band_is_wider_than_the_elite_envelope(lift):
    """Club athletes are less balanced than world-record holders. The band has to
    hold every one of them, or the log fills with false alarms."""
    elite_low, elite_high = ELITE_RATIO_RANGE[lift]
    band_low, band_high = RATIO_BAND_VS_SQUAT[lift]
    assert band_low < elite_low
    assert band_high > elite_high


def test_no_lifter_in_the_sample_would_be_flagged(lifters):
    """The strongest possible check on the bands: run the real data through them."""
    from app.decision.plausibility import check_ratio

    for row in lifters:
        squat = kg(row["squat_lb"])
        for lift, column in (("bench press", "bench_lb"), ("deadlift", "deadlift_lb")):
            flag = check_ratio(lift, kg(row[column]), squat)
            assert flag is None, f"{row['lifter']}: {flag}"


def test_no_lifter_in_the_sample_would_hit_a_ceiling(lifters):
    from app.decision.plausibility import check_ceiling

    for row in lifters:
        for lift, column in (
            ("squat", "squat_lb"),
            ("bench press", "bench_lb"),
            ("deadlift", "deadlift_lb"),
        ):
            assert check_ceiling(lift, kg(row[column])) is None, row["lifter"]

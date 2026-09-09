"""Empirical constants, derived from real competition results.

Every number in this file traces to `reference/openpowerlifting_top_lifters.csv`
— the top ~115 lifters of all time by Dots, Raw+Wraps, taken from
openpowerlifting.org. `tests/test_reference.py` recomputes the derivations from
that file and fails if a constant here stops matching the data.

Why bother. The validator's job is not to reject impossible lifts; nobody is
going to text their coach a 900 kg bench. Its job is to catch *parse errors* —
"one forty" landing as 14, a rep count read as a weight, pounds read as
kilograms. A single global ceiling of 600 kg catches almost none of those,
because it is far above every real lift for every movement. Per-lift ceilings set
just above what humans have actually done are tighter by a factor of two on the
bench, and tighter still once ratios are considered.

What this data can and cannot tell you. OpenPowerlifting is *meet* data: single
maximal attempts on a platform, months apart. It bounds what is physically
possible and how the three lifts relate to each other. It contains no training
sessions at all, so it says nothing about week-to-week progression, what a stall
looks like, or whether 85% is the right deload. Those live in `decision/rules.py`
as coaching policy, and are labelled as such.
"""

from __future__ import annotations

LB_TO_KG = 0.45359237

# --- what the top ~115 lifters of all time have actually done -----------------
# Computed from the reference CSV; see tests/test_reference.py.

OBSERVED_MAX_KG: dict[str, float] = {
    "squat": 500.0,        # Daniel Bell, 1102.3 lb, wraps
    "bench press": 292.6,  # Larry Williams, 645.0 lb, raw
    "deadlift": 492.5,     # Colton Engelbrecht, 1085.7 lb, raw
}

CEILING_HEADROOM = 1.15
"""How far above the best lift ever recorded a ceiling sits.

Generous on purpose. A validator that rejects a real lift is worse than one that
lets an implausible one through, because the athlete loses data and trust while
the implausible one gets caught by the ratio and history checks below.
"""

LIFT_CEILING_KG: dict[str, float] = {
    "squat": 575.0,          # 500.0 observed x 1.15
    "bench press": 340.0,    # 292.6 observed x 1.15
    "deadlift": 570.0,       # 492.5 observed x 1.15
    "front squat": 400.0,    # not in the dataset; ~0.7 of the squat ceiling
    "sumo deadlift": 570.0,  # same movement, same ceiling
    "romanian deadlift": 400.0,
    "overhead press": 250.0,  # not in the dataset; strict-press records sit ~230
    "barbell row": 300.0,
}

DEFAULT_CEILING_KG = 400.0
"""For accessory lifts with no competition data. Loose, but not unbounded."""


def ceiling_for(lift: str | None) -> float:
    return LIFT_CEILING_KG.get(lift or "", DEFAULT_CEILING_KG)


# --- how the three lifts relate to each other ---------------------------------
# Elite envelopes, straight from the sample:
#     bench / squat      0.38 - 0.76   (median 0.58)
#     deadlift / squat   0.79 - 1.41   (median 1.01)
#
# Those are tight because elite lifters are, by selection, balanced. A club
# athlete six months into training is not: someone rehabbing a knee may bench
# near their squat, and a natural puller may deadlift far above it. So the bands
# used for flagging are widened well past the elite envelope. Outside these, the
# most likely explanation is not an unusual athlete but two numbers swapped
# during parsing.

ELITE_RATIO_RANGE: dict[str, tuple[float, float]] = {
    "bench press": (0.38, 0.76),
    "deadlift": (0.79, 1.41),
}

RATIO_BAND_VS_SQUAT: dict[str, tuple[float, float]] = {
    "bench press": (0.25, 1.10),
    "deadlift": (0.55, 1.90),
}


# --- session-to-session movement ----------------------------------------------

MAX_PLAUSIBLE_SESSION_JUMP = 0.25
"""Fractional change from an athlete's own last session before we ask.

Scales to the individual in a way no global constant can: 140 kg is a suspicious
log for a 100 kg squatter and an ordinary backoff for a 200 kg one. Competition
data cannot supply this number — it has no sessions in it — so it is a judgement
call, set wide enough that real training never trips it. Peaking blocks and
deload weeks both move less than 25% between sessions.
"""

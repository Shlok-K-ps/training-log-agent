"""Deterministic lift-name normalisation.

The model is allowed to be sloppy about naming; this module is not. Every lift
name is folded to a canonical form *in Python* before it touches the database,
so "bp", "Bench", and "bench press" are one series in the history, always.
"""

from __future__ import annotations

import re

CANONICAL_LIFTS: dict[str, str] = {
    "squat": "squat",
    "back squat": "squat",
    "high bar squat": "squat",
    "low bar squat": "squat",
    "sq": "squat",
    "bench": "bench press",
    "bench press": "bench press",
    "bp": "bench press",
    "flat bench": "bench press",
    "deadlift": "deadlift",
    "dead lift": "deadlift",
    "dl": "deadlift",
    "conventional deadlift": "deadlift",
    "sumo deadlift": "sumo deadlift",
    "front squat": "front squat",
    "overhead press": "overhead press",
    "ohp": "overhead press",
    "shoulder press": "overhead press",
    "military press": "overhead press",
    "press": "overhead press",
    "romanian deadlift": "romanian deadlift",
    "rdl": "romanian deadlift",
    "barbell row": "barbell row",
    "bent over row": "barbell row",
    "row": "barbell row",
    "pull up": "pull up",
    "pullup": "pull up",
    "pull-up": "pull up",
    "chin up": "chin up",
    "chinup": "chin up",
}


def normalize_lift(name: str | None) -> str | None:
    """Fold a free-text lift name to its canonical form."""
    if name is None:
        return None
    cleaned = re.sub(r"[^a-z0-9 ]+", " ", name.strip().lower())
    cleaned = re.sub(r"\s+", " ", cleaned).strip()
    if not cleaned:
        return None
    if cleaned in CANONICAL_LIFTS:
        return CANONICAL_LIFTS[cleaned]
    # Strip a trailing plural and retry ("squats" -> "squat").
    if cleaned.endswith("s") and cleaned[:-1] in CANONICAL_LIFTS:
        return CANONICAL_LIFTS[cleaned[:-1]]
    return cleaned

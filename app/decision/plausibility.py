"""Is this logged number believable? Deterministic checks, no model.

Three checks, in increasing order of how much they know about the athlete:

1. **Ceiling** — above what any human has lifted. Rejected outright in
   `agent/schemas.py`, before storage.
2. **Ratio** — this lift against the athlete's own best on another lift. Catches
   the classic parse failure where two numbers in one message get swapped.
3. **History** — this session against their own last session on the same lift.
   The sharpest of the three, because it scales to the individual.

Checks 2 and 3 never reject. They attach a flag, the row is stored anyway, and
the reply asks the athlete to confirm. Dropping a real session to protect against
a possible typo is the worse failure: the athlete loses data they cannot get back
and stops trusting the log, while a wrong number they are asked about gets fixed
in one message.
"""

from __future__ import annotations

from dataclasses import dataclass

from app.reference import (
    MAX_PLAUSIBLE_SESSION_JUMP,
    RATIO_BAND_VS_SQUAT,
    ceiling_for,
)


@dataclass(frozen=True)
class Flag:
    """A reason to ask, not a reason to refuse."""

    code: str
    message: str


def check_ceiling(lift: str, weight_kg: float | None) -> Flag | None:
    """Above anything ever done in competition. Almost certainly a parse error."""
    if weight_kg is None:
        return None
    ceiling = ceiling_for(lift)
    if weight_kg > ceiling:
        return Flag(
            "above_ceiling",
            f"{weight_kg:g} kg is above the {ceiling:g} kg ceiling for {lift} — "
            "that is heavier than anyone has lifted in competition.",
        )
    return None


def check_ratio(lift: str, weight_kg: float | None, best_squat_kg: float | None) -> Flag | None:
    """Compare against the athlete's own best squat.

    The squat is the anchor because almost every programme trains it and it sits
    in the middle of the three lifts. If an athlete has no squat on record this
    check simply does not fire.
    """
    if weight_kg is None or not best_squat_kg:
        return None
    band = RATIO_BAND_VS_SQUAT.get(lift)
    if band is None:
        return None
    low, high = band
    ratio = weight_kg / best_squat_kg
    if ratio > high:
        return Flag(
            "ratio_high",
            f"{weight_kg:g} kg is {ratio:.1f}x your best squat ({best_squat_kg:g} kg). "
            f"For {lift} that is usually {low:g}-{high:g}x. Did two numbers get swapped?",
        )
    if ratio < low:
        return Flag(
            "ratio_low",
            f"{weight_kg:g} kg is only {ratio:.2f}x your best squat ({best_squat_kg:g} kg), "
            f"below the usual {low:g}-{high:g}x for {lift}. Logged as given.",
        )
    return None


def check_jump(
    lift: str, weight_kg: float | None, last_weight_kg: float | None
) -> Flag | None:
    """Compare against this athlete's own last session on this lift."""
    if weight_kg is None or not last_weight_kg:
        return None
    change = (weight_kg - last_weight_kg) / last_weight_kg
    if abs(change) <= MAX_PLAUSIBLE_SESSION_JUMP:
        return None
    direction = "up" if change > 0 else "down"
    return Flag(
        "big_jump",
        f"That is {abs(change) * 100:.0f}% {direction} from your last {lift} "
        f"session ({last_weight_kg:g} kg). Logged — reply if it should be something else.",
    )


def review(
    lift: str,
    weight_kg: float | None,
    *,
    last_weight_kg: float | None = None,
    best_squat_kg: float | None = None,
) -> list[Flag]:
    """Every flag that applies, most specific first.

    History beats ratio: an athlete's own last session is stronger evidence than
    a population-level relationship, so when both fire the athlete sees the one
    they can act on.
    """
    flags = [
        check_jump(lift, weight_kg, last_weight_kg),
        check_ratio(lift, weight_kg, best_squat_kg),
    ]
    return [f for f in flags if f is not None]

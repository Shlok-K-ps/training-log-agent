"""Deterministic training-management choices after a new injury report.

These are not diagnoses or rehabilitation prescriptions. Every option keeps the
injury gate open and gives the coach a bounded way to change training while a
qualified assessment/clearance is obtained.
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class InjuryPivot:
    code: str
    title: str
    plan: str
    rationale: str
    recommended: bool = False


_URGENT_WORDS = {"sharp", "pop", "swelling", "numb", "tingling", "cannot", "can't", "unstable"}
_LOWER_WORDS = {"knee", "hip", "ankle", "back", "hamstring", "quad", "groin", "leg"}
_UPPER_WORDS = {"shoulder", "elbow", "wrist", "pec", "chest", "arm", "neck"}


def injury_pivot_options(note: str | None) -> tuple[InjuryPivot, ...]:
    """Rank four conservative paths from the recorded injury description."""
    text = (note or "reported injury").casefold()
    urgent = any(word in text for word in _URGENT_WORDS)
    if any(word in text for word in _LOWER_WORDS):
        affected = "lower-body and axial loading"
        unaffected = "upper-body work"
    elif any(word in text for word in _UPPER_WORDS):
        affected = "upper-body loading"
        unaffected = "lower-body work"
    else:
        affected = "the affected movement pattern"
        unaffected = "clearly unaffected training"

    paths = (
        InjuryPivot(
            "full_hold",
            "Pause the full programme",
            "Pause planned training and load progression. Ask the athlete to obtain an appropriate qualified assessment; keep the injury flag open until independent clearance is recorded.",
            "Best when symptoms are new, severe, unclear, or affect normal movement.",
            recommended=urgent,
        ),
        InjuryPivot(
            "affected_hold",
            "Hold the affected pattern",
            f"Remove {affected} from the plan. Keep the injury flag open and do not prescribe a replacement load until the coach records a reviewed return path.",
            "Preserves the rest of the programme without experimenting on the painful pattern.",
            recommended=not urgent,
        ),
        InjuryPivot(
            "unaffected_only",
            "Train unaffected work only",
            f"Allow {unaffected} only when it is symptom-free. Cap effort at RPE 6, remove grinders, and stop the session if symptoms appear or change.",
            "Maintains routine while deliberately reducing fatigue and avoiding progression.",
        ),
        InjuryPivot(
            "recovery_microcycle",
            "Use a recovery microcycle",
            f"For the next seven days, omit {affected}; reduce clearly unaffected work to 70% of normal set volume with an RPE 6 cap. Re-review before the next microcycle.",
            "Creates a time-bounded pivot instead of letting a vague modified programme persist.",
        ),
    )
    return paths if urgent else (paths[1], paths[2], paths[3], paths[0])

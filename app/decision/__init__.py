"""Layer 3 — the decision engine. Plain Python, no model, no randomness.

Athletes act on what comes out of here, so it must be identical on every run and
provable line by line. Every rule in `rules.py` has a test in `tests/`.
"""

from app.decision.rules import (
    BAR_INCREMENT,
    DELOAD_FACTOR,
    DELOAD_STALL_EPISODES,
    STALL_FLAT_SESSIONS,
    STALL_FLAT_WITH_RPE,
    Assessment,
    SessionPoint,
    Verdict,
    evaluate,
    round_to_increment,
    to_session_points,
)

__all__ = [
    "Assessment",
    "SessionPoint",
    "Verdict",
    "evaluate",
    "to_session_points",
    "round_to_increment",
    "BAR_INCREMENT",
    "DELOAD_FACTOR",
    "DELOAD_STALL_EPISODES",
    "STALL_FLAT_SESSIONS",
    "STALL_FLAT_WITH_RPE",
]

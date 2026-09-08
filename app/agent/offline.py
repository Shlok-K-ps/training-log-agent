"""A regex stand-in for the model, for demos and tests without an API key.

This is NOT the product. It exists so the storage and decision layers can be
exercised end-to-end offline, and so the test suite never touches the network. It
handles exactly the tidy phrasings a regex can handle — which is the point: the
messy half is why Layer 1 uses a model at all.

    "squat 3x5 at 140kg rpe 8"        -> parsed here and by Gemini
    "squats felt awful, ground out    -> only Gemini
     the last two at one forty"
"""

from __future__ import annotations

import re
from typing import Any

SET_RE = re.compile(
    r"""(?P<lift>[a-zA-Z][a-zA-Z \-]{1,30}?)\s*
        (?:(?P<sets>\d{1,2})\s*[x×]\s*(?P<reps>\d{1,3}))?\s*
        (?:@|at|for)?\s*
        (?P<weight>\d{1,3}(?:\.\d)?)\s*(?P<unit>kgs?|kilos?|lbs?|pounds?)\b
        (?:[^0-9]{0,15}?rpe\s*(?P<rpe>\d{1,2}(?:\.\d)?))?
    """,
    re.IGNORECASE | re.VERBOSE,
)

QUERY_RE = re.compile(
    r"\b(stall|stalling|stalled|progress|progressing|going|plateau|deload|next)\b",
    re.IGNORECASE,
)
LIFT_IN_QUERY_RE = re.compile(
    r"\b(squat|bench(?: press)?|deadlift|ohp|overhead press|row|front squat|rdl)\b",
    re.IGNORECASE,
)
PHASE_RE = re.compile(r"\b(cut(?:ting)?|bulk(?:ing)?|maintenance|maintaining)\b", re.IGNORECASE)
INJURY_RE = re.compile(
    r"\b(hurt|pain|painful|tweak(?:ed)?|injur(?:y|ed)|strain(?:ed)?|niggle)\b", re.IGNORECASE
)
RECOVERED_RE = re.compile(r"\b(cleared|recovered|healed|all good now)\b", re.IGNORECASE)


class OfflineClient:
    """Implements the `ModelClient` protocol without a network call."""

    def call(self, text: str, system_instruction: str) -> list[tuple[str, dict[str, Any]]]:
        calls: list[tuple[str, dict[str, Any]]] = []
        lowered = text.lower()

        for match in SET_RE.finditer(text):
            unit = match.group("unit") or "kg"
            args: dict[str, Any] = {
                "lift": match.group("lift").strip(),
                "weight": float(match.group("weight")),
                "unit": "lb" if unit.lower().startswith(("lb", "pound")) else "kg",
            }
            if match.group("sets"):
                args["sets"] = int(match.group("sets"))
            if match.group("reps"):
                args["reps"] = int(match.group("reps"))
            if match.group("rpe"):
                args["rpe"] = float(match.group("rpe"))
            calls.append(("log_set", args))

        phase = PHASE_RE.search(lowered)
        if phase:
            word = phase.group(1)
            calls.append(
                ("log_status", {"phase": "cut" if word.startswith("cut") else "bulk" if word.startswith("bulk") else "maintain"})
            )

        if RECOVERED_RE.search(lowered):
            calls.append(("log_status", {"injured": False}))
        elif INJURY_RE.search(lowered):
            calls.append(("log_status", {"injured": True, "injury_note": text.strip()[:120]}))

        if QUERY_RE.search(lowered) and not any(c[0] == "log_set" for c in calls):
            lift = LIFT_IN_QUERY_RE.search(lowered)
            calls.append(("query_progress", {"lift": lift.group(1)} if lift else {}))

        if not calls:
            calls.append(
                ("clarify", {"question": "What lift, and what weight? e.g. squat 3x5 @ 140kg"})
            )
        return calls

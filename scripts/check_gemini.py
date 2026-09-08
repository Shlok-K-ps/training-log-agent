#!/usr/bin/env python3
"""Prove Layer 1 works: send messy human sentences to Gemini, print the schema
arguments it returns, then show what the validator does with them.

Run this on a machine that can reach generativelanguage.googleapis.com:

    export GEMINI_API_KEY=...      # or put it in .env
    python scripts/check_gemini.py

Nothing is written to the database. This only exercises the parsing boundary.
"""

from __future__ import annotations

import json
import sys
from datetime import date

from app.agent.parser import GeminiClient, build_system_instruction
from app.agent.schemas import ValidationError, validate_call
from app.config import settings

# Deliberately messy. A regex handles none of these; that is the argument for
# putting a model at this layer and nowhere else.
CASES = [
    "squats felt awful today, ground out the last two at one forty",
    "did 3x5 bench at 225lb yesterday, rpe 8. also tweaked my left shoulder on the last set",
    "am i stalling on deadlift?",
    "starting a cut monday",
    "did some squats",
    "5x3 @ 180 deads, easy. then 4 sets of 8 rows at 70",
]


def main() -> int:
    if not settings.gemini_api_key:
        print("GEMINI_API_KEY is not set. Put it in .env or export it.", file=sys.stderr)
        return 1

    today = date.today()
    client = GeminiClient()
    instruction = build_system_instruction(today)
    print(f"model: {settings.gemini_model}   today: {today}\n")

    failures = 0
    for text in CASES:
        print("=" * 78)
        print(f"athlete: {text}")
        try:
            calls = client.call(text, instruction)
        except Exception as exc:  # noqa: BLE001
            print(f"  !! model call failed: {type(exc).__name__}: {exc}")
            failures += 1
            continue

        if not calls:
            print("  !! model returned no tool call")
            failures += 1
            continue

        for name, args in calls:
            print(f"  raw   -> {name}({json.dumps(args, sort_keys=True)})")
            try:
                print(f"  valid -> {validate_call(name, args, today)}")
            except ValidationError as exc:
                print(f"  REJECTED by the validator: {exc}")
    print("=" * 78)
    print("done." if not failures else f"done, {failures} case(s) failed.")
    return 1 if failures else 0


if __name__ == "__main__":
    raise SystemExit(main())

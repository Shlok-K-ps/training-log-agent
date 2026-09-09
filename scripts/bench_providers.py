#!/usr/bin/env python3
"""Which model actually parses a training log properly? Measure it, don't guess.

Runs the same labelled cases through every provider whose key is in the
environment and scores each on whether it produced the right tool calls with the
right arguments. Nothing is written to the database.

    export GEMINI_API_KEY=...            # any subset
    export GROQ_API_KEY=...
    export GITHUB_MODELS_TOKEN=...
    python scripts/bench_providers.py

    python scripts/bench_providers.py --only gemini,groq --verbose

The cases are the ones that matter for this system, not a generic benchmark:
multi-lift messages, pounds, relative dates, an injury mentioned in passing, and
— the one most models get wrong — a message with no weight in it, where the only
correct answer is to ask rather than invent a number.
"""

from __future__ import annotations

import argparse
import os
import sys
import time
from dataclasses import dataclass
from datetime import date, timedelta
from typing import Any, Callable

from app.agent.parser import GeminiClient, build_system_instruction
from app.agent.providers import PROVIDERS, OpenAICompatClient
from app.agent.schemas import ValidationError, validate_call

TODAY = date(2026, 9, 8)  # a Tuesday, so "yesterday" and "monday" are unambiguous
YESTERDAY = (TODAY - timedelta(days=1)).isoformat()

Check = Callable[[list[Any]], "str | None"]


def find(actions: list[Any], kind: str) -> list[Any]:
    return [a for a in actions if type(a).__name__ == kind]


@dataclass
class Case:
    text: str
    why: str
    check: Check


def case_squat_no_numbers_but_a_weight(actions):
    sets = find(actions, "LogSet")
    if len(sets) != 1:
        return f"expected 1 log_set, got {len(sets)}"
    if sets[0].lift != "squat":
        return f"lift was {sets[0].lift!r}"
    if sets[0].weight_kg != 140:
        return f"weight was {sets[0].weight_kg} (should read 'one forty' as 140)"
    return None


def case_bench_lb_with_injury(actions):
    sets, status = find(actions, "LogSet"), find(actions, "LogStatus")
    if len(sets) != 1:
        return f"expected 1 log_set, got {len(sets)}"
    s = sets[0]
    if s.lift != "bench press":
        return f"lift was {s.lift!r}"
    if s.weight_kg is None or abs(s.weight_kg - 102.06) > 0.6:
        return f"weight was {s.weight_kg} kg (225 lb should convert to ~102.06)"
    if (s.sets, s.reps) != (3, 5):
        return f"sets/reps were {s.sets}x{s.reps}"
    if s.rpe != 8:
        return f"rpe was {s.rpe}"
    if s.session_date != YESTERDAY:
        return f"date was {s.session_date}, expected {YESTERDAY}"
    if not any(st.injured for st in status):
        return "missed the shoulder injury"
    return None


def case_question(actions):
    q = find(actions, "QueryProgress")
    if not q:
        return "did not call query_progress"
    if q[0].lift != "deadlift":
        return f"lift was {q[0].lift!r}"
    if find(actions, "LogSet"):
        return "invented a set from a question"
    return None


def case_phase(actions):
    status = find(actions, "LogStatus")
    if not any(s.phase == "cut" for s in status):
        return "did not record the cut"
    if find(actions, "LogSet"):
        return "invented a set"
    return None


def case_must_ask(actions):
    """The important one. No weight was given, so inventing one is the failure."""
    if find(actions, "Clarify"):
        return None
    sets = find(actions, "LogSet")
    if sets and sets[0].weight_kg is not None:
        return f"INVENTED a weight of {sets[0].weight_kg} kg"
    if sets:
        return None  # logged with a null weight — acceptable, not ideal
    return "neither asked nor logged"


def case_two_lifts(actions):
    sets = find(actions, "LogSet")
    if len(sets) != 2:
        return f"expected 2 log_set calls, got {len(sets)}"
    by_lift = {s.lift: s for s in sets}
    if "deadlift" not in by_lift:
        return f"lifts were {sorted(by_lift)}"
    dl = by_lift["deadlift"]
    if (dl.sets, dl.reps, dl.weight_kg) != (5, 3, 180.0):
        return f"deadlift parsed as {dl.sets}x{dl.reps} @ {dl.weight_kg}"
    row = by_lift.get("barbell row")
    if row is None:
        return f"row not recognised, got {sorted(by_lift)}"
    if (row.sets, row.reps, row.weight_kg) != (4, 8, 70.0):
        return f"row parsed as {row.sets}x{row.reps} @ {row.weight_kg}"
    return None


def case_no_rpe_from_a_feeling(actions):
    sets = find(actions, "LogSet")
    if len(sets) != 1:
        return f"expected 1 log_set, got {len(sets)}"
    if sets[0].rpe is not None:
        return f"invented an RPE of {sets[0].rpe} from 'felt easy'"
    return None


CASES = [
    Case("squats felt awful today, ground out the last two at one forty",
         "spelled-out weight, no set/rep notation", case_squat_no_numbers_but_a_weight),
    Case("did 3x5 bench at 225lb yesterday, rpe 8. also tweaked my left shoulder on the last set",
         "pounds + relative date + injury mentioned in passing", case_bench_lb_with_injury),
    Case("am i stalling on deadlift?",
         "a question, not a log", case_question),
    Case("starting a cut monday",
         "phase change, no set", case_phase),
    Case("did some squats",
         "NO weight given - must ask, not invent", case_must_ask),
    Case("5x3 @ 180 deads, easy. then 4 sets of 8 rows at 70",
         "two lifts, two notations, one message", case_two_lifts),
    Case("squat 3x5 at 140kg, felt easy",
         "'felt easy' is not an RPE", case_no_rpe_from_a_feeling),
]


def build_clients(only: set[str] | None):
    clients = []
    if os.getenv("GEMINI_API_KEY") and (not only or "gemini" in only):
        try:
            clients.append(("gemini", GeminiClient()))
        except Exception as exc:  # noqa: BLE001
            print(f"  ! gemini unavailable: {exc}", file=sys.stderr)
    for name, provider in PROVIDERS.items():
        if only and name not in only:
            continue
        if not os.getenv(provider.env_var):
            continue
        try:
            clients.append((name, OpenAICompatClient(provider)))
        except Exception as exc:  # noqa: BLE001
            print(f"  ! {name} unavailable: {exc}", file=sys.stderr)
    return clients


def run(name: str, client, verbose: bool) -> tuple[int, float]:
    instruction = build_system_instruction(TODAY)
    passed = 0
    elapsed = 0.0
    print(f"\n{'=' * 78}\n{name}\n{'=' * 78}")
    for case in CASES:
        started = time.perf_counter()
        try:
            raw = client.call(case.text, instruction)
        except Exception as exc:  # noqa: BLE001
            print(f"  FAIL  {case.text[:52]:<52}  call failed: {type(exc).__name__}")
            continue
        elapsed += time.perf_counter() - started

        actions, rejected = [], []
        for tool, args in raw:
            try:
                actions.append(validate_call(tool, args, TODAY))
            except ValidationError as exc:
                rejected.append(f"{tool}: {exc}")

        problem = case.check(actions)
        if problem is None:
            passed += 1
            print(f"  ok    {case.text[:52]:<52}  ({case.why})")
        else:
            print(f"  FAIL  {case.text[:52]:<52}  {problem}")
        if verbose or problem:
            for tool, args in raw:
                print(f"          raw: {tool}({args})")
            for r in rejected:
                print(f"          rejected by validator: {r}")
    return passed, elapsed


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--only", help="comma-separated provider names")
    parser.add_argument("--verbose", action="store_true", help="print every raw tool call")
    args = parser.parse_args()

    only = {s.strip() for s in args.only.split(",")} if args.only else None
    clients = build_clients(only)
    if not clients:
        print(
            "No provider keys found. Set at least one of:\n  GEMINI_API_KEY\n  "
            + "\n  ".join(p.env_var for p in PROVIDERS.values()),
            file=sys.stderr,
        )
        return 1

    results = [(name, *run(name, client, args.verbose)) for name, client in clients]

    print(f"\n{'=' * 78}\nSCOREBOARD  ({len(CASES)} cases)\n{'=' * 78}")
    print(f"{'provider':<14}{'passed':>8}{'total time':>13}{'  notes'}")
    for name, passed, elapsed in sorted(results, key=lambda r: (-r[1], r[2])):
        note = PROVIDERS[name].note if name in PROVIDERS else "free tier, native tool calling"
        print(f"{name:<14}{passed:>4}/{len(CASES):<3}{elapsed:>11.1f}s   {note}")
    print("\nUse the one that passes 'did some squats' — a model that invents a")
    print("weight there will quietly corrupt an athlete's history.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

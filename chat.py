#!/usr/bin/env python3
"""Local harness — talk to the agent from a terminal, no Twilio, no phone.

    python chat.py                      # real Gemini, real database
    python chat.py --offline            # regex stub, no API key needed
    python chat.py --db :memory:        # throwaway database
    python chat.py --demo               # replay a scripted 6-session stall

The WhatsApp layer is a transport. Everything the athlete sees is produced here
too, which is what makes the behaviour testable without a phone in the loop.
"""

from __future__ import annotations

import argparse
from datetime import date, timedelta

from app.agent.offline import OfflineClient
from app.agent.parser import GeminiClient, ModelClient
from app.config import settings
from app.router import handle_message
from app.storage import db

DEMO_ATHLETE = "+919000000001"

DEMO_SCRIPT: list[tuple[int, str]] = [
    (-28, "squat 3x5 at 130kg rpe 7"),
    (-25, "squat 3x5 at 130kg rpe 8"),
    (-21, "squat 3x5 at 130kg rpe 8.5"),
    (-18, "squat 3x5 at 120kg rpe 6"),
    (-14, "squat 3x5 at 132.5kg rpe 7.5"),
    (-11, "squat 3x5 at 135kg rpe 8"),
    (-7, "squat 3x5 at 135kg rpe 8.5"),
    (-3, "squat 3x5 at 135kg rpe 9"),
    (0, "am i stalling on squat?"),
]


def make_client(offline: bool) -> ModelClient:
    if offline or not settings.gemini_api_key:
        if not offline:
            print("! GEMINI_API_KEY not set - using the offline regex stub.\n")
        return OfflineClient()
    return GeminiClient()


def run_demo(conn, client: ModelClient) -> None:
    today = date.today()
    print("Replaying a scripted history for a single athlete.\n" + "-" * 60)
    for offset, message in DEMO_SCRIPT:
        when = today + timedelta(days=offset)
        print(f"\n[{when}] athlete: {message}")
        print(handle_message(conn, DEMO_ATHLETE, message, client, today=when))
    print("\n" + "-" * 60)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--offline", action="store_true", help="use the regex stub")
    parser.add_argument("--db", default=None, help="database path, or :memory:")
    parser.add_argument("--athlete", default=DEMO_ATHLETE, help="athlete phone id")
    parser.add_argument("--demo", action="store_true", help="replay a scripted history")
    args = parser.parse_args()

    conn = db.connect(args.db) if args.db else db.connect()
    db.init_db(conn)
    client = make_client(args.offline)

    if args.demo:
        run_demo(conn, client)
        return

    print("Training log. Type a session, a question, or 'help'. Ctrl-C to quit.\n")
    while True:
        try:
            message = input("you > ").strip()
        except (EOFError, KeyboardInterrupt):
            print()
            return
        if message.lower() in {"quit", "exit"}:
            return
        if not message:
            continue
        print()
        print(handle_message(conn, args.athlete, message, client))
        print()


if __name__ == "__main__":
    main()

#!/usr/bin/env python3
"""Close an athlete's injury flag. Operator tool — not reachable from WhatsApp.

This is the only path that opens the gate to load advice. It is a separate
command, run by a person, because the whole point of the Safety Guardian is
that no inbound message — and no model reading one — can do this.

    python scripts/clear_injury.py --athlete +919000000000 \\
        --actor "Coach Rao" --reason "physio cleared, full ROM, pain 0/10"

    python scripts/clear_injury.py --list        # who is currently flagged
"""

from __future__ import annotations

import argparse
import sys
from datetime import date
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app.decision.guardian import InjuryVeto, assess
from app.storage import db


def _open_injuries(conn, today: date) -> list[tuple[str, InjuryVeto]]:
    rows = conn.execute("SELECT DISTINCT athlete_id FROM entries").fetchall()
    out = []
    for row in rows:
        athlete = str(row["athlete_id"])
        outcome = assess(conn, athlete, today=today)
        if isinstance(outcome, InjuryVeto):
            out.append((athlete, outcome))
    return out


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--athlete", help="athlete id (E.164 phone number)")
    parser.add_argument("--actor", help="who is clearing it — a person, not the athlete")
    parser.add_argument("--reason", help="why, in enough detail to be reviewed later")
    parser.add_argument("--list", action="store_true", help="list open injury flags")
    parser.add_argument("--db", default=None, help="database path override")
    args = parser.parse_args(argv)

    conn = db.connect(args.db)
    db.init_db(conn)
    today = date.today()

    if args.list:
        rows = _open_injuries(conn, today)
        if not rows:
            print("No open injury flags.")
            return 0
        for athlete, veto in rows:
            days = f"{veto.days_open}d" if veto.days_open is not None else "?"
            asked = " · athlete has asked to be cleared" if veto.clearance_requested else ""
            stale = " · STALE" if veto.stale else ""
            print(f"{athlete}  open {days} since {veto.open_since}  "
                  f"({veto.note or 'no note'}){asked}{stale}")
        return 0

    missing = [f"--{n}" for n in ("athlete", "actor", "reason") if not getattr(args, n)]
    if missing:
        parser.error("clearing an injury requires " + ", ".join(missing))

    outcome = assess(conn, args.athlete, today=today)
    if not isinstance(outcome, InjuryVeto):
        print(f"{args.athlete} has no open injury flag. Nothing to clear.")
        return 1

    print(f"Athlete:   {args.athlete}")
    print(f"Open:      {outcome.days_open}d since {outcome.open_since} ({outcome.note or 'no note'})")
    print(f"Clearing:  {args.actor} — {args.reason}")
    print()
    print("This restores load suggestions for this athlete. A clinician should have")
    print("seen them. Type the athlete id again to confirm:")
    if input("> ").strip() != args.athlete.strip():
        print("Did not match. Nothing was changed.")
        return 1

    db.clear_injury(conn, args.athlete, actor=args.actor, reason=args.reason)
    print(f"Cleared. Recorded against {args.actor}.")
    return 0


if __name__ == "__main__":  # pragma: no cover
    sys.exit(main())

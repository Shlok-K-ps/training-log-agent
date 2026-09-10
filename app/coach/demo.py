"""A demo squad, so an empty console can show what a full one looks like.

On a fresh deployment nothing has texted the agent yet, so the roster is empty
and correct and completely uninformative. This loads eight fictional athletes
whose logs exercise every branch the console can show: a clearance waiting on
the coach, a stall, a regression, a deload, silence, an approaching meet, and
four people who are simply fine.

The athletes are obviously fictional and every id is in the +99900000000 range,
which is not a dialable number, so a demo row can never be confused with a real
athlete or texted by accident. `clear_demo_squad` removes exactly these rows and
nothing else.
"""

from __future__ import annotations

import sqlite3
from datetime import date, timedelta

from app.storage import db

# Reserved test range. Nothing real can collide with this.
DEMO_PREFIX = "+99900000"


def is_demo(athlete_id: str) -> bool:
    return athlete_id.startswith(DEMO_PREFIX)


def _sets(conn, athlete_id, name, weights, *, first_day, lift="squat", rpes=None, gap=3):
    for i, weight in enumerate(weights):
        db.insert_entry(
            conn,
            db.Entry(
                athlete_id=athlete_id,
                athlete_name=name,
                kind="set",
                lift=lift,
                sets=3,
                reps=5,
                weight_kg=weight,
                rpe=None if rpes is None else rpes[i],
                session_date=(first_day + timedelta(days=i * gap)).isoformat(),
            ),
        )


def seed_demo_squad(conn: sqlite3.Connection, *, today: date | None = None) -> int:
    """Load the demo squad. Returns how many athletes were added."""
    today = today or date.today()
    if any(is_demo(a) for a in db.list_athletes(conn)):
        return 0

    # 1. Blocked on the coach: injured, and has asked to be cleared.
    _sets(conn, f"{DEMO_PREFIX}001", "Priya Kulkarni", [122.5, 125],
          first_day=today - timedelta(days=26))
    db.insert_entry(conn, db.Entry(
        athlete_id=f"{DEMO_PREFIX}001", kind="status", injured=True,
        injury_note="left knee, squatting",
        session_date=(today - timedelta(days=23)).isoformat()))
    db.request_injury_clearance(
        conn, f"{DEMO_PREFIX}001", note="knee feels fine now",
        on=(today - timedelta(days=2)).isoformat())

    # 2. Stalled, with RPE climbing — the same bar getting harder.
    _sets(conn, f"{DEMO_PREFIX}002", "Rohit Sharma", [140, 140, 140, 140],
          rpes=[7, 8, 9, 9.5], first_day=today - timedelta(days=12))

    # 3. Gone quiet. The signal no athlete ever sends you.
    _sets(conn, f"{DEMO_PREFIX}003", "Neha Desai", [95, 97.5],
          first_day=today - timedelta(days=19))

    # 4. Regressed — logged as a backoff, not a stall.
    _sets(conn, f"{DEMO_PREFIX}004", "Sameer Bhat", [102.5, 100, 97.5],
          first_day=today - timedelta(days=9))

    # 5. Meet in five weeks.
    _sets(conn, f"{DEMO_PREFIX}005", "Ananya Rao", [150, 155],
          first_day=today - timedelta(days=4))
    db.insert_entry(conn, db.Entry(
        athlete_id=f"{DEMO_PREFIX}005", kind="status",
        meet_date=(today + timedelta(weeks=5)).isoformat(),
        experience="advanced", days_per_week=4,
        session_date=today.isoformat()))

    # 6-8. Progressing normally. These collapse into one line.
    for i, (name, start) in enumerate(
        [("Arjun Menon", 100.0), ("Kavya Suresh", 72.5), ("Dev Patel", 117.5)], start=6
    ):
        _sets(conn, f"{DEMO_PREFIX}00{i}", name,
              [start, start + 2.5, start + 5], rpes=[7, 7.5, 8],
              first_day=today - timedelta(days=7))

    # 9. Injured, but hasn't asked to be cleared — watch, not action.
    _sets(conn, f"{DEMO_PREFIX}009", "Vikram Iyer", [180, 185],
          lift="deadlift", first_day=today - timedelta(days=6))
    db.insert_entry(conn, db.Entry(
        athlete_id=f"{DEMO_PREFIX}009", kind="status", injured=True,
        injury_note="lower back, pulling",
        session_date=(today - timedelta(days=4)).isoformat()))

    return sum(1 for a in db.list_athletes(conn) if is_demo(a))


def clear_demo_squad(conn: sqlite3.Connection) -> int:
    """Remove every demo athlete. Touches nothing outside the demo range."""
    pattern = DEMO_PREFIX + "%"
    removed = conn.execute(
        "SELECT COUNT(DISTINCT athlete_id) AS n FROM entries WHERE athlete_id LIKE ?",
        (pattern,),
    ).fetchone()["n"]
    for table in ("entries", "outbound_drafts", "scheduled_deliveries",
                  "saved_places", "schedule_proposals", "scheduling_preferences",
                  "oauth_connections"):
        conn.execute(f"DELETE FROM {table} WHERE athlete_id LIKE ?", (pattern,))
    conn.commit()
    return int(removed)

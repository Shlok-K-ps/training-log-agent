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


def _profile(
    conn, athlete_id, *, bodyweight, squat, bench, deadlift, days, experience,
    goal_lift=None, goal_target=None, goal_start=None, goal_date=None,
):
    conn.execute(
        """
        INSERT INTO athlete_profile_revisions
            (athlete_id, bodyweight_kg, squat_1rm_kg, bench_1rm_kg,
             deadlift_1rm_kg, training_days, experience, goal_lift,
             goal_target_kg, goal_start_date, goal_target_date, created_by, created_at)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 'Demo coach', ?)
        """,
        (
            athlete_id, bodyweight, squat, bench, deadlift, days, experience,
            goal_lift, goal_target, goal_start, goal_date,
            (goal_start or date.today().isoformat()) + "T00:00:00+00:00",
        ),
    )
    conn.commit()


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

    # Mixed same-day recovery signals make the readiness UI useful at first load.
    checkins = (
        ("002", 5.0, 4, 7, 7, 83.0),
        ("004", 6.5, 6, 5, 5, 76.0),
        ("005", 8.0, 9, 2, 2, 68.0),
        ("006", 7.5, 8, 3, 3, 91.0),
        ("008", 7.0, 7, 4, 4, 88.0),
    )
    for suffix, sleep, readiness, soreness, stress, bodyweight in checkins:
        db.insert_entry(conn, db.Entry(
            athlete_id=f"{DEMO_PREFIX}{suffix}", kind="status",
            sleep_hours=sleep, sleep_quality=max(1, min(10, readiness)),
            readiness=readiness, soreness=soreness, stress=stress,
            bodyweight_kg=bodyweight, session_date=today.isoformat()))

    # Three goal shapes: behind, on track, and ahead of the linear checkpoint.
    began = (today - timedelta(weeks=6)).isoformat()
    deadline = (today + timedelta(weeks=6)).isoformat()
    profiles = (
        ("001", 62, 125, 67.5, 145, 3, "intermediate", None, None),
        ("002", 83, 160, 105, 190, 4, "intermediate", "squat", 190),
        ("003", 71, 105, 62.5, 130, 3, "novice", None, None),
        ("004", 76, 120, 82.5, 150, 4, "intermediate", None, None),
        ("005", 68, 170, 92.5, 190, 4, "advanced", "squat", 195),
        ("006", 91, 110, 90, 175, 4, "intermediate", "squat", 125),
        ("007", 59, 82.5, 50, 105, 3, "novice", None, None),
        ("008", 88, 130, 95, 180, 4, "intermediate", None, None),
        ("009", 96, 190, 125, 220, 4, "advanced", None, None),
    )
    for suffix, bw, squat, bench, deadlift, days, experience, goal_lift, target in profiles:
        _profile(
            conn, f"{DEMO_PREFIX}{suffix}", bodyweight=bw, squat=squat,
            bench=bench, deadlift=deadlift, days=days, experience=experience,
            goal_lift=goal_lift, goal_target=target,
            goal_start=began if goal_lift else None,
            goal_date=deadline if goal_lift else None,
        )

    # Conversation, approval, schedule and failure examples for WhatsApp Desk.
    db.record_whatsapp_message(
        conn, athlete_id=f"{DEMO_PREFIX}002", direction="inbound",
        body="Slept 5 hours, readiness 4. Squat felt unusually heavy yesterday.",
        status="received", provider_sid="DEMO-IN-ROHIT", message_kind="athlete_feedback",
    )
    db.record_whatsapp_message(
        conn, athlete_id=f"{DEMO_PREFIX}001", direction="inbound",
        body="Knee is still uncomfortable on stairs. What should I train?",
        status="received", provider_sid="DEMO-IN-PRIYA", message_kind="injury",
    )
    db.record_whatsapp_message(
        conn, athlete_id=f"{DEMO_PREFIX}005", direction="outbound",
        body="Morning check-in received. Your meet-week plan is ready.",
        status="read", provider_sid="DEMO-OUT-ANANYA", message_kind="morning_checkin",
    )
    db.record_whatsapp_message(
        conn, athlete_id=f"{DEMO_PREFIX}003", direction="outbound",
        body="Morning check-in: how did you sleep and how ready do you feel?",
        status="failed", provider_sid="DEMO-OUT-NEHA", message_kind="morning_checkin",
    )
    db.create_draft(
        conn, f"{DEMO_PREFIX}002", "feedback_reply:DEMO-IN-ROHIT",
        today.isoformat(), "Readiness is low today. Hold the planned squat load while your coach reviews the session.",
    )
    db.create_draft(
        conn, f"{DEMO_PREFIX}006", "morning_checkin",
        (today + timedelta(days=1)).isoformat(),
        "Good morning — how many hours did you sleep, and what are readiness, soreness and stress from 1–10?",
    )
    db.create_draft(
        conn, f"{DEMO_PREFIX}005", "morning_checkin",
        (today + timedelta(days=1)).isoformat(),
        "Good morning — meet prep check-in. How did you sleep and how ready do you feel?",
    )
    db.review_draft(
        conn, f"{DEMO_PREFIX}005", "morning_checkin",
        (today + timedelta(days=1)).isoformat(), status="approved",
        reviewed_by="Demo coach",
    )

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
                  "oauth_connections", "whatsapp_messages",
                  "whatsapp_conversation_state", "athlete_profile_revisions",
                  "injury_plan_decisions"):
        conn.execute(f"DELETE FROM {table} WHERE athlete_id LIKE ?", (pattern,))
    conn.commit()
    return int(removed)

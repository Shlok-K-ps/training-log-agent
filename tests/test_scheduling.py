from __future__ import annotations

from datetime import datetime, timezone

from app.scheduling.morning import due_morning_prompts, send_due_morning_prompts
from app.storage import db

ATHLETE = "+919000000001"


def configured(conn):
    db.insert_entry(
        conn,
        db.Entry(
            athlete_id=ATHLETE,
            kind="status",
            timezone="Asia/Kolkata",
            morning_checkin_time="07:30",
            training_time="18:30",
            session_date="2026-09-09",
        ),
    )


def test_local_timezone_drives_the_morning_prompt(conn):
    configured(conn)
    now = datetime(2026, 9, 9, 2, 30, tzinfo=timezone.utc)
    (prompt,) = due_morning_prompts(conn, now_utc=now)
    assert prompt.athlete_id == ATHLETE
    assert "How many hours" in prompt.body and "18:30" in prompt.body


def test_delivery_is_recorded_and_not_repeated(conn):
    configured(conn)
    now = datetime(2026, 9, 9, 2, 30, tzinfo=timezone.utc)
    sent: list[tuple[str, str]] = []
    sender = lambda athlete, body: sent.append((athlete, body))
    assert send_due_morning_prompts(conn, sender, now_utc=now) == 1
    assert send_due_morning_prompts(conn, sender, now_utc=now) == 0
    assert len(sent) == 1


def test_prompt_is_not_sent_outside_the_catchup_window(conn):
    configured(conn)
    late = datetime(2026, 9, 9, 7, 0, tzinfo=timezone.utc)
    assert due_morning_prompts(conn, now_utc=late) == []

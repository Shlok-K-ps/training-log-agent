"""The outbox: nothing proactive reaches an athlete without a coach seeing it.

The agent already messages first. That is the useful part and also the risky
part — an outbound message is the one thing an athlete cannot ignore, and it
arrives with the coach's authority attached whether or not the coach wrote it.

So the send is split in two. The evening before, the agent drafts tomorrow's
messages and puts them in a queue with the reason it wants to send each one. The
coach reads the queue, edits anything that reads wrong, and approves. In the
morning, only approved drafts go out.

Unreviewed means unsent. A coach who is asleep, busy or on holiday produces
silence, not an unsupervised broadcast — the same way an unset token closes the
console rather than opening it. Set COACH_APPROVAL_REQUIRED=false to return to
sending unattended.
"""

from __future__ import annotations

import sqlite3
from collections.abc import Callable
from datetime import datetime, timedelta, timezone
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from app.config import settings
from app.scheduling.morning import MorningPrompt, morning_prompt
from app.storage import db

MORNING = "morning_checkin"


def _local_now(conn: sqlite3.Connection, athlete_id: str, now_utc: datetime):
    """(local datetime, schedule settings) or None when the timezone is unusable."""
    schedule = db.latest_schedule_settings(conn, athlete_id)
    try:
        return now_utc.astimezone(ZoneInfo(str(schedule.get("timezone", "UTC")))), schedule
    except ZoneInfoNotFoundError:
        return None


def draft_upcoming_prompts(
    conn: sqlite3.Connection, *, now_utc: datetime | None = None
) -> list[MorningPrompt]:
    """Queue tomorrow's morning messages once the athlete's evening arrives.

    Drafting is per-athlete local time, so a coach with athletes in two
    timezones still reviews each one the evening before *their* morning.
    """
    now_utc = now_utc or datetime.now(timezone.utc)
    hour = min(23, max(0, int(settings.coach_draft_hour)))
    drafted: list[MorningPrompt] = []

    for athlete_id in db.list_scheduled_athletes(conn):
        resolved = _local_now(conn, athlete_id, now_utc)
        if resolved is None:
            continue
        local_now, schedule = resolved
        if local_now.hour < hour:
            continue

        target = (local_now + timedelta(days=1)).date().isoformat()
        if db.scheduled_delivery_exists(conn, athlete_id, MORNING, target):
            continue

        body = morning_prompt(
            str(schedule["training_time"]) if schedule.get("training_time") else None
        )
        if db.create_draft(conn, athlete_id, MORNING, target, body):
            drafted.append(MorningPrompt(athlete_id=athlete_id, local_date=target, body=body))
    return drafted


def send_approved_prompts(
    conn: sqlite3.Connection,
    sender: Callable[[str, str], None],
    *,
    now_utc: datetime | None = None,
) -> int:
    """Send the drafts a coach approved, at each athlete's check-in time.

    Reads the body from the draft, not from the generator, so the coach's edit
    is what the athlete actually receives.
    """
    from app.scheduling.morning import due_morning_prompts

    sent = 0
    for prompt in due_morning_prompts(conn, now_utc=now_utc):
        row = db.draft(conn, prompt.athlete_id, MORNING, prompt.local_date)

        if settings.coach_approval_required:
            if row is None or row["status"] != "approved":
                continue          # unreviewed or skipped: silence, not a broadcast
            body = str(row["body"])
        else:
            body = str(row["body"]) if row is not None and row["status"] == "approved" else prompt.body

        sender(prompt.athlete_id, body)
        db.mark_scheduled_delivery(conn, prompt.athlete_id, MORNING, prompt.local_date)
        if row is not None:
            db.mark_draft_sent(conn, prompt.athlete_id, MORNING, prompt.local_date)
        sent += 1
    return sent

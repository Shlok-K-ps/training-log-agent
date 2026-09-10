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
console rather than opening it. This is a product invariant, not configuration.
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
COACH_NOTE = "coach_note"
FEEDBACK_REPLY = "feedback_reply:"


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

        if row is None or row["status"] != "approved":
            continue          # unreviewed or skipped: silence, not a broadcast
        if db.invalidate_draft_if_evidence_changed(
            conn, prompt.athlete_id, MORNING, prompt.local_date
        ):
            continue          # newer check-in/injury/schedule fact needs fresh approval
        body = str(row["body"])

        sender(prompt.athlete_id, body)
        db.mark_scheduled_delivery(conn, prompt.athlete_id, MORNING, prompt.local_date)
        if row is not None:
            db.mark_draft_sent(conn, prompt.athlete_id, MORNING, prompt.local_date)
        sent += 1
    return sent


def send_approved_notes(
    conn: sqlite3.Connection,
    sender: Callable[[str, str], None],
    *,
    now_utc: datetime | None = None,
) -> int:
    """Send coach-written notes whose date has arrived, in the athlete's timezone.

    A note the coach typed and queued is already reviewed — they wrote it — so it
    carries status 'approved' from the moment it is created. This only decides
    *when* it leaves, and refuses to send one dated in the athlete's future.
    """
    now_utc = now_utc or datetime.now(timezone.utc)
    sent = 0
    for row in db.approved_drafts(conn, COACH_NOTE):
        athlete_id = str(row["athlete_id"])
        resolved = _local_now(conn, athlete_id, now_utc)
        local_today = (
            resolved[0].date().isoformat() if resolved else now_utc.date().isoformat()
        )
        if str(row["local_date"]) > local_today:
            continue
        sender(athlete_id, str(row["body"]))
        db.mark_draft_sent(conn, athlete_id, COACH_NOTE, str(row["local_date"]))
        sent += 1
    return sent


def send_approved_feedback(
    conn: sqlite3.Connection,
    sender: Callable[[str, str], None],
) -> int:
    """Send coach-approved responses to athlete feedback on the next worker tick."""
    sent = 0
    for row in db.approved_drafts_with_prefix(conn, FEEDBACK_REPLY):
        athlete_id = str(row["athlete_id"])
        message_kind = str(row["message_kind"])
        local_date = str(row["local_date"])
        if db.invalidate_draft_if_evidence_changed(
            conn, athlete_id, message_kind, local_date
        ):
            continue
        sender(athlete_id, str(row["body"]))
        db.mark_draft_sent(conn, athlete_id, message_kind, local_date)
        sent += 1
    return sent

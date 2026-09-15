"""The outbox: nothing proactive reaches an athlete without a coach seeing it.

The agent already messages first. That is the useful part and also the risky
part — an outbound message is the one thing an athlete cannot ignore, and it
arrives with the coach's authority attached whether or not the coach wrote it.

So the send is split in two. The evening before, the agent drafts tomorrow's
messages and puts them in a queue with the reason it wants to send each one. The
coach reads the queue, edits anything that reads wrong, and approves. In the
morning, only approved drafts go out.

Unreviewed means unsent. A coach who is asleep, busy or on holiday produces
silence, not an unsupervised broadcast. This is a product invariant, not configuration.
"""

from __future__ import annotations

import hashlib
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
INJURY_PLAN = FEEDBACK_REPLY + "injury:"


def coach_note_kind(body: str) -> str:
    """The key of a coach note is its content.

    Different notes on one day get different keys, so both go out. The same note
    typed or submitted twice gets the same key, so the database can hold it only
    once, even when two requests arrive together.
    """
    digest = hashlib.sha256(db.normalized_message(body).encode("utf-8")).hexdigest()[:12]
    return f"{COACH_NOTE}:{digest}"


NOTE_SENT_REASON = "Sent: written by the coach."
REPLY_SENT_REASON = "Sent: approved by the coach, and no newer athlete information had arrived."
CHECKIN_SENT_REASON = "Sent: approved check-in, and no newer athlete information had arrived."


def _deliver(conn: sqlite3.Connection, row, sender: Callable[[str, str], None], *, reason: str) -> bool:
    """Serialize one athlete through freshness validation and transport delivery.

    The durable lease is intentionally held across the Telegram call.  An inbound
    webhook records its raw message before it waits for that same lease, so a
    final validation sees evidence that arrived during an earlier reservation.
    """
    athlete_id, message_kind, local_date = (
        str(row["athlete_id"]), str(row["message_kind"]), str(row["local_date"])
    )
    try:
        # A competing tick yields immediately rather than blocking its worker.
        # The current owner finishes, and the next tick sees the durable result.
        with db.outbound_delivery_lease(conn, athlete_id, wait_seconds=0):
            # Reload after owning the athlete. A concurrent worker may have sent,
            # cancelled, or superseded this row while this worker was waiting.
            current = db.draft(conn, athlete_id, message_kind, local_date)
            if current is None or str(current["status"]) != "approved":
                return False
            stale = db.stale_draft_reason(conn, current)
            if stale is not None:
                db.supersede_draft(conn, athlete_id, message_kind, local_date, stale)
                return False
            # This last database check deliberately happens after lease ownership.
            # ``claim_draft_for_send`` no longer marks sent: only a successful
            # Telegram return below can do that.
            if not db.claim_draft_for_send(conn, athlete_id, message_kind, local_date, reason=reason):
                late = db.stale_draft_reason(conn, current)
                if late is not None:
                    db.supersede_draft(conn, athlete_id, message_kind, local_date, late)
                return False
            try:
                sender(athlete_id, str(current["body"]))
            except Exception as exc:  # noqa: BLE001 - a later lease owner may retry
                db.mark_draft_failed(conn, athlete_id, message_kind, local_date, type(exc).__name__)
                return False
            return db.mark_draft_sent(conn, athlete_id, message_kind, local_date, reason=reason)
    except db.DeliveryLeaseBusy:
        # Do not turn contention into a failed draft. The next tick, or the
        # expired lease after a crashed owner, can safely make progress.
        return False


def message_kind_label(message_kind: str) -> str:
    """How a queued or sent message reads to the coach."""
    if message_kind == MORNING:
        return "Morning check-in"
    if message_kind == COACH_NOTE or message_kind.startswith(COACH_NOTE + ":"):
        return "Coach note"
    if message_kind.startswith(INJURY_PLAN):
        return "Injury plan"
    if message_kind.startswith(FEEDBACK_REPLY):
        return "Reply to athlete"
    return message_kind.replace("_", " ").capitalize()


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
        if _deliver(conn, row, sender, reason=CHECKIN_SENT_REASON):
            db.mark_scheduled_delivery(conn, prompt.athlete_id, MORNING, prompt.local_date)
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
    handled: set[tuple[str, str, str]] = set()
    return sum(
        _send_note(conn, row, sender, now_utc=now_utc, handled=handled)
        for row in db.approved_drafts_with_prefix(conn, COACH_NOTE)
    )


def _send_note(conn, row, sender, *, now_utc: datetime, handled: set) -> int:
    athlete_id = str(row["athlete_id"])
    message_kind, local_date = str(row["message_kind"]), str(row["local_date"])
    resolved = _local_now(conn, athlete_id, now_utc)
    local_today = resolved[0].date().isoformat() if resolved else now_utc.date().isoformat()
    if local_date > local_today:
        return 0
    identity = (athlete_id, local_date, db.normalized_message(row["body"]))
    already_sent = db.identical_note(
        conn, athlete_id, local_date, str(row["body"]), prefix=COACH_NOTE,
        statuses=("sent",), exclude_kind=message_kind,
    )
    if identity in handled or already_sent is not None:
        # An identical note for this athlete and day is already on its way.
        db.mark_draft_duplicate(conn, athlete_id, message_kind, local_date)
        return 0
    handled.add(identity)
    return int(_deliver(conn, row, sender, reason=NOTE_SENT_REASON))


def send_approved_feedback(
    conn: sqlite3.Connection,
    sender: Callable[[str, str], None],
) -> int:
    """Send coach-approved responses to athlete feedback, revalidated at the moment of sending."""
    return sum(
        int(_deliver(conn, row, sender, reason=REPLY_SENT_REASON))
        for row in db.approved_drafts_with_prefix(conn, FEEDBACK_REPLY)
    )


def send_approved_outbound(
    conn: sqlite3.Connection,
    sender: Callable[[str, str], None],
    *,
    now_utc: datetime | None = None,
) -> int:
    """Send every due coach note and coach-approved reply in one pass, oldest first.

    A single chronological pass keeps the athlete's conversation in the order the
    messages were written, whatever their kind; each is revalidated as it goes.
    """
    now_utc = now_utc or datetime.now(timezone.utc)
    rows = db.approved_drafts_with_prefix(conn, COACH_NOTE) + db.approved_drafts_with_prefix(conn, FEEDBACK_REPLY)
    rows.sort(key=lambda row: (str(row["created_at"]), str(row["local_date"]), str(row["message_kind"])))
    handled: set[tuple[str, str, str]] = set()
    sent = 0
    for row in rows:
        if str(row["message_kind"]).startswith(COACH_NOTE):
            sent += _send_note(conn, row, sender, now_utc=now_utc, handled=handled)
        else:
            sent += int(_deliver(conn, row, sender, reason=REPLY_SENT_REASON))
    return sent

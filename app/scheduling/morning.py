"""Proactive morning sleep check-ins with per-athlete local times."""

from __future__ import annotations

import sqlite3
from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime, timezone
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from app.decision.sleep import is_morning_prompt_due
from app.storage import db


@dataclass(frozen=True)
class MorningPrompt:
    athlete_id: str
    local_date: str
    body: str


def morning_prompt(training_time: str | None = None) -> str:
    training = f" Today's usual training time is {training_time}." if training_time else ""
    return (
        "Good morning — recovery check-in. How many hours did you sleep? "
        "Sleep quality 1–5, readiness 1–10, soreness 1–10, and stress 1–10?"
        f"{training} If you train today, include the lift and time so I can check a nap window."
    )


def due_morning_prompts(
    conn: sqlite3.Connection,
    *,
    now_utc: datetime | None = None,
) -> list[MorningPrompt]:
    now_utc = now_utc or datetime.now(timezone.utc)
    prompts: list[MorningPrompt] = []
    for athlete_id in db.list_scheduled_athletes(conn):
        settings = db.latest_schedule_settings(conn, athlete_id)
        try:
            local_now = now_utc.astimezone(ZoneInfo(str(settings.get("timezone", "UTC"))))
        except ZoneInfoNotFoundError:
            continue
        local_date = local_now.date().isoformat()
        checkin_time = str(settings.get("morning_checkin_time", "08:00"))
        if not is_morning_prompt_due(local_now, checkin_time):
            continue
        if db.scheduled_delivery_exists(conn, athlete_id, "morning_checkin", local_date):
            continue
        prompts.append(
            MorningPrompt(
                athlete_id=athlete_id,
                local_date=local_date,
                body=morning_prompt(
                    str(settings["training_time"]) if settings.get("training_time") else None
                ),
            )
        )
    return prompts


def send_due_morning_prompts(
    conn: sqlite3.Connection,
    sender: Callable[[str, str], None],
    *,
    now_utc: datetime | None = None,
) -> int:
    sent = 0
    for prompt in due_morning_prompts(conn, now_utc=now_utc):
        sender(prompt.athlete_id, prompt.body)
        db.mark_scheduled_delivery(
            conn, prompt.athlete_id, "morning_checkin", prompt.local_date
        )
        sent += 1
    return sent

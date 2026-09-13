"""How the agent reaches athletes and the coach.

Athletes are reached on their paired Telegram chat. Fictional demo athletes are
reached through the simulator, which writes the same ledger rows without
leaving the server. Anyone else cannot be reached, and the agent is told so
rather than assuming a message arrived.
"""

from __future__ import annotations

import uuid
from typing import Protocol

from app.casework import messages, store
from app.channels import telegram
from app.config import settings
from app.storage import db


class DeliveryFailed(RuntimeError):
    """The message did not leave. The agent must not treat it as sent."""


class Transport(Protocol):
    def send_athlete(self, conn, athlete_id: str, body: str, *, kind: str) -> str: ...

    def notify_coach(
        self, conn, *, case_id: int, athlete_name: str, local_date: str, title: str,
        evidence: list[str], options: tuple[tuple[str, str], ...],
    ) -> str | None: ...


class LiveTransport:
    """Telegram for paired athletes and the coach; the simulator for demo athletes."""

    def send_athlete(self, conn, athlete_id: str, body: str, *, kind: str) -> str:
        from app.coach.demo import is_demo

        chat_id = db.telegram_chat_id(conn, athlete_id)
        if settings.telegram_configured and chat_id:
            try:
                provider_id = telegram.send_outbound(chat_id, body)
            except RuntimeError as exc:
                raise DeliveryFailed(str(exc)) from None
            channel = "telegram"
        elif is_demo(athlete_id):
            provider_id = f"simulator:{uuid.uuid4().hex}"
            channel = "simulator"
        else:
            raise DeliveryFailed("This athlete has no connected Telegram chat.")
        db.record_whatsapp_message(
            conn, athlete_id=athlete_id, direction="outbound", body=body, status="sent",
            provider_sid=provider_id, message_kind=f"agent:{kind}", channel=channel,
        )
        return provider_id

    def notify_coach(
        self, conn, *, case_id: int, athlete_name: str, local_date: str, title: str,
        evidence: list[str], options: tuple[tuple[str, str], ...],
    ) -> str | None:
        from app.access import console_link

        chat_id = store.coach_chat_id(conn)
        if not (settings.telegram_configured and chat_id):
            return None
        keyboard = [
            [{"text": label, "callback_data": f"d:{case_id}:{code}"}] for code, label in options
        ]
        if settings.coach_link_secret and settings.public_base_url:
            keyboard.append([{"text": "Open the case", "url": console_link(f"/coach/case/{case_id}")}])
        text = messages.coach_escalation(athlete_name, local_date, title, evidence)
        try:
            return telegram.send_outbound(chat_id, text, reply_markup={"inline_keyboard": keyboard})
        except RuntimeError as exc:
            raise DeliveryFailed(str(exc)) from None

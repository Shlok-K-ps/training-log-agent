"""Vonage Messages API Sandbox adapter.

This module only translates transport shapes. Athlete messages still go
through the same parser, deterministic rules, approval queue and audit ledger.
"""

from __future__ import annotations

import hmac
import re

import httpx

from app.config import settings

MESSAGES_URL = "https://messages-sandbox.nexmo.com/v1/messages"


def athlete_id_from_sender(sender: str) -> str:
    """Normalise a Vonage phone number to the app's E.164 athlete identity."""
    digits = re.sub(r"\D", "", (sender or "").strip())
    return f"+{digits}" if digits else ""


def valid_webhook_secret(candidate: str | None) -> bool:
    """Protect the public demo webhook with an owner-generated secret."""
    expected = settings.vonage_webhook_secret
    return bool(expected and candidate and hmac.compare_digest(expected, candidate))


def send_outbound(athlete_id: str, body: str) -> str:
    """Send one WhatsApp text and return Vonage's delivery-tracking UUID."""
    api_key, api_secret, sandbox_number = settings.require_vonage()
    sender = re.sub(r"\D", "", sandbox_number)
    recipient = re.sub(r"\D", "", athlete_id)
    if not sender or not recipient:
        raise RuntimeError("Vonage sender and recipient must be valid phone numbers")
    response = httpx.post(
        MESSAGES_URL,
        auth=(api_key, api_secret),
        json={
            "from": sender,
            "to": recipient,
            "channel": "whatsapp",
            "message_type": "text",
            "text": body,
        },
        timeout=15.0,
    )
    response.raise_for_status()
    message_uuid = str(response.json().get("message_uuid", "")).strip()
    if not message_uuid:
        raise RuntimeError("Vonage accepted the request without a message_uuid")
    return message_uuid


def ledger_status(provider_status: str) -> str | None:
    """Map Vonage delivery callbacks onto the provider-neutral ledger."""
    return {
        "submitted": "sent",
        "delivered": "delivered",
        "read": "read",
        "rejected": "failed",
        "undeliverable": "failed",
    }.get((provider_status or "").strip().lower())

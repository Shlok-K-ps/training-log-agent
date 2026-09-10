"""WhatsApp plumbing: identity, signature checking, and message chunking.

WhatsApp is a transport, not a layer. Everything here is about getting bytes in
and out of Twilio; no parsing, no rules.
"""

from __future__ import annotations

import re
from xml.sax.saxutils import escape

from twilio.request_validator import RequestValidator
from twilio.rest import Client

from app.config import settings

# Twilio rejects WhatsApp bodies over 1600 characters.
MAX_BODY = 1500


def athlete_id_from_sender(sender: str) -> str:
    """Stable athlete identity: the E.164 number behind `whatsapp:+91...`.

    The phone number is the primary key. No sign-up, no passwords, and an athlete
    who changes handset keeps their history as long as they keep their number.
    """
    return re.sub(r"^whatsapp:", "", (sender or "").strip())


def is_valid_signature(url: str, form: dict[str, str], signature: str | None) -> bool:
    """Verify the request really came from Twilio.

    The webhook is a public URL that writes to the database. Without this, anyone
    who finds the URL can log sets as any athlete.
    """
    if not settings.validate_twilio_signature:
        return True
    if not settings.twilio_auth_token or not signature:
        return False
    validator = RequestValidator(settings.twilio_auth_token)
    return validator.validate(url, form, signature)


def webhook_url(request_url: str) -> str:
    """The URL Twilio signed.

    Behind a proxy (Render, ngrok) the app sees http://internal-host/... while
    Twilio signed https://public-host/..., and the signature check fails on a
    mismatch. PUBLIC_BASE_URL pins the value Twilio actually used.
    """
    if not settings.public_base_url:
        return request_url
    path = request_url.split("://", 1)[-1]
    path = path[path.find("/") :] if "/" in path else "/"
    return settings.public_base_url.rstrip("/") + path


def chunk(text: str, limit: int = MAX_BODY) -> list[str]:
    """Split a reply on paragraph, then line, then hard boundaries."""
    text = text.strip()
    if len(text) <= limit:
        return [text] if text else [""]

    chunks: list[str] = []
    current = ""
    for block in text.split("\n\n"):
        candidate = f"{current}\n\n{block}" if current else block
        if len(candidate) <= limit:
            current = candidate
            continue
        if current:
            chunks.append(current)
        while len(block) > limit:
            cut = block.rfind("\n", 0, limit)
            cut = cut if cut > limit // 2 else limit
            chunks.append(block[:cut].strip())
            block = block[cut:].strip()
        current = block
    if current:
        chunks.append(current)
    return chunks


def twiml(messages: list[str]) -> str:
    """Build the TwiML reply by hand — one dependency fewer, and easy to read."""
    body = "".join(f"<Message>{escape(m)}</Message>" for m in messages if m)
    return f'<?xml version="1.0" encoding="UTF-8"?><Response>{body}</Response>'


def send_outbound(athlete_id: str, body: str) -> str:
    """Send one proactive WhatsApp message through the configured Twilio sender."""
    sid, token, sender = settings.require_twilio()
    recipient = athlete_id if athlete_id.startswith("whatsapp:") else f"whatsapp:{athlete_id}"
    options = {"from_": sender, "to": recipient, "body": body}
    if settings.public_base_url:
        options["status_callback"] = (
            settings.public_base_url.rstrip("/") + "/webhook/whatsapp/status"
        )
    message = Client(sid, token).messages.create(**options)
    return str(message.sid)

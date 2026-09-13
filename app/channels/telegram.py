"""Telegram Bot API transport and signed athlete pairing links."""

from __future__ import annotations

import base64
import hashlib
import hmac
import re
from urllib.parse import quote

import httpx

from app.config import settings


def _api_url(method: str) -> str:
    token, _ = settings.require_telegram()
    return f"https://api.telegram.org/bot{token}/{method}"


def webhook_secret_token() -> str:
    """Return a Telegram-safe token without weakening generated secret entropy."""
    raw = settings.telegram_webhook_secret
    if not raw:
        return ""
    if re.fullmatch(r"[A-Za-z0-9_-]{1,256}", raw):
        return raw
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


def valid_webhook_secret(candidate: str | None) -> bool:
    expected = webhook_secret_token()
    return bool(expected and candidate and hmac.compare_digest(expected, candidate))


def _encoded(value: str) -> str:
    return base64.urlsafe_b64encode(value.encode("utf-8")).decode("ascii").rstrip("=")


def _decoded(value: str) -> str:
    padding = "=" * (-len(value) % 4)
    return base64.urlsafe_b64decode(value + padding).decode("utf-8")


def pairing_token(athlete_id: str, version: int = 1) -> str:
    """Sign the athlete identity so a Telegram user cannot claim another profile."""
    secret = settings.telegram_link_secret
    if not secret:
        raise RuntimeError("TELEGRAM_LINK_SECRET is required")
    payload = _encoded(f"{athlete_id}|{int(version)}")
    signature = hmac.new(
        secret.encode("utf-8"), payload.encode("ascii"), hashlib.sha256
    ).digest()[:12]
    return f"{payload}.{_encoded(signature.hex())}"


def athlete_from_pairing_token(token: str) -> tuple[str, int] | None:
    try:
        payload, supplied = token.strip().split(".", 1)
        athlete_id, version_raw = _decoded(payload).rsplit("|", 1)
        version = int(version_raw)
    except (ValueError, UnicodeError):
        return None
    expected = pairing_token(athlete_id, version).split(".", 1)[1]
    if not hmac.compare_digest(expected, supplied):
        return None
    return athlete_id, version


def pairing_url(athlete_id: str, version: int = 1) -> str | None:
    username = re.sub(r"^@", "", settings.telegram_bot_username.strip())
    if not settings.telegram_configured or not username:
        return None
    return (
        f"https://t.me/{quote(username)}?start="
        f"{quote(pairing_token(athlete_id, version))}"
    )


def provider_sid(chat_id: str | int, message_id: str | int) -> str:
    return f"telegram:{chat_id}:{message_id}"


def send_outbound(chat_id: str | int, body: str) -> str:
    try:
        response = httpx.post(
            _api_url("sendMessage"),
            json={
                "chat_id": str(chat_id),
                "text": body,
                "disable_web_page_preview": True,
            },
            timeout=15.0,
        )
        response.raise_for_status()
    except httpx.HTTPError:
        # HTTPStatusError includes the request URL, which contains the bot token.
        raise RuntimeError("Telegram send request failed") from None
    payload = response.json()
    if not payload.get("ok") or not isinstance(payload.get("result"), dict):
        raise RuntimeError("Telegram rejected the message")
    message_id = payload["result"].get("message_id")
    if message_id is None:
        raise RuntimeError("Telegram returned no message_id")
    return provider_sid(chat_id, message_id)


def configure_webhook() -> None:
    """Point Telegram at this deployment. Safe to call again on every startup."""
    settings.require_telegram()
    secret = webhook_secret_token()
    try:
        response = httpx.post(
            _api_url("setWebhook"),
            json={
                "url": settings.public_base_url.rstrip("/") + "/webhook/telegram",
                "secret_token": secret,
                "allowed_updates": ["message"],
                "drop_pending_updates": False,
            },
            timeout=15.0,
        )
        response.raise_for_status()
    except httpx.HTTPError:
        raise RuntimeError("Telegram webhook request failed") from None
    if not response.json().get("ok"):
        raise RuntimeError("Telegram rejected the webhook configuration")

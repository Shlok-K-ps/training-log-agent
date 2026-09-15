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
    return f"https://api.telegram.org/bot{token.strip()}/{method}"


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


# Telegram only passes a deep-link start parameter to the bot when it is made of
# A-Z, a-z, 0-9, "_" and "-" and is at most 64 characters long
# (https://core.telegram.org/bots/features#deep-linking). Anything else is
# dropped, and the athlete's Start button sends a bare "/start".
TELEGRAM_START_PARAMETER = re.compile(r"[A-Za-z0-9_-]{1,64}")
_SIGNATURE_CHARS = 16  # 12 HMAC bytes, base64url, no padding


def _secret() -> bytes:
    secret = settings.telegram_link_secret
    if not secret:
        raise RuntimeError("TELEGRAM_LINK_SECRET is required")
    return secret.encode("utf-8")


def _signature(payload: str) -> str:
    digest = hmac.new(_secret(), payload.encode("ascii"), hashlib.sha256).digest()[:12]
    return base64.urlsafe_b64encode(digest).decode("ascii")


def _legacy_signature(payload: str) -> str:
    digest = hmac.new(_secret(), payload.encode("ascii"), hashlib.sha256).digest()[:12]
    return _encoded(digest.hex())


def pairing_token(athlete_id: str, version: int = 1) -> str:
    """Sign the athlete identity so a Telegram user cannot claim another profile.

    The token is the base64url payload followed by a fixed-length base64url
    signature, with no separator, so Telegram accepts it as a start parameter.
    """
    payload = _encoded(f"{athlete_id}|{int(version)}")
    token = payload + _signature(payload)
    if not TELEGRAM_START_PARAMETER.fullmatch(token):
        raise ValueError("this athlete identifier is too long for a Telegram invite")
    return token


def athlete_from_pairing_token(token: str) -> tuple[str, int] | None:
    token = token.strip()
    if "." in token:
        # Invites generated before the Telegram-safe format. Telegram never delivers
        # these from a link, but a pasted "/start <token>" is still verified safely.
        try:
            payload, supplied = token.split(".", 1)
            expected = _legacy_signature(payload)
        except ValueError:
            return None
    elif TELEGRAM_START_PARAMETER.fullmatch(token) and len(token) > _SIGNATURE_CHARS:
        payload, supplied = token[:-_SIGNATURE_CHARS], token[-_SIGNATURE_CHARS:]
        expected = _signature(payload)
    else:
        return None
    if not hmac.compare_digest(expected, supplied):
        return None
    try:
        athlete_id, version_raw = _decoded(payload).rsplit("|", 1)
        return athlete_id, int(version_raw)
    except (ValueError, UnicodeError):
        return None


# What the coach sees about the most recent pairing attempt. Never includes a
# chat id, token or anything the athlete typed.
PAIRING_OUTCOME_LABELS = {
    "connected": "Connected successfully.",
    "already_connected": "Opened an invite again while already connected.",
    "link_replaced": "Used an invite that had already been used or was replaced by a newer one.",
    "athlete_connected_elsewhere": "This athlete is already connected to a different Telegram account.",
    "chat_connected_elsewhere": "The Telegram account used is already connected to another athlete.",
    "invite_refreshed": "You created a new invite. Earlier invites stopped working.",
}


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


def send_outbound(
    chat_id: str | int, body: str, *, reply_markup: dict | None = None
) -> str:
    payload: dict[str, object] = {
        "chat_id": str(chat_id),
        "text": body,
        "disable_web_page_preview": True,
    }
    if reply_markup:
        payload["reply_markup"] = reply_markup
    try:
        response = httpx.post(_api_url("sendMessage"), json=payload, timeout=15.0)
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


def delete_outbound(sid: str) -> bool:
    """Best-effort withdrawal for a safety correction; Telegram may already have shown it."""
    prefix, chat_id, message_id = str(sid).split(":", 2)
    if prefix != "telegram":
        return False
    try:
        response = httpx.post(
            _api_url("deleteMessage"), json={"chat_id": chat_id, "message_id": int(message_id)}, timeout=15.0,
        )
        response.raise_for_status()
    except (ValueError, httpx.HTTPError):
        return False
    payload = response.json()
    return bool(payload.get("ok") and payload.get("result"))


def answer_callback_query(callback_query_id: str, text: str) -> None:
    """Close the loading state on a pressed inline button. Failures are not fatal."""
    try:
        httpx.post(
            _api_url("answerCallbackQuery"),
            json={"callback_query_id": str(callback_query_id), "text": text[:200]},
            timeout=10.0,
        )
    except httpx.HTTPError:
        return


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
                "allowed_updates": ["message", "callback_query"],
                "drop_pending_updates": False,
            },
            timeout=15.0,
        )
        response.raise_for_status()
    except httpx.HTTPStatusError as exc:
        status = exc.response.status_code
        if status in {401, 404}:
            raise RuntimeError("Telegram rejected the bot token") from None
        raise RuntimeError(f"Telegram rejected the webhook request (HTTP {status})") from None
    except httpx.HTTPError:
        raise RuntimeError("Could not reach Telegram while registering the webhook") from None
    if not response.json().get("ok"):
        raise RuntimeError("Telegram rejected the webhook configuration")

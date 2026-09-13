"""Coach console access without passwords, and the signed agent clock.

The coach proves identity once by sending the deployment's one-time setup code
to the bot from their own Telegram account. From then on the bot sends that chat
short-lived signed links; opening one starts a signed console session. The
external scheduler proves itself with an HMAC over a fresh timestamp.
"""

from __future__ import annotations

import base64
import hashlib
import hmac
import json
import secrets
import time
from urllib.parse import quote

from fastapi import Request

from app.config import settings

LINK_TTL_SECONDS = 15 * 60
SESSION_TTL_SECONDS = 12 * 60 * 60
SESSION_COOKIE = "coach_session"
TICK_WINDOW_SECONDS = 10 * 60


def _b64(data: bytes) -> str:
    return base64.urlsafe_b64encode(data).decode("ascii").rstrip("=")


def _unb64(text: str) -> bytes:
    return base64.urlsafe_b64decode(text + "=" * (-len(text) % 4))


def _secret() -> bytes:
    if not settings.coach_link_secret:
        raise RuntimeError("COACH_LINK_SECRET is not configured")
    return settings.coach_link_secret.encode("utf-8")


def _sign(payload: dict[str, object], purpose: str) -> str:
    body = _b64(json.dumps(payload, separators=(",", ":"), sort_keys=True).encode("utf-8"))
    mac = hmac.new(_secret(), f"{purpose}.{body}".encode("ascii"), hashlib.sha256).digest()
    return f"{body}.{_b64(mac)}"


def _verify(token: str | None, purpose: str, now: float) -> dict[str, object] | None:
    if not token or not settings.coach_link_secret:
        return None
    try:
        body, supplied = token.split(".", 1)
        expected = hmac.new(_secret(), f"{purpose}.{body}".encode("ascii"), hashlib.sha256).digest()
        if not hmac.compare_digest(_b64(expected), supplied):
            return None
        payload = json.loads(_unb64(body))
    except (ValueError, UnicodeError):
        return None
    if not isinstance(payload, dict) or float(payload.get("exp", 0)) < now:
        return None
    return payload


def console_token(path: str = "/coach", *, now: float | None = None) -> str:
    moment = time.time() if now is None else now
    return _sign({"p": path, "exp": moment + LINK_TTL_SECONDS, "n": secrets.token_hex(4)}, "link")


def console_link(path: str = "/coach", *, now: float | None = None) -> str:
    return (
        settings.public_base_url.rstrip("/")
        + "/coach/enter?token="
        + quote(console_token(path, now=now))
    )


def verify_console_token(token: str | None, *, now: float | None = None) -> str | None:
    """The console path a valid link grants, or None."""
    payload = _verify(token, "link", time.time() if now is None else now)
    path = str(payload.get("p", "")) if payload else ""
    if path.startswith("/coach") and not path.startswith("//"):
        return path
    return None


def session_value(*, now: float | None = None) -> str:
    moment = time.time() if now is None else now
    return _sign({"role": "coach", "exp": moment + SESSION_TTL_SECONDS}, "session")


def valid_session(value: str | None, *, now: float | None = None) -> bool:
    payload = _verify(value, "session", time.time() if now is None else now)
    return bool(payload and payload.get("role") == "coach")


def open_for_local_development() -> bool:
    """A laptop with no link secret and no public URL needs no sign-in.

    Any deployment with a public URL stays locked until the coach arrives
    through a signed link from their own Telegram chat.
    """
    base = settings.public_base_url.strip().lower()
    local = not base or "://localhost" in base or "://127.0.0.1" in base
    return local and not settings.coach_link_secret


def request_is_coach(request: Request) -> bool:
    if open_for_local_development():
        return True
    return valid_session(request.cookies.get(SESSION_COOKIE))


def session_cookie_secure() -> bool:
    return settings.public_base_url.strip().lower().startswith("https://")


def setup_code_matches(candidate: str) -> bool:
    code = settings.coach_setup_code.strip()
    return bool(code) and hmac.compare_digest(code, candidate.strip())


def setup_code_fingerprint() -> str:
    return hashlib.sha256(settings.coach_setup_code.strip().encode("utf-8")).hexdigest()


def tick_signature(timestamp: str, secret: str | None = None) -> str:
    key = (secret if secret is not None else settings.agent_tick_secret).encode("utf-8")
    return hmac.new(key, timestamp.encode("ascii"), hashlib.sha256).hexdigest()


def valid_tick_request(
    timestamp: str | None, signature: str | None, *, now: float | None = None
) -> bool:
    if not settings.agent_tick_secret or not timestamp or not signature:
        return False
    try:
        sent = float(timestamp)
    except ValueError:
        return False
    moment = time.time() if now is None else now
    if abs(moment - sent) > TICK_WINDOW_SECONDS:
        return False
    return hmac.compare_digest(tick_signature(timestamp), signature.strip().lower())

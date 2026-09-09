"""Least-privilege Google Calendar OAuth and API adapter.

The app reads the primary calendar transiently and creates workouts only in a
secondary calendar that it created itself.  Event titles, descriptions and
attendees never cross this adapter.
"""

from __future__ import annotations

import base64
import hashlib
import hmac
import json
import secrets
from dataclasses import dataclass
from datetime import date, datetime, timedelta, timezone
from typing import Any
from urllib.parse import urlencode
from urllib.parse import quote
from zoneinfo import ZoneInfo

import httpx
from app.scheduling.planner import BusyEvent
from app.security import SecretCipher, SecretCipherError
from app.storage import db

AUTH_URL = "https://accounts.google.com/o/oauth2/v2/auth"
TOKEN_URL = "https://oauth2.googleapis.com/token"
REVOKE_URL = "https://oauth2.googleapis.com/revoke"
API_ROOT = "https://www.googleapis.com/calendar/v3"
SCOPES = (
    "https://www.googleapis.com/auth/calendar.events.readonly",
    "https://www.googleapis.com/auth/calendar.calendarlist.readonly",
    "https://www.googleapis.com/auth/calendar.app.created",
)


class CalendarIntegrationError(RuntimeError):
    pass


@dataclass(frozen=True)
class OAuthTokens:
    access_token: str
    refresh_token: str | None
    expires_at: datetime | None
    scopes: tuple[str, ...]


class TokenCipher(SecretCipher):
    """Calendar-specific error translation around the shared cipher."""

    def __init__(self, key: str) -> None:
        try:
            super().__init__(key)
        except SecretCipherError as exc:
            raise CalendarIntegrationError(str(exc)) from exc

    def decrypt(self, value: str) -> str:
        try:
            return super().decrypt(value)
        except SecretCipherError as exc:
            raise CalendarIntegrationError(str(exc)) from exc


class OAuthStateSigner:
    """Short-lived signed identity carried from WhatsApp through OAuth."""

    def __init__(self, secret: str) -> None:
        if len(secret) < 24:
            raise CalendarIntegrationError("OAUTH_STATE_SECRET must be at least 24 characters")
        self._secret = secret.encode()

    def issue(self, athlete_id: str, *, now: datetime | None = None, ttl_minutes: int = 15) -> str:
        now = now or datetime.now(timezone.utc)
        payload = json.dumps(
            {
                "athlete_id": athlete_id,
                "expires": int((now + timedelta(minutes=ttl_minutes)).timestamp()),
                "nonce": secrets.token_urlsafe(8),
            },
            separators=(",", ":"),
        ).encode()
        encoded = base64.urlsafe_b64encode(payload).rstrip(b"=")
        signature = hmac.new(self._secret, encoded, hashlib.sha256).digest()
        return encoded.decode() + "." + base64.urlsafe_b64encode(signature).rstrip(b"=").decode()

    def verify(self, token: str, *, now: datetime | None = None) -> str:
        now = now or datetime.now(timezone.utc)
        try:
            encoded, signature = token.split(".", 1)
            expected = hmac.new(self._secret, encoded.encode(), hashlib.sha256).digest()
            actual = base64.urlsafe_b64decode(signature + "=" * (-len(signature) % 4))
            canonical = base64.urlsafe_b64encode(actual).rstrip(b"=").decode()
            if signature != canonical or not hmac.compare_digest(expected, actual):
                raise CalendarIntegrationError("Invalid OAuth state")
            raw = base64.urlsafe_b64decode(encoded + "=" * (-len(encoded) % 4))
            payload = json.loads(raw)
            if int(payload["expires"]) < int(now.timestamp()):
                raise CalendarIntegrationError("Calendar connection link has expired")
            athlete_id = str(payload["athlete_id"]).strip()
            if not athlete_id:
                raise CalendarIntegrationError("OAuth state has no athlete identity")
            return athlete_id
        except CalendarIntegrationError:
            raise
        except (ValueError, KeyError, TypeError, json.JSONDecodeError) as exc:
            raise CalendarIntegrationError("Malformed OAuth state") from exc


class GoogleCalendarOAuth:
    def __init__(
        self,
        *,
        client_id: str,
        client_secret: str,
        redirect_uri: str,
        http: httpx.Client | None = None,
    ) -> None:
        self.client_id = client_id
        self.client_secret = client_secret
        self.redirect_uri = redirect_uri
        self.http = http or httpx.Client(timeout=15)

    def authorization_url(self, state: str) -> str:
        return AUTH_URL + "?" + urlencode(
            {
                "client_id": self.client_id,
                "redirect_uri": self.redirect_uri,
                "response_type": "code",
                "scope": " ".join(SCOPES),
                "access_type": "offline",
                "prompt": "consent",
                "include_granted_scopes": "true",
                "state": state,
            }
        )

    def exchange_code(self, code: str) -> OAuthTokens:
        try:
            response = self.http.post(
                TOKEN_URL,
                data={
                    "client_id": self.client_id,
                    "client_secret": self.client_secret,
                    "code": code,
                    "grant_type": "authorization_code",
                    "redirect_uri": self.redirect_uri,
                },
            )
        except httpx.HTTPError as exc:
            raise CalendarIntegrationError("Google authorization could not be reached") from exc
        if response.is_error:
            raise CalendarIntegrationError("Google rejected the calendar authorization code")
        return _tokens(response.json())

    def refresh(self, refresh_token: str) -> OAuthTokens:
        try:
            response = self.http.post(
                TOKEN_URL,
                data={
                    "client_id": self.client_id,
                    "client_secret": self.client_secret,
                    "refresh_token": refresh_token,
                    "grant_type": "refresh_token",
                },
            )
        except httpx.HTTPError as exc:
            raise CalendarIntegrationError("Google Calendar token refresh could not be reached") from exc
        if response.is_error:
            raise CalendarIntegrationError("Google Calendar access expired; reconnect it")
        tokens = _tokens(response.json())
        return OAuthTokens(
            tokens.access_token,
            refresh_token,
            tokens.expires_at,
            tokens.scopes or SCOPES,
        )


def _tokens(payload: dict[str, Any]) -> OAuthTokens:
    access = str(payload.get("access_token") or "")
    if not access:
        raise CalendarIntegrationError("Google token response had no access token")
    expires = payload.get("expires_in")
    expires_at = (
        datetime.now(timezone.utc) + timedelta(seconds=max(0, int(expires) - 60))
        if expires is not None
        else None
    )
    scopes = tuple(str(payload.get("scope") or "").split()) or SCOPES
    return OAuthTokens(access, payload.get("refresh_token"), expires_at, scopes)


class GoogleCalendarClient:
    def __init__(
        self,
        conn,
        *,
        oauth: GoogleCalendarOAuth,
        cipher: TokenCipher,
        http: httpx.Client | None = None,
    ) -> None:
        self.conn = conn
        self.oauth = oauth
        self.cipher = cipher
        self.http = http or httpx.Client(timeout=15)

    def save_tokens(self, athlete_id: str, tokens: OAuthTokens) -> None:
        db.save_oauth_connection(
            self.conn,
            athlete_id=athlete_id,
            provider="google_calendar",
            access_token=self.cipher.encrypt(tokens.access_token),
            refresh_token=(self.cipher.encrypt(tokens.refresh_token) if tokens.refresh_token else None),
            expires_at=tokens.expires_at.isoformat() if tokens.expires_at else None,
            scopes=" ".join(tokens.scopes),
        )

    def connected(self, athlete_id: str) -> bool:
        return db.oauth_connection(self.conn, athlete_id) is not None

    def disconnect(self, athlete_id: str) -> None:
        row = db.oauth_connection(self.conn, athlete_id)
        revoke_error = False
        if row is not None:
            encrypted = row["refresh_token"] or row["access_token"]
            try:
                token = self.cipher.decrypt(str(encrypted))
                response = self.http.post(REVOKE_URL, data={"token": token})
                revoke_error = response.is_error
            except (CalendarIntegrationError, httpx.HTTPError):
                revoke_error = True
        db.delete_oauth_connection(self.conn, athlete_id)
        if revoke_error:
            raise CalendarIntegrationError(
                "Local tokens were deleted, but Google did not confirm revocation; remove the app in Google Account permissions too"
            )

    def _access_token(self, athlete_id: str) -> str:
        row = db.oauth_connection(self.conn, athlete_id)
        if row is None:
            raise CalendarIntegrationError("Google Calendar is not connected")
        expires_at = datetime.fromisoformat(row["expires_at"]) if row["expires_at"] else None
        if expires_at and expires_at <= datetime.now(timezone.utc):
            if not row["refresh_token"]:
                raise CalendarIntegrationError("Google Calendar access expired; reconnect it")
            refreshed = self.oauth.refresh(self.cipher.decrypt(row["refresh_token"]))
            self.save_tokens(athlete_id, refreshed)
            return refreshed.access_token
        return self.cipher.decrypt(row["access_token"])

    def _request(self, athlete_id: str, method: str, path: str, **kwargs: Any) -> httpx.Response:
        token = self._access_token(athlete_id)
        headers = {"Authorization": f"Bearer {token}", **kwargs.pop("headers", {})}
        try:
            response = self.http.request(method, API_ROOT + path, headers=headers, **kwargs)
        except httpx.HTTPError as exc:
            raise CalendarIntegrationError("Google Calendar could not be reached") from exc
        if response.status_code == 401:
            row = db.oauth_connection(self.conn, athlete_id)
            if row is not None and row["refresh_token"]:
                refreshed = self.oauth.refresh(self.cipher.decrypt(row["refresh_token"]))
                self.save_tokens(athlete_id, refreshed)
                headers["Authorization"] = f"Bearer {refreshed.access_token}"
                try:
                    response = self.http.request(method, API_ROOT + path, headers=headers, **kwargs)
                except httpx.HTTPError as exc:
                    raise CalendarIntegrationError("Google Calendar could not be reached") from exc
        if response.is_error:
            raise CalendarIntegrationError(
                f"Google Calendar request failed ({response.status_code})"
            )
        return response

    def list_events(
        self, athlete_id: str, *, day: date, timezone_name: str
    ) -> tuple[BusyEvent, ...]:
        zone = ZoneInfo(timezone_name)
        start = datetime.combine(day, datetime.min.time(), tzinfo=zone)
        end = start + timedelta(days=1)
        calendar_list = self._request(
            athlete_id,
            "GET",
            "/users/me/calendarList",
            params={"fields": "items(id,primary,selected)"},
        ).json()
        calendar_items = calendar_list.get("items", [])
        calendar_ids = {
            str(item["id"])
            for item in calendar_items
            if item.get("id") and (item.get("primary") or item.get("selected"))
        }
        if not any(item.get("primary") for item in calendar_items):
            calendar_ids.add("primary")
        row = db.oauth_connection(self.conn, athlete_id)
        if row is not None and row["provider_calendar_id"]:
            calendar_ids.add(str(row["provider_calendar_id"]))
        events: list[BusyEvent] = []
        for calendar_id in calendar_ids:
            response = self._request(
                athlete_id,
                "GET",
                f"/calendars/{quote(calendar_id, safe='')}/events",
                params={
                    "timeMin": start.isoformat(),
                    "timeMax": end.isoformat(),
                    "singleEvents": "true",
                    "orderBy": "startTime",
                    "maxResults": "2500",
                    "fields": "items(start,end,location,status,transparency)",
                },
            )
            for item in response.json().get("items", []):
                if item.get("status") == "cancelled" or item.get("transparency") == "transparent":
                    continue
                start_value, all_day = _event_time(item.get("start", {}), zone)
                end_value, _ = _event_time(item.get("end", {}), zone)
                if start_value and end_value:
                    events.append(
                        BusyEvent(
                            start_value,
                            end_value,
                            _private_location(item.get("location")),
                            all_day,
                        )
                    )
        return tuple(events)

    def create_or_update_workout_event(
        self,
        athlete_id: str,
        *,
        start: datetime,
        end: datetime,
        timezone_name: str,
        gym_location: str,
        lift: str | None,
        event_id: str | None = None,
    ) -> str:
        row = db.oauth_connection(self.conn, athlete_id)
        if row is None:
            raise CalendarIntegrationError("Google Calendar is not connected")
        calendar_id = row["provider_calendar_id"]
        if not calendar_id:
            created = self._request(
                athlete_id,
                "POST",
                "/calendars",
                json={"summary": "Power Coach", "timeZone": timezone_name},
            ).json()
            calendar_id = str(created["id"])
            db.update_oauth_calendar_id(self.conn, athlete_id, calendar_id)
        summary = "Powerlifting training" + (f" — {lift.title()}" if lift else "")
        encoded_calendar = quote(str(calendar_id), safe="")
        encoded_event = quote(event_id, safe="") if event_id else None
        method = "PUT" if encoded_event else "POST"
        path = (
            f"/calendars/{encoded_calendar}/events/{encoded_event}"
            if encoded_event
            else f"/calendars/{encoded_calendar}/events"
        )
        event = self._request(
            athlete_id,
            method,
            path,
            json={
                "summary": summary,
                "location": gym_location,
                "description": "Scheduled after athlete confirmation in WhatsApp.",
                "start": {"dateTime": start.isoformat(), "timeZone": timezone_name},
                "end": {"dateTime": end.isoformat(), "timeZone": timezone_name},
            },
        ).json()
        return str(event["id"])


def _event_time(value: dict[str, Any], zone: ZoneInfo) -> tuple[datetime | None, bool]:
    if value.get("dateTime"):
        parsed = datetime.fromisoformat(str(value["dateTime"]).replace("Z", "+00:00"))
        if parsed.tzinfo is None:
            parsed = parsed.replace(tzinfo=zone)
        return parsed, False
    if value.get("date"):
        return datetime.combine(date.fromisoformat(str(value["date"])), time.min, tzinfo=zone), True
    return None, False


def _private_location(value: Any) -> str | None:
    location = str(value or "").strip()
    virtual_markers = ("zoom", "microsoft teams", "google meet", "meet.google", "webex")
    if (
        not location
        or location.startswith(("http://", "https://"))
        or any(marker in location.casefold() for marker in virtual_markers)
    ):
        return None
    return location[:500]

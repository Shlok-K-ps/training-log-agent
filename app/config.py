"""Configuration, loaded from the environment (never hard-coded, never committed)."""

from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path

from dotenv import load_dotenv

load_dotenv()


def _flag(name: str, default: bool) -> bool:
    raw = os.getenv(name)
    if raw is None:
        return default
    return raw.strip().lower() in {"1", "true", "yes", "on"}


@dataclass
class Settings:
    """Read once at import. Mutable so tests can override a field in place."""

    gemini_api_key: str = os.getenv("GEMINI_API_KEY", "")
    gemini_model: str = os.getenv("GEMINI_MODEL", "gemini-2.5-flash")

    twilio_account_sid: str = os.getenv("TWILIO_ACCOUNT_SID", "")
    twilio_auth_token: str = os.getenv("TWILIO_AUTH_TOKEN", "")
    twilio_whatsapp_from: str = os.getenv("TWILIO_WHATSAPP_FROM", "")

    public_base_url: str = os.getenv("PUBLIC_BASE_URL", "")
    validate_twilio_signature: bool = _flag("VALIDATE_TWILIO_SIGNATURE", True)
    enable_morning_scheduler: bool = _flag("ENABLE_MORNING_SCHEDULER", False)

    google_calendar_client_id: str = os.getenv("GOOGLE_CALENDAR_CLIENT_ID", "")
    google_calendar_client_secret: str = os.getenv("GOOGLE_CALENDAR_CLIENT_SECRET", "")
    google_maps_api_key: str = os.getenv("GOOGLE_MAPS_API_KEY", "")
    oauth_state_secret: str = os.getenv("OAUTH_STATE_SECRET", "")
    calendar_token_encryption_key: str = os.getenv(
        "CALENDAR_TOKEN_ENCRYPTION_KEY", ""
    )
    team_approved_supplement_regimens_raw: str = os.getenv(
        "TEAM_APPROVED_SUPPLEMENT_REGIMENS", ""
    )

    coach_access_token: str = os.getenv("COACH_ACCESS_TOKEN", "")
    coach_name: str = os.getenv("COACH_NAME", "Coach")
    coach_silent_after_days: int = int(os.getenv("COACH_SILENT_AFTER_DAYS", "7"))
    coach_draft_hour: int = int(os.getenv("COACH_DRAFT_HOUR", "20"))

    injury_clearance_reviewer: str = os.getenv("INJURY_CLEARANCE_REVIEWER", "")
    injury_stale_after_days: int = int(os.getenv("INJURY_STALE_AFTER_DAYS", "21"))

    database_path: str = os.getenv("DATABASE_PATH", "data/training_log.db")

    @property
    def db_file(self) -> Path:
        return Path(self.database_path)

    def require_gemini(self) -> str:
        if not self.gemini_api_key:
            raise RuntimeError(
                "GEMINI_API_KEY is not set. Copy .env.example to .env and add a key "
                "from https://aistudio.google.com/apikey"
            )
        return self.gemini_api_key

    def require_twilio(self) -> tuple[str, str, str]:
        if not self.twilio_account_sid or not self.twilio_auth_token or not self.twilio_whatsapp_from:
            raise RuntimeError("Twilio credentials and TWILIO_WHATSAPP_FROM are required")
        return self.twilio_account_sid, self.twilio_auth_token, self.twilio_whatsapp_from

    @property
    def calendar_configured(self) -> bool:
        return bool(
            self.public_base_url
            and self.google_calendar_client_id
            and self.google_calendar_client_secret
            and self.google_maps_api_key
            and self.oauth_state_secret
            and self.calendar_token_encryption_key
        )

    @property
    def google_calendar_redirect_uri(self) -> str:
        return self.public_base_url.rstrip("/") + "/integrations/google/calendar/callback"

    def approved_supplement_source(
        self, name: str, dose: float, unit: str, timing: str
    ) -> str | None:
        """Return the approver for an exact, team-verified regimen and batch."""
        wanted = (name.casefold().strip(), float(dose), unit.casefold().strip(), timing.casefold())
        for raw in self.team_approved_supplement_regimens_raw.split(";"):
            pieces = [piece.strip() for piece in raw.split("|")]
            if len(pieces) != 6:
                continue
            (
                configured_name,
                configured_dose,
                configured_unit,
                configured_timing,
                approver,
                batch_status,
            ) = pieces
            try:
                configured = (
                    configured_name.casefold(),
                    float(configured_dose),
                    configured_unit.casefold(),
                    configured_timing.casefold(),
                )
            except ValueError:
                continue
            batch_verified = batch_status.casefold() in {
                "batch_verified",
                "verified",
                "true",
                "yes",
            }
            if configured == wanted and approver and batch_verified:
                return approver[:80]
        return None


settings = Settings()

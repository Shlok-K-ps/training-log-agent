"""Coach identity.

Athlete identity is "the phone number that texted", which does not work for
someone opening a web page. This is the smallest thing that does: one shared
token for a single-coach deployment, compared in constant time.

It is deliberately not a user system. If a second coach ever needs their own
login, this file is where that grows — and until then, pretending otherwise
would be more code than the problem deserves.
"""

from __future__ import annotations

import hmac

from app.config import settings


class CoachAuthError(RuntimeError):
    pass


def is_configured() -> bool:
    return bool(settings.coach_access_token.strip())


def check(token: str | None) -> None:
    """Raise unless `token` matches the configured coach token."""
    if not is_configured():
        raise CoachAuthError(
            "COACH_ACCESS_TOKEN is not set. The coach console stays closed until "
            "it is, so an unset token can never mean an open door."
        )
    if not token or not hmac.compare_digest(
        token.strip(), settings.coach_access_token.strip()
    ):
        raise CoachAuthError("Invalid coach token.")

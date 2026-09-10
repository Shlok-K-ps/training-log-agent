"""Layer 4 — the coach's view over everything the other layers recorded.

Reads. Does not decide. The one thing it can change is an injury flag, and only
through `storage.clear_injury`, which records who did it and why.
"""

from app.coach.auth import CoachAuthError, check, is_configured
from app.coach.roster import (
    Bucket, Flag, PendingMessage, Roster, RosterEntry,
    build_roster, pending_reviews, review_athlete,
)
from app.coach.view import render, render_outbox

__all__ = [
    "CoachAuthError", "check", "is_configured",
    "Bucket", "Flag", "PendingMessage", "Roster", "RosterEntry",
    "build_roster", "pending_reviews", "review_athlete",
    "render", "render_outbox",
]

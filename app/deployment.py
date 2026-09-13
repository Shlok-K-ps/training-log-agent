"""Whether this deployment may let the training-day agent act on its own.

An autonomous agent is only as safe as its memory. If a public deployment kept
its cases on a temporary SQLite file, a restart would erase which check-ins were
already sent and which decisions were pending, and the agent would act again as
if nothing had happened. So a public deployment runs the agent only on durable
Postgres; anything else leaves the loop blocked and reports that loudly.

Local development (no public URL) may use SQLite.
"""

from __future__ import annotations

from app.config import settings


def is_public_deployment() -> bool:
    base = settings.public_base_url.strip().lower()
    return bool(base) and "://localhost" not in base and "://127.0.0.1" not in base


def storage_backend() -> str:
    return "postgres" if settings.database_url.strip() else "sqlite"


def durable_storage_configured() -> bool:
    """Agent memory survives restarts and redeploys."""
    return storage_backend() == "postgres"


def agent_blocker() -> str | None:
    """Why the enabled agent must not run here, or None when it may."""
    if not settings.enable_agent_loop:
        return None
    if is_public_deployment() and not durable_storage_configured():
        return (
            "The training-day agent is blocked: this public deployment has no DATABASE_URL, so "
            "its memory would live on temporary SQLite and be erased on every restart or deploy. "
            "Set DATABASE_URL to a Postgres database (for example Neon) and redeploy."
        )
    return None


def agent_loop_active() -> bool:
    return settings.enable_agent_loop and agent_blocker() is None


def status() -> dict[str, object]:
    blocker = agent_blocker()
    if not settings.enable_agent_loop:
        agent = "disabled"
    elif blocker:
        agent = "blocked"
    else:
        agent = "active"
    return {
        "storage_backend": storage_backend(),
        "agent_memory_durable": durable_storage_configured(),
        "public_deployment": is_public_deployment(),
        "agent_loop": agent,
        "agent_blocker": blocker,
        "proactive_checkins_owner": "training_day_agent" if settings.enable_agent_loop else (
            "legacy_morning_scheduler" if settings.enable_morning_scheduler else "none"
        ),
    }

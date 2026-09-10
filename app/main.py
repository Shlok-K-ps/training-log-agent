"""FastAPI service: WhatsApp transport in, reviewed coaching messages out.

    Vonage  ->  POST /webhook/vonage/inbound
    Twilio  ->  POST /webhook/whatsapp (legacy fallback)
                  |
                  |-- Layer 1  app.agent      Gemini -> validated tool calls
                  |-- Layer 2  app.storage    SQLite append
                  |-- Layer 3  app.decision   verdict + reply text
                  v
                receipt + coach-approved delivery  ->  WhatsApp
"""

from __future__ import annotations

import asyncio
import hashlib
import logging
import secrets
from datetime import date
from contextlib import asynccontextmanager
from contextlib import suppress
from functools import lru_cache

from fastapi import FastAPI, Request, Response
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles
from starlette.concurrency import run_in_threadpool

from app.agent.offline import OfflineClient
from app.agent.parser import GeminiClient, ModelClient
from app.channels import vonage, whatsapp
from app.decision.injury_pivot import injury_pivot_options
from app.coach import auth as coach_auth
from app.coach.athlete import athlete_detail, suggest_message
from app.coach.athlete_view import render_athlete
from app.coach.analytics_view import render_analytics
from app.coach.progress import squad_goal_paces
from app.coach.whatsapp_view import render_whatsapp_desk
from app.coach.demo import clear_demo_squad, is_demo, seed_demo_squad
from app.scheduling.outbox import (
    COACH_NOTE,
    FEEDBACK_REPLY,
    send_approved_feedback,
    send_approved_notes,
)
from app.coach import (
    COOKIE_NAME,
    build_roster,
    pending_reviews,
    render as render_roster,
    render_athletes,
    render_landing,
    render_login,
    render_outbox,
    render_privacy,
    render_terms,
)
from app.config import settings
from app.integrations.factory import calendar_client, calendar_oauth, state_signer
from app.integrations.google_calendar import CalendarIntegrationError
from app.router import handle_message
from app.scheduling import draft_upcoming_prompts, send_approved_prompts
from app.storage import db

logging.basicConfig(
    level=logging.INFO, format="%(asctime)s %(levelname)-7s %(name)s: %(message)s"
)
log = logging.getLogger("power-agent")

FEEDBACK_ACK = "Got it — I’ve logged your update and sent it to your coach for review."
INJURY_ACK = "Your injury update is logged. Training guidance is paused and your coach has been notified."


@lru_cache(maxsize=1)
def get_model_client() -> ModelClient:
    """Gemini when a key is configured, the offline stub otherwise.

    Falling back rather than crashing means the service still boots, still logs
    tidy messages, and says so in /health — a misconfigured key never looks like
    a dead webhook.
    """
    if settings.gemini_api_key:
        return GeminiClient()
    log.warning("GEMINI_API_KEY is not set - falling back to the offline regex parser")
    return OfflineClient()


@asynccontextmanager
async def lifespan(app: FastAPI):
    conn = db.connect()
    db.init_db(conn)
    conn.close()
    log.info("database ready at %s", settings.db_file)
    task = None
    if settings.enable_morning_scheduler:
        task = asyncio.create_task(_morning_scheduler_loop())
        log.info("proactive morning check-in scheduler enabled")
    try:
        yield
    finally:
        if task is not None:
            task.cancel()
            with suppress(asyncio.CancelledError):
                await task


async def _morning_scheduler_loop() -> None:
    while True:
        try:
            await run_in_threadpool(_send_morning_prompts)
        except Exception:  # noqa: BLE001 - keep the web service alive and retry later
            log.exception("morning check-in scheduler failed")
        await asyncio.sleep(60)


def _send_morning_prompts() -> int:
    """One tick: draft tomorrow's messages, then send the ones already approved."""
    conn = db.connect()
    try:
        db.init_db(conn)
        drafted = draft_upcoming_prompts(conn)
        if drafted:
            log.info("queued %d morning message(s) for coach review", len(drafted))
        def recorded_sender(athlete_id: str, body: str) -> None:
            provider_sid = whatsapp.send_outbound(athlete_id, body)
            db.record_whatsapp_message(
                conn, athlete_id=athlete_id, direction="outbound", body=body,
                status="queued", provider_sid=provider_sid, message_kind="scheduled",
            )

        sent = send_approved_prompts(conn, recorded_sender)
        sent += send_approved_notes(conn, recorded_sender)
        return sent + send_approved_feedback(conn, recorded_sender)
    finally:
        conn.close()


app = FastAPI(
    title="Power AI — Powerlifting Training-Log Agent",
    version="0.2.0",
    description="WhatsApp powerlifting coach: structured logging, deterministic verdicts, coach desk review.",
    lifespan=lifespan,
)

@app.get("/favicon.ico", include_in_schema=False)
async def favicon() -> Response:
    return Response(status_code=204)

app.mount("/static", StaticFiles(directory="app/static"), name="static")


@app.get("/", response_class=HTMLResponse)
async def product_home(request: Request) -> Response:
    token = request.query_params.get("token", "").strip() or request.cookies.get(COOKIE_NAME, "").strip()
    is_logged_in = coach_auth.is_valid(token)
    return HTMLResponse(render_landing(is_logged_in=is_logged_in))


@app.get("/coach/login", response_class=HTMLResponse)
async def coach_login_page(request: Request) -> Response:
    token = request.query_params.get("token", "").strip() or request.cookies.get(COOKIE_NAME, "").strip()
    if coach_auth.is_valid(token):
        return RedirectResponse(url="/coach", status_code=303)
    return HTMLResponse(render_login())


@app.post("/coach/login", response_class=HTMLResponse)
async def coach_login_submit(request: Request) -> Response:
    form = dict(await request.form())
    token = str(form.get("token", "")).strip()
    try:
        coach_auth.check(token)
    except coach_auth.CoachAuthError as exc:
        return HTMLResponse(render_login(error=str(exc)), status_code=401)

    response = RedirectResponse(url="/coach", status_code=303)
    is_secure = request.url.scheme == "https"
    response.set_cookie(
        key=COOKIE_NAME,
        value=token,
        httponly=True,
        secure=is_secure,
        samesite="lax",
        max_age=60 * 60 * 24 * 30,
        path="/",
    )
    return response


@app.get("/coach/logout", response_class=HTMLResponse)
async def coach_logout() -> Response:
    response = RedirectResponse(url="/coach/login", status_code=303)
    response.delete_cookie(key=COOKIE_NAME, path="/")
    return response


@app.get("/coach", response_class=HTMLResponse)
async def coach_console(request: Request, token: str = "") -> Response:
    """The roster. Read-only, and closed unless COACH_ACCESS_TOKEN is set."""
    effective_token = token.strip() if token else request.cookies.get(COOKIE_NAME, "").strip()
    if not effective_token:
        return RedirectResponse(url="/coach/login", status_code=303)
    try:
        coach_auth.check(effective_token)
    except coach_auth.CoachAuthError as exc:
        return HTMLResponse(render_login(error=str(exc)), status_code=403)

    html = await run_in_threadpool(_render_console, effective_token, None)
    response = HTMLResponse(html)
    if token and request.cookies.get(COOKIE_NAME) != effective_token:
        is_secure = request.url.scheme == "https"
        response.set_cookie(
            key=COOKIE_NAME,
            value=effective_token,
            httponly=True,
            secure=is_secure,
            samesite="lax",
            max_age=60 * 60 * 24 * 30,
            path="/",
        )
    return response


@app.post("/coach/clear-injury", response_class=HTMLResponse)
async def coach_clear_injury(request: Request) -> Response:
    """The one write the console can make, and it records who made it."""
    form = dict(await request.form())
    token = str(form.get("token", "")).strip() or request.cookies.get(COOKIE_NAME, "").strip()
    if not token:
        return RedirectResponse(url="/coach/login", status_code=303)
    try:
        coach_auth.check(token)
    except coach_auth.CoachAuthError as exc:
        return HTMLResponse(render_login(error=str(exc)), status_code=403)

    athlete_id = str(form.get("athlete_id", "")).strip()
    clearance_source = str(form.get("clearance_source", "")).strip()
    reason = str(form.get("reason", "")).strip()
    confirmation = str(form.get("independent_confirmation", "")).strip()
    message = await run_in_threadpool(
        _clear_injury, athlete_id, clearance_source, reason, confirmation
    )
    html = await run_in_threadpool(_render_athlete, athlete_id, message)
    if html is None:
        return HTMLResponse("<h1>Not found</h1><p>No such athlete.</p>", status_code=404)
    return HTMLResponse(html)


def _clear_injury(
    athlete_id: str, clearance_source: str, reason: str, confirmation: str
) -> tuple[str, str]:
    conn = db.connect()
    try:
        db.init_db(conn)
        source = clearance_source.strip()
        basis = reason.strip()
        athlete_name = (db.athlete_name(conn, athlete_id) or "").strip()
        self_labels = {
            "athlete", "self", "me", "the athlete", athlete_id.casefold(),
            athlete_name.casefold(),
        }
        if confirmation != "confirmed":
            raise ValueError("confirm that clearance came from someone other than the athlete")
        if not source:
            raise ValueError("name the coach, physio or clinician who provided clearance")
        if source.casefold() in self_labels:
            raise ValueError("the athlete cannot be their own clearance source")
        if not basis:
            raise ValueError("record the basis for clearance")
        audit_reason = (
            f"Clearance source: {source}. Basis: {basis}. "
            f"Recorded by coach: {settings.coach_name}."
        )
        db.clear_injury(
            conn, athlete_id, actor=settings.coach_name, reason=audit_reason
        )
    except ValueError as exc:
        return ("err", f"Not cleared: {exc}")
    finally:
        conn.close()
    return ("ok", f"Injury flag cleared for {athlete_id}, recorded against {settings.coach_name}.")


def _render_console(token: str, message: tuple[str, str] | None) -> str:
    conn = db.connect()
    try:
        db.init_db(conn)
        roster = build_roster(conn, today=date.today())
        roster_ids = db.list_athletes(conn)
        pending_count = len(db.pending_drafts(conn))
    finally:
        conn.close()
    has_demo = any(is_demo(a) for a in roster_ids)
    return render_roster(
        roster, token=token, coach=settings.coach_name, message=message,
        has_demo=has_demo, pending_count=pending_count,
    )


@app.get("/coach/athletes", response_class=HTMLResponse)
async def coach_athletes(request: Request, token: str = "") -> Response:
    """Searchable squad directory and the entry point to each athlete workspace."""
    effective_token = token.strip() if token else request.cookies.get(COOKIE_NAME, "").strip()
    if not effective_token:
        return RedirectResponse(url="/coach/login", status_code=303)
    try:
        coach_auth.check(effective_token)
    except coach_auth.CoachAuthError as exc:
        return HTMLResponse(render_login(error=str(exc)), status_code=403)
    return HTMLResponse(await run_in_threadpool(_render_athlete_directory, None))


def _render_athlete_directory(message: tuple[str, str] | None) -> str:
    conn = db.connect()
    try:
        db.init_db(conn)
        roster = build_roster(conn, today=date.today())
        roster_ids = db.list_athletes(conn)
        pending_count = len(db.pending_drafts(conn))
    finally:
        conn.close()
    return render_athletes(
        roster, coach=settings.coach_name, message=message,
        has_demo=any(is_demo(a) for a in roster_ids), pending_count=pending_count,
    )


@app.post("/coach/demo/seed", response_class=HTMLResponse)
async def coach_seed_demo(request: Request) -> Response:
    """Load a demo squad so an empty console can show what a full one looks like."""
    form = dict(await request.form())
    token = str(form.get("token", "")).strip() or request.cookies.get(COOKIE_NAME, "").strip()
    try:
        coach_auth.check(token)
    except coach_auth.CoachAuthError as exc:
        return HTMLResponse(f"<h1>Coach console</h1><p>{exc}</p>", status_code=403)
    message = await run_in_threadpool(_seed_demo)
    return HTMLResponse(await run_in_threadpool(_render_console, token, message))


@app.post("/coach/demo/clear", response_class=HTMLResponse)
async def coach_clear_demo(request: Request) -> Response:
    form = dict(await request.form())
    token = str(form.get("token", "")).strip() or request.cookies.get(COOKIE_NAME, "").strip()
    try:
        coach_auth.check(token)
    except coach_auth.CoachAuthError as exc:
        return HTMLResponse(f"<h1>Coach console</h1><p>{exc}</p>", status_code=403)
    message = await run_in_threadpool(_clear_demo)
    return HTMLResponse(await run_in_threadpool(_render_console, token, message))


def _seed_demo() -> tuple[str, str]:
    conn = db.connect()
    try:
        db.init_db(conn)
        added = seed_demo_squad(conn)
    finally:
        conn.close()
    if not added:
        return ("err", "The demo squad is already loaded.")
    return ("ok", f"Loaded {added} demo athletes. Remove them whenever you like.")


def _clear_demo() -> tuple[str, str]:
    conn = db.connect()
    try:
        db.init_db(conn)
        removed = clear_demo_squad(conn)
    finally:
        conn.close()
    return ("ok", f"Removed {removed} demo athletes.")


@app.get("/coach/athlete/{athlete_id}", response_class=HTMLResponse)
async def coach_athlete(athlete_id: str, request: Request, token: str = "") -> Response:
    """One athlete: what they did, what the rules make of it, what to say back."""
    effective = token.strip() or request.cookies.get(COOKIE_NAME, "").strip()
    try:
        coach_auth.check(effective)
    except coach_auth.CoachAuthError as exc:
        return HTMLResponse(f"<h1>Coach console</h1><p>{exc}</p>", status_code=403)
    html = await run_in_threadpool(_render_athlete, athlete_id, None)
    if html is None:
        return HTMLResponse("<h1>Not found</h1><p>No such athlete.</p>", status_code=404)
    return HTMLResponse(html)


@app.post("/coach/athlete/{athlete_id}/message", response_class=HTMLResponse)
async def coach_message_athlete(athlete_id: str, request: Request) -> Response:
    """Queue a coach-written message. They wrote it, so it needs no second approval."""
    form = dict(await request.form())
    token = str(form.get("token", "")).strip() or request.cookies.get(COOKIE_NAME, "").strip()
    try:
        coach_auth.check(token)
    except coach_auth.CoachAuthError as exc:
        return HTMLResponse(f"<h1>Coach console</h1><p>{exc}</p>", status_code=403)
    message = await run_in_threadpool(
        _queue_note, athlete_id, str(form.get("body", ""))
    )
    html = await run_in_threadpool(_render_athlete, athlete_id, message)
    if html is None:
        return HTMLResponse("<h1>Not found</h1><p>No such athlete.</p>", status_code=404)
    return HTMLResponse(html)


@app.post("/coach/athlete/{athlete_id}/injury-plan", response_class=HTMLResponse)
async def coach_approve_injury_plan(athlete_id: str, request: Request) -> Response:
    """Select one bounded training pivot without clearing the injury flag."""
    form = dict(await request.form())
    token = request.cookies.get(COOKIE_NAME, "").strip()
    if not token:
        return RedirectResponse(url="/coach/login", status_code=303)
    try:
        coach_auth.check(token)
    except coach_auth.CoachAuthError as exc:
        return HTMLResponse(render_login(error=str(exc)), status_code=403)
    result = await run_in_threadpool(
        _approve_injury_plan,
        athlete_id,
        str(form.get("injury_entry_id", "")).strip(),
        str(form.get("option_code", "")).strip(),
    )
    html = await run_in_threadpool(_render_athlete, athlete_id, result)
    return HTMLResponse(html or "<h1>Not found</h1>", status_code=200 if html else 404)


def _approve_injury_plan(
    athlete_id: str, injury_entry_id_raw: str, option_code: str
) -> tuple[str, str]:
    conn = db.connect()
    try:
        db.init_db(conn)
        current_id = db.open_injury_entry_id(conn, athlete_id)
        try:
            supplied_id = int(injury_entry_id_raw)
        except ValueError:
            return ("err", "The injury version was invalid; refresh and review again.")
        if current_id != supplied_id:
            return ("err", "The injury changed; refresh and review the current options.")
        _, note = db.injury_state(conn, athlete_id)
        option = next(
            (candidate for candidate in injury_pivot_options(note) if candidate.code == option_code),
            None,
        )
        if option is None:
            return ("err", "That training pivot is not available.")
        db.record_injury_plan_decision(
            conn, athlete_id=athlete_id, injury_entry_id=supplied_id,
            option_code=option.code, plan_text=option.plan,
            approved_by=settings.coach_name,
        )
        message_kind = FEEDBACK_REPLY + f"injury:{supplied_id}"
        body = (
            f"Training update from {settings.coach_name}: {option.plan} "
            "This changes training only; your injury flag remains open until independent clearance is recorded."
        )
        db.create_draft(conn, athlete_id, message_kind, date.today().isoformat(), body)
        db.review_draft(
            conn, athlete_id, message_kind, date.today().isoformat(),
            status="approved", reviewed_by=settings.coach_name, body=body,
        )
    except ValueError as exc:
        return ("err", f"Plan not approved: {exc}")
    finally:
        conn.close()
    return ("ok", f"Approved “{option.title}”. It is queued for WhatsApp delivery.")


@app.post("/coach/athletes/register", response_class=HTMLResponse)
async def coach_register_athlete(request: Request) -> Response:
    form = dict(await request.form())
    token = str(form.get("token", "")).strip() or request.cookies.get(COOKIE_NAME, "").strip()
    try:
        coach_auth.check(token)
    except coach_auth.CoachAuthError as exc:
        return HTMLResponse(f"<h1>Coach console</h1><p>{exc}</p>", status_code=403)
    message = await run_in_threadpool(
        _register, {str(key): str(value) for key, value in form.items()}
    )
    return HTMLResponse(await run_in_threadpool(_render_athlete_directory, message))


def _render_athlete(athlete_id: str, message: tuple[str, str] | None) -> str | None:
    conn = db.connect()
    try:
        db.init_db(conn)
        if athlete_id not in db.list_athletes(conn):
            return None
        today = date.today()
        detail = athlete_detail(conn, athlete_id, today=today)
    finally:
        conn.close()
    return render_athlete(
        detail,
        coach=settings.coach_name,
        suggested=suggest_message(detail, coach=settings.coach_name),
        message=message,
    )


def _queue_note(athlete_id: str, body: str) -> tuple[str, str]:
    body = body.strip()
    if not body:
        return ("err", "Nothing to send — the message was empty.")
    conn = db.connect()
    try:
        db.init_db(conn)
        today = date.today().isoformat()
        db.create_draft(conn, athlete_id, COACH_NOTE, today, body)
        db.review_draft(
            conn, athlete_id, COACH_NOTE, today,
            status="approved", reviewed_by=settings.coach_name, body=body,
        )
    except ValueError as exc:
        return ("err", f"Not queued: {exc}")
    finally:
        conn.close()
    return ("ok", "Queued. It goes out on the next send, in the athlete's timezone.")


def _optional_number(raw: str, *, integer: bool = False):
    value = (raw or "").strip()
    if not value:
        return None
    try:
        return int(value) if integer else float(value)
    except ValueError as exc:
        raise ValueError(f"{value!r} is not a valid number") from exc


def _goal_date_from_form(form: dict[str, str]) -> str | None:
    """Join the cross-browser day/month/year controls into one ISO date."""
    legacy = form.get("goal_target_date", "").strip()
    if legacy:
        try:
            return date.fromisoformat(legacy).isoformat()
        except ValueError as exc:
            raise ValueError("goal date must be a valid date") from exc
    pieces = tuple(form.get(key, "").strip() for key in (
        "goal_day", "goal_month", "goal_year"
    ))
    if not any(pieces):
        return None
    if not all(pieces):
        raise ValueError("select the goal day, month, and year")
    try:
        day, month, year = (int(value) for value in pieces)
        return date(year, month, day).isoformat()
    except (TypeError, ValueError) as exc:
        raise ValueError("goal date must be a valid calendar date") from exc


def _register(form: dict[str, str]) -> tuple[str, str]:
    athlete_id = form.get("athlete_id", "")
    name = form.get("name", "")
    conn = db.connect()
    try:
        db.init_db(conn)
        db.register_athlete(
            conn,
            athlete_id,
            name,
            on=date.today().isoformat(),
            bodyweight_kg=_optional_number(form.get("bodyweight_kg", "")),
            squat_1rm_kg=_optional_number(form.get("squat_1rm_kg", "")),
            bench_1rm_kg=_optional_number(form.get("bench_1rm_kg", "")),
            deadlift_1rm_kg=_optional_number(form.get("deadlift_1rm_kg", "")),
            training_days=_optional_number(form.get("training_days", ""), integer=True),
            experience=form.get("experience", "").strip() or None,
            injury_note=form.get("injury_note", ""),
            goal_lift=form.get("goal_lift", "").strip() or None,
            goal_target_kg=_optional_number(form.get("goal_target_kg", "")),
            goal_target_date=_goal_date_from_form(form),
            created_by=settings.coach_name,
        )
    except ValueError as exc:
        return ("err", f"Not added: {exc}")
    finally:
        conn.close()
    return ("ok", f"{name.strip()} added. They appear once they text, or right away here.")


@app.get("/coach/outbox", response_class=HTMLResponse)
async def coach_outbox(request: Request, token: str = "") -> Response:
    """Tonight's queue: what wants to go out tomorrow, and why."""
    effective_token = token.strip() if token else request.cookies.get(COOKIE_NAME, "").strip()
    if not effective_token:
        return RedirectResponse(url="/coach/login", status_code=303)
    try:
        coach_auth.check(effective_token)
    except coach_auth.CoachAuthError as exc:
        return HTMLResponse(render_login(error=str(exc)), status_code=403)
    return HTMLResponse(await run_in_threadpool(_render_outbox, effective_token, None))


@app.get("/coach/whatsapp", response_class=HTMLResponse)
async def coach_whatsapp(request: Request, tab: str = "inbox", athlete: str = "") -> Response:
    """The daily message desk: feedback, approval, schedule and delivery."""
    token = request.cookies.get(COOKIE_NAME, "").strip()
    if not token:
        return RedirectResponse(url="/coach/login", status_code=303)
    try:
        coach_auth.check(token)
    except coach_auth.CoachAuthError as exc:
        return HTMLResponse(render_login(error=str(exc)), status_code=403)
    valid_tab = tab if tab in {"inbox", "approval", "scheduled", "sent"} else "inbox"
    return HTMLResponse(
        await run_in_threadpool(_render_whatsapp, valid_tab, athlete.strip(), None)
    )


@app.get("/coach/analytics", response_class=HTMLResponse)
async def coach_analytics(request: Request) -> Response:
    token = request.cookies.get(COOKIE_NAME, "").strip()
    if not token:
        return RedirectResponse(url="/coach/login", status_code=303)
    try:
        coach_auth.check(token)
    except coach_auth.CoachAuthError as exc:
        return HTMLResponse(render_login(error=str(exc)), status_code=403)
    return HTMLResponse(await run_in_threadpool(_render_analytics))


def _render_analytics() -> str:
    conn = db.connect()
    try:
        db.init_db(conn)
        paces = squad_goal_paces(conn, today=date.today())
        pending_count = len(db.pending_drafts(conn))
    finally:
        conn.close()
    return render_analytics(
        paces, coach=settings.coach_name, today=date.today(),
        pending_count=pending_count,
    )


@app.post("/coach/whatsapp/review", response_class=HTMLResponse)
async def coach_whatsapp_review(request: Request) -> Response:
    form = dict(await request.form())
    token = request.cookies.get(COOKIE_NAME, "").strip()
    if not token:
        return RedirectResponse(url="/coach/login", status_code=303)
    try:
        coach_auth.check(token)
    except coach_auth.CoachAuthError as exc:
        return HTMLResponse(render_login(error=str(exc)), status_code=403)
    result = await run_in_threadpool(
        _review_draft,
        str(form.get("athlete_id", "")).strip(),
        str(form.get("message_kind", "")).strip(),
        str(form.get("local_date", "")).strip(),
        str(form.get("decision", "")).strip(),
        str(form.get("body", "")),
    )
    return HTMLResponse(await run_in_threadpool(_render_whatsapp, "approval", "", result))


@app.post("/coach/whatsapp/bulk-approve", response_class=HTMLResponse)
async def coach_whatsapp_bulk_approve(request: Request) -> Response:
    token = request.cookies.get(COOKIE_NAME, "").strip()
    if not token:
        return RedirectResponse(url="/coach/login", status_code=303)
    try:
        coach_auth.check(token)
    except coach_auth.CoachAuthError as exc:
        return HTMLResponse(render_login(error=str(exc)), status_code=403)
    result = await run_in_threadpool(_bulk_approve_unchanged)
    return HTMLResponse(await run_in_threadpool(_render_whatsapp, "approval", "", result))


@app.post("/coach/whatsapp/reviewed", response_class=HTMLResponse)
async def coach_whatsapp_mark_reviewed(request: Request) -> Response:
    form = dict(await request.form())
    token = request.cookies.get(COOKIE_NAME, "").strip()
    if not token:
        return RedirectResponse(url="/coach/login", status_code=303)
    try:
        coach_auth.check(token)
    except coach_auth.CoachAuthError as exc:
        return HTMLResponse(render_login(error=str(exc)), status_code=403)
    athlete_id = str(form.get("athlete_id", "")).strip()
    result = await run_in_threadpool(_mark_feedback_reviewed, athlete_id)
    return HTMLResponse(await run_in_threadpool(_render_whatsapp, "inbox", athlete_id, result))


@app.post("/coach/whatsapp/simulate", response_class=HTMLResponse)
async def coach_whatsapp_simulate(request: Request) -> Response:
    form = dict(await request.form())
    token = request.cookies.get(COOKIE_NAME, "").strip()
    if not token:
        return RedirectResponse(url="/coach/login", status_code=303)
    try:
        coach_auth.check(token)
    except coach_auth.CoachAuthError as exc:
        return HTMLResponse(render_login(error=str(exc)), status_code=403)
    athlete_id = str(form.get("athlete_id", "")).strip()
    body = str(form.get("body", "")).strip()
    if not is_demo(athlete_id) or not body:
        result = ("err", "Simulations require a demo athlete and a message.")
    else:
        await run_in_threadpool(
            _process, athlete_id, body, "SIM" + secrets.token_hex(12)
        )
        result = ("ok", "Simulated athlete message received and processed.")
    return HTMLResponse(await run_in_threadpool(_render_whatsapp, "inbox", athlete_id, result))


def _bulk_approve_unchanged() -> tuple[str, str]:
    conn = db.connect()
    try:
        db.init_db(conn)
        count = db.bulk_approve_unchanged(conn, reviewed_by=settings.coach_name)
    except ValueError as exc:
        return ("err", f"Nothing approved: {exc}")
    finally:
        conn.close()
    return ("ok", f"Approved {count} unchanged morning message(s).")


def _mark_feedback_reviewed(athlete_id: str) -> tuple[str, str]:
    if not athlete_id:
        return ("err", "No athlete was selected.")
    conn = db.connect()
    try:
        db.init_db(conn)
        db.mark_whatsapp_conversation_reviewed(conn, athlete_id)
    finally:
        conn.close()
    return ("ok", "Feedback marked as reviewed.")


def _render_whatsapp(
    tab: str, athlete_id: str, message: tuple[str, str] | None
) -> str:
    conn = db.connect()
    try:
        db.init_db(conn)
        pending = pending_reviews(conn, today=date.today())
        conversations = db.whatsapp_conversations(conn)
        selected = athlete_id or (
            str(conversations[0]["athlete_id"]) if conversations else ""
        )
        messages = db.whatsapp_messages(conn, selected, limit=100) if selected else []
        selected_name = db.athlete_name(conn, selected) or selected
        demo_athletes = tuple(
            (candidate, db.athlete_name(conn, candidate) or candidate)
            for candidate in db.list_athletes(conn) if is_demo(candidate)
        )
        scheduled = db.approved_drafts(conn, "morning_checkin") + db.approved_drafts(conn, COACH_NOTE)
        sent = [
            row for row in db.whatsapp_messages(conn, limit=300)
            if row["direction"] == "outbound"
        ]
    finally:
        conn.close()
    return render_whatsapp_desk(
        conversations=conversations, messages=messages, pending=pending,
        scheduled=scheduled, sent=sent, selected_athlete=selected,
        selected_name=selected_name, tab=tab, coach=settings.coach_name,
        demo_athletes=demo_athletes, today=date.today(), message=message,
        transport_ready=settings.whatsapp_configured,
        transport_name=settings.whatsapp_transport_name,
    )


@app.post("/coach/outbox/review", response_class=HTMLResponse)
async def coach_review_draft(request: Request) -> Response:
    form = dict(await request.form())
    token = str(form.get("token", "")).strip() or request.cookies.get(COOKIE_NAME, "").strip()
    if not token:
        return RedirectResponse(url="/coach/login", status_code=303)
    try:
        coach_auth.check(token)
    except coach_auth.CoachAuthError as exc:
        return HTMLResponse(render_login(error=str(exc)), status_code=403)

    message = await run_in_threadpool(
        _review_draft,
        str(form.get("athlete_id", "")).strip(),
        str(form.get("message_kind", "")).strip(),
        str(form.get("local_date", "")).strip(),
        str(form.get("decision", "")).strip(),
        str(form.get("body", "")),
    )
    return HTMLResponse(await run_in_threadpool(_render_outbox, token, message))


def _review_draft(
    athlete_id: str, message_kind: str, local_date: str, decision: str, body: str
) -> tuple[str, str]:
    conn = db.connect()
    try:
        db.init_db(conn)
        db.review_draft(
            conn, athlete_id, message_kind, local_date,
            status=decision, reviewed_by=settings.coach_name, body=body,
        )
    except ValueError as exc:
        return ("err", f"Not saved: {exc}")
    finally:
        conn.close()
    verb = "approved for" if decision == "approved" else "held back from"
    return ("ok", f"Message {verb} {athlete_id} on {local_date}.")


def _render_outbox(token: str, message: tuple[str, str] | None) -> str:
    conn = db.connect()
    try:
        db.init_db(conn)
        pending = pending_reviews(conn, today=date.today())
    finally:
        conn.close()
    return render_outbox(
        pending, token=token, coach=settings.coach_name, today=date.today(),
        message=message,
    )


@app.get("/privacy", response_class=HTMLResponse)
async def privacy_policy() -> str:
    return render_privacy()


@app.get("/terms", response_class=HTMLResponse)
async def terms() -> str:
    return render_terms()


@app.get("/health")
async def health() -> dict[str, object]:
    return {
        "status": "ok",
        "model": settings.gemini_model if settings.gemini_api_key else "offline-stub",
        "database": str(settings.db_file),
        "signature_validation": (
            bool(settings.vonage_webhook_secret)
            if settings.vonage_configured
            else settings.validate_twilio_signature
        ),
        "whatsapp_integration": settings.whatsapp_configured,
        "whatsapp_transport": settings.whatsapp_transport_name,
        "morning_scheduler": settings.enable_morning_scheduler,
        "calendar_integration": settings.calendar_configured,
    }


@app.get("/integrations/google/calendar/start")
async def google_calendar_start(token: str) -> Response:
    """Validate the WhatsApp-issued identity link before sending it to Google."""
    if not settings.calendar_configured:
        return HTMLResponse("Calendar integration is not configured.", status_code=503)
    try:
        state_signer().verify(token)
        return RedirectResponse(calendar_oauth().authorization_url(token), status_code=302)
    except CalendarIntegrationError as exc:
        return HTMLResponse(str(exc), status_code=400)


@app.get("/integrations/google/calendar/callback")
async def google_calendar_callback(request: Request) -> Response:
    """Exchange the one-time Google code and store only encrypted tokens."""
    if request.query_params.get("error"):
        return HTMLResponse("Calendar access was not granted. You can close this tab.", status_code=400)
    code = request.query_params.get("code", "")
    state = request.query_params.get("state", "")
    conn = db.connect()
    try:
        if not code or not state:
            raise CalendarIntegrationError("Google returned an incomplete authorization response")
        db.init_db(conn)
        athlete_id = state_signer().verify(state)
        tokens = calendar_oauth().exchange_code(code)
        calendar_client(conn).save_tokens(athlete_id, tokens)
        return HTMLResponse(
            "<h1>Calendar connected</h1><p>Return to WhatsApp and ask me to plan training.</p>"
        )
    except CalendarIntegrationError as exc:
        log.warning("calendar OAuth failed: %s", exc)
        return HTMLResponse(f"Calendar connection failed: {exc}", status_code=400)
    finally:
        conn.close()


@app.post("/webhook/whatsapp")
async def whatsapp_webhook(request: Request) -> Response:
    form = dict(await request.form())
    url = whatsapp.webhook_url(str(request.url))
    signature = request.headers.get("X-Twilio-Signature")

    if not whatsapp.is_valid_signature(url, {k: str(v) for k, v in form.items()}, signature):
        log.warning("rejected request with a bad Twilio signature")
        return Response(status_code=403, content="invalid signature")

    athlete_id = whatsapp.athlete_id_from_sender(str(form.get("From", "")))
    body = str(form.get("Body", ""))
    provider_sid = str(form.get("MessageSid", "")).strip()
    if not athlete_id:
        return Response(
            content=whatsapp.twiml(["Couldn't identify the sender."]),
            media_type="application/xml",
        )

    log.info("message from %s: %r", athlete_id, body[:120])
    reply = await run_in_threadpool(_process, athlete_id, body, provider_sid)
    return Response(
        content=whatsapp.twiml(whatsapp.chunk(reply)), media_type="application/xml"
    )


def _process(athlete_id: str, body: str, provider_sid: str = "") -> str:
    """Blocking work — one SQLite connection per request keeps threads honest."""
    conn = db.connect()
    try:
        db.init_db(conn)
        if provider_sid and db.whatsapp_message_by_sid(conn, provider_sid) is not None:
            previous = db.whatsapp_reply_to(conn, provider_sid)
            return str(previous["body"]) if previous is not None else "Message received."
        db.record_whatsapp_message(
            conn, athlete_id=athlete_id, direction="inbound", body=body,
            status="received", provider_sid=provider_sid or None,
            message_kind="athlete_feedback",
        )
        reply = handle_message(conn, athlete_id, body, get_model_client())
        identity = provider_sid or hashlib.sha256(
            f"{athlete_id}|{date.today().isoformat()}|{body}".encode("utf-8")
        ).hexdigest()[:20]
        db.create_draft(
            conn, athlete_id, FEEDBACK_REPLY + identity,
            date.today().isoformat(), reply,
        )
        injured, _ = db.injury_state(conn, athlete_id)
        acknowledgement = INJURY_ACK if injured else FEEDBACK_ACK
        db.record_whatsapp_message(
            conn, athlete_id=athlete_id, direction="outbound", body=acknowledgement,
            status="queued", message_kind="receipt",
            reply_to_sid=provider_sid or None,
        )
        return acknowledgement
    except Exception:  # noqa: BLE001
        log.exception("failed to handle message from %s", athlete_id)
        return "Something broke on my end. Your message wasn't logged — send it again."
    finally:
        conn.close()


@app.post("/webhook/whatsapp/status")
async def whatsapp_status_webhook(request: Request) -> Response:
    """Apply Twilio delivery callbacks to the message ledger."""
    form = dict(await request.form())
    url = whatsapp.webhook_url(str(request.url))
    signature = request.headers.get("X-Twilio-Signature")
    if not whatsapp.is_valid_signature(url, {k: str(v) for k, v in form.items()}, signature):
        return Response(status_code=403, content="invalid signature")
    sid = str(form.get("MessageSid", "")).strip()
    status = str(form.get("MessageStatus", "")).strip().lower()
    status = {"accepted": "queued", "sending": "queued", "undelivered": "failed"}.get(
        status, status
    )
    error_code = str(form.get("ErrorCode", "")).strip() or None
    conn = db.connect()
    try:
        db.init_db(conn)
        db.update_whatsapp_status(conn, sid, status, error_code=error_code)
    finally:
        conn.close()
    return Response(status_code=204)


@app.post("/webhook/vonage/inbound")
async def vonage_whatsapp_webhook(request: Request) -> Response:
    """Receive a Vonage Sandbox message and send the neutral receipt via REST."""
    if not vonage.valid_webhook_secret(request.query_params.get("token")):
        log.warning("rejected request with a bad Vonage webhook secret")
        return Response(status_code=403, content="invalid webhook secret")
    try:
        payload = await request.json()
    except ValueError:
        return Response(status_code=400, content="invalid JSON")
    athlete_id = vonage.athlete_id_from_sender(str(payload.get("from", "")))
    body = str(payload.get("text", "")).strip()
    provider_sid = str(payload.get("message_uuid", "")).strip()
    if not athlete_id or not body or not provider_sid:
        return Response(status_code=400, content="incomplete WhatsApp message")

    log.info("Vonage message from %s: %r", athlete_id, body[:120])
    reply = await run_in_threadpool(_process, athlete_id, body, provider_sid)
    try:
        outbound_sid = await run_in_threadpool(
            whatsapp.send_outbound, athlete_id, reply
        )
        conn = db.connect()
        try:
            db.init_db(conn)
            db.attach_whatsapp_reply_sid(conn, provider_sid, outbound_sid)
        finally:
            conn.close()
    except Exception:  # noqa: BLE001 - a non-2xx response asks Vonage to retry
        log.exception("failed to send Vonage acknowledgement to %s", athlete_id)
        return Response(status_code=502, content="outbound acknowledgement failed")
    return Response(status_code=200, content="ok")


@app.post("/webhook/vonage/status")
async def vonage_status_webhook(request: Request) -> Response:
    """Apply Vonage delivery/read/failure callbacks to the shared ledger."""
    if not vonage.valid_webhook_secret(request.query_params.get("token")):
        return Response(status_code=403, content="invalid webhook secret")
    try:
        payload = await request.json()
    except ValueError:
        return Response(status_code=400, content="invalid JSON")
    sid = str(payload.get("message_uuid", "")).strip()
    status = vonage.ledger_status(str(payload.get("status", "")))
    error = payload.get("error") if isinstance(payload.get("error"), dict) else {}
    error_code = str(error.get("title") or error.get("detail") or "").strip() or None
    if sid and status:
        conn = db.connect()
        try:
            db.init_db(conn)
            db.update_whatsapp_status(conn, sid, status, error_code=error_code)
        finally:
            conn.close()
    return Response(status_code=200, content="ok")

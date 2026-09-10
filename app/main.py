"""FastAPI service: Twilio WhatsApp sandbox in, templated coaching reply out.

    Twilio  ->  POST /webhook/whatsapp
                  |
                  |-- Layer 1  app.agent      Gemini -> validated tool calls
                  |-- Layer 2  app.storage    SQLite append
                  |-- Layer 3  app.decision   verdict + reply text
                  v
                TwiML response  ->  Twilio  ->  WhatsApp
"""

from __future__ import annotations

import asyncio
import logging
from datetime import date
from contextlib import asynccontextmanager
from contextlib import suppress
from functools import lru_cache

from fastapi import FastAPI, Request, Response
from fastapi.responses import HTMLResponse, RedirectResponse
from starlette.concurrency import run_in_threadpool

from app.agent.offline import OfflineClient
from app.agent.parser import GeminiClient, ModelClient
from app.channels import whatsapp
from app.coach import auth as coach_auth
from app.coach.demo import clear_demo_squad, is_demo, seed_demo_squad
from app.coach import (
    COOKIE_NAME,
    build_roster,
    pending_reviews,
    render as render_roster,
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
        return send_approved_prompts(conn, whatsapp.send_outbound)
    finally:
        conn.close()


app = FastAPI(
    title="Powerlifting Training-Log Agent",
    version="0.2.0",
    description="WhatsApp coaching with deterministic readiness, nutrition and calendar planning.",
    lifespan=lifespan,
)


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
    reason = str(form.get("reason", "")).strip()
    message = await run_in_threadpool(_clear_injury, athlete_id, reason)
    html = await run_in_threadpool(_render_console, token, message)
    return HTMLResponse(html)


def _clear_injury(athlete_id: str, reason: str) -> tuple[str, str]:
    conn = db.connect()
    try:
        db.init_db(conn)
        db.clear_injury(conn, athlete_id, actor=settings.coach_name, reason=reason)
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
    finally:
        conn.close()
    has_demo = any(is_demo(a) for a in roster_ids)
    return render_roster(
        roster, token=token, coach=settings.coach_name, message=message,
        has_demo=has_demo,
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
        "signature_validation": settings.validate_twilio_signature,
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
    if not athlete_id:
        return Response(
            content=whatsapp.twiml(["Couldn't identify the sender."]),
            media_type="application/xml",
        )

    log.info("message from %s: %r", athlete_id, body[:120])
    reply = await run_in_threadpool(_process, athlete_id, body)
    return Response(
        content=whatsapp.twiml(whatsapp.chunk(reply)), media_type="application/xml"
    )


def _process(athlete_id: str, body: str) -> str:
    """Blocking work — one SQLite connection per request keeps threads honest."""
    conn = db.connect()
    try:
        db.init_db(conn)
        return handle_message(conn, athlete_id, body, get_model_client())
    except Exception:  # noqa: BLE001
        log.exception("failed to handle message from %s", athlete_id)
        return "Something broke on my end. Your message wasn't logged — send it again."
    finally:
        conn.close()

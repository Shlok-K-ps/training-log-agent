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
from contextlib import asynccontextmanager
from contextlib import suppress
from functools import lru_cache

from fastapi import FastAPI, Request, Response
from fastapi.responses import HTMLResponse, RedirectResponse
from starlette.concurrency import run_in_threadpool

from app.agent.offline import OfflineClient
from app.agent.parser import GeminiClient, ModelClient
from app.channels import whatsapp
from app.config import settings
from app.integrations.factory import calendar_client, calendar_oauth, state_signer
from app.integrations.google_calendar import CalendarIntegrationError
from app.router import handle_message
from app.scheduling import send_due_morning_prompts
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
    conn = db.connect()
    try:
        db.init_db(conn)
        return send_due_morning_prompts(conn, whatsapp.send_outbound)
    finally:
        conn.close()


app = FastAPI(
    title="Powerlifting Training-Log Agent",
    version="0.2.0",
    description="WhatsApp coaching with deterministic readiness, nutrition and calendar planning.",
    lifespan=lifespan,
)


@app.get("/", response_class=HTMLResponse)
async def product_home() -> str:
    return """
    <h1>Power Coach</h1>
    <p>A WhatsApp powerlifting assistant that plans training from athlete-provided
    readiness, food access and approved supplement information.</p>
    <p>Optional Google Calendar access finds feasible workout times around busy
    events and travel. Calendar changes require confirmation in WhatsApp.</p>
    <p><a href='/privacy'>Privacy</a> · <a href='/terms'>Terms</a></p>
    """


@app.get("/privacy", response_class=HTMLResponse)
async def privacy_policy() -> str:
    return """
    <h1>Privacy</h1>
    <p>Calendar connection is optional. The service reads event start/end times and
    usable locations only to plan travel and training. It does not retain event
    titles, descriptions, attendees or meeting content.</p>
    <p>OAuth tokens and saved places are encrypted at rest when the calendar
    integration is configured. Confirmed workout
    references are stored until the athlete asks to delete them. Calendar data is
    not sold and is not sent to the language model.</p>
    <p>Training, sleep, readiness and nutrition messages may be sent to the
    configured language-model provider for structured parsing. Coaching decisions
    are made by deterministic application rules, not by that model.</p>
    <p>Send “disconnect calendar” in WhatsApp to delete stored calendar tokens. Send
    “forget my locations” to delete saved home, office and gym places.</p>
    """


@app.get("/terms", response_class=HTMLResponse)
async def terms() -> str:
    return """
    <h1>Terms</h1>
    <p>This service is a training-log and planning aid, not medical care. Athletes
    remain responsible for confirming calendar changes and following advice from
    their coach, clinician or dietitian. Injury and severe-recovery flags suppress
    load advice.</p>
    """


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

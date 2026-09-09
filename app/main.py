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
from starlette.concurrency import run_in_threadpool

from app.agent.offline import OfflineClient
from app.agent.parser import GeminiClient, ModelClient
from app.channels import whatsapp
from app.config import settings
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
    version="0.1.0",
    description="WhatsApp in, deterministic coaching verdict out.",
    lifespan=lifespan,
)


@app.get("/health")
async def health() -> dict[str, object]:
    return {
        "status": "ok",
        "model": settings.gemini_model if settings.gemini_api_key else "offline-stub",
        "database": str(settings.db_file),
        "signature_validation": settings.validate_twilio_signature,
        "morning_scheduler": settings.enable_morning_scheduler,
    }


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

"""FastAPI service for the Power AI training-day agent, served by Uvicorn on Render.

    Telegram  ->  POST /webhook/telegram
                  |
                  |-- app.agent      Gemini 2.5 Flash -> validated structured data
                  |-- app.casework   the training-day case engine (the agent loop)
                  |-- app.decision   fixed, tested coaching and safety rules
                  |-- app.storage    Neon Postgres when deployed; SQLite locally and in tests
                  v
                check-ins, follow-ups, sessions and escalations  ->  Telegram

GitHub Actions calls the signed /internal/agent/tick endpoint to wake the loop.
The /webhook/whatsapp and /webhook/vonage routes are historical experiments with
Twilio and Vonage; the deployed product does not use them.
"""

from __future__ import annotations

import asyncio
import hashlib
import json
import logging
import re
import secrets
from datetime import date
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError
from contextlib import asynccontextmanager
from contextlib import suppress
from functools import lru_cache
from urllib.parse import quote, unquote

from fastapi import FastAPI, Request, Response
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles
from starlette.concurrency import run_in_threadpool

from app.agent.offline import OfflineClient
from app.agent.parser import GeminiClient, ModelClient
from app import access, deployment, public_demo
from app.agent.schemas import LOOP_TOOL_NAMES
from app.casework import board as agent_board
from app.casework import clock, demo_day, engine
from app.casework import status as agent_status
from app.coach import demo_view, onboarding_view
from app.casework import store as case_store
from app.coach import agent_view
from app.coach.view import banner, coach_frame
from app.casework.transport import DeliveryFailed, LiveTransport
from app.channels import telegram, vonage, whatsapp
from app.decision.injury_pivot import injury_pivot_options, pivot_message
from app.coach.athlete import athlete_detail, suggest_message
from app.coach.athlete_view import render_athlete
from app.coach.analytics_view import render_analytics
from app.coach.progress import squad_goal_paces
from app.coach.whatsapp_view import render_whatsapp_desk
from app.coach.demo import clear_demo_squad, is_demo, seed_demo_squad
from app.scheduling.outbox import (
    COACH_NOTE,
    FEEDBACK_REPLY,
    INJURY_PLAN,
    MORNING,
    new_coach_note_kind,
    send_approved_feedback,
    send_approved_notes,
)
from app.coach import (
    build_roster,
    pending_reviews,
    render as render_roster,
    render_athletes,
    render_landing,
    render_privacy,
    render_terms,
)
from app.config import settings
from app.integrations.factory import calendar_client, calendar_oauth, state_signer
from app.integrations.google_calendar import CalendarIntegrationError
from app.router import handle_message_with_actions
from app.scheduling import draft_upcoming_prompts, send_approved_prompts
from app.storage import db

logging.basicConfig(
    level=logging.INFO, format="%(asctime)s %(levelname)-7s %(name)s: %(message)s"
)
log = logging.getLogger("power-agent")

FEEDBACK_ACK = "Got it — I’ve logged your update and sent it to your coach for review."
# Channels where the training-day agent reads the message and may answer itself.
AGENT_CHANNELS = frozenset({"telegram", "simulator"})
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
    log.info("database ready (%s)", deployment.storage_backend())
    app.state.telegram_webhook_ready = False
    app.state.telegram_webhook_error = None
    if settings.telegram_configured:
        try:
            await run_in_threadpool(telegram.configure_webhook)
            app.state.telegram_webhook_ready = True
            log.info("Telegram webhook connected")
        except Exception as exc:  # noqa: BLE001 - service and simulator must still boot
            # Telegram transport exceptions deliberately contain no credentials.
            app.state.telegram_webhook_error = str(exc)
            log.exception("Telegram webhook setup failed")
    tasks = []
    blocker = deployment.agent_blocker()
    if blocker:
        log.error(blocker)
    if settings.enable_agent_loop:
        # The case engine is the only owner of proactive check-ins: the legacy
        # morning scheduler is never started alongside it.
        if settings.agent_background_ticks:
            tasks.append(asyncio.create_task(_agent_loop()))
            log.info("training-day agent loop started (%s)", deployment.status()["agent_loop"])
    elif settings.enable_morning_scheduler:
        tasks.append(asyncio.create_task(_morning_scheduler_loop()))
        log.info("legacy morning scheduler enabled because the training-day agent is off")
    try:
        yield
    finally:
        for task in tasks:
            task.cancel()
            with suppress(asyncio.CancelledError):
                await task


async def _agent_loop() -> None:
    """Wake the agent every minute while the process is awake.

    A free web service sleeps when idle, so an external scheduler also calls the
    signed tick endpoint. The lease and idempotency keys make both safe at once.
    """
    while True:
        try:
            await run_in_threadpool(_run_agent_tick)
            await run_in_threadpool(_send_approved_coach_messages)
        except Exception:  # noqa: BLE001 - keep the web service alive and retry later
            log.exception("training-day agent tick failed")
        await asyncio.sleep(60)


def _run_agent_tick() -> dict[str, object]:
    blocker = deployment.agent_blocker()
    if not settings.enable_agent_loop or blocker:
        return {"skipped": True, "blocked": blocker or "The training-day agent is disabled."}
    conn = db.connect()
    try:
        db.init_db(conn)
        report = engine.tick(
            conn, now=clock.utcnow(), transport=LiveTransport(), coach_name=settings.coach_name
        )
        if report.actions or report.opened or report.escalated or report.closed:
            log.info("agent tick: %s", report.as_dict())
        return report.as_dict()
    finally:
        conn.close()


async def _morning_scheduler_loop() -> None:
    while True:
        try:
            await run_in_threadpool(_send_morning_prompts)
        except Exception:  # noqa: BLE001 - keep the web service alive and retry later
            log.exception("morning check-in scheduler failed")
        await asyncio.sleep(60)


def _recorded_sender(conn):
    def recorded_sender(athlete_id: str, body: str) -> None:
        telegram_chat = db.telegram_chat_id(conn, athlete_id)
        if settings.telegram_configured and telegram_chat:
            provider_sid = telegram.send_outbound(telegram_chat, body)
            channel = "telegram"
        else:
            provider_sid = whatsapp.send_outbound(athlete_id, body)
            channel = "whatsapp"
        db.record_whatsapp_message(
            conn, athlete_id=athlete_id, direction="outbound", body=body,
            status="sent" if channel == "telegram" else "queued",
            provider_sid=provider_sid, message_kind="scheduled",
            channel=channel,
        )

    return recorded_sender


def _send_approved_coach_messages() -> int:
    """Send notes the coach wrote and replies the coach approved. Never check-ins."""
    conn = db.connect()
    try:
        db.init_db(conn)
        sender = _recorded_sender(conn)
        return send_approved_notes(conn, sender) + send_approved_feedback(conn, sender)
    finally:
        conn.close()


def _send_morning_prompts() -> int:
    """Legacy morning scheduler: draft tomorrow's check-ins, send approved messages.

    Dormant whenever ENABLE_AGENT_LOOP is on; the training-day agent then owns
    every proactive check-in and this is never scheduled or called by a tick.
    """
    conn = db.connect()
    try:
        db.init_db(conn)
        drafted = draft_upcoming_prompts(conn)
        if drafted:
            log.info("queued %d morning message(s) for coach review", len(drafted))
        sender = _recorded_sender(conn)
        sent = send_approved_prompts(conn, sender)
        sent += send_approved_notes(conn, sender)
        return sent + send_approved_feedback(conn, sender)
    finally:
        conn.close()


app = FastAPI(
    title="Power AI — Powerlifting Training-Log Agent",
    version="0.2.0",
    description=(
        "Training-day agent for a powerlifting coach: Telegram messaging, Gemini 2.5 Flash "
        "message interpretation, tested rules for coaching and safety decisions, and Neon "
        "Postgres memory."
    ),
    lifespan=lifespan,
)

@app.get("/favicon.ico", include_in_schema=False)
async def favicon() -> Response:
    return Response(status_code=204)

app.mount("/static", StaticFiles(directory="app/static"), name="static")


@app.get("/", response_class=HTMLResponse)
async def product_home() -> Response:
    return HTMLResponse(render_landing())


@app.get("/demo", response_class=HTMLResponse)
async def watch_the_agent() -> Response:
    """Public, fictional, self-contained: runs the real agent in a throwaway database."""
    trace = await run_in_threadpool(public_demo.public_demo)
    return HTMLResponse(demo_view.render_public_demo(trace))


# --- Coach console ------------------------------------------------------------
# Every write redirects back to a page (post/redirect/get), so a browser refresh
# never repeats an approval, a note or a clearance. The outcome travels in a
# short-lived cookie and is shown once on the page the coach lands on.

FLASH_COOKIE = "coach_flash"


def _redirect(url: str, message: tuple[str, str] | None = None) -> RedirectResponse:
    response = RedirectResponse(url=url, status_code=303)
    if message is not None:
        response.set_cookie(
            FLASH_COOKIE, quote(json.dumps(list(message))),
            max_age=60, httponly=True, samesite="lax", path="/",
        )
    return response


def _take_flash(request: Request) -> tuple[str, str] | None:
    raw = request.cookies.get(FLASH_COOKIE)
    if not raw:
        return None
    try:
        kind, text = json.loads(unquote(raw))
    except (ValueError, TypeError):
        return None
    if kind not in {"ok", "warn", "err"} or not isinstance(text, str):
        return None
    return kind, text


def _page(request: Request, html: str | None) -> Response:
    if html is None:
        return HTMLResponse("<h1>Not found</h1><p>No such athlete.</p>", status_code=404)
    response = HTMLResponse(html)
    if FLASH_COOKIE in request.cookies:
        response.delete_cookie(FLASH_COOKIE, path="/")
    return response


def _return_to(form: dict, default: str) -> str:
    """Only ever send the coach back to a console page on this site."""
    target = str(form.get("return_to", "")).strip()
    if target.startswith("/coach") and not target.startswith("//"):
        return target
    return default


def _athlete_url(athlete_id: str, anchor: str = "") -> str:
    return f"/coach/athlete/{quote(athlete_id)}" + (f"#{anchor}" if anchor else "")


LOCKED_PAGE = """<!doctype html><html lang="en"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>Coach console · Power AI</title>
<link rel="stylesheet" href="/static/tokens.css"><link rel="stylesheet" href="/static/app.css">
</head><body><main style="max-width:32rem;margin:12vh auto;padding:0 1.5rem">
<h1 style="font-size:1.75rem;letter-spacing:-.02em">Open the console from Telegram</h1>
<p>The coach console has no password. Send <b>/console</b> to the Power AI bot from the
coach's linked Telegram account and open the link it replies with. Links expire after
15 minutes.</p>
<p style="color:var(--text-2,#6b6b70)">First time? Send <b>/coach</b> followed by the
deployment's setup code to link your Telegram account.</p>
<p><a href="/">About Power AI</a></p></main></body></html>"""


@app.middleware("http")
async def coach_console_guard(request: Request, call_next):
    """Every /coach page needs a session started from a signed Telegram link."""
    path = request.url.path
    if path.startswith("/coach") and path != "/coach/enter" and not access.request_is_coach(request):
        return HTMLResponse(LOCKED_PAGE, status_code=401)
    return await call_next(request)


@app.get("/coach/enter", include_in_schema=False)
async def coach_enter(token: str = "") -> Response:
    target = access.verify_console_token(token)
    if target is None:
        return HTMLResponse(LOCKED_PAGE, status_code=401)
    response = RedirectResponse(url=target, status_code=303)
    response.set_cookie(
        access.SESSION_COOKIE, access.session_value(),
        max_age=access.SESSION_TTL_SECONDS, httponly=True, samesite="lax",
        secure=access.session_cookie_secure(), path="/",
    )
    return response


@app.get("/coach/login", include_in_schema=False)
async def coach_sign_in_retired() -> Response:
    """The desk has no password; old bookmarks land on it directly."""
    return RedirectResponse(url="/coach", status_code=303)


@app.get("/coach/logout", include_in_schema=False)
async def coach_sign_out() -> Response:
    response = RedirectResponse(url="/", status_code=303)
    response.delete_cookie(access.SESSION_COOKIE, path="/")
    return response


# --- The training-day agent's clock and the coach's decisions -----------------------


@app.post("/internal/agent/tick", include_in_schema=False)
async def agent_tick(request: Request) -> Response:
    """Signed, idempotent wake-up for the agent, called by an external scheduler."""
    if not access.valid_tick_request(
        request.headers.get("X-Agent-Timestamp"), request.headers.get("X-Agent-Signature")
    ):
        return Response(status_code=403, content="invalid tick signature")
    report = await run_in_threadpool(_run_agent_tick)
    if report.get("blocked"):
        return Response(status_code=503, content=json.dumps(report), media_type="application/json")
    try:
        await run_in_threadpool(_send_approved_coach_messages)
    except Exception:  # noqa: BLE001 - the agent tick already ran; approved sends retry next time
        log.exception("sending coach-approved messages failed during tick")
    return Response(content=json.dumps(report), media_type="application/json")


@app.post("/coach/agent/run", response_class=HTMLResponse)
async def coach_run_agent(request: Request) -> Response:
    form = dict(await request.form())
    report = await run_in_threadpool(_run_agent_tick)
    if report.get("blocked"):
        message = ("err", str(report["blocked"]))
    elif report.get("skipped"):
        message = ("warn", "The agent is already running; try again in a moment.")
    else:
        message = (
            "ok",
            f"Agent ran: {report['opened']} day(s) opened, {report['actions']} message(s) sent, "
            f"{report['escalated']} escalation(s), {report['closed']} case(s) closed.",
        )
    return _redirect(_return_to(form, "/coach"), message)


def _decide_case(case_id: int, option: str) -> tuple[bool, str]:
    conn = db.connect()
    try:
        db.init_db(conn)
        case = case_store.case_by_id(conn, case_id)
        if case is not None and case["simulated"]:
            # A simulated demo day keeps its own clock and only reaches the simulator.
            return engine.apply_coach_decision(
                conn, case_id, option, coach_name=settings.coach_name,
                now=demo_day.decision_time(case), transport=demo_day.SimulatorTransport(),
            )
        return engine.apply_coach_decision(
            conn, case_id, option, coach_name=settings.coach_name, now=clock.utcnow(),
            transport=LiveTransport(),
        )
    except DeliveryFailed as exc:
        return False, f"The decision was saved but the message could not be sent: {exc}"
    finally:
        conn.close()


@app.post("/coach/case/{case_id}/decide", response_class=HTMLResponse)
async def coach_decide_case(case_id: int, request: Request) -> Response:
    form = dict(await request.form())
    ok, text = await run_in_threadpool(_decide_case, case_id, str(form.get("option", "")))
    return _redirect(_return_to(form, f"/coach/case/{case_id}"), ("ok" if ok else "err", text))


def _demo_day(phase: str) -> tuple[str, str]:
    if not settings.enable_agent_loop:
        return ("err", "The training-day agent is disabled on this deployment.")
    if phase not in {"morning", "evening", "reset"}:
        return ("err", "Unknown demo step.")
    conn = db.connect()
    try:
        db.init_db(conn)
        if phase == "reset":
            removed = demo_day.reset(conn)
            return ("ok", f"Simulated demo day reset ({removed} case(s) removed).")
        return demo_day.play(conn, phase, coach_name=settings.coach_name)
    finally:
        conn.close()


@app.post("/coach/demo/day/{phase}", response_class=HTMLResponse)
async def coach_demo_day(phase: str, request: Request) -> Response:
    """The scripted, simulated demo day. Separate from the real-time agent."""
    form = dict(await request.form())
    result = await run_in_threadpool(_demo_day, phase)
    return _redirect(_return_to(form, "/coach#demo-day"), result)


@app.get("/coach", response_class=HTMLResponse)
async def coach_console(request: Request) -> Response:
    """Today: the decisions, approvals and exceptions waiting on the coach."""
    return _page(request, await run_in_threadpool(_render_console, _take_flash(request)))


def _current_injury_plan_title(conn, athlete_id: str) -> str | None:
    """The coach's chosen pivot for the athlete's current injury, if any."""
    entry_id = db.open_injury_entry_id(conn, athlete_id)
    decision = db.latest_injury_plan_decision(conn, athlete_id)
    if entry_id is None or decision is None or int(decision["injury_entry_id"]) != entry_id:
        return None
    _, note = db.injury_state(conn, athlete_id)
    code = str(decision["option_code"])
    return next(
        (option.title for option in injury_pivot_options(note) if option.code == code),
        code.replace("_", " ").capitalize(),
    )


def _render_console(message: tuple[str, str] | None) -> str:
    conn = db.connect()
    try:
        db.init_db(conn)
        today = date.today()
        roster = build_roster(conn, today=today)
        roster_ids = db.list_athletes(conn)
        pending = _reviewable(conn, today)
        injury_plans = tuple(
            (entry, _current_injury_plan_title(conn, entry.athlete_id))
            for entry in roster.entries
            if any(flag.kind == "injured" for flag in entry.flags)
        )
        board = agent_board.snapshot(conn, clock.utcnow())
        steps = agent_status.setup_checklist(
            conn, clock.utcnow(), telegram_available=settings.telegram_configured,
            agent_blocker=deployment.agent_blocker(),
        )
    finally:
        conn.close()
    return render_roster(
        roster, coach=settings.coach_name, message=message,
        has_demo=any(is_demo(a) for a in roster_ids),
        pending_count=len(pending), pending=pending, injury_plans=injury_plans,
        agent_board=agent_view.agent_board(board, blocker=deployment.agent_blocker()),
        extra_style=agent_view.AGENT_STYLE + onboarding_view.ONBOARDING_STYLE,
        setup_html=onboarding_view.setup_checklist(steps),
        empty_html=onboarding_view.empty_state() if not roster_ids else "",
    )


@app.get("/coach/case/{case_id}", response_class=HTMLResponse)
async def coach_case(case_id: int, request: Request) -> Response:
    """One training day: every observation, decision, action and outcome."""
    return _page(request, await run_in_threadpool(_render_case, case_id, _take_flash(request)))


def _render_case(case_id: int, message: tuple[str, str] | None) -> str | None:
    conn = db.connect()
    try:
        db.init_db(conn)
        case = case_store.case_by_id(conn, case_id)
        if case is None:
            return None
        events = case_store.case_events(conn, case_id)
        athlete_name = db.athlete_name(conn, str(case["athlete_id"])) or str(case["athlete_id"])
        pending_count = _pending_count(conn)
    finally:
        conn.close()
    body = agent_view.render_case_body(
        case, events, athlete_name=athlete_name, message_banner=banner(message)
    )
    return coach_frame(
        body, active="overview", coach=settings.coach_name,
        title=f"{athlete_name} · {case['local_date']}",
        subtitle="The agent's reasoning and actions for this training day, in order.",
        today=case["local_date"], pending_count=pending_count,
        extra_style=agent_view.AGENT_STYLE, athlete_id=str(case["athlete_id"]),
        back=("/coach", "Today"),
    )


def _plan_change(athlete_id: str, form: dict) -> tuple[str, str]:
    conn = db.connect()
    try:
        db.init_db(conn)
        if athlete_id not in db.list_athletes(conn):
            return ("err", "No such athlete.")
        case_store.add_plan_session(
            conn, athlete_id=athlete_id, weekday=int(str(form.get("weekday", ""))),
            lift=str(form.get("lift", "")), sets=int(str(form.get("sets", ""))),
            reps=int(str(form.get("reps", ""))), rpe=float(str(form.get("rpe", ""))),
            approved_by=settings.coach_name, now=clock.utcnow(),
        )
    except ValueError as exc:
        return ("err", f"Plan not changed: {exc}")
    finally:
        conn.close()
    return ("ok", "Lift approved. The agent will use it from the next training day it opens.")


@app.post("/coach/athlete/{athlete_id}/plan", response_class=HTMLResponse)
async def coach_add_plan_lift(athlete_id: str, request: Request) -> Response:
    form = dict(await request.form())
    result = await run_in_threadpool(_plan_change, athlete_id, form)
    return _redirect(_athlete_url(athlete_id, "agent-plan"), result)


def _retire_plan_lift(athlete_id: str, session_id: str) -> tuple[str, str]:
    conn = db.connect()
    try:
        db.init_db(conn)
        removed = session_id.isdigit() and case_store.retire_plan_session(
            conn, athlete_id, int(session_id), now=clock.utcnow()
        )
    finally:
        conn.close()
    return ("ok", "Lift removed from the plan.") if removed else ("err", "That lift was not in the plan.")


@app.post("/coach/athlete/{athlete_id}/plan/retire", response_class=HTMLResponse)
async def coach_retire_plan_lift(athlete_id: str, request: Request) -> Response:
    form = dict(await request.form())
    result = await run_in_threadpool(_retire_plan_lift, athlete_id, str(form.get("session_id", "")))
    return _redirect(_athlete_url(athlete_id, "agent-plan"), result)


def _toggle_autopilot(athlete_id: str, enabled: bool) -> tuple[str, str]:
    conn = db.connect()
    try:
        db.init_db(conn)
        if athlete_id not in db.list_athletes(conn):
            return ("err", "No such athlete.")
        case_store.set_autopilot(
            conn, athlete_id, enabled, updated_by=settings.coach_name, now=clock.utcnow()
        )
    finally:
        conn.close()
    return (
        "ok",
        "Autopilot on: routine days go out without you, held or reduced only."
        if enabled else "Autopilot off: every session now waits for your approval.",
    )


@app.post("/coach/athlete/{athlete_id}/autopilot", response_class=HTMLResponse)
async def coach_autopilot(athlete_id: str, request: Request) -> Response:
    form = dict(await request.form())
    result = await run_in_threadpool(
        _toggle_autopilot, athlete_id, str(form.get("enabled", "")) == "on"
    )
    return _redirect(_athlete_url(athlete_id, "agent-plan"), result)


@app.post("/coach/clear-injury", response_class=HTMLResponse)
async def coach_clear_injury(request: Request) -> Response:
    """The one write the console can make, and it records who made it."""
    form = dict(await request.form())
    athlete_id = str(form.get("athlete_id", "")).strip()
    clearance_source = str(form.get("clearance_source", "")).strip()
    reason = str(form.get("reason", "")).strip()
    confirmation = str(form.get("independent_confirmation", "")).strip()
    message = await run_in_threadpool(
        _clear_injury, athlete_id, clearance_source, reason, confirmation
    )
    anchor = "" if message[0] == "ok" else "clearance-review"
    return _redirect(_athlete_url(athlete_id, anchor), message)


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
    who = athlete_name or athlete_id
    return ("ok", f"Injury flag cleared for {who}, recorded against {settings.coach_name}.")


@app.get("/coach/athletes", response_class=HTMLResponse)
async def coach_athletes(request: Request) -> Response:
    """Searchable squad directory and the entry point to each athlete workspace."""
    return _page(request, await run_in_threadpool(_render_athlete_directory, _take_flash(request)))


def _render_athlete_directory(message: tuple[str, str] | None) -> str:
    conn = db.connect()
    try:
        db.init_db(conn)
        roster = build_roster(conn, today=date.today())
        roster_ids = db.list_athletes(conn)
        telegram_linked_ids = db.telegram_linked_athletes(conn)
        pending_count = _pending_count(conn)
    finally:
        conn.close()
    return render_athletes(
        roster, coach=settings.coach_name, message=message,
        has_demo=any(is_demo(a) for a in roster_ids), pending_count=pending_count,
        telegram_configured=settings.telegram_configured,
        telegram_ready=bool(getattr(app.state, "telegram_webhook_ready", False)),
        telegram_error=getattr(app.state, "telegram_webhook_error", None),
        telegram_linked_ids=telegram_linked_ids,
    )


@app.post("/coach/demo/seed", response_class=HTMLResponse)
async def coach_seed_demo(request: Request) -> Response:
    """Load a demo squad so an empty console can show what a full one looks like."""
    form = dict(await request.form())
    return _redirect(_return_to(form, "/coach"), await run_in_threadpool(_seed_demo))


@app.post("/coach/demo/clear", response_class=HTMLResponse)
async def coach_clear_demo(request: Request) -> Response:
    form = dict(await request.form())
    return _redirect(_return_to(form, "/coach"), await run_in_threadpool(_clear_demo))


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
async def coach_athlete(athlete_id: str, request: Request, welcome: str = "") -> Response:
    """One athlete: whether the agent can work, then evidence, plan and conversation."""
    return _page(
        request,
        await run_in_threadpool(_render_athlete, athlete_id, _take_flash(request), welcome == "1"),
    )


@app.post("/coach/athlete/{athlete_id}/message", response_class=HTMLResponse)
async def coach_message_athlete(athlete_id: str, request: Request) -> Response:
    """Queue a coach-written message. They wrote it, so it needs no second approval."""
    form = dict(await request.form())
    message = await run_in_threadpool(
        _queue_note, athlete_id, str(form.get("body", ""))
    )
    return _redirect(_athlete_url(athlete_id, "messages"), message)


@app.post("/coach/athlete/{athlete_id}/injury-plan", response_class=HTMLResponse)
async def coach_approve_injury_plan(athlete_id: str, request: Request) -> Response:
    """Choose one bounded training pivot and approve the message that explains it."""
    form = dict(await request.form())
    result = await run_in_threadpool(
        _approve_injury_plan,
        athlete_id,
        str(form.get("injury_entry_id", "")).strip(),
        str(form.get("option_code", "")).strip(),
        str(form.get("body", "")),
    )
    return _redirect(_athlete_url(athlete_id, "injury-plan"), result)


def _delivery_channel(conn, athlete_id: str) -> str:
    """Where an approved message will actually go, in words a coach can act on."""
    if settings.telegram_configured and db.telegram_chat_id(conn, athlete_id):
        return "goes out on the next send via Telegram"
    if settings.whatsapp_configured:
        return f"goes out on the next send via {settings.whatsapp_transport_name}"
    if settings.telegram_configured:
        return "goes out once this athlete connects Telegram"
    return "goes out once a messaging channel is connected"


def _approve_injury_plan(
    athlete_id: str, injury_entry_id_raw: str, option_code: str, edited_body: str = ""
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
            return ("err", "The injury changed; review the current options again.")
        _, note = db.injury_state(conn, athlete_id)
        option = next(
            (candidate for candidate in injury_pivot_options(note) if candidate.code == option_code),
            None,
        )
        if option is None:
            return ("err", "Choose one of the injury plans first.")
        body = edited_body.strip() or pivot_message(option, coach=settings.coach_name)
        db.record_injury_plan_decision(
            conn, athlete_id=athlete_id, injury_entry_id=supplied_id,
            option_code=option.code, plan_text=option.plan,
            approved_by=settings.coach_name,
        )
        today = date.today().isoformat()
        message_kind = f"{INJURY_PLAN}{supplied_id}"
        existing = db.draft(conn, athlete_id, message_kind, today)
        if existing is not None and str(existing["status"]) == "sent":
            # A changed plan after today's message went out is a new message.
            message_kind = f"{message_kind}:{secrets.token_hex(4)}"
        db.create_draft(conn, athlete_id, message_kind, today, body)
        db.review_draft(
            conn, athlete_id, message_kind, today,
            status="approved", reviewed_by=settings.coach_name, body=body,
        )
        channel = _delivery_channel(conn, athlete_id)
    except ValueError as exc:
        return ("err", f"Plan not approved: {exc}")
    finally:
        conn.close()
    return ("ok", f"“{option.title}” is now the plan. The message is scheduled and {channel}.")


@app.get("/coach/athletes/new", response_class=HTMLResponse)
async def coach_new_athlete(request: Request) -> Response:
    """Add an athlete with a name and usual times. No identifiers to invent."""
    message = _take_flash(request)

    def render() -> str:
        conn = db.connect()
        try:
            db.init_db(conn)
            pending_count = _pending_count(conn)
        finally:
            conn.close()
        return onboarding_view.new_athlete_page(
            coach=settings.coach_name, today=date.today(), pending_count=pending_count, message=message
        )

    return _page(request, await run_in_threadpool(render))


@app.post("/coach/athletes/register", response_class=HTMLResponse)
async def coach_register_athlete(request: Request) -> Response:
    form = dict(await request.form())
    message, athlete_id = await run_in_threadpool(
        _register, {str(key): str(value) for key, value in form.items()}
    )
    if athlete_id is None:
        return _redirect("/coach/athletes/new", message)
    return _redirect(f"/coach/athlete/{quote(athlete_id)}?welcome=1#telegram", message)


@app.get("/coach/setup", response_class=HTMLResponse)
async def coach_setup(request: Request) -> Response:
    message = _take_flash(request)

    def render() -> str:
        conn = db.connect()
        try:
            db.init_db(conn)
            steps = agent_status.setup_checklist(
                conn, clock.utcnow(), telegram_available=settings.telegram_configured,
                agent_blocker=deployment.agent_blocker(),
            )
            pending_count = _pending_count(conn)
        finally:
            conn.close()
        return onboarding_view.setup_page(
            steps, coach=settings.coach_name, today=date.today(), pending_count=pending_count,
            bot_username=settings.telegram_bot_username, telegram_available=settings.telegram_configured,
            message=message,
        )

    return _page(request, await run_in_threadpool(render))


def _athlete_status(conn, athlete_id: str):
    return agent_status.athlete_status(
        conn, athlete_id, clock.utcnow(), telegram_available=settings.telegram_configured,
        agent_blocker=deployment.agent_blocker(),
    )


@app.get("/coach/athlete/{athlete_id}/status.json")
async def coach_athlete_status(athlete_id: str) -> Response:
    def read() -> dict | None:
        conn = db.connect()
        try:
            db.init_db(conn)
            if athlete_id not in db.list_athletes(conn):
                return None
            status = _athlete_status(conn, athlete_id)
        finally:
            conn.close()
        label, href = agent_status.next_setup_step(status)
        return {
            "telegram_connected": status.telegram_connected, "ready": status.ready,
            "plan": status.plan, "autopilot": status.autopilot if status.autopilot_decided else None,
            "next_action": status.next_action, "blockers": status.blockers,
            "next_step": {"label": label, "href": href},
        }

    data = await run_in_threadpool(read)
    if data is None:
        return Response(status_code=404, content="no such athlete")
    return Response(content=json.dumps(data), media_type="application/json")


@app.get("/coach/athlete/{athlete_id}/simulate", response_class=HTMLResponse)
async def coach_simulate_athlete(athlete_id: str, request: Request) -> Response:
    """A safe test: the athlete's next planned day, played in a throwaway database."""

    def render() -> str | None:
        conn = db.connect()
        try:
            db.init_db(conn)
            if athlete_id not in db.list_athletes(conn):
                return None
            status = _athlete_status(conn, athlete_id)
            trace = public_demo.simulate_athlete(
                conn, athlete_id, now=clock.utcnow(), coach_name=settings.coach_name
            )
            pending_count = _pending_count(conn)
        finally:
            conn.close()
        return onboarding_view.simulate_page(
            trace, status, coach=settings.coach_name, today=date.today(), pending_count=pending_count
        )

    return _page(request, await run_in_threadpool(render))


def _approved_outbound(conn) -> list:
    """Every coach-approved message still waiting for its send, soonest first."""
    legacy_checkins = db.approved_drafts(conn, MORNING) if _legacy_checkins_visible() else []
    rows = (
        legacy_checkins
        + db.approved_drafts_with_prefix(conn, COACH_NOTE)
        + db.approved_drafts_with_prefix(conn, FEEDBACK_REPLY)
    )
    return sorted(rows, key=lambda row: (str(row["local_date"]), str(row["athlete_id"])))


def _legacy_checkins_visible() -> bool:
    """Morning-check-in drafts belong to the legacy scheduler, dormant under the agent."""
    return not settings.enable_agent_loop


def _visible_drafts(conn) -> list:
    rows = db.pending_drafts(conn)
    if _legacy_checkins_visible():
        return rows
    return [row for row in rows if str(row["message_kind"]) != MORNING]


def _pending_count(conn) -> int:
    return len(_visible_drafts(conn))


def _reviewable(conn, today: date) -> tuple:
    items = pending_reviews(conn, today=today)
    if _legacy_checkins_visible():
        return items
    return tuple(item for item in items if item.message_kind != MORNING)


def _render_athlete(
    athlete_id: str, message: tuple[str, str] | None, welcome: bool = False
) -> str | None:
    conn = db.connect()
    try:
        db.init_db(conn)
        if athlete_id not in db.list_athletes(conn):
            return None
        today = date.today()
        detail = athlete_detail(conn, athlete_id, today=today)
        telegram_chat = db.telegram_chat_id(conn, athlete_id)
        telegram_pairing_version = db.telegram_pairing_version(conn, athlete_id)
        conversation = db.whatsapp_messages(conn, athlete_id, limit=40)
        pending = _visible_drafts(conn)
        scheduled = [
            row for row in _approved_outbound(conn) if str(row["athlete_id"]) == athlete_id
        ]
        agent_state = agent_board.athlete_agent_state(conn, athlete_id)
        status = _athlete_status(conn, athlete_id)
    finally:
        conn.close()
    pairing_url = telegram.pairing_url(athlete_id, telegram_pairing_version)
    telegram_ready = bool(getattr(app.state, "telegram_webhook_ready", False))
    next_step = agent_status.next_setup_step(status)
    local_weekday = clock.utcnow().astimezone(engine._zone(status.timezone)).weekday()
    return render_athlete(
        detail,
        agent_panel=agent_view.athlete_agent_panel(athlete_id, agent_state, default_weekday=local_weekday),
        status_html=onboarding_view.athlete_status_header(
            status, next_step=next_step, simulate_href=f"/coach/athlete/{quote(athlete_id)}/simulate"
        ),
        invite_html=onboarding_view.invite_section(
            status, pairing_url=pairing_url, telegram_ready=telegram_ready, welcome=welcome,
            next_step=next_step,
        ),
        advanced_html=onboarding_view.advanced_section(
            athlete_id, telegram_connected=telegram_chat is not None
        ),
        welcome=welcome,
        coach=settings.coach_name,
        suggested=suggest_message(detail, coach=settings.coach_name),
        message=message,
        telegram_pairing_url=telegram.pairing_url(
            athlete_id, telegram_pairing_version
        ),
        telegram_linked=telegram_chat is not None,
        telegram_ready=bool(getattr(app.state, "telegram_webhook_ready", False)),
        conversation=conversation,
        scheduled=scheduled,
        awaiting=sum(1 for row in pending if str(row["athlete_id"]) == athlete_id),
        pending_count=len(pending),
    )


@app.post("/coach/athlete/{athlete_id}/telegram/unlink", response_class=HTMLResponse)
async def coach_unlink_telegram(athlete_id: str) -> Response:
    conn = db.connect()
    try:
        db.init_db(conn)
        removed = db.unlink_telegram_chat(conn, athlete_id)
    finally:
        conn.close()
    message = (
        ("ok", "Telegram was disconnected. The next pairing link can bind a new chat.")
        if removed
        else ("err", "This athlete did not have a Telegram chat connected.")
    )
    return _redirect(_athlete_url(athlete_id), message)


def _queue_note(athlete_id: str, body: str) -> tuple[str, str]:
    body = body.strip()
    if not body:
        return ("err", "Nothing to send — the message was empty.")
    conn = db.connect()
    try:
        db.init_db(conn)
        today = date.today().isoformat()
        message_kind = new_coach_note_kind()
        db.create_draft(conn, athlete_id, message_kind, today, body)
        db.review_draft(
            conn, athlete_id, message_kind, today,
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
    """Validate the native calendar value, retaining old form compatibility."""
    calendar_value = form.get("goal_target_date", "").strip()
    if calendar_value:
        try:
            return date.fromisoformat(calendar_value).isoformat()
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


def _clock_field(raw: str, label: str) -> str | None:
    value = (raw or "").strip()
    if not value:
        return None
    match = re.fullmatch(r"([01]?\d|2[0-3]):([0-5]\d)", value)
    if match is None:
        raise ValueError(f"{label} must be a time like 07:30")
    return f"{int(match.group(1)):02d}:{match.group(2)}"


def _register(form: dict[str, str]) -> tuple[tuple[str, str], str | None]:
    """Add an athlete. The internal identifier is generated unless a WhatsApp number is given."""
    supplied = re.sub(r"[\s()-]", "", form.get("athlete_id", ""))
    athlete_id = supplied or db.new_athlete_id()
    name = form.get("name", "")
    injury_note = form.get("injury_note", "").strip()
    if injury_note.casefold() in {"no", "none", "nothing", "nil", "n/a", "na"}:
        injury_note = ""
    conn = db.connect()
    try:
        db.init_db(conn)
        timezone_name = form.get("timezone", "").strip() or None
        if timezone_name:
            try:
                ZoneInfo(timezone_name)
            except (ZoneInfoNotFoundError, ValueError):
                raise ValueError("choose a timezone from the list") from None
        checkin = _clock_field(form.get("checkin_time", ""), "check-in time")
        training = _clock_field(form.get("training_time", ""), "training time")
        if checkin and training and checkin >= training:
            raise ValueError("the check-in must be earlier in the day than training")
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
            injury_note=injury_note,
            goal_lift=form.get("goal_lift", "").strip() or None,
            goal_target_kg=_optional_number(form.get("goal_target_kg", "")),
            goal_target_date=_goal_date_from_form(form),
            created_by=settings.coach_name,
        )
        if timezone_name or checkin or training:
            db.insert_entry(conn, db.Entry(
                athlete_id=athlete_id, kind="status", timezone=timezone_name,
                morning_checkin_time=checkin, training_time=training,
                session_date=date.today().isoformat(),
            ))
    except ValueError as exc:
        return ("err", f"Not added: {exc}"), None
    finally:
        conn.close()
    return ("ok", f"{name.strip()} added. Send them the Telegram invite below."), athlete_id


@app.get("/coach/outbox", include_in_schema=False)
async def coach_outbox() -> Response:
    """The outbox is the Messaging Desk's approval tab; old links land there."""
    return RedirectResponse(url="/coach/whatsapp?tab=approval", status_code=303)


@app.get("/coach/whatsapp", response_class=HTMLResponse)
async def coach_whatsapp(request: Request, tab: str = "inbox", athlete: str = "") -> Response:
    """The daily message desk: feedback, approval, schedule and delivery."""
    valid_tab = tab if tab in {"inbox", "approval", "scheduled", "sent"} else "inbox"
    return _page(
        request,
        await run_in_threadpool(_render_whatsapp, valid_tab, athlete.strip(), _take_flash(request)),
    )


@app.get("/coach/analytics", response_class=HTMLResponse)
async def coach_analytics() -> Response:
    return HTMLResponse(await run_in_threadpool(_render_analytics))


def _render_analytics() -> str:
    conn = db.connect()
    try:
        db.init_db(conn)
        paces = squad_goal_paces(conn, today=date.today())
        pending_count = _pending_count(conn)
    finally:
        conn.close()
    return render_analytics(
        paces, coach=settings.coach_name, today=date.today(),
        pending_count=pending_count,
    )


@app.post("/coach/whatsapp/review", response_class=HTMLResponse)
@app.post("/coach/outbox/review", response_class=HTMLResponse, include_in_schema=False)
async def coach_whatsapp_review(request: Request) -> Response:
    form = dict(await request.form())
    result = await run_in_threadpool(
        _review_draft,
        str(form.get("athlete_id", "")).strip(),
        str(form.get("message_kind", "")).strip(),
        str(form.get("local_date", "")).strip(),
        str(form.get("decision", "")).strip(),
        str(form.get("body", "")),
    )
    return _redirect(_return_to(form, "/coach/whatsapp?tab=approval"), result)


@app.post("/coach/whatsapp/bulk-approve", response_class=HTMLResponse)
async def coach_whatsapp_bulk_approve(request: Request) -> Response:
    form = dict(await request.form())
    result = await run_in_threadpool(_bulk_approve_unchanged)
    return _redirect(_return_to(form, "/coach/whatsapp?tab=approval"), result)


@app.post("/coach/whatsapp/reviewed", response_class=HTMLResponse)
async def coach_whatsapp_mark_reviewed(request: Request) -> Response:
    form = dict(await request.form())
    athlete_id = str(form.get("athlete_id", "")).strip()
    result = await run_in_threadpool(_mark_feedback_reviewed, athlete_id)
    return _redirect(f"/coach/whatsapp?tab=inbox&athlete={quote(athlete_id)}", result)


@app.post("/coach/whatsapp/simulate", response_class=HTMLResponse)
async def coach_whatsapp_simulate(request: Request) -> Response:
    form = dict(await request.form())
    athlete_id = str(form.get("athlete_id", "")).strip()
    body = str(form.get("body", "")).strip()
    if not is_demo(athlete_id) or not body:
        result = ("err", "Simulations require a demo athlete and a message.")
    else:
        answered = await run_in_threadpool(
            _process, athlete_id, body, "SIM" + secrets.token_hex(12), "simulator"
        )
        result = (
            ("ok", "Simulated athlete message received; the agent replied on today's case.")
            if answered is None
            else ("ok", "Simulated athlete message received and processed.")
        )
    return _redirect(f"/coach/whatsapp?tab=inbox&athlete={quote(athlete_id)}", result)


def _bulk_approve_unchanged() -> tuple[str, str]:
    if not _legacy_checkins_visible():
        return ("err", "Check-ins are sent by the training-day agent; there are no morning drafts to approve.")
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
        pending = _reviewable(conn, date.today())
        conversations = db.whatsapp_conversations(conn)
        selected = athlete_id or (
            str(conversations[0]["athlete_id"]) if conversations else ""
        )
        messages = db.whatsapp_messages(conn, selected, limit=100) if selected else []
        names = {
            candidate: db.athlete_name(conn, candidate) or candidate
            for candidate in db.list_athletes(conn)
        }
        selected_name = names.get(selected) or selected
        demo_athletes = tuple(
            (candidate, name) for candidate, name in names.items() if is_demo(candidate)
        )
        scheduled = _approved_outbound(conn)
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
        transport_ready=(
            settings.whatsapp_configured
            or bool(getattr(app.state, "telegram_webhook_ready", False))
        ),
        transport_name=settings.messaging_transport_name,
        names=names,
        legacy_checkins=_legacy_checkins_visible(),
    )


def _review_draft(
    athlete_id: str, message_kind: str, local_date: str, decision: str, body: str
) -> tuple[str, str]:
    conn = db.connect()
    try:
        db.init_db(conn)
        name = db.athlete_name(conn, athlete_id) or athlete_id
        db.review_draft(
            conn, athlete_id, message_kind, local_date,
            status=decision, reviewed_by=settings.coach_name, body=body,
        )
    except ValueError as exc:
        return ("err", f"Not saved: {exc}")
    finally:
        conn.close()
    verb = "approved for" if decision == "approved" else "held back from"
    return ("ok", f"Message {verb} {name} on {local_date}.")


@app.get("/privacy", response_class=HTMLResponse)
async def privacy_policy() -> str:
    return render_privacy()


@app.get("/terms", response_class=HTMLResponse)
async def terms() -> str:
    return render_terms()


@app.get("/health")
async def health() -> dict[str, object]:
    storage = deployment.status()
    return {
        # Degraded, not down: the site and webhooks still work, the agent does not.
        "status": "degraded" if storage["agent_blocker"] else "ok",
        **storage,
        "model": settings.gemini_model if settings.gemini_api_key else "offline-stub",
        "database": (
            "postgres (DATABASE_URL)" if storage["storage_backend"] == "postgres"
            else str(settings.db_file)
        ),
        "messaging_channel": "telegram" if settings.telegram_configured else "not configured",
        # Historical WhatsApp experiments; reported only so a misconfiguration is visible.
        "legacy_whatsapp_adapter": (
            settings.whatsapp_transport_name if settings.whatsapp_configured else "inactive"
        ),
        "telegram_integration": settings.telegram_configured,
        "telegram_webhook_ready": bool(
            getattr(app.state, "telegram_webhook_ready", False)
        ),
        "telegram_webhook_error": getattr(
            app.state, "telegram_webhook_error", None
        ),
        "messaging_transport": settings.messaging_transport_name,
        "morning_scheduler": settings.enable_morning_scheduler and not settings.enable_agent_loop,
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


def _process(
    athlete_id: str,
    body: str,
    provider_sid: str = "",
    channel: str = "whatsapp",
) -> str | None:
    """Blocking work — one SQLite connection per request keeps threads honest.

    Returns the receipt to send, or None when the training-day agent has already
    answered the athlete itself.
    """
    conn = db.connect()
    try:
        db.init_db(conn)
        if provider_sid and db.whatsapp_message_by_sid(conn, provider_sid) is not None:
            previous = db.whatsapp_reply_to(conn, provider_sid)
            if previous is not None:
                return str(previous["body"])
            return None if channel in AGENT_CHANNELS else "Message received."
        db.record_whatsapp_message(
            conn, athlete_id=athlete_id, direction="inbound", body=body,
            status="received", provider_sid=provider_sid or None,
            message_kind="athlete_feedback",
            channel=channel,
        )
        now = clock.utcnow()
        agent_owned = deployment.agent_loop_active() and channel in AGENT_CHANNELS
        reply, actions = handle_message_with_actions(
            conn, athlete_id, body, get_model_client(),
            today=engine.local_today(conn, athlete_id, now) if agent_owned else None,
            allowed=LOOP_TOOL_NAMES if agent_owned else None,
        )
        if agent_owned and engine.observe_message(
            conn, athlete_id, actions, raw_text=body, now=now,
            transport=LiveTransport(), coach_name=settings.coach_name,
        ):
            return None
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
            channel=channel,
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


def _console_link_text(path: str = "/coach") -> str:
    if not (settings.coach_link_secret and settings.public_base_url):
        return "The console link secret is not configured on this deployment yet."
    return (
        "Your coach console (link valid for 15 minutes):\n" + access.console_link(path)
    )


def _coach_command(conn, chat_id: str, body: str) -> str | None:
    """Coach-only Telegram commands. None means the message is not one of them."""
    command, _, argument = body.partition(" ")
    command = command.split("@", 1)[0].lower()
    coach_chat = case_store.coach_chat_id(conn)
    if command == "/coach":
        if not argument.strip() or not access.setup_code_matches(argument):
            return "That setup code is not valid for this deployment."
        outcome = case_store.link_coach_chat(
            conn, chat_id, code_fingerprint=access.setup_code_fingerprint(), now=clock.utcnow()
        )
        if outcome == "taken":
            return "This setup code has already linked another Telegram account. Rotate the code to relink."
        return (
            ("Linked. Escalations from the training-day agent will arrive here with decision buttons.\n\n"
             if outcome == "linked" else "This chat is already the coach chat.\n\n")
            + _console_link_text()
        )
    if chat_id == coach_chat:
        if command == "/console":
            return _console_link_text()
        return (
            "This is the coach chat. Use the buttons on an escalation to decide, or send /console "
            "for a console link."
        )
    return None


def _telegram_coach_decision(callback: dict) -> Response:
    callback_id = str(callback.get("id", ""))
    message = callback.get("message") if isinstance(callback.get("message"), dict) else {}
    chat = message.get("chat") if isinstance(message.get("chat"), dict) else {}
    chat_id = str(chat.get("id", "")).strip()
    data = str(callback.get("data", ""))
    conn = db.connect()
    try:
        db.init_db(conn)
        coach_chat = case_store.coach_chat_id(conn)
    finally:
        conn.close()
    if not coach_chat or chat_id != coach_chat:
        telegram.answer_callback_query(callback_id, "Only the linked coach chat can decide.")
        return Response(status_code=200, content="not the coach chat")
    match = re.fullmatch(r"d:(\d{1,12}):([a-z_]{1,40})", data)
    if match is None:
        telegram.answer_callback_query(callback_id, "That button is no longer valid.")
        return Response(status_code=200, content="bad decision")
    ok, text = _decide_case(int(match.group(1)), match.group(2))
    telegram.answer_callback_query(callback_id, text)
    if ok:
        try:
            telegram.send_outbound(chat_id, f"Done: {text}")
        except RuntimeError:
            log.warning("could not confirm a coach decision in Telegram")
    return Response(status_code=200, content="decided" if ok else "refused")


@app.post("/webhook/telegram")
async def telegram_webhook(request: Request) -> Response:
    """Receive a private Telegram message through a signed Bot API webhook."""
    supplied_secret = request.headers.get("X-Telegram-Bot-Api-Secret-Token")
    if not telegram.valid_webhook_secret(supplied_secret):
        log.warning("rejected request with a bad Telegram webhook secret")
        return Response(status_code=403, content="invalid webhook secret")
    try:
        payload = await request.json()
    except ValueError:
        return Response(status_code=400, content="invalid JSON")
    callback = payload.get("callback_query")
    if isinstance(callback, dict):
        return await run_in_threadpool(_telegram_coach_decision, callback)
    message = payload.get("message")
    if not isinstance(message, dict):
        return Response(status_code=200, content="ignored")
    chat = message.get("chat")
    if not isinstance(chat, dict) or chat.get("type") != "private":
        return Response(status_code=200, content="private chats only")
    chat_id = str(chat.get("id", "")).strip()
    message_id = str(message.get("message_id", "")).strip()
    body = str(message.get("text", "")).strip()
    if not chat_id or not message_id or not body:
        return Response(status_code=200, content="unsupported message")
    inbound_sid = telegram.provider_sid(chat_id, message_id)

    conn = db.connect()
    try:
        db.init_db(conn)
        coach_reply = _coach_command(conn, chat_id, body)
        if coach_reply is not None:
            try:
                await run_in_threadpool(telegram.send_outbound, chat_id, coach_reply)
            except Exception:  # noqa: BLE001
                log.exception("failed to answer a coach command")
                return Response(status_code=502, content="send failed")
            return Response(status_code=200, content="coach command")
        if body.startswith("/start"):
            pieces = body.split(maxsplit=1)
            pairing = telegram.athlete_from_pairing_token(pieces[1]) if len(pieces) == 2 else None
            athlete_id = pairing[0] if pairing is not None else None
            if len(pieces) == 1:
                reply = (
                    "Power AI is ready, but a plain /start cannot identify your athlete "
                    "profile. Ask your coach to open your athlete page and press Connect "
                    "Telegram, then use that secure link."
                )
            elif pairing is None:
                reply = "This pairing link is invalid or expired. Ask your coach for a fresh link."
            else:
                try:
                    db.link_telegram_chat(
                        conn, chat_id=chat_id, athlete_id=athlete_id,
                        pairing_version=pairing[1],
                    )
                    name = db.athlete_name(conn, athlete_id) or "your athlete profile"
                    reply = (
                        f"Connected to Power AI as {name}. Send your training, sleep, "
                        "readiness or nutrition update whenever you're ready."
                    )
                    db.record_whatsapp_message(
                        conn, athlete_id=athlete_id, direction="inbound",
                        body="Telegram pairing accepted", status="received",
                        provider_sid=inbound_sid, message_kind="channel_pairing",
                        channel="telegram",
                    )
                except ValueError as exc:
                    reply = f"Telegram could not be connected: {exc}."
            try:
                outbound_sid = await run_in_threadpool(
                    telegram.send_outbound, chat_id, reply
                )
                if athlete_id is not None and db.telegram_athlete_id(conn, chat_id):
                    db.record_whatsapp_message(
                        conn, athlete_id=athlete_id, direction="outbound", body=reply,
                        status="sent", provider_sid=outbound_sid,
                        message_kind="channel_pairing", reply_to_sid=inbound_sid,
                        channel="telegram",
                    )
            except Exception:  # noqa: BLE001
                log.exception("failed to answer Telegram pairing request")
                return Response(status_code=502, content="send failed")
            return Response(status_code=200, content="ok")

        athlete_id = db.telegram_athlete_id(conn, chat_id)
    finally:
        conn.close()

    if athlete_id is None:
        await run_in_threadpool(
            telegram.send_outbound,
            chat_id,
            "This chat is not paired. Ask your coach to open your athlete page and "
            "send you the secure Telegram pairing link.",
        )
        return Response(status_code=200, content="not paired")

    reply = await run_in_threadpool(
        _process, athlete_id, body, inbound_sid, "telegram"
    )
    if reply is None:
        return Response(status_code=200, content="handled by the training-day agent")
    try:
        outbound_sid = await run_in_threadpool(telegram.send_outbound, chat_id, reply)
        conn = db.connect()
        try:
            db.init_db(conn)
            db.attach_whatsapp_reply_sid(conn, inbound_sid, outbound_sid)
        finally:
            conn.close()
    except Exception:  # noqa: BLE001 - Telegram retries non-2xx webhook responses
        log.exception("failed to send Telegram acknowledgement")
        return Response(status_code=502, content="send failed")
    return Response(status_code=200, content="ok")

"""Deployment blockers: one check-in owner, durable memory, idempotent ticks, a working demo."""

from __future__ import annotations

import asyncio
import re
import time
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from app import access, deployment
from app.casework import clock, demo_day, store
from app.coach.demo import DEMO_PREFIX
from app.scheduling.outbox import FEEDBACK_REPLY, MORNING
from app.storage import db

ROOT = Path(__file__).resolve().parents[1]


@pytest.fixture()
def env(tmp_path, monkeypatch):
    from app import main
    from app.config import settings

    for name, value in {
        "database_path": str(tmp_path / "hardening.db"),
        "database_url": "",
        "public_base_url": "",
        "coach_link_secret": "",
        "agent_tick_secret": "tick-secret",
        "telegram_bot_token": "",
        "gemini_api_key": "",
        "enable_agent_loop": True,
        "enable_morning_scheduler": False,
        "coach_name": "Coach Rao",
    }.items():
        monkeypatch.setattr(settings, name, value)
    main.get_model_client.cache_clear()
    moment = {"now": datetime(2026, 9, 14, 7, 31, tzinfo=timezone.utc)}
    monkeypatch.setattr(clock, "utcnow", lambda: moment["now"])
    return main, settings, moment


def signed_tick(client):
    stamp = str(int(time.time()))
    return client.post("/internal/agent/tick", headers={
        "X-Agent-Timestamp": stamp, "X-Agent-Signature": access.tick_signature(stamp)})


def planned_demo_athletes(settings, suffixes=("101", "102")) -> list[str]:
    conn = db.connect(settings.database_path)
    db.init_db(conn)
    start = datetime(2026, 9, 1, tzinfo=timezone.utc)
    ids = []
    for suffix in suffixes:
        athlete = f"{DEMO_PREFIX}{suffix}"
        db.register_athlete(conn, athlete, f"Test Athlete {suffix}", on="2026-09-01")
        for weekday in range(7):
            store.add_plan_session(conn, athlete_id=athlete, weekday=weekday, lift="squat", sets=4,
                                   reps=5, rpe=7, approved_by="Coach Rao", now=start)
        store.set_autopilot(conn, athlete, True, updated_by="Coach Rao", now=start)
        ids.append(athlete)
    conn.close()
    return ids


def scalar(settings, sql, *params):
    conn = db.connect(settings.database_path)
    try:
        return conn.execute(sql, params).fetchone()[0]
    finally:
        conn.close()


# --- 1. Exactly one owner of proactive check-ins -----------------------------------


def _started_loops(main, settings, monkeypatch, *, agent: bool, legacy: bool) -> list[str]:
    started: list[str] = []

    def fake(name):
        def loop():
            started.append(name)
            return asyncio.sleep(3600)
        return loop

    monkeypatch.setattr(main, "_agent_loop", fake("agent"))
    monkeypatch.setattr(main, "_morning_scheduler_loop", fake("legacy"))
    monkeypatch.setattr(settings, "agent_background_ticks", True)
    monkeypatch.setattr(settings, "enable_agent_loop", agent)
    monkeypatch.setattr(settings, "enable_morning_scheduler", legacy)
    with TestClient(main.app) as client:
        client.get("/health")
    return started


def test_the_legacy_morning_scheduler_never_runs_beside_the_agent(env, monkeypatch):
    main, settings, _ = env
    assert _started_loops(main, settings, monkeypatch, agent=True, legacy=True) == ["agent"]
    assert _started_loops(main, settings, monkeypatch, agent=False, legacy=True) == ["legacy"]


def test_a_signed_tick_never_touches_the_morning_workflow(env, monkeypatch):
    main, settings, _ = env

    def forbidden(*_args, **_kwargs):
        raise AssertionError("the legacy morning workflow was called")

    for name in ("_send_morning_prompts", "draft_upcoming_prompts", "send_approved_prompts"):
        monkeypatch.setattr(main, name, forbidden)
    coach_sends: list[str] = []
    monkeypatch.setattr(main, "send_approved_outbound", lambda conn, sender: coach_sends.append("outbound") or 0)
    planned_demo_athletes(settings)
    with TestClient(main.app) as client:
        response = signed_tick(client)
    assert response.status_code == 200 and response.json()["actions"] == 2
    assert coach_sends == ["outbound"], "coach-written and coach-approved messages still go out, in one ordered pass"


def test_the_console_shows_no_morning_draft_queue_under_the_agent(env, monkeypatch):
    main, settings, _ = env
    athlete = "+919812340001"
    tomorrow = (date.today() + timedelta(days=1)).isoformat()
    conn = db.connect(settings.database_path)
    db.init_db(conn)
    db.register_athlete(conn, athlete, "Priya Kulkarni", on="2026-09-01")
    db.create_draft(conn, athlete, MORNING, tomorrow, "LEGACY MORNING DRAFT")
    db.create_draft(conn, athlete, FEEDBACK_REPLY + "X1", date.today().isoformat(), "Coach reply draft")
    conn.close()

    with TestClient(main.app) as client:
        today = client.get("/coach").text
        assert "Coach reply draft" in today, "replies to athletes still need the coach"
        assert "LEGACY MORNING DRAFT" not in today
        assert "Approve unchanged check-ins" not in today
        desk = client.get("/coach/whatsapp?tab=approval").text
        assert "LEGACY MORNING DRAFT" not in desk
        refused = client.post("/coach/whatsapp/bulk-approve", data={"return_to": "/coach"})
        assert "Check-ins are sent by the training-day agent" in refused.text
    conn = db.connect(settings.database_path)
    try:
        legacy = db.draft(conn, athlete, MORNING, tomorrow)
        assert (legacy["status"], legacy["resolution"]) == ("skipped", "superseded"), "retired, never deleted"
        assert legacy["reason"] == db.LEGACY_CHECKIN_REASON
    finally:
        conn.close()

    monkeypatch.setattr(settings, "enable_agent_loop", False)
    with TestClient(main.app) as client:
        assert "LEGACY MORNING DRAFT" not in client.get("/coach").text, "a retired check-in is never revived"


def test_the_render_blueprint_has_one_check_in_owner_and_durable_storage():
    blueprint = (ROOT / "render.yaml").read_text(encoding="utf-8")
    active = "\n".join(line for line in blueprint.splitlines() if not line.lstrip().startswith("#"))
    assert re.search(r"key: ENABLE_MORNING_SCHEDULER\s+value: \"false\"", active)
    assert re.search(r"key: ENABLE_AGENT_LOOP\s+value: \"true\"", active)
    assert re.search(r"key: DATABASE_URL\s+sync: false", active)
    assert "/tmp" not in active and "DATABASE_PATH" not in active


# --- 2. A public agent deployment cannot run on ephemeral memory ---------------------


def test_a_public_agent_deployment_refuses_temporary_memory(env, monkeypatch):
    main, settings, _ = env
    monkeypatch.setattr(settings, "public_base_url", "https://agent.example.com")
    started: list[str] = []
    monkeypatch.setattr(main, "_agent_loop", lambda: started.append("agent") or asyncio.sleep(3600))
    planned_demo_athletes(settings)

    with TestClient(main.app) as client:
        health = client.get("/health").json()
        assert health["status"] == "degraded"
        assert health["storage_backend"] == "sqlite"
        assert health["agent_memory_durable"] is False
        assert health["agent_loop"] == "blocked"
        assert "DATABASE_URL" in health["agent_blocker"]

        tick = signed_tick(client)
        assert tick.status_code == 503 and "DATABASE_URL" in tick.text
        run = client.post("/coach/agent/run", data={"return_to": "/coach"})
        assert "Agent blocked." in run.text and "DATABASE_URL" in run.text
        simulated = client.post("/coach/whatsapp/simulate", data={
            "athlete_id": f"{DEMO_PREFIX}101", "body": "slept 8h readiness 8"})
        assert simulated.status_code == 200

    assert scalar(settings, "SELECT COUNT(*) FROM agent_cases") == 0
    assert scalar(settings, "SELECT COUNT(*) FROM agent_events") == 0


def test_storage_status_distinguishes_local_public_and_durable(env, monkeypatch):
    _, settings, _ = env
    assert deployment.status()["agent_loop"] == "active", "local development may use SQLite"
    assert deployment.status()["agent_memory_durable"] is False

    monkeypatch.setattr(settings, "public_base_url", "https://agent.example.com")
    assert deployment.agent_blocker() is not None

    monkeypatch.setattr(settings, "database_url", "postgresql://user:secret@db.example/app")
    status = deployment.status()
    assert status["storage_backend"] == "postgres" and status["agent_memory_durable"] is True
    assert status["agent_loop"] == "active" and status["agent_blocker"] is None

    monkeypatch.setattr(settings, "enable_agent_loop", False)
    assert deployment.status()["agent_loop"] == "disabled"


# --- 3. Repeated signed ticks cannot duplicate actions --------------------------------


def test_repeated_signed_ticks_cannot_duplicate_actions(env):
    main, settings, moment = env
    athletes = planned_demo_athletes(settings)
    with TestClient(main.app) as client:
        reports = [signed_tick(client).json() for _ in range(4)]
        moment["now"] = moment["now"] + timedelta(minutes=14)
        reports += [signed_tick(client).json() for _ in range(3)]

    assert reports[0]["opened"] == 2 and reports[0]["actions"] == 2
    assert sum(report["opened"] for report in reports) == 2
    assert sum(report["actions"] for report in reports) == 2
    assert scalar(settings, "SELECT COUNT(*) FROM agent_cases") == len(athletes)
    assert scalar(settings, "SELECT COUNT(*) FROM whatsapp_messages "
                            "WHERE direction = 'outbound' AND message_kind = 'agent:checkin_sent'") == 2
    keys = scalar(settings, "SELECT COUNT(idempotency_key) FROM agent_events")
    assert keys == scalar(settings, "SELECT COUNT(DISTINCT idempotency_key) FROM agent_events") == 2


# --- 4. The deterministic demo works after the real training time has passed -----------


def test_the_simulated_demo_day_works_after_real_training_time(env):
    main, settings, moment = env
    moment["now"] = datetime(2026, 9, 14, 23, 40, tzinfo=timezone.utc)  # long after 18:00 training

    def simulated():
        conn = db.connect(settings.database_path)
        try:
            return {str(row["athlete_id"])[-3:]: dict(row) for row in store.simulated_cases(conn)}
        finally:
            conn.close()

    with TestClient(main.app) as client:
        client.post("/coach/demo/seed")
        real = client.post("/coach/agent/run", data={"return_to": "/coach"})
        assert "Agent ran: 0 day(s) opened, 0 message(s) sent" in real.text, "real time rules still apply"

        assert "Play the simulated morning first." in client.post("/coach/demo/day/evening").text
        morning = client.post("/coach/demo/day/morning")
        assert "Simulated morning of Monday 5 January 2026 played" in morning.text
        cases = simulated()
        assert {case["local_date"] for case in cases.values()} == {demo_day.DEMO_DATE.isoformat()}
        assert cases["006"]["state"] == "awaiting_outcome", "routine day: the session went out alone"
        assert cases["007"]["state"] == "awaiting_outcome"
        assert cases["008"]["state"] == "awaiting_outcome" and cases["008"]["follow_ups"] == 2
        assert (cases["002"]["state"], "autopilot_off") == ("needs_coach", "autopilot_off")
        assert '"injury_open"' in cases["001"]["escalation_json"]
        assert (cases["003"]["state"], cases["003"]["outcome"]) == ("closed", "no_response")

        today = client.get("/coach").text
        assert "Simulated demo day" in today and "Monday 5 January 2026" in today
        assert "Run agent now (real time)" in today

        decided = client.post(f"/coach/case/{cases['002']['id']}/decide",
                              data={"option": "send", "return_to": "/coach#demo-day"})
        assert "Session sent to Rohit" in decided.text
        client.post("/coach/demo/day/evening")
        cases = simulated()
        assert (cases["006"]["state"], cases["006"]["outcome"]) == ("closed", "completed")
        assert (cases["007"]["state"], cases["007"]["outcome"]) == ("closed", "done")
        assert (cases["008"]["state"], cases["008"]["outcome"]) == ("closed", "skipped")
        assert cases["002"]["state"] == "awaiting_outcome" and cases["002"]["outcome_prompts"] == 1
        assert cases["001"]["state"] == "needs_coach", "the injury still waits for the coach"

        messages = scalar(settings, "SELECT COUNT(*) FROM whatsapp_messages")
        events = scalar(settings, "SELECT COUNT(*) FROM agent_events")
        client.post("/coach/demo/day/morning")
        client.post("/coach/demo/day/evening")
        client.post("/coach/agent/run", data={"return_to": "/coach"})
        assert scalar(settings, "SELECT COUNT(*) FROM whatsapp_messages") == messages, "replaying repeats nothing"
        assert scalar(settings, "SELECT COUNT(*) FROM agent_events") == events, "real ticks never touch the simulation"
        assert scalar(settings, "SELECT COUNT(*) FROM agent_cases WHERE simulated = 0") == 0
        assert scalar(settings, "SELECT COUNT(*) FROM whatsapp_messages WHERE channel = 'telegram'") == 0

        client.post("/coach/demo/day/reset")
        assert simulated() == {}

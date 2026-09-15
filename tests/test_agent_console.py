"""The coach console reframed around the agent: done, waiting, exceptions, timeline, learned."""

from __future__ import annotations

from datetime import datetime, timezone

import pytest
from fastapi.testclient import TestClient

from app.casework import clock, engine, store
from app.storage import db

ATHLETE = "+919812340001"


class Quiet:
    def send_athlete(self, conn, athlete_id, body, *, kind):
        return "fake"

    def notify_coach(self, conn, **_):
        return None


@pytest.fixture()
def console(tmp_path, monkeypatch):
    from app import main
    from app.config import settings

    monkeypatch.setattr(settings, "database_path", str(tmp_path / "console.db"))
    monkeypatch.setattr(settings, "coach_name", "Coach Rao")
    monkeypatch.setattr(main, "LiveTransport", Quiet)
    now = datetime(2026, 9, 14, 2, 1, tzinfo=timezone.utc)  # 07:31 in Kolkata
    monkeypatch.setattr(clock, "utcnow", lambda: now)
    conn = db.connect(settings.database_path)
    db.init_db(conn)
    db.register_athlete(conn, ATHLETE, "Priya Kulkarni", on="2026-09-01")
    db.insert_entry(conn, db.Entry(athlete_id=ATHLETE, kind="status", timezone="Asia/Kolkata",
                                   morning_checkin_time="07:30", session_date="2026-09-01"))
    conn.close()
    return main, settings


def test_the_coach_approves_a_plan_and_turns_on_autopilot_from_the_athlete_page(console):
    main, settings = console
    with TestClient(main.app) as client:
        page = client.get(f"/coach/athlete/{ATHLETE}")
        assert "Weekly plan" in page.text and "Add to weekly plan" in page.text
        assert "No approved plan yet" in page.text

        refused = client.post(f"/coach/athlete/{ATHLETE}/plan", data={
            "weekday": "0", "lift": "squat", "sets": "4", "reps": "5", "rpe": "11"})
        assert "Plan not changed" in refused.text, "an RPE outside 5–10 is refused"

        client.post(f"/coach/athlete/{ATHLETE}/plan", data={
            "weekday": "0", "lift": "squat", "sets": "4", "reps": "5", "rpe": "7"})
        client.post(f"/coach/athlete/{ATHLETE}/autopilot", data={"enabled": "on"})
        page = client.get(f"/coach/athlete/{ATHLETE}")
        assert "Squat" in page.text and "4×5" in page.text and "RPE 7" in page.text
        assert "Autopilot on." in page.text

    conn = db.connect(settings.database_path)
    try:
        assert [row["rpe"] for row in store.active_plan(conn, ATHLETE)] == [7.0]
        assert store.agent_settings(conn, ATHLETE)["autopilot"] is True
    finally:
        conn.close()


def test_today_shows_open_cases_exceptions_timeline_and_the_case_page(console):
    main, settings = console
    conn = db.connect(settings.database_path)
    try:
        store.add_plan_session(conn, athlete_id=ATHLETE, weekday=0, lift="squat", sets=4, reps=5,
                               rpe=7, approved_by="Coach Rao", now=clock.utcnow())
    finally:
        conn.close()

    with TestClient(main.app) as client:
        client.post("/coach/agent/run", data={"return_to": "/coach"})
        today = client.get("/coach").text
        assert "What happens next" in today
        assert "Waiting for athlete check-in" in today
        assert "Sent the morning check-in." in today
        assert "Handled by the agent" in today

        conn = db.connect(settings.database_path)
        try:
            actions = [engine.LogCheckIn(checked_on="2026-09-14", sleep_hours=8, readiness=8)]
            engine.observe_message(conn, ATHLETE, actions, raw_text="slept 8h readiness 8",
                                   now=clock.utcnow(), transport=Quiet(), coach_name="Coach Rao")
            case = store.case_for_day(conn, ATHLETE, "2026-09-14")
        finally:
            conn.close()
        assert case["state"] == "needs_coach", "autopilot is off by default"

        today = client.get("/coach").text
        assert "Needs you" in today and 'data-kind="case"' in today
        assert "Session waiting for approval" in today
        assert "Send the adjusted session" in today

        page = client.get(f"/coach/case/{case['id']}").text
        assert "Reasoning and actions" in page
        assert "Readiness" in page and "Autopilot is off" in page

        decided = client.post(f"/coach/case/{case['id']}/decide",
                              data={"option": "send", "return_to": f"/coach/case/{case['id']}"})
        assert decided.status_code == 200
        page = client.get(f"/coach/case/{case['id']}").text
        assert "Waiting for session report" in page
        assert "Delivered the session Coach Rao approved." in page
        assert client.get("/coach/case/99999").status_code == 404

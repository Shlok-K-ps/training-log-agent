"""The public "Watch the agent work" demonstration: complete, honest and isolated."""

from __future__ import annotations

import json

import pytest
from fastapi.testclient import TestClient

from app import public_demo
from app.storage import db


@pytest.fixture()
def fresh_trace():
    public_demo.public_demo.cache_clear()
    yield
    public_demo.public_demo.cache_clear()


def test_the_demo_day_runs_the_whole_loop_through_the_real_agent(fresh_trace):
    trace = public_demo.public_demo()
    kinds = {step["kind"] for step in trace["steps"]}
    assert {"clock", "athlete", "interpret", "rule", "action", "wait", "escalation", "coach", "outcome"} <= kinds

    titles = [(step.get("athlete"), step["title"]) for step in trace["steps"]]
    assert ("priya", "Sent the morning check-in") in titles
    assert ("priya", "Delivered today's session") in titles
    assert ("arjun", "Followed up on a missing reply") in titles
    assert ("arjun", "Injury rule: stopped all training guidance") in titles
    assert any(kind == "arjun" and title.startswith("Coach Maya chose") for kind, title in titles)
    assert ("arjun", "Sent the coach's injury plan") in titles

    arjun = [step for step in trace["steps"] if step.get("athlete") == "arjun"]
    stop = next(i for i, step in enumerate(arjun) if step["title"].startswith("Injury rule"))
    assert not any(step["title"] == "Delivered today's session" for step in arjun[stop:]), \
        "an injury report stops autonomous load guidance"

    interpretation = next(step for step in trace["steps"] if step["kind"] == "interpret")
    assert interpretation["body"].startswith("log_checkin(")

    report = trace["report"]
    assert report["days_owned"] == report["days_closed"] == 2
    assert (report["checkins"], report["follow_ups"], report["escalations"], report["coach_decisions"]) == (2, 1, 1, 1)
    assert report["sessions_autonomous"] == 1
    assert report["coach_typed_messages"] == 0
    assert report["autonomous_messages"] == report["agent_messages"] - 1
    assert [item["outcome"] for item in report["outcomes"]] == ["Trained and logged", "Trained"]


def test_building_the_demo_never_touches_production_or_telegram(fresh_trace, monkeypatch):
    from app.channels import telegram

    real_connect = db.connect

    def guarded(path=None):
        assert path == ":memory:", "the public demo must never open the configured database"
        return real_connect(path)

    monkeypatch.setattr(db, "connect", guarded)
    monkeypatch.setattr(telegram, "send_outbound", lambda *_a, **_k: pytest.fail("the demo sent a message"))
    trace = public_demo.public_demo()
    assert trace["report"]["days_closed"] == 2


@pytest.mark.console_locked
def test_the_demo_is_public_while_the_console_stays_locked(tmp_path, monkeypatch, fresh_trace):
    from app import main
    from app.config import settings

    monkeypatch.setattr(settings, "database_path", str(tmp_path / "production.db"))
    monkeypatch.setattr(settings, "public_base_url", "https://agent.example.com")
    monkeypatch.setattr(settings, "coach_link_secret", "link-secret")
    with TestClient(main.app) as client:
        landing = client.get("/").text
        assert 'href="/demo" data-primary-cta' in landing
        assert "Watch the agent work" in landing
        assert client.get("/coach").status_code == 401

        page = client.get("/demo")
        assert page.status_code == 200
        assert "Fictional simulation · nothing is sent · no login" in page.text
        for label in ("Interpretation", "Fixed rule", "Agent action", "Needs the coach", "Coach decision", "Outcome"):
            assert label in page.text
        assert "Day complete: here is the work the agent did" in page.text
        assert "Replay the day" in page.text and "Simulation or real agent?" in page.text
        embedded = page.text.split('<script type="application/json" id="demo-trace">', 1)[1].split("</script>", 1)[0]
        assert len(json.loads(embedded)["steps"]) > 30

    conn = db.connect(settings.database_path)
    try:
        assert db.list_athletes(conn) == []
        assert conn.execute("SELECT COUNT(*) FROM agent_cases").fetchone()[0] == 0
        assert conn.execute("SELECT COUNT(*) FROM whatsapp_messages").fetchone()[0] == 0
    finally:
        conn.close()


def test_the_landing_page_explains_the_agent():
    from app.coach.view import render_landing

    html = render_landing()
    for text in (
        "The problem", 'aria-label="The closed agent loop"', "DOES ALONE", "ALWAYS ASKS THE COACH",
        "Public simulation", "Real Telegram agent", "See it in one minute",
    ):
        assert text in html

"""The coach console: the roster view, its ordering, and its one write."""

from __future__ import annotations

from datetime import date

import pytest

from app.coach import Bucket, build_roster, render, review_athlete
from app.coach import auth as coach_auth
from app.config import settings
from app.storage import db

TODAY = date(2026, 9, 10)


def _log(conn, athlete_id, name, weights, *, lift="squat", start="2026-08-01", rpes=None):
    for i, weight in enumerate(weights):
        day = date.fromisoformat(start).toordinal() + i * 3
        db.insert_entry(
            conn,
            db.Entry(
                athlete_id=athlete_id, athlete_name=name, kind="set", lift=lift,
                sets=3, reps=5, weight_kg=weight,
                rpe=None if rpes is None else rpes[i],
                session_date=date.fromordinal(day).isoformat(),
            ),
        )


# --- bucketing ----------------------------------------------------------------


def test_an_athlete_who_asked_to_be_cleared_is_blocked_on_the_coach(conn):
    _log(conn, "+911", "Priya", [140], start="2026-09-08")
    db.insert_entry(conn, db.Entry(athlete_id="+911", kind="status", injured=True,
                                   injury_note="left knee", session_date="2026-08-18"))
    db.request_injury_clearance(conn, "+911", note="feels fine", on="2026-09-08")

    entry = review_athlete(conn, "+911", today=TODAY)
    assert entry.bucket is Bucket.NEEDS_YOU
    assert entry.needs_action is True
    assert any("asked to be cleared" in f.detail for f in entry.flags)


def test_an_injury_with_no_request_is_watch_not_needs_you(conn):
    _log(conn, "+911", "Priya", [140], start="2026-09-08")
    db.insert_entry(conn, db.Entry(athlete_id="+911", kind="status", injured=True,
                                   injury_note="knee", session_date="2026-09-08"))
    entry = review_athlete(conn, "+911", today=TODAY)
    assert entry.bucket is Bucket.WATCH
    assert entry.needs_action is False


def test_silence_is_surfaced_because_nobody_reports_it(conn):
    """The signal an athlete will never send you."""
    _log(conn, "+912", "Neha", [100, 102.5], start="2026-08-25")
    entry = review_athlete(conn, "+912", today=TODAY)
    assert entry.days_silent == 13
    assert any(f.kind == "silent" for f in entry.flags)
    assert entry.bucket is Bucket.WATCH


def test_a_stall_reaches_the_coach_without_the_athlete_asking(conn):
    _log(conn, "+913", "Rohit", [140, 140, 140, 140], start="2026-09-01")
    entry = review_athlete(conn, "+913", today=date(2026, 9, 11))
    assert any(f.kind == "stalled" for f in entry.flags)


def test_an_athlete_with_nothing_wrong_collapses_to_fine(conn):
    _log(conn, "+914", "Sam", [140, 145, 150], start="2026-09-05")
    entry = review_athlete(conn, "+914", today=date(2026, 9, 12))
    assert entry.bucket is Bucket.FINE
    assert entry.flags == ()


def test_the_silence_threshold_is_configurable(conn, monkeypatch):
    _log(conn, "+915", "Ana", [140], start="2026-09-08")
    monkeypatch.setattr(settings, "coach_silent_after_days", 1)
    assert any(f.kind == "silent" for f in review_athlete(conn, "+915", today=TODAY).flags)


# --- ordering is the product ---------------------------------------------------


def test_the_roster_puts_coach_decisions_first_and_fine_last(conn):
    _log(conn, "+920", "Fine Fiona", [140, 145, 150], start="2026-09-05")
    _log(conn, "+921", "Stalled Sam", [140, 140, 140, 140], start="2026-09-01")
    _log(conn, "+922", "Blocked Bea", [140], start="2026-09-09")
    db.insert_entry(conn, db.Entry(athlete_id="+922", kind="status", injured=True,
                                   injury_note="back", session_date="2026-08-20"))
    db.request_injury_clearance(conn, "+922", note="better", on="2026-09-09")

    roster = build_roster(conn, today=date(2026, 9, 12))
    assert [e.display_name for e in roster.entries][0] == "Blocked Bea"
    assert roster.entries[-1].bucket is Bucket.FINE
    assert roster.total == 3
    assert roster.needing_attention == 2


# --- the console decides nothing -----------------------------------------------


def test_the_console_never_invents_a_verdict_the_athlete_would_not_get(conn):
    """Every flag traces to the same rules that answer the athlete."""
    from app.decision.rules import Verdict, evaluate

    _log(conn, "+930", "Rohit", [140, 140, 140, 140], start="2026-09-01")
    history = db.session_history(conn, "+930", "squat")
    assert evaluate("+930", "squat", history).verdict is Verdict.STALLED
    entry = review_athlete(conn, "+930", today=date(2026, 9, 11))
    assert any(f.kind == "stalled" for f in entry.flags)


# --- auth ----------------------------------------------------------------------


def test_an_unset_token_closes_the_console_rather_than_opening_it(monkeypatch):
    monkeypatch.setattr(settings, "coach_access_token", "")
    with pytest.raises(coach_auth.CoachAuthError, match="not set"):
        coach_auth.check("anything")


def test_a_wrong_token_is_refused(monkeypatch):
    monkeypatch.setattr(settings, "coach_access_token", "s3cret-token-value")
    with pytest.raises(coach_auth.CoachAuthError, match="Invalid"):
        coach_auth.check("wrong")
    with pytest.raises(coach_auth.CoachAuthError):
        coach_auth.check(None)
    coach_auth.check("s3cret-token-value")


# --- rendering -----------------------------------------------------------------


def test_the_page_renders_and_escapes_athlete_supplied_text(conn):
    _log(conn, "+940", "<script>alert(1)</script>", [140], start="2026-09-09")
    html = render(build_roster(conn, today=TODAY), token="t", coach="Coach Rao")
    assert "<script>alert(1)</script>" not in html
    assert "&lt;script&gt;" in html
    assert "Coach Rao" in html


def test_the_clear_form_appears_only_for_athletes_awaiting_a_decision(conn):
    _log(conn, "+950", "Waiting Wanda", [140], start="2026-09-09")
    db.insert_entry(conn, db.Entry(athlete_id="+950", kind="status", injured=True,
                                   injury_note="knee", session_date="2026-08-20"))
    _log(conn, "+951", "Fine Fred", [140, 145, 150], start="2026-09-05")

    html = render(build_roster(conn, today=date(2026, 9, 12)), token="t", coach="Coach")
    assert html.count("/coach/clear-injury") == 0, "no clearance requested yet"

    db.request_injury_clearance(conn, "+950", note="better", on="2026-09-11")
    html = render(build_roster(conn, today=date(2026, 9, 12)), token="t", coach="Coach")
    assert html.count("/coach/clear-injury") == 1

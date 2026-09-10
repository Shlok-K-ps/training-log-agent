"""The demo squad: an empty console can show what a full one looks like."""

from __future__ import annotations

from datetime import date

from app.coach import Bucket, build_roster
from app.coach.demo import DEMO_PREFIX, clear_demo_squad, is_demo, seed_demo_squad
from app.storage import db

TODAY = date(2026, 9, 10)


def test_the_demo_squad_exercises_every_bucket(conn):
    """A demo that only shows healthy athletes teaches the coach nothing."""
    assert seed_demo_squad(conn, today=TODAY) == 9
    roster = build_roster(conn, today=TODAY)

    buckets = {e.bucket for e in roster.entries}
    assert buckets == {Bucket.NEEDS_YOU, Bucket.WATCH, Bucket.MEET_PREP, Bucket.FINE}

    kinds = {f.kind for e in roster.entries for f in e.flags}
    assert {"clearance_requested", "stalled", "regressed", "silent", "injured", "meet"} <= kinds


def test_seeding_twice_changes_nothing(conn):
    assert seed_demo_squad(conn, today=TODAY) == 9
    assert seed_demo_squad(conn, today=TODAY) == 0
    assert len(db.list_athletes(conn)) == 9


def test_demo_ids_are_unroutable_so_nobody_gets_texted(conn):
    """Every demo id is in a reserved range that cannot be dialled."""
    seed_demo_squad(conn, today=TODAY)
    for athlete_id in db.list_athletes(conn):
        assert is_demo(athlete_id)
        assert athlete_id.startswith(DEMO_PREFIX)


def test_clearing_removes_demo_athletes_and_leaves_real_ones(conn):
    db.insert_entry(
        conn,
        db.Entry(athlete_id="+919812340001", athlete_name="Real Athlete", kind="set",
                 lift="squat", sets=3, reps=5, weight_kg=140, session_date="2026-09-09"),
    )
    seed_demo_squad(conn, today=TODAY)
    assert len(db.list_athletes(conn)) == 10

    assert clear_demo_squad(conn) == 9
    remaining = db.list_athletes(conn)
    assert remaining == ["+919812340001"]
    assert db.session_history(conn, "+919812340001", "squat")


def test_clearing_an_empty_database_is_harmless(conn):
    assert clear_demo_squad(conn) == 0
    assert db.list_athletes(conn) == []


def test_the_priya_case_is_the_one_blocked_on_the_coach(conn):
    """The demo's headline: an athlete the agent cannot unblock by itself."""
    seed_demo_squad(conn, today=TODAY)
    roster = build_roster(conn, today=TODAY)
    blocked = roster.bucket(Bucket.NEEDS_YOU)
    assert len(blocked) == 1
    assert blocked[0].display_name == "Priya Kulkarni"
    assert blocked[0].needs_action is True
    assert db.injury_state(conn, f"{DEMO_PREFIX}001")[0] is True

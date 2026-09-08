"""Layer 2 tests: the log round-trips, and derived state follows the log."""

from __future__ import annotations

import sqlite3

import pytest

from app.storage import db
from app.storage.lifts import normalize_lift
from tests.conftest import entry

ATHLETE = "+911"


def test_a_set_round_trips():
    conn = db.connect(":memory:")
    db.init_db(conn)
    db.insert_entry(conn, entry("2026-09-01", 140, 8))
    (row,) = db.session_history(conn, ATHLETE, "squat")
    assert (row.weight_kg, row.rpe, row.sets, row.reps) == (140.0, 8.0, 3, 5)


def test_history_is_returned_oldest_first(conn):
    for day, weight in [("2026-09-08", 145), ("2026-09-01", 140), ("2026-09-04", 142.5)]:
        db.insert_entry(conn, entry(day, weight))
    assert [e.weight_kg for e in db.session_history(conn, ATHLETE, "squat")] == [140.0, 142.5, 145.0]


def test_lift_names_are_normalised_on_the_way_in(conn):
    db.insert_entry(conn, entry("2026-09-01", 100, lift="BP"))
    db.insert_entry(conn, entry("2026-09-04", 102.5, lift="bench press"))
    assert len(db.session_history(conn, ATHLETE, "bench")) == 2
    assert db.list_lifts(conn, ATHLETE) == ["bench press"]


def test_athletes_are_isolated_from_each_other(conn):
    db.insert_entry(conn, entry("2026-09-01", 140, athlete_id="+911"))
    db.insert_entry(conn, entry("2026-09-01", 200, athlete_id="+922"))
    assert [e.weight_kg for e in db.session_history(conn, "+911", "squat")] == [140.0]
    assert [e.weight_kg for e in db.session_history(conn, "+922", "squat")] == [200.0]


def test_phase_defaults_to_maintain_and_then_follows_the_latest_declaration(conn):
    assert db.latest_phase(conn, ATHLETE) == "maintain"
    db.insert_entry(conn, entry("2026-09-01", 140, phase="bulk"))
    assert db.latest_phase(conn, ATHLETE) == "bulk"
    db.insert_entry(conn, entry("2026-09-04", 140, phase="cut"))
    assert db.latest_phase(conn, ATHLETE) == "cut"


def test_injury_state_is_derived_from_the_log_not_stored_separately(conn):
    assert db.injury_state(conn, ATHLETE) == (False, None)
    db.insert_entry(
        conn,
        db.Entry(athlete_id=ATHLETE, kind="status", injured=True,
                 injury_note="left knee", session_date="2026-09-01"),
    )
    assert db.injury_state(conn, ATHLETE) == (True, "left knee")
    db.insert_entry(
        conn,
        db.Entry(athlete_id=ATHLETE, kind="status", injured=False, session_date="2026-09-05"),
    )
    assert db.injury_state(conn, ATHLETE)[0] is False


def test_a_status_row_needs_no_lift(conn):
    db.insert_entry(conn, db.Entry(athlete_id=ATHLETE, kind="status", phase="cut", session_date="2026-09-01"))
    assert db.list_lifts(conn, ATHLETE) == []


def test_a_set_row_without_a_lift_is_refused_by_the_schema(conn):
    with pytest.raises(sqlite3.IntegrityError):
        conn.execute(
            "INSERT INTO entries (athlete_id, kind, session_date, created_at) VALUES (?,?,?,?)",
            (ATHLETE, "set", "2026-09-01", "2026-09-01T00:00:00"),
        )


def test_an_invalid_phase_is_refused_by_the_schema(conn):
    with pytest.raises(sqlite3.IntegrityError):
        conn.execute(
            "INSERT INTO entries (athlete_id, kind, lift, phase, session_date, created_at) "
            "VALUES (?,?,?,?,?,?)",
            (ATHLETE, "set", "squat", "recomp", "2026-09-01", "2026-09-01T00:00:00"),
        )


def test_session_date_defaults_to_today_when_omitted(conn):
    from datetime import date

    db.insert_entry(conn, db.Entry(athlete_id=ATHLETE, lift="squat", weight_kg=140))
    assert db.session_history(conn, ATHLETE, "squat")[0].session_date == date.today().isoformat()


@pytest.mark.parametrize(
    "raw,expected",
    [("Squat", "squat"), ("  BENCH  ", "bench press"), ("dl", "deadlift"),
     ("OHP", "overhead press"), ("pull-ups", "pull up"), ("hip thrust", "hip thrust")],
)
def test_normalisation_table(raw, expected):
    assert normalize_lift(raw) == expected


def test_normalisation_of_nothing_is_nothing():
    assert normalize_lift(None) is None
    assert normalize_lift("   ") is None

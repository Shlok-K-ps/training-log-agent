"""Coach-led onboarding, goal pacing and injury-pivot workflows."""

from __future__ import annotations

from datetime import date

import pytest

from app.coach.demo import DEMO_PREFIX, seed_demo_squad
from app.coach.progress import goal_pace, squad_goal_paces
from app.decision.injury_pivot import injury_pivot_options
from app.storage import db


def test_onboarding_records_starting_maxes_goal_and_open_injury(conn):
    db.register_athlete(
        conn, "+919812340001", "Priya", on="2026-01-01",
        bodyweight_kg=64, squat_1rm_kg=130, bench_1rm_kg=72.5,
        deadlift_1rm_kg=155, training_days=4, experience="intermediate",
        injury_note="left knee pain", goal_lift="squat", goal_target_kg=150,
        goal_target_date="2026-04-01", created_by="Coach Rao",
    )
    profile = dict(db.latest_athlete_profile(conn, "+919812340001"))
    assert profile["bodyweight_kg"] == 64
    assert profile["squat_1rm_kg"] == 130
    assert profile["training_days"] == 4
    assert profile["goal_lift"] == "squat"
    assert db.injury_state(conn, "+919812340001") == (True, "left knee pain")


def test_partial_goal_is_rejected_during_onboarding(conn):
    with pytest.raises(ValueError, match="lift, target weight, and target date"):
        db.register_athlete(
            conn, "+919812340001", "Priya", on="2026-01-01",
            goal_lift="squat", goal_target_kg=150,
        )


@pytest.mark.parametrize(
    ("top_weight", "expected"),
    [(None, "lagging"), (150, "on_track"), (160, "ahead")],
)
def test_goal_pace_compares_e1rm_with_the_dated_checkpoint(conn, top_weight, expected):
    db.register_athlete(
        conn, "+919812340001", "Priya", on="2026-01-01",
        squat_1rm_kg=160, goal_lift="squat", goal_target_kg=190,
        goal_target_date="2026-03-02",
    )
    if top_weight is not None:
        db.insert_entry(
            conn,
            db.Entry(
                athlete_id="+919812340001", kind="set", lift="squat",
                sets=3, reps=5, weight_kg=top_weight, session_date="2026-02-01",
            ),
        )
    pace = goal_pace(conn, "+919812340001", today=date(2026, 2, 1))
    assert pace is not None
    assert pace.status == expected
    assert pace.target_kg == 190


def test_urgent_injury_ranks_full_hold_first_without_claiming_clearance():
    options = injury_pivot_options("sharp knee pain with swelling")
    assert len(options) == 4
    assert options[0].code == "full_hold"
    assert options[0].recommended is True
    assert all("clear" not in option.title.casefold() for option in options)


def test_injury_plan_selection_is_bound_to_the_current_injury_version(conn):
    db.register_athlete(
        conn, "+919812340001", "Priya", on="2026-01-01",
        injury_note="left knee pain",
    )
    first = db.open_injury_entry_id(conn, "+919812340001")
    option = injury_pivot_options("left knee pain")[0]
    db.record_injury_plan_decision(
        conn, athlete_id="+919812340001", injury_entry_id=first,
        option_code=option.code, plan_text=option.plan, approved_by="Coach Rao",
    )
    db.insert_entry(
        conn,
        db.Entry(
            athlete_id="+919812340001", kind="status", injured=True,
            injury_note="new swelling", session_date="2026-01-02",
        ),
    )
    with pytest.raises(ValueError, match="injury changed"):
        db.record_injury_plan_decision(
            conn, athlete_id="+919812340001", injury_entry_id=first,
            option_code=option.code, plan_text=option.plan, approved_by="Coach Rao",
        )


def test_demo_squad_populates_mixed_goal_and_whatsapp_states(conn):
    assert seed_demo_squad(conn, today=date(2026, 9, 11)) == 9
    assert {pace.status for pace in squad_goal_paces(conn, today=date(2026, 9, 11))} == {
        "ahead", "on_track", "lagging"
    }
    conversations = db.whatsapp_conversations(conn)
    assert any(row["unread_count"] for row in conversations)
    assert any(row["status"] == "failed" for row in db.whatsapp_messages(conn))
    assert any(
        row["athlete_id"].startswith(DEMO_PREFIX) for row in db.pending_drafts(conn)
    )

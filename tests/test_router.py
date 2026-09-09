"""End-to-end tests across all three layers, with the model replaced by a script."""

from __future__ import annotations

from datetime import date

from app.router import FALLBACK, HELP, handle_message
from app.storage import db
from tests.conftest import FakeClient

ATHLETE = "+911"
TODAY = date(2026, 9, 8)


def send(conn, calls, text="whatever", today=TODAY):
    return handle_message(conn, ATHLETE, text, FakeClient(calls), today=today)


def test_help_never_reaches_the_model(conn):
    client = FakeClient([])
    assert handle_message(conn, ATHLETE, "help", client, today=TODAY) == HELP
    assert client.seen == []


def test_an_empty_message_never_reaches_the_model(conn):
    client = FakeClient([])
    assert handle_message(conn, ATHLETE, "   ", client, today=TODAY) == FALLBACK
    assert client.seen == []


def test_a_logged_set_is_confirmed_and_stored(conn):
    reply = send(conn, [("log_set", {"lift": "squat", "sets": 3, "reps": 5, "weight": 140, "rpe": 8})])
    assert "Logged" in reply and "140 kg" in reply
    assert len(db.session_history(conn, ATHLETE, "squat")) == 1


def test_several_lifts_in_one_message_become_several_rows(conn):
    reply = send(
        conn,
        [
            ("log_set", {"lift": "squat", "sets": 3, "reps": 5, "weight": 140}),
            ("log_set", {"lift": "bench", "sets": 3, "reps": 8, "weight": 80}),
        ],
    )
    assert db.list_lifts(conn, ATHLETE) == ["bench press", "squat"] or set(
        db.list_lifts(conn, ATHLETE)
    ) == {"squat", "bench press"}
    assert reply.count("Logged") == 2


def test_an_invalid_call_is_dropped_and_the_valid_one_survives(conn):
    reply = send(
        conn,
        [
            ("log_set", {"lift": "squat", "weight": 9000}),          # rejected
            ("log_set", {"lift": "bench", "weight": 80, "reps": 5}),  # kept
        ],
    )
    assert db.list_lifts(conn, ATHLETE) == ["bench press"]
    assert "Bench Press" in reply


def test_a_reply_is_still_produced_when_every_call_is_rejected(conn):
    reply = send(conn, [("log_set", {"lift": "squat", "weight": 9000})])
    assert reply.startswith(FALLBACK.split("\n")[0])
    assert db.list_lifts(conn, ATHLETE) == []


def test_a_model_failure_does_not_lose_the_athletes_data(conn):
    class Broken:
        def call(self, text, system_instruction):
            raise RuntimeError("429 quota exceeded")

    reply = handle_message(conn, ATHLETE, "squat 3x5 140", Broken(), today=TODAY)
    assert "couldn't" in reply.lower()
    assert db.list_lifts(conn, ATHLETE) == []


def test_the_stall_arc_end_to_end(conn):
    """Three flat sessions, then the athlete asks. The verdict is the rule's, not the model's."""
    for day in ("2026-09-01", "2026-09-04", "2026-09-08"):
        send(conn, [("log_set", {"lift": "squat", "sets": 3, "reps": 5,
                                 "weight": 140, "rpe": 8, "session_date": day})])
    reply = send(conn, [("query_progress", {"lift": "squat"})])
    assert "Stalled" in reply
    assert "3 sessions" in reply


def test_the_deload_arc_end_to_end(conn):
    script = [
        ("2026-08-01", 130), ("2026-08-04", 130), ("2026-08-08", 130),
        ("2026-08-12", 135), ("2026-08-16", 140),
        ("2026-08-20", 140), ("2026-08-24", 140),
    ]
    for day, weight in script:
        send(conn, [("log_set", {"lift": "squat", "sets": 3, "reps": 5,
                                 "weight": weight, "rpe": 8, "session_date": day})])
    reply = send(conn, [("query_progress", {"lift": "squat"})])
    assert "Deload" in reply
    assert "120 kg" in reply  # 85% of 140, rounded to the nearest plate


def test_an_injury_flag_suppresses_load_advice_on_later_replies(conn):
    for day in ("2026-09-01", "2026-09-04", "2026-09-08"):
        send(conn, [("log_set", {"lift": "squat", "sets": 3, "reps": 5,
                                 "weight": 140, "rpe": 8, "session_date": day})])
    send(conn, [("log_status", {"injured": True, "injury_note": "left knee"})])
    reply = send(conn, [("query_progress", {"lift": "squat"})])
    assert "physio" in reply.lower()
    assert "➡️" not in reply


def test_clearing_the_injury_restores_advice(conn):
    for day in ("2026-09-01", "2026-09-04", "2026-09-08"):
        send(conn, [("log_set", {"lift": "squat", "sets": 3, "reps": 5,
                                 "weight": 140, "rpe": 8, "session_date": day})])
    send(conn, [("log_status", {"injured": True})])
    send(conn, [("log_status", {"injured": False})])
    reply = send(conn, [("query_progress", {"lift": "squat"})])
    assert "physio" not in reply.lower()


def test_a_cut_changes_the_meaning_of_the_same_log(conn):
    for day in ("2026-09-01", "2026-09-04", "2026-09-08"):
        send(conn, [("log_set", {"lift": "squat", "sets": 3, "reps": 5,
                                 "weight": 140, "rpe": 8, "session_date": day,
                                 "phase": "cut"})])
    reply = send(conn, [("query_progress", {"lift": "squat"})])
    assert "Holding" in reply
    assert "Stalled" not in reply


def test_a_bare_question_covers_every_lift_logged(conn):
    send(conn, [("log_set", {"lift": "squat", "weight": 140, "reps": 5})])
    send(conn, [("log_set", {"lift": "bench", "weight": 80, "reps": 5})])
    reply = send(conn, [("query_progress", {})])
    assert "Squat" in reply and "Bench Press" in reply


def test_a_clarify_call_is_passed_through_as_a_question(conn):
    reply = send(conn, [("clarify", {"question": "What weight did you use?"})])
    assert "What weight did you use?" in reply
    assert db.list_lifts(conn, ATHLETE) == []


def test_known_lifts_are_given_to_the_model_as_context(conn):
    send(conn, [("log_set", {"lift": "squat", "weight": 140, "reps": 5})])
    client = FakeClient([("query_progress", {})])
    handle_message(conn, ATHLETE, "how's it going", client, today=TODAY)
    assert client.seen == ["how's it going"]


def test_the_athletes_name_is_remembered(conn):
    send(conn, [("log_status", {"athlete_name": "Priya"})])
    assert db.athlete_name(conn, ATHLETE) == "Priya"


def test_checkin_tracks_sleep_readiness_and_nutrition_together(conn):
    reply = send(
        conn,
        [
            (
                "log_checkin",
                {
                    "sleep_hours": 7.5,
                    "readiness": 8,
                    "soreness": 3,
                    "bodyweight_kg": 80,
                    "protein_g": 144,
                },
            )
        ],
    )
    stored = db.latest_checkin(conn, ATHLETE, TODAY.isoformat())
    assert stored is not None and stored.sleep_hours == 7.5
    assert "1.8 g/kg" in reply
    assert "Readiness: green" in reply


def test_prescription_waits_for_an_explicit_program_profile(conn):
    send(conn, [("log_set", {"lift": "squat", "weight": 140, "sets": 3, "reps": 5})])
    reply = send(conn, [("ask_prescription", {"lift": "squat"})])
    assert "experience level" in reply
    assert "days per week" in reply


def test_novice_profile_history_and_readiness_feed_one_prescription(conn):
    send(
        conn,
        [
            (
                "configure_program",
                {"methodology": "auto", "experience": "novice", "days_per_week": 3},
            )
        ],
    )
    send(conn, [("log_set", {"lift": "squat", "weight": 140, "sets": 3, "reps": 5, "rpe": 8})])
    reply = send(
        conn,
        [
            ("log_checkin", {"sleep_hours": 6.5, "readiness": 6, "soreness": 5}),
            ("ask_prescription", {"lift": "squat"}),
        ],
    )
    assert "Method: linear progression" in reply
    assert "Base load 145 kg, reduced by same-day readiness" in reply


def test_red_readiness_suppresses_the_prescription(conn):
    send(conn, [("configure_program", {"experience": "novice", "days_per_week": 3})])
    send(conn, [("log_set", {"lift": "squat", "weight": 140, "sets": 3, "reps": 5})])
    reply = send(
        conn,
        [
            ("log_checkin", {"sleep_hours": 3, "readiness": 2, "soreness": 9}),
            ("ask_prescription", {"lift": "squat"}),
        ],
    )
    assert "severe recovery flag" in reply
    assert "➡️" not in reply


def test_morning_sleep_checkin_schedules_a_nap(conn):
    send(
        conn,
        [
            (
                "configure_schedule",
                {
                    "timezone": "Asia/Kolkata",
                    "morning_checkin_time": "07:30",
                    "training_time": "18:30",
                    "nap_window_start": "13:00",
                    "nap_window_end": "15:00",
                },
            )
        ],
    )
    reply = send(
        conn,
        [
            (
                "log_checkin",
                {"sleep_hours": 5.5, "readiness": 5, "training_lift": "squat"},
            )
        ],
    )
    assert "Nap: 45 minutes at 13:00" in reply


def test_completed_nap_recalculates_the_planned_lift_without_erasing_sleep(conn):
    send(conn, [("configure_program", {"experience": "novice", "days_per_week": 3})])
    send(conn, [("log_set", {"lift": "squat", "weight": 140, "sets": 3, "reps": 5})])
    send(
        conn,
        [
            (
                "log_checkin",
                {"sleep_hours": 5, "readiness": 4, "training_lift": "squat"},
            )
        ],
    )
    reply = send(conn, [("log_nap", {"nap_minutes": 40, "readiness": 7})])
    assert "Nap logged: 40 minutes" in reply
    assert "original night's sleep remains" in reply
    assert "Squat — next session" in reply


def test_nap_cannot_override_a_severe_sleep_flag(conn):
    send(conn, [("configure_program", {"experience": "novice", "days_per_week": 3})])
    send(conn, [("log_set", {"lift": "squat", "weight": 140, "sets": 3, "reps": 5})])
    send(
        conn,
        [("log_checkin", {"sleep_hours": 3, "readiness": 2, "training_lift": "squat"})],
    )
    reply = send(conn, [("log_nap", {"nap_minutes": 45, "readiness": 8})])
    assert "severe recovery flag" in reply
    assert "➡️" not in reply


def test_food_access_and_approved_supplement_build_a_training_day_plan(conn):
    send(
        conn,
        [
            (
                "configure_nutrition",
                {
                    "diet_style": "vegetarian",
                    "foods_available": ["rice", "dal", "paneer", "banana"],
                    "allergies": ["peanuts"],
                    "cooking_access": "basic",
                    "meals_per_day": 4,
                },
            ),
            (
                "configure_supplement",
                {
                    "name": "creatine",
                    "dose": 5,
                    "unit": "g",
                    "timing": "post_training",
                    "approved_by": "coach",
                    "batch_tested": True,
                },
            ),
        ],
    )
    reply = send(conn, [("ask_nutrition_plan", {"training_time": "18:30"})])
    assert "pre-training meal" in reply and "16:30" in reply
    assert "post-training meal" in reply and "19:30" in reply
    assert "creatine 5 g" in reply
    assert "peanuts" not in reply


def test_unapproved_supplement_is_saved_but_not_scheduled(conn):
    reply = send(
        conn,
        [
            (
                "configure_supplement",
                {"name": "mystery blend", "dose": 1, "unit": "scoop", "timing": "pre_training"},
            )
        ],
    )
    assert "will not be scheduled" in reply
    send(
        conn,
        [
            (
                "configure_nutrition",
                {"diet_style": "vegan", "foods_available": ["rice", "tofu", "banana"]},
            )
        ],
    )
    plan = send(conn, [("ask_nutrition_plan", {"training_time": "18:30"})])
    assert "mystery blend 1 scoop" not in plan
    assert "mystery blend was not scheduled" in plan


def test_nutrition_plan_asks_for_access_instead_of_inventing_food(conn):
    reply = send(conn, [("ask_nutrition_plan", {"training_time": "18:30"})])
    assert "diet style" in reply and "foods" in reply


def test_supplement_intake_is_logged_and_unknown_schedule_is_flagged(conn):
    reply = send(conn, [("log_supplement_taken", {"name": "creatine"})])
    assert "Taken: creatine" in reply
    assert "no active dose schedule" in reply


def test_morning_training_time_can_trigger_the_food_plan(conn):
    send(
        conn,
        [
            (
                "configure_nutrition",
                {"diet_style": "vegan", "foods_available": ["rice", "tofu", "banana"]},
            )
        ],
    )
    reply = send(
        conn,
        [
            (
                "log_checkin",
                {"sleep_hours": 7, "readiness": 8, "training_time": "18:30"},
            )
        ],
    )
    assert "Today's food and approved supplements" in reply
    assert "pre-training meal" in reply

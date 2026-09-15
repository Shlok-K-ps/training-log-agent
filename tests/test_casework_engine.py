"""The training-day agent over simulated time: it owns a day until the outcome is known."""

from __future__ import annotations

import re
from datetime import date, datetime, timedelta
from zoneinfo import ZoneInfo

import pytest

from app.agent.schemas import validate_call
from app.casework import engine, store
from app.casework.transport import DeliveryFailed
from app.storage import db

TZ = ZoneInfo("Asia/Kolkata")
MONDAY = date(2026, 9, 14)
ATHLETE = "+919812340001"
QUIET = "+919812340002"
COACH = "Coach Rao"


def at(day: date, clock: str) -> datetime:
    hour, minute = (int(piece) for piece in clock.split(":"))
    return datetime(day.year, day.month, day.day, hour, minute, tzinfo=TZ)


class FakeTransport:
    def __init__(self):
        self.athlete: list[tuple[str, str, str]] = []
        self.coach: list[dict] = []
        self.unreachable: set[str] = set()
        self.withdrawn: list[tuple[str, str]] = []

    def send_athlete(self, conn, athlete_id, body, *, kind):
        if athlete_id in self.unreachable:
            raise DeliveryFailed("This athlete has no connected Telegram chat.")
        self.athlete.append((athlete_id, kind, body))
        return f"fake:{len(self.athlete)}"

    def notify_coach(self, conn, *, case_id, athlete_name, local_date, title, evidence, options):
        self.coach.append({"case_id": case_id, "title": title, "evidence": evidence, "options": options})
        return f"coach:{len(self.coach)}"

    def withdraw_athlete_message(self, conn, athlete_id, provider_sid):
        self.withdrawn.append((athlete_id, provider_sid))
        return True

    def kinds(self, athlete_id=ATHLETE):
        return [kind for who, kind, _ in self.athlete if who == athlete_id]


class Crash(BaseException):
    """Stands in for the process dying mid-send."""


@pytest.fixture()
def world(conn):
    for athlete_id, name in ((ATHLETE, "Priya Kulkarni"), (QUIET, "Neha Desai")):
        db.register_athlete(conn, athlete_id, name, on="2026-09-01")
        db.insert_entry(conn, db.Entry(
            athlete_id=athlete_id, kind="status", timezone="Asia/Kolkata",
            morning_checkin_time="07:30", training_time="18:00", session_date="2026-09-01",
        ))
        for weekday in range(7):
            store.add_plan_session(conn, athlete_id=athlete_id, weekday=weekday, lift="squat",
                                   sets=4, reps=5, rpe=7, approved_by=COACH, now=at(MONDAY, "06:00"))
        store.set_autopilot(conn, athlete_id, True, updated_by=COACH, now=at(MONDAY, "06:00"))
    return conn, FakeTransport()


def tick(conn, transport, moment):
    return engine.tick(conn, now=moment, transport=transport, coach_name=COACH)


def say(conn, transport, moment, calls, athlete_id=ATHLETE, text="message"):
    actions = [validate_call(name, args, moment.date()) for name, args in calls]
    for action in actions:
        if type(action).__name__ == "LogStatus" and action.injured:
            db.insert_entry(conn, db.Entry(athlete_id=athlete_id, kind="status", injured=True,
                                           injury_note=action.injury_note,
                                           session_date=moment.date().isoformat()))
    return engine.observe_message(conn, athlete_id, actions, raw_text=text, now=moment,
                                  transport=transport, coach_name=COACH)


def case_for(conn, day=MONDAY, athlete_id=ATHLETE):
    return store.case_for_day(conn, athlete_id, day.isoformat())


def event_codes(conn, case):
    return [(row["kind"], row["code"]) for row in store.case_events(conn, case["id"])]


def test_a_routine_day_closes_without_the_coach(world):
    conn, transport = world
    assert tick(conn, transport, at(MONDAY, "07:00")).opened == 2
    assert transport.athlete == [], "nothing is sent before the check-in time"

    tick(conn, transport, at(MONDAY, "07:31"))
    assert transport.kinds() == ["checkin_sent"]
    assert case_for(conn)["state"] == "awaiting_checkin"

    assert say(conn, transport, at(MONDAY, "08:05"),
               [("log_checkin", {"sleep_hours": 7.5, "readiness": 8, "soreness": 3})])
    session = transport.athlete[-1]
    assert session[1] == "session_delivered"
    assert "Squat 4×5 @ RPE 7" in session[2]
    assert not re.search(r"\d\s*kg", session[2]), "the agent never names a load"
    assert case_for(conn)["state"] == "awaiting_outcome"

    tick(conn, transport, at(MONDAY, "20:31"))
    assert transport.kinds()[-1] == "outcome_question_sent"

    assert say(conn, transport, at(MONDAY, "21:10"),
               [("log_set", {"lift": "squat", "sets": 4, "reps": 5, "weight": 140, "rpe": 7})])
    closed = case_for(conn)
    assert (closed["state"], closed["outcome"]) == ("closed", "completed")
    assert transport.coach == [], "a routine day never reaches the coach"
    kinds = {kind for kind, _ in event_codes(conn, closed)}
    assert {"observation", "decision", "action", "expectation", "outcome"} <= kinds


def test_lower_readiness_reduces_the_session_and_never_increases_it(world):
    conn, transport = world
    tick(conn, transport, at(MONDAY, "07:31"))
    say(conn, transport, at(MONDAY, "08:00"),
        [("log_checkin", {"sleep_hours": 6, "readiness": 6, "soreness": 5})])
    body = transport.athlete[-1][2]
    assert "Squat 4×5 @ RPE 6.5" in body
    assert "Planned was:" in body and "Squat 4×5 @ RPE 7" in body


def test_safety_evidence_ordered_before_dispatch_retires_the_workout(world):
    conn, transport = world
    tick(conn, transport, at(MONDAY, "07:31"))
    readiness_sequence = db.record_athlete_event(
        conn, athlete_id=ATHLETE, kind="inbound_evidence", summary="Safe readiness accepted.",
        detail={"safety_signal": None}, occurred_at=store.iso(at(MONDAY, "08:00")),
    )
    db.record_athlete_event(
        conn, athlete_id=ATHLETE, kind="inbound_evidence", summary="Pain accepted before dispatch.",
        detail={"safety_signal": "pain_or_injury"}, occurred_at=store.iso(at(MONDAY, "08:01")),
    )
    actions = [validate_call("log_checkin", {"sleep_hours": 8, "readiness": 8}, MONDAY)]
    assert engine.observe_message(
        conn, ATHLETE, actions, raw_text="slept 8 hours, readiness 8", now=at(MONDAY, "08:02"),
        transport=transport, coach_name=COACH, event_sequence=readiness_sequence,
    )
    assert "session_delivered" not in transport.kinds()
    case = case_for(conn)
    assert ("decision", "workout_retired_before_dispatch") in event_codes(conn, case)
    order = list(conn.execute("SELECT sequence, kind FROM athlete_event_log WHERE athlete_id = ? ORDER BY sequence", (ATHLETE,)))
    assert [row["sequence"] for row in order] == sorted(row["sequence"] for row in order)


def test_an_incomplete_checkin_gets_one_clarifying_question(world):
    conn, transport = world
    tick(conn, transport, at(MONDAY, "07:31"))
    say(conn, transport, at(MONDAY, "08:00"), [("log_checkin", {"soreness": 4})])
    assert transport.kinds()[-1] == "clarification_sent"
    say(conn, transport, at(MONDAY, "08:10"), [("log_checkin", {"sleep_hours": 8, "readiness": 8})])
    assert transport.kinds()[-1] == "session_delivered"
    assert transport.kinds().count("clarification_sent") == 1


def test_an_unresponsive_athlete_gets_bounded_follow_ups_then_the_day_closes(world):
    conn, transport = world
    for clock in ("07:31", "09:02", "11:02", "13:32", "15:00", "19:00"):
        tick(conn, transport, at(MONDAY, clock))
    assert transport.kinds(QUIET) == ["checkin_sent", "follow_up_sent", "follow_up_sent"]
    closed = case_for(conn, athlete_id=QUIET)
    assert (closed["state"], closed["outcome"]) == ("closed", "no_response")
    assert transport.coach == []

    tuesday = MONDAY + timedelta(days=1)
    for clock in ("07:31", "09:02", "11:02", "13:32", "17:00"):
        tick(conn, transport, at(tuesday, clock))
    second = case_for(conn, tuesday, QUIET)
    assert second["state"] == "needs_coach"
    assert [c["title"] for c in transport.coach if c["case_id"] == second["id"]] == [
        "Silent on consecutive training days"
    ]
    assert transport.kinds(QUIET).count("follow_up_sent") == 4, "still exactly two per day"


def test_an_injury_report_immediately_stops_autonomous_guidance(world):
    conn, transport = world
    tick(conn, transport, at(MONDAY, "07:31"))
    say(conn, transport, at(MONDAY, "08:00"), [("log_checkin", {"sleep_hours": 8, "readiness": 8})])
    assert transport.kinds()[-1] == "session_delivered"

    assert say(conn, transport, at(MONDAY, "09:00"),
               [("log_status", {"injured": True, "injury_note": "left knee pain on stairs"})])
    hold = transport.athlete[-1]
    assert hold[1] == "guidance_paused"
    assert "don't train the session" in hold[2]
    assert transport.withdrawn == [(ATHLETE, "fake:3")]
    case = case_for(conn)
    assert case["state"] == "needs_coach"
    assert transport.coach[-1]["title"] == "Injury reported"
    assert ("rest", "Rest today") in transport.coach[-1]["options"]
    assert ("action", "workout_withdrawal_attempted") in event_codes(conn, case)

    sent_before = len(transport.athlete)
    tick(conn, transport, at(MONDAY, "20:31"))
    assert len(transport.athlete) == sent_before, "no outcome question while a decision is pending"

    say(conn, transport, at(MONDAY, "21:00"), [("log_checkin", {"sleep_hours": 8, "readiness": 9})])
    assert len(transport.athlete) == sent_before, "a new check-in cannot restart autonomous guidance"


def test_an_athlete_already_injured_gets_no_session_only_a_coach_review(world):
    conn, transport = world
    db.insert_entry(conn, db.Entry(athlete_id=ATHLETE, kind="status", injured=True,
                                   injury_note="lower back", session_date="2026-09-12"))
    tick(conn, transport, at(MONDAY, "07:31"))
    say(conn, transport, at(MONDAY, "08:00"), [("log_checkin", {"sleep_hours": 8, "readiness": 9})])
    assert "session_delivered" not in transport.kinds()
    assert transport.kinds()[-1] == "coach_review_notice"
    assert case_for(conn)["state"] == "needs_coach"


def test_a_coach_decision_lets_the_case_continue_to_a_known_outcome(world):
    conn, transport = world
    tick(conn, transport, at(MONDAY, "07:31"))
    say(conn, transport, at(MONDAY, "08:00"),
        [("log_status", {"injured": True, "injury_note": "left knee pain"})])
    case = case_for(conn)

    ok, _ = engine.apply_coach_decision(conn, case["id"], "made_up", coach_name=COACH,
                                        now=at(MONDAY, "08:30"), transport=transport)
    assert not ok
    ok, message = engine.apply_coach_decision(conn, case["id"], "unaffected_only", coach_name=COACH,
                                              now=at(MONDAY, "08:30"), transport=transport)
    assert ok and "injury flag stays open" in message
    assert transport.kinds()[-1] == "injury_plan_sent"
    assert db.latest_injury_plan_decision(conn, ATHLETE)["option_code"] == "unaffected_only"
    assert db.injury_state(conn, ATHLETE)[0] is True
    assert case_for(conn)["state"] == "awaiting_outcome"

    again, _ = engine.apply_coach_decision(conn, case["id"], "rest", coach_name=COACH,
                                           now=at(MONDAY, "08:31"), transport=transport)
    assert not again, "a case is decided once"

    tick(conn, transport, at(MONDAY, "20:31"))
    assert "adjusted plan" in transport.athlete[-1][2]
    say(conn, transport, at(MONDAY, "21:00"), [("report_session_outcome", {"status": "done"})])
    assert (case_for(conn)["state"], case_for(conn)["outcome"]) == ("closed", "done")


def test_autopilot_off_waits_for_the_coach_then_sends_the_approved_session(world):
    conn, transport = world
    store.set_autopilot(conn, ATHLETE, False, updated_by=COACH, now=at(MONDAY, "06:00"))
    tick(conn, transport, at(MONDAY, "07:31"))
    say(conn, transport, at(MONDAY, "08:00"), [("log_checkin", {"sleep_hours": 8, "readiness": 8})])
    case = case_for(conn)
    assert case["state"] == "needs_coach"
    ok, _ = engine.apply_coach_decision(conn, case["id"], "send", coach_name=COACH,
                                        now=at(MONDAY, "08:20"), transport=transport)
    assert ok
    assert "confirmed by Coach Rao" in transport.athlete[-1][2]
    assert case_for(conn)["state"] == "awaiting_outcome"


def test_an_unreachable_athlete_is_escalated_instead_of_assumed_contacted(world):
    conn, transport = world
    transport.unreachable.add(ATHLETE)
    tick(conn, transport, at(MONDAY, "07:31"))
    case = case_for(conn)
    assert case["state"] == "needs_coach"
    assert transport.coach[-1]["title"] == "Message could not be delivered"


def test_a_crash_after_sending_never_produces_a_duplicate(tmp_path, monkeypatch):
    path = tmp_path / "agent.db"
    conn = db.connect(path)
    db.init_db(conn)
    db.register_athlete(conn, ATHLETE, "Priya Kulkarni", on="2026-09-01")
    db.insert_entry(conn, db.Entry(athlete_id=ATHLETE, kind="status", timezone="Asia/Kolkata",
                                   morning_checkin_time="07:30", session_date="2026-09-01"))
    store.add_plan_session(conn, athlete_id=ATHLETE, weekday=MONDAY.weekday(), lift="squat",
                           sets=4, reps=5, rpe=7, approved_by=COACH, now=at(MONDAY, "06:00"))
    transport = FakeTransport()

    def die(key):
        raise Crash(key)

    monkeypatch.setattr(engine, "AFTER_SEND", die)
    with pytest.raises(Crash):
        tick(conn, transport, at(MONDAY, "07:31"))
    conn.close()
    assert transport.kinds() == ["checkin_sent"], "the message left before the process died"

    monkeypatch.setattr(engine, "AFTER_SEND", None)
    restarted = db.connect(path)
    db.init_db(restarted)
    report = tick(restarted, transport, at(MONDAY, "07:40"))
    tick(restarted, transport, at(MONDAY, "07:41"))
    assert transport.kinds() == ["checkin_sent"], "no duplicate after the restart"
    assert report.recovered == 1
    case = case_for(restarted)
    assert case["state"] == "awaiting_checkin"
    statuses = [row["status"] for row in store.case_events(restarted, case["id"]) if row["kind"] == "action"]
    assert statuses == ["unconfirmed"]
    restarted.close()


def test_repeated_ticks_at_the_same_moment_are_idempotent(world):
    conn, transport = world
    for _ in range(3):
        tick(conn, transport, at(MONDAY, "07:31"))
    assert transport.kinds() == ["checkin_sent"]
    assert len([c for c in store.cases_in_states(conn, ("awaiting_checkin",))]) == 2


def test_the_checkin_time_adapts_to_late_replies_and_explains_why(world):
    conn, transport = world
    day = MONDAY
    for offset in range(4):
        current = day + timedelta(days=offset)
        tick(conn, transport, at(current, "07:31"))
        say(conn, transport, at(current, "09:10"),
            [("log_checkin", {"sleep_hours": 8, "readiness": 8})])
        say(conn, transport, at(current, "19:00"), [("report_session_outcome", {"status": "done"})])

    fifth = day + timedelta(days=4)
    report = tick(conn, transport, at(fifth, "07:00"))
    assert report.adaptations >= 1
    case = case_for(conn, fifth)
    assert case["checkin_time"] == "08:00"
    adapted = [row for row in store.case_events(conn, case["id"]) if row["kind"] == "adaptation"]
    assert adapted and "median 99 minutes" in adapted[0]["summary"]
    assert "never be earlier than the coach's 07:30" in adapted[0]["summary"]
    record = store.latest_adaptation(conn, ATHLETE, "checkin_time")
    assert (record["old_value"], record["new_value"]) == ("07:30", "08:00")

    tick(conn, transport, at(fifth, "07:45"))
    assert transport.kinds().count("checkin_sent") == 4, "the moved check-in has not fired yet"
    tick(conn, transport, at(fifth, "08:01"))
    assert transport.kinds().count("checkin_sent") == 5

    sixth = day + timedelta(days=5)
    tick(conn, transport, at(sixth, "07:00"))
    assert case_for(conn, sixth)["checkin_time"] == "08:00", "new evidence is needed before moving again"


def test_no_training_day_is_opened_once_training_time_has_passed(world):
    conn, transport = world
    report = tick(conn, transport, at(MONDAY, "18:05"))
    assert report.opened == 0 and transport.athlete == []
    assert case_for(conn) is None
    tomorrow = MONDAY + timedelta(days=1)
    assert tick(conn, transport, at(tomorrow, "07:31")).opened == 2, "the next day opens normally"

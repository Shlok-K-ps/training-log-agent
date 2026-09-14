"""Fictional training days played through the real agent, in a throwaway database.

The public demonstration and the coach's "safe simulated test" both run here.
Nothing is simulated by hand: the real engine, parser, rules and message
templates run against a private in-memory SQLite database that exists only for
the length of one simulation. It is never the production database, nothing is
sent anywhere, and the only output is a trace of what the agent observed,
decided and did, ready to be played back.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime, timedelta, timezone
from functools import lru_cache
from typing import Callable
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from app.agent.offline import OfflineClient
from app.agent.parser import parse_message
from app.agent.schemas import LOOP_TOOL_NAMES
from app.casework import engine, store
from app.casework.engine import OUTCOME_LABELS, STATE_LABELS
from app.casework.policy import DEFAULT_CHECKIN_TIME, DEFAULT_TRAINING_TIME
from app.router import handle_message_with_actions
from app.storage import db

PUBLIC_DAY = date(2026, 1, 5)  # a fictional Monday
PUBLIC_COACH = "Coach Maya"

KIND_LABELS = {
    "clock": "Time passes",
    "athlete": "Athlete",
    "interpret": "Interpretation",
    "rule": "Fixed rule",
    "action": "Agent action",
    "wait": "Agent waits",
    "observe": "Agent observes",
    "escalation": "Needs the coach",
    "coach": "Coach decision",
    "outcome": "Outcome",
    "adapt": "Adaptation",
}

ACTION_TITLES = {
    "checkin_sent": "Sent the morning check-in",
    "follow_up_sent": "Followed up on a missing reply",
    "clarification_sent": "Asked for the missing check-in values",
    "session_delivered": "Delivered today's session",
    "coach_review_notice": "Told the athlete the coach is reviewing",
    "guidance_paused": "Paused all training guidance",
    "outcome_question_sent": "Asked whether training happened",
    "outcome_reminder_sent": "Sent one reminder",
    "log_confirmed": "Confirmed the logged session",
    "outcome_acknowledged": "Acknowledged the session report",
    "rest_day_sent": "Sent the coach's rest day",
    "injury_plan_sent": "Sent the coach's injury plan",
    "coach_notified": "Alerted the coach with one-tap options",
}
DECISION_TITLES = {
    "checkin_scheduled": "Scheduled today's check-in",
    "checkin_assessed": "Scored readiness with fixed rules",
    "checkin_incomplete": "Found missing check-in values",
    "guidance_stopped": "Injury rule: stopped all training guidance",
}
COACH_AUTHORISED = {"rest_day_sent", "injury_plan_sent"}


def _fmt(value: object) -> str:
    if isinstance(value, bool):
        return "true" if value else "false"
    if isinstance(value, float) and value.is_integer():
        return str(int(value))
    if isinstance(value, str):
        return f'"{value}"'
    return str(value)


def _plus(clock: str, minutes: int) -> str:
    hour, minute = (int(piece) for piece in clock.split(":"))
    total = min(23 * 60 + 59, max(0, hour * 60 + minute + minutes))
    return f"{total // 60:02d}:{total % 60:02d}"


class _Recorder:
    """A transport that delivers to nobody and remembers what the coach was shown."""

    def __init__(self, simulation: "Simulation"):
        self.simulation = simulation

    def send_athlete(self, conn, athlete_id: str, body: str, *, kind: str) -> str:
        self.simulation.delivered += 1
        return f"simulation:{self.simulation.delivered}"

    def notify_coach(self, conn, *, case_id, athlete_name, local_date, title, evidence, options):
        self.simulation.coach_alerts.append(
            {"title": title, "evidence": list(evidence), "options": [list(o) for o in options]}
        )
        return "simulation:coach"


@dataclass
class _Athlete:
    key: str
    athlete_id: str
    name: str
    plan: tuple[tuple[str, int, int, float], ...]
    autopilot: bool | None

    @property
    def first(self) -> str:
        return self.name.split()[0]


class Simulation:
    def __init__(self, day: date, *, coach_name: str, timezone_name: str = "UTC"):
        try:
            self.zone = ZoneInfo(timezone_name)
        except (ZoneInfoNotFoundError, ValueError):
            self.zone = ZoneInfo("UTC")
        self.timezone_name = str(self.zone)
        self.day = day
        self.coach_name = coach_name
        # Private to this simulation: never the configured production database.
        self.conn = db.connect(":memory:")
        db.init_db(self.conn)
        self.transport = _Recorder(self)
        self.athletes: dict[str, _Athlete] = {}
        self.by_id: dict[str, str] = {}
        self.steps: list[dict] = []
        self.clock: str | None = None
        self.last_event = 0
        self.delivered = 0
        self.coach_alerts: list[dict] = []

    # --- setting up the fictional day -------------------------------------------------

    def add_athlete(
        self, key: str, name: str, *, checkin: str, training: str,
        plan: list[tuple[str, int, int, float]], autopilot: bool | None,
        injury_note: str | None = None,
    ) -> None:
        athlete_id = f"+1555010{len(self.athletes) + 1:04d}"
        before = (self.day - timedelta(days=7)).isoformat()
        db.register_athlete(self.conn, athlete_id, name, on=before, injury_note=injury_note)
        db.insert_entry(self.conn, db.Entry(
            athlete_id=athlete_id, kind="status", timezone=self.timezone_name,
            morning_checkin_time=checkin, training_time=training, session_date=before,
        ))
        approved = datetime.combine(self.day - timedelta(days=7), datetime.min.time(), timezone.utc)
        for weekday in range(7):
            for lift, sets, reps, rpe in plan:
                store.add_plan_session(
                    self.conn, athlete_id=athlete_id, weekday=weekday, lift=lift, sets=sets,
                    reps=reps, rpe=rpe, approved_by=self.coach_name, now=approved,
                )
        if autopilot is not None:
            store.set_autopilot(self.conn, athlete_id, autopilot, updated_by=self.coach_name, now=approved)
        self.athletes[key] = _Athlete(key, athlete_id, name, tuple(plan), autopilot)
        self.by_id[athlete_id] = key

    def moment(self, clock: str) -> datetime:
        hour, minute = (int(piece) for piece in clock.split(":"))
        local = datetime(self.day.year, self.day.month, self.day.day, hour, minute, tzinfo=self.zone)
        return local.astimezone(timezone.utc)

    # --- driving it -----------------------------------------------------------------

    def _step(self, kind: str, *, athlete: str | None = None, title: str, body: str = "",
              detail: dict | None = None, **flags) -> None:
        self.steps.append({
            "clock": self.clock, "kind": kind, "label": KIND_LABELS.get(kind, kind),
            "athlete": athlete, "title": title, "body": body, "detail": detail or {}, **flags,
        })

    def _advance(self, clock: str) -> None:
        if clock != self.clock:
            self.clock = clock
            self._step("clock", title=clock)

    def tick(self, clock: str) -> None:
        self._advance(clock)
        engine.tick(self.conn, now=self.moment(clock), transport=self.transport, coach_name=self.coach_name)
        self._drain()

    def say(self, key: str, text: str, clock: str) -> None:
        athlete = self.athletes[key]
        self._advance(clock)
        self._step("athlete", athlete=key, title=f"{athlete.first} replies", body=text, from_athlete=True)
        parsed = parse_message(text, OfflineClient(), today=self.day, allowed=LOOP_TOOL_NAMES)
        calls = [
            f"{name}({', '.join(f'{k}={_fmt(v)}' for k, v in args.items())})"
            for name, args in parsed.raw_calls if name in LOOP_TOOL_NAMES
        ]
        self._step(
            "interpret", athlete=key, title="Turned the message into validated data",
            body="\n".join(calls) or "Nothing usable: the agent will ask again.",
            detail={"rejected": list(parsed.rejected)},
        )
        _, actions = handle_message_with_actions(
            self.conn, athlete.athlete_id, text, OfflineClient(), today=self.day, allowed=LOOP_TOOL_NAMES
        )
        engine.observe_message(
            self.conn, athlete.athlete_id, actions, raw_text=text, now=self.moment(clock),
            transport=self.transport, coach_name=self.coach_name,
        )
        self._drain()

    def coach(self, key: str, clock: str, choose: Callable[[list[list[str]]], str], *, simulated_by: str = "") -> bool:
        athlete = self.athletes[key]
        case = store.case_for_day(self.conn, athlete.athlete_id, self.day.isoformat())
        if case is None or case["state"] != "needs_coach":
            return False
        self._advance(clock)
        options = (store.loads(case["escalation_json"]) or {}).get("options", [])
        code = choose(options)
        engine.apply_coach_decision(
            self.conn, int(case["id"]), code, coach_name=self.coach_name,
            now=self.moment(clock), transport=self.transport,
        )
        self._drain(coach_note=simulated_by)
        return True

    def case_state(self, key: str) -> str | None:
        case = store.case_for_day(self.conn, self.athletes[key].athlete_id, self.day.isoformat())
        return None if case is None else str(case["state"])

    def _drain(self, coach_note: str = "") -> None:
        rows = list(self.conn.execute(
            "SELECT * FROM agent_events WHERE id > ? ORDER BY id", (self.last_event,)
        ))
        for row in rows:
            self.last_event = int(row["id"])
            kind, code = str(row["kind"]), str(row["code"])
            key = self.by_id.get(str(row["athlete_id"]))
            detail = store.loads(row["detail_json"]) or {}
            summary = str(row["summary"])
            if kind == "observation":
                if code in {"athlete_message", "interrupted_send_found"}:
                    continue
                self._step("observe", athlete=key, title=summary)
            elif kind == "decision":
                body = summary
                if code == "checkin_assessed" and detail.get("changes"):
                    body += " " + " ".join(detail["changes"])
                self._step("rule", athlete=key, title=DECISION_TITLES.get(code, "Applied a fixed rule"),
                           body=body)
            elif kind == "action":
                if code == "coach_notified":
                    alert = self.coach_alerts[-1] if self.coach_alerts else {}
                    # The options are already shown on the escalation step just before this one.
                    self._step("action", athlete=key, title=ACTION_TITLES[code],
                               body=f"Sent to the coach's Telegram: {alert.get('title', '')}",
                               to_coach=True, authority="autonomous")
                    continue
                message = str(detail.get("message", ""))
                # engine summary for a coach-approved session: "Delivered the session <coach> approved."
                coach_authorised = code in COACH_AUTHORISED or summary.endswith(" approved.")
                self._step("action", athlete=key, title=ACTION_TITLES.get(code, summary), body=message,
                           to_athlete=bool(message),
                           authority="coach" if coach_authorised else "autonomous")
            elif kind == "expectation":
                self._step("wait", athlete=key, title="Waits for the athlete", body=summary)
            elif kind == "escalation":
                self._step("escalation", athlete=key, title=f"Needs the coach: {detail.get('title', '')}",
                           body=" ".join(str(line) for line in detail.get("evidence", [])),
                           detail={"options": detail.get("options", [])})
            elif kind == "coach":
                body = coach_note or "One tap in the coach's Telegram. No message typed."
                self._step("coach", athlete=key, title=summary, body=body)
            elif kind == "outcome":
                self._step("outcome", athlete=key, title=OUTCOME_LABELS.get(code, code), body=summary)
            elif kind == "adaptation":
                self._step("adapt", athlete=key, title="Adapted the check-in time", body=summary)
        if self.steps:
            self.steps[-1]["cases"] = self._snapshot()

    def _snapshot(self) -> dict[str, dict]:
        snapshot = {}
        for key, athlete in self.athletes.items():
            case = store.case_for_day(self.conn, athlete.athlete_id, self.day.isoformat())
            if case is None:
                snapshot[key] = {"state": "No case yet", "state_code": "none", "waiting": "", "outcome": ""}
                continue
            snapshot[key] = {
                "state": STATE_LABELS.get(str(case["state"]), str(case["state"])),
                "state_code": str(case["state"]),
                "waiting": str(case["waiting_for"] or ""),
                "outcome": OUTCOME_LABELS.get(str(case["outcome"] or ""), ""),
            }
        return snapshot

    # --- the report -----------------------------------------------------------------

    def _count(self, sql: str, *params) -> int:
        return int(self.conn.execute(sql, params).fetchone()[0])

    def finish(self) -> dict:
        sent = "SELECT COUNT(*) FROM agent_events WHERE kind = 'action' AND status = 'sent' AND code = ?"
        agent_messages = self._count(
            "SELECT COUNT(*) FROM agent_events WHERE kind = 'action' AND status = 'sent' "
            "AND code != 'coach_notified'"
        )
        coach_authorised = sum(1 for step in self.steps if step.get("authority") == "coach" and step.get("to_athlete"))
        outcomes = []
        for athlete in self.athletes.values():
            case = store.case_for_day(self.conn, athlete.athlete_id, self.day.isoformat())
            outcomes.append({
                "name": athlete.name,
                "outcome": OUTCOME_LABELS.get(str(case["outcome"] or ""), "") if case else "No training day opened",
                "state": STATE_LABELS.get(str(case["state"]), "") if case else "",
            })
        report = {
            "days_owned": self._count("SELECT COUNT(*) FROM agent_cases"),
            "days_closed": self._count("SELECT COUNT(*) FROM agent_cases WHERE state = 'closed'"),
            "checkins": self._count(sent, "checkin_sent"),
            "follow_ups": self._count(sent, "follow_up_sent"),
            "sessions_autonomous": sum(
                1 for step in self.steps
                if step.get("title") == ACTION_TITLES["session_delivered"] and step.get("authority") == "autonomous"
            ),
            "escalations": self._count("SELECT COUNT(*) FROM agent_events WHERE kind = 'escalation'"),
            "coach_decisions": self._count("SELECT COUNT(*) FROM agent_events WHERE kind = 'coach'"),
            "agent_messages": agent_messages,
            "autonomous_messages": agent_messages - coach_authorised,
            "coach_typed_messages": 0,
            "outcomes": outcomes,
        }
        athletes = [
            {
                "key": athlete.key, "name": athlete.name, "first": athlete.first,
                "plan": " · ".join(f"{lift.title()} {sets}×{reps} @ RPE {rpe:g}" for lift, sets, reps, rpe in athlete.plan),
                "autopilot": "Autopilot on" if athlete.autopilot else (
                    "Autopilot off" if athlete.autopilot is False else "Autopilot not decided"),
            }
            for athlete in self.athletes.values()
        ]
        self.conn.close()
        return {
            "day": f"{self.day:%A} (fictional)", "coach": self.coach_name, "timezone": self.timezone_name,
            "athletes": athletes, "steps": self.steps, "report": report,
        }


def _first_non_rest(options: list[list[str]]) -> str:
    return next((code for code, _ in options if code != "rest"), options[0][0])


@lru_cache(maxsize=1)
def public_demo() -> dict:
    """The landing page's demonstration: one routine day and one injury escalation."""
    simulation = Simulation(PUBLIC_DAY, coach_name=PUBLIC_COACH)
    simulation.add_athlete("priya", "Priya Nair", checkin="07:30", training="18:00",
                           plan=[("squat", 4, 5, 7.0), ("bench press", 3, 6, 7.0)], autopilot=True)
    simulation.add_athlete("arjun", "Arjun Mehta", checkin="07:30", training="18:00",
                           plan=[("deadlift", 3, 3, 7.5), ("bench press", 3, 5, 7.0)], autopilot=True)
    simulation.tick("07:30")
    simulation.say("priya", "slept 7.5h, readiness 8, soreness 3", "07:52")
    simulation.tick("09:01")
    simulation.say("arjun", "slept 6h, readiness 6. left knee pain on the stairs", "09:18")
    simulation.coach("arjun", "09:30", _first_non_rest)
    simulation.tick("20:31")
    simulation.say("priya", "squat 4x5 at 140kg rpe 7", "20:48")
    simulation.say("arjun", "done", "21:05")
    return simulation.finish()


def simulate_athlete(conn, athlete_id: str, *, now: datetime, coach_name: str) -> dict | None:
    """What the agent would do on this athlete's next planned day. Read-only on `conn`."""
    plan_rows = store.active_plan(conn, athlete_id)
    if not plan_rows:
        return None
    schedule = db.latest_schedule_settings(conn, athlete_id)
    settings_row = store.agent_settings(conn, athlete_id)
    timezone_name = str(schedule.get("timezone") or "UTC")
    checkin = str(settings_row["checkin_time"] or schedule.get("morning_checkin_time") or DEFAULT_CHECKIN_TIME)
    training = str(schedule.get("training_time") or DEFAULT_TRAINING_TIME)
    try:
        zone = ZoneInfo(timezone_name)
    except (ZoneInfoNotFoundError, ValueError):
        zone = ZoneInfo("UTC")
    today = now.astimezone(zone).date()
    weekdays = {int(row["weekday"]) for row in plan_rows}
    day = next(today + timedelta(days=offset) for offset in range(7)
               if (today + timedelta(days=offset)).weekday() in weekdays)
    lifts = [
        (str(row["lift"]), int(row["sets"]), int(row["reps"]), float(row["rpe"]))
        for row in plan_rows if int(row["weekday"]) == day.weekday()
    ]
    injured, note = db.injury_state(conn, athlete_id)
    autopilot = settings_row["autopilot"] if store.autopilot_decided(conn, athlete_id) else None
    name = db.athlete_name(conn, athlete_id) or "Athlete"

    simulation = Simulation(day, coach_name=coach_name, timezone_name=timezone_name)
    simulation.add_athlete("athlete", name, checkin=checkin, training=training, plan=lifts,
                           autopilot=autopilot, injury_note=note if injured else None)
    simulation.tick(checkin)
    simulation.say("athlete", "slept 8h, readiness 8, soreness 3", _plus(checkin, 25))
    simulation.coach(
        "athlete", _plus(checkin, 40),
        lambda options: "send" if any(code == "send" for code, _ in options) else "rest",
        simulated_by="Simulated here so the rest of the day can play out. For real, you decide.",
    )
    evening = _plus(training, 151)
    simulation.tick(evening)
    if simulation.case_state("athlete") not in {None, "closed", "needs_coach"}:
        simulation.say("athlete", "done", _plus(evening, 20))
    return simulation.finish()

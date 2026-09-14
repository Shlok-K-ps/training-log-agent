"""Plain answers about readiness: is this athlete set up, and what will the agent do next?

The coach should not have to understand cases, leases or schedules to know
whether the agent is working. Everything here is read from the same stored
state the agent itself uses, and mirrors the engine's own opening rules.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timedelta
from urllib.parse import quote

from app.casework import engine, policy, store
from app.casework.agent_view_labels import WEEKDAY_SHORT
from app.coach.demo import is_demo
from app.storage import db

WAITING_FOR_DECISION = "Today's training day is waiting for your decision."


@dataclass
class AthleteStatus:
    athlete_id: str
    name: str
    demo: bool
    telegram_connected: bool
    telegram_available: bool
    plan: list[str]
    plan_days: list[str]
    autopilot: bool
    autopilot_decided: bool
    injured: bool
    timezone: str
    checkin_time: str
    training_time: str
    next_action: str
    blockers: list[str] = field(default_factory=list)
    # The blockers that are simply unfinished setup steps (no Telegram, no plan).
    setup_gaps: list[str] = field(default_factory=list)
    notes: list[str] = field(default_factory=list)
    latest_case_id: int | None = None
    waiting_case_id: int | None = None

    @property
    def first_name(self) -> str:
        return self.name.split()[0] if self.name else "this athlete"

    @property
    def reachable(self) -> bool:
        return self.demo or self.telegram_connected

    @property
    def ready(self) -> bool:
        return bool(self.plan) and self.autopilot_decided and self.reachable and not self.blockers

    @property
    def url(self) -> str:
        return f"/coach/athlete/{quote(self.athlete_id)}"


def _clock(moment: datetime, zone) -> str:
    return moment.astimezone(zone).strftime("%H:%M")


def athlete_status(
    conn, athlete_id: str, now: datetime, *, telegram_available: bool, agent_blocker: str | None
) -> AthleteStatus:
    name = db.athlete_name(conn, athlete_id) or ""
    first = name.split()[0] if name else "this athlete"
    demo = is_demo(athlete_id)
    connected = db.telegram_chat_id(conn, athlete_id) is not None
    rows = store.active_plan(conn, athlete_id)
    plan = [
        f"{WEEKDAY_SHORT[int(r['weekday'])]} · {str(r['lift']).title()} {int(r['sets'])}×{int(r['reps'])} "
        f"@ RPE {float(r['rpe']):g}"
        for r in rows
    ]
    weekdays = sorted({int(r["weekday"]) for r in rows})
    agent_settings = store.agent_settings(conn, athlete_id)
    decided = store.autopilot_decided(conn, athlete_id)
    schedule = db.latest_schedule_settings(conn, athlete_id)
    zone_name = str(schedule.get("timezone") or "UTC")
    zone = engine._zone(zone_name)
    checkin = str(agent_settings["checkin_time"] or schedule.get("morning_checkin_time") or policy.DEFAULT_CHECKIN_TIME)
    training = str(schedule.get("training_time") or policy.DEFAULT_TRAINING_TIME)
    injured, _ = db.injury_state(conn, athlete_id)
    local_now = now.astimezone(zone)
    today = local_now.date().isoformat()
    open_case = store.open_case_for_day(conn, athlete_id, today)
    latest = store.recent_cases(conn, athlete_id, 1)

    status = AthleteStatus(
        athlete_id=athlete_id, name=name, demo=demo, telegram_connected=connected,
        telegram_available=telegram_available, plan=plan,
        plan_days=[WEEKDAY_SHORT[day] for day in weekdays], autopilot=bool(agent_settings["autopilot"]),
        autopilot_decided=decided, injured=injured, timezone=zone_name, checkin_time=checkin,
        training_time=training, next_action="",
        latest_case_id=int(latest[0]["id"]) if latest else None,
    )

    if agent_blocker:
        status.blockers.append(agent_blocker)
    if not status.reachable:
        if telegram_available:
            gap = f"Telegram is not connected, so the agent cannot message {first}."
            status.blockers.append(gap)
            status.setup_gaps.append(gap)
        else:
            status.blockers.append(
                "The Telegram bot is not configured on this deployment, so the agent cannot message real athletes."
            )
    if not plan:
        gap = f"No training plan yet, so the agent has no training days to run for {first}."
        status.blockers.append(gap)
        status.setup_gaps.append(gap)
    if open_case is not None and open_case["state"] == "needs_coach":
        status.waiting_case_id = int(open_case["id"])
        status.blockers.append(WAITING_FOR_DECISION)

    if plan and not decided:
        status.notes.append("Autopilot not decided yet: every session will wait for your approval.")
    elif plan and not status.autopilot:
        status.notes.append("Autopilot is off: every session waits for your approval.")
    if injured:
        status.notes.append("Injury open: the agent sends no training guidance until you decide.")

    setup_blockers = [b for b in status.blockers if b != WAITING_FOR_DECISION]
    if setup_blockers:
        status.next_action = (
            "Nothing until setup is finished."
            if setup_blockers == status.setup_gaps else
            "Nothing until the blockers are fixed."
        )
    elif open_case is not None:
        if open_case["state"] == "needs_coach":
            status.next_action = "Sends today's session once you decide."
        elif open_case["next_action_at"]:
            due = datetime.fromisoformat(str(open_case["next_action_at"]))
            status.next_action = (
                f"{open_case['waiting_for'] or engine.STATE_LABELS.get(str(open_case['state']), '')} · "
                f"next step at {_clock(due, zone)}"
            )
        else:
            status.next_action = "Working on today's training day."
    else:
        status.next_action = _next_training_day(conn, athlete_id, local_now, set(weekdays), checkin, training)
    return status


def _next_training_day(conn, athlete_id, local_now, weekdays, checkin, training) -> str:
    latest_opening = min(training, policy.LAST_CASE_OPENING.strftime("%H:%M"))
    for offset in range(8):
        day = local_now.date() + timedelta(days=offset)
        if day.weekday() not in weekdays:
            continue
        if offset == 0:
            if store.case_for_day(conn, athlete_id, day.isoformat()) is not None:
                continue
            if local_now.strftime("%H:%M") >= latest_opening:
                continue
            if local_now.strftime("%H:%M") >= checkin:
                return "Check-in on the agent's next run (within about 10 minutes)."
            return f"Check-in today at {checkin}."
        label = "tomorrow" if offset == 1 else f"on {day:%A} {day.day} {day:%B}"
        return f"Check-in {label} at {checkin}."
    return "No planned training day in the next week."


def next_setup_step(status: AthleteStatus) -> tuple[str, str]:
    if not status.reachable:
        return ("Send the Telegram invite", f"{status.url}#telegram")
    if not status.plan:
        return ("Create weekly plan", f"{status.url}#agent-plan")
    if not status.autopilot_decided:
        return ("Choose autopilot", f"{status.url}#autopilot")
    return ("Run a safe simulated test", f"{status.url}/simulate")


def setup_checklist(conn, now: datetime, *, telegram_available: bool, agent_blocker: str | None) -> list[dict]:
    """The six steps between an empty console and a working agent, detected automatically."""
    athletes = [a for a in db.list_athletes(conn) if not is_demo(a)]
    statuses = [
        athlete_status(conn, a, now, telegram_available=telegram_available, agent_blocker=agent_blocker)
        for a in athletes
    ]

    def first(predicate):
        return next((s for s in statuses if predicate(s)), None)

    add_url = "/coach/athletes/new"
    paired = first(lambda s: s.telegram_connected)
    planned = first(lambda s: s.plan)
    decided = first(lambda s: s.plan and s.autopilot_decided)
    ready = first(lambda s: s.ready)
    to_pair = first(lambda s: not s.telegram_connected)
    to_plan = first(lambda s: s.telegram_connected and not s.plan) or first(lambda s: not s.plan)
    to_decide = first(lambda s: s.plan and not s.autopilot_decided)
    to_ready = first(lambda s: not s.ready)
    coach_linked = store.coach_chat_id(conn) is not None

    return [
        {
            "key": "coach", "label": "Coach Telegram linked", "done": coach_linked,
            "detail": "Escalations reach your Telegram with one-tap decisions." if coach_linked
            else "Link your own Telegram so the agent can reach you when it needs a decision.",
            "href": "/coach/setup#coach-telegram", "action": "Link your Telegram",
        },
        {
            "key": "athlete", "label": "First athlete added", "done": bool(athletes),
            "detail": f"{len(athletes)} athlete{'s' if len(athletes) != 1 else ''} on your roster." if athletes
            else "Name, timezone and usual times. No IDs or phone numbers.",
            "href": add_url, "action": "Add an athlete",
        },
        {
            "key": "paired", "label": "Athlete Telegram paired", "done": paired is not None,
            "detail": f"{paired.first_name} is connected." if paired
            else "Send the athlete a one-tap Telegram invite.",
            "href": f"{to_pair.url}#telegram" if to_pair else add_url, "action": "Invite on Telegram",
        },
        {
            "key": "plan", "label": "Training plan added", "done": planned is not None,
            "detail": f"{planned.first_name}: {len(planned.plan)} planned lift{'s' if len(planned.plan) != 1 else ''}."
            if planned else "Sets, reps and target RPE for the days they train.",
            "href": f"{to_plan.url}#agent-plan" if to_plan else add_url, "action": "Add a training plan",
        },
        {
            "key": "autopilot", "label": "Autopilot decision made", "done": decided is not None,
            "detail": f"{decided.first_name}: autopilot {'on' if decided.autopilot else 'off'}." if decided
            else "Choose whether routine days go out without you.",
            "href": f"{to_decide.url}#autopilot" if to_decide else (f"{to_plan.url}#agent-plan" if to_plan else add_url),
            "action": "Decide on autopilot",
        },
        {
            "key": "ready", "label": "First training-day case ready", "done": ready is not None,
            "detail": f"{ready.first_name}: {ready.next_action}" if ready
            else (f"{to_ready.first_name}: {to_ready.blockers[0]}" if to_ready and to_ready.blockers
                  else "The agent opens a case on the first planned day."),
            "href": f"{to_ready.url}#agent-status" if to_ready else add_url, "action": "See what is blocking it",
        },
    ]

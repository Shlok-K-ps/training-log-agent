"""The training-day agent.

For every athlete with a coach-approved weekly plan, the agent opens a case on
each scheduled training day and owns it until the outcome is known. It sends
the check-in, follows up on silence, reads the reply, decides whether the day is
routine, delivers a pre-authorised session or escalates to the coach, asks
whether training happened, and closes the case only on evidence.

Every observation, decision, action, expectation and outcome is written to
`agent_events`. Each send is reserved under an idempotency key before it leaves,
so a crash or a restart can never deliver the same message twice.
"""

from __future__ import annotations

import json
import uuid
from dataclasses import dataclass
from datetime import date, datetime, timedelta, timezone
from typing import Callable, Sequence
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from app.agent.schemas import Action, LogCheckIn, LogSet, LogStatus, ReportSessionOutcome
from app.casework import messages, policy, store
from app.casework.adaptation import maybe_adapt_checkin_time
from app.casework.policy import PlannedLift
from app.casework.transport import DeliveryFailed, Transport
from app.config import settings
from app.decision.injury_pivot import injury_pivot_options, pivot_message
from app.decision.readiness import DailyCheckIn
from app.storage import db

# Test hook: runs after a message has left and before it is recorded as sent.
AFTER_SEND: Callable[[str], None] | None = None

STATE_LABELS = {
    "scheduled": "Check-in scheduled",
    "awaiting_checkin": "Waiting for check-in",
    "awaiting_outcome": "Waiting for session report",
    "needs_coach": "Needs your decision",
    "closed": "Closed",
}

OUTCOME_LABELS = {
    "completed": "Trained and logged",
    "completed_other_lifts": "Trained (other lifts logged)",
    "done": "Trained",
    "partial": "Partly trained",
    "skipped": "Skipped",
    "missed": "Missed (coach confirmed)",
    "rest_day": "Rest day (coach decision)",
    "no_response": "No check-in reply",
    "undelivered": "Could not be reached",
    "acknowledged": "Acknowledged by coach",
}

CHECKIN_FIELDS = (
    "sleep_hours", "sleep_quality", "readiness", "soreness", "stress",
    "bodyweight_kg", "protein_g", "calories", "nutrition_adherence",
)


@dataclass
class TickReport:
    opened: int = 0
    actions: int = 0
    closed: int = 0
    escalated: int = 0
    recovered: int = 0
    adaptations: int = 0
    skipped: bool = False

    def as_dict(self) -> dict[str, object]:
        return dict(self.__dict__)


# --- Helpers ----------------------------------------------------------------------


def _zone(name: str) -> ZoneInfo:
    try:
        return ZoneInfo(name)
    except (ZoneInfoNotFoundError, ValueError):
        return ZoneInfo("UTC")


def _local_moment(local_date: str, clock: str, tz_name: str) -> datetime:
    hour, minute = (int(piece) for piece in clock.split(":"))
    day = date.fromisoformat(local_date)
    return datetime(day.year, day.month, day.day, hour, minute, tzinfo=_zone(tz_name)).astimezone(
        timezone.utc
    )


def _local_clock(moment: datetime, tz_name: str) -> str:
    return moment.astimezone(_zone(tz_name)).strftime("%H:%M")


def _timing() -> policy.Timing:
    return policy.Timing().scaled(settings.agent_time_scale)


def _name(conn, athlete_id: str) -> str:
    return db.athlete_name(conn, athlete_id) or athlete_id


def _first_name(conn, athlete_id: str) -> str:
    name = db.athlete_name(conn, athlete_id)
    return name.split()[0] if name else "there"


def _plan(case) -> tuple[PlannedLift, ...]:
    return tuple(PlannedLift.from_dict(item) for item in store.loads(case["plan_json"]) or [])


def _session(case) -> tuple[PlannedLift, ...] | None:
    raw = store.loads(case["session_json"])
    return tuple(PlannedLift.from_dict(item) for item in raw) if isinstance(raw, list) else None


def _escalation(case) -> dict:
    return store.loads(case["escalation_json"]) or {}


def _fresh(conn, case):
    return store.case_by_id(conn, case["id"])


def _event(conn, case, kind: str, code: str, summary: str, now: datetime, detail=None) -> None:
    store.record_event(
        conn, case_id=int(case["id"]), athlete_id=str(case["athlete_id"]), kind=kind,
        code=code, summary=summary, detail=detail, now=now,
    )


def _plan_text(plan: Sequence[PlannedLift]) -> str:
    return "; ".join(item.describe() for item in plan)


def _session_summary(case) -> str:
    raw = store.loads(case["session_json"])
    if isinstance(raw, dict) and raw.get("pivot"):
        return "today's adjusted plan"
    lifts = _session(case) or _plan(case)
    return "today's " + " and ".join(item.lift for item in lifts) + " session"


# --- Waking up on the clock ---------------------------------------------------------


def tick(conn, *, now: datetime, transport: Transport, coach_name: str) -> TickReport:
    """Advance every training day whose next step is due. Safe to call repeatedly."""
    report = TickReport()
    holder = uuid.uuid4().hex
    if not store.acquire_lease(conn, "agent-tick", holder, now=now, ttl_seconds=120):
        report.skipped = True
        return report
    try:
        report.recovered = _recover_interrupted_sends(conn, now)
        _open_training_days(conn, now, report)
        for case in store.due_cases(conn, store.iso(now)):
            _advance(conn, case, now=now, transport=transport, coach_name=coach_name, report=report)
    finally:
        store.release_lease(conn, "agent-tick", holder)
    return report


def _recover_interrupted_sends(conn, now: datetime) -> int:
    rows = store.stale_reservations(conn, store.iso(now - timedelta(minutes=2)))
    for row in rows:
        store.finish_action(conn, str(row["idempotency_key"]), "unconfirmed")
        store.record_event(
            conn, case_id=row["case_id"], athlete_id=str(row["athlete_id"]), kind="observation",
            code="interrupted_send_found",
            summary=(
                "Found a send that was interrupted before it was confirmed. It is treated as "
                "sent so the athlete never receives it twice."
            ),
            detail={"action": row["code"], "key": row["idempotency_key"]}, now=now,
        )
    return len(rows)


def _open_training_days(conn, now: datetime, report: TickReport) -> None:
    for athlete_id in store.planned_athletes(conn):
        schedule = db.latest_schedule_settings(conn, athlete_id)
        tz_name = str(schedule.get("timezone") or "UTC")
        local_now = now.astimezone(_zone(tz_name))
        local_date = local_now.date().isoformat()
        if store.case_for_day(conn, athlete_id, local_date) is not None:
            continue
        plan = store.plan_for_weekday(conn, athlete_id, local_now.weekday())
        if not plan:
            continue
        base = str(schedule.get("morning_checkin_time") or policy.DEFAULT_CHECKIN_TIME)
        training = str(schedule.get("training_time") or policy.DEFAULT_TRAINING_TIME)
        # A morning check-in after training has started would only be noise.
        latest_opening = min(training, policy.LAST_CASE_OPENING.strftime("%H:%M"))
        if local_now.strftime("%H:%M") >= latest_opening:
            continue
        adaptation = maybe_adapt_checkin_time(
            conn, athlete_id, now=now, base_time=base, training_time=training,
            first_name=_first_name(conn, athlete_id),
        )
        checkin_time = store.agent_settings(conn, athlete_id)["checkin_time"] or base
        due = max(_local_moment(local_date, checkin_time, tz_name), now)
        case_id = store.create_case(
            conn, athlete_id=athlete_id, local_date=local_date, timezone_name=tz_name,
            checkin_time=checkin_time, training_time=training,
            plan=[item.as_dict() for item in plan], next_action_at=store.iso(due), now=now,
        )
        if case_id is None:
            continue
        case = store.case_by_id(conn, case_id)
        report.opened += 1
        _event(
            conn, case, "observation", "training_day_found",
            f"{local_now:%A} is a training day in the coach-approved plan: {_plan_text(plan)}.",
            now, {"plan": [item.as_dict() for item in plan]},
        )
        if adaptation is not None:
            report.adaptations += 1
            _event(conn, case, "adaptation", "checkin_time_adapted", str(adaptation["explanation"]),
                   now, adaptation)
        _event(
            conn, case, "decision", "checkin_scheduled",
            f"Check-in scheduled for {checkin_time} ({tz_name}).", now, {"due_at": store.iso(due)},
        )


def _advance(conn, case, *, now, transport, coach_name, report) -> None:
    state = case["state"]
    timing = _timing()
    first = _first_name(conn, case["athlete_id"])
    tz_name = str(case["timezone"])

    if state == "scheduled":
        body = messages.checkin(first, date.fromisoformat(case["local_date"]), _plan(case))
        if _send(conn, case, step="checkin", code="checkin_sent", body=body,
                 summary="Sent the morning check-in.", now=now, transport=transport,
                 coach_name=coach_name, report=report):
            follow_at = now + timedelta(minutes=timing.first_follow_up)
            if store.update_case(
                conn, case, now=now, state="awaiting_checkin",
                waiting_for="Athlete check-in (sleep and readiness)",
                next_action_at=store.iso(follow_at),
                checkin_sent_at=case["checkin_sent_at"] or store.iso(now),
            ):
                _event(conn, case, "expectation", "checkin_reply_expected",
                       f"Expect a check-in reply. If none arrives, follow up at "
                       f"{_local_clock(follow_at, tz_name)}.", now, {"by": store.iso(follow_at)})
        return

    if state == "awaiting_checkin":
        sent_at = datetime.fromisoformat(case["checkin_sent_at"]) if case["checkin_sent_at"] else now
        window_end = sent_at + timedelta(minutes=timing.checkin_window)
        number = int(case["follow_ups"]) + 1
        if number <= policy.MAX_CHECKIN_FOLLOW_UPS and now < window_end:
            body = messages.follow_up(first, number, _local_clock(window_end, tz_name))
            if _send(conn, case, step=f"follow_up:{number}", code="follow_up_sent", body=body,
                     summary=f"No check-in yet, so sent follow-up {number} of "
                             f"{policy.MAX_CHECKIN_FOLLOW_UPS}.",
                     now=now, transport=transport, coach_name=coach_name, report=report):
                next_at = (
                    now + timedelta(minutes=timing.second_follow_up) if number == 1 else window_end
                )
                next_at = min(next_at, window_end)
                if store.update_case(conn, case, now=now, follow_ups=number,
                                     next_action_at=store.iso(next_at)):
                    _event(conn, case, "expectation", "checkin_reply_expected",
                           f"Still expecting a check-in; next step at {_local_clock(next_at, tz_name)}.",
                           now, {"by": store.iso(next_at)})
        else:
            _close_without_checkin(conn, case, now=now, transport=transport,
                                   coach_name=coach_name, report=report)
        return

    if state == "awaiting_outcome":
        prompts = int(case["outcome_prompts"])
        if prompts >= 2:
            _escalate(
                conn, case, "no_session_report", now=now, transport=transport,
                coach_name=coach_name, report=report,
                evidence=[
                    f"Session delivered: {_session_summary(case)}.",
                    "Asked twice whether training happened; no answer yet.",
                ],
            )
            return
        if prompts == 0:
            body = messages.outcome_question(first, _session_summary(case))
            step, summary, wait = "outcome_question", "Asked whether today's session happened.", timing.outcome_reminder
        else:
            body = messages.outcome_reminder(first)
            step, summary, wait = "outcome_reminder", "No session report yet, so sent one reminder.", timing.outcome_escalation
        if _send(conn, case, step=step, code=f"{step}_sent", body=body, summary=summary, now=now,
                 transport=transport, coach_name=coach_name, report=report):
            next_at = now + timedelta(minutes=wait)
            if store.update_case(conn, case, now=now, outcome_prompts=prompts + 1,
                                 waiting_for="Athlete's session report",
                                 next_action_at=store.iso(next_at)):
                _event(conn, case, "expectation", "session_report_expected",
                       f"Expect a session report; next step at {_local_clock(next_at, tz_name)}.",
                       now, {"by": store.iso(next_at)})


def _send(conn, case, *, step, code, body, summary, now, transport, coach_name, report) -> bool:
    """Deliver one athlete message at most once. True when the step can be treated as done."""
    key = f"case:{case['id']}:{step}"
    status = store.reserve_action(
        conn, case_id=int(case["id"]), athlete_id=str(case["athlete_id"]), key=key, code=code,
        summary=summary, detail={"message": body}, now=now,
    )
    if status != "new":
        return status in {"reserved", "sent", "unconfirmed"}
    try:
        provider_id = transport.send_athlete(conn, str(case["athlete_id"]), body, kind=code)
    except DeliveryFailed as exc:
        store.finish_action(conn, key, "failed", note=str(exc))
        _escalate(
            conn, _fresh(conn, case), "delivery_failed", now=now, transport=transport,
            coach_name=coach_name, report=report,
            evidence=[str(exc), f"Could not complete: {summary}"], extra={"outcome": "undelivered"},
        )
        return False
    if AFTER_SEND is not None:
        AFTER_SEND(key)
    store.finish_action(conn, key, "sent", note=provider_id)
    report.actions += 1
    return True


def _close(conn, case, *, outcome: str, summary: str, now: datetime, report, detail=None) -> None:
    fresh = _fresh(conn, case)
    if fresh is None or fresh["state"] == "closed":
        return
    if store.update_case(conn, fresh, now=now, state="closed", outcome=outcome, waiting_for=None,
                         next_action_at=None, closed_at=store.iso(now)):
        _event(conn, fresh, "outcome", outcome, summary, now, detail)
        if report is not None:
            report.closed += 1


def _escalate(conn, case, code, *, now, transport, coach_name, report, evidence,
              proposal=None, light=None, extra=None) -> None:
    athlete_id = str(case["athlete_id"])
    _, injury_note = db.injury_state(conn, athlete_id)
    options = policy.coach_options(code, injury_note=injury_note)
    title = policy.ESCALATION_TITLES[code]
    payload = {
        "code": code, "title": title, "evidence": list(evidence),
        "options": [list(option) for option in options],
        "proposal": proposal, "light": light, **(extra or {}),
    }
    fresh = _fresh(conn, case)
    fields = {
        "state": "needs_coach", "waiting_for": f"Your decision: {title}", "next_action_at": None,
        "escalation_json": json.dumps(payload, sort_keys=True),
    }
    if extra and extra.get("outcome"):
        fields["outcome"] = extra["outcome"]
    if not store.update_case(conn, fresh, now=now, **fields):
        return
    _event(conn, fresh, "escalation", code, f"Escalated to the coach: {title}.", now, payload)
    if report is not None:
        report.escalated += 1
    key = f"case:{case['id']}:notify:{code}"
    if store.reserve_action(
        conn, case_id=int(case["id"]), athlete_id=athlete_id, key=key, code="coach_notified",
        summary="Sent the escalation to the coach's Telegram with decision buttons.",
        detail={"title": title}, now=now,
    ) != "new":
        return
    try:
        provider_id = transport.notify_coach(
            conn, case_id=int(case["id"]), athlete_name=_name(conn, athlete_id),
            local_date=str(case["local_date"]), title=title, evidence=list(evidence), options=options,
        )
    except DeliveryFailed as exc:
        store.finish_action(conn, key, "failed", note=str(exc))
        return
    if provider_id:
        store.finish_action(conn, key, "sent", note=provider_id)
    else:
        store.finish_action(conn, key, "skipped",
                            note="No coach Telegram chat is linked; the decision waits in the console.")


def _close_without_checkin(conn, case, *, now, transport, coach_name, report) -> None:
    streak = policy.SILENT_STREAK_DAYS - 1
    previous = store.previous_outcomes(conn, str(case["athlete_id"]), str(case["local_date"]), streak)
    evidence = [
        f"No check-in reply on {case['local_date']} after the check-in and "
        f"{case['follow_ups']} follow-ups."
    ]
    if streak and len(previous) == streak and all(outcome == "no_response" for outcome in previous):
        evidence.append(f"No reply on the previous {streak} training day(s) either.")
        _escalate(conn, case, "silent_streak", now=now, transport=transport, coach_name=coach_name,
                  report=report, evidence=evidence, extra={"outcome": "no_response"})
        return
    _close(conn, case, outcome="no_response",
           summary=evidence[0] + " No session guidance was sent today.", now=now, report=report)


# --- Waking up on an athlete message ------------------------------------------------


def local_today(conn, athlete_id: str, now: datetime) -> date:
    """The athlete's own calendar date, so "today" in a message means their day."""
    schedule = db.latest_schedule_settings(conn, athlete_id)
    return now.astimezone(_zone(str(schedule.get("timezone") or "UTC"))).date()


def observe_message(
    conn, athlete_id: str, actions: Sequence[Action], *, raw_text: str, now: datetime,
    transport: Transport, coach_name: str,
) -> bool:
    """Fold a validated athlete message into today's case. True if the agent replied."""
    schedule = db.latest_schedule_settings(conn, athlete_id)
    local_date = now.astimezone(_zone(str(schedule.get("timezone") or "UTC"))).date().isoformat()
    case = store.open_case_for_day(conn, athlete_id, local_date)
    if case is None:
        return False
    report = TickReport()
    excerpt = " ".join((raw_text or "").split())[:160]
    _event(conn, case, "observation", "athlete_message", f"Athlete wrote: “{excerpt}”", now,
           {"parsed_as": [type(action).__name__ for action in actions]})

    injury = next((a for a in actions if isinstance(a, LogStatus) and a.injured), None)
    if injury is not None:
        return _handle_injury(conn, case, injury, now=now, transport=transport,
                              coach_name=coach_name, report=report)

    state = case["state"]
    if state == "needs_coach" and _escalation(case).get("code") != "no_session_report":
        _event(conn, case, "observation", "awaiting_coach",
               "A coach decision is pending, so the message is added to the case evidence only.", now)
        return False

    sets = [a for a in actions if isinstance(a, LogSet) and a.session_date == local_date]
    outcome = next(
        (a for a in actions if isinstance(a, ReportSessionOutcome) and a.session_date == local_date),
        None,
    )
    checkin = next(
        (a for a in actions if isinstance(a, LogCheckIn) and a.checked_on == local_date), None
    )
    if sets:
        return _handle_session_log(conn, case, sets, now=now, transport=transport,
                                   coach_name=coach_name, report=report)
    if outcome is not None and state in {"awaiting_outcome", "needs_coach", "awaiting_checkin", "scheduled"}:
        return _handle_outcome(conn, case, outcome, now=now, transport=transport,
                               coach_name=coach_name, report=report)
    if checkin is not None and state in {"scheduled", "awaiting_checkin"}:
        return _handle_checkin(conn, case, checkin, now=now, transport=transport,
                               coach_name=coach_name, report=report)
    return False


def _handle_injury(conn, case, injury: LogStatus, *, now, transport, coach_name, report) -> bool:
    if _escalation(case).get("code") == "injury_open":
        _event(conn, case, "observation", "injury_update",
               "Further injury detail added to the pending decision.", now, {"note": injury.injury_note})
        return False
    session_sent = case["state"] == "awaiting_outcome" and case["session_json"] is not None
    note = injury.injury_note or "pain or injury reported"
    _event(conn, case, "decision", "guidance_stopped",
           "Injury reported: autonomous training guidance stops until the coach decides.", now,
           {"note": note, "session_already_sent": session_sent})
    _send(conn, case, step="injury_hold", code="guidance_paused",
          body=messages.injury_hold(_first_name(conn, case["athlete_id"]), session_sent),
          summary="Told the athlete guidance is paused and the coach has been alerted.",
          now=now, transport=transport, coach_name=coach_name, report=report)
    evidence = [f"Athlete reported: “{note}”."]
    evidence.append(
        "A session had already been sent today; the athlete was told not to train it."
        if session_sent else "No session had been sent today."
    )
    _escalate(conn, _fresh(conn, case), "injury_open", now=now, transport=transport,
              coach_name=coach_name, report=report, evidence=evidence)
    return True


def _handle_checkin(conn, case, checkin: LogCheckIn, *, now, transport, coach_name, report) -> bool:
    athlete_id = str(case["athlete_id"])
    first = _first_name(conn, athlete_id)
    stored = (store.loads(case["readiness_json"]) or {}).get("checkin", {})
    values = dict(stored)
    for name in CHECKIN_FIELDS:
        value = getattr(checkin, name, None)
        if value is not None:
            values[name] = value
    merged = DailyCheckIn(checked_on=str(case["local_date"]), **values)
    updates = {"readiness_json": json.dumps({"checkin": values}, sort_keys=True)}
    if case["checkin_received_at"] is None:
        updates["checkin_received_at"] = store.iso(now)

    missing = policy.missing_fields(merged)
    if missing and not case["clarified"]:
        if store.update_case(conn, case, now=now, clarified=1, **updates):
            fresh = _fresh(conn, case)
            _event(conn, fresh, "decision", "checkin_incomplete",
                   f"Check-in is missing {' and '.join(missing)}; asking once before deciding.", now,
                   {"received": values})
            _send(conn, fresh, step="clarify", code="clarification_sent",
                  body=messages.clarify_missing(first, missing),
                  summary="Asked for the missing check-in values.", now=now, transport=transport,
                  coach_name=coach_name, report=report)
        return True

    injured, injury_note = db.injury_state(conn, athlete_id)
    autopilot = bool(store.agent_settings(conn, athlete_id)["autopilot"])
    plan = _plan(case)
    result = policy.triage(plan, merged, injured=injured, autopilot=autopilot)
    if not store.update_case(conn, case, now=now, **updates):
        return False
    case = _fresh(conn, case)
    readiness = result.readiness
    band = readiness.band.value
    title = policy.ESCALATION_TITLES.get(result.escalation or "", "")
    _event(
        conn, case, "decision", "checkin_assessed",
        f"Readiness {readiness.score}/100 ({band}). "
        + ("Routine day within autopilot authority." if result.routine else f"Not routine: {title}."),
        now,
        {
            "score": readiness.score, "band": band, "reasons": list(readiness.reasons),
            "plan": [item.as_dict() for item in plan],
            "session": [item.as_dict() for item in result.session],
            "changes": list(result.changes), "routine": result.routine,
            "escalation": result.escalation, "missing": list(missing),
            "rule": "The session may be held or reduced, never increased.",
        },
    )

    if result.routine:
        body = messages.session(first, result.session, plan, readiness, result.changes, coach=coach_name)
        if _send(conn, case, step="session", code="session_delivered", body=body,
                 summary="Delivered today's session within the coach-approved plan (hold or reduce only).",
                 now=now, transport=transport, coach_name=coach_name, report=report):
            _await_outcome(conn, case, session=[item.as_dict() for item in result.session], now=now)
        return True

    _send(conn, case, step="awaiting_coach", code="coach_review_notice",
          body=messages.awaiting_coach(first),
          summary="Told the athlete the coach is reviewing today's session.",
          now=now, transport=transport, coach_name=coach_name, report=report)
    evidence = [f"Readiness {readiness.score}/100 ({band}).", *readiness.reasons[:3],
                f"Planned: {_plan_text(plan)}."]
    if injured:
        evidence.insert(0, f"Injury flag is open: {injury_note or 'no detail recorded'}.")
    if result.escalation == "autopilot_off":
        evidence.append("Autopilot is off for this athlete, so every session needs your approval.")
    session_dicts = [item.as_dict() for item in result.session]
    _escalate(
        conn, _fresh(conn, case), result.escalation, now=now, transport=transport,
        coach_name=coach_name, report=report, evidence=evidence,
        proposal=session_dicts if result.escalation == "autopilot_off" else None,
        light=session_dicts if result.escalation == "readiness_red" else None,
    )
    return True


def _await_outcome(conn, case, *, session, now: datetime) -> None:
    timing = _timing()
    training_at = _local_moment(str(case["local_date"]), str(case["training_time"]), str(case["timezone"]))
    ask_at = training_at + timedelta(minutes=timing.outcome_question_after_training)
    if ask_at <= now:
        ask_at = now + timedelta(minutes=max(1.0, 30 * settings.agent_time_scale))
    fresh = _fresh(conn, case)
    if store.update_case(
        conn, fresh, now=now, state="awaiting_outcome", session_json=json.dumps(session, sort_keys=True),
        waiting_for="Athlete's session report", next_action_at=store.iso(ask_at),
        outcome_prompts=0, escalation_json=None,
    ):
        _event(conn, fresh, "expectation", "session_report_expected",
               f"Expect a session report after training; ask at "
               f"{_local_clock(ask_at, str(case['timezone']))} if none arrives.",
               now, {"by": store.iso(ask_at)})


def _handle_session_log(conn, case, sets: list[LogSet], *, now, transport, coach_name, report) -> bool:
    planned = {item.lift for item in _plan(case)}
    parts = []
    for item in sets:
        shape = f"{item.sets}×{item.reps} " if item.sets and item.reps else ""
        load = f"@ {item.weight_kg:g} kg" if item.weight_kg is not None else ""
        effort = f" RPE {item.rpe:g}" if item.rpe is not None else ""
        parts.append(f"{item.lift} {shape}{load}{effort}".strip())
    logged = "; ".join(parts)
    matched = any(item.lift in planned for item in sets)
    _event(conn, case, "observation", "session_logged", f"Athlete logged: {logged}.", now,
           {"planned_lifts": sorted(planned), "matched_plan": matched})
    _send(conn, case, step="log_confirmation", code="log_confirmed",
          body=messages.log_confirmation(_first_name(conn, case["athlete_id"]), logged),
          summary="Confirmed the logged session to the athlete.", now=now, transport=transport,
          coach_name=coach_name, report=report)
    before_checkin = case["state"] in {"scheduled", "awaiting_checkin"}
    summary = (
        f"Outcome known: the athlete trained and logged {logged}"
        + (" before checking in, so no session guidance was needed." if before_checkin else ".")
    )
    _close(conn, case, outcome="completed" if matched else "completed_other_lifts",
           summary=summary, now=now, report=report, detail={"logged": logged})
    return True


def _handle_outcome(conn, case, outcome: ReportSessionOutcome, *, now, transport, coach_name, report) -> bool:
    note = f" Reason given: “{outcome.note}”." if outcome.note else ""
    _send(conn, case, step="outcome_ack", code="outcome_acknowledged",
          body=messages.outcome_ack(_first_name(conn, case["athlete_id"]), outcome.status),
          summary="Acknowledged the athlete's session report.", now=now, transport=transport,
          coach_name=coach_name, report=report)
    _close(conn, case, outcome=outcome.status,
           summary=f"Outcome known: athlete reported the session as {outcome.status}.{note}",
           now=now, report=report, detail={"status": outcome.status, "note": outcome.note})
    return True


# --- Waking up on a coach decision --------------------------------------------------


def apply_coach_decision(
    conn, case_id: int, option: str, *, coach_name: str, now: datetime, transport: Transport,
) -> tuple[bool, str]:
    """Carry out one decision on an escalated case, then let the agent continue."""
    case = store.case_by_id(conn, case_id)
    if case is None:
        return False, "That case does not exist."
    if case["state"] != "needs_coach":
        return False, "This case has already been decided."
    escalation = _escalation(case)
    options = {code: label for code, label in escalation.get("options", [])}
    if option not in options:
        return False, "That option is not available for this case."
    report = TickReport()
    athlete_id = str(case["athlete_id"])
    first = _first_name(conn, athlete_id)
    code = escalation.get("code")
    _event(conn, case, "coach", f"coach_{option}", f"{coach_name} chose “{options[option]}”.", now,
           {"option": option, "escalation": code})

    if option == "rest":
        _send(conn, case, step="coach:rest", code="rest_day_sent", body=messages.rest_day(first, coach_name),
              summary="Told the athlete today is a rest day.", now=now, transport=transport,
              coach_name=coach_name, report=report)
        _close(conn, case, outcome="rest_day", summary=f"{coach_name} made today a rest day.", now=now,
               report=report)
        return True, f"Rest day sent to {first}."

    if option in {"send", "light"}:
        raw = escalation.get("proposal" if option == "send" else "light") or []
        session = tuple(PlannedLift.from_dict(item) for item in raw)
        plan = _plan(case)
        if not session or not policy.never_increases(plan, session):
            return False, "The proposed session is no longer valid."
        checkin_values = (store.loads(case["readiness_json"]) or {}).get("checkin", {})
        readiness = policy.evaluate_readiness(DailyCheckIn(checked_on=str(case["local_date"]), **checkin_values))
        _, changes = policy.adjust_for_band(plan, readiness.band)
        body = messages.session(first, session, plan, readiness, changes, coach=coach_name,
                                confirmed_by_coach=True)
        if _send(conn, case, step=f"coach:{option}", code="session_delivered", body=body,
                 summary=f"Delivered the session {coach_name} approved.", now=now, transport=transport,
                 coach_name=coach_name, report=report):
            _await_outcome(conn, case, session=[item.as_dict() for item in session], now=now)
        return True, f"Session sent to {first}."

    if code == "injury_open":
        _, note = db.injury_state(conn, athlete_id)
        pivot = next((item for item in injury_pivot_options(note) if item.code == option), None)
        entry_id = db.open_injury_entry_id(conn, athlete_id)
        if pivot is None or entry_id is None:
            return False, "The injury has changed; review the case again."
        db.record_injury_plan_decision(
            conn, athlete_id=athlete_id, injury_entry_id=entry_id, option_code=pivot.code,
            plan_text=pivot.plan, approved_by=coach_name,
        )
        if _send(conn, case, step="coach:pivot", code="injury_plan_sent",
                 body=pivot_message(pivot, coach=coach_name),
                 summary=f"Sent {coach_name}'s injury plan: {pivot.title}.", now=now,
                 transport=transport, coach_name=coach_name, report=report):
            _await_outcome(conn, case, session={"pivot": pivot.code, "title": pivot.title}, now=now)
        return True, f"“{pivot.title}” sent to {first}. The injury flag stays open."

    if option in {"done", "missed"}:
        _close(conn, case, outcome="done" if option == "done" else "missed",
               summary=f"{coach_name} confirmed the session was {'trained' if option == 'done' else 'missed'}.",
               now=now, report=report)
        return True, "Case closed."

    outcome = escalation.get("outcome") or "acknowledged"
    _close(conn, case, outcome=outcome, summary=f"{coach_name} acknowledged: {escalation.get('title')}.",
           now=now, report=report)
    return True, "Case closed."

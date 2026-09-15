"""Every message the agent sends, as fixed templates.

The agent chooses *which* message to send; it never writes free prose. Numbers
that appear here come from the coach's plan, the readiness rules, or the
athlete's own validated log, never from the language model.
"""

from __future__ import annotations

from datetime import date

from app.casework.policy import PlannedLift
from app.decision.readiness import ReadinessAssessment


def _lines(session: tuple[PlannedLift, ...]) -> str:
    return "\n".join(f"• {item.describe()}" for item in session)


def checkin(first_name: str, day: date, plan: tuple[PlannedLift, ...]) -> str:
    lifts = ", ".join(item.lift for item in plan)
    return (
        f"Morning {first_name}! {day:%A} is a training day ({lifts}). Before I send today's "
        "session, reply with hours slept and readiness 1–10 (soreness and stress help too).\n"
        "e.g. slept 7h, readiness 8, soreness 3"
    )


def follow_up(first_name: str, number: int, cutoff: str) -> str:
    if number == 1:
        return (
            f"Quick nudge {first_name}: I still need your check-in (hours slept and readiness 1–10) "
            "before I can send today's session."
        )
    return (
        f"Last check for today, {first_name}. Without a check-in by {cutoff} I won't send session "
        "guidance today."
    )


def clarify_missing(first_name: str, missing: tuple[str, ...]) -> str:
    return f"Thanks {first_name}. I'm missing {' and '.join(missing)}. Can you send that?"


def session(
    first_name: str,
    today: tuple[PlannedLift, ...],
    plan: tuple[PlannedLift, ...],
    readiness: ReadinessAssessment,
    changes: tuple[str, ...],
    *,
    coach: str,
    confirmed_by_coach: bool = False,
) -> str:
    source = f"confirmed by {coach}" if confirmed_by_coach else f"from {coach}'s approved plan"
    reduced = today != plan
    why = (
        f"Readiness {readiness.score}/100 ({readiness.band.value}). {changes[0]}"
        if changes else f"Readiness {readiness.score}/100 ({readiness.band.value})."
    )
    return (
        f"{first_name}, today's session ({source}):\n{_lines(today)}\n"
        + (f"Planned was:\n{_lines(plan)}\n" if reduced else "")
        + f"{why}\nKeep every set at or under its RPE target. After training, reply with how it "
        "went, e.g. done, top set 140 rpe 7"
    )


def awaiting_coach(first_name: str) -> str:
    return (
        f"Thanks {first_name}, check-in received. Your coach is reviewing today's session and "
        "I'll message you as soon as it's confirmed."
    )


def injury_hold(first_name: str, session_already_sent: bool) -> str:
    hold = (
        " Please don't train the session I sent earlier; disregard and hold that workout until your coach replies."
        if session_already_sent else ""
    )
    return (
        f"Thanks for telling me, {first_name}. I've paused all training guidance and alerted "
        f"your coach.{hold} If the pain is severe or getting worse, get it checked by a "
        "qualified professional."
    )


def outcome_question(first_name: str, summary: str) -> str:
    return (
        f"How did today go, {first_name}? Did {summary} happen? Reply done (with your top set "
        "if you have it) or skipped."
    )


def outcome_reminder(first_name: str) -> str:
    return (
        f"Still need today's result, {first_name}: reply done or skipped so I can close the day."
    )


def log_confirmation(first_name: str, logged: str) -> str:
    return f"Logged, {first_name}: {logged}. That closes today. Good work."


def outcome_ack(first_name: str, status: str) -> str:
    if status == "done":
        return f"Nice, {first_name}. Today is marked as done."
    if status == "partial":
        return f"Thanks {first_name}. Today is marked as partly done."
    return f"Thanks for letting me know, {first_name}. Today is marked as skipped."


def rest_day(first_name: str, coach: str) -> str:
    return f"{first_name}, {coach} has made today a rest day. No training today. Recover well."


def coach_escalation(
    athlete_name: str, local_date: str, title: str, evidence: list[str]
) -> str:
    facts = "\n".join(f"• {line}" for line in evidence)
    return f"Power AI needs a decision: {title}\n{athlete_name} · {local_date}\n{facts}"

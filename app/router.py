"""The seam between the three layers.

Nothing here decides anything and nothing here talks to a model. It takes the
validated actions from Layer 1, writes them through Layer 2, asks Layer 3 for a
verdict, and stitches the templated reply together.
"""

from __future__ import annotations

import sqlite3
from datetime import date

from app.agent.parser import ModelClient, parse_message
from app.agent.schemas import Action, Clarify, LogSet, LogStatus, QueryProgress
from app.decision.format import format_assessment, format_logged, format_status
from app.decision.rules import evaluate
from app.storage import db

MAX_VERDICTS_PER_REPLY = 3

FALLBACK = (
    "I couldn't turn that into a training entry. Try something like:\n"
    "  _squat 3x5 at 140kg, RPE 8_\n"
    "  _bench felt heavy today, 3x5 100kg rpe 9_\n"
    "  _am I stalling on deadlift?_"
)

HELP = (
    "*Training log*\n"
    "Send me your sessions in plain English and I'll track every lift.\n\n"
    "• _squat 3x5 @ 140kg rpe 8_  — logs a session\n"
    "• _bench 3x5 225lb yesterday_  — pounds and dates both work\n"
    "• _am I stalling on squat?_  — verdict from your history\n"
    "• _i'm on a cut now_  — flat weight in a cut counts as holding\n"
    "• _tweaked my left knee_  — flags an injury; I stop suggesting loads\n"
    "• _how's my bench going?_  — progressing, stalled, or deload\n\n"
    "Verdicts come from fixed rules over your own log, not from a chatbot's opinion."
)


def handle_message(
    conn: sqlite3.Connection,
    athlete_id: str,
    text: str,
    client: ModelClient,
    *,
    today: date | None = None,
) -> str:
    """One inbound WhatsApp message in, one reply out."""
    today = today or date.today()
    text = (text or "").strip()

    if not text:
        return FALLBACK
    if text.lower() in {"help", "/help", "?", "start", "hi", "hello"}:
        return HELP

    known = db.list_lifts(conn, athlete_id)
    parsed = parse_message(text, client, today=today, known_lifts=known)

    if not parsed.actions:
        if parsed.rejected:
            return FALLBACK + "\n\n_(rejected: " + parsed.rejected[0] + ")_"
        return FALLBACK

    return _apply(conn, athlete_id, text, parsed.actions, today)


def _apply(
    conn: sqlite3.Connection,
    athlete_id: str,
    raw_text: str,
    actions: list[Action],
    today: date,
) -> str:
    name = db.athlete_name(conn, athlete_id)
    confirmations: list[str] = []
    questions: list[str] = []
    lifts_to_assess: list[str] = []
    assess_all = False

    for action in actions:
        if isinstance(action, LogSet):
            db.insert_entry(
                conn,
                db.Entry(
                    athlete_id=athlete_id,
                    athlete_name=name,
                    kind="set",
                    lift=action.lift,
                    sets=action.sets,
                    reps=action.reps,
                    weight_kg=action.weight_kg,
                    rpe=action.rpe,
                    phase=action.phase,
                    session_date=action.session_date,
                    raw_text=raw_text,
                ),
            )
            confirmations.append(
                format_logged(
                    action.lift,
                    action.sets,
                    action.reps,
                    action.weight_kg,
                    action.rpe,
                    action.session_date,
                )
            )
            if action.lift not in lifts_to_assess:
                lifts_to_assess.append(action.lift)

        elif isinstance(action, LogStatus):
            if action.athlete_name:
                name = action.athlete_name
            db.insert_entry(
                conn,
                db.Entry(
                    athlete_id=athlete_id,
                    athlete_name=name,
                    kind="status",
                    phase=action.phase,
                    injured=action.injured,
                    injury_note=action.injury_note,
                    session_date=today.isoformat(),
                    raw_text=raw_text,
                ),
            )
            if action.phase or action.injured is not None:
                confirmations.append(
                    format_status(action.phase, action.injured, action.injury_note)
                )
            elif action.athlete_name:
                confirmations.append(f"✅ Got it, {action.athlete_name}.")

        elif isinstance(action, QueryProgress):
            if action.lift:
                if action.lift not in lifts_to_assess:
                    lifts_to_assess.append(action.lift)
            else:
                assess_all = True

        elif isinstance(action, Clarify):
            questions.append(f"❓ {action.question}")

    if assess_all:
        for lift in db.list_lifts(conn, athlete_id):
            if lift not in lifts_to_assess:
                lifts_to_assess.append(lift)

    phase = db.latest_phase(conn, athlete_id)
    injured, injury_note = db.injury_state(conn, athlete_id)

    verdicts: list[str] = []
    for lift in lifts_to_assess[:MAX_VERDICTS_PER_REPLY]:
        history = db.session_history(conn, athlete_id, lift)
        assessment = evaluate(
            athlete_id,
            lift,
            history,
            phase=phase,
            injured=injured,
            injury_note=injury_note,
        )
        verdicts.append(format_assessment(assessment, athlete_name=None))

    blocks = [b for b in ["\n".join(confirmations), "\n\n".join(verdicts), "\n".join(questions)] if b]
    return "\n\n".join(blocks) if blocks else FALLBACK

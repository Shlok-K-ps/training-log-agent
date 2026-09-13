"""Durable memory for the training-day agent: plans, cases, events and adaptations.

A stateful agent is only as trustworthy as what it remembers after a restart,
so everything it knows about a training day lives in these tables rather than
in process memory. Every write commits immediately.
"""

from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone
from typing import Any

from app.casework.policy import PlannedLift
from app.storage.lifts import normalize_lift

OPEN_STATES = ("scheduled", "awaiting_checkin", "awaiting_outcome", "needs_coach")
TIMED_STATES = ("scheduled", "awaiting_checkin", "awaiting_outcome")
EVENT_KINDS = (
    "observation", "decision", "action", "expectation", "outcome",
    "escalation", "adaptation", "coach",
)
_CASE_FIELDS = frozenset({
    "state", "waiting_for", "next_action_at", "follow_ups", "outcome_prompts",
    "clarified", "session_json", "readiness_json", "escalation_json", "outcome",
    "checkin_sent_at", "checkin_received_at", "closed_at",
})


def iso(moment: datetime) -> str:
    return moment.astimezone(timezone.utc).isoformat(timespec="seconds")


def loads(value: str | None) -> Any:
    return json.loads(value) if value else None


def _dumps(value: Any) -> str | None:
    return None if value is None else json.dumps(value, sort_keys=True)


def _in(values: tuple[str, ...]) -> str:
    return ", ".join("?" for _ in values)


# --- Coach-approved weekly plans ------------------------------------------------


def add_plan_session(
    conn, *, athlete_id: str, weekday: int, lift: str, sets: int, reps: int,
    rpe: float, approved_by: str, now: datetime,
) -> int:
    """Approve one lift for one weekday, replacing any earlier version of it."""
    name = normalize_lift(lift)
    if not name:
        raise ValueError("a planned lift needs a name")
    if not 0 <= int(weekday) <= 6:
        raise ValueError("weekday must be between Monday and Sunday")
    if not 1 <= int(sets) <= 20:
        raise ValueError("sets must be between 1 and 20")
    if not 1 <= int(reps) <= 30:
        raise ValueError("reps must be between 1 and 30")
    target = float(rpe)
    if not 5 <= target <= 10 or target * 2 != int(target * 2):
        raise ValueError("target RPE must be between 5 and 10 in half steps")
    if not (approved_by or "").strip():
        raise ValueError("a plan must record the approving coach")
    stamp = iso(now)
    conn.execute(
        "UPDATE plan_sessions SET retired_at = ? WHERE athlete_id = ? AND weekday = ? "
        "AND lift = ? AND retired_at IS NULL",
        (stamp, athlete_id, int(weekday), name),
    )
    cur = conn.execute(
        "INSERT INTO plan_sessions (athlete_id, weekday, lift, sets, reps, rpe, approved_by, approved_at) "
        "VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
        (athlete_id, int(weekday), name, int(sets), int(reps), target, approved_by.strip()[:80], stamp),
    )
    conn.commit()
    return int(cur.lastrowid)


def retire_plan_session(conn, athlete_id: str, session_id: int, *, now: datetime) -> bool:
    cur = conn.execute(
        "UPDATE plan_sessions SET retired_at = ? WHERE id = ? AND athlete_id = ? AND retired_at IS NULL",
        (iso(now), int(session_id), athlete_id),
    )
    conn.commit()
    return cur.rowcount == 1


def active_plan(conn, athlete_id: str) -> list:
    return list(conn.execute(
        "SELECT * FROM plan_sessions WHERE athlete_id = ? AND retired_at IS NULL "
        "ORDER BY weekday, id",
        (athlete_id,),
    ))


def plan_for_weekday(conn, athlete_id: str, weekday: int) -> tuple[PlannedLift, ...]:
    return tuple(
        PlannedLift(str(row["lift"]), int(row["sets"]), int(row["reps"]), float(row["rpe"]))
        for row in conn.execute(
            "SELECT * FROM plan_sessions WHERE athlete_id = ? AND weekday = ? "
            "AND retired_at IS NULL ORDER BY id",
            (athlete_id, int(weekday)),
        )
    )


def planned_athletes(conn) -> list[str]:
    return [
        str(row["athlete_id"])
        for row in conn.execute(
            "SELECT DISTINCT athlete_id FROM plan_sessions WHERE retired_at IS NULL ORDER BY athlete_id"
        )
    ]


# --- Per-athlete agent settings ---------------------------------------------------


def agent_settings(conn, athlete_id: str) -> dict[str, Any]:
    row = conn.execute(
        "SELECT autopilot, checkin_time FROM agent_settings WHERE athlete_id = ?", (athlete_id,)
    ).fetchone()
    if row is None:
        return {"autopilot": False, "checkin_time": None}
    return {"autopilot": bool(row["autopilot"]), "checkin_time": row["checkin_time"]}


def _save_settings(conn, athlete_id: str, *, autopilot: bool, checkin_time: str | None,
                   updated_by: str, now: datetime) -> None:
    conn.execute(
        "INSERT INTO agent_settings (athlete_id, autopilot, checkin_time, updated_by, updated_at) "
        "VALUES (?, ?, ?, ?, ?) ON CONFLICT (athlete_id) DO UPDATE SET "
        "autopilot = excluded.autopilot, checkin_time = excluded.checkin_time, "
        "updated_by = excluded.updated_by, updated_at = excluded.updated_at",
        (athlete_id, int(autopilot), checkin_time, updated_by[:80], iso(now)),
    )
    conn.commit()


def set_autopilot(conn, athlete_id: str, enabled: bool, *, updated_by: str, now: datetime) -> None:
    current = agent_settings(conn, athlete_id)
    _save_settings(conn, athlete_id, autopilot=bool(enabled), checkin_time=current["checkin_time"],
                   updated_by=updated_by, now=now)


def set_checkin_time(conn, athlete_id: str, value: str | None, *, updated_by: str, now: datetime) -> None:
    current = agent_settings(conn, athlete_id)
    _save_settings(conn, athlete_id, autopilot=current["autopilot"], checkin_time=value,
                   updated_by=updated_by, now=now)


# --- Cases ------------------------------------------------------------------------


def create_case(
    conn, *, athlete_id: str, local_date: str, timezone_name: str, checkin_time: str,
    training_time: str, plan: list[dict[str, object]], next_action_at: str, now: datetime,
    simulated: bool = False,
) -> int | None:
    """Open the case for one training day. Returns None when it already exists."""
    stamp = iso(now)
    cur = conn.execute(
        "INSERT INTO agent_cases (athlete_id, local_date, timezone, checkin_time, training_time, "
        "state, next_action_at, plan_json, created_at, updated_at, simulated) "
        "VALUES (?, ?, ?, ?, ?, 'scheduled', ?, ?, ?, ?, ?) "
        "ON CONFLICT (athlete_id, local_date) DO NOTHING",
        (athlete_id, local_date, timezone_name, checkin_time, training_time, next_action_at,
         _dumps(plan), stamp, stamp, int(simulated)),
    )
    conn.commit()
    if cur.rowcount != 1:
        return None
    row = case_for_day(conn, athlete_id, local_date)
    return int(row["id"]) if row is not None else None


def case_by_id(conn, case_id: int):
    return conn.execute("SELECT * FROM agent_cases WHERE id = ?", (int(case_id),)).fetchone()


def case_for_day(conn, athlete_id: str, local_date: str):
    return conn.execute(
        "SELECT * FROM agent_cases WHERE athlete_id = ? AND local_date = ?", (athlete_id, local_date)
    ).fetchone()


def open_case_for_day(conn, athlete_id: str, local_date: str):
    return conn.execute(
        f"SELECT * FROM agent_cases WHERE athlete_id = ? AND local_date = ? AND state IN ({_in(OPEN_STATES)})",
        (athlete_id, local_date, *OPEN_STATES),
    ).fetchone()


def due_cases(
    conn, now_iso: str, *, simulated: bool = False, athlete_ids: list[str] | None = None
) -> list:
    """Cases whose next step is due. Real and simulated cases never mix."""
    rows = conn.execute(
        f"SELECT * FROM agent_cases WHERE simulated = ? AND state IN ({_in(TIMED_STATES)}) "
        "AND next_action_at IS NOT NULL AND next_action_at <= ? ORDER BY next_action_at, id",
        (int(simulated), *TIMED_STATES, now_iso),
    )
    return [row for row in rows if athlete_ids is None or row["athlete_id"] in athlete_ids]


def simulated_cases(conn) -> list:
    return list(conn.execute("SELECT * FROM agent_cases WHERE simulated = 1 ORDER BY athlete_id"))


def update_case(conn, case, *, now: datetime, **fields: Any) -> bool:
    """Apply a change only if nobody else changed the case since it was read."""
    unknown = set(fields) - _CASE_FIELDS
    if unknown:
        raise ValueError(f"unknown case fields: {sorted(unknown)}")
    assignments = ", ".join(f"{name} = ?" for name in fields)
    cur = conn.execute(
        f"UPDATE agent_cases SET {assignments}, updated_at = ?, version = version + 1 "
        "WHERE id = ? AND version = ?",
        (*fields.values(), iso(now), int(case["id"]), int(case["version"])),
    )
    conn.commit()
    return cur.rowcount == 1


def previous_outcomes(
    conn, athlete_id: str, before_date: str, limit: int, *, simulated: bool = False
) -> list[str | None]:
    return [
        row["outcome"]
        for row in conn.execute(
            "SELECT outcome FROM agent_cases WHERE athlete_id = ? AND local_date < ? "
            "AND simulated = ? ORDER BY local_date DESC LIMIT ?",
            (athlete_id, before_date, int(simulated), int(limit)),
        )
    ]


def cases_in_states(conn, states: tuple[str, ...], *, simulated: bool = False) -> list:
    return list(conn.execute(
        f"SELECT * FROM agent_cases WHERE simulated = ? AND state IN ({_in(states)}) "
        "ORDER BY next_action_at, id",
        (int(simulated), *states),
    ))


def closed_since(conn, since_iso: str) -> list:
    return list(conn.execute(
        "SELECT * FROM agent_cases WHERE simulated = 0 AND state = 'closed' AND closed_at >= ? "
        "ORDER BY closed_at DESC",
        (since_iso,),
    ))


def recent_cases(conn, athlete_id: str, limit: int = 10) -> list:
    return list(conn.execute(
        "SELECT * FROM agent_cases WHERE athlete_id = ? AND simulated = 0 "
        "ORDER BY local_date DESC LIMIT ?",
        (athlete_id, int(limit)),
    ))


def checkin_latencies(
    conn, athlete_id: str, *, checkin_time: str, since: str | None, limit: int
) -> list[float]:
    """Minutes from check-in sent to first reply, for days that used this check-in time."""
    sql = (
        "SELECT checkin_sent_at, checkin_received_at FROM agent_cases WHERE athlete_id = ? "
        "AND checkin_time = ? AND checkin_sent_at IS NOT NULL AND checkin_received_at IS NOT NULL "
        "AND simulated = 0"
    )
    params: list[Any] = [athlete_id, checkin_time]
    if since:
        sql += " AND created_at > ?"
        params.append(since)
    sql += " ORDER BY local_date DESC LIMIT ?"
    params.append(int(limit))
    result = []
    for row in conn.execute(sql, params):
        sent = datetime.fromisoformat(str(row["checkin_sent_at"]))
        received = datetime.fromisoformat(str(row["checkin_received_at"]))
        result.append(max(0.0, (received - sent).total_seconds() / 60))
    return result


# --- The event log: observations, decisions, actions, expectations, outcomes ----------


def record_event(
    conn, *, case_id: int | None, athlete_id: str, kind: str, code: str, summary: str,
    now: datetime, detail: Any = None,
) -> int:
    if kind not in EVENT_KINDS:
        raise ValueError(f"unknown event kind: {kind!r}")
    cur = conn.execute(
        "INSERT INTO agent_events (case_id, athlete_id, occurred_at, kind, code, summary, detail_json) "
        "VALUES (?, ?, ?, ?, ?, ?, ?)",
        (case_id, athlete_id, iso(now), kind, code, summary[:500], _dumps(detail)),
    )
    conn.commit()
    return int(cur.lastrowid)


def reserve_action(
    conn, *, case_id: int, athlete_id: str, key: str, code: str, summary: str,
    detail: Any, now: datetime,
) -> str:
    """Claim an action before it runs. Returns "new", or the status it already has."""
    cur = conn.execute(
        "INSERT INTO agent_events (case_id, athlete_id, occurred_at, kind, code, summary, "
        "detail_json, idempotency_key, status) VALUES (?, ?, ?, 'action', ?, ?, ?, ?, 'reserved') "
        "ON CONFLICT (idempotency_key) DO NOTHING",
        (case_id, athlete_id, iso(now), code, summary[:500], _dumps(detail), key),
    )
    conn.commit()
    if cur.rowcount == 1:
        return "new"
    row = conn.execute(
        "SELECT status FROM agent_events WHERE idempotency_key = ?", (key,)
    ).fetchone()
    return str(row["status"]) if row is not None else "reserved"


def finish_action(conn, key: str, status: str, *, note: str | None = None) -> None:
    if status not in {"sent", "failed", "unconfirmed", "skipped"}:
        raise ValueError(f"unknown action status: {status!r}")
    row = conn.execute(
        "SELECT detail_json FROM agent_events WHERE idempotency_key = ?", (key,)
    ).fetchone()
    detail = (loads(row["detail_json"]) if row is not None else None) or {}
    if note:
        detail["result"] = note
    conn.execute(
        "UPDATE agent_events SET status = ?, detail_json = ? WHERE idempotency_key = ?",
        (status, _dumps(detail), key),
    )
    conn.commit()


def stale_reservations(conn, before_iso: str) -> list:
    return list(conn.execute(
        "SELECT * FROM agent_events WHERE kind = 'action' AND status = 'reserved' AND occurred_at < ?",
        (before_iso,),
    ))


def case_events(conn, case_id: int) -> list:
    return list(conn.execute(
        "SELECT * FROM agent_events WHERE case_id = ? ORDER BY id", (int(case_id),)
    ))


_REAL_EVENTS = "(case_id IS NULL OR case_id IN (SELECT id FROM agent_cases WHERE simulated = 0))"


def recent_events(conn, limit: int = 20) -> list:
    """The real agent's latest events; the simulated demo day is shown separately."""
    return list(conn.execute(
        f"SELECT * FROM agent_events WHERE {_REAL_EVENTS} ORDER BY id DESC LIMIT ?", (int(limit),)
    ))


def sent_actions_since(conn, since_iso: str) -> int:
    row = conn.execute(
        "SELECT COUNT(*) AS n FROM agent_events WHERE kind = 'action' AND status = 'sent' "
        f"AND occurred_at >= ? AND {_REAL_EVENTS}",
        (since_iso,),
    ).fetchone()
    return int(row["n"])


# --- Adaptations ------------------------------------------------------------------


def record_adaptation(
    conn, *, athlete_id: str, parameter: str, old_value: str, new_value: str,
    evidence: dict[str, Any], explanation: str, now: datetime,
) -> int:
    cur = conn.execute(
        "INSERT INTO agent_adaptations (athlete_id, parameter, old_value, new_value, evidence_json, "
        "explanation, created_at) VALUES (?, ?, ?, ?, ?, ?, ?)",
        (athlete_id, parameter, old_value, new_value, _dumps(evidence), explanation, iso(now)),
    )
    conn.commit()
    return int(cur.lastrowid)


def latest_adaptation(conn, athlete_id: str, parameter: str):
    return conn.execute(
        "SELECT * FROM agent_adaptations WHERE athlete_id = ? AND parameter = ? ORDER BY id DESC LIMIT 1",
        (athlete_id, parameter),
    ).fetchone()


def adaptations(conn, limit: int = 10) -> list:
    return list(conn.execute(
        "SELECT * FROM agent_adaptations ORDER BY id DESC LIMIT ?", (int(limit),)
    ))


# --- The coach's Telegram chat ----------------------------------------------------


def coach_chat_id(conn) -> str | None:
    row = conn.execute("SELECT chat_id FROM coach_channel WHERE id = 1").fetchone()
    return str(row["chat_id"]) if row is not None else None


def link_coach_chat(conn, chat_id: str, *, code_fingerprint: str, now: datetime) -> str:
    """Bind the coach chat once per setup code. Returns linked, already or taken."""
    row = conn.execute("SELECT chat_id, code_fingerprint FROM coach_channel WHERE id = 1").fetchone()
    if row is not None and str(row["chat_id"]) == str(chat_id):
        return "already"
    if row is not None and str(row["code_fingerprint"]) == code_fingerprint:
        return "taken"
    conn.execute(
        "INSERT INTO coach_channel (id, chat_id, linked_at, code_fingerprint) VALUES (1, ?, ?, ?) "
        "ON CONFLICT (id) DO UPDATE SET chat_id = excluded.chat_id, linked_at = excluded.linked_at, "
        "code_fingerprint = excluded.code_fingerprint",
        (str(chat_id), iso(now), code_fingerprint),
    )
    conn.commit()
    return "linked"


# --- A lease so two schedulers never run the loop at once -------------------------


def acquire_lease(conn, name: str, holder: str, *, now: datetime, ttl_seconds: int) -> bool:
    conn.execute(
        "INSERT INTO agent_lease (name, holder, expires_at) VALUES (?, ?, ?) "
        "ON CONFLICT (name) DO UPDATE SET holder = excluded.holder, expires_at = excluded.expires_at "
        "WHERE agent_lease.expires_at < ?",
        (name, holder, iso(now + timedelta(seconds=ttl_seconds)), iso(now)),
    )
    conn.commit()
    row = conn.execute("SELECT holder FROM agent_lease WHERE name = ?", (name,)).fetchone()
    return row is not None and str(row["holder"]) == holder


def release_lease(conn, name: str, holder: str) -> None:
    conn.execute("DELETE FROM agent_lease WHERE name = ? AND holder = ?", (name, holder))
    conn.commit()

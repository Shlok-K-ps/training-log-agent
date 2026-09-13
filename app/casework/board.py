"""What the coach console shows about the agent: done, waiting, needs you, learned."""

from __future__ import annotations

import statistics
from dataclasses import dataclass, field
from datetime import datetime, timedelta

from app.casework import store
from app.storage import db


@dataclass
class Board:
    needs_coach: list[dict] = field(default_factory=list)
    open_cases: list[dict] = field(default_factory=list)
    completed: list[dict] = field(default_factory=list)
    timeline: list[dict] = field(default_factory=list)
    learned: list[dict] = field(default_factory=list)
    messages_sent: int = 0
    planned_athletes: int = 0
    coach_linked: bool = False


def _case(conn, row) -> dict:
    item = dict(row)
    item["athlete_name"] = db.athlete_name(conn, str(row["athlete_id"])) or str(row["athlete_id"])
    item["escalation"] = store.loads(row["escalation_json"]) or {}
    return item


def snapshot(conn, now: datetime) -> Board:
    since = store.iso(now - timedelta(hours=24))
    board = Board(
        needs_coach=[_case(conn, row) for row in store.cases_in_states(conn, ("needs_coach",))],
        open_cases=[
            _case(conn, row)
            for row in store.cases_in_states(conn, ("scheduled", "awaiting_checkin", "awaiting_outcome"))
        ],
        completed=[_case(conn, row) for row in store.closed_since(conn, since)],
        messages_sent=store.sent_actions_since(conn, since),
        planned_athletes=len(store.planned_athletes(conn)),
        coach_linked=store.coach_chat_id(conn) is not None,
    )
    zones: dict[int, str] = {}
    for row in store.recent_events(conn, 25):
        item = dict(row)
        case_id = row["case_id"]
        if case_id is not None and case_id not in zones:
            case = store.case_by_id(conn, case_id)
            zones[case_id] = str(case["timezone"]) if case is not None else "UTC"
        item["timezone"] = zones.get(case_id, "UTC")
        item["athlete_name"] = db.athlete_name(conn, str(row["athlete_id"])) or str(row["athlete_id"])
        board.timeline.append(item)
    for row in store.adaptations(conn, 5):
        item = dict(row)
        item["athlete_name"] = db.athlete_name(conn, str(row["athlete_id"])) or str(row["athlete_id"])
        evidence = store.loads(row["evidence_json"]) or {}
        item["before_median"] = evidence.get("median_minutes")
        after = store.checkin_latencies(
            conn, str(row["athlete_id"]), checkin_time=str(row["new_value"]),
            since=str(row["created_at"]), limit=7,
        )
        item["after_median"] = round(statistics.median(after)) if after else None
        item["after_samples"] = len(after)
        board.learned.append(item)
    return board


def athlete_agent_state(conn, athlete_id: str) -> dict:
    return {
        "plan": store.active_plan(conn, athlete_id),
        "settings": store.agent_settings(conn, athlete_id),
        "cases": store.recent_cases(conn, athlete_id, 7),
        "adaptation": store.latest_adaptation(conn, athlete_id, "checkin_time"),
    }

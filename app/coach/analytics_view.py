"""Goal pacing analytics for the coach workspace."""

from __future__ import annotations

from datetime import date
from html import escape

from app.coach.progress import GoalPace
from app.coach.view import coach_frame


_STYLE = """
.pace-stats{display:grid;grid-template-columns:repeat(3,1fr);gap:10px;margin-bottom:20px}
.pace-stat{background:var(--surface);border:1px solid var(--border);border-radius:6px;padding:15px}
.pace-stat strong{font-size:26px;display:block}.pace-stat span{color:var(--ink-faint);font-size:12px}
.pace-table{background:var(--surface);border:1px solid var(--border);border-radius:6px;overflow:auto}
.pace-table table{margin:0;min-width:680px}.pace-ahead{color:var(--plate-green-text)}
.pace-on_track{color:var(--plate-blue-text)}.pace-lagging{color:var(--plate-red-text)}
.pace-note{padding:12px 14px;background:var(--plate-blue-bg);border:1px solid var(--plate-blue-border);border-radius:5px;margin-bottom:18px;color:var(--plate-blue-text);font-size:13px}
"""


def render_analytics(
    paces: tuple[GoalPace, ...], *, coach: str, today: date, pending_count: int
) -> str:
    counts = {state: sum(1 for pace in paces if pace.status == state)
              for state in ("ahead", "on_track", "lagging")}
    stats = (
        '<div class="pace-stats">'
        f'<div class="pace-stat"><strong>{counts["ahead"]}</strong><span>Ahead of track</span></div>'
        f'<div class="pace-stat"><strong>{counts["on_track"]}</strong><span>On track</span></div>'
        f'<div class="pace-stat"><strong>{counts["lagging"]}</strong><span>Lagging</span></div></div>'
    )
    rows = "".join(
        '<tr>'
        f'<td><a class="athlete-name" href="/coach/athlete/{escape(pace.athlete_id)}">{escape(pace.athlete_name)}</a></td>'
        f'<td>{escape(pace.lift.title())}</td><td>{pace.current_kg:g} kg</td>'
        f'<td>{pace.expected_kg:g} kg</td><td>{pace.target_kg:g} kg</td>'
        f'<td>{escape(pace.target_date)}</td><td class="pace-{escape(pace.status)}"><b>{escape(pace.status.replace("_", " ").title())}</b></td>'
        '</tr>' for pace in paces
    )
    table = (
        '<div class="pace-table"><table><thead><tr><th>Athlete</th><th>Goal</th>'
        '<th>Current e1RM</th><th>Expected today</th><th>Target</th><th>Deadline</th>'
        f'<th>Pace</th></tr></thead><tbody>{rows}</tbody></table></div>'
        if rows else '<p class="empty">Add a goal lift, current 1RM, target and date when enrolling an athlete to calculate pacing.</p>'
    )
    note = (
        '<div class="pace-note"><strong>How pace is calculated:</strong> the athlete’s '
        'best estimated 1RM is compared with a straight-line checkpoint between their '
        'recorded starting 1RM and target. It is a planning signal, not a promise; the '
        'coach decides whether the goal or programme should change.</div>'
    )
    return coach_frame(
        stats + note + table, active="analytics", coach=coach, title="Goal Analytics",
        subtitle="Who is ahead, on track, or lagging for the current block or meet goal.",
        today=today.isoformat(), pending_count=pending_count, extra_style=_STYLE,
    )

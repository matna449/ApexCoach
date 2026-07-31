"""Weekly Adaptation Engine (Logic Spec §4).

Functional core, imperative shell (docs/adr/0016): decision functions
(decide_state_transition, decide_skip_disposition, select_reschedule_slot,
recovery_week_replacement) are pure. run_weekly_adaptation() is the one
impure entry point — reads weekly_plans/monthly_targets/daily_metrics via
the repositories and writes the adapted plan back.
"""

import json
from datetime import date, datetime, timedelta

from apex_coach.engines.daily_engine import KEY_SESSION_TYPES
from apex_coach.orchestrator.orchestrator import RecoveryBand, classify_recovery

DAYS_OF_WEEK = ["Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday", "Sunday"]
_DAY_INDEX = {day: i for i, day in enumerate(DAYS_OF_WEEK)}

WEEK_STATUSES = {"ON_TRACK", "LOAD_DEFICIT", "OVERREACHED", "RECOVERY_WEEK", "COMPLETE"}

# §4.3 Recovery Week Protocol — replacement session type when a recovery
# week is triggered. Zone2_Short's own §4.3 row ("maintained or swapped
# depending on daily engine output") can't be resolved without that day's
# actual daily_engine run; kept as "maintained" (Zone2_Short unchanged),
# the simpler of its two documented options.
RECOVERY_WEEK_REPLACEMENT = {
    "HIIT": "Zone2_Short",
    "Threshold": "Zone2_Short",
    "Zone2_Long": "Zone2_Short",
    "Zone2_Short": "Zone2_Short",
    "Strength": "Recovery",
    "Recovery": "Recovery",
    "Rest": "Rest",
}


# -- §4.1 State machine -------------------------------------------------------


def decide_state_transition(
    current_state: str,
    *,
    end_of_week_reached: bool = False,
    key_session_skipped: bool = False,
    load_pct: float | None = None,
    overreached_3_consecutive_days: bool = False,
    two_consecutive_red_days: bool = False,
    monthly_engine_triggers_recovery: bool = False,
    rescheduled_session_completed: bool = False,
    monthly_load_not_recoverable: bool = False,
) -> str:
    if current_state not in WEEK_STATUSES:
        raise ValueError(f"unknown week_status: {current_state!r}")

    if end_of_week_reached:
        return "COMPLETE"

    if current_state == "ON_TRACK":
        if key_session_skipped and load_pct is not None and load_pct < 80:
            return "LOAD_DEFICIT"
        if overreached_3_consecutive_days:
            return "OVERREACHED"
        if monthly_engine_triggers_recovery or two_consecutive_red_days:
            return "RECOVERY_WEEK"
        return "ON_TRACK"

    if current_state == "LOAD_DEFICIT":
        if rescheduled_session_completed:
            return "ON_TRACK"
        if monthly_load_not_recoverable:
            return "RECOVERY_WEEK"
        return "LOAD_DEFICIT"

    if current_state == "OVERREACHED":
        return "RECOVERY_WEEK"  # automatic — cannot return to ON_TRACK directly

    # RECOVERY_WEEK and COMPLETE only change via end_of_week_reached, above.
    return current_state


def two_consecutive_red_days(recent_recovery_pct: list[float]) -> bool:
    """recent_recovery_pct: [yesterday, day_before], most recent first.
    recovery_band is re-derived from stored whoop_recovery_pct rather than
    persisted (docs/adr/0016) — a pure recomputation, not a stored fact."""
    if len(recent_recovery_pct) < 2:
        return False
    return all(
        classify_recovery(pct) == RecoveryBand.RED for pct in recent_recovery_pct[:2]
    )


# -- §4.2 Skip Disposition ---------------------------------------------------


def select_reschedule_slot(
    planned_sessions: list[dict], key_session_types: frozenset = frozenset(KEY_SESSION_TYPES)
) -> str | None:
    """Greedy earliest-available day search. "Minimum 1 full day between KEY
    sessions" means a candidate day must be at least 2 days (index-wise) from
    every existing KEY session day — adjacent days have 0 days between them.
    Returns the day name, or None if no valid slot exists."""
    by_day = {s["day"]: s["session_type"] for s in planned_sessions}
    key_day_indices = [
        _DAY_INDEX[day] for day, session_type in by_day.items() if session_type in key_session_types
    ]

    for day in DAYS_OF_WEEK:
        session_type = by_day.get(day)
        if session_type in key_session_types or session_type == "Rest":
            continue
        idx = _DAY_INDEX[day]
        if all(abs(idx - kd) >= 2 for kd in key_day_indices):
            return day
    return None


def decide_skip_disposition(
    days_remaining_in_week: int,
    monthly_load_pct: float,
    current_week_state: str,
    reschedule_slot: str | None,
) -> str:
    """Returns "RESCHEDULE" or "WRITE_OFF" (§4.2). WRITE_OFF's documented
    conditions are the exact negation of RESCHEDULE's — computed as one
    check, not two."""
    can_reschedule = (
        days_remaining_in_week >= 2
        and monthly_load_pct < 85
        and current_week_state != "RECOVERY_WEEK"
        and reschedule_slot is not None
    )
    return "RESCHEDULE" if can_reschedule else "WRITE_OFF"


def apply_skip(
    planned_sessions: list[dict],
    skipped_session_type: str,
    skipped_day: str,
    days_remaining_in_week: int,
    monthly_load_pct: float,
    current_week_state: str,
) -> tuple[list[dict], dict]:
    """Applies a Skip Disposition decision to the plan. Returns
    (adapted_sessions, skip_record) — skip_record matches skipped_sessions'
    documented shape (docs/adr/0016)."""
    slot = select_reschedule_slot(planned_sessions)
    disposition = decide_skip_disposition(
        days_remaining_in_week, monthly_load_pct, current_week_state, slot
    )

    adapted = [dict(s) for s in planned_sessions]

    if disposition == "RESCHEDULE":
        displaced_type = next((s["session_type"] for s in adapted if s["day"] == slot), "Rest")
        for s in adapted:
            if s["day"] == slot:
                s["session_type"] = skipped_session_type
            elif s["day"] == skipped_day:
                s["session_type"] = displaced_type

    skip_record = {
        "session_type": skipped_session_type,
        "disposition": "rescheduled" if disposition == "RESCHEDULE" else "written_off",
        "original_day": skipped_day,
    }
    return adapted, skip_record


# -- §4.3 Recovery Week Protocol ----------------------------------------------


def apply_recovery_week_protocol(planned_sessions: list[dict]) -> list[dict]:
    return [
        {"day": s["day"], "session_type": RECOVERY_WEEK_REPLACEMENT[s["session_type"]]}
        for s in planned_sessions
    ]


# -- Orchestrator: reads/writes via the repositories (docs/adr/0016) -------


def _diff_sessions(planned: list[dict], adapted: list[dict]) -> list[dict]:
    planned_by_day = {s["day"]: s["session_type"] for s in planned}
    changes = []
    for a in adapted:
        before = planned_by_day.get(a["day"])
        if before != a["session_type"]:
            changes.append({"day": a["day"], "from": before, "to": a["session_type"]})
    return changes


def run_weekly_adaptation(
    plan_repo,
    metrics_repo,
    week_start_date: str,
    *,
    today: str | None = None,
    key_session_skipped_type: str | None = None,
    key_session_skipped_day: str | None = None,
    rescheduled_session_completed: bool = False,
    end_of_week_reached: bool = False,
    monthly_overreach_detected: bool | None = None,
    monthly_load_not_recoverable: bool = False,
    overreached_3_consecutive_days: bool = False,
) -> dict:
    """Reads current weekly_plans/monthly_targets/daily_metrics state,
    decides the new state and adapted plan, writes it back. Returns a diff:
    which sessions changed and why."""
    week = plan_repo.get_weekly_plan(week_start_date)
    if week is None:
        raise ValueError(f"no weekly_plans row for week_start_date {week_start_date!r}")

    planned_sessions = json.loads(week["planned_sessions_json"] or "[]")
    stored_adapted = json.loads(week["adapted_plan_json"] or "null")
    adapted_sessions = stored_adapted if stored_adapted is not None else [
        dict(s) for s in planned_sessions
    ]
    skipped_sessions = json.loads(week["skipped_sessions"] or "[]")

    today_date = date.fromisoformat(today) if today else datetime.now().date()
    week_start = date.fromisoformat(week_start_date)
    days_remaining = max(0, 7 - (today_date - week_start).days)

    month_start = week_start.replace(day=1).isoformat()
    month = plan_repo.get_monthly_target(month_start)
    monthly_load_pct = (
        (month["load_actual_total"] / month["load_target_total"] * 100)
        if month and month.get("load_target_total")
        else 0.0
    )

    day_before_yesterday = (today_date - timedelta(days=2)).isoformat()
    yesterday = (today_date - timedelta(days=1)).isoformat()
    recent = metrics_repo.get_daily_metrics_range(day_before_yesterday, yesterday)
    recent_recovery_pct = [
        row["whoop_recovery_pct"]
        for row in sorted(recent, key=lambda r: r["date"], reverse=True)
        if row["whoop_recovery_pct"] is not None
    ]

    if key_session_skipped_type is not None:
        adapted_sessions, skip_record = apply_skip(
            adapted_sessions,
            key_session_skipped_type,
            key_session_skipped_day,
            days_remaining,
            monthly_load_pct,
            week["week_status"],
        )
        skipped_sessions = [*skipped_sessions, skip_record]

    new_state = decide_state_transition(
        week["week_status"],
        end_of_week_reached=end_of_week_reached,
        key_session_skipped=key_session_skipped_type is not None,
        load_pct=monthly_load_pct,
        overreached_3_consecutive_days=overreached_3_consecutive_days,
        two_consecutive_red_days=two_consecutive_red_days(recent_recovery_pct),
        monthly_engine_triggers_recovery=bool(monthly_overreach_detected),
        rescheduled_session_completed=rescheduled_session_completed,
        monthly_load_not_recoverable=monthly_load_not_recoverable,
    )

    if new_state == "RECOVERY_WEEK" and week["week_status"] != "RECOVERY_WEEK":
        adapted_sessions = apply_recovery_week_protocol(adapted_sessions)

    diff = _diff_sessions(planned_sessions, adapted_sessions)

    plan_repo.update_weekly_plan(
        week_start_date,
        week_status=new_state,
        adapted_plan_json=json.dumps(adapted_sessions),
        skipped_sessions=json.dumps(skipped_sessions),
    )

    return {
        "week_status": new_state,
        "adapted_sessions": adapted_sessions,
        "skipped_sessions": skipped_sessions,
        "diff": diff,
    }

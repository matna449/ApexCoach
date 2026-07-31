"""Monthly Load Engine (Logic Spec §5).

Functional core, imperative shell (docs/adr/0016, reapplied per docs/adr/0017):
decision/calculation functions are pure. run_monthly_review() is the one
impure entry point — reads metrics_repository/plan_repository and writes
monthly_targets.month_summary_json back.

Monthly has final authority over weekly per the Three-Horizon Model
(ADR-0002): load_overreach_detected() is the real signal
weekly_engine.run_weekly_adaptation()'s monthly_overreach_detected
parameter was deferred for (ADR-0016).
"""

import json
from calendar import monthrange
from datetime import date, datetime, timedelta

from apex_coach.services.load_calculator import calculate_load_au

WEEKS_PER_MONTH = 4.33

LOAD_DEFICIT_THRESHOLD = 0.75
OVERREACH_THRESHOLD = 1.15


# -- §5.1 Load Accumulation Model ---------------------------------------------


def calculate_weekly_target(monthly_target: float) -> float:
    return monthly_target / WEEKS_PER_MONTH


def calculate_daily_target(weekly_target: float, training_days_per_week: int) -> float:
    return weekly_target / training_days_per_week


def flag_load_threshold(load_pct: float) -> str | None:
    """load_pct is a fraction (actual/target), not a percentage. Returns
    LOAD_DEFICIT, OVERREACH_RISK, or None."""
    if load_pct < LOAD_DEFICIT_THRESHOLD:
        return "LOAD_DEFICIT"
    if load_pct > OVERREACH_THRESHOLD:
        return "OVERREACH_RISK"
    return None


def load_au_for_activity(
    activity: dict,
    resting_hr: float | None = None,
    max_hr: float | None = None,
    sex: str | None = None,
) -> float:
    """resting_hr/max_hr/sex are only required when activity_type is
    HR-based (docs/adr/0024's TRIMP calculation) — irrelevant for
    RPE-based (Strength) or duration-based (Yoga) activities, so callers
    iterating over a mixed batch don't need to resolve them universally."""
    duration_minutes = (activity.get("duration_seconds") or 0) / 60
    activity_type = activity["activity_type"]
    return calculate_load_au(
        activity_type,
        duration_minutes,
        avg_hr_bpm=activity.get("avg_hr_bpm"),
        resting_hr=resting_hr,
        max_hr=max_hr,
        sex=sex,
        rpe=activity.get("rpe"),
    )


# -- §5.2 Performance Forecast -------------------------------------------------


def hrv_trend_direction(hrv_weekly_avgs: list[float]) -> str:
    if len(hrv_weekly_avgs) < 2:
        return "STABLE"
    deltas = [hrv_weekly_avgs[i] - hrv_weekly_avgs[i - 1] for i in range(1, len(hrv_weekly_avgs))]
    avg_delta = sum(deltas) / len(deltas)
    if avg_delta > 0:
        return "IMPROVING"
    if avg_delta < 0:
        return "DECLINING"
    return "STABLE"


def forecast_performance(load_projected_pct: float, hrv_trend: str) -> tuple[str, str]:
    """load_projected_pct is a fraction. Returns (status, message)."""
    if load_projected_pct >= 0.90:
        if hrv_trend == "IMPROVING":
            return "ON_TRACK", "ON_TRACK — Performance trajectory positive."
        if hrv_trend == "STABLE":
            return "ON_TRACK", "ON_TRACK — Monitor HRV for early fatigue signals."
        return "AT_RISK", (
            "AT_RISK — Load on target but HRV declining. "
            "Review sleep, nutrition, and stress. May need early deload."
        )
    if load_projected_pct >= 0.75:
        return "MINOR_DEFICIT", (
            "MINOR_DEFICIT — Slightly behind pace. "
            "Protect all remaining key sessions this month."
        )
    return "SIGNIFICANT_DEFICIT", (
        "SIGNIFICANT_DEFICIT — Load well behind target. "
        "Adjust monthly target downward OR investigate causes (illness, "
        "injury, travel). Do not attempt to compensate with overload."
    )


def taper_adjusted_target(load_target: float, weeks_to_race: int | None) -> float:
    """§5.2 Taper detection — only overrides when weeks_to_race <= 3."""
    if weeks_to_race is None or weeks_to_race > 3:
        return load_target
    if weeks_to_race >= 3:
        return load_target * 0.80
    if weeks_to_race == 2:
        return load_target * 0.65
    return load_target * 0.40  # race week or beyond


# -- Authority hierarchy (ADR-0002, ADR-0016) --------------------------------


def load_overreach_detected(daily_load_pcts: list[float]) -> bool:
    """§5.1: "surplus sustained 3+ days -> trigger RECOVERY_WEEK". Feeds
    weekly_engine.run_weekly_adaptation()'s monthly_overreach_detected."""
    if len(daily_load_pcts) < 3:
        return False
    return all(pct > OVERREACH_THRESHOLD for pct in daily_load_pcts[-3:])


# -- §5.3 Monthly Summary ------------------------------------------------------


def _generate_key_observations(
    session_type_overpush_counts: dict[str, int],
    session_type_counts: dict[str, int],
    hrv_trend: str,
) -> list[str]:
    observations = []
    for session_type, overpush_count in session_type_overpush_counts.items():
        total = session_type_counts.get(session_type, 0)
        if total and overpush_count / total >= 0.5:
            observations.append(
                f"{session_type} sessions consistently overpush: "
                f"{overpush_count} of {total} recorded overpush flags."
            )
    if hrv_trend == "STABLE":
        observations.append("HRV stable across month — no overtraining signal.")
    elif hrv_trend == "DECLINING":
        observations.append("HRV declining across month — monitor for early fatigue.")
    return observations


def _generate_next_month_recommendation(periodisation_phase: str, forecast_status: str) -> str:
    if forecast_status in ("SIGNIFICANT_DEFICIT", "AT_RISK"):
        return f"Reassess {periodisation_phase} phase load target before continuing."
    return f"Maintain {periodisation_phase} phase. Continue current approach."


def build_month_summary(
    month_label: str,
    periodisation_phase: str,
    load_target_au: float,
    load_actual_au: float,
    hrv_weekly_avgs_ms: list[float],
    session_scores: list[dict],
    sessions_skipped: int,
    sessions_written_off: int,
    recovery_weeks: int,
    weeks_to_race: int | None,
    days_elapsed: int,
    days_in_month: int,
) -> dict:
    """Pure — assembles the §5.3 JSON structure from already-gathered data."""
    load_pct_complete = load_actual_au / load_target_au if load_target_au else 0.0
    load_pace = load_actual_au / days_elapsed if days_elapsed else 0.0
    load_projected = load_pace * days_in_month
    load_projected_pct = load_projected / load_target_au if load_target_au else 0.0

    hrv_trend = hrv_trend_direction(hrv_weekly_avgs_ms)
    forecast_status, _forecast_message = forecast_performance(load_projected_pct, hrv_trend)

    execution_scores = [s["execution_score"] for s in session_scores if s.get("execution_score") is not None]
    session_quality_avg = sum(execution_scores) / len(execution_scores) if execution_scores else 0.0

    overpush_flags = sum(1 for s in session_scores if s.get("overpush_flag"))
    underpush_flags = sum(1 for s in session_scores if s.get("underpush_flag"))

    top_session = max(session_scores, key=lambda s: s.get("execution_score") or -1, default=None)
    worst_session = min(session_scores, key=lambda s: s.get("execution_score") or 101, default=None)

    session_type_overpush_counts: dict[str, int] = {}
    session_type_counts: dict[str, int] = {}
    for s in session_scores:
        session_type = s.get("session_type", "unknown")
        session_type_counts[session_type] = session_type_counts.get(session_type, 0) + 1
        if s.get("overpush_flag"):
            session_type_overpush_counts[session_type] = (
                session_type_overpush_counts.get(session_type, 0) + 1
            )

    key_observations = _generate_key_observations(
        session_type_overpush_counts, session_type_counts, hrv_trend
    )
    next_month_recommendation = _generate_next_month_recommendation(
        periodisation_phase, forecast_status
    )

    return {
        "month": month_label,
        "periodisation_phase": periodisation_phase,
        "load_target_au": load_target_au,
        "load_actual_au": load_actual_au,
        "load_pct": round(load_pct_complete * 100, 1),
        "load_status": forecast_status,
        "hrv_trend": hrv_trend,
        "hrv_weekly_avgs_ms": hrv_weekly_avgs_ms,
        "session_quality_avg": round(session_quality_avg, 1),
        "sessions_completed": len(session_scores),
        "sessions_skipped": sessions_skipped,
        "sessions_written_off": sessions_written_off,
        "recovery_weeks": recovery_weeks,
        "overpush_flags": overpush_flags,
        "underpush_flags": underpush_flags,
        "top_execution_session": top_session,
        "worst_execution_session": worst_session,
        "key_observations": key_observations,
        "next_month_recommendation": next_month_recommendation,
    }


# -- Orchestrator: reads/writes via the repositories --------------------------


def run_monthly_review(
    plan_repo,
    metrics_repo,
    month_start_date: str,
    *,
    today: str | None = None,
) -> dict:
    """Reads activities/session_scores/daily_metrics/weekly_plans for the
    month, computes the summary, writes it to monthly_targets.month_summary_json."""
    month = plan_repo.get_monthly_target(month_start_date)
    if month is None:
        raise ValueError(f"no monthly_targets row for month_start_date {month_start_date!r}")

    month_start = date.fromisoformat(month_start_date)
    days_in_month = monthrange(month_start.year, month_start.month)[1]
    month_end = month_start.replace(day=days_in_month)
    today_date = date.fromisoformat(today) if today else datetime.now().date()
    days_elapsed = max(1, (min(today_date, month_end) - month_start).days + 1)

    daily_rows = metrics_repo.get_daily_metrics_range(month_start.isoformat(), month_end.isoformat())
    hrv_by_date = {row["date"]: row["whoop_hrv_ms"] for row in daily_rows if row["whoop_hrv_ms"] is not None}
    hrv_weekly_avgs_ms = _weekly_averages(hrv_by_date, month_start, month_end)
    resting_hr_by_date = {
        row["date"]: row["whoop_rhr_bpm"] for row in daily_rows if row["whoop_rhr_bpm"] is not None
    }

    activities = metrics_repo.get_activities_range(
        month_start.isoformat(), month_end.isoformat()
    )
    profile = plan_repo.get_athlete_profile()
    load_actual_au = sum(
        load_au_for_activity(
            a,
            resting_hr=resting_hr_by_date.get(a["date"])
            or (profile.get("baseline_resting_hr") if profile else None),
            max_hr=profile.get("max_hr") if profile else None,
            sex=profile.get("sex") if profile else None,
        )
        for a in activities
    )

    session_scores = []
    for activity in activities:
        score = metrics_repo.get_session_score(activity["id"])
        if score is not None:
            session_scores.append({**score, "session_type": activity.get("intended_session_type")})

    sessions_skipped = 0
    sessions_written_off = 0
    recovery_weeks = 0
    for week_start in _week_starts_in_month(month_start, month_end):
        week = plan_repo.get_weekly_plan(week_start.isoformat())
        if week is None:
            continue
        skipped = json.loads(week["skipped_sessions"] or "[]")
        sessions_skipped += len(skipped)
        sessions_written_off += sum(1 for s in skipped if s.get("disposition") == "written_off")
        if week["week_status"] == "RECOVERY_WEEK":
            recovery_weeks += 1

    weeks_to_race = None
    if month.get("race_date"):
        race_date = date.fromisoformat(month["race_date"])
        weeks_to_race = max(0, (race_date - today_date).days // 7)

    summary = build_month_summary(
        month_label=month_start.strftime("%B %Y"),
        periodisation_phase=month.get("periodisation_phase") or "BASE",
        load_target_au=month["load_target_total"],
        load_actual_au=load_actual_au,
        hrv_weekly_avgs_ms=hrv_weekly_avgs_ms,
        session_scores=session_scores,
        sessions_skipped=sessions_skipped,
        sessions_written_off=sessions_written_off,
        recovery_weeks=recovery_weeks,
        weeks_to_race=weeks_to_race,
        days_elapsed=days_elapsed,
        days_in_month=days_in_month,
    )

    plan_repo.update_monthly_target(
        month_start_date,
        load_actual_total=load_actual_au,
        hrv_trend_json=json.dumps(hrv_weekly_avgs_ms),
        month_summary_json=json.dumps(summary),
    )

    return summary


def _week_starts_in_month(month_start: date, month_end: date) -> list[date]:
    starts = []
    cursor = month_start - timedelta(days=month_start.weekday())  # back to Monday
    while cursor <= month_end:
        starts.append(cursor)
        cursor += timedelta(days=7)
    return starts


def _weekly_averages(hrv_by_date: dict[str, float], month_start: date, month_end: date) -> list[float]:
    weeks = _week_starts_in_month(month_start, month_end)
    averages = []
    for week_start in weeks:
        week_end = week_start + timedelta(days=6)
        values = [
            v
            for d, v in hrv_by_date.items()
            if week_start <= date.fromisoformat(d) <= week_end
        ]
        if values:
            averages.append(round(sum(values) / len(values), 1))
    return averages

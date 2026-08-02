"""Macro training-block planning (PRD #138, F20.2).

Functional core, imperative shell (docs/adr/0016, reapplied per
docs/adr/0017): every function here is pure -- no database or repository
dependency. The orchestrator that reads activity history / writes
race_goals+monthly_targets (F20.3) lives elsewhere and calls into this
module, not the other way round.

This is the fourth, higher horizon -- Macro/Race-Goal -- above Monthly in
the Three-Horizon Model (ADR-0002). It only ever proposes *initial* values
for monthly_targets rows (via F20.3's accept step); it has no override
authority over the existing Daily/Weekly/Monthly hierarchy.
"""

from datetime import date, timedelta

from apex_coach.engines.monthly_engine import OVERREACH_THRESHOLD, WEEKS_PER_MONTH, taper_adjusted_target

# Race distance -> ordered (periodisation_phase, minimum_weeks) tuples,
# summing to that distance's minimum sensible block length. Standard
# exercise-science phase-length convention, not literature-validated or
# personalized for this athlete -- same treatment as structure_generator.py's
# PHASE_SESSION_TYPE_WEIGHTS and load_calculator.py's TRIMP_B_CONSTANT,
# expected to need tuning once used against real outcomes.
#
# BASE is always first and is the "elastic" phase: generate_macro_plan()
# stretches it to absorb any lead time beyond the minimum, while
# BUILD/PEAK/TAPER stay pinned to their template length, anchored backward
# from the race date -- BUILD/PEAK/TAPER are tied tightly to race
# proximity, BASE is the phase with the most legitimate flexibility.
RACE_DISTANCE_PHASE_TEMPLATES: dict[str, list[tuple[str, int]]] = {
    "5K": [("BASE", 3), ("BUILD", 3), ("PEAK", 2), ("TAPER", 1)],
    "10K": [("BASE", 4), ("BUILD", 4), ("PEAK", 2), ("TAPER", 1)],
    "HALF_MARATHON": [("BASE", 6), ("BUILD", 5), ("PEAK", 2), ("TAPER", 2)],
    "MARATHON": [("BASE", 8), ("BUILD", 6), ("PEAK", 3), ("TAPER", 3)],
}

# Progressive-overload convention: load grows at most 10%/month during
# BASE/BUILD/PEAK -- comfortably under OVERREACH_THRESHOLD, so the ramp
# never proposes a month-over-month jump already known to be an overreach
# risk (§5.1). TAPER doesn't ramp at all -- it cuts via the existing
# taper_adjusted_target() instead (reused, not reimplemented).
MONTHLY_LOAD_RAMP_RATE = 1.10
assert MONTHLY_LOAD_RAMP_RATE <= OVERREACH_THRESHOLD, (
    "the monthly ramp rate must never itself exceed OVERREACH_THRESHOLD"
)


def _monday_of(d: date) -> date:
    return d - timedelta(days=d.weekday())


def estimate_current_weekly_load_au(recent_activities: list[dict]) -> float:
    """Average weekly load AU across the calendar weeks the given
    activities span (Monday-Sunday) -- including weeks with zero recorded
    activity, so an athlete who trains inconsistently doesn't get an
    inflated estimate from only counting the weeks they actually trained.

    Each activity dict needs `date` (ISO string) and `load_score`
    (float | None) -- the shape `MetricsRepository.get_activities_range()`
    already returns. Activities with no load_score (e.g. WeightTraining
    with no historical RPE, docs/adr/0024) are excluded from the load sum
    but still count toward the date range the average is spread over.

    `recent_activities` is expected to already be the caller's chosen
    trailing window (e.g. the last 8 weeks, via
    metrics_repo.get_activities_range()) -- this function only reflects
    whatever span it's given, it doesn't apply its own recency window.
    Returns 0.0 for an empty list -- no history to ground an estimate in,
    not an invalid input; the caller decides what to fall back to.
    """
    if not recent_activities:
        return 0.0

    dates = [date.fromisoformat(a["date"]) for a in recent_activities]
    first_monday = _monday_of(min(dates))
    last_monday = _monday_of(max(dates))
    weeks_spanned = (last_monday - first_monday).days // 7 + 1

    total_load = sum(
        a["load_score"] for a in recent_activities if a.get("load_score") is not None
    )
    return total_load / weeks_spanned


def _phase_timeline(
    padded_template: list[tuple[str, int]], block_start: date
) -> list[tuple[str, date, date]]:
    """[(phase, start_date_inclusive, end_date_exclusive), ...] walking
    forward from block_start through the padded (slack-absorbed) template."""
    timeline = []
    cursor = block_start
    for phase, weeks in padded_template:
        phase_end = cursor + timedelta(weeks=weeks)
        timeline.append((phase, cursor, phase_end))
        cursor = phase_end
    return timeline


def _phase_for(timeline: list[tuple[str, date, date]], d: date) -> str:
    for phase, start, end in timeline:
        if start <= d < end:
            return phase
    # d is on/after the timeline's final boundary (race day itself, or a
    # lookup date that landed exactly there) -- still the last phase
    # (TAPER), not an error; callers only ever look up dates within
    # [block_start, race_date].
    return timeline[-1][0]


def _month_starts_between(start: date, end: date) -> list[date]:
    """The 1st of every calendar month from start's month through end's
    month, inclusive -- monthly_targets rows are always keyed by
    month_start_date regardless of which day of the month `start` falls on."""
    starts = []
    cursor = date(start.year, start.month, 1)
    while cursor <= end:
        starts.append(cursor)
        cursor = date(cursor.year + 1, 1, 1) if cursor.month == 12 else date(cursor.year, cursor.month + 1, 1)
    return starts


def generate_macro_plan(
    goal_distance: str,
    race_date: date,
    today: date,
    current_weekly_load_au: float,
) -> list[dict]:
    """One {month_start_date, periodisation_phase, load_target_total}
    recommendation per calendar month from today's month through race_date's
    month.

    Raises ValueError if race_date isn't after today, or if there isn't
    enough runway for the chosen distance's minimum block length (e.g. a
    marathon goal three weeks out) -- surfaced loudly, not silently
    truncated or guessed around.

    Known simplification: a month is assigned exactly one phase, based on
    whichever phase is active on the 1st of that month -- a month whose
    real phase boundary falls mid-month (e.g. BASE ending the 15th) is
    still labeled with a single phase for the whole month, matching
    monthly_targets' one-phase-per-month grain. Finer-than-monthly phase
    blending isn't this ticket's job (week-level structure generation
    already exists for that, PRD #111).
    """
    if goal_distance not in RACE_DISTANCE_PHASE_TEMPLATES:
        raise ValueError(
            f"goal_distance must be one of {sorted(RACE_DISTANCE_PHASE_TEMPLATES)}, "
            f"got {goal_distance!r}"
        )
    if race_date <= today:
        raise ValueError(f"race_date ({race_date}) must be after today ({today})")

    template = RACE_DISTANCE_PHASE_TEMPLATES[goal_distance]
    min_weeks = sum(weeks for _, weeks in template)
    weeks_available = (race_date - today).days // 7
    if weeks_available < min_weeks:
        raise ValueError(
            f"{goal_distance} needs at least {min_weeks} weeks to build toward the "
            f"race -- only {weeks_available} weeks between today ({today}) and "
            f"race_date ({race_date})"
        )

    slack_weeks = weeks_available - min_weeks
    padded_template = [
        (phase, weeks + slack_weeks if i == 0 else weeks)
        for i, (phase, weeks) in enumerate(template)
    ]

    block_start = race_date - timedelta(weeks=weeks_available)
    timeline = _phase_timeline(padded_template, block_start)

    recommendations = []
    weekly_load = current_weekly_load_au
    peak_weekly_load = current_weekly_load_au
    for month_start in _month_starts_between(today, race_date):
        lookup_date = max(month_start, block_start)
        phase = _phase_for(timeline, lookup_date)

        if phase == "TAPER":
            weeks_to_race = max((race_date - month_start).days // 7, 0)
            weekly_load_this_month = taper_adjusted_target(peak_weekly_load, weeks_to_race)
        else:
            weekly_load_this_month = weekly_load
            peak_weekly_load = weekly_load
            weekly_load *= MONTHLY_LOAD_RAMP_RATE

        recommendations.append(
            {
                "month_start_date": month_start.isoformat(),
                "periodisation_phase": phase,
                "load_target_total": round(weekly_load_this_month * WEEKS_PER_MONTH, 1),
            }
        )

    return recommendations

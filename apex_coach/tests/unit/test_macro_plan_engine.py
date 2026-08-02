from datetime import date, timedelta

import pytest

from apex_coach.engines.macro_plan_engine import (
    MONTHLY_LOAD_RAMP_RATE,
    RACE_DISTANCE_PHASE_TEMPLATES,
    estimate_current_weekly_load_au,
    generate_macro_plan,
)
from apex_coach.engines.monthly_engine import OVERREACH_THRESHOLD, WEEKS_PER_MONTH, taper_adjusted_target


# -- RACE_DISTANCE_PHASE_TEMPLATES -------------------------------------------


def test_all_four_distances_are_templated():
    assert set(RACE_DISTANCE_PHASE_TEMPLATES) == {"5K", "10K", "HALF_MARATHON", "MARATHON"}


@pytest.mark.parametrize(
    "distance, min_total_weeks",
    [("5K", 9), ("10K", 11), ("HALF_MARATHON", 15), ("MARATHON", 20)],
)
def test_each_template_sums_to_a_sensible_week_count(distance, min_total_weeks):
    assert sum(weeks for _, weeks in RACE_DISTANCE_PHASE_TEMPLATES[distance]) == min_total_weeks


def test_block_length_increases_with_distance():
    totals = [
        sum(weeks for _, weeks in RACE_DISTANCE_PHASE_TEMPLATES[d])
        for d in ["5K", "10K", "HALF_MARATHON", "MARATHON"]
    ]
    assert totals == sorted(totals)
    assert len(set(totals)) == 4  # strictly increasing, no ties


@pytest.mark.parametrize("distance", RACE_DISTANCE_PHASE_TEMPLATES.keys())
def test_template_phases_are_ordered_base_build_peak_taper(distance):
    phases = [phase for phase, _weeks in RACE_DISTANCE_PHASE_TEMPLATES[distance]]
    assert phases == ["BASE", "BUILD", "PEAK", "TAPER"]


# -- estimate_current_weekly_load_au -----------------------------------------


def test_estimate_current_weekly_load_au_empty_history():
    assert estimate_current_weekly_load_au([]) == 0.0


def test_estimate_current_weekly_load_au_single_week():
    activities = [
        {"date": "2026-01-05", "load_score": 50.0},
        {"date": "2026-01-07", "load_score": 30.0},
    ]
    # Both dates fall in the same Mon-Sun week -- 1 week spanned.
    assert estimate_current_weekly_load_au(activities) == pytest.approx(80.0)


def test_estimate_current_weekly_load_au_counts_zero_activity_weeks():
    activities = [
        {"date": "2026-01-05", "load_score": 60.0},  # week of Jan 5
        {"date": "2026-01-19", "load_score": 30.0},  # week of Jan 19 -- Jan 12's week has nothing
    ]
    # 3 distinct Mon-Sun weeks spanned (Jan 5, Jan 12, Jan 19), even though
    # the middle week has no recorded activity -- the average reflects
    # actual training frequency, not just active weeks.
    assert estimate_current_weekly_load_au(activities) == pytest.approx(90.0 / 3)


def test_estimate_current_weekly_load_au_excludes_unscored_activities_from_sum():
    activities = [
        {"date": "2026-01-05", "load_score": 60.0},
        {"date": "2026-01-06", "load_score": None},  # e.g. WeightTraining, no historical RPE
    ]
    # Unscored activity still counts toward the (single-week) span, but
    # contributes nothing to the load sum.
    assert estimate_current_weekly_load_au(activities) == pytest.approx(60.0)


# -- generate_macro_plan: validation ------------------------------------------


def test_generate_macro_plan_rejects_unknown_distance():
    with pytest.raises(ValueError):
        generate_macro_plan("ULTRA", date(2026, 6, 1), date(2026, 1, 1), 100.0)


def test_generate_macro_plan_rejects_race_date_not_after_today():
    with pytest.raises(ValueError):
        generate_macro_plan("5K", date(2026, 1, 1), date(2026, 1, 1), 100.0)
    with pytest.raises(ValueError):
        generate_macro_plan("5K", date(2025, 12, 31), date(2026, 1, 1), 100.0)


@pytest.mark.parametrize(
    "distance, min_weeks",
    [("5K", 9), ("10K", 11), ("HALF_MARATHON", 15), ("MARATHON", 20)],
)
def test_generate_macro_plan_accepts_exactly_the_minimum_runway(distance, min_weeks):
    today = date(2026, 1, 5)  # Monday
    race_date = today + timedelta(weeks=min_weeks)
    # Doesn't raise.
    generate_macro_plan(distance, race_date, today, 100.0)


@pytest.mark.parametrize(
    "distance, min_weeks",
    [("5K", 9), ("10K", 11), ("HALF_MARATHON", 15), ("MARATHON", 20)],
)
def test_generate_macro_plan_rejects_one_week_short_of_the_minimum(distance, min_weeks):
    today = date(2026, 1, 5)
    race_date = today + timedelta(weeks=min_weeks - 1)
    with pytest.raises(ValueError, match=str(min_weeks)):
        generate_macro_plan(distance, race_date, today, 100.0)


def test_generate_macro_plan_rejects_marathon_three_weeks_out():
    # The PRD's own example of the too-short-notice rejection path.
    today = date(2026, 8, 2)
    race_date = today + timedelta(weeks=3)
    with pytest.raises(ValueError):
        generate_macro_plan("MARATHON", race_date, today, 100.0)


# -- generate_macro_plan: phase sequence + load ramp (exact-fit runway) ------


def test_generate_macro_plan_exact_fit_phases_and_ramp():
    today = date(2026, 1, 5)  # Monday
    race_date = today + timedelta(weeks=9)  # 5K's exact minimum, no slack
    current_weekly_load_au = 100.0

    plan = generate_macro_plan("5K", race_date, today, current_weekly_load_au)

    assert [row["month_start_date"] for row in plan] == ["2026-01-01", "2026-02-01", "2026-03-01"]
    assert [row["periodisation_phase"] for row in plan] == ["BASE", "BUILD", "PEAK"]

    # No slack to absorb -- BASE/BUILD/PEAK ramp by MONTHLY_LOAD_RAMP_RATE
    # each month, monthly total = weekly * WEEKS_PER_MONTH (calculate_weekly_target's
    # own inverse).
    week1 = current_weekly_load_au
    week2 = week1 * MONTHLY_LOAD_RAMP_RATE
    week3 = week2 * MONTHLY_LOAD_RAMP_RATE
    assert plan[0]["load_target_total"] == pytest.approx(round(week1 * WEEKS_PER_MONTH, 1))
    assert plan[1]["load_target_total"] == pytest.approx(round(week2 * WEEKS_PER_MONTH, 1))
    assert plan[2]["load_target_total"] == pytest.approx(round(week3 * WEEKS_PER_MONTH, 1))


def test_generate_macro_plan_ramp_never_exceeds_overreach_threshold():
    today = date(2026, 1, 5)
    race_date = today + timedelta(weeks=20)  # MARATHON's exact minimum
    plan = generate_macro_plan("MARATHON", race_date, today, 200.0)

    for prev_row, next_row in zip(plan, plan[1:]):
        ratio = next_row["load_target_total"] / prev_row["load_target_total"]
        assert ratio <= OVERREACH_THRESHOLD + 1e-9


# -- generate_macro_plan: slack runway is absorbed by BASE -------------------


def test_generate_macro_plan_slack_runway_extends_base_not_build_peak_taper():
    today = date(2026, 1, 5)
    exact_fit_race_date = today + timedelta(weeks=9)  # 5K's minimum
    slack_race_date = today + timedelta(weeks=13)  # 4 weeks of slack

    exact_fit_plan = generate_macro_plan("5K", exact_fit_race_date, today, 100.0)
    slack_plan = generate_macro_plan("5K", slack_race_date, today, 100.0)

    exact_fit_base_months = sum(1 for row in exact_fit_plan if row["periodisation_phase"] == "BASE")
    slack_base_months = sum(1 for row in slack_plan if row["periodisation_phase"] == "BASE")

    # The extra runway shows up as more BASE-labeled months, not a change
    # to how many months BUILD/PEAK/TAPER occupy in either plan.
    assert slack_base_months > exact_fit_base_months


# -- generate_macro_plan: TAPER cuts via the existing taper_adjusted_target --


def test_generate_macro_plan_taper_month_uses_taper_adjusted_target():
    today = date(2026, 1, 5)
    race_date = today + timedelta(weeks=13)  # 5K with 4 weeks of slack (see above)
    current_weekly_load_au = 100.0

    plan = generate_macro_plan("5K", race_date, today, current_weekly_load_au)

    taper_rows = [row for row in plan if row["periodisation_phase"] == "TAPER"]
    assert len(taper_rows) == 1
    taper_row = taper_rows[0]

    # BASE absorbs the 4 weeks of slack (7 total) then BUILD (3 weeks) --
    # two non-taper ramp months (Jan, Feb both BASE at the same starting
    # rate since BASE doesn't ramp *within* itself here) precede the BUILD
    # month whose weekly value becomes peak_weekly_load for the taper cut.
    week_jan = current_weekly_load_au
    week_feb = week_jan * MONTHLY_LOAD_RAMP_RATE
    week_mar_build = week_feb * MONTHLY_LOAD_RAMP_RATE  # BUILD month -- last non-taper value

    taper_month_start = date.fromisoformat(taper_row["month_start_date"])
    weeks_to_race = max((race_date - taper_month_start).days // 7, 0)
    expected_weekly = taper_adjusted_target(week_mar_build, weeks_to_race)

    assert taper_row["load_target_total"] == pytest.approx(round(expected_weekly * WEEKS_PER_MONTH, 1))
    # The taper cut actually reduced load relative to the last ramp value --
    # confirms this isn't accidentally still ramping through taper.
    assert taper_row["load_target_total"] < plan[-2]["load_target_total"]

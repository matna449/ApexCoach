import pytest

from apex_coach.services.load_calculator import (
    calculate_hr_based_load,
    calculate_load_au,
    calculate_recovery_load,
    calculate_rpe_based_load,
    grade_adjustment_factor,
)


@pytest.mark.parametrize(
    "grade_pct, expected",
    [(-2, 1.00), (0, 1.00), (2, 1.05), (5, 1.12), (8, 1.22), (15, 1.35)],
)
def test_grade_adjustment_factor_tiers(grade_pct, expected):
    assert grade_adjustment_factor(grade_pct) == expected


def test_hr_based_load_matches_formula():
    # 60 min * 150 bpm * 1.0 flat / 1000 = 9.0 AU
    assert calculate_hr_based_load(60, 150, grade_pct=0) == pytest.approx(9.0)


def test_hr_based_load_applies_grade_factor():
    # 60 * 150 * 1.12 / 1000 = 10.08
    assert calculate_hr_based_load(60, 150, grade_pct=5) == pytest.approx(10.08)


def test_rpe_based_load_matches_worked_example():
    # "RPE 6 for 60 min = 60 AU"
    assert calculate_rpe_based_load(60, 6) == pytest.approx(60.0)


def test_recovery_load_matches_formula():
    assert calculate_recovery_load(60) == pytest.approx(18.0)


def test_calculate_load_au_dispatches_by_activity_type():
    assert calculate_load_au("Run", 60, avg_hr_bpm=150, grade_pct=0) == pytest.approx(9.0)
    assert calculate_load_au("WeightTraining", 60, rpe=6) == pytest.approx(60.0)
    assert calculate_load_au("Yoga", 60) == pytest.approx(18.0)


def test_calculate_load_au_modality_swap_still_hr_based():
    # A HIIT session executed as a Ride (modality swap) still gets HR-based
    # scoring — dispatch is on activity_type, not the planned session_type.
    assert calculate_load_au("Ride", 45, avg_hr_bpm=160, grade_pct=0) == pytest.approx(7.2)


def test_calculate_load_au_requires_avg_hr_for_hr_based():
    with pytest.raises(ValueError):
        calculate_load_au("Run", 60)


def test_calculate_load_au_requires_rpe_for_rpe_based():
    with pytest.raises(ValueError):
        calculate_load_au("WeightTraining", 60)


def test_calculate_load_au_rejects_unknown_activity_type():
    with pytest.raises(ValueError):
        calculate_load_au("Kayaking", 60)

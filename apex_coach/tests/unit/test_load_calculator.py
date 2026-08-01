import pytest

from apex_coach.services.load_calculator import (
    calculate_hr_based_load,
    calculate_load_au,
    calculate_recovery_load,
    calculate_rpe_based_load,
    invert_duration_for_target_load,
)

# duration=60, avg_hr=150, resting=50, max_hr=190 -> delta_hr_ratio = 100/140
# Independently computed (not derived from the function under test):
# ratio = 0.7142857142857143
# male:   60 * ratio * 0.64 * e^(1.92*ratio) = 108.09535934022335
# female: 60 * ratio * 0.64 * e^(1.67*ratio) = 90.41790987210604
MALE_TRIMP = 108.09535934022335
FEMALE_TRIMP = 90.41790987210604


def test_hr_based_load_matches_male_trimp_worked_example():
    assert calculate_hr_based_load(60, 150, 50, 190, "MALE") == pytest.approx(MALE_TRIMP)


def test_hr_based_load_matches_female_trimp_worked_example():
    assert calculate_hr_based_load(60, 150, 50, 190, "FEMALE") == pytest.approx(FEMALE_TRIMP)


def test_hr_based_load_rejects_unknown_sex():
    with pytest.raises(ValueError):
        calculate_hr_based_load(60, 150, 50, 190, "OTHER")


def test_hr_based_load_rejects_max_hr_not_greater_than_resting_hr():
    with pytest.raises(ValueError):
        calculate_hr_based_load(60, 150, 190, 190, "MALE")


def test_rpe_based_load_matches_worked_example():
    # "RPE 6 for 60 min = 60 AU"
    assert calculate_rpe_based_load(60, 6) == pytest.approx(60.0)


def test_recovery_load_matches_formula():
    assert calculate_recovery_load(60) == pytest.approx(18.0)


def test_calculate_load_au_dispatches_by_activity_type():
    assert calculate_load_au(
        "Run", 60, avg_hr_bpm=150, resting_hr=50, max_hr=190, sex="MALE"
    ) == pytest.approx(MALE_TRIMP)
    assert calculate_load_au("WeightTraining", 60, rpe=6) == pytest.approx(60.0)
    assert calculate_load_au("Yoga", 60) == pytest.approx(18.0)


def test_calculate_load_au_modality_swap_still_hr_based():
    # A HIIT session executed as a Ride (modality swap) still gets HR-based
    # scoring — dispatch is on activity_type, not the planned session_type.
    assert calculate_load_au(
        "Ride", 60, avg_hr_bpm=150, resting_hr=50, max_hr=190, sex="MALE"
    ) == pytest.approx(MALE_TRIMP)


@pytest.mark.parametrize(
    "kwargs",
    [
        {"resting_hr": 50, "max_hr": 190, "sex": "MALE"},  # missing avg_hr_bpm
        {"avg_hr_bpm": 150, "max_hr": 190, "sex": "MALE"},  # missing resting_hr
        {"avg_hr_bpm": 150, "resting_hr": 50, "sex": "MALE"},  # missing max_hr
        {"avg_hr_bpm": 150, "resting_hr": 50, "max_hr": 190},  # missing sex
    ],
)
def test_calculate_load_au_requires_all_trimp_inputs_for_hr_based(kwargs):
    with pytest.raises(ValueError):
        calculate_load_au("Run", 60, **kwargs)


def test_calculate_load_au_requires_rpe_for_rpe_based():
    with pytest.raises(ValueError):
        calculate_load_au("WeightTraining", 60)


def test_calculate_load_au_rejects_unknown_activity_type():
    with pytest.raises(ValueError):
        calculate_load_au("Kayaking", 60)


# F19.2 (#118): invert_duration_for_target_load is the algebraic inverse of
# calculate_hr_based_load, solved for duration given a fixed avg_hr. Reuses
# the exact worked example above (duration=60, avg_hr=150, resting=50,
# max_hr=190) in reverse: feeding MALE_TRIMP/FEMALE_TRIMP back in as the
# target_au should recover duration=60.


def test_invert_duration_for_target_load_is_inverse_of_hr_based_load_male():
    assert invert_duration_for_target_load(MALE_TRIMP, 150, 50, 190, "MALE") == pytest.approx(60.0)


def test_invert_duration_for_target_load_is_inverse_of_hr_based_load_female():
    assert invert_duration_for_target_load(FEMALE_TRIMP, 150, 50, 190, "FEMALE") == pytest.approx(
        60.0
    )


def test_invert_duration_for_target_load_rejects_unknown_sex():
    with pytest.raises(ValueError):
        invert_duration_for_target_load(100.0, 150, 50, 190, "OTHER")


def test_invert_duration_for_target_load_rejects_max_hr_not_greater_than_resting_hr():
    with pytest.raises(ValueError):
        invert_duration_for_target_load(100.0, 150, 190, 190, "MALE")

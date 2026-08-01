import pytest

from apex_coach.services.zone_calculator import calculate_zones, zone_midpoint


@pytest.mark.parametrize(
    "max_hr, resting_hr, zone2, zone4",
    [
        # Values recomputed from the HRR formula with rounding — see docs/adr/0009.
        # Logic Spec §8.2's original table only had row 1 right; rows 2-6 didn't
        # match the documented formula under either rounding or truncation.
        (192, 48, (134, 149), (163, 178)),  # Reference case
        (185, 52, (132, 145), (158, 172)),  # Slightly lower max HR
        (200, 55, (142, 157), (171, 185)),  # High max HR, higher resting HR
        (192, 40, (131, 146), (162, 177)),  # Low resting HR, very fit state
        (192, 60, (139, 152), (166, 179)),  # High resting HR, fatigued state
        (180, 55, (130, 143), (155, 167)),  # Low max HR athlete
    ],
)
def test_calculate_zones_matches_logic_spec_table(max_hr, resting_hr, zone2, zone4):
    zones = calculate_zones(max_hr, resting_hr)
    assert zones["zone2"] == zone2
    assert zones["zone4"] == zone4


def test_calculate_zones_returns_all_5_zones_matching_sdd_worked_example():
    zones = calculate_zones(max_hr=192, resting_hr=48)

    assert zones == {
        "zone1": (120, 134),
        "zone2": (134, 149),
        "zone3": (149, 163),
        "zone4": (163, 178),
        "zone5": (178, 192),
    }


def test_zone5_upper_bound_is_exactly_max_hr():
    zones = calculate_zones(max_hr=192, resting_hr=48)
    assert zones["zone5"][1] == 192


def test_calculate_zones_rejects_resting_hr_at_or_above_max_hr():
    with pytest.raises(ValueError):
        calculate_zones(max_hr=150, resting_hr=150)

    with pytest.raises(ValueError):
        calculate_zones(max_hr=150, resting_hr=160)


def test_zone_midpoint_is_average_of_bounds():
    assert zone_midpoint((134, 148)) == 141.0
    assert zone_midpoint((162, 176)) == 169.0

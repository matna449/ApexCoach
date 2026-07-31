import pytest

from apex_coach.services.session_scorer import (
    WARMUP_SECONDS,
    compute_execution_score,
    compute_hr_drift_ratio,
    detect_overpush,
    detect_underpush,
    score_hr_drift,
    score_load_delta,
    score_rpe_alignment,
    score_session,
    score_time_in_zone,
)

ZONE4 = (163, 178)  # matches SDD §5.1's worked example (Max HR 192, RHR 48)
ZONE2 = (134, 149)


# -- score_time_in_zone — §6.2, 10-minute warm-up exclusion -----------------


def test_time_in_zone_excludes_warmup_and_computes_pct():
    hr_data = [100.0] * WARMUP_SECONDS + [150.0] * 80 + [100.0] * 20
    zone_min, zone_max = 140, 160

    score = score_time_in_zone(hr_data, "Threshold", zone_min, zone_max)

    assert score == 80.0


def test_time_in_zone_returns_none_for_strength():
    hr_data = [150.0] * (WARMUP_SECONDS + 100)
    assert score_time_in_zone(hr_data, "Strength", 100, 200) is None


def test_time_in_zone_raises_when_shorter_than_warmup():
    hr_data = [150.0] * 100
    with pytest.raises(ValueError):
        score_time_in_zone(hr_data, "Threshold", 140, 160)


# -- score_hr_drift — §6.2 --------------------------------------------------


@pytest.mark.parametrize(
    "second_half_hr, expected_score",
    [
        (103.0, 100.0),  # ratio 0.03 exactly
        (105.0, 85.0),  # ratio 0.05 exactly
        (108.0, 70.0),  # ratio 0.08 exactly
        (112.0, 50.0),  # ratio 0.12 exactly
        (113.0, 30.0),  # ratio 0.13
    ],
)
def test_hr_drift_zone2_tiers(second_half_hr, expected_score):
    # first_half_avg=100 chosen so second_half_hr's own value equals
    # 100*(1+ratio) exactly, avoiding float multiplication error at boundaries.
    hr_data = [100.0] * 5 + [second_half_hr] * 5

    assert score_hr_drift(hr_data, "Zone2_Long") == expected_score


@pytest.mark.parametrize("session_type", ["HIIT", "Threshold"])
def test_hr_drift_fixed_80_for_key_sessions(session_type):
    hr_data = [100.0, 200.0, 50.0, 175.0]  # arbitrary — must not affect score
    assert score_hr_drift(hr_data, session_type) == 80.0


@pytest.mark.parametrize("session_type", ["Strength", "Recovery"])
def test_hr_drift_none_for_uncovered_session_types(session_type):
    hr_data = [100.0] * 10
    assert score_hr_drift(hr_data, session_type) is None


# -- score_rpe_alignment — §6.2 ----------------------------------------------


@pytest.mark.parametrize(
    "actual_rpe, expected_score",
    [(9, 100.0), (8, 85.0), (7, 65.0), (6, 40.0), (5, 15.0), (1, 15.0)],
)
def test_rpe_alignment_hiit_tiers(actual_rpe, expected_score):
    # HIIT's expected_rpe is 9
    assert score_rpe_alignment("HIIT", actual_rpe) == expected_score


def test_rpe_alignment_symmetric_around_expected():
    # Threshold expected_rpe=7; delta of 1 in either direction -> 85
    assert score_rpe_alignment("Threshold", 6) == 85.0
    assert score_rpe_alignment("Threshold", 8) == 85.0


# -- score_load_delta — §6.2 -------------------------------------------------


@pytest.mark.parametrize(
    "actual, planned, expected_score",
    [
        (100, 100, 100.0),  # ratio 0
        (105, 100, 100.0),  # ratio 0.05
        (110, 100, 90.0),  # ratio 0.10
        (120, 100, 75.0),  # ratio 0.20
        (135, 100, 55.0),  # ratio 0.35
        (136, 100, 30.0),  # ratio > 0.35
    ],
)
def test_load_delta_tiers(actual, planned, expected_score):
    assert score_load_delta(actual, planned) == expected_score


# -- compute_execution_score — renormalization (docs/adr/0014) -------------


def test_execution_score_all_four_components():
    components = {
        "time_in_zone_score": 100.0,
        "hr_drift_score": 100.0,
        "rpe_alignment_score": 100.0,
        "load_delta_score": 100.0,
    }
    assert compute_execution_score(components) == pytest.approx(100.0)


def test_execution_score_renormalizes_for_strength_two_components():
    # Strength: only rpe (0.20) + load_delta (0.10) apply, renormalized to
    # 2/3 + 1/3 of the total.
    components = {
        "time_in_zone_score": None,
        "hr_drift_score": None,
        "rpe_alignment_score": 100.0,
        "load_delta_score": 0.0,
    }
    # 100 * (0.20/0.30) + 0 * (0.10/0.30) = 66.67
    assert compute_execution_score(components) == pytest.approx(66.667, abs=0.01)


def test_execution_score_renormalizes_for_recovery_three_components():
    components = {
        "time_in_zone_score": 100.0,
        "hr_drift_score": None,
        "rpe_alignment_score": 0.0,
        "load_delta_score": 0.0,
    }
    # applicable weight = 0.45+0.20+0.10 = 0.75; time_in_zone contributes
    # 100 * (0.45/0.75) = 60
    assert compute_execution_score(components) == pytest.approx(60.0)


def test_execution_score_raises_when_no_components_applicable():
    with pytest.raises(ValueError):
        compute_execution_score(
            {
                "time_in_zone_score": None,
                "hr_drift_score": None,
                "rpe_alignment_score": None,
                "load_delta_score": None,
            }
        )


# -- overpush / underpush — §6.3, independent of execution_score ----------


def test_overpush_threshold_triggers_above_15_pct():
    zone4_max = 178
    hr_data = [190.0] * 16 + [150.0] * 84  # 16% over zone4_max
    assert detect_overpush(hr_data, "Threshold", zone4_max) is True


def test_overpush_threshold_does_not_trigger_at_exactly_15_pct():
    zone4_max = 178
    hr_data = [190.0] * 15 + [150.0] * 85  # exactly 15%, not > 15%
    assert detect_overpush(hr_data, "Threshold", zone4_max) is False


def test_overpush_zone2_triggers_above_10_pct():
    zone2_max = 149
    hr_data = [160.0] * 11 + [140.0] * 89
    assert detect_overpush(hr_data, "Zone2_Long", zone2_max) is True


def test_overpush_not_applicable_for_hiit():
    assert detect_overpush([200.0] * 100, "HIIT", 178) is False


def test_underpush_hiit_triggers_above_40_pct_of_non_warmup():
    zone4_max = 178
    non_warmup_under = [170.0] * 41  # 41% below zone4_max (never reached zone5)
    non_warmup_over = [180.0] * 59
    hr_data = [150.0] * WARMUP_SECONDS + non_warmup_under + non_warmup_over

    assert detect_underpush(hr_data, "HIIT", 163, zone4_max) is True


def test_underpush_hiit_raises_when_shorter_than_warmup():
    with pytest.raises(ValueError):
        detect_underpush([150.0] * 100, "HIIT", 163, 178)


def test_underpush_threshold_triggers_when_avg_below_zone4_min():
    zone4_min, zone4_max = 163, 178
    hr_data = [150.0] * 100  # avg well below zone4_min

    assert detect_underpush(hr_data, "Threshold", zone4_min, zone4_max) is True


def test_underpush_not_applicable_for_zone2():
    assert detect_underpush([100.0] * 100, "Zone2_Long", 134, 149) is False


# -- score_session — end to end ---------------------------------------------


def test_score_session_threshold_end_to_end():
    hr_data = [110.0] * WARMUP_SECONDS + [165.0] * 2647
    zone_boundaries = {"zone4": ZONE4, "zone2": ZONE2}

    result = score_session(
        session_type="Threshold",
        hr_data=hr_data,
        zone_boundaries=zone_boundaries,
        actual_rpe=7,
        actual_load_au=105,
        planned_load_au=100,
    )

    assert 0 <= result["execution_score"] <= 100
    assert result["score_breakdown"]["hr_drift_score"] == 80.0
    assert result["score_breakdown"]["rpe_alignment_score"] == 100.0
    assert isinstance(result["overpush_flag"], bool)
    assert isinstance(result["underpush_flag"], bool)


def test_score_session_strength_has_no_time_in_zone_or_hr_drift():
    hr_data = [130.0] * 2000

    result = score_session(
        session_type="Strength",
        hr_data=hr_data,
        zone_boundaries=None,
        actual_rpe=6,
        actual_load_au=100,
        planned_load_au=100,
    )

    assert result["score_breakdown"]["time_in_zone_score"] is None
    assert result["score_breakdown"]["hr_drift_score"] is None
    assert result["score_breakdown"]["rpe_alignment_score"] == 100.0
    assert result["overpush_flag"] is False
    assert result["underpush_flag"] is False


# -- input validation (Copilot review) --------------------------------------


def test_compute_hr_drift_ratio_rejects_too_short_stream():
    with pytest.raises(ValueError):
        compute_hr_drift_ratio([100.0])
    with pytest.raises(ValueError):
        compute_hr_drift_ratio([])


def test_compute_hr_drift_ratio_rejects_zero_first_half_average():
    with pytest.raises(ValueError):
        compute_hr_drift_ratio([0.0, 0.0, 100.0, 100.0])


def test_score_load_delta_rejects_non_positive_planned_load():
    with pytest.raises(ValueError):
        score_load_delta(100, 0)
    with pytest.raises(ValueError):
        score_load_delta(100, -10)


def test_detect_overpush_rejects_empty_hr_data():
    with pytest.raises(ValueError):
        detect_overpush([], "Threshold", 178)


def test_detect_underpush_threshold_rejects_empty_hr_data():
    with pytest.raises(ValueError):
        detect_underpush([], "Threshold", 163, 178)


def test_score_session_rejects_unknown_session_type():
    with pytest.raises(ValueError):
        score_session(
            session_type="Yoga",
            hr_data=[150.0] * 1000,
            zone_boundaries=None,
            actual_rpe=5,
            actual_load_au=100,
            planned_load_au=100,
        )


def test_score_session_rejects_missing_zone_boundaries_for_hr_paced_session():
    with pytest.raises(ValueError):
        score_session(
            session_type="Threshold",
            hr_data=[150.0] * 1000,
            zone_boundaries=None,
            actual_rpe=7,
            actual_load_au=100,
            planned_load_au=100,
        )

import pytest

from apex_coach.adapters.whoop_adapter import MockWhoopAdapter
from apex_coach.orchestrator.orchestrator import (
    HRVDeltaBand,
    RecoveryBand,
    SorenessBand,
    classify_daily_inputs,
    classify_hrv_delta,
    classify_recovery,
    classify_soreness,
)


# -- classify_recovery — §2.1: 67-100 GREEN, 34-66 YELLOW, 0-33 RED --------


@pytest.mark.parametrize(
    "score, expected",
    [
        (100, RecoveryBand.GREEN),
        (67, RecoveryBand.GREEN),  # lower boundary of GREEN
        (66, RecoveryBand.YELLOW),  # one below GREEN
        (34, RecoveryBand.YELLOW),  # lower boundary of YELLOW
        (33, RecoveryBand.RED),  # one below YELLOW
        (0, RecoveryBand.RED),
    ],
)
def test_classify_recovery_boundaries(score, expected):
    assert classify_recovery(score) == expected


def test_classify_recovery_rejects_out_of_range():
    with pytest.raises(ValueError):
        classify_recovery(101)
    with pytest.raises(ValueError):
        classify_recovery(-1)


# -- classify_hrv_delta — §2.2, boundaries resolved per docs/adr/0013 -----


@pytest.mark.parametrize(
    "delta, expected",
    [
        (5.01, HRVDeltaBand.POSITIVE),
        (100, HRVDeltaBand.POSITIVE),
        (5.0, HRVDeltaBand.NEUTRAL),  # Neutral owns its stated inclusive bound
        (0, HRVDeltaBand.NEUTRAL),
        (-5.0, HRVDeltaBand.NEUTRAL),  # Neutral owns -5, not Negative
        (-5.01, HRVDeltaBand.NEGATIVE),
        (-10.0, HRVDeltaBand.NEGATIVE),  # Negative owns -10, not Strong Neg
        (-10.01, HRVDeltaBand.STRONG_NEG),
        (-100, HRVDeltaBand.STRONG_NEG),
    ],
)
def test_classify_hrv_delta_boundaries(delta, expected):
    assert classify_hrv_delta(delta) == expected


# -- classify_soreness — §2.3: direct 1-5 mapping ---------------------------


@pytest.mark.parametrize(
    "score, expected",
    [
        (1, SorenessBand.NONE),
        (2, SorenessBand.MILD),
        (3, SorenessBand.MODERATE),
        (4, SorenessBand.HIGH),
        (5, SorenessBand.SEVERE),
    ],
)
def test_classify_soreness_maps_every_score(score, expected):
    assert classify_soreness(score) == expected


def test_classify_soreness_rejects_out_of_range():
    with pytest.raises(ValueError):
        classify_soreness(0)
    with pytest.raises(ValueError):
        classify_soreness(6)


# -- classify_daily_inputs — combines all three, using the real WhoopDailyPayload


def test_classify_daily_inputs_combines_all_three_bands():
    payload = MockWhoopAdapter().get_daily_payload("2026-07-30")

    # Mock payload: whoop_recovery_pct=62.0, whoop_hrv_ms=71.4 (API Contract §2.2)
    result = classify_daily_inputs(payload, muscle_soreness=3, hrv_30d_avg_ms=78.2)

    assert result["recovery_band"] == RecoveryBand.YELLOW
    assert result["hrv_delta_ms"] == pytest.approx(71.4 - 78.2)
    assert result["hrv_delta_band"] == HRVDeltaBand.NEGATIVE
    assert result["soreness_band"] == SorenessBand.MODERATE
    assert result["recovery_pct"] == 62.0


def test_classify_daily_inputs_raises_when_recovery_missing():
    payload = MockWhoopAdapter().get_daily_payload("2026-07-30")
    payload.recovery.score = None

    with pytest.raises(ValueError):
        classify_daily_inputs(payload, muscle_soreness=3, hrv_30d_avg_ms=78.2)


def test_classify_daily_inputs_raises_when_hrv_missing():
    payload = MockWhoopAdapter().get_daily_payload("2026-07-30")
    payload.recovery.score.hrv_rmssd_milli = None

    with pytest.raises(ValueError):
        classify_daily_inputs(payload, muscle_soreness=3, hrv_30d_avg_ms=78.2)

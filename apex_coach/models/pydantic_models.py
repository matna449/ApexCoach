"""Typed API payload models (API Contract §2). See docs/adr/0011 for
WhoopDailyPayload combining all 3 WHOOP endpoints.
"""

from datetime import datetime
from typing import Literal

from pydantic import BaseModel, field_validator

ScoreState = Literal["SCORED", "PENDING_SCORE", "UNSCORABLE"]


class WhoopRecoveryScore(BaseModel):
    recovery_score: float
    resting_heart_rate: float
    hrv_rmssd_milli: float
    spo2_percentage: float | None = None
    skin_temp_celsius: float | None = None


class WhoopRecovery(BaseModel):
    cycle_id: int
    created_at: datetime
    score_state: ScoreState
    score: WhoopRecoveryScore | None = None

    @field_validator("score_state")
    @classmethod
    def must_be_scored(cls, v: str) -> str:
        if v != "SCORED":
            raise ValueError(f"Recovery not yet scored: {v}")
        return v


class WhoopCycleScore(BaseModel):
    strain: float
    kilojoule: float
    average_heart_rate: int
    max_heart_rate: int


class WhoopCycle(BaseModel):
    id: int
    created_at: datetime
    score_state: ScoreState
    score: WhoopCycleScore | None = None

    @field_validator("score_state")
    @classmethod
    def must_be_scored(cls, v: str) -> str:
        if v != "SCORED":
            raise ValueError(f"Cycle not yet scored: {v}")
        return v


class WhoopSleepStageSummary(BaseModel):
    total_in_bed_time_milli: int
    total_awake_time_milli: int


class WhoopSleepScore(BaseModel):
    sleep_performance_percentage: float
    stage_summary: WhoopSleepStageSummary

    @property
    def total_sleep_hours(self) -> float:
        asleep_milli = (
            self.stage_summary.total_in_bed_time_milli
            - self.stage_summary.total_awake_time_milli
        )
        return asleep_milli / 1000 / 60 / 60


class WhoopSleep(BaseModel):
    id: str
    created_at: datetime
    score_state: ScoreState
    score: WhoopSleepScore | None = None

    @field_validator("score_state")
    @classmethod
    def must_be_scored(cls, v: str) -> str:
        if v != "SCORED":
            raise ValueError(f"Sleep not yet scored: {v}")
        return v


class WhoopDailyPayload(BaseModel):
    date: str
    recovery: WhoopRecovery
    cycle: WhoopCycle
    sleep: WhoopSleep

    @property
    def whoop_recovery_pct(self) -> float | None:
        return self.recovery.score.recovery_score if self.recovery.score else None

    @property
    def whoop_hrv_ms(self) -> float | None:
        return self.recovery.score.hrv_rmssd_milli if self.recovery.score else None

    @property
    def whoop_rhr_bpm(self) -> float | None:
        return self.recovery.score.resting_heart_rate if self.recovery.score else None

    @property
    def whoop_strain(self) -> float | None:
        return self.cycle.score.strain if self.cycle.score else None

    @property
    def whoop_sleep_hours(self) -> float | None:
        return self.sleep.score.total_sleep_hours if self.sleep.score else None


class StravaSplit(BaseModel):
    split: int
    distance: float
    elapsed_time: int
    elevation_difference: float
    average_speed: float
    average_heartrate: float | None = None
    average_grade_adjusted_speed: float | None = None


class Activity(BaseModel):
    # int for Strava's numeric ids; str for intervals.icu's prefixed ids
    # (e.g. "i171360215", confirmed against a real account — F18.5/#94).
    id: int | str
    name: str
    type: str
    start_date: datetime
    elapsed_time: int  # seconds
    distance: float  # metres
    total_elevation_gain: float  # metres
    average_speed: float  # m/s
    average_heartrate: float | None = None
    max_heartrate: float | None = None
    has_heartrate: bool = False
    splits_metric: list[StravaSplit] = []

    @property
    def pace_sec_per_km(self) -> float | None:
        if self.average_speed and self.average_speed > 0:
            return 1000 / self.average_speed
        return None

    @property
    def grade_pct(self) -> float:
        if self.distance > 0:
            return (self.total_elevation_gain / self.distance) * 100
        return 0.0


class ActivityStreamSeries(BaseModel):
    data: list[float]
    series_type: str
    original_size: int
    resolution: str | None = None


class ActivityStream(BaseModel):
    heartrate: ActivityStreamSeries
    time: ActivityStreamSeries
    distance: ActivityStreamSeries

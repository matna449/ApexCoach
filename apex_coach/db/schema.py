"""SQLAlchemy Core table definitions for the Apex Coach v1 schema.

Source of truth: SDD §4 (SQLite Data Schema) and API Integration Contract §5
(Token Storage Schema). Column names, types, and keys mirror those documents
exactly, except where docs/adr/0004 records a deliberate deviation.
"""

import uuid
from datetime import datetime, timezone

import sqlalchemy as sa

metadata = sa.MetaData()


def _uuid() -> str:
    return str(uuid.uuid4())


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


daily_metrics = sa.Table(
    "daily_metrics",
    metadata,
    sa.Column("id", sa.String, primary_key=True, default=_uuid),
    sa.Column("date", sa.String, nullable=False, unique=True),
    sa.Column("whoop_recovery_pct", sa.Float, nullable=True),
    sa.Column("whoop_hrv_ms", sa.Float, nullable=True),
    sa.Column("whoop_rhr_bpm", sa.Integer, nullable=True),
    sa.Column("whoop_strain", sa.Float, nullable=True),
    sa.Column("whoop_sleep_hours", sa.Float, nullable=True),
    sa.Column("hrv_30d_avg_ms", sa.Float, nullable=True),
    sa.Column("muscle_soreness", sa.Integer, nullable=True),
    sa.Column("subjective_energy", sa.Integer, nullable=True),
    sa.Column("sleep_quality_felt", sa.Integer, nullable=True),
    sa.Column("health_check_json", sa.Text, nullable=True),
    sa.Column("created_at", sa.String, nullable=False, default=_now_iso),
)

hr_zones = sa.Table(
    "hr_zones",
    metadata,
    sa.Column("id", sa.String, primary_key=True, default=_uuid),
    sa.Column(
        "date", sa.String, sa.ForeignKey("daily_metrics.date"), nullable=False
    ),
    sa.Column("max_hr_bpm", sa.Integer, nullable=True),
    sa.Column("rest_hr_bpm", sa.Integer, nullable=True),
    sa.Column("zone1_min", sa.Integer, nullable=True),
    sa.Column("zone1_max", sa.Integer, nullable=True),
    sa.Column("zone2_min", sa.Integer, nullable=True),
    sa.Column("zone2_max", sa.Integer, nullable=True),
    sa.Column("zone3_min", sa.Integer, nullable=True),
    sa.Column("zone3_max", sa.Integer, nullable=True),
    sa.Column("zone4_min", sa.Integer, nullable=True),
    sa.Column("zone4_max", sa.Integer, nullable=True),
    sa.Column("zone5_min", sa.Integer, nullable=True),
    sa.Column("zone5_max", sa.Integer, nullable=True),
    sa.Column("created_at", sa.String, nullable=False, default=_now_iso),
)

activities = sa.Table(
    "activities",
    metadata,
    sa.Column("id", sa.String, primary_key=True, default=_uuid),
    sa.Column("strava_id", sa.String, nullable=False, unique=True),
    sa.Column(
        "date", sa.String, sa.ForeignKey("daily_metrics.date"), nullable=False
    ),
    sa.Column("activity_type", sa.String, nullable=True),
    sa.Column("intended_session_type", sa.String, nullable=True),
    sa.Column("duration_seconds", sa.Integer, nullable=True),
    sa.Column("distance_metres", sa.Float, nullable=True),
    sa.Column("elevation_gain_m", sa.Float, nullable=True),
    sa.Column("avg_hr_bpm", sa.Integer, nullable=True),
    sa.Column("max_hr_bpm", sa.Integer, nullable=True),
    sa.Column("avg_pace_sec_per_km", sa.Float, nullable=True),
    sa.Column("grade_adj_pace", sa.Float, nullable=True),
    sa.Column("load_score", sa.Float, nullable=True),
    sa.Column("rpe", sa.Integer, nullable=True),
    sa.Column("strava_raw_json", sa.Text, nullable=True),
    sa.Column("created_at", sa.String, nullable=False, default=_now_iso),
)

session_scores = sa.Table(
    "session_scores",
    metadata,
    sa.Column("id", sa.String, primary_key=True, default=_uuid),
    sa.Column(
        "activity_id", sa.String, sa.ForeignKey("activities.id"), nullable=False
    ),
    sa.Column("execution_score", sa.Float, nullable=True),
    sa.Column("time_in_zone_pct", sa.Float, nullable=True),
    sa.Column("hr_drift_coeff", sa.Float, nullable=True),
    # SDD §4.5 documents these as TEXT "TRUE"/"FALSE"; corrected to BOOLEAN
    # per docs/adr/0004 — SQLAlchemy renders this portably on both dialects.
    sa.Column("overpush_flag", sa.Boolean, nullable=True),
    sa.Column("underpush_flag", sa.Boolean, nullable=True),
    sa.Column("score_breakdown_json", sa.Text, nullable=True),
    sa.Column("created_at", sa.String, nullable=False, default=_now_iso),
)

decisions = sa.Table(
    "decisions",
    metadata,
    sa.Column("id", sa.String, primary_key=True, default=_uuid),
    sa.Column(
        "date", sa.String, sa.ForeignKey("daily_metrics.date"), nullable=False
    ),
    sa.Column("scheduled_session", sa.String, nullable=True),
    sa.Column(
        "recommendation",
        sa.Enum(
            "GO",
            "MODIFY",
            "MODALITY_SWAP",
            "ABORT",
            name="decision_recommendation",
            native_enum=False,
            create_constraint=True,
        ),
        nullable=True,
    ),
    sa.Column("rationale_json", sa.Text, nullable=True),
    sa.Column("llm_explanation", sa.Text, nullable=True),
    sa.Column("athlete_override", sa.String, nullable=True),
    sa.Column("created_at", sa.String, nullable=False, default=_now_iso),
)

weekly_plans = sa.Table(
    "weekly_plans",
    metadata,
    sa.Column("id", sa.String, primary_key=True, default=_uuid),
    sa.Column("week_start_date", sa.String, nullable=False, unique=True),
    sa.Column("planned_sessions_json", sa.Text, nullable=True),
    sa.Column("adapted_plan_json", sa.Text, nullable=True),
    # F19.2 (#118): pure-engine-generated structured HR-zone breakdown,
    # persisted once at generation time — not regenerated on read
    # (regeneration is F19.3's explicit action). PRD #111.
    sa.Column("generated_structure_json", sa.Text, nullable=True),
    # F19.6 (#121): day -> intervals.icu eventId, e.g. {"Monday": "12345"}.
    # Lets a re-push update the existing calendar event in place rather
    # than creating a duplicate. PRD #111, docs/adr/0027.
    sa.Column("pushed_event_ids_json", sa.Text, nullable=True),
    sa.Column("load_target", sa.Float, nullable=True),
    sa.Column("load_actual", sa.Float, nullable=True),
    sa.Column("skipped_sessions", sa.Text, nullable=True),
    sa.Column(
        "week_status",
        sa.Enum(
            "ON_TRACK",
            "LOAD_DEFICIT",
            "OVERREACHED",
            "RECOVERY_WEEK",
            "COMPLETE",
            name="week_status",
            native_enum=False,
            create_constraint=True,
        ),
        nullable=True,
    ),
    sa.Column("created_at", sa.String, nullable=False, default=_now_iso),
    sa.Column("updated_at", sa.String, nullable=True, onupdate=_now_iso),
)

monthly_targets = sa.Table(
    "monthly_targets",
    metadata,
    sa.Column("id", sa.String, primary_key=True, default=_uuid),
    sa.Column("month_start_date", sa.String, nullable=False, unique=True),
    sa.Column(
        "periodisation_phase",
        sa.Enum(
            "BASE",
            "BUILD",
            "PEAK",
            "TAPER",
            "RECOVERY",
            name="periodisation_phase",
            native_enum=False,
            create_constraint=True,
        ),
        nullable=True,
    ),
    sa.Column("load_target_total", sa.Float, nullable=True),
    sa.Column("load_actual_total", sa.Float, nullable=True),
    sa.Column("hrv_trend_json", sa.Text, nullable=True),
    sa.Column("race_date", sa.String, nullable=True),
    sa.Column("month_summary_json", sa.Text, nullable=True),
    sa.Column("created_at", sa.String, nullable=False, default=_now_iso),
    sa.Column("updated_at", sa.String, nullable=True, onupdate=_now_iso),
)

# PRD #138 (F20.1): one row per training-block goal -- a fourth, higher
# horizon (Macro/Race-Goal) above Monthly in the Three-Horizon Model
# (ADR-0002), with advisory/initial-value-only authority: a race goal seeds
# monthly_targets rows (once F20.3's accept step ships) but never overrides
# Daily/Weekly/Monthly's existing authority hierarchy. At most one ACTIVE
# row at a time (docs/adr/0023, single-athlete system) -- enforced by the
# partial unique index below (ix_race_goals_one_active), not just at the
# repository layer.
race_goals = sa.Table(
    "race_goals",
    metadata,
    sa.Column("id", sa.String, primary_key=True, default=_uuid),
    sa.Column(
        "goal_distance",
        sa.Enum(
            "5K",
            "10K",
            "HALF_MARATHON",
            "MARATHON",
            name="goal_distance",
            native_enum=False,
            create_constraint=True,
        ),
        nullable=False,
    ),
    sa.Column("target_race_date", sa.String, nullable=False),
    sa.Column(
        "status",
        sa.Enum(
            "ACTIVE",
            "COMPLETED",
            "ABANDONED",
            name="race_goal_status",
            native_enum=False,
            create_constraint=True,
        ),
        nullable=False,
    ),
    sa.Column("created_at", sa.String, nullable=False, default=_now_iso),
    sa.Column("updated_at", sa.String, nullable=True, onupdate=_now_iso),
)

sa.Index(
    "ix_race_goals_one_active",
    race_goals.c.status,
    unique=True,
    sqlite_where=race_goals.c.status == "ACTIVE",
)

# Single-row athlete config (docs/adr/0023: single-user, no per-athlete
# keying needed) — max_hr/sex feed the Banister TRIMP load calculation
# (docs/adr/0024); baseline_resting_hr is a fallback only, the TRIMP
# calculation prefers the day-of WHOOP resting HR (daily_metrics.whoop_rhr_bpm)
# when available.
athlete_profile = sa.Table(
    "athlete_profile",
    metadata,
    sa.Column("id", sa.String, primary_key=True, default=_uuid),
    sa.Column("max_hr", sa.Integer, nullable=True),
    sa.Column("baseline_resting_hr", sa.Integer, nullable=True),
    sa.Column(
        "sex",
        sa.Enum(
            "MALE",
            "FEMALE",
            name="athlete_sex",
            native_enum=False,
            create_constraint=True,
        ),
        nullable=True,
    ),
    # F18.4/F18.6 (#93/#95): which adapter sync-session dispatches to.
    # Nullable — a NULL/missing row is treated as the CLI's
    # DEFAULT_ACTIVITY_SYNC_PROVIDER (INTERVALS_ICU, docs/adr/0025, PRD #89).
    sa.Column(
        "activity_sync_provider",
        sa.Enum(
            "STRAVA",
            "INTERVALS_ICU",
            name="activity_sync_provider",
            native_enum=False,
            create_constraint=True,
        ),
        nullable=True,
    ),
    sa.Column("created_at", sa.String, nullable=False, default=_now_iso),
    sa.Column("updated_at", sa.String, nullable=True, onupdate=_now_iso),
)

# API Integration Contract §5 — separate from the SDD's main schema, but
# defined here alongside it since schema.py owns all table definitions.
oauth_tokens = sa.Table(
    "oauth_tokens",
    metadata,
    sa.Column("id", sa.String, primary_key=True, default=_uuid),
    sa.Column(
        "provider",
        sa.Enum(
            "WHOOP",
            "STRAVA",
            "INTERVALS_ICU",
            name="oauth_provider",
            native_enum=False,
            create_constraint=True,
        ),
        nullable=False,
        unique=True,
    ),
    sa.Column("access_token", sa.Text, nullable=True),
    sa.Column("refresh_token", sa.Text, nullable=True),
    sa.Column("expires_at", sa.String, nullable=True),
    sa.Column("scope", sa.String, nullable=True),
    sa.Column("updated_at", sa.String, nullable=False, default=_now_iso, onupdate=_now_iso),
)

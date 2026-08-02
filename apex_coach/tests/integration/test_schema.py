import pytest
import sqlalchemy as sa

from apex_coach.db.schema import metadata

EXPECTED_TABLES = {
    "daily_metrics",
    "hr_zones",
    "activities",
    "session_scores",
    "decisions",
    "weekly_plans",
    "monthly_targets",
    "oauth_tokens",
    "athlete_profile",
    "race_goals",
}


def test_schema_creates_cleanly_against_in_memory_sqlite():
    engine = sa.create_engine("sqlite:///:memory:")
    metadata.create_all(engine)

    inspector = sa.inspect(engine)
    assert set(inspector.get_table_names()) == EXPECTED_TABLES


def test_hr_zones_declares_fk_to_daily_metrics_date():
    engine = sa.create_engine("sqlite:///:memory:")
    metadata.create_all(engine)

    inspector = sa.inspect(engine)
    fks = inspector.get_foreign_keys("hr_zones")
    assert any(
        fk["referred_table"] == "daily_metrics" and fk["referred_columns"] == ["date"]
        for fk in fks
    )


def test_session_scores_declares_fk_to_activities_id():
    engine = sa.create_engine("sqlite:///:memory:")
    metadata.create_all(engine)

    inspector = sa.inspect(engine)
    fks = inspector.get_foreign_keys("session_scores")
    assert any(
        fk["referred_table"] == "activities" and fk["referred_columns"] == ["id"]
        for fk in fks
    )


def test_daily_metrics_id_and_created_at_are_populated_by_client_side_default():
    engine = sa.create_engine("sqlite:///:memory:")
    metadata.create_all(engine)

    daily_metrics = metadata.tables["daily_metrics"]
    with engine.begin() as conn:
        conn.execute(daily_metrics.insert().values(date="2026-07-30"))
        row = conn.execute(sa.select(daily_metrics)).one()

    assert row.id is not None
    assert row.created_at is not None
    assert "T" in row.created_at  # ISO 8601, not SQLite's space-separated default


def test_race_goals_partial_unique_index_rejects_a_second_active_row():
    """schema-level backstop for the single-active-race-goal invariant
    (docs/adr/0023) -- PlanRepository.insert_race_goal() already enforces
    this with a friendlier check-then-raise, but this confirms the DB
    constraint itself holds even for a raw insert that bypasses the
    repository layer entirely."""
    engine = sa.create_engine("sqlite:///:memory:")
    metadata.create_all(engine)

    race_goals = metadata.tables["race_goals"]
    with engine.begin() as conn:
        conn.execute(
            race_goals.insert().values(
                goal_distance="5K", target_race_date="2026-09-01", status="ACTIVE"
            )
        )

    with engine.connect() as conn:
        with pytest.raises(sa.exc.IntegrityError):
            conn.execute(
                race_goals.insert().values(
                    goal_distance="MARATHON",
                    target_race_date="2027-04-01",
                    status="ACTIVE",
                )
            )
            conn.commit()


def test_decisions_recommendation_check_constraint_rejects_bad_value():
    engine = sa.create_engine("sqlite:///:memory:")
    metadata.create_all(engine)

    daily_metrics = metadata.tables["daily_metrics"]
    decisions = metadata.tables["decisions"]
    with engine.begin() as conn:
        conn.execute(daily_metrics.insert().values(date="2026-07-30"))

    with engine.connect() as conn:
        with pytest.raises(sa.exc.IntegrityError):
            conn.execute(
                decisions.insert().values(
                    date="2026-07-30", recommendation="NOT_A_REAL_VALUE"
                )
            )
            conn.commit()

"""Sole writer for the engine-authority-hierarchy tables (ADR-0003, ADR-0007).

weekly_plans / monthly_targets are genuinely mutated in place across their
period. decisions is append-only except athlete_override, which — like
activities.rpe (ADR-0006) — is captured after the row already exists and is
only settable via a dedicated targeted update.
"""

import sqlalchemy as sa

from apex_coach.db.schema import athlete_profile, decisions, monthly_targets, weekly_plans


def _row_to_dict(row) -> dict:
    return dict(row._mapping)


class PlanRepository:
    def __init__(self, engine: sa.engine.Engine):
        self._engine = engine

    # -- weekly_plans -------------------------------------------------------

    def insert_weekly_plan(self, **fields) -> str:
        with self._engine.begin() as conn:
            result = conn.execute(
                weekly_plans.insert().values(**fields).returning(weekly_plans.c.id)
            )
            return result.scalar_one()

    def update_weekly_plan(self, week_start_date: str, **fields) -> None:
        with self._engine.begin() as conn:
            result = conn.execute(
                weekly_plans.update()
                .where(weekly_plans.c.week_start_date == week_start_date)
                .values(**fields)
            )
            if result.rowcount == 0:
                raise ValueError(
                    f"no weekly_plans row for week_start_date {week_start_date!r}"
                )

    def get_weekly_plan(self, week_start_date: str) -> dict | None:
        with self._engine.begin() as conn:
            row = conn.execute(
                sa.select(weekly_plans).where(
                    weekly_plans.c.week_start_date == week_start_date
                )
            ).one_or_none()
        return _row_to_dict(row) if row is not None else None

    # -- monthly_targets ------------------------------------------------------

    def insert_monthly_target(self, **fields) -> str:
        with self._engine.begin() as conn:
            result = conn.execute(
                monthly_targets.insert()
                .values(**fields)
                .returning(monthly_targets.c.id)
            )
            return result.scalar_one()

    def update_monthly_target(self, month_start_date: str, **fields) -> None:
        with self._engine.begin() as conn:
            result = conn.execute(
                monthly_targets.update()
                .where(monthly_targets.c.month_start_date == month_start_date)
                .values(**fields)
            )
            if result.rowcount == 0:
                raise ValueError(
                    f"no monthly_targets row for month_start_date {month_start_date!r}"
                )

    def get_monthly_target(self, month_start_date: str) -> dict | None:
        with self._engine.begin() as conn:
            row = conn.execute(
                sa.select(monthly_targets).where(
                    monthly_targets.c.month_start_date == month_start_date
                )
            ).one_or_none()
        return _row_to_dict(row) if row is not None else None

    # -- decisions --------------------------------------------------------

    def insert_decision(self, **fields) -> str:
        if "athlete_override" in fields:
            raise ValueError(
                "athlete_override is set via record_athlete_override(), not "
                "insert_decision() — it's captured on a separate timeline from "
                "the engine's recommendation"
            )
        with self._engine.begin() as conn:
            result = conn.execute(
                decisions.insert().values(**fields).returning(decisions.c.id)
            )
            return result.scalar_one()

    def record_athlete_override(self, decision_id: str, athlete_override: str) -> None:
        with self._engine.begin() as conn:
            result = conn.execute(
                decisions.update()
                .where(decisions.c.id == decision_id)
                .values(athlete_override=athlete_override)
            )
            if result.rowcount == 0:
                raise ValueError(f"no decision found for id {decision_id!r}")

    def get_decision(self, date: str) -> dict | None:
        with self._engine.begin() as conn:
            row = conn.execute(
                sa.select(decisions)
                .where(decisions.c.date == date)
                .order_by(decisions.c.created_at.desc())
                .limit(1)
            ).one_or_none()
        return _row_to_dict(row) if row is not None else None

    # -- athlete_profile ----------------------------------------------------
    # Single global row (docs/adr/0023: single-user, no per-athlete keying) —
    # unlike weekly_plans/monthly_targets there's no natural business key to
    # target an update by, so update_athlete_profile() updates whichever one
    # row exists.

    def insert_athlete_profile(self, **fields) -> str:
        with self._engine.begin() as conn:
            result = conn.execute(
                athlete_profile.insert().values(**fields).returning(athlete_profile.c.id)
            )
            return result.scalar_one()

    def update_athlete_profile(self, **fields) -> None:
        with self._engine.begin() as conn:
            result = conn.execute(athlete_profile.update().values(**fields))
            if result.rowcount == 0:
                raise ValueError("no athlete_profile row exists yet")

    def get_athlete_profile(self) -> dict | None:
        with self._engine.begin() as conn:
            row = conn.execute(sa.select(athlete_profile)).one_or_none()
        return _row_to_dict(row) if row is not None else None

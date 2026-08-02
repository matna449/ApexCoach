"""Sole writer for the engine-authority-hierarchy tables (ADR-0003, ADR-0007).

weekly_plans / monthly_targets are genuinely mutated in place across their
period. decisions is append-only except athlete_override, which — like
activities.rpe (ADR-0006) — is captured after the row already exists and is
only settable via a dedicated targeted update.
"""

import sqlalchemy as sa

from apex_coach.db.schema import (
    athlete_profile,
    decisions,
    monthly_targets,
    race_goals,
    weekly_plans,
)


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

    def upsert_monthly_target(
        self,
        month_start_date: str,
        periodisation_phase: str,
        load_target_total: float,
        race_date: str | None = None,
        source: str = "ATHLETE",
    ) -> bool:
        """Insert-or-update a monthly_targets row by month_start_date
        existence — moved here from apex_coach.cli.main's
        _upsert_monthly_target() (F19.8/F20.3) so the CLI's
        set-monthly-target command, the web PUT endpoint, and F20.3's
        macro-plan accept/regenerate steps all share exactly one
        implementation of this branching rather than each importing across
        module-layering boundaries (engines/web never import from cli).
        Returns True if a new row was created, False if an existing one
        was updated.

        `source` (F20.4) records who wrote this write — 'ATHLETE' (the
        default, matching every caller except the macro-plan engine) or
        'MACRO_PLAN' (accept_macro_plan()/regenerate_macro_plan() pass this
        explicitly). preview_macro_plan()'s already-customized guardrail
        reads it back to tell "the macro plan itself wrote this, safe to
        regenerate" apart from "the athlete deliberately set this, don't
        touch."""
        fields = {
            "periodisation_phase": periodisation_phase,
            "load_target_total": load_target_total,
            "race_date": race_date,
            "source": source,
        }
        existing = self.get_monthly_target(month_start_date)
        if existing is None:
            self.insert_monthly_target(month_start_date=month_start_date, **fields)
            return True
        self.update_monthly_target(month_start_date, **fields)
        return False

    # -- race_goals -----------------------------------------------------------
    # PRD #138: a race goal is one level up monthly_targets (Macro horizon,
    # ADR-0002's Three-Horizon Model) -- it seeds monthly_targets rows once
    # F20.3's accept step ships, rather than being a peer of Monthly. At
    # most one ACTIVE row at a time (docs/adr/0023, single-athlete system);
    # the partial unique index (schema.py's ix_race_goals_one_active) is
    # the real guarantee, not this layer -- callers still get a friendly
    # ValueError instead of a raw IntegrityError bubbling up.

    def insert_race_goal(self, **fields) -> str:
        if fields.get("status") == "ACTIVE" and self.get_active_race_goal() is not None:
            raise ValueError(
                "an ACTIVE race goal already exists -- abandon or complete it "
                "before setting a new one"
            )
        with self._engine.begin() as conn:
            result = conn.execute(
                race_goals.insert().values(**fields).returning(race_goals.c.id)
            )
            return result.scalar_one()

    def get_active_race_goal(self) -> dict | None:
        with self._engine.begin() as conn:
            row = conn.execute(
                sa.select(race_goals).where(race_goals.c.status == "ACTIVE")
            ).one_or_none()
        return _row_to_dict(row) if row is not None else None

    def update_race_goal_status(self, race_goal_id: str, status: str) -> None:
        with self._engine.begin() as conn:
            result = conn.execute(
                race_goals.update()
                .where(race_goals.c.id == race_goal_id)
                .values(status=status)
            )
            if result.rowcount == 0:
                raise ValueError(f"no race_goals row for id {race_goal_id!r}")

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

"""Sole writer for the audit-trail tables (ADR-0003, ADR-0006, ADR-0012).

hr_zones and session_scores are append-only. activities is a documented
exception — upsert on strava_id (dedup-on-sync) plus a targeted RPE update
(athlete input arrives after the Strava-sync row already exists).
daily_metrics is append-only per date but supports a targeted upsert:
WHOOP fetch and the morning health check are independent writers that
populate different columns of the same day's row (ADR-0012). Upsert
(single atomic statement), not read-then-insert-or-update — two writers
racing a check-then-act would both see no row and both attempt insert.
"""

import sqlalchemy as sa

from apex_coach.db.schema import activities, daily_metrics, hr_zones, session_scores

_DAILY_METRICS_IMMUTABLE_FIELDS = {"id", "date", "created_at"}


def _row_to_dict(row) -> dict:
    return dict(row._mapping)


class MetricsRepository:
    def __init__(self, engine: sa.engine.Engine):
        self._engine = engine

    # -- daily_metrics ----------------------------------------------------

    def insert_daily_metrics(self, **fields) -> str:
        with self._engine.begin() as conn:
            result = conn.execute(
                daily_metrics.insert().values(**fields).returning(daily_metrics.c.id)
            )
            return result.scalar_one()

    def upsert_daily_metrics(self, date: str, **fields) -> None:
        if not fields:
            raise ValueError("upsert_daily_metrics requires at least one field to set")
        invalid = _DAILY_METRICS_IMMUTABLE_FIELDS & fields.keys()
        if invalid:
            raise ValueError(f"cannot set immutable field(s): {sorted(invalid)}")

        stmt = sa.dialects.sqlite.insert(daily_metrics).values(date=date, **fields)
        update_columns = {name: stmt.excluded[name] for name in fields}
        stmt = stmt.on_conflict_do_update(
            index_elements=[daily_metrics.c.date],
            set_=update_columns,
        )
        with self._engine.begin() as conn:
            conn.execute(stmt)

    def get_daily_metrics(self, date: str) -> dict | None:
        with self._engine.begin() as conn:
            row = conn.execute(
                sa.select(daily_metrics).where(daily_metrics.c.date == date)
            ).one_or_none()
        return _row_to_dict(row) if row is not None else None

    def get_daily_metrics_range(self, start_date: str, end_date: str) -> list[dict]:
        with self._engine.begin() as conn:
            rows = conn.execute(
                sa.select(daily_metrics)
                .where(daily_metrics.c.date >= start_date)
                .where(daily_metrics.c.date <= end_date)
                .order_by(daily_metrics.c.date)
            ).all()
        return [_row_to_dict(row) for row in rows]

    # -- hr_zones -----------------------------------------------------------

    def insert_hr_zones(self, **fields) -> str:
        with self._engine.begin() as conn:
            result = conn.execute(
                hr_zones.insert().values(**fields).returning(hr_zones.c.id)
            )
            return result.scalar_one()

    def get_hr_zones(self, date: str) -> dict | None:
        with self._engine.begin() as conn:
            row = conn.execute(
                sa.select(hr_zones)
                .where(hr_zones.c.date == date)
                .order_by(hr_zones.c.created_at.desc())
                .limit(1)
            ).one_or_none()
        return _row_to_dict(row) if row is not None else None

    # -- activities -----------------------------------------------------------

    def save_activity(self, **fields) -> None:
        if "rpe" in fields:
            raise ValueError(
                "rpe is set via update_activity_rpe(), not save_activity() — "
                "a Strava resync must never overwrite athlete-entered RPE"
            )
        stmt = sa.dialects.sqlite.insert(activities).values(**fields)
        update_columns = {
            col.name: stmt.excluded[col.name]
            for col in activities.columns
            if col.name not in ("id", "strava_id", "created_at", "rpe")
        }
        stmt = stmt.on_conflict_do_update(
            index_elements=[activities.c.strava_id],
            set_=update_columns,
        )
        with self._engine.begin() as conn:
            conn.execute(stmt)

    def update_activity_rpe(self, strava_id: str, rpe: int) -> None:
        with self._engine.begin() as conn:
            result = conn.execute(
                activities.update()
                .where(activities.c.strava_id == strava_id)
                .values(rpe=rpe)
            )
            if result.rowcount == 0:
                raise ValueError(f"no activity found for strava_id {strava_id!r}")

    def get_activity(self, strava_id: str) -> dict | None:
        with self._engine.begin() as conn:
            row = conn.execute(
                sa.select(activities).where(activities.c.strava_id == strava_id)
            ).one_or_none()
        return _row_to_dict(row) if row is not None else None

    def get_activities_for_date(self, date: str) -> list[dict]:
        with self._engine.begin() as conn:
            rows = conn.execute(
                sa.select(activities).where(activities.c.date == date)
            ).all()
        return [_row_to_dict(row) for row in rows]

    def get_activities_range(self, start_date: str, end_date: str) -> list[dict]:
        with self._engine.begin() as conn:
            rows = conn.execute(
                sa.select(activities)
                .where(activities.c.date >= start_date)
                .where(activities.c.date <= end_date)
                .order_by(activities.c.date)
            ).all()
        return [_row_to_dict(row) for row in rows]

    # -- session_scores -----------------------------------------------------

    def insert_session_score(self, **fields) -> str:
        with self._engine.begin() as conn:
            result = conn.execute(
                session_scores.insert()
                .values(**fields)
                .returning(session_scores.c.id)
            )
            return result.scalar_one()

    def get_session_score(self, activity_id: str) -> dict | None:
        with self._engine.begin() as conn:
            row = conn.execute(
                sa.select(session_scores)
                .where(session_scores.c.activity_id == activity_id)
                .order_by(session_scores.c.created_at.desc())
                .limit(1)
            ).one_or_none()
        return _row_to_dict(row) if row is not None else None

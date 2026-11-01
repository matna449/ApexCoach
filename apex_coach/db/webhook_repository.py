"""Sole writer for whoop_webhook_events (F21 spec §4): dedupe and audit trail."""

from datetime import datetime, timezone

import sqlalchemy as sa

from apex_coach.db.schema import whoop_webhook_events
from apex_coach.db.upsert import dialect_insert

RECEIVED = "received"
PROCESSED = "processed"
PENDING = "pending"
IGNORED = "ignored"
ERROR = "error"

_FINISHED = {PROCESSED, IGNORED}


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


class WebhookEventRepository:
    def __init__(self, engine: sa.engine.Engine):
        self._engine = engine

    def record_received(self, trace_id: str, type_: str, record_id: str) -> bool:
        """Returns whether the event still needs processing. WHOOP retries, so a
        delivery of an event that did not finish is processed again."""
        stmt = (
            dialect_insert(self._engine, whoop_webhook_events)
            .values(trace_id=trace_id, type=type_, record_id=record_id, status=RECEIVED)
            .on_conflict_do_nothing(index_elements=[whoop_webhook_events.c.trace_id])
        )
        with self._engine.begin() as conn:
            conn.execute(stmt)
            status = conn.execute(
                sa.select(whoop_webhook_events.c.status).where(
                    whoop_webhook_events.c.trace_id == trace_id
                )
            ).scalar_one()
        return status not in _FINISHED

    def mark(self, trace_id: str, status: str, error: str | None = None) -> None:
        with self._engine.begin() as conn:
            conn.execute(
                whoop_webhook_events.update()
                .where(whoop_webhook_events.c.trace_id == trace_id)
                .values(
                    status=status,
                    error=error,
                    processed_at=_now_iso() if status in _FINISHED else None,
                )
            )

    def get(self, trace_id: str) -> dict | None:
        with self._engine.begin() as conn:
            row = conn.execute(
                sa.select(whoop_webhook_events).where(whoop_webhook_events.c.trace_id == trace_id)
            ).one_or_none()
        return dict(row._mapping) if row is not None else None

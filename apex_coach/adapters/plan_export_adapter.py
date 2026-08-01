"""PlanExportAdapterProtocol — pushes a generated structured weekly plan to
an athlete's calendar. Deliberately separate from ActivitySyncAdapterProtocol
(strava_adapter.py): this is write-direction and intervals.icu-only — Strava
has no calendar/planning equivalent and shouldn't be forced to implement
methods it structurally can't support. See PRD #111, docs/adr/0027.
"""

from typing import Protocol


class PlanExportAdapterProtocol(Protocol):
    def push_session(
        self, event_date: str, structured_session: dict, existing_event_id: str | None
    ) -> str:
        """Creates (existing_event_id is None) or updates in place
        (existing_event_id given) a calendar event for one structured
        session. Returns the event id — callers persist it and pass it back
        in on the next push for the same day, making re-push idempotent
        (update, not duplicate)."""
        ...


class MockPlanExportAdapter:
    """Deterministic fake — no I/O. Echoes back the existing event id when
    given one (update), otherwise mints one from event_date (create)."""

    def push_session(
        self, event_date: str, structured_session: dict, existing_event_id: str | None
    ) -> str:
        return existing_event_id or f"mock-event-{event_date}"

---
status: accepted
---

# Adopt Alembic now, enforce enums via CHECK constraints, and add db/engine.py for connection-level FK enforcement

SDD §2.2 documented Alembic only for the v2.0 Postgres promotion, implying v1's SQLite schema would ship without managed migration history. Building F10.1 (`db/schema.py`) surfaced three implementation gaps the SDD's module breakdown didn't anticipate: how "version-controlled schema changes" scaffolding should actually work in v1, whether the documented TEXT enum columns (`decisions.recommendation`, `weekly_plans.week_status`, `monthly_targets.periodisation_phase`, `oauth_tokens.provider`) should be DB-enforced or left entirely to the Pydantic layer, and where SQLite's `PRAGMA foreign_keys = ON` — required per-connection, not per-schema — actually lives, since no connection/engine module existed in §3.1's directory tree.

We're adopting Alembic from the first migration (`0001`, generated from `schema.py`'s metadata) rather than deferring it to v2.0, because starting migration history now means it's complete when the Postgres promotion happens, instead of being reverse-engineered from a live v1 database at that point. Enum-shaped TEXT columns get `sa.Enum(..., native_enum=False)`, which SQLAlchemy renders as a CHECK constraint on SQLite and a native ENUM type on PostgreSQL — the same portability property that drove SQLAlchemy Core over the ORM in §2.1, applied one level down. `db/engine.py` is added as a genuinely new module: a thin `create_engine()` wrapper with an event listener that fires the PRAGMA on every new connection, because "foreign keys are enforced" (§4.1) is not actually true of a schema file that only defines tables — enforcement is a connection-time property SQLite does not apply by default.

Alternative considered: leave `migrations/` as an empty README-only placeholder until a second schema version actually exists. Rejected because F10.1 is the one point where adopting Alembic costs nothing — zero existing migration history to reconcile. Every ticket after this one adds tables or columns that would otherwise need a hand-written migration reconciled against Alembic's expectations later.

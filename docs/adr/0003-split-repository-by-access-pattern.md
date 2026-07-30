---
status: accepted
---

# Split repository.py by access pattern instead of one repository for all tables

SDD §3.2 documented a single `repository` module contracting over all persistence: `oauth_tokens` (API Contract §5 — one encrypted row per provider, updated in place on every token refresh), the audit-trail tables (`daily_metrics`, `hr_zones`, `activities`, `session_scores` — append-heavy, one row per day/activity, mostly never mutated after creation for auditability per SDD §4.1 — see docs/adr/0006 for `activities`' exception), and the more state-machine-flavored tables (`weekly_plans`, `monthly_targets`, `decisions` — read/written across the engine authority hierarchy). These three groups have genuinely different access shapes, not just different table names.

We're splitting `repository.py` into `token_repository.py`, `metrics_repository.py`, and `plan_repository.py` before any code exists, because the cost of doing it now is one SDD table edit and the cost of doing it after implementation is a real refactor across whatever's already calling the unified interface. Each new module remains the sole writer for its own tables, so SDD §7.2's "the repository layer is the only place that writes to the DB" locality principle holds at a finer grain rather than being eroded.

Alternative considered: keep `repository.py` unified and revisit only if real usage shows the shapes diverge. Rejected for this specific split because the divergence is already visible in the schema as documented (encrypted single-row token store vs. immutable audit trail vs. mutable plan state) — this isn't a hypothetical future concern, it's already true of SDD §4 and API Contract §5 as written.

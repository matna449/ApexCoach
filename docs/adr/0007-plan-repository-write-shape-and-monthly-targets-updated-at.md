---
status: accepted
---

# decisions gets the activities treatment for athlete_override; monthly_targets gains updated_at

ADR-0003 grouped `decisions` with `weekly_plans`/`monthly_targets` as "state-machine-flavored" tables, separate from `metrics_repository`'s audit-trail group. But SDD §4.6 describes `decisions` itself as "Full audit trail of all recommendations made," and its `athlete_override` column ("NULL or the athlete's chosen override, e.g. `WENT_ANYWAY` — logged for pattern analysis") is captured after the row already exists, on a separate timeline from the daily engine's `recommendation`/`rationale_json`/`llm_explanation` output — the same shape as ADR-0006's `activities.rpe` case. `decisions.date` also has an FK to `daily_metrics.date` with no unique constraint, same as `hr_zones.date` and `session_scores.activity_id` in F10.3.

`plan_repository.py` treats `decisions` with the same rules ADR-0006 established for `activities`: `insert_decision()` never accepts `athlete_override` — it's set only via `record_athlete_override(decision_id, override)` — and multiple rows per date are accepted as a possibility with no new migration, resolved as "most recent decision for this date" via `ORDER BY created_at DESC` at query time. `weekly_plans` and `monthly_targets` are different in kind, not degree: both are genuinely mutated in place across their period (`weekly_plans.adapted_plan_json` "updated after each daily engine run," `monthly_targets.load_actual_total` "Updated weekly"), so `plan_repository` uses real `UPDATE` statements against their unique `week_start_date`/`month_start_date` keys, not append-plus-most-recent-wins.

Separately: `weekly_plans` has an `updated_at` column with `onupdate=_now_iso` already wired in `schema.py`; `monthly_targets` — despite being equally described as updated across its period — did not. Nothing in the docs explains the asymmetry, so we're treating it as an SDD oversight and adding `monthly_targets.updated_at` via a new Alembic migration, matching `weekly_plans`' shape.

Alternative considered: accept `athlete_override` as a plain optional field on `insert_decision()`, since (unlike `activities`) `decisions` has no resync/upsert path that could silently clobber it. Rejected for consistency — the reason to keep it as a targeted method isn't only the clobber risk, it's that the athlete's override is a distinct fact captured on a distinct timeline from the engine's output, and a future reader should be able to see that distinction in the repository's method signatures, not just in a comment.

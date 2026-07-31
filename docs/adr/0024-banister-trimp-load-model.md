---
status: accepted
---

# Banister Impulse-Response (TRIMP) replaces the grade-adjusted HR load formula

SDD §5.2 flagged `apex_coach/services/load_calculator.py`'s current run/ride/swim formula (`duration_minutes × avg_hr_bpm × grade_factor / 1000`) as an approximation, with the Banister Impulse-Response model named as its v1.5 replacement. This ADR resolves the formula, where its inputs come from, and what happens to already-persisted load values.

## The formula

Standard Banister TRIMP (Morton et al.'s refinement):

```
TRIMP = duration_minutes × ΔHR_ratio × 0.64 × e^(b × ΔHR_ratio)
ΔHR_ratio = (HR_exercise_avg − HR_rest) / (HR_max − HR_rest)
b = 1.92 (male) or 1.67 (female) — the original research's exponential weighting constant
```

This **replaces** `calculate_hr_based_load()` for Run/Ride/Swim activities. `calculate_rpe_based_load()` (Strength) and `calculate_recovery_load()` (Yoga/duration-based) are untouched — original Banister TRIMP is an HR-response model with no equivalent for non-HR-paced activities, and those two formulas weren't the approximation SDD §5.2 was calling out.

**`grade_pct` is dropped for HR-based activities.** TRIMP is self-adjusting for terrain: climbing raises heart rate, which raises `ΔHR_ratio`, which raises TRIMP directly — a separate grade multiplier on top would double-count intensity that the HR response already captures. The current formula needed an explicit grade term only because it used flat `avg_hr_bpm` without HR-reserve normalization; TRIMP doesn't have that gap.

## Where the inputs come from

- **`HR_exercise_avg`**: `activities.avg_hr_bpm`, already stored (F02/F06.1).
- **`HR_rest`**: the **day-of WHOOP resting HR** (`daily_metrics.whoop_rhr_bpm` for the activity's date) — already fetched daily (F43), and more physiologically accurate than a static value since resting HR genuinely fluctuates with fatigue, illness, and travel, which is part of what TRIMP is meant to surface. **Fallback** when that date has no WHOOP data (activity synced before any WHOOP fetch, or a gap day): fall back to `athlete_profile.baseline_resting_hr`. This must never be a hard failure — weekly/monthly load aggregation cannot crash because one day's WHOOP data is missing.
- **`HR_max`**: new `athlete_profile.max_hr` — doesn't fluctuate day-to-day the way resting HR does, so a stored profile value (settable, override-able) is appropriate, matching how `zones`/`sync-session` already accept `--max-hr` as an input today.
- **`b` (sex constant)**: new `athlete_profile.sex` (`MALE` | `FEMALE`) — a genuine simplification inherited from the source research, which only calibrated the constant for those two categories. Documented here, not silently baked in, so a future reader isn't surprised by why an athlete's sex is stored at all.

**New `athlete_profile` table** (single row, no per-athlete keying needed — this system is single-user per docs/adr/0023): `max_hr`, `baseline_resting_hr`, `sex`. A `set-athlete-profile` CLI command mirrors `set-monthly-target`'s shape (`insert`-or-`update` on first vs. subsequent calls). `zones`/`sync-session`'s existing `--max-hr`/`--resting-hr` flags stay as-is for now (out of scope for this ADR) — they can be migrated to default from the profile in a later ticket, not required to land this formula.

`calculate_load_au()`'s signature changes for HR-based activities: `grade_pct` is removed, `resting_hr`, `max_hr`, and `sex` are added (required when `activity_type` is HR-based; irrelevant for RPE/duration-based branches). Callers (`load_au_for_activity()` in `monthly_engine.py`, `sync-session`'s CLI command) resolve `resting_hr` (from `daily_metrics` with the profile fallback) and `max_hr`/`sex` (from `athlete_profile`) before calling it — `calculate_load_au()` itself stays a pure function with no repository access.

## Migration: no explicit backfill

`weekly_engine`'s and `monthly_engine`'s load aggregates (`weekly_plans.load_actual`, `monthly_targets.load_actual_total`) are **recomputed from raw activity data on every run** — `load_au_for_activity()` calls `calculate_load_au()` fresh each time rather than reading the stored `activities.load_score` column. This means the next `weekly-summary`/`monthly-summary` run after this change ships automatically recalculates **every** activity in range under the new formula, including historical ones — no migration script needed for those aggregates.

The one place that *doesn't* self-correct: `activities.load_score` itself, a snapshot persisted once at `sync-session` time (F11.7). Already-synced activities keep whatever value was computed under the old formula until the athlete explicitly re-runs `sync-session` for that activity (an upsert on `strava_id`, so re-syncing does recompute it). This is left as-is deliberately — recalculating historical `load_score` values accurately would require knowing the athlete's resting HR *on each historical date*, which was never captured before this ADR (resting HR was only ever an ephemeral `--resting-hr`/`--max-hr` CLI flag, ADR-0023's `zones`/`sync-session` predecessors). Fabricating historical accuracy that doesn't exist is worse than clearly documenting the cutover: values synced before this ships are old-formula, values synced after are new-formula, and the aggregate engines' auto-recompute already makes the athlete-facing weekly/monthly numbers consistent regardless.

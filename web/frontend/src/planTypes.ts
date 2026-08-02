// F19.4 (#119): types for GET /api/plan/week (web/backend/main.py). These
// mirror apex_coach.engines.structure_generator.generate_week_structure()'s
// three structure shapes verbatim (HIIT intervals; AU-distributed single
// blocks with a warmup/cooldown split; and the two fixed-duration
// degenerate cases, Strength and Recovery/Rest) -- the backend forwards
// `structure` straight through from generated_structure_json, so the
// frontend's discriminated shape has to match the engine's output exactly,
// not an idealized re-shape of it.
export type IntervalsStructure = {
  type: 'intervals'
  rep_count: number
  work_zone: string
  work_hr_bpm: number
  work_min: number
  recovery_zone: string
  recovery_hr_bpm: number
  recovery_min: number
  warmup_cooldown_min: number
  total_duration_min: number
}

// Covers all three single_block variants: AU-distributed sessions (zone +
// target_hr_bpm + main_set_min + warmup_cooldown_min + total_duration_min),
// Recovery (zone + duration_min only), and Strength (duration_min only, no
// zone -- RPE-based, docs/adr/0027).
export type SingleBlockStructure = {
  type: 'single_block'
  zone?: string
  target_hr_bpm?: number
  main_set_min?: number
  warmup_cooldown_min?: number
  total_duration_min?: number
  duration_min?: number
}

export type RestStructure = {
  type: 'rest'
  duration_min: number
}

export type SessionStructure = IntervalsStructure | SingleBlockStructure | RestStructure

export type PlanDay = {
  day: string
  session_type: string
  structure: SessionStructure
  // F19.7 (#123): true once this day has an event id in
  // weekly_plans.pushed_event_ids_json (pushed to intervals.icu), false for
  // a local-only draft that hasn't been pushed (or re-pushed since
  // regeneration) yet.
  pushed: boolean
}

// F19.7 (#123): resolved the same way apex_coach.cli.main's
// `_build_plan_export_adapter` resolves it -- a NULL athlete_profile row
// defaults to 'INTERVALS_ICU'. Pushing a plan to a calendar is
// intervals.icu-only (docs/adr/0027); the frontend uses this to
// disable/hide the push button for STRAVA athletes.
export type ActivitySyncProvider = 'STRAVA' | 'INTERVALS_ICU'

export type WeekPlanResponse = {
  week_start_date: string
  generated: boolean
  days: PlanDay[]
  activity_sync_provider: ActivitySyncProvider
}

// F19.7 (#123): POST /api/plan/week/push response shape.
export type PushWeekResponse = {
  week_start_date: string
  pushed_days: { day: string; event_id: string }[]
}

// F19.5 (#120): type for GET /api/plan/month (web/backend/main.py). One
// entry per week overlapping the selected calendar month, rendered with
// F19.4's own WeekGrid (PlanView.tsx) rather than a parallel
// per-day/per-session rendering. `_week_view_payload` (the month endpoint's
// per-week helper) doesn't resolve `activity_sync_provider` -- there's no
// push button in month view (#123 only wired one into the week view) -- so
// this omits the field WeekPlanResponse otherwise requires, rather than
// reusing it verbatim.
export type MonthPlanResponse = {
  month: string
  weeks: Omit<WeekPlanResponse, 'activity_sync_provider'>[]
}

// F19.8 (#137): types for GET/POST /api/plan/month/target
// (web/backend/main.py). Mirrors apex_coach.db.schema's monthly_targets
// enum verbatim -- the set of phases a training block can be in.
export type PeriodisationPhase = 'BASE' | 'BUILD' | 'PEAK' | 'TAPER' | 'RECOVERY'

export type MonthlyTargetResponse = {
  month_start_date: string
  // False when no monthly_targets row exists yet for this month -- the
  // other fields are all null in that case, same shape as the CLI's `--show`
  // "No monthly target stored" case.
  exists: boolean
  periodisation_phase: PeriodisationPhase | null
  load_target_total: number | null
  race_date: string | null
}

export type SetMonthlyTargetResponse = {
  month_start_date: string
  // True if this write created the row (first target set for this month),
  // false if it updated an existing one.
  created: boolean
  periodisation_phase: PeriodisationPhase
  load_target_total: number
  race_date: string | null
}

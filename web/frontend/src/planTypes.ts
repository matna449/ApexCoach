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
  // Always false for now -- push status becomes meaningful once F19.7
  // (#123) wires a push button up to weekly_plans.pushed_event_ids_json.
  pushed: boolean
}

export type WeekPlanResponse = {
  week_start_date: string
  generated: boolean
  days: PlanDay[]
}

// F19.5 (#120): type for GET /api/plan/month (web/backend/main.py). One
// entry per week overlapping the selected calendar month, in the exact same
// shape WeekPlanResponse already uses -- the month view renders each entry
// with F19.4's own WeekGrid (PlanView.tsx) rather than a parallel
// per-day/per-session rendering.
export type MonthPlanResponse = {
  month: string
  weeks: WeekPlanResponse[]
}

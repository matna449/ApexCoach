// F19.2 (#105): types shared between MorningView's data layer and the
// conversational-flow components (BiometricsHeader, ConversationalHealthCheck,
// VerdictStamp). These mirror the exact shapes #81/F17.1-3 established at the
// API boundary -- unchanged here, just factored out of MorningView.tsx so
// presentational components can import them without a cycle back through it.
export type Biometrics = {
  whoop_recovery_pct: number | null
  whoop_hrv_ms: number | null
  whoop_rhr_bpm: number | null
  whoop_strain: number | null
  whoop_sleep_hours: number | null
}

export type Question = { key: string; text: string }

export type QuestionCatalog = { fixed: Question[]; adaptive: Question[] }

export type MorningContext = {
  date: string
  session_type: string
  biometrics: Biometrics
  questions: QuestionCatalog
}

export type NoPlanDetail = {
  error: 'no_plan_for_date'
  message: string
  biometrics: Biometrics
  available_session_types: string[]
}

export type DecisionResponse = {
  recommendation: string
  rationale: string | null
  check_recovery_week_trigger: boolean
  override_triggered: boolean
  override_reasons: string[]
  explanation: string | null
  banner: string | null
  severity: 'WARN' | 'INFO' | null
  decision_context: object
}

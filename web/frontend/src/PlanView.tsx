import { useEffect, useState } from 'react'
import Badge from './Badge'
import type { PlanDay, PushWeekResponse, SessionStructure, WeekPlanResponse } from './planTypes'

// F19.4 (#119): replaces F19.5's (#108) intentional placeholder -- an
// honest empty calendar shape with no network call -- with the real
// read-only week view once F19.2 (#118, generation) and this ticket's own
// backend endpoint exist. Fetches GET /api/plan/week (web/backend/main.py),
// which itself only *reads* weekly_plans.generated_structure_json -- the
// same JSON the CLI's `generate-week-structure` command persists
// (docs/adr/0023, no duplicated business logic).
//
// F19.7 (#123): each day's Pushed/Draft badge now reflects real push
// status (weekly_plans.pushed_event_ids_json via GET /api/plan/week's
// `pushed` field), and an explicit "Push to intervals.icu" button POSTs to
// /api/plan/week/push (also web/backend/main.py), which itself dispatches
// through `_push_week()` in apex_coach.cli.main -- the same push logic the
// `push-week` CLI command uses (F19.6, #121). No push logic is
// reimplemented here or in the backend endpoint. The button is hidden
// (replaced by an explanatory message) when the athlete's configured
// activity_sync_provider is STRAVA, since pushing a plan to a calendar is
// intervals.icu-only (docs/adr/0027).
const API_BASE_URL = 'http://localhost:8000'

const WEEKDAYS = ['Monday', 'Tuesday', 'Wednesday', 'Thursday', 'Friday', 'Saturday', 'Sunday']
const WEEKDAY_LABELS: Record<string, string> = {
  Monday: 'Mon',
  Tuesday: 'Tue',
  Wednesday: 'Wed',
  Thursday: 'Thu',
  Friday: 'Fri',
  Saturday: 'Sat',
  Sunday: 'Sun',
}

function toIsoDate(d: Date): string {
  const y = d.getFullYear()
  const m = String(d.getMonth() + 1).padStart(2, '0')
  const day = String(d.getDate()).padStart(2, '0')
  return `${y}-${m}-${day}`
}

// ISO Monday of the week containing `d` -- matches web/backend/main.py's
// `_monday_on_or_before` (F16.3), computed client-side since this view has
// no navigation between weeks yet (current week only, like MorningView's
// "today only" scope).
function mondayOf(d: Date): Date {
  const jsDay = d.getDay() // 0=Sun..6=Sat
  const diffToMonday = jsDay === 0 ? -6 : 1 - jsDay
  const monday = new Date(d)
  monday.setDate(d.getDate() + diffToMonday)
  return monday
}

function dateForDay(weekStartIso: string, dayName: string): string {
  const offset = WEEKDAYS.indexOf(dayName)
  const [y, m, d] = weekStartIso.split('-').map(Number)
  const date = new Date(y, m - 1, d + offset)
  return toIsoDate(date)
}

function fmtMin(min: number): string {
  return `${Math.round(min)} min`
}

function zoneLabel(zone: string): string {
  return zone.replace('zone', 'Zone ')
}

type Segment = { label: string; detail: string }

function describeStructure(structure: SessionStructure): { segments: Segment[]; totalLabel: string } {
  if (structure.type === 'rest') {
    return { segments: [], totalLabel: 'Rest day' }
  }

  if (structure.type === 'intervals') {
    return {
      segments: [
        { label: 'Warmup + cooldown', detail: fmtMin(structure.warmup_cooldown_min) },
        {
          label: `Main set — ${structure.rep_count}× intervals`,
          detail: `${fmtMin(structure.work_min)} @ ${zoneLabel(structure.work_zone)} / ${fmtMin(structure.recovery_min)} @ ${zoneLabel(structure.recovery_zone)} recovery`,
        },
      ],
      totalLabel: `${fmtMin(structure.total_duration_min)} total`,
    }
  }

  // single_block, AU-distributed: has a warmup/cooldown split around a
  // zone-targeted main set (Threshold/Zone2_Long/Zone2_Short).
  if (structure.zone && structure.main_set_min !== undefined && structure.warmup_cooldown_min !== undefined) {
    return {
      segments: [
        { label: 'Warmup + cooldown', detail: fmtMin(structure.warmup_cooldown_min) },
        { label: 'Main set', detail: `${fmtMin(structure.main_set_min)} @ ${zoneLabel(structure.zone)}` },
      ],
      totalLabel: `${fmtMin(structure.total_duration_min ?? structure.main_set_min + structure.warmup_cooldown_min)} total`,
    }
  }

  // single_block, Recovery: fixed duration at Zone 1, no warmup/cooldown split.
  if (structure.zone && structure.duration_min !== undefined) {
    return {
      segments: [{ label: 'Main set', detail: `${fmtMin(structure.duration_min)} @ ${zoneLabel(structure.zone)}` }],
      totalLabel: `${fmtMin(structure.duration_min)} total`,
    }
  }

  // single_block, Strength: fixed duration, RPE-based, no HR zone.
  const duration = structure.duration_min ?? 0
  return {
    segments: [{ label: 'Main set', detail: `${fmtMin(duration)} (RPE-based)` }],
    totalLabel: `${fmtMin(duration)} total`,
  }
}

function DayCard({ dayName, dateIso, planDay }: { dayName: string; dateIso: string; planDay: PlanDay | null }) {
  return (
    <div
      className="flex min-h-40 flex-col gap-2 rounded-md border border-border bg-surface-card p-3"
      data-testid={`plan-day-${dayName}`}
    >
      <div className="flex items-baseline justify-between">
        <span className="text-xs font-medium tracking-widest text-text-muted uppercase">
          {WEEKDAY_LABELS[dayName]}
        </span>
        <span className="font-mono text-xs text-text-muted tabular-nums">{dateIso.slice(5)}</span>
      </div>

      {planDay === null && <p className="text-sm text-text-muted">No session planned</p>}

      {planDay !== null && (
        <>
          <div className="flex items-center justify-between gap-2">
            <span
              className="text-sm font-semibold text-text-heading"
              data-testid={`plan-day-session-type-${dayName}`}
            >
              {planDay.session_type}
            </span>
            <Badge tone={planDay.pushed ? 'good' : 'info'} testId={`plan-day-pushed-${dayName}`}>
              {planDay.pushed ? 'Pushed' : 'Draft'}
            </Badge>
          </div>

          {(() => {
            const { segments, totalLabel } = describeStructure(planDay.structure)
            return (
              <div className="flex flex-col gap-1">
                {segments.map((seg) => (
                  <div key={seg.label} className="text-xs">
                    <span className="text-text-muted">{seg.label}: </span>
                    <span className="font-mono text-text-primary">{seg.detail}</span>
                  </div>
                ))}
                <span className="mt-1 font-mono text-xs font-medium text-text-heading tabular-nums">
                  {totalLabel}
                </span>
              </div>
            )
          })()}
        </>
      )}
    </div>
  )
}

// F19.5 (#120): pulled out of PlanView's render body so MonthView.tsx can
// render each of the month's weeks with the exact same per-day/per-session
// grid this week view uses, rather than a parallel implementation.
export function WeekGrid({ weekStartIso, days }: { weekStartIso: string; days: PlanDay[] }) {
  return (
    <div className="grid grid-cols-7 gap-3">
      {WEEKDAYS.map((dayName) => (
        <DayCard
          key={dayName}
          dayName={dayName}
          dateIso={dateForDay(weekStartIso, dayName)}
          planDay={days.find((d) => d.day === dayName) ?? null}
        />
      ))}
    </div>
  )
}

type LoadState =
  | { kind: 'loading' }
  | { kind: 'error'; message: string }
  | { kind: 'loaded'; plan: WeekPlanResponse }

async function fetchWeekPlan(weekStart: string): Promise<LoadState> {
  let res: Response
  try {
    res = await fetch(`${API_BASE_URL}/api/plan/week?week_start=${weekStart}`)
  } catch (err: unknown) {
    return { kind: 'error', message: err instanceof Error ? err.message : String(err) }
  }
  if (res.status === 404) {
    // No weekly_plans row for this week yet -- render the same "nothing
    // generated" empty state a week with no structure gets, rather than a
    // hard error (the athlete hasn't planned this week, that's expected).
    // activity_sync_provider is irrelevant here (no push button renders
    // when generated is false) -- INTERVALS_ICU is just the same default
    // the backend itself falls back to for a NULL athlete_profile row.
    return {
      kind: 'loaded',
      plan: {
        week_start_date: weekStart,
        generated: false,
        days: [],
        activity_sync_provider: 'INTERVALS_ICU',
      },
    }
  }
  if (!res.ok) {
    const body = (await res.json().catch(() => null)) as { detail?: unknown } | null
    const detail = body?.detail
    return {
      kind: 'error',
      message: typeof detail === 'string' ? detail : `GET /api/plan/week returned ${res.status}`,
    }
  }
  const plan = (await res.json()) as WeekPlanResponse
  return { kind: 'loaded', plan }
}

type PushState =
  | { kind: 'idle' }
  | { kind: 'pushing' }
  | { kind: 'error'; message: string }

async function postPushWeek(weekStart: string): Promise<{ ok: true } | { ok: false; message: string }> {
  let res: Response
  try {
    res = await fetch(`${API_BASE_URL}/api/plan/week/push?week_start=${weekStart}`, {
      method: 'POST',
    })
  } catch (err: unknown) {
    return { ok: false, message: err instanceof Error ? err.message : String(err) }
  }
  if (!res.ok) {
    const body = (await res.json().catch(() => null)) as { detail?: unknown } | null
    const detail = body?.detail
    return {
      ok: false,
      message: typeof detail === 'string' ? detail : `POST /api/plan/week/push returned ${res.status}`,
    }
  }
  // Response body (PushWeekResponse) isn't needed here -- re-fetching the
  // week plan below is the single source of truth for per-day pushed
  // status, so the frontend never has two places that could disagree about
  // it.
  await (res.json() as Promise<PushWeekResponse>).catch(() => undefined)
  return { ok: true }
}

function PlanView() {
  const weekStart = toIsoDate(mondayOf(new Date()))
  const [state, setState] = useState<LoadState>({ kind: 'loading' })
  const [pushState, setPushState] = useState<PushState>({ kind: 'idle' })

  const loadPlan = () => {
    setState({ kind: 'loading' })
    fetchWeekPlan(weekStart).then(setState)
  }

  useEffect(() => {
    loadPlan()
    // weekStart is stable for the component's lifetime; run once on mount.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [])

  async function handlePush() {
    setPushState({ kind: 'pushing' })
    const result = await postPushWeek(weekStart)
    if (result.ok) {
      setPushState({ kind: 'idle' })
      loadPlan() // refresh so each day's Pushed/Draft badge reflects the push
    } else {
      setPushState({ kind: 'error', message: result.message })
    }
  }

  const plan = state.kind === 'loaded' ? state.plan : null
  const isStrava = plan?.activity_sync_provider === 'STRAVA'

  return (
    <div className="p-6" data-testid="plan-view">
      <div className="flex flex-wrap items-center justify-between gap-3">
        <h2 className="text-lg font-semibold" data-testid="plan-week-heading">
          Week of {weekStart}
        </h2>

        {plan !== null && plan.generated && (
          <div className="flex items-center gap-3">
            {isStrava ? (
              <p className="text-sm text-text-muted" data-testid="push-disabled-strava">
                Push to intervals.icu is unavailable — the configured provider is Strava.
              </p>
            ) : (
              <button
                type="button"
                onClick={handlePush}
                disabled={pushState.kind === 'pushing'}
                className="rounded-md border border-border-strong bg-surface-card px-4 py-2 text-sm font-medium text-text-heading transition-colors hover:bg-surface-panel disabled:opacity-50"
                data-testid="push-week-button"
              >
                {pushState.kind === 'pushing' ? 'Pushing…' : 'Push to intervals.icu'}
              </button>
            )}
          </div>
        )}
      </div>

      {pushState.kind === 'error' && (
        <p className="mt-1 text-sm text-status-bad" data-testid="push-error">
          Push failed: {pushState.message}
        </p>
      )}

      {state.kind === 'loading' && (
        <p className="mt-1 text-sm text-text-muted" data-testid="plan-loading">
          Loading…
        </p>
      )}

      {state.kind === 'error' && (
        <p className="mt-1 text-sm text-status-bad" data-testid="plan-error">
          Error: {state.message}
        </p>
      )}

      {state.kind === 'loaded' && !state.plan.generated && (
        <p className="mt-1 text-sm text-text-muted" data-testid="plan-not-generated">
          No structured plan generated yet for this week.
        </p>
      )}

      {state.kind === 'loaded' && (
        <div className="mt-6">
          <WeekGrid weekStartIso={state.plan.week_start_date} days={state.plan.days} />
        </div>
      )}
    </div>
  )
}

export default PlanView

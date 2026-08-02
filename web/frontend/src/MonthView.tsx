import { useEffect, useState } from 'react'
import { WeekGrid } from './PlanView'
import type { MonthPlanResponse } from './planTypes'

// F19.5 (#120): month view stitching together every weekly_plans row that
// overlaps the selected calendar month. Fetches GET /api/plan/month
// (web/backend/main.py), which itself stitches together
// GET /api/plan/week's own read logic (`_structured_days()`) one week at a
// time -- this component then renders each of those weeks with PlanView's
// own `WeekGrid` (same per-day/per-session cards, not a parallel
// implementation, per #120's acceptance criteria). Like PlanView, this is
// current-month-only for now -- no prev/next navigation yet (mirrors F19.4's
// "current week only" scope).
const API_BASE_URL = 'http://localhost:8000'

function toIsoMonth(d: Date): string {
  const y = d.getFullYear()
  const m = String(d.getMonth() + 1).padStart(2, '0')
  return `${y}-${m}`
}

type LoadState =
  | { kind: 'loading' }
  | { kind: 'error'; message: string }
  | { kind: 'loaded'; plan: MonthPlanResponse }

async function fetchMonthPlan(month: string): Promise<LoadState> {
  let res: Response
  try {
    res = await fetch(`${API_BASE_URL}/api/plan/month?month=${month}`)
  } catch (err: unknown) {
    return { kind: 'error', message: err instanceof Error ? err.message : String(err) }
  }
  if (!res.ok) {
    const body = (await res.json().catch(() => null)) as { detail?: unknown } | null
    const detail = body?.detail
    return {
      kind: 'error',
      message: typeof detail === 'string' ? detail : `GET /api/plan/month returned ${res.status}`,
    }
  }
  const plan = (await res.json()) as MonthPlanResponse
  return { kind: 'loaded', plan }
}

function MonthView() {
  const month = toIsoMonth(new Date())
  const [state, setState] = useState<LoadState>({ kind: 'loading' })

  useEffect(() => {
    setState({ kind: 'loading' })
    fetchMonthPlan(month).then(setState)
    // month is stable for the component's lifetime; run once on mount.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [])

  return (
    <div className="p-6" data-testid="plan-month-view">
      <h2 className="text-lg font-semibold" data-testid="plan-month-heading">
        Month of {month}
      </h2>

      {state.kind === 'loading' && (
        <p className="mt-1 text-sm text-text-muted" data-testid="plan-month-loading">
          Loading…
        </p>
      )}

      {state.kind === 'error' && (
        <p className="mt-1 text-sm text-status-bad" data-testid="plan-month-error">
          Error: {state.message}
        </p>
      )}

      {state.kind === 'loaded' && (
        <div className="mt-6 flex flex-col gap-6">
          {state.plan.weeks.map((week) => (
            <div key={week.week_start_date} data-testid={`plan-month-week-${week.week_start_date}`}>
              <h3 className="mb-2 text-sm font-medium text-text-muted">Week of {week.week_start_date}</h3>
              {!week.generated && (
                <p className="mb-2 text-sm text-text-muted" data-testid={`plan-month-week-not-generated-${week.week_start_date}`}>
                  No structured plan generated yet for this week.
                </p>
              )}
              <WeekGrid weekStartIso={week.week_start_date} days={week.days} />
            </div>
          ))}
        </div>
      )}
    </div>
  )
}

export default MonthView

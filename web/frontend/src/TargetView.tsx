import { useEffect, useState } from 'react'
import SelectCard from './SelectCard'
import type { MonthlyTargetResponse, PeriodisationPhase, SetMonthlyTargetResponse } from './planTypes'

// F19.8 (#137): web UI for the monthly target -- previously CLI-only
// (`set-monthly-target`, F11.8/#48). Fetches/writes GET+POST
// /api/plan/month/target (web/backend/main.py), which themselves wrap
// PlanRepository.get_monthly_target() and the same insert-vs-update-by-
// existence branching `set-monthly-target` uses (docs/adr/0023, no
// duplicated persistence path). Periodisation-phase selection reuses
// SelectCard, the same tappable-card pattern MorningView's session-type
// picker and ConversationalHealthCheck's rating picker already use. Like
// PlanView/MonthView, this is current-calendar-month-only for now -- no
// prev/next navigation yet.
const API_BASE_URL = 'http://localhost:8000'

const PERIODISATION_PHASES: PeriodisationPhase[] = ['BASE', 'BUILD', 'PEAK', 'TAPER', 'RECOVERY']

function toIsoMonthStart(d: Date): string {
  const y = d.getFullYear()
  const m = String(d.getMonth() + 1).padStart(2, '0')
  return `${y}-${m}-01`
}

type LoadState =
  | { kind: 'loading' }
  | { kind: 'error'; message: string }
  | { kind: 'loaded'; target: MonthlyTargetResponse }

async function fetchMonthlyTarget(monthStart: string): Promise<LoadState> {
  let res: Response
  try {
    res = await fetch(`${API_BASE_URL}/api/plan/month/target?month_start=${monthStart}`)
  } catch (err: unknown) {
    return { kind: 'error', message: err instanceof Error ? err.message : String(err) }
  }
  if (!res.ok) {
    const body = (await res.json().catch(() => null)) as { detail?: unknown } | null
    const detail = body?.detail
    return {
      kind: 'error',
      message: typeof detail === 'string' ? detail : `GET /api/plan/month/target returned ${res.status}`,
    }
  }
  const target = (await res.json()) as MonthlyTargetResponse
  return { kind: 'loaded', target }
}

type SaveState = { kind: 'idle' } | { kind: 'saving' } | { kind: 'error'; message: string }

async function postMonthlyTarget(
  monthStart: string,
  phase: PeriodisationPhase,
  loadTargetTotal: number,
  raceDate: string | null,
): Promise<{ ok: true; target: SetMonthlyTargetResponse } | { ok: false; message: string }> {
  let res: Response
  try {
    res = await fetch(`${API_BASE_URL}/api/plan/month/target?month_start=${monthStart}`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({
        periodisation_phase: phase,
        load_target_total: loadTargetTotal,
        race_date: raceDate,
      }),
    })
  } catch (err: unknown) {
    return { ok: false, message: err instanceof Error ? err.message : String(err) }
  }
  if (!res.ok) {
    const body = (await res.json().catch(() => null)) as { detail?: unknown } | null
    const detail = body?.detail
    return {
      ok: false,
      message: typeof detail === 'string' ? detail : `POST /api/plan/month/target returned ${res.status}`,
    }
  }
  const target = (await res.json()) as SetMonthlyTargetResponse
  return { ok: true, target }
}

function TargetSummary({ target, onEdit }: { target: MonthlyTargetResponse; onEdit: () => void }) {
  return (
    <div
      className="flex flex-col gap-4 rounded-md border border-border bg-surface-card p-4"
      data-testid="target-summary"
    >
      <div className="flex items-start justify-between gap-3">
        <div className="flex flex-col gap-1">
          <span className="text-xs font-medium tracking-widest text-text-muted uppercase">Phase</span>
          <span className="font-mono text-base font-semibold text-text-heading" data-testid="target-summary-phase">
            {target.periodisation_phase}
          </span>
        </div>
        <button
          type="button"
          onClick={onEdit}
          className="rounded-md border border-border-strong bg-surface-card px-3 py-1.5 text-sm font-medium text-text-heading transition-colors hover:bg-surface-panel"
          data-testid="target-edit-button"
        >
          Edit
        </button>
      </div>
      <div className="grid grid-cols-2 gap-4">
        <div className="flex flex-col gap-1">
          <span className="text-xs font-medium tracking-widest text-text-muted uppercase">Load target total</span>
          <span className="font-mono text-sm text-text-primary tabular-nums" data-testid="target-summary-load">
            {target.load_target_total}
          </span>
        </div>
        <div className="flex flex-col gap-1">
          <span className="text-xs font-medium tracking-widest text-text-muted uppercase">Race date</span>
          <span
            className="font-mono text-sm text-text-primary tabular-nums"
            data-testid="target-summary-race-date"
          >
            {target.race_date ?? 'None set'}
          </span>
        </div>
      </div>
    </div>
  )
}

function TargetForm({
  monthStart,
  initial,
  onSaved,
  onCancel,
}: {
  monthStart: string
  initial: MonthlyTargetResponse
  onSaved: (target: SetMonthlyTargetResponse) => void
  onCancel: (() => void) | null
}) {
  const [phase, setPhase] = useState<PeriodisationPhase | null>(initial.periodisation_phase)
  const [loadTargetTotal, setLoadTargetTotal] = useState(
    initial.load_target_total !== null ? String(initial.load_target_total) : '',
  )
  const [raceDate, setRaceDate] = useState(initial.race_date ?? '')
  const [saveState, setSaveState] = useState<SaveState>({ kind: 'idle' })

  const parsedLoad = Number(loadTargetTotal)
  const canSave = phase !== null && loadTargetTotal.trim() !== '' && !Number.isNaN(parsedLoad)

  async function handleSave() {
    if (!canSave || phase === null) return
    setSaveState({ kind: 'saving' })
    const result = await postMonthlyTarget(
      monthStart,
      phase,
      parsedLoad,
      raceDate.trim() === '' ? null : raceDate,
    )
    if (result.ok) {
      setSaveState({ kind: 'idle' })
      onSaved(result.target)
    } else {
      setSaveState({ kind: 'error', message: result.message })
    }
  }

  return (
    <div
      className="flex flex-col gap-4 rounded-md border border-border bg-surface-card p-4"
      data-testid="target-form"
    >
      <div className="flex flex-col gap-2">
        <span className="text-xs font-medium tracking-widest text-text-muted uppercase">Periodisation phase</span>
        <div className="flex flex-wrap gap-2">
          {PERIODISATION_PHASES.map((p) => (
            <SelectCard
              key={p}
              label={p}
              selected={phase === p}
              onSelect={() => setPhase(p)}
              testId={`target-phase-${p}`}
            />
          ))}
        </div>
      </div>

      <label className="flex flex-col gap-1 text-sm">
        <span className="text-xs font-medium tracking-widest text-text-muted uppercase">Load target total</span>
        <input
          type="number"
          inputMode="decimal"
          value={loadTargetTotal}
          onChange={(e) => setLoadTargetTotal(e.target.value)}
          className="rounded-md border border-border bg-surface-panel px-3 py-2 font-mono text-text-primary focus:border-border-strong focus:outline-none"
          data-testid="target-load-input"
        />
      </label>

      <label className="flex flex-col gap-1 text-sm">
        <span className="text-xs font-medium tracking-widest text-text-muted uppercase">Race date (optional)</span>
        <input
          type="date"
          value={raceDate}
          onChange={(e) => setRaceDate(e.target.value)}
          className="rounded-md border border-border bg-surface-panel px-3 py-2 font-mono text-text-primary focus:border-border-strong focus:outline-none"
          data-testid="target-race-date-input"
        />
      </label>

      {saveState.kind === 'error' && (
        <p className="text-sm text-status-bad" data-testid="target-save-error">
          Save failed: {saveState.message}
        </p>
      )}

      <div className="flex items-center gap-3">
        <button
          type="button"
          onClick={handleSave}
          disabled={!canSave || saveState.kind === 'saving'}
          className="rounded-md border border-border-strong bg-surface-card px-4 py-2 text-sm font-medium text-text-heading transition-colors hover:bg-surface-panel disabled:opacity-50"
          data-testid="target-save-button"
        >
          {saveState.kind === 'saving' ? 'Saving…' : 'Save target'}
        </button>
        {onCancel && (
          <button
            type="button"
            onClick={onCancel}
            className="text-sm font-medium text-text-muted transition-colors hover:text-text-primary"
            data-testid="target-cancel-button"
          >
            Cancel
          </button>
        )}
      </div>
    </div>
  )
}

function TargetView() {
  const monthStart = toIsoMonthStart(new Date())
  const [state, setState] = useState<LoadState>({ kind: 'loading' })
  const [editing, setEditing] = useState(false)

  const load = () => {
    setState({ kind: 'loading' })
    fetchMonthlyTarget(monthStart).then(setState)
  }

  useEffect(() => {
    load()
    // monthStart is stable for the component's lifetime; run once on mount.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [])

  return (
    <div className="p-6" data-testid="target-view">
      <h2 className="text-lg font-semibold" data-testid="target-heading">
        Monthly target — {monthStart.slice(0, 7)}
      </h2>

      {state.kind === 'loading' && (
        <p className="mt-1 text-sm text-text-muted" data-testid="target-loading">
          Loading…
        </p>
      )}

      {state.kind === 'error' && (
        <p className="mt-1 text-sm text-status-bad" data-testid="target-error">
          Error: {state.message}
        </p>
      )}

      {state.kind === 'loaded' && (
        <div className="mt-6 max-w-md">
          {!state.target.exists && (
            <p className="mb-3 text-sm text-text-muted" data-testid="target-not-set">
              No target set for this month yet — pick a phase, a load target, and, if you're building
              toward one, a race date.
            </p>
          )}

          {state.target.exists && !editing && (
            <TargetSummary target={state.target} onEdit={() => setEditing(true)} />
          )}

          {(!state.target.exists || editing) && (
            <TargetForm
              monthStart={monthStart}
              initial={state.target}
              onCancel={state.target.exists ? () => setEditing(false) : null}
              onSaved={(saved) => {
                setEditing(false)
                setState({
                  kind: 'loaded',
                  target: {
                    month_start_date: saved.month_start_date,
                    exists: true,
                    periodisation_phase: saved.periodisation_phase,
                    load_target_total: saved.load_target_total,
                    race_date: saved.race_date,
                  },
                })
              }}
            />
          )}
        </div>
      )}
    </div>
  )
}

export default TargetView

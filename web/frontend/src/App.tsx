import { useEffect, useState } from 'react'
import ExecutionScoreTrendChart from './ExecutionScoreTrendChart'
import LoadActualVsTargetChart from './LoadActualVsTargetChart'
import HrvTrendChart from './HrvTrendChart'
import MonthView from './MonthView'
import MorningView from './MorningView'
import PlanView from './PlanView'
import Sidebar, { type View } from './Sidebar'

// F17.1 (#83): morning becomes the primary screen; the F16.2/3/4 trend
// charts move to a secondary "History" view. No router library — a local
// view/tab state is enough for a two-screen, single-user local app
// (docs/adr/0023), and keeps the dependency footprint unchanged.
//
// F19.1 (#104): the old centered <h1> + top button-row nav is replaced by a
// persistent left Sidebar (Morning/History/Plan + theme toggle); the same
// local view-state pattern gains a third value ('plan') for the new bare
// stub route. MorningView and the three trend charts below are unchanged —
// only wrapped in the new shell/palette.
//
// F19.5 (#120): a fourth value ('month') renders MonthView, the month
// calendar preview alongside PlanView's week preview.
const API_BASE_URL = 'http://localhost:8000'

type HealthResponse = {
  status: string
}

function HistoryView() {
  const [health, setHealth] = useState<HealthResponse | null>(null)
  const [error, setError] = useState<string | null>(null)

  useEffect(() => {
    fetch(`${API_BASE_URL}/api/health`)
      .then((res) => {
        if (!res.ok) {
          throw new Error(`GET /api/health returned ${res.status}`)
        }
        return res.json() as Promise<HealthResponse>
      })
      .then(setHealth)
      .catch((err: unknown) => {
        setError(err instanceof Error ? err.message : String(err))
      })
  }, [])

  return (
    <div className="flex flex-col gap-10 p-6">
      <h2 className="text-lg font-semibold">Backend health check</h2>
      {error && <p className="text-status-bad">Error: {error}</p>}
      {!error && !health && <p className="text-text-muted">Loading…</p>}
      {health && (
        <pre
          data-testid="health-response"
          className="rounded-md border border-border bg-surface-card p-3 font-mono text-sm"
        >
          {JSON.stringify(health, null, 2)}
        </pre>
      )}
      <ExecutionScoreTrendChart />
      <LoadActualVsTargetChart />
      <HrvTrendChart />
    </div>
  )
}

function App() {
  const [view, setView] = useState<View>('morning')

  return (
    <div className="flex min-h-svh bg-surface-page text-text-primary">
      <Sidebar view={view} onNavigate={setView} />
      <main className="min-w-0 flex-1 overflow-y-auto">
        {view === 'morning' && (
          <div className="p-6">
            <MorningView />
          </div>
        )}
        {view === 'history' && <HistoryView />}
        {view === 'plan' && <PlanView />}
        {view === 'month' && <MonthView />}
      </main>
    </div>
  )
}

export default App

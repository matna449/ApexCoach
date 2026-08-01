import { useEffect, useState } from 'react'
import ExecutionScoreTrendChart from './ExecutionScoreTrendChart'
import LoadActualVsTargetChart from './LoadActualVsTargetChart'
import HrvTrendChart from './HrvTrendChart'
import MorningView from './MorningView'

// F17.1 (#83): morning becomes the primary screen; the F16.2/3/4 trend
// charts move to a secondary "History" view. No router library — a local
// view/tab state is enough for a two-screen, single-user local app
// (docs/adr/0023), and keeps the dependency footprint unchanged.
const API_BASE_URL = 'http://localhost:8000'

type HealthResponse = {
  status: string
}

type View = 'morning' | 'history'

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
    <>
      <h2>Backend health check</h2>
      {error && <p style={{ color: 'red' }}>Error: {error}</p>}
      {!error && !health && <p>Loading…</p>}
      {health && (
        <pre data-testid="health-response">{JSON.stringify(health, null, 2)}</pre>
      )}
      <ExecutionScoreTrendChart />
      <LoadActualVsTargetChart />
      <HrvTrendChart />
    </>
  )
}

function App() {
  const [view, setView] = useState<View>('morning')

  return (
    <main>
      <h1>ApexCoach</h1>
      <nav>
        <button
          type="button"
          onClick={() => setView('morning')}
          aria-current={view === 'morning'}
        >
          Morning
        </button>
        <button
          type="button"
          onClick={() => setView('history')}
          aria-current={view === 'history'}
        >
          History
        </button>
      </nav>
      {view === 'morning' && <MorningView />}
      {view === 'history' && <HistoryView />}
    </main>
  )
}

export default App

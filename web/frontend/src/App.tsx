import { useEffect, useState } from 'react'
import LoadActualVsTargetChart from './LoadActualVsTargetChart'
import HrvTrendChart from './HrvTrendChart'

// F16.1 scaffolding: prove the FastAPI <-> React round trip works, nothing
// more. Fetches the backend directly (backend CORS in web/backend/main.py
// allows this dev server's origin, http://localhost:5173). Later tickets
// (#68/#69/#70) replace this with real trend-chart screens.
const API_BASE_URL = 'http://localhost:8000'

type HealthResponse = {
  status: string
}

function App() {
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
    <main>
      <h1>ApexCoach</h1>
      <h2>Backend health check</h2>
      {error && <p style={{ color: 'red' }}>Error: {error}</p>}
      {!error && !health && <p>Loading…</p>}
      {health && (
        <pre data-testid="health-response">{JSON.stringify(health, null, 2)}</pre>
      )}
      <LoadActualVsTargetChart />
      <HrvTrendChart />
    </main>
  )
}

export default App

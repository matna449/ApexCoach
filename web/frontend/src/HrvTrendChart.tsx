import { useEffect, useState } from 'react'
import {
  CartesianGrid,
  Line,
  LineChart,
  ResponsiveContainer,
  Tooltip,
  XAxis,
  YAxis,
} from 'recharts'

// F16.2 (#68): the web UI's first real screen — an HRV trend chart backed by
// real `daily_metrics` rows via GET /api/trends/hrv (web/backend/main.py).
const API_BASE_URL = 'http://localhost:8000'

type HrvReading = {
  date: string
  whoop_hrv_ms: number | null
}

function HrvTrendChart() {
  const [readings, setReadings] = useState<HrvReading[] | null>(null)
  const [error, setError] = useState<string | null>(null)

  useEffect(() => {
    fetch(`${API_BASE_URL}/api/trends/hrv`)
      .then((res) => {
        if (!res.ok) {
          throw new Error(`GET /api/trends/hrv returned ${res.status}`)
        }
        return res.json() as Promise<HrvReading[]>
      })
      .then(setReadings)
      .catch((err: unknown) => {
        setError(err instanceof Error ? err.message : String(err))
      })
  }, [])

  const hasData = readings !== null && readings.some((r) => r.whoop_hrv_ms !== null)

  return (
    <section>
      <h2>HRV trend (last 30 days)</h2>
      {error && <p style={{ color: 'red' }}>Error: {error}</p>}
      {!error && readings === null && <p>Loading…</p>}
      {!error && readings !== null && !hasData && (
        <p data-testid="hrv-empty-state">No HRV data for this range yet.</p>
      )}
      {!error && hasData && (
        <div data-testid="hrv-chart" style={{ width: '100%', height: 320 }}>
          <ResponsiveContainer width="100%" height="100%">
            <LineChart data={readings ?? []}>
              <CartesianGrid strokeDasharray="3 3" />
              <XAxis dataKey="date" />
              <YAxis
                domain={['auto', 'auto']}
                label={{ value: 'HRV (ms)', angle: -90, position: 'insideLeft' }}
              />
              <Tooltip />
              <Line
                type="monotone"
                dataKey="whoop_hrv_ms"
                name="HRV (ms)"
                stroke="#3d7cff"
                connectNulls
                dot={false}
              />
            </LineChart>
          </ResponsiveContainer>
        </div>
      )}
    </section>
  )
}

export default HrvTrendChart

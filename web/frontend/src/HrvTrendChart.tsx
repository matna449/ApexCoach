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
    <section className="rounded-md border border-border bg-surface-card p-4">
      <h2>HRV trend (last 30 days)</h2>
      {error && <p className="text-status-bad">Error: {error}</p>}
      {!error && readings === null && <p className="text-text-muted">Loading…</p>}
      {!error && readings !== null && !hasData && (
        <p data-testid="hrv-empty-state" className="text-text-muted">
          No HRV data for this range yet.
        </p>
      )}
      {!error && hasData && (
        <div data-testid="hrv-chart" style={{ width: '100%', height: 320 }}>
          <ResponsiveContainer width="100%" height="100%">
            <LineChart data={readings ?? []}>
              <CartesianGrid stroke="var(--color-border)" strokeDasharray="3 3" />
              <XAxis
                dataKey="date"
                tick={{ fill: 'var(--color-text-muted)', fontFamily: 'var(--font-mono)', fontSize: 12 }}
                stroke="var(--color-border)"
              />
              <YAxis
                domain={['auto', 'auto']}
                tick={{ fill: 'var(--color-text-muted)', fontFamily: 'var(--font-mono)', fontSize: 12 }}
                stroke="var(--color-border)"
                label={{
                  value: 'HRV (ms)',
                  angle: -90,
                  position: 'insideLeft',
                  fill: 'var(--color-text-muted)',
                  fontFamily: 'var(--font-mono)',
                }}
              />
              <Tooltip
                contentStyle={{
                  background: 'var(--color-surface-card)',
                  border: '1px solid var(--color-border)',
                  borderRadius: 4,
                  fontFamily: 'var(--font-mono)',
                  fontSize: 12,
                }}
                labelStyle={{ color: 'var(--color-text-heading)' }}
                itemStyle={{ color: 'var(--color-text-primary)' }}
              />
              <Line
                type="monotone"
                dataKey="whoop_hrv_ms"
                name="HRV (ms)"
                stroke="var(--color-accent)"
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

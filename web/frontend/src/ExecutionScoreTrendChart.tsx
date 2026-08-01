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

// F16.4: third screen — execution score trend. Fetches
// GET /api/execution-score-trend (web/backend/main.py) and renders
// execution_score over time, plus overpush/underpush counts as badges.
const API_BASE_URL = 'http://localhost:8000'

type ExecutionScorePoint = {
  date: string
  activity_id: string
  activity_type: string | null
  intended_session_type: string | null
  execution_score: number | null
  overpush_flag: boolean
  underpush_flag: boolean
}

type ExecutionScoreTrendResponse = {
  start_date: string
  end_date: string
  points: ExecutionScorePoint[]
  overpush_count: number
  underpush_count: number
}

function defaultStartDate(): string {
  const d = new Date()
  d.setDate(d.getDate() - 90)
  return d.toISOString().slice(0, 10)
}

function defaultEndDate(): string {
  return new Date().toISOString().slice(0, 10)
}

function ExecutionScoreTrendChart() {
  const [startDate, setStartDate] = useState(defaultStartDate)
  const [endDate, setEndDate] = useState(defaultEndDate)
  const [data, setData] = useState<ExecutionScoreTrendResponse | null>(null)
  const [error, setError] = useState<string | null>(null)

  useEffect(() => {
    setError(null)
    setData(null)
    const params = new URLSearchParams({ start_date: startDate, end_date: endDate })
    fetch(`${API_BASE_URL}/api/execution-score-trend?${params.toString()}`)
      .then((res) => {
        if (!res.ok) {
          throw new Error(`GET /api/execution-score-trend returned ${res.status}`)
        }
        return res.json() as Promise<ExecutionScoreTrendResponse>
      })
      .then(setData)
      .catch((err: unknown) => {
        setError(err instanceof Error ? err.message : String(err))
      })
  }, [startDate, endDate])

  const chartData = (data?.points ?? []).map((p) => ({
    date: p.date,
    execution_score: p.execution_score,
  }))

  return (
    <section>
      <h2>Execution score trend</h2>
      <div style={{ display: 'flex', gap: '1rem', alignItems: 'center', marginBottom: '0.5rem' }}>
        <label>
          Start{' '}
          <input
            type="date"
            value={startDate}
            onChange={(e) => setStartDate(e.target.value)}
          />
        </label>
        <label>
          End{' '}
          <input type="date" value={endDate} onChange={(e) => setEndDate(e.target.value)} />
        </label>
      </div>

      {error && <p style={{ color: 'red' }}>Error: {error}</p>}
      {!error && !data && <p>Loading…</p>}

      {data && (
        <>
          <div style={{ display: 'flex', gap: '1rem', marginBottom: '0.5rem' }} data-testid="execution-score-flag-counts">
            <span
              style={{
                background: '#fdecea',
                color: '#a33',
                padding: '0.25rem 0.5rem',
                borderRadius: '0.25rem',
              }}
            >
              Overpush: {data.overpush_count}
            </span>
            <span
              style={{
                background: '#eaf2fd',
                color: '#345',
                padding: '0.25rem 0.5rem',
                borderRadius: '0.25rem',
              }}
            >
              Underpush: {data.underpush_count}
            </span>
          </div>

          {chartData.length === 0 ? (
            <p>No session scores in this date range.</p>
          ) : (
            <ResponsiveContainer width="100%" height={300}>
              <LineChart data={chartData}>
                <CartesianGrid strokeDasharray="3 3" />
                <XAxis dataKey="date" />
                <YAxis domain={[0, 100]} />
                <Tooltip />
                <Line
                  type="monotone"
                  dataKey="execution_score"
                  stroke="#2563eb"
                  connectNulls
                  dot
                />
              </LineChart>
            </ResponsiveContainer>
          )}
        </>
      )}
    </section>
  )
}

export default ExecutionScoreTrendChart

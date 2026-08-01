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

// F19.4 (#107): axis/tick label style shared by all recharts <Tick>-style
// props across this file -- tabular-mono face, muted text token, matching
// index.css's --font-mono / --color-text-muted.
const AXIS_TICK_STYLE = { fill: 'var(--color-text-muted)', fontFamily: 'var(--font-mono)', fontSize: 12 }
const TOOLTIP_CONTENT_STYLE = {
  background: 'var(--color-surface-card)',
  border: '1px solid var(--color-border)',
  borderRadius: 4,
  fontFamily: 'var(--font-mono)',
  fontSize: 12,
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
    <section className="rounded-md border border-border bg-surface-card p-4">
      <h2>Execution score trend</h2>
      <div className="mb-2 flex items-center gap-4 text-sm text-text-primary">
        <label className="flex items-center gap-1.5">
          Start
          <input
            type="date"
            value={startDate}
            onChange={(e) => setStartDate(e.target.value)}
            className="rounded-sm border border-border bg-surface-page px-2 py-1 font-mono text-text-primary"
          />
        </label>
        <label className="flex items-center gap-1.5">
          End
          <input
            type="date"
            value={endDate}
            onChange={(e) => setEndDate(e.target.value)}
            className="rounded-sm border border-border bg-surface-page px-2 py-1 font-mono text-text-primary"
          />
        </label>
      </div>

      {error && <p className="text-status-bad">Error: {error}</p>}
      {!error && !data && <p className="text-text-muted">Loading…</p>}

      {data && (
        <>
          <div
            className="mb-2 flex gap-4"
            data-testid="execution-score-flag-counts"
          >
            <span className="rounded-sm bg-status-bad/15 px-2 py-1 font-mono text-sm text-status-bad">
              Overpush: {data.overpush_count}
            </span>
            <span className="rounded-sm bg-status-warn/15 px-2 py-1 font-mono text-sm text-status-warn">
              Underpush: {data.underpush_count}
            </span>
          </div>

          {chartData.length === 0 ? (
            <p className="text-text-muted">No session scores in this date range.</p>
          ) : (
            <ResponsiveContainer width="100%" height={300}>
              <LineChart data={chartData}>
                <CartesianGrid stroke="var(--color-border)" strokeDasharray="3 3" />
                <XAxis dataKey="date" tick={AXIS_TICK_STYLE} stroke="var(--color-border)" />
                <YAxis domain={[0, 100]} tick={AXIS_TICK_STYLE} stroke="var(--color-border)" />
                <Tooltip
                  contentStyle={TOOLTIP_CONTENT_STYLE}
                  labelStyle={{ color: 'var(--color-text-heading)' }}
                  itemStyle={{ color: 'var(--color-text-primary)' }}
                />
                <Line
                  type="monotone"
                  dataKey="execution_score"
                  stroke="var(--color-accent)"
                  connectNulls
                  dot={{ r: 3, fill: 'var(--color-accent)', strokeWidth: 0 }}
                  activeDot={{ r: 5 }}
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

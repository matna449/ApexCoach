import { useEffect, useState } from 'react'
import {
  Bar,
  BarChart,
  CartesianGrid,
  Legend,
  ResponsiveContainer,
  Tooltip,
  XAxis,
  YAxis,
} from 'recharts'

// F16.3: load actual vs. target, weekly + monthly. Fetches
// GET /api/load/weekly and GET /api/load/monthly (web/backend/main.py) and
// renders each as a grouped bar chart (actual vs. target per period).
const API_BASE_URL = 'http://localhost:8000'

// F19.4 (#107): fixed categorical assignment (dataviz skill: assign hues in
// a fixed order, never cycle by rank) — "Actual" is the single most
// important series here (what really happened), so it gets the reserved
// signature accent token; "Target" is the secondary reference series, so it
// stays a muted neutral tone rather than competing for attention. Both are
// CSS custom properties that resolve against index.css's :root/.dark
// blocks, so they track the manual theme toggle (useTheme.ts) directly
// instead of the OS-only prefers-color-scheme query this file used before.
const COLOR_ACTUAL = 'var(--color-accent)'
const COLOR_TARGET = 'var(--color-border-strong)'
const AXIS_TICK_STYLE = { fill: 'var(--color-text-muted)', fontFamily: 'var(--font-mono)', fontSize: 12 }
const TOOLTIP_CONTENT_STYLE = {
  background: 'var(--color-surface-card)',
  border: '1px solid var(--color-border)',
  borderRadius: 4,
  fontFamily: 'var(--font-mono)',
  fontSize: 12,
}
const LEGEND_WRAPPER_STYLE = { fontFamily: 'var(--font-mono)', fontSize: 12, color: 'var(--color-text-muted)' }

type WeeklyLoadPoint = {
  week_start_date: string
  load_actual: number | null
  load_target: number | null
}

type MonthlyLoadPoint = {
  month_start_date: string
  load_actual_total: number | null
  load_target_total: number | null
}

function useFetchJson<T>(path: string): { data: T | null; error: string | null } {
  const [data, setData] = useState<T | null>(null)
  const [error, setError] = useState<string | null>(null)

  useEffect(() => {
    fetch(`${API_BASE_URL}${path}`)
      .then((res) => {
        if (!res.ok) throw new Error(`GET ${path} returned ${res.status}`)
        return res.json() as Promise<T>
      })
      .then(setData)
      .catch((err: unknown) => setError(err instanceof Error ? err.message : String(err)))
  }, [path])

  return { data, error }
}

function WeeklyChart() {
  const { data, error } = useFetchJson<{ weeks: WeeklyLoadPoint[] }>(
    '/api/load/weekly?weeks=8',
  )

  return (
    <section className="rounded-md border border-border bg-surface-card p-4">
      <h3>Weekly: load actual vs. target</h3>
      {error && <p className="text-status-bad">Error: {error}</p>}
      {!error && !data && <p className="text-text-muted">Loading…</p>}
      {data && (
        <ResponsiveContainer width="100%" height={280}>
          <BarChart data={data.weeks} barGap={2} barCategoryGap="20%">
            <CartesianGrid stroke="var(--color-border)" strokeDasharray="3 3" vertical={false} />
            <XAxis dataKey="week_start_date" tick={AXIS_TICK_STYLE} stroke="var(--color-border)" />
            <YAxis tick={AXIS_TICK_STYLE} stroke="var(--color-border)" />
            <Tooltip
              contentStyle={TOOLTIP_CONTENT_STYLE}
              labelStyle={{ color: 'var(--color-text-heading)' }}
              itemStyle={{ color: 'var(--color-text-primary)' }}
            />
            <Legend wrapperStyle={LEGEND_WRAPPER_STYLE} />
            <Bar dataKey="load_actual" name="Actual" fill={COLOR_ACTUAL} radius={[4, 4, 0, 0]} />
            <Bar dataKey="load_target" name="Target" fill={COLOR_TARGET} radius={[4, 4, 0, 0]} />
          </BarChart>
        </ResponsiveContainer>
      )}
    </section>
  )
}

function MonthlyChart() {
  const { data, error } = useFetchJson<{ months: MonthlyLoadPoint[] }>(
    '/api/load/monthly?months=6',
  )

  return (
    <section className="rounded-md border border-border bg-surface-card p-4">
      <h3>Monthly: load actual vs. target</h3>
      {error && <p className="text-status-bad">Error: {error}</p>}
      {!error && !data && <p className="text-text-muted">Loading…</p>}
      {data && (
        <ResponsiveContainer width="100%" height={280}>
          <BarChart data={data.months} barGap={2} barCategoryGap="20%">
            <CartesianGrid stroke="var(--color-border)" strokeDasharray="3 3" vertical={false} />
            <XAxis dataKey="month_start_date" tick={AXIS_TICK_STYLE} stroke="var(--color-border)" />
            <YAxis tick={AXIS_TICK_STYLE} stroke="var(--color-border)" />
            <Tooltip
              contentStyle={TOOLTIP_CONTENT_STYLE}
              labelStyle={{ color: 'var(--color-text-heading)' }}
              itemStyle={{ color: 'var(--color-text-primary)' }}
            />
            <Legend wrapperStyle={LEGEND_WRAPPER_STYLE} />
            <Bar
              dataKey="load_actual_total"
              name="Actual"
              fill={COLOR_ACTUAL}
              radius={[4, 4, 0, 0]}
            />
            <Bar
              dataKey="load_target_total"
              name="Target"
              fill={COLOR_TARGET}
              radius={[4, 4, 0, 0]}
            />
          </BarChart>
        </ResponsiveContainer>
      )}
    </section>
  )
}

function LoadActualVsTargetChart() {
  return (
    <div className="flex flex-col gap-4">
      <h2>Load: actual vs. target</h2>
      <WeeklyChart />
      <MonthlyChart />
    </div>
  )
}

export default LoadActualVsTargetChart

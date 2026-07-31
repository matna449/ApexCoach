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

// Fixed categorical assignment (dataviz skill: assign hues in a fixed order,
// never cycle by rank) — slot 1 (blue) is always "actual", slot 2 (green)
// is always "target", in both light and dark mode.
const COLOR_ACTUAL = { light: '#2a78d6', dark: '#3987e5' }
const COLOR_TARGET = { light: '#008300', dark: '#008300' }

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

function usePrefersDark(): boolean {
  const [prefersDark, setPrefersDark] = useState(
    () => window.matchMedia?.('(prefers-color-scheme: dark)').matches ?? false,
  )
  useEffect(() => {
    const mql = window.matchMedia('(prefers-color-scheme: dark)')
    const onChange = (e: MediaQueryListEvent) => setPrefersDark(e.matches)
    mql.addEventListener('change', onChange)
    return () => mql.removeEventListener('change', onChange)
  }, [])
  return prefersDark
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

function WeeklyChart({ isDark }: { isDark: boolean }) {
  const { data, error } = useFetchJson<{ weeks: WeeklyLoadPoint[] }>(
    '/api/load/weekly?weeks=8',
  )

  return (
    <section>
      <h3>Weekly: load actual vs. target</h3>
      {error && <p style={{ color: 'red' }}>Error: {error}</p>}
      {!error && !data && <p>Loading…</p>}
      {data && (
        <ResponsiveContainer width="100%" height={280}>
          <BarChart data={data.weeks} barGap={2} barCategoryGap="20%">
            <CartesianGrid strokeDasharray="3 3" vertical={false} opacity={0.3} />
            <XAxis dataKey="week_start_date" tick={{ fontSize: 12 }} />
            <YAxis tick={{ fontSize: 12 }} />
            <Tooltip />
            <Legend />
            <Bar
              dataKey="load_actual"
              name="Actual"
              fill={isDark ? COLOR_ACTUAL.dark : COLOR_ACTUAL.light}
              radius={[4, 4, 0, 0]}
            />
            <Bar
              dataKey="load_target"
              name="Target"
              fill={isDark ? COLOR_TARGET.dark : COLOR_TARGET.light}
              radius={[4, 4, 0, 0]}
            />
          </BarChart>
        </ResponsiveContainer>
      )}
    </section>
  )
}

function MonthlyChart({ isDark }: { isDark: boolean }) {
  const { data, error } = useFetchJson<{ months: MonthlyLoadPoint[] }>(
    '/api/load/monthly?months=6',
  )

  return (
    <section>
      <h3>Monthly: load actual vs. target</h3>
      {error && <p style={{ color: 'red' }}>Error: {error}</p>}
      {!error && !data && <p>Loading…</p>}
      {data && (
        <ResponsiveContainer width="100%" height={280}>
          <BarChart data={data.months} barGap={2} barCategoryGap="20%">
            <CartesianGrid strokeDasharray="3 3" vertical={false} opacity={0.3} />
            <XAxis dataKey="month_start_date" tick={{ fontSize: 12 }} />
            <YAxis tick={{ fontSize: 12 }} />
            <Tooltip />
            <Legend />
            <Bar
              dataKey="load_actual_total"
              name="Actual"
              fill={isDark ? COLOR_ACTUAL.dark : COLOR_ACTUAL.light}
              radius={[4, 4, 0, 0]}
            />
            <Bar
              dataKey="load_target_total"
              name="Target"
              fill={isDark ? COLOR_TARGET.dark : COLOR_TARGET.light}
              radius={[4, 4, 0, 0]}
            />
          </BarChart>
        </ResponsiveContainer>
      )}
    </section>
  )
}

function LoadActualVsTargetChart() {
  const isDark = usePrefersDark()

  return (
    <div>
      <h2>Load: actual vs. target</h2>
      <WeeklyChart isDark={isDark} />
      <MonthlyChart isDark={isDark} />
    </div>
  )
}

export default LoadActualVsTargetChart

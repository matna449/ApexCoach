import { afterEach, describe, expect, it, vi } from 'vitest'
import { cleanup, render, screen, waitFor, within } from '@testing-library/react'
import MonthView from './MonthView'
import type { MonthPlanResponse } from './planTypes'

// F19.5 (#120): MonthView fetches GET /api/plan/month for the current month
// (computed client-side) and renders one WeekGrid (F19.4's own per-day
// cards) per week the backend returns. Mirrors PlanView.test.tsx's
// fetch-mocking pattern.
afterEach(() => {
  cleanup()
  vi.restoreAllMocks()
})

function jsonResponse(status: number, body: unknown): Response {
  return {
    ok: status >= 200 && status < 300,
    status,
    json: async () => body,
  } as Response
}

function installFetch(handler: (url: string) => Response) {
  const fetchMock = vi.fn(async (url: string) => handler(url))
  vi.stubGlobal('fetch', fetchMock)
  return fetchMock
}

const FIXED_NOW = new Date(2026, 7, 2) // 2026-08-02
const EXPECTED_MONTH = '2026-08'

function withFixedNow(fn: () => void) {
  vi.useFakeTimers()
  vi.setSystemTime(FIXED_NOW)
  try {
    fn()
  } finally {
    vi.useRealTimers()
  }
}

describe('MonthView', () => {
  it('renders one week grid per week overlapping the month, with day cards from F19.4', async () => {
    const plan: MonthPlanResponse = {
      month: EXPECTED_MONTH,
      weeks: [
        {
          week_start_date: '2026-07-27',
          generated: true,
          days: [
            {
              day: 'Monday',
              session_type: 'HIIT',
              structure: {
                type: 'intervals',
                rep_count: 6,
                work_zone: 'zone5',
                work_hr_bpm: 172,
                work_min: 3,
                recovery_zone: 'zone2',
                recovery_hr_bpm: 140,
                recovery_min: 2,
                warmup_cooldown_min: 10,
                total_duration_min: 40,
              },
              pushed: false,
            },
          ],
        },
        {
          week_start_date: '2026-08-03',
          generated: false,
          days: [],
        },
      ],
    }

    const fetchMock = installFetch((url) => {
      if (url.includes('/api/plan/month')) return jsonResponse(200, plan)
      throw new Error(`unexpected fetch: ${url}`)
    })

    withFixedNow(() => render(<MonthView />))

    expect(await screen.findByTestId('plan-month-heading')).toHaveTextContent(EXPECTED_MONTH)

    // Both weeks render, each with a full 7-day grid (F19.4's DayCard, via
    // WeekGrid), even the ungenerated one.
    const firstWeek = screen.getByTestId('plan-month-week-2026-07-27')
    const secondWeek = screen.getByTestId('plan-month-week-2026-08-03')
    expect(firstWeek).toBeInTheDocument()
    expect(secondWeek).toBeInTheDocument()
    // Every weekday card renders in both weeks (7 days x 2 weeks) --
    // reusing F19.4's DayCard, not a parallel implementation.
    expect(screen.getAllByTestId('plan-day-Monday')).toHaveLength(2)
    expect(within(firstWeek).getByTestId('plan-day-session-type-Monday')).toHaveTextContent('HIIT')
    expect(within(secondWeek).getByTestId('plan-day-Monday')).toHaveTextContent('No session planned')
    expect(screen.getByTestId('plan-month-week-not-generated-2026-08-03')).toHaveTextContent(
      'No structured plan generated yet for this week.',
    )

    const call = fetchMock.mock.calls.find(([url]) => (url as string).includes('/api/plan/month'))
    expect(call).toBeDefined()
    expect(call![0]).toContain(`month=${EXPECTED_MONTH}`)
  })

  it('surfaces a fetch error', async () => {
    installFetch(() => jsonResponse(500, { detail: 'boom' }))

    withFixedNow(() => render(<MonthView />))

    await waitFor(() => expect(screen.getByTestId('plan-month-error')).toHaveTextContent('boom'))
  })
})

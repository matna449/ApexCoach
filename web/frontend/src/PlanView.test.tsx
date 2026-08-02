import { afterEach, describe, expect, it, vi } from 'vitest'
import { cleanup, render, screen, waitFor } from '@testing-library/react'
import PlanView from './PlanView'
import type { WeekPlanResponse } from './planTypes'

// F19.4 (#119): PlanView fetches GET /api/plan/week for the current week
// (Monday computed client-side) and renders 7 day cards. Mirrors
// MorningView.test.tsx's fetch-mocking pattern.
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

// Sunday, so weekStart resolves to the Monday six days earlier -- exercises
// the "week wraps into the previous month" arithmetic in mondayOf/dateForDay.
const FIXED_NOW = new Date(2026, 7, 2) // 2026-08-02 (Sunday)
const EXPECTED_WEEK_START = '2026-07-27'

function withFixedNow(fn: () => void) {
  vi.useFakeTimers()
  vi.setSystemTime(FIXED_NOW)
  try {
    fn()
  } finally {
    vi.useRealTimers()
  }
}

describe('PlanView', () => {
  it('renders 7 days with generated structure, segments, zones, and "Not pushed"', async () => {
    const plan: WeekPlanResponse = {
      week_start_date: EXPECTED_WEEK_START,
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
        {
          day: 'Tuesday',
          session_type: 'Zone2_Long',
          structure: {
            type: 'single_block',
            zone: 'zone2',
            target_hr_bpm: 140,
            main_set_min: 60,
            warmup_cooldown_min: 10,
            total_duration_min: 70,
          },
          pushed: false,
        },
        {
          day: 'Wednesday',
          session_type: 'Rest',
          structure: { type: 'rest', duration_min: 0 },
          pushed: false,
        },
      ],
    }

    const fetchMock = installFetch((url) => {
      if (url.includes('/api/plan/week')) return jsonResponse(200, plan)
      throw new Error(`unexpected fetch: ${url}`)
    })

    withFixedNow(() => render(<PlanView />))

    expect(await screen.findByTestId('plan-week-heading')).toHaveTextContent(EXPECTED_WEEK_START)

    // All 7 weekday cards render, even the 4 with no planned session.
    for (const day of ['Monday', 'Tuesday', 'Wednesday', 'Thursday', 'Friday', 'Saturday', 'Sunday']) {
      expect(screen.getByTestId(`plan-day-${day}`)).toBeInTheDocument()
    }
    expect(screen.getByTestId('plan-day-Thursday')).toHaveTextContent('No session planned')

    expect(screen.getByTestId('plan-day-session-type-Monday')).toHaveTextContent('HIIT')
    expect(screen.getByTestId('plan-day-Monday')).toHaveTextContent('6× intervals')
    expect(screen.getByTestId('plan-day-Monday')).toHaveTextContent('Zone 5')
    expect(screen.getByTestId('plan-day-Monday')).toHaveTextContent('40 min total')
    expect(screen.getByTestId('plan-day-pushed-Monday')).toHaveTextContent('Not pushed')

    expect(screen.getByTestId('plan-day-session-type-Tuesday')).toHaveTextContent('Zone2_Long')
    expect(screen.getByTestId('plan-day-Tuesday')).toHaveTextContent('60 min @ Zone 2')
    expect(screen.getByTestId('plan-day-pushed-Tuesday')).toHaveTextContent('Not pushed')

    expect(screen.getByTestId('plan-day-session-type-Wednesday')).toHaveTextContent('Rest')
    expect(screen.getByTestId('plan-day-Wednesday')).toHaveTextContent('Rest day')

    const call = fetchMock.mock.calls.find(([url]) => (url as string).includes('/api/plan/week'))
    expect(call).toBeDefined()
    expect(call![0]).toContain(`week_start=${EXPECTED_WEEK_START}`)
  })

  it('not-yet-generated week: shows the empty-state message and placeholder cards', async () => {
    const plan: WeekPlanResponse = { week_start_date: EXPECTED_WEEK_START, generated: false, days: [] }
    installFetch((url) => {
      if (url.includes('/api/plan/week')) return jsonResponse(200, plan)
      throw new Error(`unexpected fetch: ${url}`)
    })

    withFixedNow(() => render(<PlanView />))

    expect(await screen.findByTestId('plan-not-generated')).toHaveTextContent(
      'No structured plan generated yet for this week.',
    )
    expect(screen.getByTestId('plan-day-Monday')).toHaveTextContent('No session planned')
  })

  it('surfaces a fetch error', async () => {
    installFetch(() => jsonResponse(500, { detail: 'boom' }))

    withFixedNow(() => render(<PlanView />))

    await waitFor(() => expect(screen.getByTestId('plan-error')).toHaveTextContent('boom'))
  })
})

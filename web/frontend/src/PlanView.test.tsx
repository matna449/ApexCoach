import { afterEach, describe, expect, it, vi } from 'vitest'
import { cleanup, fireEvent, render, screen, waitFor } from '@testing-library/react'
import PlanView from './PlanView'
import type { PushWeekResponse, WeekPlanResponse } from './planTypes'

// F19.4 (#119): PlanView fetches GET /api/plan/week for the current week
// (Monday computed client-side) and renders 7 day cards. Mirrors
// MorningView.test.tsx's fetch-mocking pattern.
//
// F19.7 (#123): adds coverage for the "Push to intervals.icu" button --
// POSTs /api/plan/week/push, refetches on success, surfaces errors, and is
// hidden (replaced by a message) when activity_sync_provider is STRAVA.
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

const GENERATED_PLAN: WeekPlanResponse = {
  week_start_date: EXPECTED_WEEK_START,
  generated: true,
  activity_sync_provider: 'INTERVALS_ICU',
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
      pushed: true,
    },
    {
      day: 'Wednesday',
      session_type: 'Rest',
      structure: { type: 'rest', duration_min: 0 },
      pushed: false,
    },
  ],
}

describe('PlanView', () => {
  it('renders 7 days with generated structure, segments, zones, and per-session Pushed/Draft status', async () => {
    const fetchMock = installFetch((url) => {
      if (url.includes('/api/plan/week')) return jsonResponse(200, GENERATED_PLAN)
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
    // Monday has no event id -- local-only draft.
    expect(screen.getByTestId('plan-day-pushed-Monday')).toHaveTextContent('Draft')

    expect(screen.getByTestId('plan-day-session-type-Tuesday')).toHaveTextContent('Zone2_Long')
    expect(screen.getByTestId('plan-day-Tuesday')).toHaveTextContent('60 min @ Zone 2')
    // Tuesday has an event id -- already pushed.
    expect(screen.getByTestId('plan-day-pushed-Tuesday')).toHaveTextContent('Pushed')

    expect(screen.getByTestId('plan-day-session-type-Wednesday')).toHaveTextContent('Rest')
    expect(screen.getByTestId('plan-day-Wednesday')).toHaveTextContent('Rest day')

    const call = fetchMock.mock.calls.find(([url]) => (url as string).includes('/api/plan/week'))
    expect(call).toBeDefined()
    expect(call![0]).toContain(`week_start=${EXPECTED_WEEK_START}`)
  })

  it('not-yet-generated week: shows the empty-state message, placeholder cards, and no push button', async () => {
    const plan: WeekPlanResponse = {
      week_start_date: EXPECTED_WEEK_START,
      generated: false,
      activity_sync_provider: 'INTERVALS_ICU',
      days: [],
    }
    installFetch((url) => {
      if (url.includes('/api/plan/week')) return jsonResponse(200, plan)
      throw new Error(`unexpected fetch: ${url}`)
    })

    withFixedNow(() => render(<PlanView />))

    expect(await screen.findByTestId('plan-not-generated')).toHaveTextContent(
      'No structured plan generated yet for this week.',
    )
    expect(screen.getByTestId('plan-day-Monday')).toHaveTextContent('No session planned')
    // Nothing generated yet -- nothing to push.
    expect(screen.queryByTestId('push-week-button')).not.toBeInTheDocument()
  })

  it('surfaces a fetch error', async () => {
    installFetch(() => jsonResponse(500, { detail: 'boom' }))

    withFixedNow(() => render(<PlanView />))

    await waitFor(() => expect(screen.getByTestId('plan-error')).toHaveTextContent('boom'))
  })

  it('clicking "Push to intervals.icu" pushes the week and refetches updated push status', async () => {
    const pushedPlan: WeekPlanResponse = {
      ...GENERATED_PLAN,
      days: GENERATED_PLAN.days.map((d) => ({ ...d, pushed: true })),
    }
    const pushResponse: PushWeekResponse = {
      week_start_date: EXPECTED_WEEK_START,
      pushed_days: [
        { day: 'Monday', event_id: 'evt-1' },
        { day: 'Tuesday', event_id: 'evt-2' },
        { day: 'Wednesday', event_id: 'evt-3' },
      ],
    }

    let getCallCount = 0
    const fetchMock = vi.fn(async (url: string, init?: RequestInit) => {
      if (url.includes('/api/plan/week/push') && init?.method === 'POST') {
        return jsonResponse(200, pushResponse)
      }
      if (url.includes('/api/plan/week')) {
        getCallCount += 1
        return jsonResponse(200, getCallCount === 1 ? GENERATED_PLAN : pushedPlan)
      }
      throw new Error(`unexpected fetch: ${url}`)
    })
    vi.stubGlobal('fetch', fetchMock)

    withFixedNow(() => render(<PlanView />))

    const button = await screen.findByTestId('push-week-button')
    expect(button).toHaveTextContent('Push to intervals.icu')
    expect(screen.getByTestId('plan-day-pushed-Monday')).toHaveTextContent('Draft')

    fireEvent.click(button)

    await waitFor(() => expect(screen.getByTestId('plan-day-pushed-Monday')).toHaveTextContent('Pushed'))

    const pushCall = fetchMock.mock.calls.find(([url]) => (url as string).includes('/api/plan/week/push'))
    expect(pushCall).toBeDefined()
    expect(pushCall![0]).toContain(`week_start=${EXPECTED_WEEK_START}`)
    expect(pushCall![1]).toMatchObject({ method: 'POST' })
  })

  it('surfaces a push error without losing the loaded plan', async () => {
    const fetchMock = vi.fn(async (url: string, init?: RequestInit) => {
      if (url.includes('/api/plan/week/push') && init?.method === 'POST') {
        return jsonResponse(400, { detail: 'no generated structure' })
      }
      if (url.includes('/api/plan/week')) return jsonResponse(200, GENERATED_PLAN)
      throw new Error(`unexpected fetch: ${url}`)
    })
    vi.stubGlobal('fetch', fetchMock)

    withFixedNow(() => render(<PlanView />))

    const button = await screen.findByTestId('push-week-button')
    fireEvent.click(button)

    await waitFor(() =>
      expect(screen.getByTestId('push-error')).toHaveTextContent('no generated structure'),
    )
    // The already-loaded week grid is still shown alongside the error.
    expect(screen.getByTestId('plan-day-Monday')).toBeInTheDocument()
  })

  it('hides the push button and shows a message when the provider is Strava', async () => {
    const stravaPlan: WeekPlanResponse = { ...GENERATED_PLAN, activity_sync_provider: 'STRAVA' }
    installFetch((url) => {
      if (url.includes('/api/plan/week')) return jsonResponse(200, stravaPlan)
      throw new Error(`unexpected fetch: ${url}`)
    })

    withFixedNow(() => render(<PlanView />))

    expect(await screen.findByTestId('push-disabled-strava')).toHaveTextContent(
      'configured provider is Strava',
    )
    expect(screen.queryByTestId('push-week-button')).not.toBeInTheDocument()
  })
})

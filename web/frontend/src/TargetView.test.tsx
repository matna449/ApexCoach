import { afterEach, describe, expect, it, vi } from 'vitest'
import { cleanup, fireEvent, render, screen, waitFor } from '@testing-library/react'
import TargetView from './TargetView'
import type { MonthlyTargetResponse, SetMonthlyTargetResponse } from './planTypes'

// F19.8 (#137): TargetView fetches GET /api/plan/month/target for the
// current month (computed client-side) and either shows a read-only summary
// (target already set) or a SelectCard-driven create form (no target yet).
// Mirrors PlanView.test.tsx's fetch-mocking pattern.
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

function installFetch(handler: (url: string, init?: RequestInit) => Response) {
  const fetchMock = vi.fn(async (url: string, init?: RequestInit) => handler(url, init))
  vi.stubGlobal('fetch', fetchMock)
  return fetchMock
}

const FIXED_NOW = new Date(2026, 7, 2) // 2026-08-02
const EXPECTED_MONTH_START = '2026-08-01'

function withFixedNow(fn: () => void) {
  vi.useFakeTimers()
  vi.setSystemTime(FIXED_NOW)
  try {
    fn()
  } finally {
    vi.useRealTimers()
  }
}

describe('TargetView', () => {
  it('no target set: shows the empty state and a create form', async () => {
    const notSet: MonthlyTargetResponse = {
      month_start_date: EXPECTED_MONTH_START,
      exists: false,
      periodisation_phase: null,
      load_target_total: null,
      race_date: null,
    }
    const fetchMock = installFetch((url) => {
      if (url.includes('/api/plan/month/target')) return jsonResponse(200, notSet)
      throw new Error(`unexpected fetch: ${url}`)
    })

    withFixedNow(() => render(<TargetView />))

    expect(await screen.findByTestId('target-not-set')).toBeInTheDocument()
    expect(screen.getByTestId('target-form')).toBeInTheDocument()
    expect(screen.queryByTestId('target-summary')).not.toBeInTheDocument()
    // Save is disabled until a phase and a load target are chosen.
    expect(screen.getByTestId('target-save-button')).toBeDisabled()

    const call = fetchMock.mock.calls.find(([url]) => (url as string).includes('/api/plan/month/target'))
    expect(call).toBeDefined()
    expect(call![0]).toContain(`month_start=${EXPECTED_MONTH_START}`)
  })

  it('creates a new target: picking a phase, entering a load target, and saving POSTs and shows the summary', async () => {
    const notSet: MonthlyTargetResponse = {
      month_start_date: EXPECTED_MONTH_START,
      exists: false,
      periodisation_phase: null,
      load_target_total: null,
      race_date: null,
    }
    const created: SetMonthlyTargetResponse = {
      month_start_date: EXPECTED_MONTH_START,
      created: true,
      periodisation_phase: 'BUILD',
      load_target_total: 450,
      race_date: '2026-09-15',
    }

    const fetchMock = vi.fn(async (url: string, init?: RequestInit) => {
      if (url.includes('/api/plan/month/target') && init?.method === 'POST') {
        return jsonResponse(200, created)
      }
      if (url.includes('/api/plan/month/target')) return jsonResponse(200, notSet)
      throw new Error(`unexpected fetch: ${url}`)
    })
    vi.stubGlobal('fetch', fetchMock)

    withFixedNow(() => render(<TargetView />))

    await screen.findByTestId('target-form')

    fireEvent.click(screen.getByTestId('target-phase-BUILD'))
    fireEvent.change(screen.getByTestId('target-load-input'), { target: { value: '450' } })
    fireEvent.change(screen.getByTestId('target-race-date-input'), { target: { value: '2026-09-15' } })

    const saveButton = screen.getByTestId('target-save-button')
    expect(saveButton).not.toBeDisabled()
    fireEvent.click(saveButton)

    await waitFor(() => expect(screen.getByTestId('target-summary')).toBeInTheDocument())
    expect(screen.getByTestId('target-summary-phase')).toHaveTextContent('BUILD')
    expect(screen.getByTestId('target-summary-load')).toHaveTextContent('450')
    expect(screen.getByTestId('target-summary-race-date')).toHaveTextContent('2026-09-15')

    const postCall = fetchMock.mock.calls.find(
      ([url, init]) => (url as string).includes('/api/plan/month/target') && (init as RequestInit)?.method === 'POST',
    )
    expect(postCall).toBeDefined()
    expect(postCall![0]).toContain(`month_start=${EXPECTED_MONTH_START}`)
    expect(JSON.parse((postCall![1] as RequestInit).body as string)).toEqual({
      periodisation_phase: 'BUILD',
      load_target_total: 450,
      race_date: '2026-09-15',
    })
  })

  it('target already set: shows a read-only summary, and Edit reveals a pre-filled form', async () => {
    const existing: MonthlyTargetResponse = {
      month_start_date: EXPECTED_MONTH_START,
      exists: true,
      periodisation_phase: 'PEAK',
      load_target_total: 500,
      race_date: '2026-09-01',
    }
    installFetch((url) => {
      if (url.includes('/api/plan/month/target')) return jsonResponse(200, existing)
      throw new Error(`unexpected fetch: ${url}`)
    })

    withFixedNow(() => render(<TargetView />))

    expect(await screen.findByTestId('target-summary')).toBeInTheDocument()
    expect(screen.getByTestId('target-summary-phase')).toHaveTextContent('PEAK')
    expect(screen.getByTestId('target-summary-load')).toHaveTextContent('500')
    expect(screen.queryByTestId('target-form')).not.toBeInTheDocument()

    fireEvent.click(screen.getByTestId('target-edit-button'))

    expect(screen.getByTestId('target-form')).toBeInTheDocument()
    expect(screen.queryByTestId('target-summary')).not.toBeInTheDocument()
    expect(screen.getByTestId('target-phase-PEAK')).toHaveAttribute('aria-pressed', 'true')
    expect(screen.getByTestId('target-load-input')).toHaveValue(500)
    expect(screen.getByTestId('target-race-date-input')).toHaveValue('2026-09-01')

    fireEvent.click(screen.getByTestId('target-cancel-button'))

    expect(screen.getByTestId('target-summary')).toBeInTheDocument()
    expect(screen.queryByTestId('target-form')).not.toBeInTheDocument()
  })

  it('surfaces a fetch error', async () => {
    installFetch(() => jsonResponse(500, { detail: 'boom' }))

    withFixedNow(() => render(<TargetView />))

    await waitFor(() => expect(screen.getByTestId('target-error')).toHaveTextContent('boom'))
  })

  it('surfaces a save error without losing the form', async () => {
    const notSet: MonthlyTargetResponse = {
      month_start_date: EXPECTED_MONTH_START,
      exists: false,
      periodisation_phase: null,
      load_target_total: null,
      race_date: null,
    }
    const fetchMock = vi.fn(async (url: string, init?: RequestInit) => {
      if (url.includes('/api/plan/month/target') && init?.method === 'POST') {
        return jsonResponse(400, { detail: 'unknown periodisation_phase' })
      }
      if (url.includes('/api/plan/month/target')) return jsonResponse(200, notSet)
      throw new Error(`unexpected fetch: ${url}`)
    })
    vi.stubGlobal('fetch', fetchMock)

    withFixedNow(() => render(<TargetView />))

    await screen.findByTestId('target-form')
    fireEvent.click(screen.getByTestId('target-phase-BASE'))
    fireEvent.change(screen.getByTestId('target-load-input'), { target: { value: '300' } })
    fireEvent.click(screen.getByTestId('target-save-button'))

    await waitFor(() =>
      expect(screen.getByTestId('target-save-error')).toHaveTextContent('unknown periodisation_phase'),
    )
    // The form is still shown so the athlete can fix and retry.
    expect(screen.getByTestId('target-form')).toBeInTheDocument()
  })
})

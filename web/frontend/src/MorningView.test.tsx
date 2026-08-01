import { afterEach, describe, expect, it, vi } from 'vitest'
import { cleanup, render, screen, waitFor, waitForElementToBeRemoved } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import MorningView from './MorningView'
import type { DecisionResponse, MorningContext, NoPlanDetail } from './morningTypes'

// F19.2 (#105): integration coverage for the conversational morning flow,
// equivalent to the CLI's morning-command behaviors (test_cli_morning.py):
// happy path, the no-plan/session-type-fallback path, a joint-pain-style
// override, and the degraded-Ollama WARN banner. All fetch calls are
// mocked; request shapes are asserted to prove #105 didn't change the wire
// contract #85 already established.
afterEach(() => {
  cleanup()
  vi.restoreAllMocks()
})

const BIOMETRICS = {
  whoop_recovery_pct: 62,
  whoop_hrv_ms: 71.4,
  whoop_rhr_bpm: 48,
  whoop_strain: 8.4,
  whoop_sleep_hours: 7.5,
}

const QUESTIONS = {
  fixed: [
    { key: 'muscle_soreness', text: 'How is your overall muscle soreness right now?' },
    { key: 'subjective_energy', text: 'How is your subjective energy level today?' },
    { key: 'sleep_quality_felt', text: 'How was your sleep quality last night?' },
  ],
  adaptive: [{ key: 'left_knee_pain', text: 'Left knee pain (1-5)?' }],
}

function makeContext(sessionType = 'HIIT'): MorningContext {
  return { date: '2026-08-01', session_type: sessionType, biometrics: BIOMETRICS, questions: QUESTIONS }
}

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

async function answerAllQuestions(user: ReturnType<typeof userEvent.setup>) {
  for (const q of [...QUESTIONS.fixed, ...QUESTIONS.adaptive]) {
    const button = await screen.findByTestId(`answer-${q.key}-3`)
    await user.click(button)
  }
}

describe('MorningView', () => {
  it('happy path: fetches context, answers the health check, and renders the verdict', async () => {
    const context = makeContext()
    const decision: DecisionResponse = {
      recommendation: 'GO',
      rationale: 'Recovery and HRV both look solid this morning.',
      check_recovery_week_trigger: false,
      override_triggered: false,
      override_reasons: [],
      explanation: 'You are well recovered -- proceed as planned.',
      banner: null,
      severity: null,
      decision_context: { date: '2026-08-01' },
    }

    const fetchMock = installFetch((url) => {
      if (url.includes('/api/morning/decision')) return jsonResponse(200, decision)
      if (url.includes('/api/morning/context')) return jsonResponse(200, context)
      throw new Error(`unexpected fetch: ${url}`)
    })

    const user = userEvent.setup()
    render(<MorningView />)

    await waitForElementToBeRemoved(() => screen.queryByTestId('typing-indicator'))
    expect(screen.getByTestId('biometrics-header')).toHaveTextContent('62%')

    await answerAllQuestions(user)
    await user.click(await screen.findByTestId('confirm-decision'))

    await waitFor(() => expect(screen.getByTestId('verdict-stamp')).toHaveTextContent('GO'))
    expect(screen.getByTestId('morning-explanation')).toHaveTextContent(decision.explanation!)
    expect(screen.getByTestId('morning-followup')).toBeInTheDocument()

    const decisionCall = fetchMock.mock.calls.find(([url]) => (url as string).includes('/api/morning/decision'))
    expect(decisionCall).toBeDefined()
    const [, init] = decisionCall!
    expect(init?.method).toBe('POST')
    expect(JSON.parse(init!.body as string)).toEqual({
      date: '2026-08-01',
      session_type: 'HIIT',
      fixed_answers: { muscle_soreness: 3, subjective_energy: 3, sleep_quality_felt: 3 },
      adaptive_answers: { left_knee_pain: 3 },
    })
  })

  it('no-plan fallback: surfaces the session-type picker as the first question, then proceeds', async () => {
    const detail: NoPlanDetail = {
      error: 'no_plan_for_date',
      message: 'No weekly plan covers this date -- pick a session type to continue.',
      biometrics: BIOMETRICS,
      available_session_types: ['HIIT', 'Threshold', 'Zone2_Long', 'Strength', 'Recovery', 'Rest'],
    }
    const context = makeContext('Strength')

    installFetch((url) => {
      if (url.includes('session_type=Strength')) return jsonResponse(200, context)
      if (url.includes('/api/morning/context')) return jsonResponse(409, { detail })
      throw new Error(`unexpected fetch: ${url}`)
    })

    const user = userEvent.setup()
    render(<MorningView />)

    const picker = await screen.findByTestId('morning-session-picker')
    expect(picker).toHaveTextContent(detail.message)
    // Biometrics render even before a session type is picked.
    expect(screen.getByTestId('biometrics-header')).toHaveTextContent('62%')
    // No health-check question is shown yet -- the picker comes first.
    expect(screen.queryByTestId('question-muscle_soreness')).not.toBeInTheDocument()

    await user.click(screen.getByTestId('session-type-Strength'))

    expect(await screen.findByTestId('question-muscle_soreness')).toBeInTheDocument()
  })

  it('joint-pain override: renders the override reasons and MODIFY verdict', async () => {
    const context = makeContext()
    const decision: DecisionResponse = {
      recommendation: 'MODIFY',
      rationale: 'Reported knee pain triggered an override.',
      check_recovery_week_trigger: false,
      override_triggered: true,
      override_reasons: ['health_check_override: left_knee_pain = 4'],
      explanation: 'Swap to a lower-impact session today.',
      banner: null,
      severity: null,
      decision_context: {},
    }

    installFetch((url) => {
      if (url.includes('/api/morning/decision')) return jsonResponse(200, decision)
      if (url.includes('/api/morning/context')) return jsonResponse(200, context)
      throw new Error(`unexpected fetch: ${url}`)
    })

    const user = userEvent.setup()
    render(<MorningView />)

    await answerAllQuestions(user)
    await user.click(await screen.findByTestId('confirm-decision'))

    await waitFor(() => expect(screen.getByTestId('verdict-stamp')).toHaveTextContent('MODIFY'))
    expect(screen.getByTestId('morning-override')).toHaveTextContent('health_check_override: left_knee_pain = 4')
  })

  it('degraded-Ollama banner: renders the WARN badge with unchanged banner content, no followup', async () => {
    const context = makeContext()
    const decision: DecisionResponse = {
      recommendation: 'GO',
      rationale: 'Recovery looks fine.',
      check_recovery_week_trigger: false,
      override_triggered: false,
      override_reasons: [],
      explanation: null,
      banner: '[Ollama offline -- start with: ollama serve]',
      severity: 'WARN',
      decision_context: {},
    }

    installFetch((url) => {
      if (url.includes('/api/morning/decision')) return jsonResponse(200, decision)
      if (url.includes('/api/morning/context')) return jsonResponse(200, context)
      throw new Error(`unexpected fetch: ${url}`)
    })

    const user = userEvent.setup()
    render(<MorningView />)

    await answerAllQuestions(user)
    await user.click(await screen.findByTestId('confirm-decision'))

    const banner = await screen.findByTestId('morning-banner')
    expect(banner).toHaveTextContent('WARN')
    expect(banner).toHaveTextContent('[Ollama offline -- start with: ollama serve]')
    // A degraded explanation (null) means no explanation bubble and no
    // follow-up loop offered -- matches the CLI's parity behavior.
    expect(screen.queryByTestId('morning-explanation')).not.toBeInTheDocument()
    expect(screen.queryByTestId('morning-followup')).not.toBeInTheDocument()
  })
})

import { useEffect, useState } from 'react'

// F17.1/F17.2/F17.3 (#83/#84/#85): the web UI's primary screen. Fetches
// GET /api/morning/context on load (real WHOOP fetch + session resolution
// + question catalog), POSTs the answered form to /api/morning/decision
// (health check -> classify -> decide -> Ollama explain), then offers a
// POST /api/morning/followup chat loop once an explanation is available.
const API_BASE_URL = 'http://localhost:8000'

type Biometrics = {
  whoop_recovery_pct: number | null
  whoop_hrv_ms: number | null
  whoop_rhr_bpm: number | null
  whoop_strain: number | null
  whoop_sleep_hours: number | null
}

type Question = { key: string; text: string }

type QuestionCatalog = { fixed: Question[]; adaptive: Question[] }

type MorningContext = {
  date: string
  session_type: string
  biometrics: Biometrics
  questions: QuestionCatalog
}

type NoPlanDetail = {
  error: 'no_plan_for_date'
  message: string
  biometrics: Biometrics
  available_session_types: string[]
}

type DecisionResponse = {
  recommendation: string
  rationale: string | null
  check_recovery_week_trigger: boolean
  override_triggered: boolean
  override_reasons: string[]
  explanation: string | null
  banner: string | null
  severity: 'WARN' | 'INFO' | null
  decision_context: object
}

type FollowupResult = { explanation: string | null; banner: string | null; severity: 'WARN' | 'INFO' | null }

type FollowupTurn = { question: string } & FollowupResult

type LoadState =
  | { kind: 'loading' }
  | { kind: 'need-session-type'; detail: NoPlanDetail }
  | { kind: 'ready'; context: MorningContext }
  | { kind: 'submitting'; context: MorningContext }
  | { kind: 'decided'; context: MorningContext; decision: DecisionResponse }
  | { kind: 'error'; message: string }

async function extractErrorMessage(res: Response, fallback: string): Promise<string> {
  const body = (await res.json().catch(() => null)) as { detail?: unknown } | null
  const detail = body?.detail
  return typeof detail === 'string' ? detail : fallback
}

async function fetchContext(date: string, sessionType?: string): Promise<LoadState> {
  const params = new URLSearchParams({ date })
  if (sessionType) params.set('session_type', sessionType)

  let res: Response
  try {
    res = await fetch(`${API_BASE_URL}/api/morning/context?${params.toString()}`)
  } catch (err: unknown) {
    return { kind: 'error', message: err instanceof Error ? err.message : String(err) }
  }

  if (res.status === 409) {
    const body = (await res.json()) as { detail: NoPlanDetail }
    return { kind: 'need-session-type', detail: body.detail }
  }
  if (!res.ok) {
    return {
      kind: 'error',
      message: await extractErrorMessage(res, `GET /api/morning/context returned ${res.status}`),
    }
  }
  const context = (await res.json()) as MorningContext
  return { kind: 'ready', context }
}

async function submitDecision(
  context: MorningContext,
  fixedAnswers: Record<string, number>,
  adaptiveAnswers: Record<string, number>,
): Promise<LoadState> {
  let res: Response
  try {
    res = await fetch(`${API_BASE_URL}/api/morning/decision`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({
        date: context.date,
        session_type: context.session_type,
        fixed_answers: fixedAnswers,
        adaptive_answers: adaptiveAnswers,
      }),
    })
  } catch (err: unknown) {
    return { kind: 'error', message: err instanceof Error ? err.message : String(err) }
  }

  if (!res.ok) {
    return {
      kind: 'error',
      message: await extractErrorMessage(res, `POST /api/morning/decision returned ${res.status}`),
    }
  }
  const decision = (await res.json()) as DecisionResponse
  return { kind: 'decided', context, decision }
}

async function submitFollowup(
  decisionContext: object,
  priorExplanation: string,
  question: string,
): Promise<FollowupResult | { error: string }> {
  let res: Response
  try {
    res = await fetch(`${API_BASE_URL}/api/morning/followup`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({
        decision_context: decisionContext,
        prior_explanation: priorExplanation,
        question,
      }),
    })
  } catch (err: unknown) {
    return { error: err instanceof Error ? err.message : String(err) }
  }
  if (!res.ok) {
    return { error: await extractErrorMessage(res, `POST /api/morning/followup returned ${res.status}`) }
  }
  return (await res.json()) as FollowupResult
}

function BiometricsSummary({ biometrics }: { biometrics: Biometrics }) {
  return (
    <dl data-testid="morning-biometrics">
      <dt>Recovery</dt>
      <dd>{biometrics.whoop_recovery_pct ?? '—'}%</dd>
      <dt>HRV</dt>
      <dd>{biometrics.whoop_hrv_ms ?? '—'} ms</dd>
      <dt>Resting HR</dt>
      <dd>{biometrics.whoop_rhr_bpm ?? '—'} bpm</dd>
      <dt>Strain</dt>
      <dd>{biometrics.whoop_strain ?? '—'}</dd>
      <dt>Sleep</dt>
      <dd>{biometrics.whoop_sleep_hours ?? '—'} hrs</dd>
    </dl>
  )
}

function QuestionInput({ question }: { question: Question }) {
  return (
    <label>
      {question.text} (1-5)
      <input type="number" min={1} max={5} step={1} name={question.key} required />
    </label>
  )
}

function FollowupChat({
  decisionContext,
  initialExplanation,
}: {
  decisionContext: object
  initialExplanation: string
}) {
  const [turns, setTurns] = useState<FollowupTurn[]>([])
  const [priorExplanation, setPriorExplanation] = useState(initialExplanation)
  const [question, setQuestion] = useState('')
  const [pending, setPending] = useState(false)
  const [error, setError] = useState<string | null>(null)

  async function handleAsk(e: React.FormEvent<HTMLFormElement>) {
    e.preventDefault()
    const asked = question.trim()
    // Empty input ends the loop cleanly — nothing forces further questions.
    if (!asked) return

    setPending(true)
    setError(null)
    const result = await submitFollowup(decisionContext, priorExplanation, asked)
    setPending(false)

    if ('error' in result) {
      setError(result.error)
      return
    }
    setTurns((prev) => [...prev, { question: asked, ...result }])
    // Only advance the conversation on a real answer — a degraded
    // follow-up keeps the prior explanation as the anchor for the next
    // question, matching the CLI's _run_followup_loop().
    if (result.explanation) {
      setPriorExplanation(result.explanation)
    }
    setQuestion('')
  }

  return (
    <div data-testid="morning-followup">
      <h3>Ask a follow-up</h3>
      <ul>
        {turns.map((turn, i) => (
          <li key={i}>
            <p>
              <strong>You:</strong> {turn.question}
            </p>
            {turn.banner && (
              <p style={{ color: turn.severity === 'WARN' ? 'orange' : 'inherit' }}>
                [{turn.severity}] {turn.banner}
              </p>
            )}
            {turn.explanation && (
              <p data-testid="morning-followup-answer">
                <strong>Coach:</strong> {turn.explanation}
              </p>
            )}
          </li>
        ))}
      </ul>
      {error && (
        <p style={{ color: 'red' }} data-testid="morning-followup-error">
          Error: {error}
        </p>
      )}
      <form onSubmit={handleAsk}>
        <input
          type="text"
          value={question}
          onChange={(e) => setQuestion(e.target.value)}
          placeholder="why? what if I do it anyway?"
          disabled={pending}
        />
        <button type="submit" disabled={pending}>
          {pending ? 'Asking…' : 'Ask'}
        </button>
      </form>
    </div>
  )
}

function DecisionResult({ decision }: { decision: DecisionResponse }) {
  return (
    <div data-testid="morning-decision">
      <p>
        Recommendation: <strong>{decision.recommendation}</strong>
      </p>
      {decision.rationale && <p>Rationale: {decision.rationale}</p>}
      {decision.check_recovery_week_trigger && <p>⚠️ Recovery week trigger flagged.</p>}
      {decision.override_triggered && (
        <div data-testid="morning-override">
          <p>Override triggered:</p>
          <ul>
            {decision.override_reasons.map((reason) => (
              <li key={reason}>{reason}</li>
            ))}
          </ul>
        </div>
      )}
      {decision.banner && (
        <p style={{ color: decision.severity === 'WARN' ? 'orange' : 'inherit' }}>
          [{decision.severity}] {decision.banner}
        </p>
      )}
      {decision.explanation && <p data-testid="morning-explanation">{decision.explanation}</p>}
      {/* Only offered when there's an explanation to follow up on — matches
          the CLI's morning command (docs/adr/0023 parity). */}
      {decision.explanation && (
        <FollowupChat
          decisionContext={decision.decision_context}
          initialExplanation={decision.explanation}
        />
      )}
    </div>
  )
}

function MorningView() {
  const today = new Date().toISOString().slice(0, 10)
  const [state, setState] = useState<LoadState>({ kind: 'loading' })

  useEffect(() => {
    setState({ kind: 'loading' })
    fetchContext(today).then(setState)
    // today is stable for the component's lifetime (computed once above);
    // this effect is meant to run once on mount, matching the other screens.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [])

  function pickSessionType(sessionType: string) {
    setState({ kind: 'loading' })
    fetchContext(today, sessionType).then(setState)
  }

  function handleSubmit(context: MorningContext, e: React.FormEvent<HTMLFormElement>) {
    e.preventDefault()
    const formData = new FormData(e.currentTarget)
    const fixedAnswers: Record<string, number> = {}
    for (const q of context.questions.fixed) {
      fixedAnswers[q.key] = Number(formData.get(q.key))
    }
    const adaptiveAnswers: Record<string, number> = {}
    for (const q of context.questions.adaptive) {
      adaptiveAnswers[q.key] = Number(formData.get(q.key))
    }
    setState({ kind: 'submitting', context })
    submitDecision(context, fixedAnswers, adaptiveAnswers).then(setState)
  }

  return (
    <section>
      <h2>Today — {today}</h2>

      {state.kind === 'loading' && <p>Loading…</p>}

      {state.kind === 'error' && (
        <p style={{ color: 'red' }} data-testid="morning-error">
          Error: {state.message}
        </p>
      )}

      {state.kind === 'need-session-type' && (
        <div data-testid="morning-session-picker">
          <BiometricsSummary biometrics={state.detail.biometrics} />
          <p>{state.detail.message}</p>
          <label>
            Session type
            <select
              defaultValue=""
              onChange={(e) => {
                if (e.target.value) pickSessionType(e.target.value)
              }}
            >
              <option value="" disabled>
                Choose a session type…
              </option>
              {state.detail.available_session_types.map((sessionType) => (
                <option key={sessionType} value={sessionType}>
                  {sessionType}
                </option>
              ))}
            </select>
          </label>
        </div>
      )}

      {(state.kind === 'ready' || state.kind === 'submitting') && (
        <div data-testid="morning-form">
          <p>
            Scheduled session: <strong>{state.context.session_type}</strong>
          </p>
          <BiometricsSummary biometrics={state.context.biometrics} />
          <form onSubmit={(e) => handleSubmit(state.context, e)}>
            {state.context.questions.fixed.map((q) => (
              <QuestionInput key={q.key} question={q} />
            ))}
            {state.context.questions.adaptive.map((q) => (
              <QuestionInput key={q.key} question={q} />
            ))}
            <button type="submit" disabled={state.kind === 'submitting'}>
              {state.kind === 'submitting' ? 'Thinking…' : 'Get recommendation'}
            </button>
          </form>
        </div>
      )}

      {state.kind === 'decided' && <DecisionResult decision={state.decision} />}
    </section>
  )
}

export default MorningView

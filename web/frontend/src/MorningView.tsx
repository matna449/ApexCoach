import { useEffect, useState } from 'react'
import type { Biometrics, DecisionResponse, MorningContext, NoPlanDetail } from './morningTypes'
import ChatBubble from './ChatBubble'
import TypingIndicator from './TypingIndicator'
import SelectCard from './SelectCard'
import BiometricsHeader from './BiometricsHeader'
import ConversationalHealthCheck from './ConversationalHealthCheck'
import VerdictStamp from './VerdictStamp'
import Badge from './Badge'

// F17.1/F17.2/F17.3 (#83/#84/#85): the web UI's primary screen. Fetches
// GET /api/morning/context on load (real WHOOP fetch + session resolution
// + question catalog), POSTs the answered health check to
// /api/morning/decision (health check -> classify -> decide -> Ollama
// explain), then offers a POST /api/morning/followup chat loop once an
// explanation is available.
//
// F19.2 (#105): rebuilds the presentation as a conversational,
// one-question-at-a-time chat thread on top of the F19.1 (#104) token
// system. The data layer below (types, fetchContext/submitDecision/
// submitFollowup, and the exact request/response shapes) is UNCHANGED from
// #85 -- only how it's rendered changes.
const API_BASE_URL = 'http://localhost:8000'

type DecisionRequestAnswers = { fixedAnswers: Record<string, number>; adaptiveAnswers: Record<string, number> }

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

type FollowupResult = { explanation: string | null; banner: string | null; severity: 'WARN' | 'INFO' | null }

type FollowupTurn = { question: string } & FollowupResult

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

// F19.2 (#105): kept present and functional exactly as #85 built it -- its
// visual restyle into the unified chat thread is a separate ticket (#106)
// blocked on this one, per the issue's explicit instruction not to touch
// its appearance here.
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

function biometricsFor(state: LoadState): Biometrics | null {
  if (state.kind === 'need-session-type') return state.detail.biometrics
  if (state.kind === 'ready' || state.kind === 'submitting' || state.kind === 'decided') return state.context.biometrics
  return null
}

function DecisionResult({ decision }: { decision: DecisionResponse }) {
  return (
    <div className="flex flex-col gap-4" data-testid="morning-decision">
      <VerdictStamp recommendation={decision.recommendation} />
      {decision.rationale && <ChatBubble speaker="coach">{decision.rationale}</ChatBubble>}
      {decision.check_recovery_week_trigger && (
        <Badge tone="warn" testId="recovery-week-flag">
          Recovery week trigger flagged
        </Badge>
      )}
      {decision.override_triggered && (
        <div className="flex flex-col gap-1" data-testid="morning-override">
          <span className="text-sm text-text-muted">Override triggered:</span>
          <ul className="flex flex-wrap gap-1">
            {decision.override_reasons.map((reason) => (
              <li key={reason}>
                <Badge tone="override">{reason}</Badge>
              </li>
            ))}
          </ul>
        </div>
      )}
      {decision.banner && (
        <div className="flex items-start gap-2" data-testid="morning-banner">
          <Badge tone={decision.severity === 'WARN' ? 'warn' : 'info'}>{decision.severity}</Badge>
          <span className="text-sm text-text-primary">{decision.banner}</span>
        </div>
      )}
      {decision.explanation && (
        <ChatBubble speaker="coach" testId="morning-explanation">
          {decision.explanation}
        </ChatBubble>
      )}
      {/* Only offered when there's an explanation to follow up on — matches
          the CLI's morning command (docs/adr/0023 parity). */}
      {decision.explanation && (
        <FollowupChat decisionContext={decision.decision_context} initialExplanation={decision.explanation} />
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

  function handleAnswersSubmit(context: MorningContext, { fixedAnswers, adaptiveAnswers }: DecisionRequestAnswers) {
    setState({ kind: 'submitting', context })
    submitDecision(context, fixedAnswers, adaptiveAnswers).then(setState)
  }

  const biometrics = biometricsFor(state)

  return (
    <section className="mx-auto flex max-w-2xl flex-col gap-4" data-testid="morning-view">
      <h2 className="text-lg font-semibold">Today — {today}</h2>

      {biometrics && <BiometricsHeader biometrics={biometrics} />}

      <div className="flex flex-col gap-3">
        {state.kind === 'loading' && <TypingIndicator label="Fetching this morning's data…" />}

        {state.kind === 'error' && (
          <ChatBubble speaker="coach" testId="morning-error">
            Error: {state.message}
          </ChatBubble>
        )}

        {state.kind === 'need-session-type' && (
          <div className="flex flex-col gap-2" data-testid="morning-session-picker">
            <ChatBubble speaker="coach">{state.detail.message}</ChatBubble>
            <div className="flex flex-wrap gap-2 pl-1">
              {state.detail.available_session_types.map((sessionType) => (
                <SelectCard
                  key={sessionType}
                  label={sessionType}
                  onSelect={() => pickSessionType(sessionType)}
                  testId={`session-type-${sessionType}`}
                />
              ))}
            </div>
          </div>
        )}

        {(state.kind === 'ready' || state.kind === 'submitting') && (
          <ConversationalHealthCheck
            key={state.context.session_type}
            questions={state.context.questions}
            submitting={state.kind === 'submitting'}
            onSubmit={(fixedAnswers, adaptiveAnswers) =>
              handleAnswersSubmit(state.context, { fixedAnswers, adaptiveAnswers })
            }
          />
        )}

        {state.kind === 'submitting' && <TypingIndicator label="Working out today's recommendation…" />}

        {state.kind === 'decided' && <DecisionResult decision={state.decision} />}
      </div>
    </section>
  )
}

export default MorningView

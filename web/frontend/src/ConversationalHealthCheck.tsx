import { useState, type ReactNode } from 'react'
import ChatBubble from './ChatBubble'
import SelectCard from './SelectCard'
import type { Question, QuestionCatalog } from './morningTypes'

// F19.2 (#105): owns the one-question-at-a-time health-check sequence --
// fixed questions then adaptive (same order the backend returns via
// context.questions.fixed/adaptive; this component never invents or
// reorders question text/keys, the backend stays the source of truth), the
// collected-answers state, edit-in-place reopening of any already-answered
// question, and the final review/confirm step. `questions` only ever
// contains what GET /api/morning/context already returned -- no
// duplication of the catalog itself.
const RATING_VALUES = [1, 2, 3, 4, 5]

function ratingSublabel(n: number): string | undefined {
  if (n === 1) return 'Low'
  if (n === 5) return 'High'
  return undefined
}

function RatingRow({
  question,
  selectedValue,
  onSelect,
}: {
  question: Question
  selectedValue: number | undefined
  onSelect: (value: number) => void
}) {
  return (
    <div className="flex flex-col gap-2">
      <ChatBubble speaker="coach" testId={`question-${question.key}`}>
        {question.text}
      </ChatBubble>
      <div className="flex gap-2 pl-1">
        {RATING_VALUES.map((n) => (
          <SelectCard
            key={n}
            label={String(n)}
            sublabel={ratingSublabel(n)}
            selected={selectedValue === n}
            onSelect={() => onSelect(n)}
            testId={`answer-${question.key}-${n}`}
          />
        ))}
      </div>
    </div>
  )
}

function ConversationalHealthCheck({
  questions,
  onSubmit,
  submitting,
}: {
  questions: QuestionCatalog
  onSubmit: (fixedAnswers: Record<string, number>, adaptiveAnswers: Record<string, number>) => void
  submitting: boolean
}) {
  const allQuestions: Question[] = [...questions.fixed, ...questions.adaptive]

  const [answers, setAnswers] = useState<Record<string, number>>({})
  const [activeKey, setActiveKey] = useState<string | null>(null)

  function selectAnswer(key: string, value: number) {
    setAnswers((prev) => ({ ...prev, [key]: value }))
    setActiveKey(null)
  }

  function handleConfirm() {
    const fixedAnswers: Record<string, number> = {}
    const adaptiveAnswers: Record<string, number> = {}
    for (const q of questions.fixed) fixedAnswers[q.key] = answers[q.key]
    for (const q of questions.adaptive) adaptiveAnswers[q.key] = answers[q.key]
    onSubmit(fixedAnswers, adaptiveAnswers)
  }

  const items: ReactNode[] = []
  let frontierRendered = false

  for (const q of allQuestions) {
    const answered = q.key in answers
    const isActive = activeKey === q.key

    if (answered) {
      // Reopened for editing (either mid-sequence or from the review step)
      // -- always rendered as the open input, regardless of position, so
      // reopening one answer never hides or clears any other collected
      // answer.
      items.push(
        isActive ? (
          <RatingRow key={q.key} question={q} selectedValue={answers[q.key]} onSelect={(v) => selectAnswer(q.key, v)} />
        ) : (
          <button
            key={q.key}
            type="button"
            onClick={() => setActiveKey(q.key)}
            data-testid={`collapsed-${q.key}`}
            className="flex w-full flex-col items-start gap-1 rounded-lg border border-border bg-surface-card px-4 py-2 text-left text-sm transition-colors hover:border-border-strong"
          >
            <span className="text-text-primary">{q.text}</span>
            <span className="font-mono text-xs text-text-muted">
              Your answer: <span className="text-text-heading">{answers[q.key]}</span> (tap to change)
            </span>
          </button>
        ),
      )
      continue
    }

    // Unanswered. Only the first unanswered question in sequence opens (the
    // "frontier") -- and only when nothing else is currently being edited,
    // so reopening an earlier answer pauses forward progress instead of
    // showing two open questions at once.
    if (activeKey === null && !frontierRendered) {
      items.push(<RatingRow key={q.key} question={q} selectedValue={undefined} onSelect={(v) => selectAnswer(q.key, v)} />)
      frontierRendered = true
    }
  }

  const allAnswered = allQuestions.length > 0 && allQuestions.every((q) => q.key in answers)
  const showReview = allAnswered && activeKey === null

  return (
    <div className="flex flex-col gap-3" data-testid="health-check">
      {items}
      {showReview && (
        <div className="flex flex-col gap-3" data-testid="health-check-review">
          <ChatBubble speaker="coach">
            <div className="flex flex-col gap-2">
              <p>Here&apos;s everything you told me — tap any answer above to change it.</p>
              <ul className="flex flex-col gap-1">
                {allQuestions.map((q) => (
                  <li key={q.key} className="flex justify-between gap-4 font-mono text-xs">
                    <span className="text-text-muted">{q.text}</span>
                    <span className="text-text-heading">{answers[q.key]}</span>
                  </li>
                ))}
              </ul>
            </div>
          </ChatBubble>
          <button
            type="button"
            onClick={handleConfirm}
            disabled={submitting}
            data-testid="confirm-decision"
            className="self-start rounded-md border border-border-strong bg-surface-card px-4 py-2 text-sm font-medium text-text-heading transition-colors hover:bg-surface-panel disabled:opacity-50"
          >
            {submitting ? 'Thinking…' : 'Get recommendation'}
          </button>
        </div>
      )}
    </div>
  )
}

export default ConversationalHealthCheck

import { afterEach, describe, expect, it, vi } from 'vitest'
import { cleanup, render, screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import ConversationalHealthCheck from './ConversationalHealthCheck'
import type { QuestionCatalog } from './morningTypes'

// F19.2 (#105): the question-sequence/answer-state/edit-in-place state
// machine is the trickiest part of the conversational flow, so it gets a
// direct unit test independent of any fetch mocking (that's covered at the
// MorningView integration level instead).
afterEach(() => {
  cleanup()
})

const QUESTIONS: QuestionCatalog = {
  fixed: [
    { key: 'muscle_soreness', text: 'How is your overall muscle soreness right now?' },
    { key: 'subjective_energy', text: 'How is your subjective energy level today?' },
  ],
  adaptive: [{ key: 'left_knee_pain', text: 'Left knee pain (1-5)?' }],
}

describe('ConversationalHealthCheck', () => {
  it('asks one question at a time, in fixed-then-adaptive order', async () => {
    const user = userEvent.setup()
    render(<ConversationalHealthCheck questions={QUESTIONS} onSubmit={vi.fn()} submitting={false} />)

    // Only the first fixed question is open; nothing later has appeared yet.
    expect(screen.getByTestId('question-muscle_soreness')).toBeInTheDocument()
    expect(screen.queryByTestId('question-subjective_energy')).not.toBeInTheDocument()
    expect(screen.queryByTestId('question-left_knee_pain')).not.toBeInTheDocument()

    await user.click(screen.getByTestId('answer-muscle_soreness-2'))

    // First question collapses; second (still fixed) opens next.
    expect(screen.getByTestId('collapsed-muscle_soreness')).toBeInTheDocument()
    expect(screen.getByTestId('question-subjective_energy')).toBeInTheDocument()
    expect(screen.queryByTestId('question-left_knee_pain')).not.toBeInTheDocument()

    await user.click(screen.getByTestId('answer-subjective_energy-4'))

    // Adaptive question opens only after all fixed ones are answered.
    expect(screen.getByTestId('question-left_knee_pain')).toBeInTheDocument()
    expect(screen.queryByTestId('health-check-review')).not.toBeInTheDocument()
  })

  it('shows a review step listing every answer, with one confirm action', async () => {
    const user = userEvent.setup()
    const onSubmit = vi.fn()
    render(<ConversationalHealthCheck questions={QUESTIONS} onSubmit={onSubmit} submitting={false} />)

    await user.click(screen.getByTestId('answer-muscle_soreness-2'))
    await user.click(screen.getByTestId('answer-subjective_energy-4'))
    await user.click(screen.getByTestId('answer-left_knee_pain-1'))

    const review = screen.getByTestId('health-check-review')
    expect(review).toHaveTextContent('How is your overall muscle soreness right now?')
    expect(review).toHaveTextContent('How is your subjective energy level today?')
    expect(review).toHaveTextContent('Left knee pain (1-5)?')

    expect(onSubmit).not.toHaveBeenCalled()
    await user.click(screen.getByTestId('confirm-decision'))

    expect(onSubmit).toHaveBeenCalledWith(
      { muscle_soreness: 2, subjective_energy: 4 },
      { left_knee_pain: 1 },
    )
  })

  it('lets a prior answer be reopened and changed without corrupting other answers', async () => {
    const user = userEvent.setup()
    const onSubmit = vi.fn()
    render(<ConversationalHealthCheck questions={QUESTIONS} onSubmit={onSubmit} submitting={false} />)

    await user.click(screen.getByTestId('answer-muscle_soreness-2'))
    await user.click(screen.getByTestId('answer-subjective_energy-4'))
    await user.click(screen.getByTestId('answer-left_knee_pain-1'))

    // All three answered -- review is showing. Tap back into the first
    // answer to change it.
    expect(screen.getByTestId('health-check-review')).toBeInTheDocument()
    await user.click(screen.getByTestId('collapsed-muscle_soreness'))

    // Reopening pauses the review and shows only that question's editor;
    // the other two answers are untouched (not cleared, not re-asked).
    expect(screen.queryByTestId('health-check-review')).not.toBeInTheDocument()
    expect(screen.getByTestId('question-muscle_soreness')).toBeInTheDocument()
    expect(screen.getByTestId('collapsed-subjective_energy')).toHaveTextContent('Your answer: 4')
    expect(screen.getByTestId('collapsed-left_knee_pain')).toHaveTextContent('Your answer: 1')

    await user.click(screen.getByTestId('answer-muscle_soreness-5'))

    // Back to review, with the edited value reflected and everything else intact.
    const review = await screen.findByTestId('health-check-review')
    expect(review).toBeInTheDocument()
    await user.click(screen.getByTestId('confirm-decision'))

    expect(onSubmit).toHaveBeenCalledWith(
      { muscle_soreness: 5, subjective_energy: 4 },
      { left_knee_pain: 1 },
    )
  })

  it('disables the confirm button and shows a pending label while submitting', async () => {
    const user = userEvent.setup()
    render(<ConversationalHealthCheck questions={QUESTIONS} onSubmit={vi.fn()} submitting={true} />)

    await user.click(screen.getByTestId('answer-muscle_soreness-2'))
    await user.click(screen.getByTestId('answer-subjective_energy-4'))
    await user.click(screen.getByTestId('answer-left_knee_pain-1'))

    const confirm = screen.getByTestId('confirm-decision')
    expect(confirm).toBeDisabled()
    expect(confirm).toHaveTextContent('Thinking…')
  })
})

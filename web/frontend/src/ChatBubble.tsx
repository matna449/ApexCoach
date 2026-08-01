import type { ReactNode } from 'react'

// F19.2 (#105): shared Coach/athlete message shell for the conversational
// morning flow. Also the primitive #106 (followup-chat restyle) will reuse
// to put FollowupChat in the same visual thread.
export type ChatSpeaker = 'coach' | 'athlete'

function ChatBubble({
  speaker,
  children,
  testId,
}: {
  speaker: ChatSpeaker
  children: ReactNode
  testId?: string
}) {
  const isCoach = speaker === 'coach'
  return (
    <div className={`flex ${isCoach ? 'justify-start' : 'justify-end'}`} data-testid={testId}>
      <div
        className={`max-w-[85%] rounded-lg border px-4 py-3 text-sm leading-relaxed ${
          isCoach
            ? 'border-border bg-surface-card text-text-primary'
            : 'border-border-strong bg-surface-panel text-text-primary'
        }`}
      >
        {children}
      </div>
    </div>
  )
}

export default ChatBubble

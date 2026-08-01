// F19.2 (#105): animated "Coach is thinking" bubble. Shown during the
// initial GET /api/morning/context fetch and again while POST
// /api/morning/decision (health check -> classify -> decide -> Ollama
// explain) is in flight -- both can take a few seconds, and this is what
// makes that wait read as "working" rather than "broken" (PRD #102 story 10).
function TypingIndicator({ label = 'Coach is thinking…' }: { label?: string }) {
  return (
    <div className="flex justify-start" data-testid="typing-indicator">
      <div className="flex items-center gap-2 rounded-lg border border-border bg-surface-card px-4 py-3">
        <span className="sr-only">{label}</span>
        <span className="flex gap-1" aria-hidden="true">
          <span className="h-1.5 w-1.5 animate-bounce rounded-full bg-text-muted [animation-delay:-0.3s]" />
          <span className="h-1.5 w-1.5 animate-bounce rounded-full bg-text-muted [animation-delay:-0.15s]" />
          <span className="h-1.5 w-1.5 animate-bounce rounded-full bg-text-muted" />
        </span>
      </div>
    </div>
  )
}

export default TypingIndicator

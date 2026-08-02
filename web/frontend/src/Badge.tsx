import type { ReactNode } from 'react'

// F19.2 (#105): WARN/INFO/override pill. Uses the muted status scale
// (index.css/#104) rather than the reserved accent token -- 'warn' maps to
// the amber status step (Ollama-degraded WARN banner), 'override' to the
// red step (joint-pain-style override reasons), 'info' stays neutral.
// 'good' (F19.7, #123) maps to the green status step -- "pushed to
// intervals.icu", the calendar's confirmed-synced state.
export type BadgeTone = 'warn' | 'info' | 'override' | 'good'

const TONE_CLASSES: Record<BadgeTone, string> = {
  warn: 'border-status-warn/40 bg-status-warn/10 text-status-warn',
  info: 'border-border-strong bg-surface-panel text-text-muted',
  override: 'border-status-bad/40 bg-status-bad/10 text-status-bad',
  good: 'border-status-good/40 bg-status-good/10 text-status-good',
}

function Badge({ tone, children, testId }: { tone: BadgeTone; children: ReactNode; testId?: string }) {
  return (
    <span
      data-testid={testId}
      className={`inline-flex items-center gap-1 rounded-sm border px-2 py-0.5 font-mono text-xs font-medium tracking-wide uppercase ${TONE_CLASSES[tone]}`}
    >
      {children}
    </span>
  )
}

export default Badge

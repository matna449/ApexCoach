// F19.2 (#105): tappable answer card. Used both for 1-5 health-check
// ratings and for session-type selection -- both are "pick one option from
// a small set," so a single generic card driven by props covers both use
// cases without a use-case-specific variant prop.
//
// Note: intentionally does NOT use the reserved --color-accent token
// (index.css/#104) for its selected state -- that token is reserved
// exclusively for VerdictStamp so it never gets diluted (PRD #102).
// Selection here is communicated with border weight/surface instead.
function SelectCard({
  label,
  sublabel,
  selected = false,
  onSelect,
  testId,
}: {
  label: string
  sublabel?: string
  selected?: boolean
  onSelect: () => void
  testId?: string
}) {
  return (
    <button
      type="button"
      onClick={onSelect}
      aria-pressed={selected}
      data-testid={testId}
      className={`flex min-w-16 flex-1 flex-col items-center gap-1 rounded-md border px-3 py-2 text-center transition-colors ${
        selected
          ? 'border-2 border-border-strong bg-surface-card text-text-heading'
          : 'border border-border bg-surface-panel text-text-primary hover:border-border-strong hover:bg-surface-card'
      }`}
    >
      <span className="font-mono text-base font-semibold">{label}</span>
      {sublabel && <span className="text-xs text-text-muted">{sublabel}</span>}
    </button>
  )
}

export default SelectCard

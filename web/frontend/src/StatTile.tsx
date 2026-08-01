// F19.2 (#105): a single biometric value + label, tabular-mono per PRD
// #102's type direction (every numeric value uses the mono scale).
function StatTile({ label, value, testId }: { label: string; value: string; testId?: string }) {
  return (
    <div className="flex flex-col gap-0.5" data-testid={testId}>
      <span className="text-xs tracking-wide text-text-muted uppercase">{label}</span>
      <span className="font-mono text-lg font-semibold text-text-heading tabular-nums">{value}</span>
    </div>
  )
}

export default StatTile

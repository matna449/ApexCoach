import type { Biometrics } from './morningTypes'
import StatTile from './StatTile'

// F19.2 (#105): persistent stat-tile row. Rendered once biometrics are
// available (either from the need-session-type 409 detail or a resolved
// context) and stays mounted above the conversation thread for the rest of
// the flow -- PRD #102 story 4: biometrics must stay visible the whole time
// the athlete is answering questions, never scrolled out of view with the
// thread below it.
function fmt(value: number | null): string {
  return value === null ? '—' : String(value)
}

function BiometricsHeader({ biometrics }: { biometrics: Biometrics }) {
  return (
    <div
      data-testid="biometrics-header"
      className="sticky top-0 z-10 grid grid-cols-2 gap-x-4 gap-y-3 rounded-lg border border-border bg-surface-panel px-4 py-3 sm:grid-cols-5"
    >
      <StatTile testId="stat-recovery" label="Recovery" value={`${fmt(biometrics.whoop_recovery_pct)}%`} />
      <StatTile testId="stat-hrv" label="HRV" value={`${fmt(biometrics.whoop_hrv_ms)} ms`} />
      <StatTile testId="stat-rhr" label="Resting HR" value={`${fmt(biometrics.whoop_rhr_bpm)} bpm`} />
      <StatTile testId="stat-strain" label="Strain" value={fmt(biometrics.whoop_strain)} />
      <StatTile testId="stat-sleep" label="Sleep" value={`${fmt(biometrics.whoop_sleep_hours)} hrs`} />
    </div>
  )
}

export default BiometricsHeader

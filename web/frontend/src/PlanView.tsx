// F19.5 (#108): fleshes out the bare stub F19.1 (#104) wired into the
// sidebar nav. This is intentionally a placeholder, not a real feature --
// the athlete already decided (in a conversation not captured here) how
// ApexCoach will generate a plan and push it to intervals.icu, which syncs
// to Coros; that flow is future work (ADR-0025 has partial adapter
// research). This ticket only reserves the nav/information-architecture
// slot with an honest empty state: a calendar-grid *shape*, no invented
// data model (no "planned sessions," "sync status," "last synced," etc.),
// no network call, no backend endpoint.
const WEEKDAYS = ['Mon', 'Tue', 'Wed', 'Thu', 'Fri', 'Sat', 'Sun']

// Five weeks x seven days -- purely structural cell count for an empty
// calendar-grid shape. No dates, no data plotted into any cell.
const EMPTY_CELL_COUNT = 35

function PlanView() {
  return (
    <div className="p-6">
      <h2 className="text-lg font-semibold">Plan</h2>
      <p className="mt-1 text-sm text-text-muted">Training plan sync isn't connected yet.</p>

      <div className="relative mt-6 max-w-2xl">
        <div
          aria-hidden="true"
          className="grid grid-cols-7 gap-px overflow-hidden rounded-lg border border-border bg-border"
        >
          {WEEKDAYS.map((day) => (
            <div
              key={day}
              className="bg-surface-panel px-2 py-2 text-center font-mono text-xs font-medium tracking-widest text-text-muted uppercase"
            >
              {day}
            </div>
          ))}
          {Array.from({ length: EMPTY_CELL_COUNT }, (_, i) => (
            <div key={i} className="aspect-square bg-surface-card" />
          ))}
        </div>

        <div className="pointer-events-none absolute inset-0 flex items-center justify-center p-6">
          <p className="rounded-md border border-border bg-surface-panel px-4 py-3 text-center text-sm font-medium text-text-muted shadow-sm">
            Nothing synced here yet.
          </p>
        </div>
      </div>
    </div>
  )
}

export default PlanView

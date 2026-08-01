import { useTheme } from './useTheme'

// F19.1 (#104): persistent left-sidebar navigation, replacing App.tsx's old
// centered <h1> + top button-row nav. Owns the theme toggle itself (PRD
// #102's component architecture lists "Sidebar (nav + theme toggle)" as one
// self-contained feature block); the parent owns which View is active,
// matching how App.tsx already owned view state pre-redesign.
export type View = 'morning' | 'history' | 'plan'

const NAV_ITEMS: { key: View; label: string }[] = [
  { key: 'morning', label: 'Morning' },
  { key: 'history', label: 'History' },
  { key: 'plan', label: 'Plan' },
]

function Sidebar({
  view,
  onNavigate,
}: {
  view: View
  onNavigate: (view: View) => void
}) {
  const { theme, toggleTheme } = useTheme()

  return (
    <nav
      aria-label="Primary"
      className="flex h-full w-56 shrink-0 flex-col justify-between border-r border-border bg-surface-panel px-3 py-4"
    >
      <div>
        <p className="mb-4 px-2 font-mono text-xs font-medium tracking-widest text-text-muted uppercase">
          ApexCoach
        </p>
        <ul className="flex flex-col gap-1">
          {NAV_ITEMS.map((item) => (
            <li key={item.key}>
              <button
                type="button"
                onClick={() => onNavigate(item.key)}
                aria-current={view === item.key ? 'page' : undefined}
                className={`w-full rounded-md px-3 py-2 text-left text-sm font-medium transition-colors ${
                  view === item.key
                    ? 'bg-surface-card text-text-heading'
                    : 'text-text-muted hover:bg-surface-card hover:text-text-primary'
                }`}
              >
                {item.label}
              </button>
            </li>
          ))}
        </ul>
      </div>

      <button
        type="button"
        onClick={toggleTheme}
        aria-label={`Switch to ${theme === 'dark' ? 'light' : 'dark'} mode`}
        className="rounded-md border border-border px-3 py-2 text-left text-sm font-medium text-text-muted transition-colors hover:bg-surface-card hover:text-text-primary"
      >
        {theme === 'dark' ? 'Light mode' : 'Dark mode'}
      </button>
    </nav>
  )
}

export default Sidebar

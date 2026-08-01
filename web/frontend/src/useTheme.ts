import { useCallback, useEffect, useState } from 'react'

// F19.1 (#104): manual light/dark toggle, persisted client-side. Once the
// athlete has explicitly toggled, their choice wins over OS
// prefers-color-scheme on every subsequent load -- OS preference only
// decides the very first visit (no stored value yet). index.html carries a
// pre-paint inline script that applies the same THEME_STORAGE_KEY/logic
// synchronously so there's no flash of the wrong theme before React mounts.
export type Theme = 'dark' | 'light'

export const THEME_STORAGE_KEY = 'apexcoach-theme'

function isTheme(value: string | null): value is Theme {
  return value === 'dark' || value === 'light'
}

function readStoredTheme(): Theme | null {
  try {
    const stored = window.localStorage.getItem(THEME_STORAGE_KEY)
    return isTheme(stored) ? stored : null
  } catch {
    // localStorage can throw in locked-down environments (private
    // browsing, disabled storage) -- fall back to OS preference.
    return null
  }
}

function systemPrefersDark(): boolean {
  return window.matchMedia?.('(prefers-color-scheme: dark)').matches ?? true
}

export function getInitialTheme(): Theme {
  return readStoredTheme() ?? (systemPrefersDark() ? 'dark' : 'light')
}

function applyThemeToDocument(theme: Theme) {
  document.documentElement.classList.toggle('dark', theme === 'dark')
}

export function useTheme(): { theme: Theme; toggleTheme: () => void } {
  const [theme, setTheme] = useState<Theme>(getInitialTheme)

  useEffect(() => {
    applyThemeToDocument(theme)
  }, [theme])

  const toggleTheme = useCallback(() => {
    setTheme((prev) => {
      const next: Theme = prev === 'dark' ? 'light' : 'dark'
      try {
        window.localStorage.setItem(THEME_STORAGE_KEY, next)
      } catch {
        // Best-effort persistence; the toggle still works for this
        // session even if storage is unavailable.
      }
      return next
    })
  }, [])

  return { theme, toggleTheme }
}

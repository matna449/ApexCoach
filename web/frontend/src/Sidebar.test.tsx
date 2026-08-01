import { afterEach, describe, expect, it, vi } from 'vitest'
import { cleanup, render, screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import Sidebar from './Sidebar'
import { THEME_STORAGE_KEY } from './useTheme'

// F19.1 (#104): smoke test proving the vitest + React Testing Library
// pattern for later tickets (F19.2/F19.3, #105/#106), and covering the
// nav shell + theme-toggle persistence this ticket introduces.
afterEach(() => {
  cleanup()
  window.localStorage.clear()
  document.documentElement.classList.remove('dark')
})

describe('Sidebar', () => {
  it('renders Morning, History, and Plan, with the active view marked current', () => {
    render(<Sidebar view="morning" onNavigate={() => {}} />)

    expect(screen.getByRole('button', { name: 'Morning' })).toHaveAttribute('aria-current', 'page')
    expect(screen.getByRole('button', { name: 'History' })).not.toHaveAttribute('aria-current')
    expect(screen.getByRole('button', { name: 'Plan' })).not.toHaveAttribute('aria-current')
  })

  it('calls onNavigate with the clicked view', async () => {
    const user = userEvent.setup()
    const onNavigate = vi.fn()
    render(<Sidebar view="morning" onNavigate={onNavigate} />)

    await user.click(screen.getByRole('button', { name: 'Plan' }))

    expect(onNavigate).toHaveBeenCalledWith('plan')
  })

  it('toggles the dark class on <html> and persists the choice to localStorage', async () => {
    const user = userEvent.setup()
    render(<Sidebar view="morning" onNavigate={() => {}} />)

    const wasDark = document.documentElement.classList.contains('dark')
    const toggle = screen.getByRole('button', { name: /switch to (dark|light) mode/i })

    await user.click(toggle)

    expect(document.documentElement.classList.contains('dark')).toBe(!wasDark)
    expect(window.localStorage.getItem(THEME_STORAGE_KEY)).toBe(!wasDark ? 'dark' : 'light')

    // A second toggle flips back and persists again -- proves the choice
    // (not just OS preference) drives every subsequent render.
    await user.click(toggle)

    expect(document.documentElement.classList.contains('dark')).toBe(wasDark)
    expect(window.localStorage.getItem(THEME_STORAGE_KEY)).toBe(wasDark ? 'dark' : 'light')
  })
})

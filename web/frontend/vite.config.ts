import { defineConfig } from 'vitest/config'
import react from '@vitejs/plugin-react'
import tailwindcss from '@tailwindcss/vite'

// https://vite.dev/config/
// F19.1 (#104): adds the Tailwind CSS Vite plugin (ADR-0026) and a vitest
// `test` block -- this repo had no frontend test runner before this
// ticket. `vitest/config`'s defineConfig is a drop-in replacement for
// Vite's own that additionally types the `test` key, so dev/build/preview
// behavior is unchanged.
export default defineConfig({
  plugins: [react(), tailwindcss()],
  test: {
    environment: 'jsdom',
    setupFiles: ['./src/setupTests.ts'],
  },
})

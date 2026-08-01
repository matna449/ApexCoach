// F19.1 (#104): vitest test setup -- extends `expect` with jest-dom
// matchers (toBeInTheDocument, etc.) for every test file, per
// setupFiles in vite.config.ts.
import '@testing-library/jest-dom/vitest'

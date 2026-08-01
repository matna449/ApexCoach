---
status: accepted
---

# Tailwind CSS adopted for the frontend design-token system, superseding ADR-0023's minimal-dependency default on styling

ADR-0023 pulled the web UI forward into v1.5 as a deliberately minimal addition — FastAPI as a pure façade, React talking to it, and (per PRD #81) at most one new dependency category (client-side routing) beyond what F16.1-4 needed. The frontend has shipped since then with zero CSS dependencies: a single hand-written `index.css` using CSS custom properties for a generic light/dark starter palette. PRD (`docs/ApexCoach_PRD_v1.0.md` §8, v1.5) is now being extended with a real, dark-mode-first design-token system, a componentized conversational morning flow, and a floated Plan page — a full visual overhaul, not an incremental addition to the existing screens.

**Decision: adopt Tailwind CSS for the frontend's styling layer, on top of a token-driven theme config, rather than continuing with hand-written CSS custom properties.** This is a deliberate exception to ADR-0023's minimal-dependency default, not a reversal of it — ADR-0023's actual concerns (no PostgreSQL, no Azure, no multi-user, CLI stays primary, FastAPI stays a thin façade) are all backend/infrastructure concerns and are untouched here. Tailwind is a build-time, dev-dependency-only tool (no runtime cost, no server-side footprint) and the tradeoff is judged worth it specifically because this round of work is a full design-system build — consistent token application (color/type/space/radius scales) across a growing component library is materially faster and less error-prone with Tailwind's utility classes and theme config than hand-maintaining custom-property usage across every component file by hand.

The token system itself (palette, type scale, spacing, radii, the semantic split between Recovery/HRV status colors and the single recommendation-verdict accent) is specified in the accompanying design PRD, not here — this ADR only settles the *mechanism*, not the tokens' values.

## Consequences

- `tailwindcss` + its Vite plugin become new frontend devDependencies — the first CSS-tooling dependency this codebase has taken on.
- `web/frontend/src/index.css` is replaced by a Tailwind entrypoint + a theme config (or CSS `@theme` block) expressing the design PRD's token values, rather than hand-written custom properties.
- Component styling moves to Tailwind utility classes in JSX/TSX, not separate CSS Modules files per component.
- Dark mode is Tailwind's `dark:` variant, driven by a manually-toggleable theme (persisted client-side, defaulting to OS preference) rather than `prefers-color-scheme` alone, since the design PRD requires an explicit light/dark opt-out affordance.
- This does not reopen ADR-0023's backend/infrastructure boundaries — PostgreSQL, Azure, and multi-user support remain out of scope for this round of work.

# Apex Coach

**Holistic AI Training Coach** — a local-first coaching system for endurance athletes that reconciles nervous-system recovery signals (WHOOP), mechanical/performance execution data (Strava), and subjective input into a single three-horizon (daily / weekly / monthly) decision engine. Deterministic Python drives every recommendation; a local LLM (Ollama) only explains the output, never produces it.

Status: **design phase** — v1.0 is fully specified across four companion documents but not yet implemented (see [Roadmap](#roadmap)).

## Documentation

The full v1.0 design is captured in four companion documents, meant to be read in this order. Each is Word (`.docx`) source; this table is the index and must be kept in sync whenever a doc's version, status, or scope changes.

| # | Document | Covers | Version | Status | Date |
|---|----------|--------|---------|--------|------|
| 1 | [ApexCoach_PRD_v1.0.docx](./ApexCoach_PRD_v1.0.docx) | Problem statement, vision, three-horizon model, feature catalogue (F01–F10), success metrics, constraints, roadmap | 1.0 | In Review | June 2026 |
| 2 | [ApexCoach_SDD_v1.0.docx](./ApexCoach_SDD_v1.0.docx) | Architecture & module boundaries, tech stack, SQLite schema, key algorithm specs, infra/deployment, test strategy overview | 1.0 | In Review | June 2026 |
| 3 | [ApexCoach_API_Integration_Contract_v1.0.docx](./ApexCoach_API_Integration_Contract_v1.0.docx) | WHOOP / Strava / Ollama OAuth flows, endpoint contracts, mock fixtures, failure modes, rate-limit strategy | 1.0 | In Review | June 2026 |
| 4 | [ApexCoach_Logic_Algorithm_Spec_v1.0.docx](./ApexCoach_Logic_Algorithm_Spec_v1.0.docx) | Input classification bands, full decision trees, weekly state machine, monthly load/forecast model, session scoring, zone calculator | 1.0 | In Review | June 2026 |

Each document's own "Document Control" section names the next document in the chain — the Logic & Algorithm Spec points to a not-yet-written **Test Strategy Document** as the next piece of design work.

> When a `.docx` is revised (version bump, status change), update its row above in the same commit — this table is the single index into the doc set and should never drift from the files it links.

### System at a glance

- **Three decision horizons**, monthly has final authority over weekly, weekly over daily.
- **Daily engine** — WHOOP recovery + HRV delta + soreness + morning health check → `GO / MODIFY / MODALITY_SWAP / ABORT`.
- **Weekly engine** — reschedules or writes off skipped key sessions against the monthly load target.
- **Monthly engine** — accumulates load, forecasts performance, flags target risk.
- **Explanation layer** — local Ollama (LLaMA 3.1 8B) turns structured decision JSON into natural language. It explains; it never decides.
- **Persistence** — SQLite in v1.0, schema written to be PostgreSQL-compatible for a clean v2.0 promotion to Azure.

See the [PRD](./ApexCoach_PRD_v1.0.docx) §3 for the full three-horizon model and the [SDD](./ApexCoach_SDD_v1.0.docx) §1.2 for the system context diagram.

## Roadmap

| Phase | Scope |
|-------|-------|
| v1.0 — Script MVP (current) | F01–F10, CLI only, SQLite, local Ollama |
| v1.5 — Enrichment Layer | Banister Impulse-Response load model, NSDR/Yoga Nidra recommender, trend reports, 80%+ coverage in CI |
| v2.0 — Azure Web App | FastAPI backend, PostgreSQL, minimal React frontend, multi-user |
| v3.0 — Expanded Intelligence | Coros API, auto periodisation, nutrition data, coach collaboration |

## Working with this repo

This repo also carries the design-decision infrastructure for stress-testing plans against the docs above:

- [`CONTEXT.md`](./CONTEXT.md) — canonical glossary of Apex Coach domain terms (recovery bands, session tiers, decision outputs, etc.), sourced from the four docs and updated as terminology is resolved or refined.
- [`docs/adr/`](./docs/adr/) — architecture decision records for choices that are hard to reverse and not already settled in the SDD.

Use the `grill-me` skill to stress-test a plan in general, or `grill-with-docs` to stress-test a plan against this glossary and ADR set specifically.

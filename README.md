# Apex Coach

**Holistic AI Training Coach** — a local-first coaching system for endurance athletes that reconciles nervous-system recovery signals (WHOOP), mechanical/performance execution data (Strava), and subjective input into a single three-horizon (daily / weekly / monthly) decision engine. Deterministic Python drives every recommendation; a local LLM (Ollama) only explains the output, never produces it.

Status: **design phase** — v1.0 is fully specified across four companion documents but not yet implemented (see [Roadmap](#roadmap)).

## Documentation

The full v1.0 design is captured in four companion documents, meant to be read in this order. `.docx` is the authored source (opens in Word); the linked `.md` is a generated, GitHub-readable mirror of the same content — read that one here.

| # | Document | Covers | Version | Status | Date |
|---|----------|--------|---------|--------|------|
| 1 | [PRD](./docs/ApexCoach_PRD_v1.0.md) ([.docx](./ApexCoach_PRD_v1.0.docx)) | Problem statement, vision, three-horizon model, feature catalogue (F01–F10), success metrics, constraints, roadmap | 1.0 | In Review | June 2026 |
| 2 | [SDD](./docs/ApexCoach_SDD_v1.0.md) ([.docx](./ApexCoach_SDD_v1.0.docx)) | Architecture & module boundaries, tech stack, SQLite schema, key algorithm specs, infra/deployment, test strategy overview | 1.0 | In Review | June 2026 |
| 3 | [API Integration Contract](./docs/ApexCoach_API_Integration_Contract_v1.0.md) ([.docx](./ApexCoach_API_Integration_Contract_v1.0.docx)) | WHOOP / Strava / Ollama OAuth flows, endpoint contracts, mock fixtures, failure modes, rate-limit strategy | 1.0 | In Review | June 2026 |
| 4 | [Logic & Algorithm Spec](./docs/ApexCoach_Logic_Algorithm_Spec_v1.0.md) ([.docx](./ApexCoach_Logic_Algorithm_Spec_v1.0.docx)) | Input classification bands, full decision trees, weekly state machine, monthly load/forecast model, session scoring, zone calculator | 1.0 | In Review | June 2026 |

Each document's own "Document Control" section names the next document in the chain — the Logic & Algorithm Spec points to a not-yet-written **Test Strategy Document** as the next piece of design work.

> When a `.docx` is revised (version bump, status change), update its row above **and** regenerate `docs/*.md` in the same commit: run `./scripts/convert_docs.sh` (requires `pandoc`; uses macOS `textutil` if present to preserve diagram/code alignment — see [scripts/](./scripts/)). This table is the single index into the doc set and should never drift from the files it links.

### System at a glance

- **Three decision horizons**, monthly has final authority over weekly, weekly over daily.
- **Daily engine** — WHOOP recovery + HRV delta + soreness + morning health check → `GO / MODIFY / MODALITY_SWAP / ABORT`.
- **Weekly engine** — reschedules or writes off skipped key sessions against the monthly load target.
- **Monthly engine** — accumulates load, forecasts performance, flags target risk.
- **Explanation layer** — local Ollama (gemma4:latest, docs/adr/0022) turns structured decision JSON into natural language. It explains; it never decides.
- **Persistence** — SQLite in v1.0, schema written to be PostgreSQL-compatible for a clean v2.0 promotion to Azure.

See the [PRD](./docs/ApexCoach_PRD_v1.0.md) §3 for the full three-horizon model and the [SDD](./docs/ApexCoach_SDD_v1.0.md) §1.2 for the system context diagram.

## Roadmap

| Phase | Scope |
|-------|-------|
| v1.0 — Script MVP (current) | F01–F10, CLI only, SQLite, local Ollama |
| v1.5 — Enrichment Layer | Banister Impulse-Response load model, NSDR/Yoga Nidra recommender, trend reports, 80%+ coverage in CI |
| v2.0 — Azure Web App | FastAPI backend, PostgreSQL, minimal React frontend, multi-user |
| v3.0 — Expanded Intelligence | Coros API, auto periodisation, nutrition data, coach collaboration |

## Running locally

1. Copy `.env.example` to `.env` and fill in `APEX_ENCRYPTION_KEY` (and provider credentials once you've registered OAuth apps).
2. `apex_coach init-db` — creates the SQLite schema. Nothing else does this; run it once before any command that touches the database.
3. `apex_coach connect-whoop` — one-time OAuth handshake (see `docs/adr/0018`).
4. `apex_coach whoop-smoke --real` — verify the connection.
5. `apex_coach connect-strava` — one-time OAuth handshake (see `docs/adr/0019`).
6. `apex_coach strava-smoke --real` — verify the connection.

## Working with this repo

This repo also carries the design-decision infrastructure for stress-testing plans against the docs above:

- [`CONTEXT.md`](./CONTEXT.md) — canonical glossary of Apex Coach domain terms (recovery bands, session tiers, decision outputs, etc.), sourced from the four docs and updated as terminology is resolved or refined.
- [`docs/adr/`](./docs/adr/) — architecture decision records for choices that are hard to reverse and not already settled in the SDD.

Use the `grill-me` skill to stress-test a plan in general, or `grill-with-docs` to stress-test a plan against this glossary and ADR set specifically.

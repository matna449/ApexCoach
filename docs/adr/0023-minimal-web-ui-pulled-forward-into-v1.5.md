---
status: accepted
---

# A minimal local web UI is pulled forward into v1.5; PostgreSQL, Azure, and multi-user stay v2.0

With v1.0 (F01–F11) complete and v1.5 being scoped into tickets (Banister load model, NSDR recommendation engine, historical trend charts, CI/coverage), the athlete asked to "appify this a bit" — a proper React frontend, deployable to Azure later. Taken literally, the PRD's v2.0 bullet list (§8) bundles a FastAPI backend, PostgreSQL, a React frontend, an Azure deployment pipeline, and multi-user support into one lump. Pulling all of that forward now would mean abandoning v1.5 mid-flight and taking on cloud infrastructure, a database migration, and auth simultaneously — a much bigger bet than what was actually being asked for.

**Decision: only the frontend/backend split moves into v1.5, scoped as a local-only, single-user addition — not a v2.0 migration.** FastAPI becomes a thin façade over the existing repositories and engines exactly as they are (no rewrite of `daily_engine`/`weekly_engine`/`monthly_engine`/the repository layer); React talks to that façade; SQLite, single-user, and local-only execution are all unchanged. The CLI is not replaced — it stays the primary/tested interface, and the web UI is additive. PostgreSQL, the Azure deployment pipeline, and multi-user support remain explicitly out of scope, deferred to actual v2.0.

**The originally-scoped "historical trend charts" ticket (terminal or simple HTML report) is retired as a standalone deliverable and folded into this work** — its goal becomes the web UI's first screen instead of a throwaway terminal renderer that would be discarded within weeks. The data-reading work is identical either way (HRV trend, load actual-vs-target, execution scores over a date range via the existing repositories); only the rendering target changes, from ASCII/HTML-string to a real React component.

**NSDR/Yoga Nidra recommendation engine is deprioritised**, not dropped — it stays documented in the PRD's v1.5 scope but isn't part of this round of tickets.

PRD §8's roadmap is updated to match: v1.5 now includes the web UI (FastAPI + React) with NSDR marked deferred; v2.0 is trimmed to PostgreSQL, the Azure deployment pipeline, an A/B test framework on the frontend introduced here, mobile-accessible access, and multi-user support.

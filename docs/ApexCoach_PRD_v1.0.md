# Apex Coach

## Holistic AI Training Coach

*Local-first intelligent coaching system for endurance athletes*

|                    |                                     |
|--------------------|-------------------------------------|
| **Document Type**  | Product Requirements Document (PRD) |
| **Version**        | 1.0 — Initial Draft                 |
| **Author**         | Mattias (Primary User / Developer)  |
| **Status**         | In Review                           |
| **Date**           | June 2026                           |
| **Classification** | Personal / Confidential             |

## 1. Purpose & Vision

### 1.1 Problem Statement

Modern wearables like WHOOP and Coros provide rich biometric data, but they operate in silos. An athlete following a structured training plan currently has to manually reconcile nervous system signals (WHOOP recovery, HRV, RHR) with mechanical fatigue signals (muscle soreness, tendon health) and performance execution data (Strava pace, HR, elevation) to decide how to train on any given day — and then mentally project that decision forward across the week and month.

This manual cognitive load is error-prone, inconsistent, and fails to account for the full picture. Athletes overtrain when metrics are green but local fatigue is high. Athletes underperform when they miss the window to push on genuinely well-recovered days. The weekly view obscures monthly periodisation drift.

### 1.2 Vision

Apex Coach is a local-first AI coaching system that aggregates all athlete data into a single structured model and applies a three-horizon decision engine — daily, weekly, and monthly — to produce clear, explainable training recommendations. The system augments but does not replace the athlete's judgement. All reasoning is transparent and auditable.

### 1.3 Design Philosophy

- Local first. All data stays on device. No cloud dependency for core function.

- Deterministic logic before AI. Zone calculations and load scoring are pure Python — testable, fast, auditable. The LLM reasons over structured outputs, not raw data.

- Explainability over black-box decisions. Every recommendation includes a brief rationale citing the specific metrics that drove it.

- Extensible by design. Script-first architecture with clean module boundaries so each component can be promoted to a web service independently.

- Test-driven development from day one. Every module ships with a test suite before being integrated.

## 2. User Persona

|  |  |
|----|----|
| **Name** | Mattias |
| **Role** | Primary User & Developer |
| **Training Model** | Pyramidal periodisation — 1 HIIT, 1 Threshold, 2 Zone 2 (one long), 1 Strength, Active Recovery & Yoga/Mobility |
| **Devices** | WHOOP (recovery & strain), Coros watch (activities), Strava (activity sync hub) |
| **Goals** | Avoid overtraining. Ensure high-quality execution of key sessions. Track performance trajectory monthly. Build a software engineering learning vehicle. |
| **Pain Points** | Manual reconciliation of WHOOP and Coros data in the athlete's head. Overpushing threshold sessions. Underpushing VO2max sessions. No holistic weekly/monthly view. |
| **Technical Level** | Bachelor-level software development. Learning TDD formally through this project. |

## 3. System Overview

### 3.1 Three-Horizon Decision Model

The system operates across three nested planning horizons. The monthly layer has final authority — weekly and daily decisions are constrained by monthly targets.

| **Horizon** | **Cadence** | **Primary Inputs** | **Primary Output** |
|----|----|----|----|
| Monthly | Reviews weekly, updates monthly | Load targets, race calendar, trend HRV, Strava TSS-equivalent | Periodisation phase, monthly load target, performance forecast |
| Weekly | Updates daily after each session | Monthly target, WHOOP weekly trend, session execution scores, skipped sessions | Adapted weekly plan — reschedule, write-off, or recovery week trigger |
| Daily | Runs on demand each morning | WHOOP recovery, HRV, RHR, manual soreness, morning health check, today's scheduled session | Today's recommendation: GO / MODIFY / SWAP / ABORT + rationale |

### 3.2 Data Sources

| **Source** | **Type** | **Key Metrics** | **Used By** |
|----|----|----|----|
| WHOOP API | REST / OAuth 2.0 | Recovery %, HRV, RHR, Strain, Sleep stages | Daily engine, Weekly engine, Zone calculation |
| Strava API | REST / OAuth 2.0 | Activity type, distance, duration, HR, pace, elevation gain, splits | Session scoring, Monthly load, Zone validation |
| Manual Input | CLI prompt / JSON | Muscle soreness (1–5), subjective feel, morning health check ratings | Daily engine, Weekly adaptation |
| Training Plan | User-defined config file | Weekly session labels, target zones, periodisation phase, race dates | All three horizons |
| Ollama (local LLM) | Local inference | Reasoning, natural language explanation, conversational queries | Recommendation layer, explanations |
| SQLite | Local database | All persisted metrics, decisions, scores | All modules |

## 4. Feature Catalogue

### 4.1 Must-Have (v1.0 — Script MVP)

#### F01 — WHOOP OAuth Integration

- Register developer app, obtain Client ID and Secret.

- Complete OAuth 2.0 authorisation flow (one-time browser handshake).

- Securely store and auto-refresh access tokens.

- Fetch daily recovery payload: recovery %, HRV, RHR, strain.

#### F02 — Strava OAuth Integration

- Complete Strava OAuth 2.0 flow.

- Fetch activities: type, distance, duration, average HR, max HR, elevation gain, elapsed time, splits.

- Strava as single source of truth for all completed activity data.

#### F03 — HR Zone Calculator

- Calculate five HR zones using Heart Rate Reserve (HRR) method.

- Inputs: Max HR (from Strava history or manual override), Resting HR (daily from WHOOP).

- Zones recalculate daily as resting HR fluctuates with fitness.

- Output stored in SQLite alongside the date for trend analysis.

#### F04 — Morning Health Check

- Adaptive CLI prompt triggered each morning before the daily engine runs.

- Fixed daily checks: overall muscle soreness (1–5), subjective energy (1–5), sleep quality felt (1–5).

- Adaptive checks based on yesterday's session: e.g. knee pain after strength, Achilles after long Zone 2.

- Responses stored in SQLite and fed directly into the daily decision engine.

#### F05 — Daily Decision Engine

- Consumes: WHOOP recovery %, HRV vs 30-day average, morning health check scores, today's scheduled session type.

- Outputs one of four recommendations: GO / MODIFY / MODALITY SWAP / ABORT.

- Modality swap logic: if soreness is high and session is run-based, recommend cycling or swimming equivalent.

- All logic is deterministic Python. No LLM involvement in the core decision.

#### F06 — Session Execution Scorer

- After each session syncs to Strava, fetch activity and score execution quality.

- Inputs: intended session type label, time in target HR zone, HR drift coefficient, grade-adjusted pace, elevation gain, RPE (manual input), strain vs plan.

- Output: execution quality score (0–100) stored in SQLite with breakdown.

- Flag overpush on threshold and underpush on VO2max sessions automatically.

#### F07 — Weekly Adaptation Engine

- Runs after each daily query and after each session is scored.

- Checks remaining sessions against monthly load target.

- If a key session was skipped: determine whether to reschedule (load deficit) or write off (recovery debt too high).

- Outputs an adapted weekly plan diff — which sessions changed and why.

#### F08 — Monthly Load Tracker

- Accumulates session load scores week by week.

- User defines monthly target load at the start of each training block.

- Engine flags if weekly pace puts the monthly target at risk.

- Generates monthly summary: actual vs target load, trend HRV, session quality averages, notable patterns.

#### F09 — Ollama Explanation Layer

- Wraps every decision engine output with a natural language explanation.

- Model: gemma4:latest running locally via Ollama on M4 Pro (24 GB RAM) — docs/adr/0022.

- LLM receives structured JSON from the decision engine — it explains, it does not decide.

- Supports conversational follow-up queries: athlete can ask 'why' or 'what if I do it anyway'.

#### F10 — SQLite Persistence Layer

- Single local database file for all data.

- Schema designed for clean promotion to PostgreSQL (Azure) with no breaking changes.

- Tables: users, daily_metrics, activities, session_scores, decisions, weekly_plans, monthly_targets, health_checks.

### 4.2 Nice-to-Have (v2.0 — Web App on Azure)

- Web-based dashboard with session history charts and trend visualisations.

- Push notifications / morning prompt via mobile web.

- Multi-week periodisation planning wizard.

- A/B testing framework for frontend recommendation display variants.

- Coros API integration if a stable endpoint becomes available.

- Training load algorithm based on open standards (e.g. Banister Impulse-Response model).

- NSDR / Yoga Nidra recommendation engine for nervous system reboot protocols.

- Multi-user support with individual athlete profiles.

## 5. Success Metrics

### 5.1 Functional Acceptance Criteria

| **\#** | **Criterion** | **Measurement** | **Target** |
|----|----|----|----|
| 1 | Daily decision engine produces a recommendation each morning | Time from WHOOP payload fetch to output | \< 3 seconds |
| 2 | HR zones recalculate correctly with new resting HR | Unit test: known RHR + MaxHR inputs produce expected zone boundaries | 100% pass |
| 3 | Session scorer flags threshold overpush | Integration test: inject overpush Strava activity, verify flag raised | 100% pass |
| 4 | Weekly adaptation correctly reschedules a skipped HIIT | Integration test: simulate Tuesday skip, verify Wednesday or Thursday rescheduled | 100% pass |
| 5 | Ollama explanation layer returns a response | End-to-end test: send structured JSON, verify natural language output returned | \< 8 seconds |
| 6 | All API tokens refresh without manual intervention | Token expiry simulation test | Zero manual re-auth required |
| 7 | SQLite schema migrates to PostgreSQL without data loss | Migration script test on copy of local DB | Zero data loss |

### 5.2 Quality Gates

- No feature is integrated without a passing unit test suite.

- All API integration modules have a mock-based test that runs offline.

- Decision engine logic is covered by a full decision matrix test (all permutations of Recovery × Soreness × Session Type).

- Code coverage target: 80% minimum on all deterministic modules.

### 5.3 Subjective Success (Athlete Perspective)

- The athlete no longer manually reconciles WHOOP and Strava data in their head.

- Threshold session overpush incidents reduce measurably over the first training block.

- VO2max session quality scores improve as the athlete learns to trust GO recommendations.

- Monthly load targets are hit or the system provides a clear explanation of why they were not.

## 6. Constraints & Assumptions

### 6.1 Technical Constraints

- Local-only execution for v1.0. No cloud dependency.

- WHOOP API: OAuth 2.0 required. No username/password scripting possible.

- Strava API: All activity data assumed to sync from Coros automatically. No direct Coros API dependency in v1.0.

- Ollama model: gemma4:latest (docs/adr/0022). Hardware: MacBook Pro 14-inch, M4 Pro, 24 GB RAM, macOS Tahoe 26.3.

- Language: Python 3.11+. CLI interface only for v1.0.

- Database: SQLite for v1.0. Schema must be PostgreSQL-compatible for clean Azure promotion.

### 6.2 Assumptions

- All Coros activity data syncs to Strava automatically and is available via the Strava API within minutes of session completion.

- WHOOP provides a stable daily recovery payload by 07:00 local time after a full night of wear.

- Max HR is taken as the highest HR recorded in Strava history, with a manual override option available.

- The athlete inputs the training plan as a structured config file at the start of each training block. The system does not auto-generate training plans in v1.0.

- Muscle soreness and morning health check inputs are provided honestly. The system cannot validate subjective inputs.

### 6.3 Out of Scope for v1.0

- Automatic training plan generation.

- Nutrition or hydration tracking.

- Sleep staging analysis beyond WHOOP's own output.

- Multi-user accounts.

- Web or mobile interface.

- Push or scheduled notifications.

- Direct Coros API integration.

## 7. Risks & Mitigations

| **Risk** | **Severity** | **Mitigation** | **Owner** |
|----|----|----|----|
| WHOOP API deprecates or changes endpoints | High | Pin API version. Abstract all API calls behind an adapter layer. Monitor developer changelog. | Developer |
| Strava rate limits hit during development | Medium | Cache all API responses locally. Use mock payloads for unit and integration tests. | Developer |
| LLM output is inconsistent or hallucinates recommendations | High | LLM never makes decisions — it only explains deterministic outputs. Structured prompt with strict output format. | Developer |
| SQLite schema becomes incompatible with PostgreSQL on migration | Medium | Use PostgreSQL-compatible types and constraints from day one. Run migration tests early. | Developer |
| Subjective inputs (soreness) are inconsistent and skew decisions | Low | Log all inputs. Build trend analysis to detect anomalies. Future: prompt for rationale on extreme inputs. | Athlete |
| Scope creep delays v1.0 delivery | Medium | Hard MVP boundary: only F01–F10 in v1.0. All other ideas logged to v2.0 backlog. | Developer |

## 8. Future Development Roadmap

### v1.0 — Script MVP (Current)

- F01–F10 as defined above.

- CLI interface only.

- SQLite local database.

- Ollama local LLM (gemma4:latest, docs/adr/0022).

### v1.5 — Enrichment Layer

- Banister Impulse-Response model for open-standard training load calculation.

- Minimal local web UI: a FastAPI façade over the existing engines/repositories (unchanged, not rewritten) plus a React frontend, with historical trend charts as its first screen. Local-only, single-user, SQLite — the CLI is not replaced. Supersedes the originally-scoped terminal/HTML trend-charts report (docs/adr/0023).

- Full decision matrix test suite and 80%+ code coverage enforced by CI.

- NSDR / Yoga Nidra recommendation engine for nervous system reboot protocols — deprioritised for this milestone (docs/adr/0023), not dropped.

### v2.0 — Azure Web App

- PostgreSQL on Azure replacing SQLite.

- A/B test framework on the React frontend introduced in v1.5.

- Mobile-accessible morning prompt via browser.

- Azure deployment pipeline with staging and production environments.

- Multi-user support with per-athlete profiles.

### v3.0 — Expanded Intelligence

- Coros API integration (if stable endpoint available).

- Automatic periodisation plan generation based on race calendar input.

- Nutrition and hydration data integration (third-party API TBD).

- Collaborative features — share summaries with a human coach.

## 9. Document Control

| **Version** | **Date** | **Changes** | **Author** |
|----|----|----|----|
| 1.0 | June 2026 | Initial draft. Full discovery completed. All features defined through structured Q&A. | Mattias |

*Next document: System Design Document (SDD) — architecture, module breakdown, SQLite schema, infrastructure diagram.*

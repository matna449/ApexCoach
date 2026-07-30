# Apex Coach

## System Design Document

*Architecture, modules, data schema, and infrastructure design*

|  |  |
|----|----|
| **Document Type** | System Design Document (SDD) |
| **Version** | 1.0 — Initial Draft |
| **Companion Doc** | ApexCoach_PRD_v1.0 — read first |
| **Author** | Mattias (Primary User / Developer) |
| **Status** | In Review |
| **Date** | June 2026 |
| **Target Platform** | macOS local script → Azure Web App (v2.0) |
| **Hardware** | MacBook Pro 14-inch, M4 Pro, 24 GB RAM, macOS Tahoe 26.3 |

## 1. Architecture Overview

### 1.1 Design Principles

- Separation of concerns. Each module has one responsibility. No module calls the LLM directly except the Explanation Layer.

- Deterministic core. Zone calculation, load scoring, and all decision logic are pure Python — no randomness, no LLM. This makes them fully unit-testable.

- LLM at the edge. Ollama receives structured JSON and returns natural language. It explains outputs; it does not produce them.

- Adapter pattern for all external APIs. WHOOP, Strava, and Ollama are accessed only through adapter classes, each with two concrete implementations — Real and Mock — behind a shared interface, injected at construction. Swapping an API or mocking it for tests requires changing one file, not the transport layer.

- Schema-first persistence. SQLite schema is designed with PostgreSQL constraints from day one. Promotion to Azure requires a data migration script, not a redesign.

- Offline-capable. Every module can run against local mock data. No live API required during development or testing.

### 1.2 System Context Diagram

The following diagram shows all external actors and the system boundary. Everything inside the boundary runs locally on the athlete's machine in v1.0.

```
┌─────────────────────────────────────────────────────────────────────┐
│                        APEX COACH (local)                           │
│                                                                     │
│  ┌──────────────┐   ┌───────────────┐   ┌───────────────────────┐  │
│  │  CLI Runner  │──▶│  Orchestrator │──▶│   Explanation Layer   │  │
│  └──────────────┘   └───────┬───────┘   │   (Ollama LLaMA 3.1) │  │
│                             │            └───────────────────────┘  │
│          ┌──────────────────┼──────────────────────┐                │
│          ▼                  ▼                       ▼                │
│  ┌──────────────┐  ┌──────────────┐  ┌──────────────────────────┐  │
│  │ Daily Engine │  │ Weekly Engine│  │    Monthly Load Tracker  │  │
│  └──────┬───────┘  └──────┬───────┘  └──────────┬───────────────┘  │
│         │                 │                      │                  │
│         └─────────────────┴──────────────────────┘                  │
│                                   │                                 │
│                    ┌──────────────▼──────────────┐                  │
│                    │       Core Services         │                  │
│                    │  Zone Calc │ Session Scorer │                  │
│                    │  Load Calc │ Health Check   │                  │
│                    └──────────────┬──────────────┘                  │
│                                   │                                 │
│                    ┌──────────────▼──────────────┐                  │
│                    │     Data Access Layer       │                  │
│                    │  WHOOP Adapter │  Strava    │                  │
│                    │  Adapter       │  SQLite    │                  │
│                    └──────────────┬──────────────┘                  │
└───────────────────────────────────┼─────────────────────────────────┘
                                    │
              ┌─────────────────────┼──────────────────────┐
              ▼                     ▼                      ▼
        ┌───────────┐        ┌───────────┐         ┌───────────┐
        │ WHOOP API │        │ Strava API│         │  SQLite   │
        │ (OAuth2)  │        │ (OAuth2)  │         │  (local)  │
        └───────────┘        └───────────┘         └───────────┘
```

## 2. Tech Stack

### 2.1 Selection & Justification

| **Layer** | **Technology** | **Version Target** | **Justification** |
|----|----|----|----|
| Language | Python | 3.11+ | Numeric libraries, first-class async, strong testing ecosystem. Promotes cleanly to FastAPI backend. |
| CLI Interface | argparse / Click | latest | Simple, testable command-line interface. Zero frontend overhead for v1.0. |
| HTTP Client | httpx | 0.27+ | Async-native, supports OAuth flows cleanly. Preferred over requests for future async promotion. |
| Auth | authlib | 1.3+ | OAuth 2.0 PKCE flow handling, token storage and refresh. Reduces auth boilerplate significantly. |
| Database | SQLite + aiosqlite | 3.x / 0.20 | File-based, zero-server, PostgreSQL-compatible DDL. aiosqlite for async queries. |
| ORM / Query | SQLAlchemy Core | 2.0+ | SQL Expression Language (not ORM). Explicit queries, full control, clean migration to PostgreSQL without model rewrites. |
| LLM Runtime | Ollama | latest | Local LLM inference on Apple Silicon. Zero data leaves the machine. Model: LLaMA 3.1 8B (fits in 24 GB with headroom). |
| LLM Client | ollama-python | 0.3+ | Official Python client for Ollama. Handles streaming, structured prompts, and JSON mode. |
| Testing | pytest + pytest-cov | 7.x / 4.x | Industry standard. Fixtures, parametrize, coverage reporting. Supports TDD workflow from day one. |
| Mocking | pytest-httpx | 0.30+ | Intercepts httpx calls for offline API testing. No live credentials needed for unit or integration tests. |
| Secrets | python-dotenv | 1.0+ | Loads .env file for local secrets. Gitignored. Maps directly to Azure App Service environment variables in v2.0. |
| Data Validation | pydantic | 2.0+ | All API payloads and config files validated against typed models. Catches bad data at ingestion, not deep in logic. |
| Numerics | pandas + numpy | 2.x / 1.x | Time-series operations for HRV trends, load accumulation, HR zone analysis over Strava streams. |

### 2.2 v2.0 Additions (Azure Promotion)

| **Layer** | **Technology** | **Notes** |
|----|----|----|
| Web Framework | FastAPI | Replaces CLI. Async-native. OpenAPI docs auto-generated. |
| Database | PostgreSQL | Replaces SQLite. Same SQLAlchemy Core queries. Migration via Alembic. |
| Hosting | Azure App Service | Python runtime. Free tier sufficient for personal use. |
| DB Hosting | Azure Database for PostgreSQL | Managed. Backups included. |
| Secrets | Azure Key Vault | Replaces .env. Same environment variable interface. |
| Frontend | React (minimal) | Single-page app. Served from Azure Static Web Apps. |

## 3. Module Breakdown

### 3.1 Directory Structure

All modules follow a flat package structure. Each module directory contains its implementation, its tests, and a README describing its contract.

```
apex_coach/
├── cli/
│   └── main.py                  # Entry point — argument parsing, orchestration calls
├── orchestrator/
│   └── orchestrator.py          # Coordinates daily / weekly / monthly engines
├── engines/
│   ├── daily_engine.py          # Decision logic: GO / MODIFY / SWAP / ABORT
│   ├── weekly_engine.py         # Adaptation logic: reschedule or write-off
│   └── monthly_engine.py        # Load tracking, periodisation phase, forecasting
├── services/
│   ├── zone_calculator.py       # HRR-based zone computation (pure math)
│   ├── session_scorer.py        # Execution quality scoring from Strava data
│   ├── load_calculator.py       # Grade-adjusted load, TSS-equivalent
│   └── health_check.py          # Morning check prompts, adaptive question logic
├── adapters/
│   ├── whoop_adapter.py         # WHOOP API: OAuth, token refresh, payload fetch
│   ├── strava_adapter.py        # Strava API: OAuth, activity fetch, stream fetch
│   └── ollama_adapter.py        # Ollama: structured prompt, JSON mode, streaming
├── db/
│   ├── schema.py                # SQLAlchemy Core table definitions
│   ├── migrations/              # Version-controlled schema changes
│   ├── token_repository.py       # OAuth tokens — no raw SQL outside this file
│   ├── metrics_repository.py     # daily_metrics / hr_zones / activities / session_scores — no raw SQL outside this file
│   └── plan_repository.py        # weekly_plans / monthly_targets / decisions — no raw SQL outside this file
├── models/
│   └── pydantic_models.py       # All typed data models (API payloads, configs, outputs)
├── config/
│   ├── training_plan.json       # User-defined weekly session labels and targets
│   └── settings.py             # Loads .env, exposes typed config object
├── tests/
│   ├── unit/                    # One test file per service/engine module
│   ├── integration/             # Tests requiring DB or mocked API responses
│   └── fixtures/                # Mock JSON payloads for WHOOP and Strava
├── .env                         # Gitignored — OAuth credentials, DB path
├── requirements.txt
└── README.md
```

### 3.2 Module Contracts

Each module exposes a defined interface. Internal implementation details are private. The table below summarises each module's inputs, outputs, and test strategy.

| **Module** | **Primary Input** | **Primary Output** | **Test Strategy** |
|----|----|----|----|
| cli | Command-line arguments (argparse/Click) | stdout recommendation/report, exit code | Integration — full CLI run against mocked Orchestrator |
| orchestrator | Adapter outputs (raw typed payloads: WhoopDailyPayload, StravaActivity), engine outputs | Classified inputs per engine (Recovery Band, HRV Delta, Soreness Band); enforces monthly → weekly → daily authority | Integration — verify call ordering, raw→classified translation, and that no engine can override a higher-horizon constraint |
| zone_calculator | Max HR (int), Resting HR (int) | Dict of 5 zone boundaries (bpm) | Unit — parametrised with known HR values |
| load_calculator | Distance (m), Duration (s), Elevation (m), Avg HR (bpm) | Load score (float), Grade-adjusted pace (float) | Unit — parametrised with flat vs hilly runs |
| session_scorer | Strava activity JSON, Intended zone label, RPE (int), planned_load_au (from weekly_engine / training plan) | Execution score (0–100), Flags (overpush / underpush) | Integration — inject mock Strava payloads |
| health_check | Yesterday's session type (str), Previous check data | Dict of scored health check responses | Unit — adaptive question logic tested per session type |
| daily_engine | Classified inputs from Orchestrator (Recovery Band, HRV Delta, Soreness Band), Health check scores, Training plan entry | Decision enum + rationale dict | Unit — full decision matrix (all Recovery x Soreness x Session permutations) |
| weekly_engine | Weekly session log, Monthly target, WHOOP 7-day trend | Adapted weekly plan diff | Integration — simulate skipped sessions, verify rescheduling |
| monthly_engine | Session scores (all), Load targets, Race calendar | Monthly summary, Load forecast, Phase recommendation | Integration — simulate full training block |
| whoop_adapter | OAuth credentials (from .env) | Typed WhoopDailyPayload model | Unit — MockWhoopAdapter substitutes RealWhoopAdapter behind shared interface; token refresh tested against both |
| strava_adapter | OAuth credentials, Activity ID | Typed StravaActivity model | Unit — MockStravaAdapter substitutes RealStravaAdapter behind shared interface; pagination tested against both |
| ollama_adapter | Structured JSON decision output | Natural language explanation string | Unit — MockOllamaAdapter simulates all 4 documented failure modes; live call retained as manual smoke test only, skipped in CI |
| token_repository | Typed OAuth token model instances | DB read/write confirmation | Integration — in-memory SQLite per test |
| metrics_repository | Typed daily_metrics / hr_zones / activities / session_scores model instances | DB read/write confirmation or query results | Integration — in-memory SQLite per test |
| plan_repository | Typed weekly_plans / monthly_targets / decisions model instances | DB read/write confirmation or query results | Integration — in-memory SQLite per test |

## 4. SQLite Data Schema

### 4.1 Schema Design Principles

- All primary keys are UUIDs (TEXT in SQLite, UUID in PostgreSQL). No auto-increment integers — they break on migration.

- All timestamps are ISO 8601 strings in UTC (TEXT in SQLite, TIMESTAMPTZ in PostgreSQL).

- All optional fields are explicitly nullable. No implicit nulls.

- Foreign keys are declared and enforced. Enable with PRAGMA foreign_keys = ON in SQLite.

- No computed fields stored in the DB. Scores and zones are recalculated from raw inputs where needed for auditability.

### 4.2 Table: daily_metrics

One row per day. Aggregates all WHOOP and manual morning inputs for a given date.

| **Column** | **Type** | **Key** | **Description** |
|----|----|----|----|
| id | TEXT | PK | UUID v4. Generated on insert. |
| date | TEXT | UQ | ISO 8601 date (YYYY-MM-DD). One row per day. Unique constraint. |
| whoop_recovery_pct | REAL |  | WHOOP recovery percentage (0.0–100.0). |
| whoop_hrv_ms | REAL |  | HRV in milliseconds from WHOOP. |
| whoop_rhr_bpm | INTEGER |  | Resting heart rate from WHOOP (bpm). |
| whoop_strain | REAL |  | WHOOP day strain score (0.0–21.0). |
| whoop_sleep_hours | REAL |  | Total sleep hours from WHOOP. |
| hrv_30d_avg_ms | REAL |  | Rolling 30-day HRV average at time of record. Stored for audit trail. |
| muscle_soreness | INTEGER |  | Manual input. Scale 1 (none) to 5 (severe). |
| subjective_energy | INTEGER |  | Manual input. Scale 1 (exhausted) to 5 (excellent). |
| sleep_quality_felt | INTEGER |  | Manual input. Scale 1 (poor) to 5 (excellent). |
| health_check_json | TEXT |  | JSON blob of adaptive health check Q&A for the day. |
| created_at | TEXT |  | UTC timestamp of record creation. |

### 4.3 Table: hr_zones

One row per day. Zones recalculate daily as resting HR changes. Stored for audit and trend analysis.

| **Column** | **Type** | **Key** | **Description** |
|----|----|----|----|
| id | TEXT | PK | UUID v4. |
| date | TEXT | FK | References daily_metrics.date. |
| max_hr_bpm | INTEGER |  | Max HR used in calculation. From Strava history or manual override. |
| rest_hr_bpm | INTEGER |  | Resting HR from WHOOP for this date. |
| zone1_min | INTEGER |  | Zone 1 lower bound (bpm). Recovery / easy aerobic. |
| zone1_max | INTEGER |  | Zone 1 upper bound (bpm). |
| zone2_min | INTEGER |  | Zone 2 lower bound (bpm). Aerobic base. |
| zone2_max | INTEGER |  | Zone 2 upper bound (bpm). |
| zone3_min | INTEGER |  | Zone 3 lower bound (bpm). Tempo / threshold approach. |
| zone3_max | INTEGER |  | Zone 3 upper bound (bpm). |
| zone4_min | INTEGER |  | Zone 4 lower bound (bpm). Threshold. |
| zone4_max | INTEGER |  | Zone 4 upper bound (bpm). |
| zone5_min | INTEGER |  | Zone 5 lower bound (bpm). VO2max / neuromuscular. |
| zone5_max | INTEGER |  | Zone 5 upper bound (bpm). Equal to max_hr_bpm. |
| created_at | TEXT |  | UTC timestamp. |

### 4.4 Table: activities

One row per completed activity, sourced from Strava. Updated on each Strava sync.

| **Column** | **Type** | **Key** | **Description** |
|----|----|----|----|
| id | TEXT | PK | UUID v4 (internal). Not Strava's ID. |
| strava_id | TEXT | UQ | Strava activity ID. Unique. Used for deduplication on sync. |
| date | TEXT | FK | References daily_metrics.date. |
| activity_type | TEXT |  | Strava type: Run, Ride, Swim, WeightTraining, Yoga, etc. |
| intended_session_type | TEXT |  | Label from training plan: HIIT, Threshold, Zone2, Strength, Recovery. NULL if unscheduled. |
| duration_seconds | INTEGER |  | Total elapsed time in seconds. |
| distance_metres | REAL |  | Total distance in metres. NULL for non-distance activities. |
| elevation_gain_m | REAL |  | Total elevation gain in metres. |
| avg_hr_bpm | INTEGER |  | Average heart rate for the activity. |
| max_hr_bpm | INTEGER |  | Max heart rate recorded during the activity. |
| avg_pace_sec_per_km | REAL |  | Average pace in seconds per kilometre. NULL for non-run activities. |
| grade_adj_pace | REAL |  | Grade-adjusted pace in sec/km. Accounts for elevation. |
| load_score | REAL |  | Calculated training load score for this session. |
| rpe | INTEGER |  | Manual post-session RPE input. Scale 1–10. |
| strava_raw_json | TEXT |  | Full Strava API response stored as JSON for reprocessing. |
| created_at | TEXT |  | UTC timestamp of record creation. |

### 4.5 Table: session_scores

One row per scored activity. Linked to activities. Stores execution quality breakdown.

| **Column** | **Type** | **Key** | **Description** |
|----|----|----|----|
| id | TEXT | PK | UUID v4. |
| activity_id | TEXT | FK | References activities.id. |
| execution_score | REAL |  | Overall execution quality score (0.0–100.0). |
| time_in_zone_pct | REAL |  | Percentage of session time spent in the intended HR zone. |
| hr_drift_coeff | REAL |  | Cardiac drift coefficient. Measure of aerobic decoupling. |
| overpush_flag | TEXT |  | TRUE / FALSE. Set when HR exceeds intended zone ceiling significantly. |
| underpush_flag | TEXT |  | TRUE / FALSE. Set when HR fails to reach intended zone floor. |
| score_breakdown_json | TEXT |  | JSON breakdown of all component scores for display and audit. |
| created_at | TEXT |  | UTC timestamp. |

### 4.6 Table: decisions

One row per daily decision engine run. Full audit trail of all recommendations made.

| **Column** | **Type** | **Key** | **Description** |
|----|----|----|----|
| id | TEXT | PK | UUID v4. |
| date | TEXT | FK | References daily_metrics.date. |
| scheduled_session | TEXT |  | Session type from training plan for this date. |
| recommendation | TEXT |  | Enum: GO / MODIFY / MODALITY_SWAP / ABORT. |
| rationale_json | TEXT |  | JSON object: keys are decision factors (recovery, hrv_trend, soreness), values are the values and their contribution. |
| llm_explanation | TEXT |  | Natural language explanation returned by Ollama. |
| athlete_override | TEXT |  | NULL or the athlete's chosen override (e.g. WENT_ANYWAY). Logged for pattern analysis. |
| created_at | TEXT |  | UTC timestamp. |

### 4.7 Table: weekly_plans

One row per week. Tracks the adapted plan state as sessions are completed or skipped.

| **Column** | **Type** | **Key** | **Description** |
|----|----|----|----|
| id | TEXT | PK | UUID v4. |
| week_start_date | TEXT | UQ | ISO 8601 date of the Monday starting this week. |
| planned_sessions_json | TEXT |  | JSON array of planned sessions for the week as defined at week start. |
| adapted_plan_json | TEXT |  | JSON array of adapted sessions, updated after each daily engine run. |
| load_target | REAL |  | Weekly load target derived from monthly goal. |
| load_actual | REAL |  | Accumulated load score from completed sessions this week. |
| skipped_sessions | TEXT |  | JSON array of session types that were skipped and their disposition (rescheduled / written_off). |
| week_status | TEXT |  | Enum: ON_TRACK / LOAD_DEFICIT / RECOVERY_WEEK / COMPLETE. |
| created_at | TEXT |  | UTC timestamp. |
| updated_at | TEXT |  | UTC timestamp of last update. |

### 4.8 Table: monthly_targets

One row per training month. Defines targets at block start, tracks actuals across the month.

| **Column** | **Type** | **Key** | **Description** |
|----|----|----|----|
| id | TEXT | PK | UUID v4. |
| month_start_date | TEXT | UQ | ISO 8601 date of the first day of the month. |
| periodisation_phase | TEXT |  | Enum: BASE / BUILD / PEAK / TAPER / RECOVERY. Defined by athlete at block start. |
| load_target_total | REAL |  | Total monthly load target. |
| load_actual_total | REAL |  | Accumulated actual load. Updated weekly. |
| hrv_trend_json | TEXT |  | JSON array of weekly avg HRV values for the month. |
| race_date | TEXT |  | Target race date if applicable. NULL otherwise. |
| month_summary_json | TEXT |  | JSON summary generated at month close: execution quality averages, load delta, notable patterns. |
| created_at | TEXT |  | UTC timestamp. |

## 5. Key Algorithms & Calculation Specs

### 5.1 HR Zone Calculation (HRR Method)

Heart Rate Reserve (HRR) zones are more accurate than max-HR-percentage zones because they account for the athlete's current fitness baseline (resting HR). Zones shift slightly day-to-day as resting HR improves.

```
HRR = Max HR - Resting HR

Zone 1 (Recovery):    50–60% HRR  →  RHR + (0.50 × HRR)  to  RHR + (0.60 × HRR)
Zone 2 (Aerobic):     60–70% HRR  →  RHR + (0.60 × HRR)  to  RHR + (0.70 × HRR)
Zone 3 (Tempo):       70–80% HRR  →  RHR + (0.70 × HRR)  to  RHR + (0.80 × HRR)
Zone 4 (Threshold):   80–90% HRR  →  RHR + (0.80 × HRR)  to  RHR + (0.90 × HRR)
Zone 5 (VO2max):      90–100% HRR →  RHR + (0.90 × HRR)  to  Max HR

Example: Max HR = 192, Resting HR = 48 (from WHOOP)
  HRR = 192 - 48 = 144
  Zone 2: 48 + (0.60 × 144) to 48 + (0.70 × 144)  =  134 to 149 bpm
  Zone 4: 48 + (0.80 × 144) to 48 + (0.90 × 144)  =  163 to 178 bpm
```

### 5.2 Grade-Adjusted Load Calculation

A flat 10km and a hilly 10km produce different training stimuli. Grade-adjusted pace normalises for elevation to give a fair load comparison across routes.

```
Grade (%) = (Elevation Gain / Distance) × 100

Grade Adjustment Factor (Minetti coefficients, simplified):
  Grade ≤  0%:  factor = 1.00  (flat or descent, no uplift)
  Grade 1–3%:  factor = 1.05
  Grade 3–6%:  factor = 1.12
  Grade 6–10%: factor = 1.22
  Grade > 10%: factor = 1.35

Grade-Adjusted Pace = Actual Pace (sec/km) × Grade Adjustment Factor

Load Score = (Duration_minutes × Avg_HR_bpm × Grade_Factor) / 1000

Note: This is an approximation. The Banister Impulse-Response model
      will replace this in v1.5 for more physiologically accurate load.
```

### 5.3 Session Execution Score

The execution score rates how well the athlete performed the intended session. Component weights are tunable via config.

```
Components:
  time_in_zone_score  (weight: 0.45)  — % of session time in intended zone → 0–100
  hr_drift_score      (weight: 0.25)  — cardiac decoupling coefficient → 0–100 (lower drift = higher score)
  rpe_alignment_score (weight: 0.20)  — RPE vs expected RPE for session type → 0–100
  load_delta_score    (weight: 0.10)  — actual load vs planned load → 0–100

execution_score = (time_in_zone_score × 0.45)
                + (hr_drift_score     × 0.25)
                + (rpe_alignment_score × 0.20)
                + (load_delta_score    × 0.10)

Flags (set independently, do not affect score):
  overpush_flag  = TRUE if time above intended zone ceiling > 15% of session
  underpush_flag = TRUE if time below intended zone floor   > 30% of session
                   (higher threshold for underpush — warm-up accounts for some)
```

### 5.4 HRV Trend Signal

The daily engine uses a rolling 30-day HRV average to contextualise the current day's HRV reading. This prevents a single outlier night from triggering an unnecessary abort.

```
hrv_delta = today_hrv - hrv_30d_avg

Signal interpretation:
  hrv_delta > +5 ms   →  POSITIVE (suppressed system clearing)
  hrv_delta within ±5 ms  →  NEUTRAL (within normal noise)
  hrv_delta < -5 ms   →  NEGATIVE (suppressed — confirm with recovery %)
  hrv_delta < -10 ms  →  STRONG NEGATIVE (override yellow → treat as red)

The 30-day average is stored in daily_metrics.hrv_30d_avg_ms at insert time.
This means historical context is preserved even if data is re-analysed later.
```

## 6. Infrastructure & Deployment

### 6.1 v1.0 — Local Script

```
┌────────────────────────────────────────────────────────┐
│  MacBook Pro M4 Pro · 24 GB RAM · macOS Tahoe          │
│                                                        │
│  ┌─────────────────────┐   ┌──────────────────────┐   │
│  │  Python 3.11 venv   │   │  Ollama (background) │   │
│  │  apex_coach/        │   │  LLaMA 3.1 8B        │   │
│  │  CLI: python -m     │──▶│  localhost:11434     │   │
│  │  apex_coach.cli     │   └──────────────────────┘   │
│  └────────┬────────────┘                              │
│           │                                           │
│           ▼                                           │
│  ┌─────────────────────┐                             │
│  │  SQLite             │                             │
│  │  ~/apex_coach.db    │                             │
│  └─────────────────────┘                             │
│                                                        │
│  External calls (HTTPS):                              │
│    api.developer.whoop.com   (OAuth + data)           │
│    www.strava.com/api/v3     (OAuth + activities)     │
└────────────────────────────────────────────────────────┘
```

### 6.2 v2.0 — Azure Promotion Path

```
┌──────────────────────┐     ┌────────────────────────────────────────┐
│  Athlete Browser     │────▶│  Azure Static Web Apps                 │
│  (mobile / desktop)  │     │  React frontend                        │
└──────────────────────┘     └────────────────┬───────────────────────┘
                                              │ HTTPS
                                              ▼
                             ┌────────────────────────────────────────┐
                             │  Azure App Service (Python)            │
                             │  FastAPI backend                       │
                             │  Same engine + service modules         │
                             └────┬───────────────────┬───────────────┘
                                  │                   │
                    ┌─────────────▼──┐   ┌───────────▼──────────────┐
                    │ Azure Database │   │  Azure Key Vault         │
                    │ PostgreSQL     │   │  OAuth tokens, secrets   │
                    └────────────────┘   └──────────────────────────┘

Note: Ollama remains local in v2.0. Cloud LLM option (Azure OpenAI)    
      is a v3.0 consideration only.                                    
```

### 6.3 Environment Variables (.env)

All secrets and configuration are loaded from a .env file in v1.0. This file is gitignored. The same variable names map directly to Azure App Service environment variables in v2.0.

```
# WHOOP
WHOOP_CLIENT_ID=...
WHOOP_CLIENT_SECRET=...
WHOOP_REDIRECT_URI=http://localhost:8080/callback

# Strava
STRAVA_CLIENT_ID=...
STRAVA_CLIENT_SECRET=...
STRAVA_REDIRECT_URI=http://localhost:8080/callback/strava

# Database
DATABASE_URL=sqlite+aiosqlite:///./apex_coach.db

# Ollama
OLLAMA_BASE_URL=http://localhost:11434
OLLAMA_MODEL=llama3.1:8b

# Athlete config
ATHLETE_MAX_HR=192          # Override. Recalculated from Strava if not set.
```

## 7. Testing Strategy Overview

The full Test Strategy Document is a separate deliverable. This section records the architectural decisions that make the system testable.

### 7.1 Test Pyramid

```
                    ╔═══════════════╗
                    ║   E2E / Manual ║   Small number. Full CLI run.
                    ╚═══════════════╝
               ╔═════════════════════════╗
               ║   Integration Tests      ║   DB + mocked APIs + engines.
               ╚═════════════════════════╝
          ╔════════════════════════════════════╗
          ║        Unit Tests                   ║   All services. All engines. All maths.
          ╚════════════════════════════════════╝
```

### 7.2 Testability Decisions

- All external I/O is behind adapter classes. Adapters are injected (not imported directly) so tests can substitute mocks.

- All decision engine functions are pure functions: same inputs always produce same outputs. No internal state, no DB calls inside engine logic.

- Each repository module (token_repository, metrics_repository, plan_repository) is the only place that writes to its own tables — no raw SQL elsewhere. Integration tests use an in-memory SQLite instance created fresh per test.

- Mock JSON fixtures for WHOOP and Strava payloads live in tests/fixtures/. These are the single source of truth for offline testing.

- The four documented Ollama failure modes (connection refused, model not found, timeout, malformed output) are unit-tested via MockOllamaAdapter, which simulates each deterministically. The one live-call integration test is marked with a custom @pytest.mark.live_llm marker and is skipped in CI — it runs manually only as a smoke test, not as failure-mode coverage.

- Code coverage target: 80% minimum on all modules in engines/ and services/. Enforced by pytest-cov with a --fail-under=80 flag in CI.

## 8. Document Control

| **Version** | **Date** | **Changes** | **Author** |
|----|----|----|----|
| 1.0 | June 2026 | Initial draft. Full architecture, module contracts, schema, algorithms, and infrastructure defined. | Mattias |

*Next document: API Integration Contract — WHOOP OAuth flow, Strava payload mapping, mock fixtures, and failure mode handling.*

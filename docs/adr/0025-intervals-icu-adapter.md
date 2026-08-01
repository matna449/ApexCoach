# ADR 0025: Intervals.icu Activity & Planning Sync Provider Adapter

## Status
Accepted

## Context
ApexCoach needs to support alternative activity-sync providers alongside Strava (starting with Intervals.icu, per PRD #89). To implement `session_scorer` calculations (such as time-in-zone and HR-drift), keep model abstractions provider-neutral, and support future workout planning (weekly/monthly decision engines), we investigated the Intervals.icu REST API endpoints, authentication models, activity payloads, calendar events, and rate limits.

## Decision

### 1. Authentication Model
* **Chosen Approach:** Personal API Key via HTTP Basic Authentication.
* **Details:** 
  * Username: `API_KEY` (literal string)
  * Password: The user's personal API key generated from `Settings > API` on Intervals.icu.
* **Rationale:** Since ApexCoach is a single-user or self-hosted application, HTTP Basic Auth completely bypasses the complexity of maintaining a browser-based OAuth2 handshake flow, redirect URIs, token refresh loops, and client secrets while remaining fully supported and secure. `0` can be used as the athlete ID for all endpoints to denote the authenticated user.

### 2. Base URL & Data Format
* **URL:** `https://intervals.icu/api/v1/`
* **Format:** Dates use local ISO-8601 format (`YYYY-MM-DD` or `YYYY-MM-DDThh:mm:ss`). Output format is JSON.

### 3. Completed Activities (For Session Scorer)
* **Activity List Endpoint:** `GET /athlete/0/activities`
  * Example query params: `?oldest=2024-01-01&newest=2024-01-31&fields=id,name,start_date_local,type,distance,moving_time,icu_training_load`
* **Single Activity Details:** `GET /activity/{id}`
* **Per-Second Stream Endpoint:** `GET /activity/{id}/streams.json`
  * **Query Parameters:** Request explicit types via `?types=time,watts,distance,heartrate,cadence,altitude`.
  * **Response Shape:** Returns a JSON array of stream objects (e.g., `[{"type": "heartrate", "data": [...]}, {"type": "time", "data": [...]}]`). This exactly mimics Strava's `get_activity_stream()` and returns identical per-second data needed for the `session_scorer`.

### 4. Planned Workouts / Calendar Events (For Planning Engine)
To fetch workout plans for monthly and weekly decision-making, we will utilize the `events` endpoint.
* **Events Endpoint:** `GET /athlete/0/events`
  * **Query Parameters:** Date ranges can be used to pull weekly or monthly blocks: `?oldest=YYYY-MM-DD&newest=YYYY-MM-DD`.
  * **Usage:** Retrieves planned workouts on the calendar, containing target zones, workout descriptions, and expected training load (`icu_training_load`). 
* **Download Specific Workout:** `GET /athlete/0/events/{eventId}/download.zwo` (can also use `.mrc` or `.erg`) to pull the structured zone data directly if needed.

### 5. Activity/Sport Type Taxonomy Mapping
Intervals.icu heavily mimics Strava's activity types internally but groups them into stable, low-cardinality "Sport Families". These map cleanly to ApexCoach’s canonical vocabulary:

| Intervals.icu Activity Type / Sport Family | ApexCoach Canonical Vocabulary |
| :--- | :--- |
| `Run`, `VirtualRun`, `TrackRun` | `Run` |
| `Ride`, `VirtualRide`, `MountainBikeRide` | `Ride` |
| `Swim`, `OpenWaterSwim`, `PoolSwim` | `Swim` |
| `WeightTraining`, `Strength`, `Crossfit` | `WeightTraining` |
| `Yoga`, `Pilates`, `Mobility` | `Yoga` |
| *Other / Unmapped types* | Default fallback or generic mapping |

*(Note: We will key off the primary sport string, which is guaranteed to be a pascal-case enum).*

### 6. Rate Limit Handling Notes
* **Limits:** Limits for API key callers are set to **5,000 requests/day** and **2,500 requests/15 minutes**.
* **Headers:** Monitor standard `X-RateLimit-*` response headers. A `429` status code will be returned when limits are breached, accompanied by a `Retry-After` header indicating the required wait time in seconds.

## Consequences
* Unblocks ticket **F18.3 (AFK): IntervalsIcuAdapter (Mock + Real) + activity-type mapping (#92)**.
* Allows ApexCoach to support both backwards-looking scoring (Activities) and forward-looking planning (Events).
* No adapter code or client logic is written in this ADR phase; implementation will follow in subsequent tickets.
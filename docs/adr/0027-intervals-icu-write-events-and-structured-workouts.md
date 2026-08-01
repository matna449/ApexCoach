# ADR 0027: Intervals.icu Write Events & Structured Workout Upload

## Status
Proposed

## Context
PRD #111 requires ApexCoach to push structured workouts into an athlete’s Intervals.icu calendar so they can be executed on a watch or head unit. ADR-0025 confirmed the read-only side of the Intervals.icu API (GET `/athlete/0/events`, activity streams, etc.) but did not cover the write side needed to create/update calendar events and attach structured workouts. [forum.intervals](https://forum.intervals.icu/t/intervals-icu-api-integration-cookbook/80090)

This ADR documents the confirmed create/update-event endpoints, the supported structured-workout attachment mechanisms, and any remaining unknowns, following the same “confirm before building” discipline as F18.1/ADR-0025. 

## Decision

### 1. Authentication Model
- **Chosen Approach:** Same as ADR-0025: Personal API Key via HTTP Basic Authentication. 
- **Details:**
  - Username: `API_KEY` (literal string)
  - Password: The user’s personal API key from Intervals.icu Settings > API. 
- **Rationale:** ApexCoach is single-user/self-hosted; HTTP Basic avoids OAuth complexity while remaining fully supported. Athlete ID `0` can be used to denote the authenticated user. 

### 2. Base URL & Data Format
- **Base URL:** `https://intervals.icu/api/v1/` 
- **Date format:** Local ISO-8601 (`YYYY-MM-DD` or `YYYY-MM-DDThh:mm:ss`). 
- **Output format:** JSON for metadata; workout files use `.zwo`, `.mrc`, or `.erg` as appropriate. [forum.intervals](https://forum.intervals.icu/t/uploading-planned-workouts-to-intervals-icu/63624)

### 3. Write Endpoints (Create/Update Events)
- **Create Event:** `POST /api/v1/athlete/{id}/events` [forum.intervals](https://forum.intervals.icu/t/uploading-planned-workouts-to-intervals-icu/63624)
- **Update Event:** `PUT /api/v1/athlete/{id}/events/{eventId}` [forum.intervals](https://forum.intervals.icu/t/uploading-planned-workouts-to-intervals-icu/63624)
- **Bulk Upsert (optional):** `POST /api/v1/athlete/{id}/events/bulk?upsert=true` for create-or-update in batch when event IDs are not yet known client-side. 
- **Usage Pattern:**
  - Use `POST` to create a new calendar event (workout, note, etc.). [forum.intervals](https://forum.intervals.icu/t/uploading-planned-workouts-to-intervals-icu/63624)
  - Use `PUT` with the server-returned `eventId` for idempotent re-pushes/updates. [forum.intervals](https://forum.intervals.icu/t/uploading-planned-workouts-to-intervals-icu/63624)
  - Bulk upsert is an optional optimization; single-event flows should prefer `POST` then `PUT`. 

### 4. Structured Workout Attachment Mechanisms
Intervals.icu supports two primary ways to attach a structured workout to a calendar event:

#### 4.1. Upload a Workout File (Preferred for Watch-Executable Workouts)
- **Supported formats:** `.zwo` (Zwift), `.mrc` (TrainerRoad), `.erg` (generic). [forum.intervals](https://forum.intervals.icu/t/uploading-planned-workouts-to-intervals-icu/63624)
- **Mechanism:** Include the workout file content in the create/update request (multipart/form-data or equivalent, depending on client library). [forum.intervals](https://forum.intervals.icu/t/uploading-planned-workouts-to-intervals-icu/63624)
- **Effect:** The event is rendered as a structured, executable workout on compatible devices/platforms that consume Intervals.icu workouts. [forum.intervals](https://forum.intervals.icu/t/api-create-or-update-workout-without-using-description-text-syntax/124215)

#### 4.2. Native Workout Text in `description`
- **Mechanism:** Provide workout structure using Intervals-native workout text syntax in the event’s `description` field. [forum.intervals](https://forum.intervals.icu/t/api-create-or-update-workout-without-using-description-text-syntax/124215)
- **Effect:** Intervals parses the text into a structured workout internally; this can then be used by Intervals’ own integrations (e.g., Zwift) if supported. [forum.intervals](https://forum.intervals.icu/t/uploading-planned-workouts-to-intervals-icu/63624)
- **Caveat:** If only a plain text description is provided without structured syntax, the event may appear as a simple calendar note and not be assumed watch-executable. [forum.intervals](https://forum.intervals.icu/t/uploading-planned-workouts-to-intervals-icu/63624)

#### 4.3. Fallback Behavior
- If neither a structured file nor recognized workout text is provided, treat the event as a non-executable calendar item (e.g., a planned rest day, cross-training note, or generic session). [forum.intervals](https://forum.intervals.icu/t/uploading-planned-workouts-to-intervals-icu/63624)

### 5. Rate Limits & Error Modes (Write Side)
- **Documented Limits:** ADR-0025 records **5,000 requests/day** and **2,500 requests/15 minutes** for API-key callers. 
- **Write-Specific Limits:** No explicit distinction between read and write rate limits was found in public docs; assume the same limits apply unless testing shows otherwise. [forum.intervals](https://forum.intervals.icu/t/intervals-icu-api-integration-cookbook/80090)
- **Error Handling:** Monitor `X-RateLimit-*` headers and handle HTTP `429` with `Retry-After` as per ADR-0025. 

### 6. Explicit Unknowns
The following items are not fully confirmed by public documentation and should be treated as unknowns until verified (e.g., via API schema inspection or live testing):

- **Exact request-body schema** for `POST /athlete/{id}/events` and `PUT /athlete/{id}/events/{eventId}` (field names, required vs optional fields, multipart vs JSON body shapes). [forum.intervals](https://forum.intervals.icu/t/uploading-planned-workouts-to-intervals-icu/63624)
- **Whether write operations have different rate limits or quotas** than read operations. [forum.intervals](https://forum.intervals.icu/t/intervals-icu-api-integration-cookbook/80090)
- **All supported workout text syntax variants** and how strictly Intervals parses them into structured workouts vs free-form notes. [forum.intervals](https://forum.intervals.icu/t/uploading-planned-workouts-to-intervals-icu/63624)
- **Any additional scopes or permissions** beyond `CALENDAR:WRITE` (if such scopes are explicitly defined in the API). 

These unknowns must be resolved in implementation (F19.6) via:
- consulting the latest Intervals.icu API docs or OpenAPI schema, if available;
- performing targeted live tests against a sandbox/test athlete account.

## Consequences
- Unblocks **F19.6 (AFK): intervals.icu push adapter + event-id tracking + CLI push command** by defining the write-side contract and workout attachment options. [forum.intervals](https://forum.intervals.icu/t/uploading-planned-workouts-to-intervals-icu/63624)
- Provides a clear path to watch-executable structured workouts via `.zwo`/`.mrc`/`.erg` uploads. [forum.intervals](https://forum.intervals.icu/t/uploading-planned-workouts-to-intervals-icu/63624)
- Makes explicit which parts of the contract are confirmed vs unknown, preventing silent assumptions in the adapter implementation. [forum.intervals](https://forum.intervals.icu/t/uploading-planned-workouts-to-intervals-icu/63624)
- Implementation will still need to resolve the exact request-body schema and verify any write-specific rate limits before finalizing the adapter. [forum.intervals](https://forum.intervals.icu/t/uploading-planned-workouts-to-intervals-icu/63624)

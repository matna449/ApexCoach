# Apex Coach

## API Integration Contract

*WHOOP · Strava · Ollama — OAuth flows, payload contracts, mock fixtures, and failure modes*

|  |  |
|----|----|
| **Document Type** | API Integration Contract |
| **Version** | 1.0 — Initial Draft |
| **Companion Docs** | ApexCoach_PRD_v1.0 · ApexCoach_SDD_v1.0 |
| **Author** | Mattias (Primary User / Developer) |
| **APIs Covered** | WHOOP Developer API v1 · Strava API v3 · Ollama REST API |
| **Auth Method** | OAuth 2.0 Authorization Code + PKCE (WHOOP & Strava) · No auth (Ollama local) |
| **Date** | June 2026 |

## 1. Integration Overview

Apex Coach integrates three external interfaces. Each is accessed exclusively through its adapter module. No engine or service module calls an API directly.

| **API** | **Auth Type** | **Base URL** | **Rate Limit** | **Adapter Module** |
|----|----|----|----|----|
| WHOOP v1 | OAuth 2.0 + PKCE | api.prod.whoop.com/developer/v1 | 100 req/min | adapters/whoop_adapter.py |
| Strava v3 | OAuth 2.0 + PKCE | www.strava.com/api/v3 | 100 req/15min | adapters/strava_adapter.py |
| Ollama | None (local) | localhost:11434 | Unlimited | adapters/ollama_adapter.py |

> **CONTRACT RULE**
>
> All API responses are validated against Pydantic models before any downstream module receives data. A validation failure is treated the same as an API error — the system falls back to the last known good data and logs the failure.

## 2. WHOOP API

### 2.1 OAuth 2.0 Authorization Flow

WHOOP uses OAuth 2.0 Authorization Code flow with PKCE. This is a one-time browser handshake. Subsequent runs use the stored refresh token to obtain new access tokens automatically.

```
STEP 1 — DEVELOPER SETUP (one time, manual)
  Register app at: developer.whoop.com
  Obtain: WHOOP_CLIENT_ID, WHOOP_CLIENT_SECRET
  Set redirect URI: http://localhost:8080/callback

STEP 2 — AUTHORIZATION URL (one time, opens browser)
  GET https://api.prod.whoop.com/oauth/oauth2/auth
    ?response_type=code
    &client_id={WHOOP_CLIENT_ID}
    &redirect_uri=http://localhost:8080/callback
    &scope=read:recovery read:sleep read:strain read:body_measurement
    &state={random_state_token}           <- CSRF protection
    &code_challenge={pkce_challenge}       <- SHA-256 of code_verifier
    &code_challenge_method=S256

STEP 3 — TOKEN EXCHANGE (after browser redirect)
  POST https://api.prod.whoop.com/oauth/oauth2/token
  Content-Type: application/x-www-form-urlencoded
  Body:
    grant_type=authorization_code
    code={authorization_code}
    client_id={WHOOP_CLIENT_ID}
    client_secret={WHOOP_CLIENT_SECRET}
    redirect_uri=http://localhost:8080/callback
    code_verifier={pkce_verifier}

STEP 4 — TOKEN RESPONSE
  {
    "access_token":  "eyJhbGci...",        <- expires in 3600s
    "refresh_token": "eyJhbGci...",        <- long-lived, store securely
    "expires_in":    3600,
    "token_type":    "Bearer"
  }

STEP 5 — TOKEN REFRESH (automatic, every run)
  POST https://api.prod.whoop.com/oauth/oauth2/token
  Body:
    grant_type=refresh_token
    refresh_token={stored_refresh_token}
    client_id={WHOOP_CLIENT_ID}
    client_secret={WHOOP_CLIENT_SECRET}
```

> **SECURITY NOTE**
>
> Tokens are stored in the SQLite database (table: oauth_tokens), encrypted at rest using Fernet symmetric encryption. The encryption key is derived via PBKDF2HMAC from a dedicated APEX_ENCRYPTION_KEY (see SDD §6.3), not from either provider's OAuth client secret — see docs/adr/0005. Never store raw tokens in .env or plaintext files.

### 2.2 Endpoint: GET /v1/recovery

Fetches the most recent recovery record. Called once per morning run. Returns recovery score, HRV, RHR, and sleep performance for the latest completed sleep cycle.

|  |  |
|----|----|
| **Endpoint** | GET /v1/recovery |
| **Auth Header** | Authorization: Bearer {access_token} |
| **Query Params** | limit=1 (fetch latest only) |
| **Adapter Method** | whoop_adapter.get_latest_recovery() -\> WhoopRecovery — internal only, see §2.5 / docs/adr/0011 |

#### Mock Payload — GET /v1/recovery

```
{
  "records": [
    {
      "cycle_id":         98234871,
      "sleep_id":         112847293,
      "user_id":          18473621,
      "created_at":       "2026-06-23T06:14:22.000Z",
      "updated_at":       "2026-06-23T06:14:22.000Z",
      "score_state":      "SCORED",
      "score": {
        "user_calibrating":         false,
        "recovery_score":           62.0,      <- 0-100. Primary decision input.
        "resting_heart_rate":       48.0,      <- bpm. Used for zone calculation.
        "hrv_rmssd_milli":          71.4,      <- ms. HRV signal.
        "spo2_percentage":          96.2,
        "skin_temp_celsius":        34.1
      }
    }
  ],
  "next_token": null
}
```

#### Pydantic Model — WhoopRecovery

```
class WhoopRecoveryScore(BaseModel):
    recovery_score:     float          # 0.0-100.0
    resting_heart_rate: float          # bpm
    hrv_rmssd_milli:    float          # milliseconds
    spo2_percentage:    float | None = None
    skin_temp_celsius:  float | None = None

class WhoopRecovery(BaseModel):
    cycle_id:    int
    created_at:  datetime
    score_state: Literal['SCORED', 'PENDING_SCORE', 'UNSCORABLE']
    score:       WhoopRecoveryScore | None = None

    @validator('score_state')
    def must_be_scored(cls, v):
        if v != 'SCORED':
            raise ValueError(f'Recovery not yet scored: {v}')
        return v
```

### 2.3 Endpoint: GET /v1/cycle

Fetches the current day's strain cycle. Called after each session to capture accumulated strain. Also provides the day's overall strain context for the weekly engine.

|  |  |
|----|----|
| **Endpoint** | GET /v1/cycle |
| **Auth Header** | Authorization: Bearer {access_token} |
| **Query Params** | limit=1 |
| **Adapter Method** | whoop_adapter.get_latest_cycle() -\> WhoopCycle — internal only, see §2.5 / docs/adr/0011 |

#### Mock Payload — GET /v1/cycle

```
{
  "records": [
    {
      "id":           102938471,
      "user_id":      18473621,
      "created_at":   "2026-06-23T04:30:00.000Z",
      "updated_at":   "2026-06-23T14:22:00.000Z",
      "start":        "2026-06-23T04:30:00.000Z",
      "end":          null,               <- null if cycle still in progress
      "timezone_offset": "+02:00",
      "score_state":  "SCORED",
      "score": {
        "strain":              8.4,       <- 0-21. Day strain accumulated so far.
        "kilojoule":           1842.0,
        "average_heart_rate":  72,
        "max_heart_rate":      164
      }
    }
  ],
  "next_token": null
}
```

```
class WhoopCycleScore(BaseModel):
    strain:             float          # 0.0-21.0. Day strain accumulated so far.
    kilojoule:          float
    average_heart_rate: int
    max_heart_rate:     int

class WhoopCycle(BaseModel):
    id:          int
    created_at:  datetime
    score_state: Literal['SCORED', 'PENDING_SCORE', 'UNSCORABLE']
    score:       WhoopCycleScore | None = None

    @validator('score_state')
    def must_be_scored(cls, v):
        if v != 'SCORED':
            raise ValueError(f'Cycle not yet scored: {v}')
        return v
```

### 2.4 Endpoint: GET /v1/activity/sleep

Fetches the latest sleep record for sleep stage breakdown and total sleep hours. Used as a supplementary input to the daily engine and stored in daily_metrics.

#### Mock Payload — GET /v1/activity/sleep

```
{
  "records": [
    {
      "id":           84729301,
      "created_at":   "2026-06-23T06:14:00.000Z",
      "start":        "2026-06-22T22:18:00.000Z",
      "end":          "2026-06-23T06:08:00.000Z",
      "score_state":  "SCORED",
      "score": {
        "sleep_performance_percentage": 81.0,
        "sleep_needed": {
          "baseline_milli":             27360000,  <- ~7.6 hrs baseline need
          "need_from_strain_milli":     2400000,   <- additional from yesterday
          "need_from_recent_nap_milli": 0
        },
        "sleep_debt_milli": 0,
        "stage_summary": {
          "total_in_bed_time_milli":    28200000,  <- 7h 50m
          "total_awake_time_milli":     1620000,
          "total_light_sleep_milli":    12420000,
          "total_slow_wave_sleep_milli":5040000,  <- deep sleep
          "total_rem_sleep_milli":      8280000,
          "sleep_cycle_count":          4,
          "disturbance_count":          3
        }
      }
    }
  ]
}
```

```
class WhoopSleepStageSummary(BaseModel):
    total_in_bed_time_milli: int
    total_awake_time_milli:  int

class WhoopSleepScore(BaseModel):
    sleep_performance_percentage: float
    stage_summary:                WhoopSleepStageSummary

    @property
    def total_sleep_hours(self) -> float:
        asleep_milli = (self.stage_summary.total_in_bed_time_milli
                         - self.stage_summary.total_awake_time_milli)
        return asleep_milli / 1000 / 60 / 60

class WhoopSleep(BaseModel):
    id:          int
    created_at:  datetime
    score_state: Literal['SCORED', 'PENDING_SCORE', 'UNSCORABLE']
    score:       WhoopSleepScore | None = None

    @validator('score_state')
    def must_be_scored(cls, v):
        if v != 'SCORED':
            raise ValueError(f'Sleep not yet scored: {v}')
        return v
```

### 2.5 Combined Model — WhoopDailyPayload

whoop_adapter's public method combines all 3 endpoints above into one typed payload per day — see docs/adr/0011. The per-endpoint methods (get_latest_recovery, get_latest_cycle, get_latest_sleep) are internal; callers use get_daily_payload() only.

#### Pydantic Model — WhoopDailyPayload

```
class WhoopDailyPayload(BaseModel):
    date:                str            # ISO 8601 date this payload covers
    recovery:            WhoopRecovery
    cycle:               WhoopCycle
    sleep:               WhoopSleep

    @property
    def whoop_recovery_pct(self) -> float | None:
        return self.recovery.score.recovery_score if self.recovery.score else None

    @property
    def whoop_hrv_ms(self) -> float | None:
        return self.recovery.score.hrv_rmssd_milli if self.recovery.score else None

    @property
    def whoop_rhr_bpm(self) -> float | None:
        return self.recovery.score.resting_heart_rate if self.recovery.score else None

    @property
    def whoop_strain(self) -> float | None:
        return self.cycle.score.strain if self.cycle.score else None

    @property
    def whoop_sleep_hours(self) -> float | None:
        return self.sleep.score.total_sleep_hours if self.sleep.score else None
```

## 3. Strava API

### 3.1 OAuth 2.0 Authorization Flow

Strava uses OAuth 2.0 Authorization Code flow. The access token expires after 6 hours. The refresh token is long-lived and rotates on each refresh — always store the new token immediately.

```
STEP 1 — DEVELOPER SETUP (one time, manual)
  Register app at: strava.com/settings/api
  Set Authorization Callback Domain: localhost
  Obtain: STRAVA_CLIENT_ID, STRAVA_CLIENT_SECRET

STEP 2 — AUTHORIZATION URL (one time, opens browser)
  GET https://www.strava.com/oauth/authorize
    ?client_id={STRAVA_CLIENT_ID}
    &redirect_uri=http://localhost:8080/callback/strava
    &response_type=code
    &approval_prompt=auto
    &scope=read,activity:read_all

STEP 3 — TOKEN EXCHANGE
  POST https://www.strava.com/oauth/token
  Body (form-encoded):
    client_id={STRAVA_CLIENT_ID}
    client_secret={STRAVA_CLIENT_SECRET}
    code={authorization_code}
    grant_type=authorization_code

STEP 4 — TOKEN RESPONSE
  {
    "token_type":     "Bearer",
    "expires_at":     1750798422,   <- Unix timestamp. Check before each call.
    "expires_in":     21600,        <- 6 hours
    "refresh_token":  "fc5b...",    <- Rotates on each refresh. Always store new.
    "access_token":   "a4b3...",
    "athlete":        { "id": 9182736, ... }
  }

STEP 5 — TOKEN REFRESH (automatic, every 6 hours)
  POST https://www.strava.com/oauth/token
  Body:
    client_id={STRAVA_CLIENT_ID}
    client_secret={STRAVA_CLIENT_SECRET}
    grant_type=refresh_token
    refresh_token={stored_refresh_token}

CRITICAL: Strava refresh tokens rotate. Every refresh response contains a NEW
refresh_token. Always overwrite the stored token immediately.
```

### 3.2 Endpoint: GET /v3/athlete/activities

Lists the athlete's recent activities. Called on each sync to detect new sessions since the last stored Strava ID. Uses the after parameter to fetch only new activities — never re-fetches what is already stored.

|  |  |
|----|----|
| **Endpoint** | GET /v3/athlete/activities |
| **Auth Header** | Authorization: Bearer {access_token} |
| **Query Params** | after={last_sync_unix_ts}&per_page=30&page=1 |
| **Adapter Method** | strava_adapter.get_new_activities(since_ts) -\> list\[StravaActivity\] |
| **Deduplication** | strava_id is UNIQUE in activities table. INSERT OR IGNORE on sync. |

#### Mock Payload — Single Activity

```
{
  "id":                    12748392017,
  "name":                  "Tuesday Threshold - Track Session",
  "type":                  "Run",
  "sport_type":            "Run",
  "start_date":            "2026-06-23T06:30:00Z",
  "start_date_local":      "2026-06-23T08:30:00+0200",
  "timezone":              "(GMT+02:00) Europe/Stockholm",
  "elapsed_time":          3247,         <- seconds
  "moving_time":           3102,
  "distance":              9843.2,       <- metres
  "total_elevation_gain":  84.0,         <- metres. Key input for load calculation.
  "average_speed":         3.173,        <- m/s
  "max_speed":             4.891,
  "average_heartrate":     161.4,        <- bpm. Zone validation.
  "max_heartrate":         178.0,
  "has_heartrate":         true,
  "device_name":           "Coros PACE 3",
  "splits_metric": [
    {
      "distance":           1000.5,
      "elapsed_time":       272,
      "elevation_difference": 3.2,
      "moving_time":        268,
      "split":              1,
      "average_speed":      3.731,
      "average_heartrate":  154.2,
      "average_grade_adjusted_speed": 3.612
    }
    // ... one object per km split
  ]
}
```

#### Pydantic Model — StravaActivity

```
class StravaSplit(BaseModel):
    split:                        int
    distance:                     float
    elapsed_time:                 int
    elevation_difference:         float
    average_speed:                float
    average_heartrate:            float | None = None
    average_grade_adjusted_speed: float | None = None

class StravaActivity(BaseModel):
    id:                   int
    name:                 str
    type:                 str
    start_date:           datetime
    elapsed_time:         int              # seconds
    distance:             float            # metres
    total_elevation_gain: float            # metres
    average_speed:        float            # m/s
    average_heartrate:    float | None = None
    max_heartrate:        float | None = None
    has_heartrate:        bool = False
    splits_metric:        list[StravaSplit] = []

    @property
    def pace_sec_per_km(self) -> float | None:
        if self.average_speed and self.average_speed > 0:
            return 1000 / self.average_speed
        return None

    @property
    def grade_pct(self) -> float:
        if self.distance > 0:
            return (self.total_elevation_gain / self.distance) * 100
        return 0.0
```

### 3.3 Endpoint: GET /v3/activities/{id}/streams

Fetches the raw HR data stream for a specific activity. Used for detailed time-in-zone analysis. Only called when has_heartrate is true. Result is cached — never re-fetched for a completed activity.

|  |  |
|----|----|
| **Endpoint** | GET /v3/activities/{id}/streams |
| **Query Params** | keys=heartrate,time,distance&key_by_type=true&series_type=distance |
| **Rate Cost** | 1 request per activity. Always cache result in strava_raw_json column. |
| **Adapter Method** | strava_adapter.get_activity_stream(activity_id) -\> StravaStream \| None |

#### Mock Payload — Activity Streams (abbreviated)

```
{
  "heartrate": {
    "data":        [142, 148, 153, 159, 163, 168, 171, ...],  <- bpm per second
    "series_type": "distance",
    "original_size": 3102,
    "resolution":  "high"
  },
  "time": {
    "data":        [0, 1, 2, 3, 4, 5, ...],                   <- seconds elapsed
    "series_type": "distance",
    "original_size": 3102
  },
  "distance": {
    "data":        [0.0, 1.8, 3.6, 5.4, ...],                 <- metres
    "series_type": "distance",
    "original_size": 3102
  }
}

Usage: zip(heartrate.data, time.data) -> per-second HR timeseries
       Count seconds where HR falls within zone boundaries -> time_in_zone_pct
```

## 4. Ollama Local API

### 4.1 Overview

Ollama runs as a background service on localhost:11434. No authentication required. The adapter sends a structured JSON context assembled by the orchestrator and receives a natural language explanation. The model never receives raw API data — only pre-processed structured summaries.

|  |  |
|----|----|
| **Service** | Ollama (local background process — ollama serve) |
| **Base URL** | http://localhost:11434 |
| **Model** | llama3.1:8b (pull with: ollama pull llama3.1:8b) |
| **Context window** | 128k tokens. Full structured input comfortably fits. |
| **Adapter Method** | ollama_adapter.explain(decision_context: dict) -\> ExplanationResult (see docs/adr/0010) |
| **Hardware fit** | ~6 GB VRAM for 8B model. 24 GB M4 Pro has ample headroom. |

### 4.2 Endpoint: POST /api/chat

```
POST http://localhost:11434/api/chat
Content-Type: application/json

{
  "model":  "llama3.1:8b",
  "stream": false,
  "options": {
    "temperature": 0.3,   <- Low. Consistent, factual explanations.
    "top_p": 0.9
  },
  "messages": [
    {
      "role":    "system",
      "content": "You are Apex Coach, a sports science assistant for an endurance
                  athlete following a pyramidal training model. You receive structured
                  JSON with biometric data, the training plan, and the decision made
                  by the coaching engine. Explain the decision in 3-5 sentences.
                  Cite the specific metrics that drove it. Do not add anything the
                  engine has not already decided. Speak directly to the athlete."
    },
    {
      "role":    "user",
      "content": "{...structured decision context JSON — see Section 4.3...}"
    }
  ]
}
```

### 4.3 Structured Decision Context — Input Contract

This is the exact JSON structure the orchestrator assembles and passes to the Ollama adapter on every run.

```
{
  "date":             "2026-06-23",
  "athlete_context": {
    "training_phase": "BUILD",
    "race_date":      "2026-09-14",
    "weeks_to_race":  12
  },
  "todays_plan": {
    "scheduled_session":  "Threshold",
    "session_description":"6 x 1km at Zone 4 HR (163-178 bpm), 90s rest"
  },
  "biometrics": {
    "whoop_recovery_pct": 62.0,
    "whoop_hrv_ms":       71.4,
    "hrv_30d_avg_ms":     78.2,
    "hrv_delta_ms":      -6.8,   <- below 30d avg. Negative signal.
    "hrv_signal":        "NEGATIVE",
    "whoop_rhr_bpm":      48,
    "whoop_strain_so_far":2.1
  },
  "morning_check": {
    "muscle_soreness":    3,     <- 1-5. Moderate.
    "subjective_energy":  3,
    "sleep_quality_felt": 3,
    "adaptive_checks": {
      "left_achilles_pain":1,    <- from yesterday long Zone 2
      "right_knee_pain":   2
    }
  },
  "decision": {
    "recommendation": "MODIFY",
    "rationale": {
      "recovery_zone":  "YELLOW (62%)",
      "hrv_signal":     "NEGATIVE (-6.8ms below 30d avg)",
      "soreness_level": "MODERATE (3/5)",
      "rule_applied":   "YELLOW + NEGATIVE HRV: extend warm-up, monitor HR
                         in first interval, abort to Zone 2 if ceiling not
                         reached by interval 2"
    }
  },
  "weekly_context": {
    "week_status":        "ON_TRACK",
    "load_actual":        142.3,
    "load_target":        280.0,
    "sessions_remaining": ["Threshold (today)", "Zone2-Long", "Strength"]
  }
}
```

#### Example Ollama Response

```
Your recovery is sitting at 62% (Yellow) with HRV tracking 6.8ms below your
30-day average — a meaningful suppression signal, not noise. Combined with
moderate muscle soreness, the engine has flagged a MODIFY rather than a full GO.
The session is still on: extend warm-up to 20 minutes and run the first two
intervals at the lower end of Zone 4 (163-166 bpm). If HR isn't reaching 163
by interval 2, cut the session and convert to Zone 2 — you're on track for the
week so protecting Thursday's load matters more than forcing today.
```

## 5. Token Storage Schema

OAuth tokens for WHOOP and Strava are stored in the oauth_tokens table. Separate from the main schema defined in the SDD.

| **Column** | **Type** | **Key** | **Description** |
|----|----|----|----|
| id | TEXT | PK | UUID v4. |
| provider | TEXT | UQ | Enum: WHOOP / STRAVA. One row per provider. |
| access_token | TEXT |  | Fernet-encrypted access token. |
| refresh_token | TEXT |  | Fernet-encrypted. Never expires (WHOOP). Rotates on each use (Strava). |
| expires_at | TEXT |  | ISO 8601 UTC. Adapter checks before each call. Refreshes if expiry \< 60 seconds away. |
| scope | TEXT |  | Space-separated scopes granted. Stored for audit. |
| updated_at | TEXT |  | UTC timestamp. Updated on every token refresh. |

## 6. Failure Mode Handling

### 6.1 WHOOP API Failures

The morning run depends on WHOOP data. If the API is unavailable the system must still produce a usable recommendation — never a crash or silent failure.

| **Code / Condition** | **Meaning** | **System Action** | **Severity** |
|----|----|----|:--:|
| **401** | Token expired or revoked | Attempt token refresh. If refresh fails, prompt athlete to re-authorise via CLI. Block daily run until resolved. | **CRITICAL** |
| **429** | Rate limit hit | Retry after 60 seconds (max 3 retries). If still failing, use last stored daily_metrics row and flag recommendation as STALE_DATA. | **WARN** |
| **500 / 503** | WHOOP server error | Retry once after 30 seconds. If still failing, fall back to last known daily_metrics. Prepend \[DATA MAY BE STALE\] to Ollama explanation. | **WARN** |
| **score_state != SCORED** | Sleep not yet scored | If PENDING_SCORE, wait 10 minutes and retry once. If still pending, proceed with previous day HRV and RHR and note this in explanation. | **WARN** |
| **Network timeout** | DNS / connection failure | Treat as server error. Use last stored data. Log full exception. Notify athlete via CLI output. | **WARN** |
| **Validation error** | API schema changed | Log raw response and validation error. Do not crash. Alert athlete that a WHOOP API update may have occurred — manual check required. | **CRITICAL** |

### 6.2 Strava API Failures

Strava sync is not time-critical. A sync failure queues the score for the next run. The daily engine does not depend on Strava data for the morning recommendation.

| **Code / Condition** | **Meaning** | **System Action** | **Severity** |
|----|----|----|:--:|
| **401** | Token expired | Refresh token. Strava tokens expire in 6 hours. Always check expires_at before calling. | **CRITICAL** |
| **403** | Scope not granted | Log and alert. Athlete must re-authorise with activity:read_all scope. Provide re-auth URL in CLI output. | **CRITICAL** |
| **429** | Rate limit (100/15min) | Back off and retry after 15 minutes. Log the backoff. All sync operations are batched to minimise total request count. | **WARN** |
| **404** | Activity not found | Activity may have been deleted from Strava. Mark record as STRAVA_DELETED in DB. Do not retry. | **INFO** |
| **No HR data** | has_heartrate = false | Score session without HR components. time_in_zone_score = null. Flag as NO_HR_DATA. Request manual RPE input from athlete. | **WARN** |
| **Sync gap \> 7d** | Long gap detected | On gap detection, perform full backfill for the missing window using paginated after/before parameters. | **INFO** |

### 6.3 Ollama Failures

Ollama is a local process. Failures are typically startup-related. A decision is always generated before Ollama is called — the explanation layer is never on the critical path.

| **Code / Condition** | **Meaning** | **System Action** | **Severity** |
|----|----|----|:--:|
| **Connection refused** | Ollama not running | Output structured decision JSON directly without explanation. Print: \[Ollama offline -- start with: ollama serve\] | **WARN** |
| **Model not found** | Model not pulled | Print: \[Run: ollama pull llama3.1:8b to enable explanations\]. Output raw decision to CLI. | **WARN** |
| **Timeout \> 30s** | Model overloaded | Abandon request. Output raw decision. Log timeout. M4 Pro should not timeout on 8B model -- investigate if this recurs. | **WARN** |
| **Malformed output** | Model ignored format | Wrap Ollama call in try/except. If explanation parsing fails, output raw model text as-is rather than crashing. | **INFO** |

> **DESIGN RULE — GRACEFUL DEGRADATION**
>
> Every failure mode above results in a usable output, not a crash or silence. The athlete always receives either: (a) full recommendation with explanation, (b) full recommendation without explanation, or (c) stale-data recommendation with a clear freshness warning. A silent failure that produces no output is never acceptable.

## 7. Rate Limit Strategy

### 7.1 Request Budget Per Day

Apex Coach is a low-frequency application. A single morning run makes at most 4 API calls. A post-session sync adds at most 3 more. Daily total is well within both APIs' limits.

| **Operation** | **WHOOP Calls** | **Strava Calls** | **Notes** |
|----|----|----|----|
| Morning run (daily engine) | 3 | 0 | GET /recovery, /cycle, /sleep |
| Token refresh (if needed) | 1 | 1 | One per provider if token expired |
| Post-session sync | 0 | 2 | GET /activities (list) + GET /activities/{id}/streams |
| Weekly summary | 0 | 0 | Reads from SQLite only. No API calls. |
| Monthly summary | 0 | 0 | Reads from SQLite only. No API calls. |
| TOTAL — typical day (1 session) | 4 | 3 | Well within WHOOP (100/min) and Strava (100/15min) limits. |

### 7.2 Caching Rules

- WHOOP recovery payload: cached per date. Never fetched twice for the same calendar date.

- Strava activity list: after parameter ensures only new activities are fetched on each sync.

- Strava activity stream: cached in strava_raw_json column on first fetch. Never re-fetched for a completed activity.

- All cache reads go through the repository layer. No module hits the API if a valid local record exists for the requested date or activity.

## 8. Document Control

| **Version** | **Date** | **Changes** | **Author** |
|----|----|----|----|
| 1.0 | June 2026 | Initial draft. WHOOP, Strava, and Ollama contracts fully specified with mock payloads, Pydantic models, failure modes, and rate limit strategy. | Mattias |

*Next document: Logic & Algorithm Specification — decision tree matrix, weekly adaptation state machine, session scoring detail, and monthly load forecasting.*

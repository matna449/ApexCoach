# Apex Coach

## Logic & Algorithm Specification

*Decision trees, state machines, scoring algorithms, and load forecasting logic*

|  |  |
|----|----|
| **Document Type** | Logic & Algorithm Specification |
| **Version** | 1.0 — Initial Draft |
| **Companion Docs** | PRD v1.0 · SDD v1.0 · API Integration Contract v1.0 |
| **Author** | Mattias (Primary User / Developer) |
| **Scope** | Daily engine · Weekly engine · Monthly engine · Session scorer · Zone calculator · Load calculator · Health check · Morning protocol |
| **Date** | June 2026 |

## 1. Document Purpose & Logic Hierarchy

This document is the authoritative specification for all conditional logic, scoring algorithms, and state machines in Apex Coach. Any implementation that deviates from this specification must update this document first. The LLM explanation layer is explicitly excluded — it receives outputs from this logic and explains them, but it does not produce them.

The three engines operate in a strict authority hierarchy:

```
MONTHLY ENGINE  (highest authority)
  |-- Sets load targets and periodisation phase for the month
  |-- Forecasts whether the athlete is on track for their race / goal
  |-- Can trigger a forced RECOVERY WEEK regardless of weekly plan
  v
WEEKLY ENGINE   (middle authority)
  |-- Adapts the weekly session plan after each skip or completion
  |-- Decides whether to RESCHEDULE or WRITE OFF a missed key session
  |-- Checks all decisions against the monthly load target
  v
DAILY ENGINE    (execution authority)
  |-- Produces GO / MODIFY / MODALITY_SWAP / ABORT for today's session
  |-- Takes today's WHOOP data, morning check, and weekly plan as inputs
  |-- Never overrides a monthly-triggered RECOVERY WEEK
```

> **IMMUTABILITY RULE**
>
> No engine modifies another engine's output. The monthly engine writes to monthly_targets. The weekly engine writes to weekly_plans. The daily engine writes to decisions. Read paths flow downward (daily reads weekly, weekly reads monthly). Write paths never cross.

## 2. Input Classification & Thresholds

All inputs are classified into discrete bands before entering any decision logic. Raw floats never enter the decision tree — only their classified equivalents. This makes the logic auditable and the tests exhaustive.

### 2.1 WHOOP Recovery Classification

| **Raw Score** | **Band** | **Enum Value** | **Interpretation** |
|----|----|----|----|
| 67 – 100 | Green | RECOVERY_GREEN | Nervous system well-recovered. Full training stimulus appropriate. |
| 34 – 66 | Yellow | RECOVERY_YELLOW | Moderate suppression. Context-dependent — check HRV delta and soreness. |
| 0 – 33 | Red | RECOVERY_RED | Significant systemic suppression. High-intensity contraindicated. |

### 2.2 HRV Delta Signal Classification

HRV delta is today's HRV minus the rolling 30-day average. This contextualises a single reading — a 70ms HRV means different things depending on whether your average is 65ms or 85ms.

| **Delta (ms)** | **Band** | **Enum Value** | **Effect on Decision** |
|----|----|----|----|
| \> +5 | Positive | HRV_POSITIVE | Confirms GREEN. Strengthens YELLOW towards GO. |
| -5 to +5 | Neutral | HRV_NEUTRAL | No adjustment. Recovery band is authoritative. |
| -5 to -10 | Negative | HRV_NEGATIVE | YELLOW -\> MODIFY. RED -\> ABORT. Confirms suppression. |
| \< -10 | Strong Neg | HRV_STRONG_NEG | YELLOW -\> treated as RED (ABORT key sessions). RED -\> ABORT + flag recovery week candidate. |

### 2.3 Muscle Soreness Classification

| **Raw Score** | **Band** | **Enum Value** | **Effect on Decision** |
|----|----|----|----|
| 1 | None | SORENESS_NONE | No adjustment. |
| 2 | Mild | SORENESS_MILD | No adjustment to plan. Note logged. |
| 3 | Moderate | SORENESS_MODERATE | Key sessions: flag for awareness. Zone 2 run: flag for potential modality swap. |
| 4 | High | SORENESS_HIGH | Key sessions: MODIFY (reduce volume). Zone 2 run: MODALITY_SWAP to cycling or swimming. |
| 5 | Severe | SORENESS_SEVERE | Any impact session: ABORT. Non-impact (cycling, swimming, yoga): GO with HR cap at Zone 2 ceiling. |

### 2.4 Session Type Classification

| **Session Label** | **Priority Tier** | **Target HR Zone** | **Description** |
|----|----|----|----|
| HIIT | KEY | Zone 5 | Norwegian 4x4 or equivalent. Cannot be trivially rescheduled. |
| Threshold | KEY | Zone 4 | Sustained effort at lactate threshold. Second-highest priority. |
| Zone2_Long | BASE | Zone 2 | Long aerobic run. Builds mitochondrial density. 70-90 min+. |
| Zone2_Short | BASE | Zone 2 | Shorter aerobic run. 40-60 min. Higher swap tolerance. |
| Strength | SUPPORT | N/A | Gym session. Load measured by RPE and volume, not HR. |
| Recovery | RECOVERY | Zone 1 | Active recovery. Yoga, foam rolling, easy walk. Non-negotiable cap. |
| Rest | RECOVERY | None | Full rest day. No structured activity. Passive recovery only. |

## 3. Daily Decision Engine

### 3.1 Full Decision Tree — Key Sessions (HIIT & Threshold)

Key sessions are the highest-priority training stimuli in pyramidal periodisation. The decision logic prioritises completing them while avoiding injury from forced high-intensity on a suppressed nervous system.

```
INPUT:  recovery_band, hrv_signal, soreness_band, session_type (KEY)
OUTPUT: recommendation (GO | MODIFY | ABORT), modifier_instructions

IF recovery_band == RECOVERY_GREEN:
  IF soreness_band in [NONE, MILD, MODERATE]:
    -> GO
    -> modifier: none
  IF soreness_band == SORENESS_HIGH:
    -> MODIFY
    -> modifier: 'Reduce interval count by 1. Monitor form carefully.'
  IF soreness_band == SORENESS_SEVERE:
    -> ABORT
    -> modifier: 'Swap to Zone2_Short or Recovery. Do not attempt impact.'

IF recovery_band == RECOVERY_YELLOW:
  IF hrv_signal in [HRV_POSITIVE, HRV_NEUTRAL]:
    IF soreness_band in [NONE, MILD]:
      -> GO
      -> modifier: 'HRV neutral/positive supports green-equivalent execution.'
    IF soreness_band == SORENESS_MODERATE:
      -> MODIFY
      -> modifier: 'Extend warm-up to 20 min. Cut 1 interval if HR slow to rise.'
    IF soreness_band in [HIGH, SEVERE]:
      -> ABORT
      -> modifier: 'Systemic + local fatigue combined. Protect weekly load.'
  IF hrv_signal == HRV_NEGATIVE:
    IF soreness_band in [NONE, MILD]:
      -> MODIFY
      -> modifier: 'Extend warm-up 20 min. Abort to Zone2 if HR ceiling not
                    reached by interval 2. Watch for cardiac drift.'
    IF soreness_band in [MODERATE, HIGH, SEVERE]:
      -> ABORT
      -> modifier: 'HRV negative + soreness elevated. High injury risk.'
  IF hrv_signal == HRV_STRONG_NEG:
    -> ABORT  (regardless of soreness)
    -> modifier: 'Strong HRV suppression overrides yellow band. Treat as red.'

IF recovery_band == RECOVERY_RED:
  -> ABORT  (regardless of HRV and soreness)
  -> modifier: 'Red nervous system. No high-intensity. Swap to Zone2 or Rest.'
  -> flag: weekly_engine.check_recovery_week_trigger()
```

### 3.2 Full Decision Tree — Zone 2 Sessions

Zone 2 sessions have higher tolerance for degraded recovery because they do not stress the nervous system significantly. The main risk is mechanical — running on sore legs adds injury risk even when WHOOP shows green.

```
INPUT:  recovery_band, hrv_signal, soreness_band, session_type (Zone2_Long | Zone2_Short)
OUTPUT: recommendation (GO | MODIFY | MODALITY_SWAP | ABORT), modifier_instructions

IF recovery_band == RECOVERY_GREEN:
  IF soreness_band in [NONE, MILD]:
    -> GO
  IF soreness_band == SORENESS_MODERATE:
    -> GO  with modifier: 'Monitor legs. Abort if form breaks down.'
  IF soreness_band == SORENESS_HIGH:
    -> MODALITY_SWAP
    -> modifier: 'WHOOP green but legs need non-impact. Swap to cycling
                  or pool running at same Zone 2 HR ceiling.'
  IF soreness_band == SORENESS_SEVERE:
    -> ABORT
    -> modifier: 'Severe soreness. Recovery session only (yoga / foam roll).'

IF recovery_band == RECOVERY_YELLOW:
  IF soreness_band in [NONE, MILD]:
    -> GO  with modifier: 'Cap HR at Zone 2 ceiling. No drift upward.'
  IF soreness_band in [MODERATE, HIGH]:
    -> MODALITY_SWAP
    -> modifier: 'Yellow + soreness. Cycling or swimming Zone 2.
                  Strict cap: HR must not exceed Zone 2 ceiling.'
  IF soreness_band == SORENESS_SEVERE:
    -> ABORT

IF recovery_band == RECOVERY_RED:
  IF session_type == Zone2_Short:
    -> MODIFY
    -> modifier: 'Strict HR cap at 70% of Zone 2 ceiling. Max 30 min.
                  Do not allow drift. Consider yoga/foam roll instead.'
  IF session_type == Zone2_Long:
    -> ABORT
    -> modifier: 'Long Zone 2 on red creates more fatigue than adaptation.
                  Replace with 20-30 min active recovery or full rest.'
```

### 3.3 Full Decision Tree — Strength Sessions

Strength sessions are neural-demand activities. They carry injury risk on high soreness days but are less dependent on cardiovascular recovery than running sessions. WHOOP recovery is less predictive here — soreness and subjective energy take precedence.

```
INPUT:  recovery_band, soreness_band, subjective_energy, adaptive_health_checks
OUTPUT: recommendation (GO | MODIFY | ABORT)

IF any adaptive_health_check >= 4 (significant joint pain):
  -> ABORT  (regardless of all other inputs)
  -> modifier: 'Joint pain flag. Do not load the flagged structure. Consult
                if persists > 3 days.'

ELSE:
  IF recovery_band == RECOVERY_GREEN AND soreness_band in [NONE, MILD]:
    -> GO
  IF recovery_band == RECOVERY_GREEN AND soreness_band == SORENESS_MODERATE:
    -> MODIFY
    -> modifier: 'Reduce working weight by 10-15%. Focus on movement quality.'
  IF recovery_band == RECOVERY_YELLOW AND soreness_band in [NONE, MILD]:
    -> GO  (strength less dependent on WHOOP signal)
  IF recovery_band == RECOVERY_YELLOW AND soreness_band in [MODERATE, HIGH]:
    -> MODIFY
    -> modifier: 'Drop to 70% of planned volume. Technique focus session.'
  IF recovery_band == RECOVERY_RED OR soreness_band == SORENESS_SEVERE:
    -> ABORT
    -> modifier: 'High systemic or mechanical fatigue. Replace with mobility work.'
```

### 3.4 Full Decision Tree — Recovery & Rest Days

Recovery days are not optional. The daily engine enforces a ceiling on recovery sessions — it can downgrade activity but cannot upgrade a rest day to a training day. The 'Monday Yellow' scenario from the original brief is handled here.

```
INPUT:  recovery_band, hrv_signal, tomorrow_session_type
OUTPUT: recommendation (always a RECOVERY action), recovery_protocol

NOTE: A rest day cannot be upgraded to a training day regardless of recovery score.
      The daily engine can only select the type and intensity of recovery activity.

IF recovery_band == RECOVERY_GREEN:
  -> GO (active recovery)
  -> protocol: 'Standard: 20-30 min yoga or foam rolling.',
  -> pre_activation: IF tomorrow_session_type == KEY:
       'Add 10 min CNS primer: drills, strides, activation. Prime without fatigue.'

IF recovery_band == RECOVERY_YELLOW:
  IF hrv_signal in [HRV_NEUTRAL, HRV_POSITIVE]:
    -> protocol: 'Parasympathetic flush: 20-30 min yoga + foam rolling.
                  Nutrition: +10% carbohydrate intake. Sleep gate: +45 min earlier.
                  Goal: convert yellow to green by tomorrow.'
  IF hrv_signal in [HRV_NEGATIVE, HRV_STRONG_NEG]:
    -> protocol: 'Nervous system reboot: NSDR protocol (20 min) or Yoga Nidra.
                  No physical activity beyond gentle walking.
                  Nutrition: prioritise protein + anti-inflammatory foods.
                  Sleep gate: +60 min earlier than usual.'

IF recovery_band == RECOVERY_RED:
  -> protocol: 'Full passive rest. No structured activity.
                Prioritise sleep, hydration, and nutrition.
                Flag to weekly engine: consecutive red days trigger recovery week.'
```

### 3.5 Complete Decision Matrix

The following matrix maps every permutation of Recovery Band x HRV Signal x Soreness Band for KEY sessions. This matrix is the test oracle — every cell must have a passing unit test.

#### KEY: G = GO M = MODIFY S = MODALITY SWAP A = ABORT

|  |  |  |  |  |  |  |
|----|:--:|:--:|:--:|:--:|:--:|----|
| **Recovery / HRV / Soreness** | **None/Mild** | **Moderate** | **High** | **Severe** | **Any Joint\>=4** |  |
| **GREEN + Positive HRV** | **GO** | **GO** | **MODIFY** | **ABORT** | **ABORT** |  |
| **GREEN + Neutral HRV** | **GO** | **GO** | **MODIFY** | **ABORT** | **ABORT** |  |
| **YELLOW + Positive HRV** | **GO** | **MODIFY** | **ABORT** | **ABORT** | **ABORT** |  |
| **YELLOW + Neutral HRV** | **GO** | **MODIFY** | **ABORT** | **ABORT** | **ABORT** |  |
| **YELLOW + Negative HRV** | **MODIFY** | **ABORT** | **ABORT** | **ABORT** | **ABORT** |  |
| **YELLOW + Strong Neg HRV** | **ABORT** | **ABORT** | **ABORT** | **ABORT** | **ABORT** |  |
| **RED (any HRV)** | **ABORT** | **ABORT** | **ABORT** | **ABORT** | **ABORT** |  |

## 4. Weekly Adaptation Engine

### 4.1 State Machine

The weekly plan is a state machine. It transitions between states after each daily engine run and each session completion. The state governs how aggressively the engine pursues rescheduling vs writing off missed sessions.

```
States:
  ON_TRACK      -- All sessions on plan. Load accumulation meeting weekly target.
  LOAD_DEFICIT  -- One or more key sessions missed. Load behind weekly target.
  OVERREACHED   -- Actual load > 115% of target for 3+ consecutive days.
  RECOVERY_WEEK -- Monthly engine or 2x consecutive RED days triggered a deload.
  COMPLETE      -- Week finished. Final state. No further transitions.

Transitions:
  ON_TRACK      -> LOAD_DEFICIT   : key session skipped AND load < 80% of target
  ON_TRACK      -> OVERREACHED    : load > 115% target for 3 consecutive days
  ON_TRACK      -> RECOVERY_WEEK  : monthly engine triggers OR 2x RED days
  LOAD_DEFICIT  -> ON_TRACK       : rescheduled session completed successfully
  LOAD_DEFICIT  -> RECOVERY_WEEK  : monthly engine determines load not recoverable
  OVERREACHED   -> RECOVERY_WEEK  : automatic. Cannot return to ON_TRACK directly.
  RECOVERY_WEEK -> COMPLETE       : end of week reached
  any state     -> COMPLETE       : Sunday 23:59 reached

RECOVERY_WEEK rules:
  - All KEY sessions downgraded to Zone2_Short or Recovery
  - No HIIT or Threshold sessions permitted
  - Daily engine still runs but recommendation cannot exceed MODIFY
  - Weekly engine logs recovery_week_reason for monthly engine audit
```

### 4.2 Skip Disposition Algorithm

When a key session is skipped (ABORT recommendation acted on, or athlete manually skips), the weekly engine must determine whether to reschedule the session or write it off. This decision consults the monthly load target.

```
INPUTS:
  skipped_session_type    -- HIIT or Threshold
  days_remaining_in_week  -- integer
  monthly_load_pct        -- (load_actual_total / load_target_total) * 100
  current_week_state      -- weeky engine state
  next_key_session_day    -- day of the next already-planned KEY session

RESCHEDULE if ALL of:
  days_remaining_in_week >= 2
  monthly_load_pct < 85%           (load deficit -- session is needed)
  current_week_state != RECOVERY_WEEK
  No KEY session already within 1 day of proposed reschedule slot
    (minimum 1 full day between KEY sessions to allow adaptation)

WRITE_OFF if ANY of:
  days_remaining_in_week < 2
  monthly_load_pct >= 85%          (load is sufficient -- don't force it)
  current_week_state == RECOVERY_WEEK
  Two KEY sessions would be within 1 day of each other

RESCHEDULE slot selection (greedy, earliest available):
  1. Find the next non-KEY, non-Rest day with >= 1 day gap from any KEY session
  2. Replace that day's session with the rescheduled KEY session
  3. Move the displaced session to the written-off day if possible, else drop it
  4. Update adapted_plan_json in weekly_plans table

RECOVERY_WEEK trigger check (called on every ABORT):
  IF 2 consecutive days have recovery_band == RECOVERY_RED:
    -> weekly_engine.trigger_recovery_week(reason='consecutive_red')
  IF monthly_engine.load_overreach_detected():
    -> weekly_engine.trigger_recovery_week(reason='monthly_overreach')
```

### 4.3 Recovery Week Protocol

When a recovery week is triggered, the entire remaining week plan is replaced. The goal is nervous system reboot, not load maintenance.

| **Original Session** | **Recovery Week Replacement** | **Rationale** |
|----|----|----|
| HIIT | Zone2_Short (30-40 min, strict Zone 2 cap) | Cardiovascular maintenance without neural stress. |
| Threshold | Zone2_Short (30-40 min) | Same. Threshold stimulus contraindicated during reboot. |
| Zone2_Long | Zone2_Short (40-50 min) | Shortened. Duration is the primary fatigue driver, not intensity. |
| Zone2_Short | Zone2_Short or Recovery | Maintained or swapped depending on daily engine output. |
| Strength | Recovery (yoga, mobility) | Mechanical load removed. Joint and tendon recovery prioritised. |
| Recovery | Recovery (unchanged) | Already appropriate. |

## 5. Monthly Load Engine

### 5.1 Load Accumulation Model

The monthly engine accumulates load from all completed sessions and compares against the athlete-defined monthly target. Load is expressed in arbitrary units (AU) consistent across all session types.

```
Session Load Score (AU):
  For run/ride/swim sessions (HR-based) — Banister Impulse-Response (TRIMP),
  docs/adr/0024. Self-adjusts for terrain via HR response; no separate grade
  term:
    delta_hr_ratio = (avg_hr_bpm - resting_hr) / (max_hr - resting_hr)
    load_au = duration_minutes * delta_hr_ratio * 0.64 * e^(b * delta_hr_ratio)
    b = 1.92 (male) or 1.67 (female) -- athlete_profile.sex
    resting_hr: day-of daily_metrics.whoop_rhr_bpm, falling back to
                athlete_profile.baseline_resting_hr if that date has none
    max_hr: athlete_profile.max_hr

  For strength sessions (RPE-based, no HR zone target):
    load_au = (duration_minutes * rpe) / 6
    Rationale: RPE 6 for 60 min = 60 AU, comparable to moderate Zone 2 run.

  For recovery sessions (yoga, foam rolling):
    load_au = duration_minutes * 0.3
    Rationale: Recovery sessions accumulate minimal training load.

Monthly Load Target (set by athlete at block start):
  Stored in monthly_targets.load_target_total
  Weekly target = monthly_target / 4.33 (avg weeks per month)
  Daily target  = weekly_target / (training_days_per_week)

Load deficit threshold:  actual < 75% of target  -> flag LOAD_DEFICIT
Load surplus threshold:  actual > 115% of target -> flag OVERREACH_RISK
Overreach confirmation:  surplus sustained 3+ days -> trigger RECOVERY_WEEK
```

### 5.2 Performance Forecast Algorithm

At the end of each week, the monthly engine forecasts whether the athlete is on track to hit their monthly target and what their performance trajectory implies for the race date.

```
INPUTS:
  load_actual_total        -- accumulated load so far this month
  load_target_total        -- monthly target
  days_elapsed             -- calendar days into the month
  days_in_month            -- total calendar days
  hrv_trend_json           -- list of weekly avg HRV values
  session_quality_avg      -- average execution score this month
  weeks_to_race            -- from monthly_targets.race_date

load_pct_complete = load_actual_total / load_target_total
load_pace         = load_actual_total / days_elapsed
load_projected    = load_pace * days_in_month
load_projected_pct= load_projected / load_target_total

HRV trend direction:
  hrv_weekly_deltas = [week[i] - week[i-1] for i in range(1, len(hrv_trend))]
  IF avg(hrv_weekly_deltas) > 0:  trend = 'IMPROVING'
  IF avg(hrv_weekly_deltas) == 0: trend = 'STABLE'
  IF avg(hrv_weekly_deltas) < 0:  trend = 'DECLINING'

Performance forecast:
  IF load_projected_pct >= 0.90 AND hrv_trend == 'IMPROVING':
    -> forecast = 'ON_TRACK — Performance trajectory positive.'
  IF load_projected_pct >= 0.90 AND hrv_trend == 'STABLE':
    -> forecast = 'ON_TRACK — Monitor HRV for early fatigue signals.'
  IF load_projected_pct >= 0.90 AND hrv_trend == 'DECLINING':
    -> forecast = 'AT_RISK — Load on target but HRV declining.
                   Review sleep, nutrition, and stress. May need early deload.'
  IF load_projected_pct < 0.90 AND load_projected_pct >= 0.75:
    -> forecast = 'MINOR_DEFICIT — Slightly behind pace.
                   Protect all remaining key sessions this month.'
  IF load_projected_pct < 0.75:
    -> forecast = 'SIGNIFICANT_DEFICIT — Load well behind target.
                   Adjust monthly target downward OR investigate causes (illness,
                   injury, travel). Do not attempt to compensate with overload.'

Taper detection (when weeks_to_race <= 3):
  -> Override monthly target: begin progressive load reduction
  -> Week -3: load_target * 0.80
  -> Week -2: load_target * 0.65
  -> Week -1: load_target * 0.40  (race week)
```

### 5.3 Monthly Summary Output

Generated at the end of each calendar month and stored in monthly_targets.month_summary_json. This is the primary input for the Ollama explanation on monthly review.

```
{
  "month":                  "June 2026",
  "periodisation_phase":    "BUILD",
  "load_target_au":         1200.0,
  "load_actual_au":         1087.4,
  "load_pct":               90.6,
  "load_status":            "MINOR_DEFICIT",
  "hrv_trend":              "STABLE",
  "hrv_weekly_avgs_ms":     [74.2, 71.8, 73.1, 72.4],
  "session_quality_avg":    71.3,
  "sessions_completed":     18,
  "sessions_skipped":       3,
  "sessions_written_off":   1,
  "recovery_weeks":         0,
  "overpush_flags":         4,  <- threshold sessions pushed above Zone 4
  "underpush_flags":        2,  <- HIIT sessions that did not reach Zone 5
  "top_execution_session":  { "date": "2026-06-17", "type": "Threshold", "score": 91.2 },
  "worst_execution_session":{ "date": "2026-06-10", "type": "HIIT",      "score": 44.1 },
  "key_observations": [
    "Threshold sessions consistently overpush: 3 of 4 recorded overpush flags.",
    "HRV stable across month — no overtraining signal.",
    "Zone 2 sessions well-executed: average time in zone 84%."
  ],
  "next_month_recommendation": "Maintain BUILD phase. Prioritise threshold
   execution quality over volume. Set HR ceiling alert for threshold sessions."
}
```

## 6. Session Execution Scorer

### 6.1 Scoring Components

The execution scorer runs after each session syncs from Strava. It produces an execution_score from 0 to 100 and sets binary flags for overpush and underpush. The score is never used in the daily decision engine — it is purely retrospective and feeds monthly analysis.

| **Component** | **Weight** | **Source** | **Calculation** |
|----|----|----|----|
| time_in_zone_score | 0.45 | Strava stream | % of session seconds within intended zone boundaries -\> 0-100 |
| hr_drift_score | 0.25 | Strava stream | Cardiac decoupling: compare avg HR first half vs second half of session |
| rpe_alignment_score | 0.20 | Manual input | Actual RPE vs expected RPE for session type (see table 6.3) |
| load_delta_score | 0.10 | Calculated | abs(actual_load_au - planned_load_au) / planned_load_au -\> inverted |

### 6.2 Component Calculation Detail

#### Time in Zone Score

```
zone_boundaries = hr_zones table for session date (from zone_calculator)
intended_zone   = zone boundaries for the session type
                  HIIT      -> Zone 5 (90-100% HRR)
                  Threshold -> Zone 4 (80-90% HRR)
                  Zone2_*   -> Zone 2 (60-70% HRR)
                  Strength  -> None (RPE only, time_in_zone_score = null)
                  Recovery  -> Zone 1 (50-60% HRR)

total_seconds   = sum of all seconds in stream
in_zone_seconds = count of seconds where hr_data[i] is within zone boundaries
                  NOTE: exclude first 10 minutes from in_zone calculation
                  (warm-up period — should not count against score)

time_in_zone_pct = in_zone_seconds / (total_seconds - 600) * 100
time_in_zone_score = min(time_in_zone_pct, 100.0)
```

#### HR Drift Score

```
Split stream at session midpoint (by time, not distance)
first_half_avg_hr  = mean(hr_data[0 : midpoint])
second_half_avg_hr = mean(hr_data[midpoint :])

drift_ratio = (second_half_avg_hr - first_half_avg_hr) / first_half_avg_hr

Score mapping (for Zone 2 sessions — aerobic decoupling):
  drift_ratio <= 0.03  -> hr_drift_score = 100  (excellent: <3% drift)
  drift_ratio <= 0.05  -> hr_drift_score =  85  (good: 3-5% drift)
  drift_ratio <= 0.08  -> hr_drift_score =  70  (acceptable: 5-8%)
  drift_ratio <= 0.12  -> hr_drift_score =  50  (notable fatigue)
  drift_ratio >  0.12  -> hr_drift_score =  30  (significant decoupling)

For KEY sessions (HIIT, Threshold):
  HR drift is expected and desirable (fatigue accumulation is the goal)
  hr_drift_score is fixed at 80 for all KEY sessions (not penalised)
```

#### RPE Alignment Score

```
Expected RPE per session type:
  HIIT       -> expected_rpe = 9    (very hard)
  Threshold  -> expected_rpe = 7    (hard)
  Zone2_Long -> expected_rpe = 4    (comfortable)
  Zone2_Short-> expected_rpe = 3    (easy-moderate)
  Strength   -> expected_rpe = 6    (moderate-hard)
  Recovery   -> expected_rpe = 2    (very easy)

rpe_delta = abs(actual_rpe - expected_rpe)

rpe_alignment_score:
  rpe_delta == 0 -> 100
  rpe_delta == 1 ->  85
  rpe_delta == 2 ->  65
  rpe_delta == 3 ->  40
  rpe_delta >= 4 ->  15  (significant mismatch — flag for review)
```

#### Load Delta Score

```
planned_load_au = daily_plan load target for this session type
                  Set from training_plan config + weekly engine output
actual_load_au  = calculated from Strava activity (see SDD Section 5.2)

load_delta_ratio = abs(actual_load_au - planned_load_au) / planned_load_au

load_delta_score:
  ratio <= 0.05 -> 100  (within 5% of plan)
  ratio <= 0.10 -> 90
  ratio <= 0.20 -> 75
  ratio <= 0.35 -> 55
  ratio >  0.35 -> 30  (significantly off plan)
```

### 6.3 Overpush and Underpush Flag Logic

```
Overpush flag (overpush_flag = TRUE) — set INDEPENDENTLY of execution score:
  IF session_type == Threshold:
    overpush = time where HR > zone4_max > 15% of session duration
    (HR drifting into Zone 5 during a threshold session)
  IF session_type == Zone2_Long or Zone2_Short:
    overpush = time where HR > zone2_max > 10% of session duration
    (HR drifting into Zone 3 during a Zone 2 session)

Underpush flag (underpush_flag = TRUE):
  IF session_type == HIIT:
    underpush = time where HR < zone4_max > 40% of non-warmup session duration
    (Never reached Zone 5 -- VO2max stimulus not achieved)
  IF session_type == Threshold:
    underpush = avg HR < zone4_min for the full session
    (Session never reached threshold zone at all)

Note: Flags do not modify execution_score. They are separate analytical signals.
      Four overpush_flags in a month triggers a monthly observation note.
```

## 7. Morning Health Check Protocol

### 7.1 Fixed Daily Questions

These three questions appear every morning regardless of yesterday's session. They are the baseline inputs to the daily engine.

| **Question** | **Scale** | **Maps To** |
|----|----|----|
| How is your overall muscle soreness right now? | 1 (none) – 5 (severe) | soreness_band (see Section 2.3) |
| How is your subjective energy level today? | 1 (exhausted) – 5 (excellent) | subjective_energy (informational) |
| How was your sleep quality last night? | 1 (poor) – 5 (excellent) | sleep_quality_felt (informational) |

### 7.2 Adaptive Questions — Session Type Mapping

After the fixed questions, the health check adapts based on yesterday's session type. This captures mechanical stress that WHOOP cannot detect.

| **Yesterday's Session** | **Adaptive Questions** | **Flag Threshold** |
|----|----|----|
| HIIT | Left knee pain (1-5)? Right knee pain (1-5)? Shin / calf tightness (1-5)? | Any \>= 4: ABORT strength/run. Any \>= 3: MODIFY note logged. |
| Threshold | Left/right hamstring tightness (1-5)? Achilles tension (1-5)? | Any \>= 4: ABORT run. \>= 3: flag for warm-up extension. |
| Zone2_Long | Left/right Achilles pain (1-5)? General leg fatigue (1-5)? | Achilles \>= 3: MODALITY_SWAP flag. Leg fatigue \>= 4: MODIFY. |
| Zone2_Short | General leg fatigue (1-5)? | \>= 4: note logged only. |
| Strength | Lower back tightness (1-5)? Left/right knee pain (1-5)? | Any \>= 4: ABORT today's strength if scheduled. \>= 3: MODIFY. |
| Recovery | General wellbeing (1-5)? | \<= 2: flag low wellbeing for daily engine context. |
| Rest | General wellbeing (1-5)? | \<= 2: flag for daily engine context. |

### 7.3 Health Check Override Rules

Adaptive health check scores can override the daily engine output regardless of WHOOP data. These are hard safety overrides, not inputs to the decision tree.

```
IF any adaptive_health_check_score >= 4:
  (pain/discomfort-style questions only — high-is-bad direction. Does NOT apply to inverted questions like Recovery/Rest's wellbeing check, where a high score is good. See docs/adr/0012.)
  -> FORCE ABORT on any session that loads the flagged structure
  -> This override is NOT adjustable by the athlete in v1.0
  -> Log override reason: 'health_check_override: {check_name} = {score}'
  -> Trigger advisory: 'Pain at this level warrants medical attention
                         if it persists beyond 3 days.'

IF any adaptive_health_check_score >= 3 for 3 consecutive days:
  -> Trigger persistent_flag in decisions table
  -> Monthly engine includes in month_summary_json observations
  -> Ollama advisory: 'Recurring {check_name} flagged for 3 days.
                        Consider physiotherapy assessment.'
```

## 8. Zone Calculator

### 8.1 HRR Zone Formula

Implemented as a pure function in services/zone_calculator.py. No database calls, no I/O. Takes two integers, returns a typed dict. Fully unit-testable.

```
def calculate_zones(max_hr: int, resting_hr: int) -> dict[str, tuple[int, int]]:
    '''
    Calculate 5 HR zones using Heart Rate Reserve (Karvonen) method.
    Returns dict with zone name -> (lower_bpm, upper_bpm) tuples.
    Boundaries are rounded to the nearest bpm, not truncated — see docs/adr/0009.
    '''
    hrr = max_hr - resting_hr

    zones = {
        'zone1': (resting_hr + round(0.50 * hrr), resting_hr + round(0.60 * hrr)),
        'zone2': (resting_hr + round(0.60 * hrr), resting_hr + round(0.70 * hrr)),
        'zone3': (resting_hr + round(0.70 * hrr), resting_hr + round(0.80 * hrr)),
        'zone4': (resting_hr + round(0.80 * hrr), resting_hr + round(0.90 * hrr)),
        'zone5': (resting_hr + round(0.90 * hrr), max_hr),
    }
    return zones

Example: max_hr=192, resting_hr=48
  HRR = 144
  Zone 1: 120 – 134 bpm  (Recovery)
  Zone 2: 134 – 149 bpm  (Aerobic base)
  Zone 3: 149 – 163 bpm  (Tempo)
  Zone 4: 163 – 178 bpm  (Threshold)
  Zone 5: 178 – 192 bpm  (VO2max / neuromuscular)

Max HR resolution:
  Primary: highest HR ever recorded in Strava activity history
  Override: ATHLETE_MAX_HR environment variable (manual override)
  Fallback: 220 - athlete_age (only if no Strava data exists)
  Max HR record updated on each Strava sync if new maximum detected.
```

### 8.2 Zone Calculator Unit Test Spec

Every test case below must have a corresponding pytest parametrize entry in tests/unit/test_zone_calculator.py before the module is integrated.

| **Max HR** | **Resting HR** | **Zone 2 (bpm)** | **Zone 4 (bpm)** | **Notes** |
|----|----|----|----|----|
| 192 | 48 | 134-149 | 163-178 | Reference case |
| 185 | 52 | 132-145 | 158-172 | Slightly lower max HR |
| 200 | 55 | 142-157 | 171-185 | High max HR, higher resting HR |
| 192 | 40 | 131-146 | 162-177 | Low resting HR, very fit state |
| 192 | 60 | 139-152 | 166-179 | High resting HR, fatigued state |
| 180 | 55 | 130-143 | 155-167 | Low max HR athlete |

## 9. Document Control

| **Version** | **Date** | **Changes** | **Author** |
|----|----|----|----|
| 1.0 | June 2026 | Initial draft. All decision trees, state machines, scoring algorithms, zone calculation, and health check protocol fully specified. | Mattias |

*Next document: Test Strategy Document — test pyramid implementation, pytest fixture design, mock payload catalogue, CI configuration, and coverage enforcement.*

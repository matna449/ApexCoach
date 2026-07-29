# Apex Coach

A local-first AI coaching system that turns WHOOP recovery signals, Strava execution data, and subjective input into daily/weekly/monthly training recommendations. This glossary is the canonical source for Apex Coach domain terms — seeded from the PRD, SDD, and Logic & Algorithm Spec (see [README.md](./README.md)), and updated inline whenever a `grill-with-docs` session resolves or sharpens a term.

## Language

### Recovery & readiness signals

**Recovery Band**:
The classification of WHOOP's raw recovery score into `RECOVERY_GREEN` (67–100), `RECOVERY_YELLOW` (34–66), or `RECOVERY_RED` (0–33). Raw scores never enter decision logic directly — only their band.
_Avoid_: recovery score, recovery level, recovery status

**HRV Delta**:
Today's HRV minus the rolling 30-day average, classified into `HRV_POSITIVE` (>+5ms), `HRV_NEUTRAL` (±5ms), `HRV_NEGATIVE` (-5 to -10ms), or `HRV_STRONG_NEG` (<-10ms). Contextualises a single HRV reading against the athlete's own baseline; it adjusts but never overrides the Recovery Band on its own.
_Avoid_: HRV trend, HRV signal, HRV score

**Soreness Band**:
The athlete's self-reported muscle soreness (1–5, via the Morning Health Check) classified into `SORENESS_NONE` through `SORENESS_SEVERE`. Drives Modality Swap and volume-reduction decisions independently of recovery signals.
_Avoid_: soreness score, soreness level, pain rating

**Morning Health Check**:
The adaptive CLI prompt run each morning before the Daily Engine executes — fixed questions (soreness, energy, sleep quality felt) plus questions adaptive to yesterday's session. Feeds the Daily Engine directly; it is not a general survey or logging tool.
_Avoid_: daily check-in, morning survey, wellness check

### Session taxonomy

**Session Type**:
The label on a scheduled training session (`HIIT`, `Threshold`, `Zone2_Long`, `Zone2_Short`, `Strength`, `Recovery`, `Rest`), each with a fixed Priority Tier and target HR zone. Defined by the athlete's training plan config, not inferred by the system.
_Avoid_: workout type, activity type

**Priority Tier**:
The rescheduling priority of a Session Type — `KEY` (HIIT, Threshold; cannot be trivially rescheduled), `BASE` (Zone 2 work), `SUPPORT` (Strength), or `RECOVERY` (Recovery, Rest). Drives the Weekly Adaptation Engine's Skip Disposition decision.
_Avoid_: session priority, importance level

**Key Session**:
A session with Priority Tier `KEY` — the highest-priority training stimulus in the pyramidal periodisation model. Losing a Key Session is the main trigger the Weekly Adaptation Engine reacts to.
_Avoid_: important session, main workout

**Modality Swap**:
Substituting a run-based session with a non-impact equivalent (cycling, swimming) when soreness is elevated but the underlying stimulus should still be delivered. Distinct from Skip Disposition — a swap still happens today, on the intended stimulus.
_Avoid_: workout substitution, session swap

### Decision engine outputs

**Decision Output**:
The Daily Engine's recommendation for a scheduled session — exactly one of `GO`, `MODIFY`, `MODALITY_SWAP`, or `ABORT`. Always deterministic Python, never produced by the LLM.
_Avoid_: recommendation, verdict, decision

**Execution Quality Score**:
The 0–100 score assigned to a completed session by the Session Execution Scorer, from time-in-zone, HR drift, grade-adjusted pace, elevation, RPE, and strain-vs-plan. Distinct from a Recovery Band or Decision Output — it scores what already happened, not what to do next.
_Avoid_: session score, performance score

**Overpush / Underpush**:
Flags raised by the Session Execution Scorer when a Threshold session was executed harder than the plan intended (overpush) or a VO2max/HIIT session was executed too conservatively (underpush). Computed from execution data, not from the pre-session Decision Output.
_Avoid_: too hard / too easy, overtraining flag

**Explanation Layer**:
The Ollama-based component that converts a Decision Output's structured JSON into natural-language rationale and answers athlete follow-up questions. It only explains outputs already produced by deterministic logic — it never decides.
_Avoid_: LLM layer, AI coach, assistant

### Load & periodisation

**Skip Disposition**:
The Weekly Adaptation Engine's choice, when a Key Session is missed, to either reschedule it (load deficit, capacity exists later in the week) or write it off (recovery debt too high to safely add volume). One of exactly two outcomes — there is no partial-credit state.
_Avoid_: skip handling, missed session logic

**Monthly Load Target**:
The load total the athlete sets at the start of a training block; the Monthly Engine has final authority and constrains what the Weekly and Daily Engines are allowed to recommend.
_Avoid_: training load, TSS, load budget

**Recovery Week**:
A flagged week where accumulated recovery debt (repeated `HRV_STRONG_NEG` + `RECOVERY_RED` readings) outweighs the Monthly Load Target, triggering a deliberate reduction in Key Session frequency.
_Avoid_: deload week, rest week, taper

**Three-Horizon Model**:
The nested Daily / Weekly / Monthly decision structure. Monthly constrains Weekly, Weekly constrains Daily — a lower horizon can never override a higher one's authority.
_Avoid_: planning layers, decision hierarchy

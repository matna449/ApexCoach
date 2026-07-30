---
status: accepted
---

# HRR zone boundaries are rounded to the nearest bpm, not truncated

Logic & Algorithm Spec §8.1's reference implementation used `int(0.XX * hrr)` for every zone boundary — Python's `int()` truncates toward zero. Building F03.1 (`services/zone_calculator.py`) and copying §8.2's unit test table into parametrized tests surfaced that the table's own values don't match truncation: only row 1 (192/48, the "reference case," called out in the table's own notes as "your approx values") matches the formula at all, and it only matches under rounding — `int(0.70 × 144)` gives 148, but the table (and SDD §5.1's independently-stated worked example) both say 149. Rows 2 through 6 didn't match the formula under truncation *or* rounding — they were off by amounts too large to be rounding noise, indicating they were hand-typed as plausible-looking illustrative numbers rather than actually computed from the pseudocode.

We're treating rounding as the intended behavior, since it's the interpretation under which the one number a human actually verified (the reference case, cross-checked independently against SDD §5.1) comes out correct. `calculate_zones()` uses `round()` instead of `int()`, and rows 2-6 of the Logic Spec's test table were recomputed by actually running the formula and correcting the doc, rather than either leaving wrong numbers in the spec or engineering the code to match numbers nobody had verified were reachable by any consistent rule.

Alternative considered: follow §8.1's `int()` pseudocode literally, since it's executable code rather than prose, and correct the "reference case" example (and SDD §5.1's matching worked example) down to match truncation instead. Rejected because that would mean overriding the one number in the entire table with an independent, cross-referenced human verification behind it, in favor of pseudocode that — by the same table's evidence — was never actually run against its own test cases.

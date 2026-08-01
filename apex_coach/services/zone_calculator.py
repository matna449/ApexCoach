"""Pure HRR (Karvonen) zone calculation. No I/O.

See Logic & Algorithm Spec §8.1 and docs/adr/0009 — boundaries are rounded
to the nearest bpm, not truncated, despite §8.1's pseudocode using int().
"""


def calculate_zones(max_hr: int, resting_hr: int) -> dict[str, tuple[int, int]]:
    """Calculate 5 HR zones using Heart Rate Reserve (Karvonen) method.

    Returns dict with zone name -> (lower_bpm, upper_bpm) tuples.
    """
    if resting_hr >= max_hr:
        raise ValueError(
            f"resting_hr ({resting_hr}) must be lower than max_hr ({max_hr})"
        )

    hrr = max_hr - resting_hr

    return {
        "zone1": (resting_hr + round(0.50 * hrr), resting_hr + round(0.60 * hrr)),
        "zone2": (resting_hr + round(0.60 * hrr), resting_hr + round(0.70 * hrr)),
        "zone3": (resting_hr + round(0.70 * hrr), resting_hr + round(0.80 * hrr)),
        "zone4": (resting_hr + round(0.80 * hrr), resting_hr + round(0.90 * hrr)),
        "zone5": (resting_hr + round(0.90 * hrr), max_hr),
    }


def zone_midpoint(zone_bounds: tuple[int, int]) -> float:
    """Representative HR for a zone — used by F19.2's structure generator
    as the fixed avg_hr fed into TRIMP-inversion (grill-me Q8)."""
    lower, upper = zone_bounds
    return (lower + upper) / 2

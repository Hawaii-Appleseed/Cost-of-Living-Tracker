"""Plausibility bounds for every value the updaters publish.

The updaters validate fetched values only lightly (`> 0`), so a mis-parsed
order-of-magnitude value — a $115,000 median SFH price from a shifted column,
a $56/gal gas price from a mangled cell — would ship to the dashboard under a
fresh "As of" label. Each updater scans its outgoing record against the ranges
here and refuses to publish on any violation (the HTML keeps its last-good
block instead, and CI fails loudly).

Ranges are deliberately generous — they exist to catch parser breakage, not to
police the economy. If Hawaiʻi ever legitimately exits a range, widening it
here is a reviewed one-line change.

Usage::

    from ha_common.sanity import scan_record, HOUSING_BOUNDS

    problems = scan_record("Honolulu", record, HOUSING_BOUNDS)
    if problems:
        ...print and exit non-zero, do NOT patch...
"""
from __future__ import annotations


class SanityError(ValueError):
    """A value fell outside its plausible range."""


# ── Housing / affordability (redfin-price-updater.py) ─────────────────────
# Fields are checked only when present and non-None: most fetches soft-fail
# by leaving the field out so the HTML keeps its last-good value, and that
# contract stays intact.
HOUSING_BOUNDS = {
    "sfhPrice":                 (100_000, 5_000_000),   # $ median resale
    "condoPrice":               (50_000, 5_000_000),
    "income":                   (40_000, 400_000),      # $ median family income
    "rent":                     (400, 10_000),          # $/mo nowcast contract rent
    "askRent":                  (400, 12_000),          # $/mo ZORI asking rent
    "sfhMortgage":              (500, 40_000),          # $/mo P&I
    "condoMortgage":            (300, 40_000),
    "sfhPTI":                   (0.02, 2.5),            # payment-to-income fraction
    "condoPTI":                 (0.02, 2.5),
    "tenantRentPTI":            (0.05, 1.0),            # ACS GRAPI-style fraction
    "mortgageOwnerPTI":         (0.05, 1.0),
    "rentBurdenedPct":          (0.0, 1.0),
    "rentSeverelyBurdenedPct":  (0.0, 1.0),
    "ownerBurdenedPct":         (0.0, 1.0),
    "ownerSeverelyBurdenedPct": (0.0, 1.0),
    "sfhIdx":                   (10, 500),               # affordability index, base 100
    "condoIdx":                 (10, 500),
    "buildAuth":                (0, 50_000),             # units authorized
    "zoriYoY":                  (-0.30, 0.50),           # fractional YoY
    "cpiRentYoY":               (-0.30, 0.50),
}

BEDROOM_RENT_BOUNDS = (300, 12_000)   # $/mo, any bedroom tier

# ── Gas (gas-price-updater.py) — $/gal, AAA Hawaiʻi ────────────────────────
GAS_BOUNDS = {
    "regular":    (2.0, 12.0),
    "mid_grade":  (2.0, 12.0),
    "premium":    (2.0, 12.0),
    "diesel":     (2.0, 15.0),
    "mom_change": (-4.0, 4.0),
    "yoy_change": (-4.0, 4.0),
}

# ── Grocery (grocery-price-updater.py) — weekly basket for family of 4 ─────
GROCERY_BOUNDS = {
    "basketPretax":         (80, 400),      # $/wk
    "basketWithTax":        (80, 400),
    "monthlyFamily4":       (300, 2_500),   # $/mo
    "groceryIdx":           (50, 200),      # Honolulu = 100
    "groceryShareOfIncome": (0.01, 0.50),   # fraction
    "weeklyPerCap":         (15, 150),      # $/wk
}

# ── BLS Honolulu CPI YoY % (bls-cpi-updater.py) ─────────────────────────────
# Energy/transport swing hard (gasoline YoY hit ±40% in 2008/2022); the
# headline and shelter series don't.
CPI_YOY_BOUNDS = {
    "allItems":  (-5, 25),
    "shelter":   (-5, 25),
    "food":      (-5, 30),
    "energy":    (-60, 80),
    "transport": (-30, 50),
}

# ── USDA TFP monthly cost, family of 4 (tfp-updater.py) ────────────────────
TFP_HI_BOUNDS   = (800, 3_000)    # $/mo, Alaska-Hawaii table
TFP_US48_BOUNDS = (500, 2_000)    # $/mo, national table


def check_range(metric: str, value, lo, hi, *, allow_none: bool = True):
    """Validate a single value; raise SanityError outside [lo, hi]."""
    if value is None:
        if allow_none:
            return None
        raise SanityError(f"{metric} is missing")
    try:
        v = float(value)
    except (TypeError, ValueError):
        raise SanityError(f"{metric}={value!r} is not numeric")
    if not (lo <= v <= hi):
        raise SanityError(f"{metric}={value!r} outside plausible range [{lo}, {hi}]")
    return value


def scan_record(prefix: str, record: dict, bounds: dict) -> list[str]:
    """Check every bounded field present in *record*; return violation messages.

    Absent / None fields are skipped — soft-fail contracts leave fields out so
    the HTML keeps its last-good value, and that must not trip the scan.
    """
    problems: list[str] = []
    for field, (lo, hi) in bounds.items():
        if record.get(field) is None:
            continue
        try:
            check_range(f"{prefix}.{field}", record[field], lo, hi)
        except SanityError as exc:
            problems.append(str(exc))
    return problems

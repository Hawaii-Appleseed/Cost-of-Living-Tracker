#!/usr/bin/env python3
"""
Fail CI when a dashboard metric has gone silently stale (Q-audit item 1).

The dashboard inlines its data into the HTML, so a fetch that soft-fails (e.g.
the dead-Census-key incident: rent/burden froze while prices refreshed, all
under one "As of" label) leaves NO visible error — the page just ships old
numbers next to new ones. redfin-price-updater.py now also writes a diffable
snapshot to data/dashboard.json with per-metric reference periods; this script
reads that snapshot and exits non-zero if any metric's period is older than its
budget, so the monthly CI job breaks instead of publishing stale data.

Budgets are in MONTHS of staleness relative to the run's `generatedAt` month
(falls back to the system clock if absent). They account for each source's
natural publish cadence + lag.

Usage:
    python3 scripts/check_freshness.py                      # checks data/dashboard.json
    python3 scripts/check_freshness.py path/to/other.json   # check a specific file
    python3 scripts/check_freshness.py --as-of 2026-06      # override "now" (for tests)
"""
from __future__ import annotations

import datetime
import json
import sys
from pathlib import Path

# Metric → max allowed staleness in months (from the run month).
# Rent/housing/ZORI are monthly-ish; BLS rent is bimonthly with ~1-mo release
# lag; the per-county rentAsOf is the nowcast target month.
BUDGETS_MONTHS = {
    "housingPeriod":  3,   # Redfin monthly
    "blsRentPeriod":  4,   # BLS Honolulu rent CPI: bimonthly + release lag
    "zoriPeriod":     3,   # Zillow ZORI monthly
    "rentAsOf":       3,   # per-county nowcast target month
}

DEFAULT_PATH = Path(__file__).resolve().parent.parent / "data" / "dashboard.json"
COUNTIES = ("State", "Honolulu", "Maui", "Hawaii", "Kauai")


def _months_between(period: str, now_ym: tuple[int, int]) -> int | None:
    """Whole months from a 'YYYY-MM' period to now_ym (positive = in the past)."""
    try:
        y, m = period[:7].split("-")
        py, pm = int(y), int(m)
    except (ValueError, AttributeError):
        return None
    return (now_ym[0] - py) * 12 + (now_ym[1] - pm)


def main() -> int:
    args = [a for a in sys.argv[1:]]
    now_ym = None
    if "--as-of" in args:
        i = args.index("--as-of")
        try:
            y, m = args[i + 1].split("-")
            now_ym = (int(y), int(m))
        except (ValueError, IndexError):
            print("ERROR: --as-of needs a YYYY-MM value"); return 2
        del args[i:i + 2]
    path = Path(args[0]) if args else DEFAULT_PATH

    if not path.exists():
        print(f"ERROR: {path} not found — run redfin-price-updater.py first.")
        return 2
    data = json.loads(path.read_text(encoding="utf-8"))
    meta = data.get("_meta", {})

    if now_ym is None:
        gen = meta.get("generatedAt", "")
        mb = _months_between(gen[:7], (9999, 12)) if gen else None
        if gen and len(gen) >= 7:
            now_ym = tuple(int(x) for x in gen[:7].split("-"))  # type: ignore
        else:
            today = datetime.date.today()
            now_ym = (today.year, today.month)

    stale: list[str] = []
    checked = 0

    # Global metric periods carried in _meta.
    for key in ("housingPeriod", "blsRentPeriod", "zoriPeriod"):
        period = meta.get(key)
        if not period:
            stale.append(f"{key}: MISSING from snapshot")
            continue
        age = _months_between(period, now_ym)
        checked += 1
        if age is None:
            stale.append(f"{key}: unparseable period {period!r}")
        elif age > BUDGETS_MONTHS[key]:
            stale.append(f"{key}: {period} is {age} mo old (budget {BUDGETS_MONTHS[key]})")

    # Per-county rent nowcast target month.
    for c in COUNTIES:
        period = (data.get(c) or {}).get("rentAsOf")
        if not period:
            continue  # county may legitimately lack a rent nowcast
        age = _months_between(period, now_ym)
        checked += 1
        if age is None:
            stale.append(f"{c}.rentAsOf: unparseable {period!r}")
        elif age > BUDGETS_MONTHS["rentAsOf"]:
            stale.append(f"{c}.rentAsOf: {period} is {age} mo old (budget {BUDGETS_MONTHS['rentAsOf']})")

    nowstr = f"{now_ym[0]:04d}-{now_ym[1]:02d}"
    if stale:
        print(f"STALE DATA (as of {nowstr}) — {len(stale)} issue(s):")
        for s in stale:
            print(f"  ✗ {s}")
        print("\nThe dashboard would ship stale numbers under a fresh label. "
              "Check the updater logs for a soft-failed fetch (e.g. a bad API key).")
        return 1
    print(f"Freshness OK (as of {nowstr}): {checked} metric period(s) within budget.")
    return 0


if __name__ == "__main__":
    sys.exit(main())

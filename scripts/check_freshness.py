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

Two anchors, checked in layers:

1. `_meta.generatedAt` must be recent against the WALL CLOCK. Without this a
   pipeline that silently stops writing snapshots self-anchors — every metric
   stays "fresh" relative to a frozen generatedAt forever.
2. Per-metric periods are checked against generatedAt (their budgets describe
   each source's publish cadence + lag at the time the snapshot was built).

Gas, grocery, CPI and TFP updaters patch index.html only (no JSON snapshot),
so their inlined data blocks are checked directly against the wall clock.

Budgets are in whole MONTHS of staleness (YYYY-MM granularity).

Usage:
    python3 scripts/check_freshness.py                      # checks data/dashboard.json + index.html
    python3 scripts/check_freshness.py path/to/other.json   # check a specific snapshot
    python3 scripts/check_freshness.py --as-of 2026-06      # override "now" (for tests)
"""
from __future__ import annotations

import datetime
import json
import re
import sys
from pathlib import Path

# Metric → max allowed staleness in months (from the snapshot's generatedAt
# month). Rent/housing/ZORI are monthly-ish; BLS rent is bimonthly with ~1-mo
# release lag; the per-county rentAsOf is the nowcast target month.
BUDGETS_MONTHS = {
    "housingPeriod":  3,   # Redfin monthly
    "blsRentPeriod":  4,   # BLS Honolulu rent CPI: bimonthly + release lag
    "zoriPeriod":     3,   # Zillow ZORI monthly
    "rentAsOf":       3,   # per-county nowcast target month
}

# generatedAt itself vs the wall clock. The workflow regenerates the snapshot
# in the same run (age 0); an ad-hoc check mid-cycle sees at most last month's
# (age 1). Age ≥ 2 means a full monthly cycle was missed.
GENERATED_AT_BUDGET_MONTHS = 1

# HTML-inlined blocks (these updaters don't write to dashboard.json), each
# checked against the wall clock: (marker tag, period field regex, budget).
HTML_BLOCK_BUDGETS = {
    "gas":     ("GAS_DATA",     r'asOf:\s*"(\d{4}-\d{2})',         2),  # AAA daily snapshot, captured monthly
    "grocery": ("GROCERY_DATA", r'lastUpdated:\s*"(\d{4}-\d{2})',  2),  # monthly CPI-adjust of baseline
    "cpi":     ("CPI_DATA",     r'latestPeriod:\s*"(\d{4}-\d{2})', 4),  # BLS Honolulu CPI: bimonthly + lag
    "tfp":     ("TFP_DATA",     r'latestPeriod:\s*"(\d{4}-\d{2})', 4),  # USDA TFP release, CPI-projected forward
}

ROOT = Path(__file__).resolve().parent.parent
DEFAULT_PATH = ROOT / "data" / "dashboard.json"
DEFAULT_HTML_PATH = ROOT / "index.html"
COUNTIES = ("State", "Honolulu", "Maui", "Hawaii", "Kauai")


def _months_between(period: str, now_ym: tuple[int, int]) -> int | None:
    """Whole months from a 'YYYY-MM' period to now_ym (positive = in the past)."""
    try:
        y, m = period[:7].split("-")
        py, pm = int(y), int(m)
    except (ValueError, AttributeError, TypeError):
        return None
    return (now_ym[0] - py) * 12 + (now_ym[1] - pm)


def extract_html_periods(html: str) -> dict[str, list[str] | None]:
    """Pull the 'YYYY-MM' period strings out of each tagged HTML data block.

    Returns {name: [periods...]} — an empty list means the block exists but
    carries no parseable period (e.g. the null block bls-cpi-updater writes on
    a failed fetch); None means the block markers themselves are missing.
    """
    out: dict[str, list[str] | None] = {}
    for name, (tag, field_re, _budget) in HTML_BLOCK_BUDGETS.items():
        m = re.search(
            rf"/\* {tag}_START \*/(.*?)/\* {tag}_END \*/", html, re.S
        )
        out[name] = re.findall(field_re, m.group(1)) if m else None
    return out


def run_checks(
    data: dict,
    html: str | None,
    today_ym: tuple[int, int],
) -> tuple[list[str], int]:
    """Return (stale issue messages, number of periods checked)."""
    stale: list[str] = []
    checked = 0
    meta = data.get("_meta", {})

    # Layer 1: the snapshot itself must be alive (wall-clock anchor).
    gen = meta.get("generatedAt", "")
    gen_ym: tuple[int, int] | None = None
    gen_age = _months_between(gen[:7], today_ym) if gen else None
    if gen_age is None:
        stale.append(f"_meta.generatedAt: missing or unparseable ({gen!r}) — "
                     "cannot verify the pipeline is still writing snapshots")
    else:
        checked += 1
        gen_ym = tuple(int(x) for x in gen[:7].split("-"))  # type: ignore
        if gen_age > GENERATED_AT_BUDGET_MONTHS:
            stale.append(
                f"_meta.generatedAt: {gen[:7]} is {gen_age} mo old "
                f"(budget {GENERATED_AT_BUDGET_MONTHS}) — the updater has "
                "stopped writing fresh snapshots"
            )

    # Layer 2: metric periods vs generatedAt (fall back to the wall clock).
    now_ym = gen_ym or today_ym
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

    # Layer 3: HTML-only data blocks (gas/grocery/CPI/TFP) vs the wall clock.
    if html is not None:
        for name, periods in extract_html_periods(html).items():
            budget = HTML_BLOCK_BUDGETS[name][2]
            tag = HTML_BLOCK_BUDGETS[name][0]
            if periods is None:
                stale.append(f"{name}: {tag} block missing from index.html")
                continue
            if not periods:
                stale.append(f"{name}: {tag} block carries no period — "
                             "the updater soft-failed and wrote a null block")
                continue
            oldest = min(periods)
            age = _months_between(oldest, today_ym)
            checked += 1
            if age is None:
                stale.append(f"{name}: unparseable period {oldest!r}")
            elif age > budget:
                stale.append(f"{name}: oldest period {oldest} is {age} mo old (budget {budget})")

    return stale, checked


def main() -> int:
    args = [a for a in sys.argv[1:]]
    today_ym: tuple[int, int] | None = None
    if "--as-of" in args:
        i = args.index("--as-of")
        try:
            y, m = args[i + 1].split("-")
            today_ym = (int(y), int(m))
        except (ValueError, IndexError):
            print("ERROR: --as-of needs a YYYY-MM value"); return 2
        del args[i:i + 2]
    path = Path(args[0]) if args else DEFAULT_PATH

    if not path.exists():
        print(f"ERROR: {path} not found — run redfin-price-updater.py first.")
        return 2
    data = json.loads(path.read_text(encoding="utf-8"))

    html = None
    if DEFAULT_HTML_PATH.exists():
        html = DEFAULT_HTML_PATH.read_text(encoding="utf-8")
    else:
        print(f"WARNING: {DEFAULT_HTML_PATH} not found — skipping gas/grocery/CPI/TFP checks.")

    if today_ym is None:
        today = datetime.date.today()
        today_ym = (today.year, today.month)

    stale, checked = run_checks(data, html, today_ym)

    nowstr = f"{today_ym[0]:04d}-{today_ym[1]:02d}"
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

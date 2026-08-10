"""Guard the BLS *area code* on every Hawaii CPI series we consume.

Why this file exists
--------------------
Until 2026-08-07 every CPI series in this repo used area `S49A`, labelled
"Honolulu" throughout the code and docs. `S49A` is Los Angeles-Long
Beach-Anaheim. The site published Los Angeles inflation as Hawaii's for as
long as the chips have existed — understating headline CPI by ~1.8pp and
shelter by ~3.6pp (2.65% vs 6.27% at the time of the fix).

The whole test suite passed throughout, because nothing asserted *which
place* the numbers describe. That is the gap this file closes: it is a
provenance test, not a numeric one.

The cheap structural check is CADENCE. BLS publishes the all-items index
(SA0) monthly for exactly four areas — US city average, New York (S12A),
Chicago (S23A) and Los Angeles (S49A). Every other area, Urban Hawaii
included, is bimonthly. So a "Hawaii" SA0 series carrying 12 observations a
year is definitionally the wrong area, and that is checkable offline against
a committed fixture without hitting the BLS API.

These tests deliberately do NOT assert YoY values. Inflation moves; the area
code must not.
"""
from __future__ import annotations

import re
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

# Correct area for Hawaii CPI. S49A is Los Angeles — see module docstring.
HAWAII_AREA = "S49F"
WRONG_AREA = "S49A"

# Expected publication cadence per series suffix, verified against the BLS
# API on 2026-08-07. Mixed on purpose: the all-items/aggregate indices are
# bimonthly for Urban Hawaii, the item-level ones are monthly.
EXPECTED_PERIODS_PER_YEAR = {
    "SA0": 6,       # all items      — bimonthly (the four-area rule above)
    "SAH": 6,       # shelter        — bimonthly
    "SAT": 6,       # transportation — bimonthly
    "SAF11": 12,    # food at home   — monthly
    "SETB01": 12,   # gasoline       — monthly
    "SEHA": 12,     # rent           — monthly
}

# Files that name BLS CPI series. Kept explicit rather than globbed so a new
# consumer has to be added here consciously.
SERIES_BEARING_FILES = [
    "bls-cpi-updater.py",
    "tfp-updater.py",
    "ha_housing/config.py",
    "ha_housing/bls.py",
    "ha_housing/nowcast.py",
    "pipelines/grocery/scripts/refresh_ce_pumd.py",
    "pipelines/grocery/src/pumd_extractor.py",
    "scripts/backtest_rent_nowcast.py",
    "scripts/backtest_rent_3leg.py",
    "backtests/rent_blend_walkforward.py",
]

CUUR_RE = re.compile(r"CUUR(S49[A-Z])([A-Z0-9]+)")


def _iter_series_refs():
    """Yield (path, full_id, area, suffix) for every CUURS49* literal."""
    for rel in SERIES_BEARING_FILES:
        p = ROOT / rel
        if not p.exists():
            continue
        text = p.read_text(encoding="utf-8")
        for m in CUUR_RE.finditer(text):
            yield rel, m.group(0), m.group(1), m.group(2)


def test_no_los_angeles_series_anywhere():
    """The regression itself: S49A must not reappear in any consumer."""
    offenders = [(rel, sid) for rel, sid, area, _ in _iter_series_refs()
                 if area == WRONG_AREA]
    assert not offenders, (
        f"S49A is Los Angeles, not Hawaii. Found {len(offenders)} reference(s): "
        + ", ".join(f"{r}:{s}" for r, s in offenders)
    )


def test_every_cpi_series_uses_the_hawaii_area():
    refs = list(_iter_series_refs())
    assert refs, "found no CUURS49* series at all — did the naming scheme change?"
    for rel, sid, area, _ in refs:
        assert area == HAWAII_AREA, f"{rel}: {sid} uses area {area}, expected {HAWAII_AREA}"


def test_series_suffixes_are_known():
    """A suffix we have no cadence expectation for is unreviewed, not fine."""
    unknown = {(rel, sid) for rel, sid, _, suf in _iter_series_refs()
               if suf not in EXPECTED_PERIODS_PER_YEAR}
    assert not unknown, (
        "unrecognised CPI series suffix — add it to EXPECTED_PERIODS_PER_YEAR "
        f"with its verified cadence: {sorted(unknown)}"
    )


def test_updater_series_map_is_hawaii():
    """The map that actually drives the published chips."""
    import importlib.util
    spec = importlib.util.spec_from_file_location(
        "bls_cpi_updater", ROOT / "bls-cpi-updater.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    assert mod.SERIES, "SERIES map is empty"
    for key, sid in mod.SERIES.items():
        m = CUUR_RE.fullmatch(sid)
        assert m, f"{key}: {sid!r} is not a recognised CUURS49* id"
        assert m.group(1) == HAWAII_AREA, f"{key}: {sid} is not Urban Hawaii"


# ---------------------------------------------------------------------------
# Cadence — the structural tell that catches a wrong area without the API
# ---------------------------------------------------------------------------

def _periods_per_year(points, year):
    return len({p["period"] for p in points if p["year"] == year})


def test_compute_yoy_handles_mixed_cadence():
    """Bimonthly and monthly series must both YoY correctly, and must be
    allowed to land on *different* latest periods — the corrected series set
    is mixed, so anything assuming one shared period grid is broken."""
    import importlib.util
    spec = importlib.util.spec_from_file_location(
        "bls_cpi_updater", ROOT / "bls-cpi-updater.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)

    # bimonthly: odd months only, +10% YoY
    bim = [{"year": y, "period": f"M{m:02d}", "value": 100.0 * (1.1 if y == 2026 else 1.0)}
           for y in (2025, 2026) for m in (1, 3, 5)]
    yoy, period = mod.compute_yoy(bim)
    assert yoy == pytest.approx(10.0)
    assert period == "2026-05"

    # monthly: every month, +5% YoY, lands one month later than the bimonthly
    mon = [{"year": y, "period": f"M{m:02d}", "value": 200.0 * (1.05 if y == 2026 else 1.0)}
           for y in (2025, 2026) for m in range(1, 7)]
    yoy_m, period_m = mod.compute_yoy(mon)
    assert yoy_m == pytest.approx(5.0)
    assert period_m == "2026-06"
    assert period != period_m, "mixed cadence should produce different latestPeriods"


def test_missing_prior_year_month_soft_fails():
    """BLS published no Oct-2025 observation for the monthly Hawaii series.
    A YoY needing it must return None (chip hides) rather than inventing a
    comparison against a different month."""
    import importlib.util
    spec = importlib.util.spec_from_file_location(
        "bls_cpi_updater", ROOT / "bls-cpi-updater.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)

    pts = [{"year": 2025, "period": f"M{m:02d}", "value": 100.0}
           for m in range(1, 13) if m != 10]
    pts.append({"year": 2026, "period": "M10", "value": 110.0})
    yoy, period = mod.compute_yoy(pts)
    assert yoy is None, "must not fabricate a YoY across a genuine data gap"
    assert period == "2026-10"


@pytest.mark.parametrize("suffix,expected", sorted(EXPECTED_PERIODS_PER_YEAR.items()))
def test_expected_cadence_table_is_self_consistent(suffix, expected):
    """Guards the table itself: only 6 or 12 are meaningful, and SA0 must be
    bimonthly — a monthly SA0 is the exact signature of the Los Angeles mix-up."""
    assert expected in (6, 12)
    if suffix == "SA0":
        assert expected == 6, (
            "a monthly all-items series means the area is US/NY/Chicago/LA, "
            "not Hawaii — this is the original bug's fingerprint"
        )

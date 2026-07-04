"""Plausibility bounds (ha_common/sanity.py): range logic + live-data fit.

The bounds exist to catch parser breakage (order-of-magnitude mis-parses),
not to police the economy — so the key contracts are: absent/None fields
never trip a scan (soft-fail stays soft), present-but-implausible values
always do, and the committed dashboard snapshot fits every housing bound.
"""
import json
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from ha_common.sanity import (  # noqa: E402
    BEDROOM_RENT_BOUNDS,
    CPI_YOY_BOUNDS,
    GAS_BOUNDS,
    GROCERY_BOUNDS,
    HOUSING_BOUNDS,
    SanityError,
    check_range,
    scan_record,
)


# ---------------- check_range ----------------

def test_in_range_returns_value():
    assert check_range("x", 5.65, 2.0, 12.0) == 5.65


def test_bounds_are_inclusive():
    assert check_range("x", 2.0, 2.0, 12.0) == 2.0
    assert check_range("x", 12.0, 2.0, 12.0) == 12.0


def test_out_of_range_raises():
    with pytest.raises(SanityError, match=r"x=56\.5 outside plausible"):
        check_range("x", 56.5, 2.0, 12.0)


def test_none_allowed_by_default():
    assert check_range("x", None, 2.0, 12.0) is None


def test_none_rejected_when_required():
    with pytest.raises(SanityError, match="missing"):
        check_range("x", None, 2.0, 12.0, allow_none=False)


def test_non_numeric_raises():
    with pytest.raises(SanityError, match="not numeric"):
        check_range("x", "N/A", 2.0, 12.0)


# ---------------- scan_record ----------------

def test_scan_skips_absent_and_none_fields():
    assert scan_record("gas.Maui", {"regular": None}, GAS_BOUNDS) == []
    assert scan_record("gas.Maui", {}, GAS_BOUNDS) == []


def test_scan_collects_every_violation():
    bad = {"regular": 56.66, "diesel": 0.75, "mom_change": -0.011}
    problems = scan_record("gas.Maui", bad, GAS_BOUNDS)
    assert len(problems) == 2
    assert any("gas.Maui.regular" in p for p in problems)
    assert any("gas.Maui.diesel" in p for p in problems)


def test_scan_ignores_unbounded_fields():
    assert scan_record("gas.State", {"all_grades": {"current": {}}}, GAS_BOUNDS) == []


# ---------------- bounds fit the live data ----------------

def test_committed_dashboard_snapshot_passes_housing_bounds():
    data = json.loads((ROOT / "data" / "dashboard.json").read_text())
    for cty in ("State", "Honolulu", "Maui", "Hawaii", "Kauai"):
        row = data.get(cty) or {}
        assert scan_record(cty, row, HOUSING_BOUNDS) == []
        for tier, val in (row.get("bedroomRent") or {}).items():
            check_range(f"{cty}.bedroomRent.{tier}", val, *BEDROOM_RENT_BOUNDS)


def test_order_of_magnitude_price_error_is_caught():
    data = json.loads((ROOT / "data" / "dashboard.json").read_text())
    row = dict(data["Honolulu"])
    row["sfhPrice"] = row["sfhPrice"] * 10          # $11.5M median: parser bug
    problems = scan_record("Honolulu", row, HOUSING_BOUNDS)
    assert any("sfhPrice" in p for p in problems)


def test_typical_values_pass_all_bound_tables():
    assert scan_record("g", {"regular": 5.65, "diesel": 7.1, "yoy_change": 1.2},
                       GAS_BOUNDS) == []
    assert scan_record("gr", {"basketWithTax": 180.35, "monthlyFamily4": 782,
                              "groceryIdx": 100.4, "groceryShareOfIncome": 0.076},
                       GROCERY_BOUNDS) == []
    for key, yoy in (("allItems", 3.68), ("shelter", 2.8), ("food", 4.27),
                     ("energy", 24.53), ("transport", 10.45)):
        check_range(f"cpi.{key}", yoy, *CPI_YOY_BOUNDS[key])

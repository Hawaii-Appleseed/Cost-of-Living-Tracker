"""Freshness gate (scripts/check_freshness.py): anchor + budget logic.

Covers the three layers: (1) generatedAt must be recent against the wall
clock so a frozen pipeline can't self-anchor, (2) snapshot metric periods
vs generatedAt, (3) HTML-only data blocks (gas/grocery/CPI/TFP) vs the
wall clock, including the null-block case a soft-failed updater writes.
"""
import importlib.util
from pathlib import Path

_spec = importlib.util.spec_from_file_location(
    "check_freshness",
    Path(__file__).resolve().parent.parent / "scripts" / "check_freshness.py",
)
cf = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(cf)


TODAY = (2026, 7)


def snapshot(generated="2026-07-01", housing="2026-06", bls="2026-05",
             zori="2026-06", rent="2026-06"):
    return {
        "_meta": {
            "generatedAt": generated,
            "housingPeriod": housing,
            "blsRentPeriod": bls,
            "zoriPeriod": zori,
        },
        "State": {"rentAsOf": rent},
        "Honolulu": {"rentAsOf": rent},
    }


def html_blocks(gas="2026-07", grocery="2026-07", cpi="2026-06", tfp="2026-06",
                null_cpi=False):
    cpi_body = "const cpiData = null;" if null_cpi else (
        f'allItems: {{ yoy: 3.7, latestPeriod: "{cpi}" }},\n'
        f'shelter:  {{ yoy: 2.8, latestPeriod: "{cpi}" }},'
    )
    return f"""
/* CPI_DATA_START */
{cpi_body}
/* CPI_DATA_END */
/* TFP_DATA_START */
hawaii: {{ family4Monthly: 1575.69, latestPeriod: "{tfp}", originalPeriod: "2025-12" }},
us48:   {{ family4Monthly: 1013.20, latestPeriod: "{tfp}" }},
/* TFP_DATA_END */
/* GROCERY_DATA_START */
State: {{ lastUpdated:"{grocery}-15", pumd:{{ asOf:"2024-12" }} }},
/* GROCERY_DATA_END */
/* GAS_DATA_START */
State:    {{ regular:5.653, asOf:"{gas}-22" }},
Honolulu: {{ regular:5.622, asOf:"{gas}-22" }},
/* GAS_DATA_END */
"""


# ---------------- _months_between ----------------

def test_months_between_same_month():
    assert cf._months_between("2026-07", TODAY) == 0


def test_months_between_across_year():
    assert cf._months_between("2025-11", TODAY) == 8


def test_months_between_truncates_full_dates():
    assert cf._months_between("2026-05-22", TODAY) == 2


def test_months_between_garbage_is_none():
    assert cf._months_between("n/a", TODAY) is None
    assert cf._months_between(None, TODAY) is None


# ---------------- extract_html_periods ----------------

def test_extracts_all_four_blocks():
    periods = cf.extract_html_periods(html_blocks())
    assert periods["gas"] == ["2026-07", "2026-07"]
    assert periods["grocery"] == ["2026-07"]
    assert periods["cpi"] == ["2026-06", "2026-06"]
    assert periods["tfp"] == ["2026-06", "2026-06"]


def test_grocery_pumd_asof_not_mistaken_for_period():
    # pumd.asOf ("2024-12") must not be picked up as the grocery period.
    periods = cf.extract_html_periods(html_blocks())
    assert "2024-12" not in periods["grocery"]


def test_tfp_original_period_not_mistaken_for_period():
    periods = cf.extract_html_periods(html_blocks())
    assert "2025-12" not in periods["tfp"]


def test_missing_block_is_none_null_block_is_empty():
    periods = cf.extract_html_periods(html_blocks(null_cpi=True))
    assert periods["cpi"] == []
    periods = cf.extract_html_periods("<html>no tagged blocks</html>")
    assert all(v is None for v in periods.values())


# ---------------- run_checks: everything fresh ----------------

def test_all_fresh_passes():
    stale, checked = cf.run_checks(snapshot(), html_blocks(), TODAY)
    assert stale == []
    # generatedAt + 3 meta periods + 2 county rentAsOf + 4 html blocks
    assert checked == 10


def test_no_html_skips_html_checks():
    stale, checked = cf.run_checks(snapshot(), None, TODAY)
    assert stale == []
    assert checked == 6


# ---------------- layer 1: generatedAt wall-clock anchor ----------------

def test_frozen_snapshot_fails_even_with_self_consistent_periods():
    # Pipeline died in April: every metric is fresh *relative to* the frozen
    # generatedAt, which is exactly the self-anchoring hole being closed.
    data = snapshot(generated="2026-04-11", housing="2026-03", bls="2026-02",
                    zori="2026-03", rent="2026-03")
    stale, _ = cf.run_checks(data, html_blocks(), TODAY)
    assert any("generatedAt" in s and "stopped writing" in s for s in stale)


def test_last_months_snapshot_is_fine():
    stale, _ = cf.run_checks(snapshot(generated="2026-06-11"),
                             html_blocks(), TODAY)
    assert stale == []


def test_missing_generated_at_is_flagged_and_falls_back_to_wall_clock():
    data = snapshot()
    del data["_meta"]["generatedAt"]
    stale, _ = cf.run_checks(data, html_blocks(), TODAY)
    assert any("generatedAt" in s for s in stale)
    # Metric checks still run, anchored to the wall clock.
    assert not any("housingPeriod" in s for s in stale)


# ---------------- layer 2: metric periods vs generatedAt ----------------

def test_stale_housing_period_fails():
    stale, _ = cf.run_checks(snapshot(housing="2026-02"), html_blocks(), TODAY)
    assert any(s.startswith("housingPeriod: 2026-02 is 5 mo old") for s in stale)


def test_missing_meta_period_fails():
    data = snapshot()
    del data["_meta"]["zoriPeriod"]
    stale, _ = cf.run_checks(data, html_blocks(), TODAY)
    assert any("zoriPeriod: MISSING" in s for s in stale)


def test_stale_county_rent_fails():
    stale, _ = cf.run_checks(snapshot(rent="2026-01"), html_blocks(), TODAY)
    assert any("State.rentAsOf" in s for s in stale)
    assert any("Honolulu.rentAsOf" in s for s in stale)


def test_county_without_rent_nowcast_is_allowed():
    data = snapshot()
    del data["Honolulu"]["rentAsOf"]
    stale, _ = cf.run_checks(data, html_blocks(), TODAY)
    assert stale == []


# ---------------- layer 3: HTML blocks vs wall clock ----------------

def test_stale_gas_block_fails():
    stale, _ = cf.run_checks(snapshot(), html_blocks(gas="2026-03"), TODAY)
    assert any(s.startswith("gas: oldest period 2026-03 is 4 mo old") for s in stale)


def test_cpi_within_bimonthly_budget_passes():
    # BLS CPI reference month naturally lags ~2-3 months; budget is 4.
    stale, _ = cf.run_checks(snapshot(), html_blocks(cpi="2026-04"), TODAY)
    assert stale == []


def test_null_cpi_block_fails():
    stale, _ = cf.run_checks(snapshot(), html_blocks(null_cpi=True), TODAY)
    assert any("cpi" in s and "null block" in s for s in stale)


def test_missing_block_markers_fail():
    stale, _ = cf.run_checks(snapshot(), "<html>no tagged blocks</html>", TODAY)
    assert len([s for s in stale if "block missing" in s]) == 4


def test_committed_html_blocks_are_extractable():
    """The real index.html must yield a period for every tagged block, so the
    gate can't silently skip a block that drifted from the expected shape.
    (Deliberately no wall-clock assertion here — the pre-update pytest gate
    must not fail on data the very same run is about to refresh.)"""
    html = (Path(__file__).resolve().parent.parent / "index.html").read_text()
    periods = cf.extract_html_periods(html)
    for name, found in periods.items():
        assert found, f"{name}: no period extracted from index.html"

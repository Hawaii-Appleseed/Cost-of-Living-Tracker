#!/usr/bin/env python3
"""
Redfin + Zillow + Census + BLS + HUD/DBEDT → Housing Affordability Tracker updater.

Entry point and orchestration only — the source fetchers, nowcast models, and
publishers live in the ha_housing package (see ha_housing/__init__.py for the
module map). This file wires them together:

    _fetch_sale_prices → mortgage rate → _fetch_rents → burden nowcast →
    bedroom tiles → income + construction → derived affordability →
    sanity bounds → patch both HTML files + write data/dashboard.json

Usage:
    python3 redfin-price-updater.py                    # update both HTML files
    python3 redfin-price-updater.py --dry-run          # print changes without writing
    python3 redfin-price-updater.py --file other.html  # target a different file

Sources:
  Redfin:  https://www.redfin.com/news/data-center/
  Zillow:  https://www.zillow.com/research/data/
  DBEDT:   https://dbedt.hawaii.gov/economic/qser/construction/
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from ha_common.sanity import (  # noqa: E402
    BEDROOM_RENT_BOUNDS, HOUSING_BOUNDS, check_range, SanityError, scan_record,
)

# Re-exported names keep the historical single-import surface: tests load this
# file by path (tests/test_blend_rent.py, tests/test_nowcast_refactor.py) and
# docs/METHODOLOGY.md reference these symbols here.
from ha_housing.config import (  # noqa: E402,F401
    BLENDED_RENT_3LEG_WEIGHTS,
    BLENDED_RENT_CPI_WEIGHT,
    BLENDED_RENT_CPI_WEIGHTS,
    CENSUS_ACS_YEAR,
    DEFAULT_FILES,
    MORTGAGE_RATE_PCT,
    RENT_ANCHOR_YEAR,
    ZORI_STATE_POP_WEIGHTS,
)
from ha_housing.redfin import _fetch_sale_prices, download_tsv, extract_hawaii_prices  # noqa: E402,F401
from ha_housing.zori import fetch_zori_asking_rents  # noqa: E402,F401
from ha_housing.census import (  # noqa: E402,F401
    fetch_census_bedroom_rent,
    fetch_census_burden_anchor,
    fetch_census_rent,
    fetch_census_renter_weights,
)
from ha_housing.bls import (  # noqa: E402,F401
    fetch_bls_rent,
    fetch_bls_rent_ratio,
    fetch_bls_series_ratio,
    nowcast_burden_anchors,
)
from ha_housing.nowcast import (  # noqa: E402,F401
    RENT_PASSTHROUGH_LAMBDA,
    RENT_PRODUCTION_METHOD,
    _months_ahead,
    _ym_of,
    audit_rent_nowcast_vs_ntr,
    blend_rent_nowcast,
    extrapolate_ratio_to,
    passthrough_rent_nowcast,
    round_to_25,
)
from ha_housing.gov import (  # noqa: E402,F401
    fetch_dbedt_construction,
    fetch_hhfdc_county_mfi,
    fetch_hud_fmr_ratios,
    fetch_hud_state_mfi,
)
from ha_housing.affordability import compute_derived_affordability, fetch_mortgage_rate  # noqa: E402,F401
from ha_housing.publish import (  # noqa: E402,F401
    _print_summary,
    _write_dashboard_json,
    _write_html,
    patch_html,
    patch_mortgage_rate,
    patch_periods,
)


def _fetch_rents(all_prices: dict) -> tuple[
    float | None,   # bls_ratio
    str   | None,   # bls_rent_period
    float | None,   # bls_rent_yoy
    str   | None,   # zori_period
    dict,           # zori_yoy_map  {countyKey: YoY%}
]:
    """Fetch Census ACS, BLS rent CPI, and Zillow ZORI; merge into *all_prices*.

    Execution order matters:
      1. Census ACS contract rent → sets the RENT_ANCHOR_YEAR dollar anchor
         for all counties.  Must run before BLS scaling so the anchors are
         captured before BLS overwrites the Honolulu value.
      2. BLS rent CPI → scales the ACS anchor to the current month.
      3. ZORI → adds asking-rent and 2024 baseline; drives the blended nowcast.
      4. Blended nowcast → overwrites CPI-only rent with 70/30 composite.

    Returns metadata consumed by downstream callers (period strings for HTML
    patching, YoY floats for the NTR/ATR audit).  All failures are soft-warned;
    the function never raises.
    """
    # ── 1. Census ACS contract rent ──────────────────────────────────────────
    print("\nFetching Census ACS contract rent (existing leases)...")
    try:
        census_rents = fetch_census_rent()
        acs_year = census_rents.pop("_year", CENSUS_ACS_YEAR)
        for key, vals in census_rents.items():
            all_prices.setdefault(key, {}).update(vals)
        print(f"  Got contract rent (ACS {acs_year}) for: {', '.join(census_rents.keys())}")
    except Exception as e:
        print(f"  WARNING: Census rent fetch failed ({e}) — rent will not be updated")

    # Snapshot ACS anchors BEFORE BLS/ZORI scaling overwrites them.
    # Both BLS ratio and ZORI ratio are applied to the same anchor year so the
    # blended formula is dimensionally consistent.
    acs_rent_anchor    = {k: v["rent"] for k, v in all_prices.items() if "rent" in v}
    honolulu_acs_anchor = acs_rent_anchor.get("Honolulu")

    # ── 2. BLS rent CPI ──────────────────────────────────────────────────────
    bls_rent_period   = None
    bls_ratio         = None    # single-month — display fallback only
    bls_ratio_smooth  = None    # 3-mo trailing mean — used for the blend
    bls_rent_yoy      = None
    print("\nFetching BLS CPI rent index (existing tenants, monthly)...")
    try:
        if honolulu_acs_anchor is None:
            raise RuntimeError(
                f"no ACS {RENT_ANCHOR_YEAR} Honolulu anchor — Census fetch must precede BLS scaling"
            )
        bls_rent = fetch_bls_rent(honolulu_acs_anchor)
        bls_rent_period  = bls_rent.pop("_period",          None)
        bls_ratio        = bls_rent.pop("_ratio",           None)
        bls_ratio_smooth = bls_rent.pop("_ratio_smoothed",  None)
        bls_rent_yoy     = bls_rent.pop("_yoy_pct",         None)
        bls_base_avg     = bls_rent.pop("_base_avg",        None)
        bls_points       = bls_rent.pop("_points",          []) or []
        for key, vals in bls_rent.items():
            all_prices.setdefault(key, {}).update(vals)
        # Interim CPI-only rent for every geography (display fallback if the
        # blend/pass-through below can't run; otherwise overwritten by it).
        if bls_ratio:
            for key in ("Maui", "Hawaii", "Kauai", "State"):
                if key in all_prices and "rent" in all_prices[key]:
                    anchor = acs_rent_anchor.get(key, all_prices[key]["rent"])
                    all_prices[key]["rent"] = round(anchor * bls_ratio)
        print(f"  Updated rents to BLS-scaled estimate ({bls_rent_period})")
    except Exception as e:
        bls_base_avg = None
        bls_points = []
        print(f"  WARNING: BLS rent fetch failed ({e}) — rents stay at raw ACS values")

    # ── 3. Zillow ZORI ───────────────────────────────────────────────────────
    zori_period      = None
    zori_anchor_avg  = {}
    zori_yoy_map     = {}
    zori_recent_pts  = {}
    print("\nFetching Zillow ZORI asking rent data...")
    try:
        zori_rents       = fetch_zori_asking_rents()
        zori_period      = zori_rents.pop("_period",      None)
        zori_anchor_avg  = zori_rents.pop("_anchor_avg",  {}) or {}
        zori_anchor_year = zori_rents.pop("_anchor_year", RENT_ANCHOR_YEAR)
        zori_yoy_map     = zori_rents.pop("_yoy_pct",     {}) or {}
        zori_recent_pts  = zori_rents.pop("_recent_points", {}) or {}
        zori_rents.pop("_smoothing_window", None)   # metadata only — not a county
        for key, ask_rent in zori_rents.items():
            all_prices.setdefault(key, {})["askRent"] = ask_rent
        print(f"  Got askRent ({zori_period or '?'}) for: {', '.join(zori_rents.keys())}")
    except Exception as e:
        print(f"  WARNING: Zillow ZORI fetch failed ({e}) — askRent will not be updated")
        zori_anchor_year = RENT_ANCHOR_YEAR

    # ── 3.5 HUD Fair Market Rent (county-specific 3rd leg, targeted) ──────────
    # Only Hawaiʻi & Kauaʻi get an FMR leg (see BLENDED_RENT_3LEG_WEIGHTS). The
    # fetch is fully soft-failing: an empty dict here just means those two
    # counties fall back to their 2-leg CPI/ZORI blend below.
    print("\nFetching HUD Fair Market Rent (county-specific blend leg)...")
    fmr_ratios = fetch_hud_fmr_ratios(RENT_ANCHOR_YEAR)
    fmr_window = ""
    if fmr_ratios:
        fmr_window = f"{fmr_ratios.pop('_anchor_fy', '?')}→{fmr_ratios.pop('_latest_fy', '?')}"
        print(f"  HUD FMR 2-BR growth ({fmr_window}): "
              + ", ".join(f"{k} {v:.3f}" for k, v in fmr_ratios.items()))

    # ── 3.6 Renter-household weights for the State aggregate (item 7) ─────────
    print("\nFetching ACS renter-household weights (B25003) for State aggregate...")
    renter_weights = fetch_census_renter_weights()

    # ── 4. Rent nowcast — target-month-aligned legs, model-selected ──────────
    # (a) Pick ONE target month = the freshest of the BLS-rent and ZORI months,
    #     so both legs share a single endpoint instead of each ending at its own
    #     latest print (item 3).
    # (b) Build the CPI leg factor (Honolulu rent CPI, applied statewide) and the
    #     per-county ZORI factor AT that target month via damped extrapolation.
    # (c) Combine via RENT_PRODUCTION_METHOD: the legacy convex blend or the
    #     log-space pass-through (item 4). Both are computed for logging.
    # (d) State is a renter-household-weighted aggregate of the county nowcasts
    #     (item 7), not an independent blend.
    # (e) Each county records rentMethod + rentAsOf; the dollar value is rounded
    #     to the nearest $25 (item 8). Falls back to CPI-only when inputs miss.
    blend_bls_ratio = bls_ratio_smooth if bls_ratio_smooth is not None else bls_ratio
    if blend_bls_ratio and zori_anchor_avg and bls_rent_period and zori_period:
        bls_ym, zori_ym = _ym_of(bls_rent_period), _ym_of(zori_period)
        target_ym  = max(bls_ym, zori_ym)
        rent_as_of = f"{target_ym[0]:04d}-{target_ym[1]:02d}"

        # CPI leg factor at target. Keep the 3-mo-smoothed (denoised) ratio when
        # BLS already reaches the target; only extrapolate when target is beyond.
        if _months_ahead(bls_ym, target_ym) <= 0:
            cpi_factor = blend_bls_ratio
        else:
            cpi_factor = extrapolate_ratio_to(bls_points, bls_base_avg, target_ym) or blend_bls_ratio

        # Per-county ZORI factor at target (extrapolate each county's series).
        zori_factors: dict[str, float] = {}
        for key in ("Honolulu", "Maui", "Hawaii", "Kauai"):
            base, pts = zori_anchor_avg.get(key), zori_recent_pts.get(key)
            if base and pts:
                r = extrapolate_ratio_to(pts, base, target_ym)
                if r is not None:
                    zori_factors[key] = r
        # Renter-weighted state ZORI factor — proxy for counties lacking a baseline.
        wmap = renter_weights or ZORI_STATE_POP_WEIGHTS
        present = {k: wmap[k] for k in wmap if k in zori_factors}
        proxy = (sum(zori_factors[k] * w for k, w in present.items()) / sum(present.values())
                 if present else None)
        if proxy is not None:
            for key in ("Honolulu", "Maui", "Hawaii", "Kauai"):
                if key not in zori_factors and (all_prices.get(key) or {}).get("askRent"):
                    zori_factors[key] = proxy
                    print(f"  {key}: no {zori_anchor_year} ZORI baseline — "
                          f"using renter-weighted state factor {proxy:.4f} as proxy")

        print(f"\nComputing rent nowcast → target {rent_as_of}, "
              f"method={RENT_PRODUCTION_METHOD}, cpi_factor={cpi_factor:.4f}...")
        for key in ("Honolulu", "Maui", "Hawaii", "Kauai"):
            v = all_prices.get(key)
            if not v or key not in acs_rent_anchor or key not in zori_factors:
                continue
            anchor, zf, fmr_r = acs_rent_anchor[key], zori_factors[key], fmr_ratios.get(key)
            w3 = BLENDED_RENT_3LEG_WEIGHTS.get(key)
            if w3 and fmr_r is not None:
                b = blend_rent_nowcast(anchor, cpi_factor, zf, cpi_weight=w3["cpi"],
                                       zori_weight=w3["zori"], fmr_ratio=fmr_r, fmr_weight=w3["fmr"])
                blend_method = "cpi+zori+fmr"
            else:
                b = blend_rent_nowcast(anchor, cpi_factor, zf,
                                       cpi_weight=BLENDED_RENT_CPI_WEIGHTS.get(key, 0.7))
                blend_method = "cpi+zori"
            pt = passthrough_rent_nowcast(anchor, cpi_factor, zf)
            if RENT_PRODUCTION_METHOD == "passthrough":
                v["rent"], v["rentMethod"] = round_to_25(pt["passthrough"]), "passthrough"
            else:
                v["rent"], v["rentMethod"] = round_to_25(b["blended"]), blend_method
            v["rentAsOf"] = rent_as_of
            print(f"  {key:<9} CPI ${b['cpi_scaled']:>5,}  ZORI ${b['zori_implied']:>5,}  "
                  f"blend ${b['blended']:>5,}  passthrough ${pt['passthrough']:>5,}  "
                  f"→ rent ${v['rent']:>5,} ({v['rentMethod']})")

        # State = renter-household-weighted aggregate of the county nowcasts.
        county_rents = {k: all_prices[k]["rent"] for k in ("Honolulu", "Maui", "Hawaii", "Kauai")
                        if all_prices.get(k, {}).get("rent")}
        wmap_s = renter_weights or {k: ZORI_STATE_POP_WEIGHTS[k]
                                    for k in ("Honolulu", "Maui", "Hawaii", "Kauai")}
        present_s = {k: wmap_s[k] for k in wmap_s if k in county_rents}
        if present_s:
            state_rent = (sum(county_rents[k] * w for k, w in present_s.items())
                          / sum(present_s.values()))
            sv = all_prices.setdefault("State", {})
            sv["rent"] = round_to_25(state_rent)
            sv["rentMethod"] = "renter-wtd of counties" if renter_weights else "pop-wtd of counties"
            sv["rentAsOf"] = rent_as_of
            print(f"  State     = {'renter' if renter_weights else 'pop'}-weighted aggregate "
                  f"of counties → rent ${sv['rent']:,}")
    else:
        print("  Skipping rent nowcast (missing BLS ratio, ZORI baseline, or periods) — "
              "marking any CPI-only rent as fallback")
        for key in ("Honolulu", "Maui", "Hawaii", "Kauai", "State"):
            v = all_prices.get(key)
            if v and v.get("rent"):
                v["rent"] = round_to_25(v["rent"])
                v.setdefault("rentMethod", "cpi-only-fallback")
                if bls_rent_period:
                    v.setdefault("rentAsOf", bls_rent_period)

    # ── 5. Export per-county YoY signals to countyData (Q2) ─────────────────
    # ZORI YoY is per-county; BLS rent CPI is Honolulu-only so we attach it
    # to the State row and Honolulu (where it's genuine) but not outer islands
    # (where it's regional proxy — shown via per-county ZORI instead).
    for key in ("Honolulu", "Maui", "Hawaii", "Kauai", "State"):
        y = zori_yoy_map.get(key)
        if y is not None:
            all_prices.setdefault(key, {})["zoriYoY"] = round(y / 100.0, 4)
    if bls_rent_yoy is not None:
        for key in ("State", "Honolulu"):
            all_prices.setdefault(key, {})["cpiRentYoY"] = round(bls_rent_yoy / 100.0, 4)

    return bls_ratio, bls_rent_period, bls_rent_yoy, zori_period, zori_yoy_map


def _fetch_income_and_construction(all_prices: dict) -> str:
    """Fetch HHFDC county MFI, HUD state MFI, and DBEDT build auth; merge into *all_prices*.

    Returns the DBEDT period string (e.g. "2025") for use in the summary table.
    All three fetches are soft-warned on failure — the function never raises.
    """
    print("\nFetching HHFDC county median family incomes (HUD FY 2025)...")
    try:
        hhfdc_incomes = fetch_hhfdc_county_mfi()
        hhfdc_incomes.pop("_period", None)
        for key, vals in hhfdc_incomes.items():
            all_prices.setdefault(key, {}).update(vals)
        print(f"  Got income for: {', '.join(hhfdc_incomes.keys())}")
    except Exception as e:
        print(f"  WARNING: HHFDC income fetch failed ({e}) — county income will not be updated")

    print("\nFetching HUD state median family income...")
    try:
        state_income = fetch_hud_state_mfi()
        state_income.pop("_period", None)
        for key, vals in state_income.items():
            all_prices.setdefault(key, {}).update(vals)
        print(f"  Got income for: {', '.join(state_income.keys())}")
    except Exception as e:
        print(f"  WARNING: HUD state income fetch failed ({e}) — state income will not be updated")

    build_period = "?"
    print("\nFetching DBEDT construction authorization data...")
    try:
        dbedt_data = fetch_dbedt_construction()
        build_period = dbedt_data.pop("_period", "?")
        for key, build_auth in dbedt_data.items():
            all_prices.setdefault(key, {})["buildAuth"] = build_auth
        print(f"  Got buildAuth ({build_period}) for: {', '.join(dbedt_data.keys())}")
    except Exception as e:
        print(f"  WARNING: DBEDT construction fetch failed ({e}) — buildAuth will not be updated")

    return build_period


def main():
    dry_run  = "--dry-run" in sys.argv
    file_idx = sys.argv.index("--file") + 1 if "--file" in sys.argv else None
    targets  = [Path(sys.argv[file_idx])] if file_idx else DEFAULT_FILES

    all_prices = _fetch_sale_prices()

    # Live 30-yr fixed mortgage rate (Freddie Mac PMMS via FRED). Single source
    # of truth for BOTH the price-derived idx/gap/PTI literals and the HTML
    # rate-slider default, so they agree at first paint. Falls back to
    # MORTGAGE_RATE_PCT when FRED_API_KEY is unset or the fetch fails.
    print("\nFetching live 30-yr fixed mortgage rate (FRED MORTGAGE30US)...")
    mortgage_rate = fetch_mortgage_rate()

    _, bls_rent_period, bls_rent_yoy, zori_period, zori_yoy_map = _fetch_rents(all_prices)

    # ── Realized-burden anchor + nowcast (renter GRAPI, owner SMOCAPI,
    #    cost-burden share). Pulls ACS 5-year anchor, nowcasts to current
    #    period using BLS rent / all-items / Hawaiʻi wages, then merges
    #    into all_prices so patch_html() writes the new fields. Failure
    #    is non-fatal — fields stay at whatever values are currently in
    #    the HTML (last good nowcast).
    print("\nFetching realized-burden anchor (ACS B25071 / B25092 / B25070 / B25091)...")
    burden = fetch_census_burden_anchor()
    if burden:
        burden = nowcast_burden_anchors(burden, str(CENSUS_ACS_YEAR))
        for key in ("State", "Honolulu", "Maui", "Hawaii", "Kauai"):
            row = burden.get(key) or {}
            target = all_prices.setdefault(key, {})
            for field in ("tenantRentPTI", "mortgageOwnerPTI",
                          "rentBurdenedPct", "rentSeverelyBurdenedPct",
                          "ownerBurdenedPct", "ownerSeverelyBurdenedPct"):
                if row.get(field) is not None:
                    target[field] = row[field]
        nowcast_period = burden.get("_nowcastPeriod")
        if nowcast_period:
            print(f"  Realized-burden nowcast period: {nowcast_period}")

    # ── Per-bedroom price tiles (ACS B25068). Soft-warn on failure —
    #    the dashboard's renderBedroomTiles() falls back to "—" when
    #    bedroomRent is missing/null.
    print("\nFetching Census ACS bedroom rent (B25031)...")
    bedroom = fetch_census_bedroom_rent()
    if bedroom:
        bedroom.pop("_year", None)
        for key, vals in bedroom.items():
            all_prices.setdefault(key, {}).update(vals)

    # Dev-facing NTR/ATR sanity check (prints table, warns on large divergence).
    audit_rent_nowcast_vs_ntr(
        hnl_cpi_yoy  = bls_rent_yoy,
        hnl_zori_yoy = zori_yoy_map.get("Honolulu"),
    )

    build_period = _fetch_income_and_construction(all_prices)

    # Recompute price-derived affordability metrics (idx/gap/mortgage/PTI) so
    # they track the freshly smoothed prices + incomes instead of drifting.
    # Uses the live FRED rate (same value patched into the slider default).
    compute_derived_affordability(all_prices, mortgage_rate)

    _print_summary(all_prices, build_period)

    # Refuse to publish implausible values — one mis-parsed column upstream
    # (Redfin TSV, Census JSON, HUD XLSX/PDF) would otherwise ship an
    # order-of-magnitude-wrong number under a fresh "As of" label. Absent /
    # None fields are fine: soft-failed fetches leave fields out so the HTML
    # keeps its last-good value.
    sanity_problems: list[str] = []
    for cty in ("State", "Honolulu", "Maui", "Hawaii", "Kauai"):
        row = all_prices.get(cty) or {}
        sanity_problems += scan_record(cty, row, HOUSING_BOUNDS)
        for tier, val in (row.get("bedroomRent") or {}).items():
            try:
                check_range(f"{cty}.bedroomRent.{tier}", val, *BEDROOM_RENT_BOUNDS)
            except SanityError as exc:
                sanity_problems.append(str(exc))
    if sanity_problems:
        print("\nERROR: sanity check failed — refusing to patch or write the snapshot:")
        for p in sanity_problems:
            print(f"  ✗ {p}")
        sys.exit(1)

    housing_period = (all_prices.get("State", {}).get("period") or "")[:7] or None

    # Run the patchers in both modes so a dry-run still validates that every
    # field (incl. the rentMethod/rentAsOf string stubs) can be written.
    misses = _write_html(targets, all_prices, zori_period, bls_rent_period,
                         housing_period, dry_run, mortgage_rate)

    if dry_run:
        tail = f" ({len(misses)} patch misses: {', '.join(misses)})" if misses else ""
        print(f"\n--dry-run: no files modified{tail}")
        return

    # ── Source-of-truth JSON artifact (item 1) ──────────────────────────────
    # The dashboard stays self-contained (data is inlined into the HTML by the
    # patchers above — the Squarespace single-file embed can't fetch at
    # runtime), but we ALSO emit a diffable JSON snapshot with per-metric asOf.
    # scripts/check_freshness.py reads this to fail CI on stale data.
    _write_dashboard_json(all_prices, {
        "housingPeriod": housing_period,
        "blsRentPeriod": bls_rent_period,
        "zoriPeriod":    zori_period,
        "buildPeriod":   build_period,
        "mortgageRate":  mortgage_rate,
    })

    if misses:
        print(f"\nERROR: {len(misses)} field(s) could not be patched into the HTML — "
              f"refusing to ship a partially-updated dashboard:\n  " + "\n  ".join(misses))
        sys.exit(1)


if __name__ == "__main__":
    main()

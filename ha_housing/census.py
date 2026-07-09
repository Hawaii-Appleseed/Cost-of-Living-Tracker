"""Census ACS fetches: contract rent, renter weights, bedroom rent, burden."""
# Extracted from redfin-price-updater.py — see that file's docstring for the
# pipeline overview. Behavior-preserving split; function bodies are unchanged.
from ha_common.http_client import fetch_bytes

from .config import (
    CENSUS_ACS_YEAR, CENSUS_API_KEY, CENSUS_BASE_URL, CENSUS_BURDEN_VARS,
    CENSUS_NAME_MAP, CENSUS_RENT_VAR, COUNTY_ANCHOR_OVERRIDE,
)


def _census_base_url(variant: str = "acs5", year: str = CENSUS_ACS_YEAR) -> str:
    """Build the Census ACS endpoint URL for a given variant (acs5 / acs1).

    The vintage YEAR stays the same — Census publishes both 1-yr and 5-yr
    estimates dated to the same end year. Variant just toggles the sample
    window (1-yr is more responsive; 5-yr is smoother and covers smaller
    geographies). 1-yr is only published for areas with ≥65k population.
    """
    return f"https://api.census.gov/data/{year}/acs/{variant}"


def fetch_census_rent() -> dict:
    """
    Download median contract rent (B25058_001E) for Hawaii state + 4 counties.

    A 5-year base is pulled first for every geography, then each geography in
    COUNTY_ANCHOR_OVERRIDE (now ALL five — see the constant) is re-fetched at
    ACS 1-year and overwrites the 5-yr value. The 1-yr level is a true 2024
    level aligned with the calendar-2024 growth factors; the 5-yr (a ~2022
    level) is kept only as a per-geography fallback when a 1-yr cell is
    suppressed or the fetch fails.

    Contract rent excludes utilities — directly comparable to Zillow ZORI.
    Returns {countyKey: {rent: int, rentAnchorVariant: "acs5"|"acs1"}}
    plus '_year' metadata.
    """
    import json

    def _get(url):
        return json.loads(fetch_bytes(url))

    key_qs = f"&key={CENSUS_API_KEY}" if CENSUS_API_KEY else ""

    # ── 1. Base 5-yr pull for everyone (state + all 4 counties) ─────────
    base_5yr   = _census_base_url("acs5")
    state_url  = f"{base_5yr}?get={CENSUS_RENT_VAR}&for=state:15{key_qs}"
    county_url = f"{base_5yr}?get={CENSUS_RENT_VAR},NAME&for=county:*&in=state:15{key_qs}"

    print(f"  Fetching Census ACS 5-yr {CENSUS_ACS_YEAR} contract rent (B25058_001E)...")
    state_data  = _get(state_url)
    county_data = _get(county_url)

    result = {"_year": CENSUS_ACS_YEAR}

    # State row: [header, data_row]
    s_hdr, s_row = state_data[0], state_data[1]
    result["State"] = {"rent": int(s_row[s_hdr.index(CENSUS_RENT_VAR)]),
                       "rentAnchorVariant": "acs5"}

    # County rows
    c_hdr, *c_rows = county_data
    rent_idx = c_hdr.index(CENSUS_RENT_VAR)
    name_idx = c_hdr.index("NAME")
    # Hawaii FIPS county codes for the 1-yr per-county query (county:* with
    # acs1 returns only ≥65k counties, but for explicit per-county fetches
    # we use the numeric code).
    county_fips = {"Honolulu": "003", "Hawaii": "001", "Maui": "009", "Kauai": "007"}
    for row in c_rows:
        key = CENSUS_NAME_MAP.get(row[name_idx])
        if key:
            result[key] = {"rent": int(row[rent_idx]), "rentAnchorVariant": "acs5"}

    # ── 2. 1-yr overrides for every geography in COUNTY_ANCHOR_OVERRIDE ──
    # State uses for=state:15; counties use for=county:<fips>. Each is fetched
    # independently and falls back to the 5-yr value already in `result` on a
    # suppressed cell or any error.
    for geo, variant in COUNTY_ANCHOR_OVERRIDE.items():
        if variant != "acs1":
            continue
        if geo == "State":
            url = f"{_census_base_url('acs1')}?get={CENSUS_RENT_VAR}&for=state:15{key_qs}"
        elif geo in county_fips:
            url = (f"{_census_base_url('acs1')}?get={CENSUS_RENT_VAR},NAME"
                   f"&for=county:{county_fips[geo]}&in=state:15{key_qs}")
        else:
            continue
        try:
            data = _get(url)
            hdr, *rows = data
            if rows:
                r_idx = hdr.index(CENSUS_RENT_VAR)
                v_raw = rows[0][r_idx]
                v = int(v_raw) if v_raw and v_raw not in ("-", "null") and int(v_raw) > 0 else None
                if v is not None:
                    result.setdefault(geo, {})
                    prev = result[geo].get("rent")
                    result[geo]["rent"] = v
                    result[geo]["rentAnchorVariant"] = "acs1"
                    pf = f" (was 5-yr ${prev:,})" if prev else ""
                    print(f"  → {geo}: ACS 1-yr {CENSUS_ACS_YEAR} anchor ${v:,}{pf}")
                else:
                    print(f"  WARNING: {geo} 1-yr anchor returned suppressed value; "
                          f"falling back to 5-yr ${result.get(geo, {}).get('rent', '?')}")
        except Exception as e:
            print(f"  WARNING: {geo} 1-yr anchor fetch failed ({e}); "
                  f"keeping 5-yr ${result.get(geo, {}).get('rent', '?')}")

    return result


# ACS B25003 — tenure. _003E = renter-occupied housing units. Used to build
# the renter-household weights that aggregate per-county rent nowcasts into the
# State figure (Q-audit item 7), replacing the old hardcoded total-population
# weights (which mis-weighted a renter quantity, over-counting low-renter-share
# neighbor islands). 5-yr is fine here — these counts are slow-moving and the
# 5-yr avoids small-cell noise.
CENSUS_RENTER_VAR = "B25003_003E"


def fetch_census_renter_weights() -> dict:
    """Return {countyKey: renter_household_share} normalized over the 4 counties.

    Pulls ACS 5-yr renter-occupied household counts (B25003_003E) for the four
    counties and returns each county's share of the statewide renter total, so
    State rent = Σ_c share_c · county_rent. Returns {} on any failure (caller
    falls back to the legacy ZORI_STATE_POP_WEIGHTS).
    """
    import json
    if not CENSUS_API_KEY:
        print("  WARNING: CENSUS_API_KEY not set; skipping renter-weight fetch "
              "(State will use legacy population weights).")
        return {}
    url = (f"{_census_base_url('acs5')}?get={CENSUS_RENTER_VAR},NAME"
           f"&for=county:*&in=state:15&key={CENSUS_API_KEY}")
    try:
        data = json.loads(fetch_bytes(url))
    except (OSError, json.JSONDecodeError) as e:
        print(f"  WARNING: renter-weight fetch failed ({e}); using legacy weights.")
        return {}
    hdr, *rows = data
    v_idx, n_idx = hdr.index(CENSUS_RENTER_VAR), hdr.index("NAME")
    counts = {}
    for row in rows:
        key = CENSUS_NAME_MAP.get(row[n_idx])
        try:
            if key and int(row[v_idx]) > 0:
                counts[key] = int(row[v_idx])
        except (TypeError, ValueError):
            continue
    total = sum(counts.values())
    if not total:
        return {}
    weights = {k: c / total for k, c in counts.items()}
    print("  Renter-household weights (B25003): "
          + ", ".join(f"{k} {w:.3f}" for k, w in weights.items()))
    return weights


def fetch_census_bedroom_rent() -> dict:
    """
    Fetch median gross rent by bedroom count (ACS 5-year table B25031
    "Median Gross Rent by Bedrooms"). Direct medians, one variable per
    bedroom bucket:

      B25031_001E — Total median gross rent (all units)
      B25031_002E — No bedroom (studio / 0 BR)
      B25031_003E — 1 bedroom
      B25031_004E — 2 bedrooms
      B25031_005E — 3 bedrooms
      B25031_006E — 4 bedrooms
      B25031_007E — 5+ bedrooms

    Gross rent INCLUDES utilities (different from B25058 contract rent).
    We collapse 3/4/5+ into a single "3+ BR" tile since 4-BR and 5+-BR
    cells are often suppressed or have wide MoEs in smaller counties.

    Returns {countyKey: {bedroomRent: {br0, br1, br2, br3plus}}} plus
    "_year" metadata. Missing/suppressed cells become None and are
    rendered as "—" in the UI. Silent failure when CENSUS_API_KEY is
    unset — the field already has a graceful "no data" fallback.
    """
    import json
    if not CENSUS_API_KEY:
        print(f"  WARNING: CENSUS_API_KEY not set; skipping bedroom rent fetch.")
        return {}

    bedroom_vars = ["B25031_002E", "B25031_003E", "B25031_004E",
                    "B25031_005E", "B25031_006E", "B25031_007E"]
    vars_csv = ",".join(bedroom_vars)
    state_url  = f"{_census_base_url('acs5')}?get=NAME,{vars_csv}&for=state:15&key={CENSUS_API_KEY}"
    county_url = f"{_census_base_url('acs5')}?get=NAME,{vars_csv}&for=county:*&in=state:15&key={CENSUS_API_KEY}"

    print(f"  Fetching Census ACS 5-yr {CENSUS_ACS_YEAR} bedroom rent (B25031)...")
    try:
        state_data  = json.loads(fetch_bytes(state_url))
        county_data = json.loads(fetch_bytes(county_url))
    except (OSError, json.JSONDecodeError) as e:
        print(f"  WARNING: bedroom rent fetch failed ({e}); skipping.")
        return {}

    def _val(row, hdr, name):
        raw = row[hdr.index(name)]
        try:
            v = float(raw)
            # ACS sentinel for "estimate not displayed" or suppressed
            return None if v <= 0 or v <= -666666666 else int(round(v))
        except (TypeError, ValueError):
            return None

    def _build(hdr, row):
        br0 = _val(row, hdr, "B25031_002E")
        br1 = _val(row, hdr, "B25031_003E")
        br2 = _val(row, hdr, "B25031_004E")
        # Collapse 3/4/5+ into one tile, averaging non-null medians
        # (smaller counties suppress 4-BR / 5+-BR).
        br3p_vals = [v for v in (
            _val(row, hdr, "B25031_005E"),
            _val(row, hdr, "B25031_006E"),
            _val(row, hdr, "B25031_007E"),
        ) if v is not None]
        br3plus = int(round(sum(br3p_vals) / len(br3p_vals))) if br3p_vals else None
        return {"br0": br0, "br1": br1, "br2": br2, "br3plus": br3plus}

    result = {"_year": CENSUS_ACS_YEAR}
    s_hdr, s_row = state_data[0], state_data[1]
    result["State"] = {"bedroomRent": _build(s_hdr, s_row)}

    c_hdr, *c_rows = county_data
    name_idx = c_hdr.index("NAME")
    for row in c_rows:
        key = CENSUS_NAME_MAP.get(row[name_idx])
        if key:
            result[key] = {"bedroomRent": _build(c_hdr, row)}

    for key in ("State", "Honolulu", "Maui", "Hawaii", "Kauai"):
        br = result.get(key, {}).get("bedroomRent")
        if br:
            parts = [f"{lbl}=${v:,}" if v else f"{lbl}=—"
                     for lbl, v in (("0BR", br["br0"]), ("1BR", br["br1"]),
                                    ("2BR", br["br2"]), ("3+BR", br["br3plus"]))]
            print(f"  {key:<9} {' · '.join(parts)}")

    return result


def fetch_census_burden_anchor() -> dict:
    """
    Fetch the ACS 5-year realized-burden anchor for Hawaiʻi state + 4 counties.

    Pulls B25071 (median GRAPI for renters), B25092 (median SMOCAPI for
    owners with a mortgage), and the cost-burden distributions B25070
    (renters) and B25091 (owners-with-mortgage). Returns a flat dict
    keyed by countyKey with per-county derived metrics. Cost-burden
    shares are computed by collapsing the 30-34.9/35-39.9/40-49.9/≥50
    buckets into "≥30 %" and the ≥50 bucket into "severely burdened",
    excluding the "not computed" pool from the denominator.

    Returns {countyKey: {tenantGRAPI, ownerSMOCAPI,
                         rentBurdenedPct, rentSeverelyBurdenedPct,
                         ownerBurdenedPct, ownerSeverelyBurdenedPct}}
    plus "_year" metadata. Percentages are decimals (0.0–1.0).

    The Census API requires a key as of mid-2025 — silently returns {}
    if CENSUS_API_KEY isn't set so the rest of the pipeline doesn't fail.
    """
    import json
    if not CENSUS_API_KEY:
        print(f"  WARNING: CENSUS_API_KEY not set; skipping realized-burden anchor fetch.")
        return {}

    vars_csv = ",".join(CENSUS_BURDEN_VARS)
    state_url  = f"{CENSUS_BASE_URL}?get=NAME,{vars_csv}&for=state:15&key={CENSUS_API_KEY}"
    county_url = f"{CENSUS_BASE_URL}?get=NAME,{vars_csv}&for=county:*&in=state:15&key={CENSUS_API_KEY}"

    print(f"  Fetching Census ACS {CENSUS_ACS_YEAR} realized-burden anchor (B25071, B25092, B25070, B25091)...")
    try:
        state_data  = json.loads(fetch_bytes(state_url))
        county_data = json.loads(fetch_bytes(county_url))
    except (OSError, json.JSONDecodeError) as e:
        print(f"  WARNING: realized-burden anchor fetch failed ({e}); skipping.")
        return {}

    def _build_row(hdr, row):
        """Compute the 6 dashboard fields from a single census API row."""
        def fv(name, scale=1.0):
            raw = row[hdr.index(name)]
            v = float(raw)
            # ACS sentinel for "estimate not displayed" (Kalawao, etc.)
            return None if v <= -666666666 else v * scale
        graphi   = fv("B25071_001E", 0.01)   # already a %, store as decimal
        smocapi  = fv("B25092_002E", 0.01)
        r_total  = fv("B25070_001E") or 0
        r_notc   = fv("B25070_011E") or 0
        r_b30_34 = fv("B25070_007E") or 0
        r_b35_39 = fv("B25070_008E") or 0
        r_b40_49 = fv("B25070_009E") or 0
        r_b50p   = fv("B25070_010E") or 0
        r_denom  = max(0, r_total - r_notc)
        rent_burdened     = (r_b30_34 + r_b35_39 + r_b40_49 + r_b50p) / r_denom if r_denom else None
        rent_severe       = r_b50p / r_denom if r_denom else None
        o_total  = fv("B25091_002E") or 0
        o_notc   = fv("B25091_010E") or 0
        o_b30_34 = fv("B25091_006E") or 0
        o_b35_39 = fv("B25091_007E") or 0
        o_b40_49 = fv("B25091_008E") or 0
        o_b50p   = fv("B25091_009E") or 0
        o_denom  = max(0, o_total - o_notc)
        owner_burdened    = (o_b30_34 + o_b35_39 + o_b40_49 + o_b50p) / o_denom if o_denom else None
        owner_severe      = o_b50p / o_denom if o_denom else None
        return {
            "tenantGRAPI":             graphi,
            "ownerSMOCAPI":            smocapi,
            "rentBurdenedPct":         rent_burdened,
            "rentSeverelyBurdenedPct": rent_severe,
            "ownerBurdenedPct":        owner_burdened,
            "ownerSeverelyBurdenedPct":owner_severe,
        }

    result = {"_year": CENSUS_ACS_YEAR}
    s_hdr, s_row = state_data[0], state_data[1]
    result["State"] = _build_row(s_hdr, s_row)

    c_hdr, *c_rows = county_data
    for row in c_rows:
        key = CENSUS_NAME_MAP.get(row[c_hdr.index("NAME")])
        if key:
            result[key] = _build_row(c_hdr, row)
    return result

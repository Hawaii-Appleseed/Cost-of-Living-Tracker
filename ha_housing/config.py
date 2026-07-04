"""Shared constants for the housing updater (single home for every knob)."""
# Extracted from redfin-price-updater.py — see that file's docstring for the
# pipeline overview. Behavior-preserving split; function bodies are unchanged.
import os
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent

# ─── CONFIG ─────────────────────────────────────────────────────
STATE_URL  = "https://redfin-public-data.s3.us-west-2.amazonaws.com/redfin_market_tracker/state_market_tracker.tsv000.gz"
COUNTY_URL = "https://redfin-public-data.s3.us-west-2.amazonaws.com/redfin_market_tracker/county_market_tracker.tsv000.gz"
ZORI_URL   = "https://files.zillowstatic.com/research/public_csvs/zori/County_zori_uc_sfrcondomfr_sm_month.csv"
DBEDT_URL  = "https://files.hawaii.gov/dbedt/economic/data_reports/qser/E-construction-tables.xlsx"

# HHFDC county income schedule PDFs (HUD income limits, published by state of Hawaii).
# The "MEDIAN" column in each schedule is HUD's FY2025 4-person median family income.
HHFDC_PDF_TEMPLATE = "https://dbedt.hawaii.gov/hhfdc/files/2025/05/{county}-County-2025.pdf"
HHFDC_COUNTIES     = ["Honolulu", "Hawaii", "Maui", "Kauai"]

# HUD State Income Limits report (FY2025) — contains each state's MFI including HI.
HUD_STATE_IL_URL   = "https://www.huduser.gov/portal/datasets/il/il25/State-Incomelimits-Report-FY25.pdf"
HUD_FY             = "FY 2025"

# DBEDT E-8 column header → countyData key (columns in order: State, Honolulu, Hawaii, Kauai, Maui)
# The header row in the sheet uses newlines inside cell values
DBEDT_COL_KEYS = ["State", "Honolulu", "Hawaii", "Kauai", "Maui"]  # columns 1–5 in E-8

# ─── Affordability assumptions (mirror the dashboard JS) ─────────
# These reproduce calcAffordPrice()/mcardV2() in index.html so the price-
# derived metrics (sfhIdx/sfhGap/sfhMortgage/sfhPTI + condo equivalents)
# are recomputed each run instead of drifting as stale literals.
#
# MORTGAGE_RATE_PCT MUST stay in sync with the rate-slider DEFAULT in the
# HTML (id="rate-slider" value=…). At the default slider position the live
# banner's affordPrice and the stored idx/gap agree; if they diverge the
# stored metrics would contradict the calculator on first paint. These are now
# kept in sync AUTOMATICALLY each run (fetch_mortgage_rate + patch_mortgage_rate).
MORTGAGE_RATE_PCT   = 6.38   # 30-yr fixed, Freddie Mac PMMS — FALLBACK only (see below)
DOWN_PAYMENT_FRAC   = 0.20   # 20% down → LTV 0.80
DTI_FRONT_FRAC      = 0.30   # 30% of gross income to P&I
MORTGAGE_TERM_MONTHS = 360   # 30-year amortization

# fetch_mortgage_rate() pulls the live weekly 30-yr fixed (Freddie Mac PMMS) from
# FRED series MORTGAGE30US and patch_mortgage_rate() writes it into the HTML rate
# slider — so the slider default, the derived idx/gap/PTI literals, and the live
# calculator all share ONE source and no longer need hand-syncing. MORTGAGE_RATE_PCT
# above is the fallback used only when FRED_API_KEY is unset or the fetch fails.
FRED_API_KEY          = os.environ.get("FRED_API_KEY", "")
FRED_MORTGAGE_SERIES  = "MORTGAGE30US"

# ─── Rent anchor year (SINGLE SOURCE OF TRUTH) ──────────────────
# Both the ACS contract-rent dollar anchor and the BLS rent-CPI base-year
# average must align on the same vintage — otherwise the scaling factor
# "BLS(now) / BLS(anchor_year_avg)" applied to "ACS(anchor_year) dollars"
# produces a dollar value that is anchored to a different year than the
# index says. Keep both pointing at the same YEAR constant.
#
# RE-ANCHORING CADENCE (see METHODOLOGY.md): bump this every December
# when a new ACS 5-year vintage is released. Pull the fresh Honolulu
# contract rent directly from the Census API response — no more
# hardcoded dollar values.
RENT_ANCHOR_YEAR = "2024"

# Census ACS — contract rent (B25058_001E, utilities excluded)
CENSUS_ACS_YEAR = RENT_ANCHOR_YEAR
CENSUS_BASE_URL = f"https://api.census.gov/data/{CENSUS_ACS_YEAR}/acs/acs5"
CENSUS_RENT_VAR = "B25058_001E"   # median contract rent (no utilities) — comparable to Zillow ZORI
CENSUS_NAME_MAP = {
    "Honolulu County, Hawaii": "Honolulu",
    "Hawaii County, Hawaii":   "Hawaii",
    "Maui County, Hawaii":     "Maui",
    "Kauai County, Hawaii":    "Kauai",
}

# Census API key (env var). Required for ACS5 calls — Census tightened
# the anonymous policy in 2025; the previous unauthenticated path now
# returns "Missing Key" HTML. Sign up free at
# https://api.census.gov/data/key_signup.html and set as CENSUS_API_KEY
# in GitHub Actions + local env.
CENSUS_API_KEY = os.environ.get("CENSUS_API_KEY", "")

# Realized-burden anchor: ACS B25071 (median GRAPI for renters) +
# B25092 (median SMOCAPI for owners with mortgage) + B25070/B25091
# cost-burden distributions. Pulled from the same 5-year vintage as
# the contract-rent anchor (RENT_ANCHOR_YEAR) so the dashboard's
# "rent" and "burden" numbers describe the same population window.
CENSUS_BURDEN_VARS = [
    "B25071_001E",   # Median GRAPI (renter households, %)
    "B25092_002E",   # Median SMOCAPI for owner-occupied with mortgage (%)
    # B25070 — Gross rent as % of household income (renter distribution)
    "B25070_001E",   # Total renters
    "B25070_007E",   # 30.0 – 34.9 %
    "B25070_008E",   # 35.0 – 39.9 %
    "B25070_009E",   # 40.0 – 49.9 %
    "B25070_010E",   # 50.0 %+
    "B25070_011E",   # Not computed
    # B25091 — Mortgage status × SMOCAPI (owner distribution, with-mortgage rows)
    "B25091_002E",   # With mortgage (total)
    "B25091_006E",   # With mortgage, 30.0 – 34.9 %
    "B25091_007E",   # With mortgage, 35.0 – 39.9 %
    "B25091_008E",   # With mortgage, 40.0 – 49.9 %
    "B25091_009E",   # With mortgage, 50.0 %+
    "B25091_010E",   # With mortgage, not computed
]

# BLS series for nowcasting from the ACS 5-year mid-point to the
# current period. Rent uses Honolulu rent CPI (already fetched
# elsewhere — re-fetched here so the burden pipeline is self-contained).
# Owner SMOCAPI is dominated by sticky locked-in P&I + slow-growing
# tax/ins/util → tracks Honolulu all-items CPI as a stand-in. Income
# uses Hawaii state private avg weekly earnings (CES).
BLS_CPI_ALL_ITEMS_HNL = "CUURS49ASA0"           # Honolulu, all items
BLS_WAGES_HI_PRIVATE  = "SMU15000000500000011"  # Hawaii state private avg weekly earnings (NSA)

# BLS CPI: Honolulu MSA — "Rent of primary residence" (existing tenants, not new leases)
# Series CUURS49ASEHA, not seasonally adjusted, base 1982-84=100.
# We scale the live ACS Honolulu contract rent (fetched each run) by the
# BLS index ratio (latest / anchor-year avg) to get a monthly-current estimate.
BLS_API_URL     = "https://api.bls.gov/publicAPI/v2/timeseries/data/"
BLS_RENT_SERIES = "CUURS49ASEHA"
BLS_BASE_YEAR   = RENT_ANCHOR_YEAR

# NTR/ATR national benchmarks — manually refreshed quarterly from BLS research
# series R-CPI-NTR and R-CPI-ATR. Used only for a dev-facing sanity check on
# the Honolulu rent nowcast (see audit_rent_nowcast_vs_ntr below). Not read by
# the dashboard UI. See METHODOLOGY.md § Quarterly NTR/ATR benchmark refresh.
NTR_ATR_BENCHMARKS_PATH = PROJECT_ROOT / "data" / "ntr_atr_benchmarks.json"

# Blended rent nowcast — per-county weights for combining the lagging BLS
# rent CPI with Zillow ZORI's leading asking-rent signal. Both series are
# growth factors vs. RENT_ANCHOR_YEAR applied to the same ACS dollar anchor:
#   blended_rent = acs_anchor × (cpi_w · bls_ratio + (1−cpi_w) · zori_ratio)
#
# The BLS Honolulu rent index (CUURS49ASEHA) is a Honolulu-only sample —
# applying it to neighbor islands at the same 70% weight implies that
# Honolulu rent dynamics are a reliable proxy for Maui/Hawaiʻi/Kauaʻi,
# which is methodologically weak. Outer islands get 50/50 so the only
# county-specific signal (ZORI) gets equal say. Honolulu and State (which
# is Honolulu-dominated by population weight ~72%) keep 70/30.
# Cleveland Fed WP 22-38r motivates the lag-vs-leading blend structure.
BLENDED_RENT_CPI_WEIGHTS = {
    "State":    0.70,   # Honolulu-dominated; CPI is regionally representative
    "Honolulu": 0.70,   # genuine local CPI signal
    "Maui":     0.50,   # ZORI is the only county-specific source
    "Hawaii":   0.50,
    "Kauai":    0.50,
}
# Backward-compat fallback for any caller still passing through the old name
BLENDED_RENT_CPI_WEIGHT = BLENDED_RENT_CPI_WEIGHTS["Honolulu"]

# Per-county 3-leg blend weights — ONLY the two counties where adding a
# genuinely county-specific HUD Fair Market Rent (FMR) leg is justified
# (M4 backtest + 3-leg addendum, docs/rent_nowcast_backtest.md):
#
#   • Hawaiʻi — realized ACS rent +27% (2021→24) outran BOTH Honolulu CPI
#     (+15%) and ZORI (+16%); only HUD FMR (+37%) captured the divergence,
#     cutting the Hawaiʻi backtest MAPE 9.21% → ~4.8%. The CPI leg is
#     Honolulu-only, so without FMR the Big Island has no signal that can
#     diverge from Honolulu — in either direction (surge OR plateau).
#   • Kauaʻi — has NO ZORI history (its ZORI leg is the statewide proxy), so
#     FMR is its first genuinely county-specific signal. CAVEAT: FMR slightly
#     *worsens* Kauaʻi's measured MAPE (status-quo CPI/proxy-ZORI 4.00% vs
#     CPI/FMR 5.74%) because Kauaʻi's realized growth was modest (+14%) while
#     FMR overshot (+25%) over the test window. FMR is therefore added at a
#     MODEST 0.20 weight here — for robustness (a real local leg), not measured
#     accuracy. Keep its weight small and re-validate annually.
#
# Maui (CPI/ZORI 50/50 — ZORI is the better county signal there) and
# Honolulu/State (CPI-led 0.70) are intentionally NOT given an FMR leg.
# Counties absent from this dict fall back to the 2-leg BLENDED_RENT_CPI_WEIGHTS.
# Weights are explicit (cpi/zori/fmr) and must sum to 1.0.
BLENDED_RENT_3LEG_WEIGHTS = {
    "Hawaii": {"cpi": 0.34, "zori": 0.33, "fmr": 0.33},
    "Kauai":  {"cpi": 0.40, "zori": 0.40, "fmr": 0.20},
}

# Number of trailing monthly periods to average when computing the BLS
# rent-CPI ratio that feeds the blended nowcast (Q1 of the rent-nowcast
# improvement plan). ZORI input is already smoothed at the same window;
# matching it here means both legs of the blend reflect a 3-month mean
# instead of a single bumpy print.
BLS_RENT_SMOOTHING_WINDOW = 3

# ACS vintage for the CONTRACT-RENT ANCHOR (B25058 only — the dollar level the
# nowcast scales forward). All five geographies use the 1-year now.
#
# WHY 1-yr for everyone (was Maui-only): the 5-year level (2020–2024) is centred
# ~2022, but the nowcast multiplies it by a 2024→present growth factor — so a
# 5-yr anchor silently OMITS ~2 years of rent growth. The 1-yr 2024 level is a
# true 2024 level, aligned with the calendar-2024 BLS base-year average and ZORI
# anchor average the growth factors are built on. (Maui already used 1-yr to
# avoid diluting the post-Lahaina shock; the same logic — wrong sample window —
# applies everywhere.) All HI counties + the State are >65k pop so all publish
# 1-yr. Each fetch falls back to the 5-yr value if a 1-yr cell is suppressed.
#
# NOTE: only the contract-rent ANCHOR moves to 1-yr. The bedroom-rent tiles
# (B25031) and cost-burden distributions (B25070/B25091) stay on the 5-yr —
# they hit small-cell suppression on thin neighbor-island samples that the 5-yr
# smooths over. See METHODOLOGY.md § Rent-anchor year.
COUNTY_ANCHOR_OVERRIDE = {
    "State":    "acs1",
    "Honolulu": "acs1",
    "Hawaii":   "acs1",
    "Maui":     "acs1",
    "Kauai":    "acs1",
}

# Redfin region name → countyData key in the HTML file
COUNTY_MAP = {
    "Honolulu County, HI": "Honolulu",
    "Hawaii County, HI":   "Hawaii",
    "Maui County, HI":     "Maui",
    "Kauai County, HI":    "Kauai",
}

# Zillow ZORI RegionName → countyData key
ZORI_COUNTY_MAP = {
    "Honolulu County": "Honolulu",
    "Hawaii County":   "Hawaii",
    "Maui County":     "Maui",
    "Kauai County":    "Kauai",
}

# Population weights for rolling the four counties up to a statewide figure.
# Used for (a) the statewide askRent level, (b) the statewide ZORI YoY, and
# (c) the statewide ZORI growth RATIO that feeds the blended nowcast. (a)/(b)
# renormalize over whatever counties are present in a given month; (c) does the
# same so the State ratio is a weighted mean of per-county ratios (NOT a
# ratio of weighted means over mismatched county sets — Zillow began
# publishing Kauaʻi only in Feb 2025, so its anchor-year average is missing,
# and ratio-of-means would otherwise inject a composition shift).
ZORI_STATE_POP_WEIGHTS = {"Honolulu": 0.72, "Hawaii": 0.14, "Maui": 0.10, "Kauai": 0.04}

# Redfin property type → which countyData field to update
PROP_TYPE_MAP = {
    "Single Family Residential": "sfhPrice",
    "Condo/Co-op":               "condoPrice",
}

DEFAULT_FILES = [
    PROJECT_ROOT / "squarespace-single-file.html",
    PROJECT_ROOT / "index.html",
]
# ────────────────────────────────────────────────────────────────

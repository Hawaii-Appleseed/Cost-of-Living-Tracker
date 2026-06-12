#!/usr/bin/env python3
"""
Backtest the blended rent nowcast (M4 of the rent-nowcast improvement plan).

Question this answers
---------------------
The production nowcast blends two growth signals against a common ACS dollar
anchor:

    rent_now = acs_anchor × ( w · bls_ratio + (1-w) · zori_ratio )

where  bls_ratio  = Honolulu BLS rent CPI growth (the SAME factor for every
county — there is only one Hawaii rent-CPI series), and  zori_ratio  = the
county's Zillow asking-rent growth. Production uses w = 0.70 for Honolulu /
State and w = 0.50 for the three outer islands (Maui, Hawaii, Kauai).

Is 0.50 defensible? We test it the only way that has ground truth: by checking
whether the blended GROWTH FACTOR reproduces realized contract-rent growth
between two years for which we have direct ACS 1-year measurements
(B25058 median contract rent — same definition as the production anchor).

Method
------
For each county c and each ordered year pair (t0, t1), t0 < t1, drawn from the
years with published ACS 1-yr contract rent (2021-2024):

    anchor      = ACS1_rent(c, t0)
    actual      = ACS1_rent(c, t1)
    true_factor = actual / anchor
    bls_factor  = BLS_CPI_annualavg(t1)  / BLS_CPI_annualavg(t0)      # Honolulu, shared
    zori_factor = ZORI_annualavg(c, t1)  / ZORI_annualavg(c, t0)      # per county

    for weight w in 0.0 .. 1.0:
        pred = anchor × ( w·bls_factor + (1-w)·zori_factor )
        ape  = |pred / actual - 1|

We then report, per county and pooled over the outer islands, the MAPE as a
function of w, the MAPE-minimising w, and how the production weights (0.50
outer / 0.70 Honolulu) compare. We also report the mean ACS 1-yr MoE per
county — the irreducible noise floor of the ground truth itself.

All endpoints are public; only the Census key is required (BLS uses the
registered key if BLS_API_KEY is set, else anonymous — one call only).

Run:  CENSUS_API_KEY=... [BLS_API_KEY=...] python3 scripts/backtest_rent_nowcast.py
"""
from __future__ import annotations

import csv
import io
import json
import os
import urllib.request

# ── Config (mirrors redfin-price-updater.py) ────────────────────────────────
CENSUS_API_KEY = os.environ.get("CENSUS_API_KEY", "")
BLS_API_KEY    = os.environ.get("BLS_API_KEY", "")

COUNTY_FIPS = {"Honolulu": "003", "Hawaii": "001", "Maui": "009", "Kauai": "007"}
NAME_TO_KEY = {
    "Honolulu County, Hawaii": "Honolulu",
    "Hawaii County, Hawaii":   "Hawaii",
    "Maui County, Hawaii":     "Maui",
    "Kauai County, Hawaii":    "Kauai",
}
OUTER_ISLANDS = ["Maui", "Hawaii", "Kauai"]
PROD_WEIGHT   = {"Honolulu": 0.70, "State": 0.70,
                 "Maui": 0.50, "Hawaii": 0.50, "Kauai": 0.50}

TEST_YEARS  = [2021, 2022, 2023, 2024]   # ACS 1-yr availability (2020 not released)
WEIGHT_GRID = [round(0.1 * i, 1) for i in range(11)]  # 0.0 .. 1.0

CENSUS_RENT_VAR = "B25058_001E"
CENSUS_RENT_MOE = "B25058_001M"
BLS_API_URL     = "https://api.bls.gov/publicAPI/v2/timeseries/data/"
BLS_RENT_SERIES = "CUURS49ASEHA"
ZORI_URL        = ("https://files.zillowstatic.com/research/public_csvs/"
                   "zori/County_zori_uc_sfrcondomfr_sm_month.csv")
ZORI_COUNTY_MAP = {
    "Honolulu County": "Honolulu", "Hawaii County": "Hawaii",
    "Maui County": "Maui", "Kauai County": "Kauai",
}


# ── Fetch helpers ───────────────────────────────────────────────────────────
def _get_json(url: str):
    req = urllib.request.Request(url, headers={"User-Agent": "rent-backtest/1.0"})
    with urllib.request.urlopen(req, timeout=60) as r:
        return json.loads(r.read().decode())


def fetch_acs_truth() -> dict:
    """Return {county: {year: {'rent': int, 'moe': int}}} from ACS 1-yr B25058."""
    key_qs = f"&key={CENSUS_API_KEY}" if CENSUS_API_KEY else ""
    fips_csv = ",".join(COUNTY_FIPS.values())
    out: dict[str, dict[int, dict]] = {c: {} for c in COUNTY_FIPS}
    for yr in TEST_YEARS:
        url = (f"https://api.census.gov/data/{yr}/acs/acs1"
               f"?get={CENSUS_RENT_VAR},{CENSUS_RENT_MOE},NAME"
               f"&for=county:{fips_csv}&in=state:15{key_qs}")
        try:
            data = _get_json(url)
        except Exception as e:
            print(f"  WARNING: ACS 1-yr {yr} fetch failed ({e})")
            continue
        hdr, *rows = data
        ei, mi, ni = hdr.index(CENSUS_RENT_VAR), hdr.index(CENSUS_RENT_MOE), hdr.index("NAME")
        for row in rows:
            key = NAME_TO_KEY.get(row[ni])
            if not key:
                continue
            try:
                est = int(row[ei])
                moe = int(row[mi])
            except (ValueError, TypeError):
                continue
            if est > 0:
                out[key][yr] = {"rent": est, "moe": moe}
    return out


def fetch_bls_annual() -> dict:
    """Return {year: annual_avg_index} for CUURS49ASEHA across TEST_YEARS."""
    payload = json.dumps({
        "seriesid":  [BLS_RENT_SERIES],
        "startyear": str(min(TEST_YEARS)),
        "endyear":   str(max(TEST_YEARS)),
        **({"registrationkey": BLS_API_KEY} if BLS_API_KEY else {}),
    }).encode()
    req = urllib.request.Request(BLS_API_URL, data=payload,
                                 headers={"Content-Type": "application/json"})
    with urllib.request.urlopen(req, timeout=60) as r:
        resp = json.loads(r.read().decode())
    if resp.get("status") != "REQUEST_SUCCEEDED":
        raise RuntimeError(f"BLS: {resp.get('status')} {resp.get('message')}")
    rows = resp["Results"]["series"][0]["data"]
    buckets: dict[int, list[float]] = {}
    for r in rows:
        if not r["period"].startswith("M") or r["period"] == "M13":
            continue
        if r["value"] in ("-", ""):
            continue
        y = int(r["year"])
        buckets.setdefault(y, []).append(float(r["value"]))
    return {y: sum(v) / len(v) for y, v in buckets.items() if v}


def fetch_zori_annual() -> dict:
    """Return {county: {year: annual_avg}} from the ZORI county CSV.

    A year is only kept if ≥6 monthly observations are present (avoids
    half-year averages skewing the growth ratio)."""
    req = urllib.request.Request(ZORI_URL, headers={"User-Agent": "rent-backtest/1.0"})
    with urllib.request.urlopen(req, timeout=120) as r:
        raw = r.read().decode()
    reader = csv.reader(io.StringIO(raw))
    headers = next(reader)
    # Map each date-column index → year
    col_year: dict[int, int] = {}
    for i, h in enumerate(headers):
        if len(h) >= 4 and h[:4].isdigit() and "-" in h:
            col_year[i] = int(h[:4])
    out: dict[str, dict[int, float]] = {}
    for row in reader:
        if len(row) < 10:
            continue
        region, state = row[2], row[5]
        if state != "HI" or region not in ZORI_COUNTY_MAP:
            continue
        key = ZORI_COUNTY_MAP[region]
        buckets: dict[int, list[float]] = {}
        for i, yr in col_year.items():
            if i < len(row) and row[i].strip():
                try:
                    buckets.setdefault(yr, []).append(float(row[i]))
                except ValueError:
                    pass
        out[key] = {y: sum(v) / len(v) for y, v in buckets.items() if len(v) >= 6}
    return out


# ── Backtest core ───────────────────────────────────────────────────────────
def build_cases(truth, bls_annual, zori_annual):
    """Yield per-(county, t0, t1) records with the realised & model factors."""
    cases = []
    for county in COUNTY_FIPS:
        yrs = sorted(truth.get(county, {}))
        for i in range(len(yrs)):
            for j in range(i + 1, len(yrs)):
                t0, t1 = yrs[i], yrs[j]
                if t0 not in bls_annual or t1 not in bls_annual:
                    continue
                z = zori_annual.get(county, {})
                if t0 not in z or t1 not in z:
                    continue
                anchor = truth[county][t0]["rent"]
                actual = truth[county][t1]["rent"]
                cases.append({
                    "county": county, "t0": t0, "t1": t1,
                    "anchor": anchor, "actual": actual,
                    "true_factor": actual / anchor,
                    "bls_factor":  bls_annual[t1] / bls_annual[t0],
                    "zori_factor": z[t1] / z[t0],
                })
    return cases


def mape_for_weight(cases, w):
    if not cases:
        return None
    apes = []
    for c in cases:
        factor = w * c["bls_factor"] + (1 - w) * c["zori_factor"]
        pred = c["anchor"] * factor
        apes.append(abs(pred / c["actual"] - 1.0))
    return 100.0 * sum(apes) / len(apes)


# Pass-through model (item 4): pred = anchor · bls^(1-λ) · zori^λ — a log-space
# bridge between the realized-CPI and asking-rent growth factors. λ>1 lets it
# overshoot BOTH legs (the convex blend above cannot), which is the case the
# Big Island needs. λ swept past 1.0 to test for overshoot benefit.
LAMBDA_GRID = [round(0.05 * i, 2) for i in range(0, 31)]   # 0.0 .. 1.5


def mape_for_lambda(cases, lam):
    if not cases:
        return None
    apes = []
    for c in cases:
        factor = (c["bls_factor"] ** (1.0 - lam)) * (c["zori_factor"] ** lam)
        pred = c["anchor"] * factor
        apes.append(abs(pred / c["actual"] - 1.0))
    return 100.0 * sum(apes) / len(apes)


def best_blend(subset):
    """(best_weight, best_mape) over the convex weight grid."""
    bw, bm = None, 1e9
    for w in WEIGHT_GRID:
        m = mape_for_weight(subset, w)
        if m is not None and m < bm:
            bw, bm = w, m
    return bw, bm


def best_lambda(subset):
    """(best_lambda, best_mape) over the pass-through λ grid."""
    bl, bm = None, 1e9
    for lam in LAMBDA_GRID:
        m = mape_for_lambda(subset, lam)
        if m is not None and m < bm:
            bl, bm = lam, m
    return bl, bm


def main():
    if not CENSUS_API_KEY:
        print("ERROR: set CENSUS_API_KEY"); return
    print("Fetching ACS 1-yr contract rent (B25058) 2021-2024 ...")
    truth = fetch_acs_truth()
    print("Fetching BLS CUURS49ASEHA annual averages ...")
    bls_annual = fetch_bls_annual()
    print("Fetching ZORI county annual averages ...")
    zori_annual = fetch_zori_annual()

    # ── ACS ground-truth MoE (the noise floor) ──────────────────────────────
    print("\nACS 1-yr ground-truth MoE (90% CI) — the irreducible noise floor:")
    print(f"  {'County':<9} {'mean MoE %':>10}   per-year MoE%")
    for county in COUNTY_FIPS:
        per = {y: 100 * d["moe"] / d["rent"] for y, d in sorted(truth[county].items())}
        if per:
            mean_moe = sum(per.values()) / len(per)
            detail = "  ".join(f"{y}:{p:.1f}" for y, p in per.items())
            print(f"  {county:<9} {mean_moe:>9.1f}%   {detail}")

    # ── ZORI coverage ───────────────────────────────────────────────────────
    print("\nZORI annual-average coverage (years with ≥6 monthly prints):")
    for county in COUNTY_FIPS:
        yrs = sorted(zori_annual.get(county, {}))
        print(f"  {county:<9} {yrs}")

    cases = build_cases(truth, bls_annual, zori_annual)
    print(f"\nUsable backtest cases (county × year-pair): {len(cases)}")
    for c in cases:
        print(f"  {c['county']:<9} {c['t0']}→{c['t1']}  "
              f"true×{c['true_factor']:.3f}  bls×{c['bls_factor']:.3f}  "
              f"zori×{c['zori_factor']:.3f}")

    # ── MAPE vs weight: pure ZORI (w=0) → pure CPI (w=1) ─────────────────────
    def report(label, subset):
        print(f"\n── {label}  (n={len(subset)}) ──")
        if not subset:
            print("  (no cases)"); return
        print(f"  {'w (CPI wt)':>10} {'MAPE %':>8}")
        best_w, best_m = None, 1e9
        for w in WEIGHT_GRID:
            m = mape_for_weight(subset, w)
            tag = ""
            if w in (0.0, 0.5, 0.7, 1.0):
                tag = {0.0: "  ← pure ZORI", 1.0: "  ← pure CPI",
                       0.5: "  ← prod outer", 0.7: "  ← prod Hono/State"}[w]
            print(f"  {w:>10.1f} {m:>8.2f}{tag}")
            if m < best_m:
                best_m, best_w = m, w
        print(f"  → MAPE-minimising weight: w={best_w:.1f} (MAPE {best_m:.2f}%)")

    report("ALL counties pooled", cases)
    report("OUTER ISLANDS pooled (Maui+Hawaii+Kauai) — production w=0.50",
           [c for c in cases if c["county"] in OUTER_ISLANDS])
    for county in COUNTY_FIPS:
        report(f"{county} only", [c for c in cases if c["county"] == county])

    # ── Pass-through model vs convex blend (item 4 gate) ─────────────────────
    print("\n" + "=" * 64)
    print("PASS-THROUGH MODEL (item 4):  pred = anchor · bls^(1-λ) · zori^λ")
    print("=" * 64)
    BUDGET = 8.0
    subsets = {
        "ALL pooled":   cases,
        "OUTER pooled": [c for c in cases if c["county"] in OUTER_ISLANDS],
        **{c: [x for x in cases if x["county"] == c] for c in COUNTY_FIPS},
    }
    print(f"\n  {'subset':<14} {'blend(w*)':>12} {'passthru(λ*)':>16} {'winner':>10}")
    pooled_pt_mape = None
    for name, subset in subsets.items():
        if not subset:
            continue
        bw, bm = best_blend(subset)
        bl, lm = best_lambda(subset)
        if name == "OUTER pooled":
            pooled_pt_mape, pooled_pt_lambda = lm, bl
        winner = "passthru" if lm < bm else "blend"
        print(f"  {name:<14} w={bw:.1f}:{bm:>6.2f}%  λ={bl:.2f}:{lm:>6.2f}%  {winner:>10}")

    # Verdict for the OUTER-pooled subset (the weakest, FMR-motivating case).
    outer = subsets["OUTER pooled"]
    bw, bm = best_blend(outer)
    bl, lm = best_lambda(outer)
    print(f"\n  VERDICT (OUTER pooled, budget {BUDGET:.0f}%):")
    print(f"    convex blend best:  w={bw:.1f}  MAPE {bm:.2f}%")
    print(f"    pass-through best:   λ={bl:.2f}  MAPE {lm:.2f}%")
    ship = lm <= BUDGET and lm <= bm
    if ship:
        print(f"    → SHIP pass-through: beats blend AND within budget. "
              f"Set RENT_PASSTHROUGH_LAMBDA={bl:.2f}, RENT_PRODUCTION_METHOD='passthrough'.")
    else:
        why = "exceeds budget" if lm > BUDGET else "does not beat the blend"
        print(f"    → KEEP blend: pass-through {why}. "
              f"Leave RENT_PRODUCTION_METHOD='blend'.")
    print("=" * 64)


if __name__ == "__main__":
    main()

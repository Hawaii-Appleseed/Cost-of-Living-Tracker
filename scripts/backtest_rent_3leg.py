#!/usr/bin/env python3
"""
Prototype: does adding a county-specific HUD FMR leg beat the 2-leg blend?

Motivation (from docs/rent_nowcast_backtest.md)
-----------------------------------------------
The production blend has only ONE county-specific growth signal (ZORI); the
BLS rent-CPI leg is Honolulu-only and is applied identically to every county.
The M4 backtest showed this fails where a neighbor island diverges from
Honolulu — Hawaiʻi County rents rose +27% (ACS 2021→2024) while Honolulu CPI
rose +15%. It also showed Kauaʻi has ZERO validation (no ZORI history).

HUD Fair Market Rent (FMR) is a free, genuinely per-county, annual series with
full history for all four counties. This harness adds it as a third leg and
asks: does a 3-leg blend (CPI / ZORI / FMR) beat the current 2-leg CPI/ZORI
MAPE of 5.93% on the outer islands — and does FMR let us finally validate
Kauaʻi?

Caveat: HUD FMR is the 40th-percentile *gross* rent (incl. utilities) and is
itself derived from lagged ACS 5-yr data + a recent-mover/CPI trend factor, so
it is partly correlated with the ACS ground truth and lags the market. We use
only its growth RATIO; level differences don't matter. Treat results as
directional — the sample is small and the ground truth is noisy.

Ground truth = ACS 1-yr contract rent (B25058), 2021-2024, per county (same as
scripts/backtest_rent_nowcast.py).

Run: CENSUS_API_KEY=... [BLS_API_KEY=...] python3 scripts/backtest_rent_3leg.py
"""
from __future__ import annotations

import csv
import io
import json
import os
import re
import urllib.request
import zipfile

CENSUS_API_KEY = os.environ.get("CENSUS_API_KEY", "")
BLS_API_KEY    = os.environ.get("BLS_API_KEY", "")

COUNTY_FIPS = {"Honolulu": "003", "Hawaii": "001", "Maui": "009", "Kauai": "007"}
NAME_TO_KEY = {
    "Honolulu County, Hawaii": "Honolulu", "Hawaii County, Hawaii": "Hawaii",
    "Maui County, Hawaii": "Maui", "Kauai County, Hawaii": "Kauai",
}
OUTER = ["Maui", "Hawaii", "Kauai"]
TEST_YEARS = [2021, 2022, 2023, 2024]

BLS_API_URL = "https://api.bls.gov/publicAPI/v2/timeseries/data/"
BLS_SERIES  = "CUURS49FSEHA"
ZORI_URL    = ("https://files.zillowstatic.com/research/public_csvs/"
               "zori/County_zori_uc_sfrcondomfr_sm_month.csv")
ZORI_MAP = {"Honolulu County": "Honolulu", "Hawaii County": "Hawaii",
            "Maui County": "Maui", "Kauai County": "Kauai"}
UA = "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36"

# HUD county-FMR workbooks (county-level, all-bedroom). Names vary by year.
HUD_FMR_URLS = {
    2021: "https://www.huduser.gov/portal/datasets/fmr/fmr2021/FY21_4050_FMRs_rev.xlsx",
    2022: "https://www.huduser.gov/portal/datasets/fmr/fmr2022/FY22_FMRs_revised.xlsx",
    2023: "https://www.huduser.gov/portal/datasets/fmr/fmr2023/FY23_FMRs_revised.xlsx",
    2024: "https://www.huduser.gov/portal/datasets/fmr/fmr2024/FMR2024_final_revised.xlsx",
}
HUD_COUNTYNAME = {"Honolulu County": "Honolulu", "Hawaii County": "Hawaii",
                  "Maui County": "Maui", "Kauai County": "Kauai"}


def _url_bytes(url, headers=None):
    req = urllib.request.Request(url, headers=headers or {"User-Agent": UA})
    with urllib.request.urlopen(req, timeout=120) as r:
        return r.read()


def fetch_acs_truth():
    key_qs = f"&key={CENSUS_API_KEY}" if CENSUS_API_KEY else ""
    fips = ",".join(COUNTY_FIPS.values())
    out = {c: {} for c in COUNTY_FIPS}
    for yr in TEST_YEARS:
        url = (f"https://api.census.gov/data/{yr}/acs/acs1"
               f"?get=B25058_001E,B25058_001M,NAME&for=county:{fips}&in=state:15{key_qs}")
        data = json.loads(_url_bytes(url))
        hdr, *rows = data
        ei, mi, ni = hdr.index("B25058_001E"), hdr.index("B25058_001M"), hdr.index("NAME")
        for row in rows:
            k = NAME_TO_KEY.get(row[ni])
            if k and int(row[ei]) > 0:
                out[k][yr] = {"rent": int(row[ei]), "moe": int(row[mi])}
    return out


def fetch_bls_annual():
    payload = json.dumps({
        "seriesid": [BLS_SERIES], "startyear": str(min(TEST_YEARS)),
        "endyear": str(max(TEST_YEARS)),
        **({"registrationkey": BLS_API_KEY} if BLS_API_KEY else {}),
    }).encode()
    req = urllib.request.Request(BLS_API_URL, data=payload,
                                 headers={"Content-Type": "application/json"})
    with urllib.request.urlopen(req, timeout=60) as r:
        resp = json.loads(r.read())
    if resp.get("status") != "REQUEST_SUCCEEDED":
        raise RuntimeError(f"BLS: {resp.get('status')} {resp.get('message')}")
    rows = resp["Results"]["series"][0]["data"]
    buckets = {}
    for r in rows:
        if r["period"].startswith("M") and r["period"] != "M13" and r["value"] not in ("-", ""):
            buckets.setdefault(int(r["year"]), []).append(float(r["value"]))
    return {y: sum(v) / len(v) for y, v in buckets.items() if v}


def fetch_zori_annual():
    raw = _url_bytes(ZORI_URL).decode()
    reader = csv.reader(io.StringIO(raw))
    headers = next(reader)
    col_year = {i: int(h[:4]) for i, h in enumerate(headers)
                if len(h) >= 7 and h[:4].isdigit() and "-" in h}
    out = {}
    for row in reader:
        if len(row) < 10 or row[5] != "HI" or row[2] not in ZORI_MAP:
            continue
        buckets = {}
        for i, yr in col_year.items():
            if i < len(row) and row[i].strip():
                try:
                    buckets.setdefault(yr, []).append(float(row[i]))
                except ValueError:
                    pass
        out[ZORI_MAP[row[2]]] = {y: sum(v) / len(v) for y, v in buckets.items() if len(v) >= 6}
    return out


def _sanitize_xlsx(data: bytes) -> bytes:
    """HUD workbooks ship a malformed dcterms date that openpyxl rejects; strip it."""
    bin_in = io.BytesIO(data)
    out = io.BytesIO()
    with zipfile.ZipFile(bin_in) as zin, zipfile.ZipFile(out, "w", zipfile.ZIP_DEFLATED) as zout:
        for n in zin.namelist():
            d = zin.read(n)
            if n == "docProps/core.xml":
                t = d.decode("utf-8", "ignore")
                t = re.sub(r"<dcterms:(created|modified)[^>]*>.*?</dcterms:\1>", "", t)
                d = t.encode("utf-8")
            zout.writestr(n, d)
    return out.getvalue()


def fetch_hud_fmr2_annual():
    """{county: {year: 2BR FMR}} — 2BR is the standard FMR reference bedroom."""
    import openpyxl
    out = {c: {} for c in COUNTY_FIPS}
    for yr, url in HUD_FMR_URLS.items():
        data = _sanitize_xlsx(_url_bytes(url))
        wb = openpyxl.load_workbook(io.BytesIO(data), read_only=True)
        ws = wb.active
        it = ws.iter_rows(values_only=True)
        hdr = list(next(it))
        idx = {c: i for i, c in enumerate(hdr)}
        i_state = idx.get("state_alpha", idx.get("stusps"))
        i_nm, i_f2 = idx.get("countyname"), idx.get("fmr_2")
        seen = {}
        for r in it:
            st = r[i_state] if i_state is not None else None
            nm = r[i_nm] if i_nm is not None else None
            if st == "HI" and nm in HUD_COUNTYNAME and HUD_COUNTYNAME[nm] not in seen:
                seen[HUD_COUNTYNAME[nm]] = float(r[i_f2])
        for k, v in seen.items():
            out[k][yr] = v
    return out


def build_cases(truth, bls, zori, fmr):
    cases = []
    for county in COUNTY_FIPS:
        yrs = sorted(truth.get(county, {}))
        for i in range(len(yrs)):
            for j in range(i + 1, len(yrs)):
                t0, t1 = yrs[i], yrs[j]
                if t0 not in bls or t1 not in bls:
                    continue
                rec = {
                    "county": county, "t0": t0, "t1": t1,
                    "anchor": truth[county][t0]["rent"], "actual": truth[county][t1]["rent"],
                    "bls": bls[t1] / bls[t0],
                    "zori": (zori[county][t1] / zori[county][t0]
                             if t0 in zori.get(county, {}) and t1 in zori.get(county, {}) else None),
                    "fmr": (fmr[county][t1] / fmr[county][t0]
                            if t0 in fmr.get(county, {}) and t1 in fmr.get(county, {}) else None),
                }
                cases.append(rec)
    return cases


def mape(cases, w_cpi, w_zori, w_fmr, *, zori_fallback_cpi=True):
    """MAPE for a (cpi, zori, fmr) weight mix. Renormalises over available legs.

    If a case lacks ZORI and zori_fallback_cpi is True, the ZORI weight is
    folded back proportionally onto the legs that ARE present (mirrors the
    production statewide-proxy idea but here we just renormalise)."""
    apes, n = [], 0
    for c in cases:
        legs, wts = [], []
        if w_cpi > 0:
            legs.append(c["bls"]); wts.append(w_cpi)
        if w_zori > 0 and c["zori"] is not None:
            legs.append(c["zori"]); wts.append(w_zori)
        if w_fmr > 0 and c["fmr"] is not None:
            legs.append(c["fmr"]); wts.append(w_fmr)
        if not legs:
            continue
        s = sum(wts)
        factor = sum(l * (w / s) for l, w in zip(legs, wts))
        pred = c["anchor"] * factor
        apes.append(abs(pred / c["actual"] - 1.0))
        n += 1
    return (100 * sum(apes) / len(apes), n) if apes else (None, 0)


def main():
    print("Fetching ACS 1-yr truth, BLS, ZORI, HUD FMR ...")
    truth = fetch_acs_truth()
    bls   = fetch_bls_annual()
    zori  = fetch_zori_annual()
    fmr   = fetch_hud_fmr2_annual()

    print("\nHUD FMR 2BR by county/year:")
    for c in COUNTY_FIPS:
        print(f"  {c:<9} {fmr.get(c)}")

    cases = build_cases(truth, bls, zori, fmr)
    outer = [c for c in cases if c["county"] in OUTER]
    outer_zori = [c for c in outer if c["zori"] is not None]
    kauai = [c for c in cases if c["county"] == "Kauai"]

    print(f"\nOuter-island cases: {len(outer)} total, "
          f"{len(outer_zori)} with ZORI, {len(kauai)} Kauaʻi (FMR brings these in)")

    def line(label, m, n):
        print(f"  {label:<42} {m:>6.2f}%   (n={n})" if m is not None else f"  {label:<42}   n/a")

    print("\n── Schemes on the ORIGINAL ZORI-available outer cases (apples-to-apples vs 5.93%) ──")
    line("2-leg  CPI .5 / ZORI .5   (PRODUCTION)", *mape(outer_zori, .5, .5, 0))
    line("3-leg  CPI .4 / ZORI .3 / FMR .3",       *mape(outer_zori, .4, .3, .3))
    line("3-leg  CPI .33/ ZORI .33/ FMR .33",      *mape(outer_zori, 1/3, 1/3, 1/3))
    line("2-leg  CPI .5 / FMR .5",                 *mape(outer_zori, .5, 0, .5))
    line("2-leg  ZORI .5 / FMR .5",                *mape(outer_zori, 0, .5, .5))

    print("\n── Best 3-leg mix on ZORI-available outer cases (0.1 simplex grid) ──")
    best = (1e9, None)
    for a in range(0, 11):
        for b in range(0, 11 - a):
            cpi, zo, fm = a/10, b/10, (10-a-b)/10
            m, n = mape(outer_zori, cpi, zo, fm)
            if m is not None and m < best[0]:
                best = (m, (cpi, zo, fm, n))
    cpi, zo, fm, n = best[1]
    print(f"  argmin: CPI {cpi:.1f} / ZORI {zo:.1f} / FMR {fm:.1f}  →  {best[0]:.2f}%  (n={n})")

    print("\n── Including KAUAʻI via FMR (no ZORI there) — all outer cases ──")
    line("2-leg  CPI .5 / FMR .5   (works for Kauaʻi)", *mape(outer, .5, 0, .5))
    line("3-leg  CPI/ZORI/FMR w/ ZORI→renorm fallback", *mape(outer, 1/3, 1/3, 1/3))
    line("Kauaʻi only:  CPI .5 / FMR .5",               *mape(kauai, .5, 0, .5))
    line("Kauaʻi only:  pure FMR",                      *mape(kauai, 0, 0, 1))
    line("Kauaʻi only:  pure CPI (status quo proxy)",   *mape(kauai, 1, 0, 0))

    print("\n── Per-county: production 2-leg vs CPI/FMR 2-leg ──")
    for c in COUNTY_FIPS:
        cc = [x for x in cases if x["county"] == c]
        ccz = [x for x in cc if x["zori"] is not None]
        m_prod, n_prod = mape(ccz, .5 if c in OUTER else .7,
                              .5 if c in OUTER else .3, 0)
        m_fmr, n_fmr = mape(cc, .5, 0, .5)
        pm = f"{m_prod:.2f}%" if m_prod is not None else "n/a"
        fm_ = f"{m_fmr:.2f}%" if m_fmr is not None else "n/a"
        print(f"  {c:<9}  prod CPI/ZORI: {pm:>7} (n={n_prod})   CPI/FMR: {fm_:>7} (n={n_fmr})")


if __name__ == "__main__":
    main()

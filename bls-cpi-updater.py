#!/usr/bin/env python3
"""
bls-cpi-updater.py
------------------
Fetches Honolulu CPI series from BLS and patches the `cpiData` block in both
squarespace-single-file.html and index.html.

Series (area S49A = Urban Hawaii / Honolulu, NSA):
    CUURS49ASA0     — All items, Honolulu (headline)
    CUURS49ASAH     — Shelter, Honolulu
    CUURS49ASAF11   — Food at home, Honolulu
    CUURS49ASETB01  — Gasoline (all types), Honolulu  (energy proxy)
    CUURS49ASAT     — Transportation, Honolulu

Cadence: bimonthly. Data periods are odd months (Jan/Mar/May/Jul/Sep/Nov),
released on or around the 15th of the following even month. YoY is computed
against the same odd-month observation one year prior — both are guaranteed
present in a bimonthly schedule, no interpolation needed.

For each series we compute YoY % change: (latest - 12mo prior) / 12mo prior * 100.

Patch strategy: replace between
    /* CPI_DATA_START */ ... /* CPI_DATA_END */

Env:
    BLS_API_KEY   — optional but recommended (higher rate limits)

Run:
    python3 bls-cpi-updater.py
    python3 bls-cpi-updater.py --dry-run
"""
from __future__ import annotations

import json
import os
import sys
from pathlib import Path

# Add project root + pipelines/grocery to sys.path
PROJECT_ROOT = Path(__file__).resolve().parent
GROCERY_ROOT = PROJECT_ROOT / "pipelines" / "grocery"
sys.path.insert(0, str(PROJECT_ROOT))
sys.path.insert(0, str(GROCERY_ROOT))

from src.cpi_fetcher import fetch_cpi_data      # noqa: E402 (grocery pipeline)
from common.html_patcher import patch_html_files   # noqa: E402

# ---------------------------------------------------------------
SERIES = {
    # Area S49A = Urban Hawaii / Honolulu (CUUR = CPI-U, NSA, bimonthly).
    # Odd-month data periods; see module docstring for release cadence.
    "allItems":  "CUURS49ASA0",     # All items
    "shelter":   "CUURS49ASAH",     # Shelter
    "food":      "CUURS49ASAF11",   # Food at home
    "energy":    "CUURS49ASETB01",  # Gasoline / energy (motor fuel)
    "transport": "CUURS49ASAT",     # Transportation
}

DEFAULT_FILES = [
    PROJECT_ROOT / "squarespace-single-file.html",
    PROJECT_ROOT / "index.html",
]

_DATA_TAG = "CPI"


def compute_metrics(points: list[dict]) -> dict | None:
    """Compute multi-window inflation metrics from a bimonthly CPI series.

    Returns a dict with:
        yoy            — % change vs same odd-month, prior year (12-mo span)
        pop            — period-over-period % change vs prior bimonthly point
                         (≈ 2-month change; primary high-frequency signal)
        annualized_6mo — geometric annualization of the latest two adjacent
                         bimonthly changes (≈ 6-mo trend, SAAR-style)
        latestPeriod   — 'YYYY-MM' of the freshest observation

    Multi-window display follows Cleveland Fed nowcasting convention
    (FRB Cleveland publishes MoM SAAR alongside YoY) — short-window rates
    catch turning points faster than YoY, which lags by construction.
    None is returned only when no usable observation exists. Individual
    fields may be None when not enough history is present.
    """
    monthly = [p for p in points if p["period"].startswith("M") and p["period"] != "M13"]
    if not monthly:
        return None
    monthly.sort(key=lambda p: (p["year"], int(p["period"][1:])))
    latest = monthly[-1]
    latest_month = int(latest["period"][1:])
    latest_period = f"{latest['year']}-{latest_month:02d}"

    # YoY — same odd-month, one year prior. Always available in a clean
    # bimonthly schedule, no interpolation needed.
    yoy = None
    prior_year = next(
        (p for p in monthly
         if p["year"] == latest["year"] - 1 and int(p["period"][1:]) == latest_month),
        None,
    )
    if prior_year and prior_year["value"] > 0:
        yoy = round((latest["value"] - prior_year["value"]) / prior_year["value"] * 100.0, 2)

    # PoP — period-over-period (bimonthly). Adjacent observation is ~2 months
    # back. Bimonthly cadence means this is the highest-frequency print
    # available without imputation.
    pop = None
    if len(monthly) >= 2 and monthly[-2]["value"] > 0:
        pop = round((latest["value"] - monthly[-2]["value"]) / monthly[-2]["value"] * 100.0, 2)

    # Annualized 6-month trend — four consecutive bimonthly observations
    # span ~6 months (3 intervals × 2 months); annualize that 6-month
    # ratio to a 12-month equivalent. Gives a SAAR-style read that's
    # responsive but smoother than PoP alone — a single noisy print is
    # diluted across three intervals before annualization.
    ann6 = None
    if len(monthly) >= 4 and monthly[-4]["value"] > 0:
        ratio = latest["value"] / monthly[-4]["value"]
        if ratio > 0:
            ann6 = round((ratio ** 2 - 1) * 100.0, 2)  # 6mo×2 = 12mo annualization

    return {
        "yoy": yoy,
        "pop": pop,
        "annualized_6mo": ann6,
        "latestPeriod": latest_period,
    }


# Back-compat shim — keep `compute_yoy` for any external callers that
# imported it before the multi-window refactor. New code should use
# `compute_metrics` directly.
def compute_yoy(points: list[dict]) -> tuple[float | None, str | None]:
    m = compute_metrics(points)
    if m is None:
        return None, None
    return m["yoy"], m["latestPeriod"]


def _fmt_num(v):
    return "null" if v is None else f"{v}"


def build_block(metrics_by_key: dict) -> str:
    lines = ["/* CPI_DATA_START */", "const cpiData = {"]
    pad = max(len(k) for k in SERIES) + 2
    for key, series_id in SERIES.items():
        entry = metrics_by_key.get(key)
        if entry and entry.get("yoy") is not None:
            lines.append(
                f'  {(key+":").ljust(pad)}{{ '
                f'yoy: {_fmt_num(entry.get("yoy"))}, '
                f'pop: {_fmt_num(entry.get("pop"))}, '
                f'annualized6mo: {_fmt_num(entry.get("annualized_6mo"))}, '
                f'latestPeriod: "{entry["latestPeriod"]}", '
                f'source: "BLS {series_id}" }},'
            )
        else:
            lines.append(f'  {(key+":").ljust(pad)}null,')
    lines.append("};")
    lines.append("/* CPI_DATA_END */")
    return "\n".join(lines)


def main() -> int:
    dry_run = "--dry-run" in sys.argv
    files = DEFAULT_FILES
    if "--file" in sys.argv:
        idx = sys.argv.index("--file") + 1
        files = [Path(sys.argv[idx])]

    api_key = os.environ.get("BLS_API_KEY", "")
    if not api_key:
        print("WARNING: BLS_API_KEY not set; using public tier (10 req/day, 2yr window)")

    series_ids = list(SERIES.values())
    try:
        raw = fetch_cpi_data(series_ids, api_key=api_key or None)
    except Exception as e:
        print(f"ERROR fetching BLS: {e}")
        print("Writing null cpiData block (dashboard will hide inflation chips).")
        raw = {sid: [] for sid in series_ids}

    metrics_by_key = {}
    for key, sid in SERIES.items():
        m = compute_metrics(raw.get(sid, []))
        metrics_by_key[key] = m
        if m is None:
            print(f"  {key:10s} ({sid}): no data")
        else:
            print(
                f"  {key:10s} ({sid}): "
                f"YoY {m['yoy']!r}  PoP {m['pop']!r}  "
                f"6mo-ann {m['annualized_6mo']!r}  latest={m['latestPeriod']}"
            )

    new_block = build_block(metrics_by_key)
    print("\nNew cpiData block:\n" + new_block + "\n")
    patch_html_files(files, _DATA_TAG, new_block, dry_run=dry_run)
    return 0


if __name__ == "__main__":
    sys.exit(main())

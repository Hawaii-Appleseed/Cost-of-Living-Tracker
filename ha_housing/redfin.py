"""Redfin S3 Data Center CSVs → smoothed median sale prices."""
# Extracted from redfin-price-updater.py — see that file's docstring for the
# pipeline overview. Behavior-preserving split; function bodies are unchanged.
import csv
import gzip
import io
import statistics
import sys
import urllib.request

from ha_common.http_client import fetch_bytes

from .config import COUNTY_MAP, COUNTY_URL, PROP_TYPE_MAP, STATE_URL


def download_redfin_csv(url: str, region_names: set[str]) -> list[dict]:
    """Stream a Redfin Data Center CSV and return only the rows for
    ``region_names``, re-keyed to the old market-tracker TSV columns so
    extract_hawaii_prices() is unchanged.

    The new files (2026) differ from the old TSVs in three ways that matter:
    column names are spaced ("PERIOD BEGIN", "PROPERTY TYPE"); states are
    identified by name ("Hawaii"), not code; and the sale price is
    "MEDIAN SALE PRICE NSA ($)" — one row per region/type/month, no
    seasonally-adjusted duplicate. Streaming matters: the county file is
    ~385 MB and only ~700 of its rows are Hawaiʻi.

    Note the level shift: on the overlapping months (2026-02..05) the new
    statewide median runs ~3-4% above the old file for single-family and
    ~1-7% below for condos — Redfin recomputed the history. Every value in the
    3-month window comes from the same file, so the smoothed figure stays
    internally consistent; it just steps once at the switch.
    """
    print(f"  Downloading {url.split('/')[-1]} (streaming, Hawaiʻi rows only)...")
    req = urllib.request.Request(url, headers={"User-Agent": "cost-of-living-tracker"})
    out = []
    with urllib.request.urlopen(req, timeout=300) as resp:
        lines = io.TextIOWrapper(resp, encoding="utf-8", newline="")
        for row in csv.DictReader(lines):
            name = row.get("REGION NAME", "")
            if name not in region_names:
                continue
            if row.get("FREQUENCY", "Monthly") != "Monthly":
                continue
            out.append({
                "REGION":            name,
                "STATE_CODE":        "HI" if name == "Hawaii" else "",
                "PROPERTY_TYPE":     row.get("PROPERTY TYPE", ""),
                "MEDIAN_SALE_PRICE": row.get("MEDIAN SALE PRICE NSA ($)", ""),
                "PERIOD_BEGIN":      row.get("PERIOD BEGIN", ""),
                "PERIOD_DURATION":   "30",
            })
    if not out:
        raise RuntimeError(f"no rows for {sorted(region_names)} in {url} — "
                           "has Redfin renamed its columns again?")
    return out


def download_tsv(url: str) -> list[dict]:
    """Download a gzipped TSV from Redfin's S3 bucket and return rows as dicts."""
    print(f"  Downloading {url.split('/')[-1]}...")
    raw = gzip.decompress(fetch_bytes(url))
    reader = csv.DictReader(io.StringIO(raw.decode("utf-8")), delimiter="\t")
    return list(reader)


SALE_PRICE_SMOOTHING_WINDOW = 3   # months for trailing median — see comment below


def extract_hawaii_prices(rows: list[dict], region_col: str, region_values: dict) -> dict:
    """
    Filter rows to Hawaii regions + target property types and return the
    SALE_PRICE_SMOOTHING_WINDOW-month trailing **median** sale price for each
    (region, property_type): {countyData_key: {sfhPrice: int, condoPrice: int}}.

    Why median, not the single latest month: Redfin reports the median sale
    price of whatever closed that month, and thin Hawaiʻi submarkets transact
    in tiny volumes (Kauaʻi SFH ≈ 27 sales/mo, Hawaiʻi condos ≈ 33). A single
    luxury batch swings the headline ±20% — e.g. the latest Kauaʻi SFH print
    sat ~19% above its own 3-month mean. Taking the median of the last three
    monthly prints damps that sampling noise while staying robust to a single
    outlier month (a mean would let one $5M sale drag the figure). This mirrors
    the ZORI trailing-mean treatment in fetch_zori_asking_rents().

    Redfin market-tracker files are monthly (PERIOD_DURATION == 30), so each
    (region, type, month) is one row; we still pin to the latest row's duration
    defensively in case Redfin ever mixes cadences into the same export.
    """
    # Filter to Hawaii + relevant property types
    filtered = []
    for row in rows:
        region = row.get(region_col, "").strip('"')
        prop   = row.get("PROPERTY_TYPE", "").strip('"')
        price  = row.get("MEDIAN_SALE_PRICE", "").strip('"')
        period = row.get("PERIOD_BEGIN", "").strip('"')
        dur    = row.get("PERIOD_DURATION", "").strip('"')

        if region not in region_values or prop not in PROP_TYPE_MAP:
            continue
        if not price or not period:
            continue

        filtered.append({
            "key":    region_values[region],
            "field":  PROP_TYPE_MAP[prop],
            "price":  int(float(price)),
            "period": period,
            "dur":    dur,
        })

    # Group every observation per (key, field), then take the trailing-median
    # of the most recent N monthly prints (restricted to the latest row's
    # cadence, deduped to one price per month).
    series: dict[tuple[str, str], list[dict]] = {}
    for row in filtered:
        series.setdefault((row["key"], row["field"]), []).append(row)

    result: dict[str, dict] = {}
    for (key, field), obs in series.items():
        obs.sort(key=lambda r: r["period"])
        latest_dur = obs[-1]["dur"]
        by_period = {r["period"]: r["price"] for r in obs if r["dur"] == latest_dur}
        window_periods = sorted(by_period)[-SALE_PRICE_SMOOTHING_WINDOW:]
        window_prices  = [by_period[p] for p in window_periods]
        smoothed       = int(round(statistics.median(window_prices)))
        latest_period  = window_periods[-1]

        raw_latest = by_period[latest_period]
        delta = (smoothed - raw_latest) / raw_latest * 100 if raw_latest else 0.0
        print(f"  {key:<9} {field:<10} {SALE_PRICE_SMOOTHING_WINDOW}-mo median "
              f"${smoothed:>9,}  (latest ${raw_latest:>9,}, {delta:+.1f}%, "
              f"n={len(window_prices)})")

        if key not in result:
            result[key] = {"period": latest_period}
        result[key][field] = smoothed
        # Keep the most recent period across both property types
        if latest_period > result[key]["period"]:
            result[key]["period"] = latest_period

    return result


def _fetch_sale_prices() -> dict:
    """Download Redfin state + county TSVs and return merged price dict.

    Returns {countyKey: {sfhPrice, condoPrice, period, ...}} for all
    Hawaii counties plus "State".  Exits the process on total failure
    (no Hawaii data at all is unrecoverable).
    """
    print("Fetching Redfin housing market data...")
    state_rows  = download_redfin_csv(STATE_URL, {"Hawaii"})
    county_rows = download_redfin_csv(COUNTY_URL, set(COUNTY_MAP))
    prices = {
        **extract_hawaii_prices(state_rows,  region_col="STATE_CODE", region_values={"HI": "State"}),
        **extract_hawaii_prices(county_rows, region_col="REGION",     region_values=COUNTY_MAP),
    }
    if not prices:
        print("ERROR: No Hawaii data found in Redfin exports")
        sys.exit(1)
    return prices

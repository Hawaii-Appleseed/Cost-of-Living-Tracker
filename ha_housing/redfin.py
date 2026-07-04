"""Redfin S3 market-tracker TSVs → smoothed median sale prices."""
# Extracted from redfin-price-updater.py — see that file's docstring for the
# pipeline overview. Behavior-preserving split; function bodies are unchanged.
import csv
import gzip
import io
import statistics
import sys

from ha_common.http_client import fetch_bytes

from .config import COUNTY_MAP, COUNTY_URL, PROP_TYPE_MAP, STATE_URL


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
    state_rows  = download_tsv(STATE_URL)
    county_rows = download_tsv(COUNTY_URL)
    prices = {
        **extract_hawaii_prices(state_rows,  region_col="STATE_CODE", region_values={"HI": "State"}),
        **extract_hawaii_prices(county_rows, region_col="REGION",     region_values=COUNTY_MAP),
    }
    if not prices:
        print("ERROR: No Hawaii data found in Redfin exports")
        sys.exit(1)
    return prices

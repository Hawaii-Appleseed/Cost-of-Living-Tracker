"""Zillow ZORI county CSV → smoothed asking rents + anchor-year averages."""
# Extracted from redfin-price-updater.py — see that file's docstring for the
# pipeline overview. Behavior-preserving split; function bodies are unchanged.
import csv
import io

from ha_common.http_client import fetch_text

from .config import RENT_ANCHOR_YEAR, ZORI_COUNTY_MAP, ZORI_STATE_POP_WEIGHTS, ZORI_URL


ZORI_SMOOTHING_WINDOW = 3   # months for trailing mean — see comment below

def fetch_zori_asking_rents() -> dict:
    """
    Download Zillow ZORI county CSV and extract:
      - A ZORI_SMOOTHING_WINDOW-month trailing mean of asking rent per
        Hawaiʻi county, written as result[key] and used as the displayed
        askRent (and as numerator in the ZORI growth ratio feeding the
        blended rent nowcast).
      - The RENT_ANCHOR_YEAR annual average per county, used as a common
        anchor with BLS rent CPI for the blended nowcast
        (→ result["_anchor_avg"][key])

    Returns {countyData_key: askRent_int, "_period": "YYYY-MM",
             "_anchor_avg": {...}, "_anchor_year": "YYYY", "_yoy_pct": {...},
             "_smoothing_window": int}.
    State-level askRent is derived as a population-weighted average
    (Honolulu ~72%, Hawaii ~14%, Maui ~10%, Kauai ~4%) of the smoothed
    county values.

    Why smooth: ZORI is already a "smoothed mean" (the _sm_ in the URL) but
    its sample size on thin markets — Kauaʻi especially — is small enough
    that a single luxury batch entering the listings pool can swing the
    headline number by 15-20% in one month (e.g. the 2026-04 print of
    $5,255 vs. a 12-month band of $4.3k–$4.5k). Averaging the latest 3
    monthly prints dampens these sampling artifacts without materially
    changing the trend signal Zillow already publishes.

    The anchor-year average MUST track RENT_ANCHOR_YEAR — the BLS rent CPI
    ratio is computed against the same year, and the blended nowcast assumes
    both series share the anchor. A drifted anchor here would silently shift
    the ZORI growth factor relative to BLS. (Anchor stays a full-year mean —
    only the *current* read is windowed.)
    """
    print(f"  Downloading {ZORI_URL.split('/')[-1]}...")
    raw = fetch_text(ZORI_URL)

    reader = csv.reader(io.StringIO(raw))
    headers = next(reader)

    # Pre-compute which column indices belong to RENT_ANCHOR_YEAR for the
    # anchor-avg calc. ZORI column headers are ISO dates like "2024-01-31".
    anchor_prefix = f"{RENT_ANCHOR_YEAR}-"
    cols_anchor = [i for i, h in enumerate(headers) if h.startswith(anchor_prefix)]

    result = {}
    anchor_avg = {}
    yoy_pct = {}   # per-county YoY % using same-month-prior-year column
    recent_points = {}  # per-county ascending [{year,period,value}] for extrapolation
    latest_date_header = None  # e.g. "2026-03-31" → we'll convert to "2026-03"
    for row in reader:
        if len(row) < 10:
            continue
        region_name = row[2]
        state       = row[5]
        if state != "HI" or region_name not in ZORI_COUNTY_MAP:
            continue

        # Find the last non-empty column (most recent month) — return both value and header
        last_idx = next(
            (i for i in range(len(row) - 1, 8, -1) if row[i].strip()),
            None,
        )
        if last_idx is None:
            continue

        key = ZORI_COUNTY_MAP[region_name]

        # Walk backward from the latest non-empty cell collecting up to
        # ZORI_SMOOTHING_WINDOW numeric values, then take the mean. Skips
        # blank or unparseable cells. Falls back to whatever fewer values
        # are available (handles Zillow's late-arriving small-market
        # coverage — e.g. Kauaʻi has only had data since Feb 2025).
        window_vals = []
        for i in range(last_idx, 8, -1):
            cell = row[i].strip() if i < len(row) else ""
            if not cell:
                continue
            try:
                window_vals.append(float(cell))
            except ValueError:
                continue
            if len(window_vals) >= ZORI_SMOOTHING_WINDOW:
                break
        if not window_vals:
            continue
        result[key] = round(sum(window_vals) / len(window_vals))

        # Collect up to 8 recent (header-date, value) pairs as ASCENDING
        # {year, period:"MNN", value} points so the blend can extrapolate this
        # county's ZORI ratio forward to the common target month. ZORI headers
        # are ISO dates "YYYY-MM-DD".
        pts = []
        for i in range(last_idx, 8, -1):
            cell = row[i].strip() if i < len(row) else ""
            hdr  = headers[i] if i < len(headers) else ""
            if not cell or len(hdr) < 7:
                continue
            try:
                val = float(cell)
            except ValueError:
                continue
            pts.append({"year": int(hdr[:4]), "period": f"M{hdr[5:7]}", "value": val})
            if len(pts) >= 8:
                break
        if pts:
            recent_points[key] = list(reversed(pts))  # ascending

        # Capture the column header (date) once; should be identical across counties
        if latest_date_header is None and last_idx < len(headers):
            latest_date_header = headers[last_idx]

        # Anchor-year annual average — skip empty cells / unparseable values
        vals_anchor = []
        for i in cols_anchor:
            if i < len(row) and row[i].strip():
                try:
                    vals_anchor.append(float(row[i]))
                except ValueError:
                    pass
        if vals_anchor:
            anchor_avg[key] = sum(vals_anchor) / len(vals_anchor)

        # YoY: current column vs the column 12 months earlier. ZORI publishes
        # every month so the same position back by 12 is the same calendar month
        # a year ago. Used by the NTR/ATR sanity-check audit.
        if last_idx >= 12 + 9:  # +9 is the first data column (after metadata)
            prior_cell = row[last_idx - 12].strip() if last_idx - 12 < len(row) else ""
            if prior_cell:
                try:
                    prior_val = float(prior_cell)
                    if prior_val > 0:
                        yoy_pct[key] = (float(row[last_idx]) / prior_val - 1.0) * 100.0
                except ValueError:
                    pass

    # Compute statewide weighted average if all counties present
    weights = ZORI_STATE_POP_WEIGHTS
    if all(k in result for k in weights):
        state_avg = sum(result[k] * w for k, w in weights.items())
        result["State"] = round(state_avg)
    # Statewide ZORI YoY via the same population weights, on the counties
    # that actually have a YoY value (Zillow can lag publishing small-market
    # YoYs by a few months; re-normalize across whatever's present).
    present_yoy = {k: weights[k] for k in weights if k in yoy_pct}
    if len(present_yoy) >= 2:
        wsum = sum(present_yoy.values())
        yoy_pct["State"] = sum(
            yoy_pct[k] * (w / wsum) for k, w in present_yoy.items()
        )
    # For the anchor-year average, allow partial coverage (Zillow started
    # publishing some small-market counties like Kauai only recently, so Kauai
    # can be missing from the anchor year even when its current value is
    # reported). When that happens, re-normalize the weights across the
    # counties we actually have.
    present_anchor = {k: weights[k] for k in weights if k in anchor_avg}
    if len(present_anchor) >= 2:
        wsum = sum(present_anchor.values())
        anchor_avg["State"] = sum(
            anchor_avg[k] * (w / wsum) for k, w in present_anchor.items()
        )

    # Convert "2026-03-31" → "2026-03" for consistency with other period fields
    if latest_date_header and len(latest_date_header) >= 7:
        result["_period"] = latest_date_header[:7]

    result["_anchor_avg"] = anchor_avg
    result["_anchor_year"] = RENT_ANCHOR_YEAR
    result["_yoy_pct"] = yoy_pct  # per-county YoY % — used by NTR/ATR audit
    result["_smoothing_window"] = ZORI_SMOOTHING_WINDOW
    result["_recent_points"] = recent_points  # per-county ascending monthly points
    return result

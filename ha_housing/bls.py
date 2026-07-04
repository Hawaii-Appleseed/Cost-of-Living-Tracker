"""BLS series ratios: rent CPI scaling + realized-burden nowcast factors."""
# Extracted from redfin-price-updater.py — see that file's docstring for the
# pipeline overview. Behavior-preserving split; function bodies are unchanged.
import os

from ha_common.http_client import fetch_bytes

from .config import (
    BLS_API_URL, BLS_BASE_YEAR, BLS_CPI_ALL_ITEMS_HNL, BLS_RENT_SERIES,
    BLS_RENT_SMOOTHING_WINDOW, BLS_WAGES_HI_PRIVATE, RENT_ANCHOR_YEAR,
)


def fetch_bls_series_ratio(series_id: str, anchor_year: str,
                           trailing_window: int = 1) -> tuple[float, str] | tuple[None, None]:
    """
    Generic BLS series ratio fetcher. Returns (numerator / anchor_year_avg, period).
    Anchor avg is the mean of all monthly observations in `anchor_year` (the ACS
    vintage YEAR, e.g. 2024 — a full-year average, not a 5-year mid-point).

    `trailing_window` (item 6): the numerator is the mean of the most recent
    `trailing_window` monthly observations rather than the single latest print.
    Used =12 for the CES wage series (the burden income denominator) so the
    factor isn't whipsawed by December-bonus seasonality (the series is NSA) or
    a single noisy print that would otherwise move every county's burden in
    lockstep. =1 (default) keeps the single-latest behaviour for CPI legs.
    """
    import json
    api_key = os.environ.get("BLS_API_KEY", "")
    end_year = str(int(anchor_year) + 5)  # cover anchor + ~5 years of nowcast room
    payload = json.dumps({
        "seriesid":  [series_id],
        "startyear": anchor_year,
        "endyear":   end_year,
        **({"registrationkey": api_key} if api_key else {}),
    }).encode()
    try:
        resp = json.loads(fetch_bytes(BLS_API_URL, data=payload, headers={"Content-Type": "application/json"}))
    except (OSError, json.JSONDecodeError) as e:
        print(f"  WARNING: BLS fetch for {series_id} failed ({e})")
        return None, None
    if resp.get("status") != "REQUEST_SUCCEEDED":
        print(f"  WARNING: BLS {series_id} returned {resp.get('status')}: {resp.get('message')}")
        return None, None
    rows = resp["Results"]["series"][0]["data"]
    if not rows:
        return None, None
    # Filter to numeric monthly observations. BLS uses "-" for missing
    # values; skip those rather than crashing the entire nowcast.
    def _parse(r):
        try:
            return float(r["value"])
        except (ValueError, TypeError):
            return None
    monthly = [(r["year"], r["period"], _parse(r))
               for r in rows
               if r["period"].startswith("M") and r["period"] != "M13"]
    monthly = [(y, p, v) for (y, p, v) in monthly if v is not None]
    if not monthly:
        return None, None
    monthly.sort()
    anchor_vals = [v for (y, p, v) in monthly if y == anchor_year]
    if not anchor_vals:
        return None, None
    anchor_avg = sum(anchor_vals) / len(anchor_vals)
    y_last, p_last, _ = monthly[-1]
    latest_period = f"{y_last}-{p_last[1:]}"   # M04 → 04
    # Numerator: trailing-window mean (window=1 → single latest print).
    window = monthly[-trailing_window:] if trailing_window > 1 else monthly[-1:]
    numerator = sum(v for (_, _, v) in window) / len(window)
    return numerator / anchor_avg, latest_period


def nowcast_burden_anchors(anchor: dict, anchor_year: str) -> dict:
    """
    Apply BLS-driven nowcast factors to the ACS realized-burden anchor.

    Math (per METHODOLOGY.md §2.4):
        rent_factor   = CPI_rent_HNL(latest)  / CPI_rent_HNL(anchor_avg)
        cost_factor   = CPI_all_HNL(latest)   / CPI_all_HNL(anchor_avg)
        income_factor = wage_HI(latest)       / wage_HI(anchor_avg)

        tenantRentPTI    = tenantGRAPI  × rent_factor / income_factor
        mortgageOwnerPTI = ownerSMOCAPI × cost_factor / income_factor

    Factors apply uniformly across counties (BLS doesn't publish
    county-level CPI or wages for Hawaiʻi; statewide is the finest
    Hawaiʻi-specific series available). Cost-burden shares are not
    nowcasted — they're tagged as ACS 5-yr in the UI.

    `anchor_year` is the ACS vintage YEAR (RENT_ANCHOR_YEAR, e.g. 2024) — each
    factor's denominator is that year's full-year average, NOT a 5-year
    mid-point. The three series (rent CPI, all-items CPI, CES wages) publish on
    different lags, so each factor's numerator may be a different latest month;
    `_nowcastPeriod` reports the wage series' latest period (the income
    denominator on both PTI numbers), and the factor periods are printed
    individually below for transparency.

    Returns anchor extended with nowcasted fields per county.
    """
    if not anchor:
        return {}

    # Cost-burden shares are NOT nowcasted (they're slow-moving ACS 5-yr
    # distributional shares). Round them up-front so the field values are
    # tight regardless of whether the BLS-driven PTI nowcast succeeds —
    # otherwise a transient BLS API outage would leak raw floats with
    # 16 decimal digits into the HTML countyData block.
    for key in ("State", "Honolulu", "Maui", "Hawaii", "Kauai"):
        if key not in anchor:
            continue
        a = anchor[key]
        for k in ("rentBurdenedPct", "rentSeverelyBurdenedPct",
                  "ownerBurdenedPct", "ownerSeverelyBurdenedPct"):
            if a.get(k) is not None:
                a[k] = round(a[k], 4)

    rent_ratio,  rent_period = fetch_bls_series_ratio(BLS_RENT_SERIES,       anchor_year)
    cost_ratio,  cost_period = fetch_bls_series_ratio(BLS_CPI_ALL_ITEMS_HNL, anchor_year)
    # Wage (income denominator): trailing-12-month mean — the CES series is NSA,
    # so a single latest month carries bonus/seasonal noise that would move every
    # county's burden in lockstep (item 6). Costs ~6 mo of extra lag, fine for a
    # slow-moving denominator. The numerator periods still differ by series; the
    # UI label tracks the wage series (the shared denominator).
    wage_ratio,  wage_period = fetch_bls_series_ratio(BLS_WAGES_HI_PRIVATE,  anchor_year,
                                                      trailing_window=12)
    if None in (rent_ratio, cost_ratio, wage_ratio):
        print(f"  WARNING: realized-burden nowcast skipped (missing BLS factor: "
              f"rent={rent_ratio}, cost={cost_ratio}, wage={wage_ratio})")
        return anchor
    # `_nowcastPeriod` (UI label) tracks the wage series — the income
    # denominator shared by both PTI numbers. Print each factor's own latest
    # period too, since the three series publish on different lags.
    nowcast_period = wage_period
    print(f"  Nowcast factors (anchor {anchor_year} avg → latest): "
          f"rent={rent_ratio:.3f} ({rent_period}), "
          f"cost={cost_ratio:.3f} ({cost_period}), "
          f"wage={wage_ratio:.3f} ({wage_period})")
    for key in ("State", "Honolulu", "Maui", "Hawaii", "Kauai"):
        if key not in anchor:
            continue
        a = anchor[key]
        if a.get("tenantGRAPI") is not None:
            a["tenantRentPTI"] = round(a["tenantGRAPI"] * (rent_ratio / wage_ratio), 4)
        if a.get("ownerSMOCAPI") is not None:
            a["mortgageOwnerPTI"] = round(a["ownerSMOCAPI"] * (cost_ratio / wage_ratio), 4)
    anchor["_nowcastPeriod"] = nowcast_period
    return anchor


def fetch_bls_rent_ratio() -> tuple[float, float, str, float | None]:
    """
    Fetch BLS CPI series CUURS49ASEHA (Honolulu MSA, rent of primary residence)
    and return (ratio_now, ratio_smoothed, period, yoy_pct).

    ratio_now     — latest_idx / RENT_ANCHOR_YEAR annual avg (single-month)
    ratio_smoothed— mean of the last BLS_RENT_SMOOTHING_WINDOW monthly ratios
                    against the same anchor average. Use this for the blended
                    nowcast so a single bumpy CPI print doesn't swing the
                    headline rent (Q1 of the rent-nowcast improvement plan).
                    ZORI input already uses the same window — matching it
                    means both legs of the blend are 3-month means.
    period        — ISO "YYYY-MM" of the latest observation
    yoy_pct       — 12-month YoY % change for the same month one year prior,
                    or None if the prior observation is unavailable.

    Raises on network/parse failure so callers can decide whether to fall back
    to raw ACS values.
    """
    import json
    import datetime

    api_key = os.environ.get("BLS_API_KEY", "")
    current_year = str(datetime.date.today().year)
    payload = json.dumps({
        "seriesid": [BLS_RENT_SERIES],
        "startyear": BLS_BASE_YEAR,
        "endyear": current_year,
        **({"registrationkey": api_key} if api_key else {}),
    }).encode()
    data = json.loads(
        fetch_bytes(BLS_API_URL, data=payload, headers={"Content-Type": "application/json"})
    )

    series_data = data["Results"]["series"][0]["data"]

    # Base-year annual average (exclude M13 annual row, skip "-" missing)
    base_vals = [
        float(r["value"])
        for r in series_data
        if r["year"] == BLS_BASE_YEAR
        and r["period"].startswith("M")
        and r["period"] != "M13"
        and r["value"] != "-"
    ]
    if not base_vals:
        raise ValueError(f"No BLS monthly data found for base year {BLS_BASE_YEAR}")
    base_avg = sum(base_vals) / len(base_vals)

    # Monthly observations, skipping the annual M13 row and "-". BLS returns
    # newest-first today, but don't rely on that — sort explicitly descending by
    # (year, period) so `monthly[0]` is always the latest print and the
    # smoothing window below is always the trailing N. (A silent ascending
    # response would otherwise anchor the headline rent to the oldest month.)
    monthly = [
        r for r in series_data
        if r["period"].startswith("M")
        and r["period"] != "M13"
        and r["value"] != "-"
    ]
    monthly.sort(key=lambda r: (r["year"], r["period"]), reverse=True)
    if not monthly:
        raise ValueError("No recent BLS monthly value found")
    recent = monthly[0]

    current_idx = float(recent["value"])
    ratio_now   = current_idx / base_avg
    period      = f"{recent['year']}-{recent['period'][1:].zfill(2)}"  # e.g. "2026-03"

    # Smoothed ratio — trailing mean of the most recent
    # BLS_RENT_SMOOTHING_WINDOW monthly ratios. Mirrors the ZORI smoothing
    # in fetch_zori_asking_rents so the blended output isn't whipsawed by
    # a single bumpy CPI print (BLS Honolulu rent has notoriously sparse
    # sampling — each unit gets revisited every 6 months, so single-print
    # noise can be substantial).
    window = monthly[:BLS_RENT_SMOOTHING_WINDOW]
    ratio_smoothed = sum(float(r["value"]) / base_avg for r in window) / len(window)

    # YoY vs. same month a year ago (skip if prior-year observation missing —
    # common when the "current year" is also the anchor year).
    prior_year = str(int(recent["year"]) - 1)
    prior = next(
        (
            r for r in series_data
            if r["year"] == prior_year
            and r["period"] == recent["period"]
            and r["value"] != "-"
        ),
        None,
    )
    yoy_pct: float | None = None
    if prior is not None:
        prior_val = float(prior["value"])
        if prior_val > 0:
            yoy_pct = (current_idx / prior_val - 1.0) * 100.0

    yoy_str = f", YoY {yoy_pct:+.2f}%" if yoy_pct is not None else ""
    print(f"  BLS {BLS_RENT_SERIES}: base_avg={base_avg:.2f}, current={current_idx:.3f}, "
          f"ratio={ratio_now:.4f} (3-mo smoothed {ratio_smoothed:.4f}, period {period}{yoy_str})")
    # Ascending {year, period, value} points (most recent ~8) for target-month
    # extrapolation in the blend. base_avg is the anchor-year average so callers
    # can build the ratio at any target month via extrapolate_ratio_to().
    points = [
        {"year": int(r["year"]), "period": r["period"], "value": float(r["value"])}
        for r in sorted(monthly, key=lambda r: (r["year"], r["period"]))[-8:]
    ]
    return ratio_now, ratio_smoothed, period, yoy_pct, base_avg, points


def fetch_bls_rent(honolulu_acs_anchor: int) -> dict:
    """
    Scales the live ACS Honolulu contract rent (from the current run's
    fetch_census_rent()) by the BLS CPI index ratio to produce a
    monthly-current estimate for existing-tenant rent in Honolulu.
    Neighbor islands are scaled in main() using the ratio directly
    (see fetch_bls_rent_ratio).

    *honolulu_acs_anchor* must be the ACS {RENT_ANCHOR_YEAR} 5-year
    Honolulu contract rent (dollars). Passing the wrong vintage here
    double-scales the index and produces a silently wrong dollar value.

    Returns {"Honolulu": {"rent": int}, "_period": "YYYY-MM",
             "_ratio": float (latest, single-month),
             "_ratio_smoothed": float (3-month trailing mean for blend),
             "_yoy_pct": float|None,
             "_base_avg": float (anchor-year index average),
             "_points": [{year,period,value}, …] ascending (for extrapolation)}.

    The CPI-only `rent` value uses the latest single-month ratio (it's a
    display fallback when the blend can't run). The blended nowcast in
    _fetch_rents() reads _ratio_smoothed (and _points/_base_avg for the
    target-month alignment).
    """
    ratio_now, ratio_smoothed, period, yoy_pct, base_avg, points = fetch_bls_rent_ratio()
    scaled_rent   = round(honolulu_acs_anchor * ratio_now)
    print(f"  → Honolulu rent ${scaled_rent:,} "
          f"(anchor ACS {RENT_ANCHOR_YEAR} ${honolulu_acs_anchor:,} × ratio {ratio_now:.4f}, "
          f"BLS period {period})")
    return {
        "Honolulu":         {"rent": scaled_rent},
        "_period":          period,
        "_ratio":           ratio_now,
        "_ratio_smoothed":  ratio_smoothed,
        "_yoy_pct":         yoy_pct,
        "_base_avg":        base_avg,
        "_points":          points,
    }

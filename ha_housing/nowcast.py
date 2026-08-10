"""Rent nowcast models: convex blend, log-space pass-through, extrapolation."""
# Extracted from redfin-price-updater.py — see that file's docstring for the
# pipeline overview. Behavior-preserving split; function bodies are unchanged.
from .config import BLENDED_RENT_CPI_WEIGHT, BLS_RENT_SERIES, NTR_ATR_BENCHMARKS_PATH

# Canonical damped-trend projection helpers (same source the grocery/TFP side
# uses — see tfp-updater.py). Reused here to bring a lagging monthly rent leg
# forward to a common target month so the blend's legs share one endpoint
# instead of each ending at its own latest print. Soft-optional: if the
# package isn't installed the rent nowcast falls back to NOT extrapolating
# (legs stay at their own latest month, the pre-alignment behaviour).
try:
    from census_forecaster.bls.projection import (   # noqa: E402
        smoothed_monthly_rate as _bls_smoothed_monthly_rate,
        damped_compound_factor as _bls_damped_compound_factor,
        PROJ_MONTHLY_CAP as _PROJ_MONTHLY_CAP,
    )
    _PROJECTION_AVAILABLE = True
except ImportError:
    _PROJECTION_AVAILABLE = False
    _PROJ_MONTHLY_CAP = 0.0189


def _ym_of(period_iso: str) -> tuple[int, int]:
    """'2026-05' → (2026, 5)."""
    y, m = period_iso.split("-")
    return int(y), int(m)


def _months_ahead(from_ym: tuple[int, int], to_ym: tuple[int, int]) -> int:
    """Signed month count from from_ym to to_ym (negative if to_ym is earlier)."""
    return (to_ym[0] - from_ym[0]) * 12 + (to_ym[1] - from_ym[1])


def extrapolate_ratio_to(
    points: list[dict],
    anchor_avg: float,
    target_ym: tuple[int, int],
) -> float | None:
    """Growth ratio of a monthly series at *target_ym* vs *anchor_avg*.

    `points` is an ASCENDING list of {year:int, period:"MNN", value:float}.
    Returns value_at(target) / anchor_avg, where value_at(target) is:
      • the latest observed value, if target ≤ latest observation, OR
      • the latest value carried forward to target via the canonical
        damped-trend extrapolation (smoothed_monthly_rate → clip ±cap →
        damped_compound_factor — the same machinery the grocery/TFP side
        uses, see tfp-updater.py).

    This is what lets the blend's lagging leg (e.g. ZORI a month behind BLS)
    be brought to a single common target month so the legs share one endpoint.
    If the projection package is unavailable, or the trend can't be estimated,
    the latest value is used as-is (no extrapolation) — never an error.
    """
    if not points or not anchor_avg:
        return None
    latest = points[-1]
    latest_ym = (latest["year"], int(latest["period"][1:]))
    n = _months_ahead(latest_ym, target_ym)
    if n <= 0 or not _PROJECTION_AVAILABLE:
        return latest["value"] / anchor_avg
    rate = _bls_smoothed_monthly_rate(points)
    if rate is None:
        return latest["value"] / anchor_avg
    rate = max(min(rate, _PROJ_MONTHLY_CAP), -_PROJ_MONTHLY_CAP)
    factor = _bls_damped_compound_factor(rate, n)
    return latest["value"] * factor / anchor_avg


def blend_rent_nowcast(
    acs_anchor: float,
    bls_ratio: float,
    zori_ratio: float,
    cpi_weight: float = BLENDED_RENT_CPI_WEIGHT,
    *,
    fmr_ratio:   float | None = None,
    fmr_weight:  float = 0.0,
    zori_weight: float | None = None,
) -> dict:
    """
    Blend BLS-CPI-scaled rent (lagging ~12 mo) with ZORI-implied rent (leading),
    plus an optional HUD-FMR third leg, to nowcast current tenant rent. Every
    component uses the same ACS dollar anchor (RENT_ANCHOR_YEAR); only the
    anchor→present growth factor differs.

      bls_ratio    = CUURS49FSEHA(latest 3-mo trailing mean) / anchor annual avg
                     [smoothed via BLS_RENT_SMOOTHING_WINDOW — see fetch_bls_rent_ratio]
      zori_ratio   = ZORI(latest 3-mo trailing mean) / ZORI(anchor annual avg)
                     [per county; state ratio used as proxy when a county's
                      anchor avg is missing]
      fmr_ratio    = HUD 2-BR FMR(latest FY) / FMR(anchor FY) — a genuinely
                     county-specific (and Kauaʻi-available) growth signal. Only
                     supplied for the counties in BLENDED_RENT_3LEG_WEIGHTS
                     (Hawaiʻi, Kauaʻi); None elsewhere → 2-leg blend.
      cpi_weight   = per-county CPI weight (see BLENDED_RENT_CPI_WEIGHTS /
                     BLENDED_RENT_3LEG_WEIGHTS).

    Weight handling:
      • 2-leg (default): fmr_weight=0, zori_weight=None → zori_weight = 1−cpi_weight.
      • 3-leg: caller passes explicit cpi/zori/fmr weights (summing to 1).
      blended_factor = cpi_w·bls_ratio + zori_w·zori_ratio + fmr_w·fmr_ratio

    If fmr_ratio is None or fmr_weight is 0 the FMR leg is dropped and its
    weight is folded back onto ZORI so the blend never silently under-sums.

    Returns a dict with the blended value plus each single-source component so
    callers can log them all (useful for audit and the methodology tooltip).
    """
    cpi_w = cpi_weight
    use_fmr = fmr_ratio is not None and fmr_weight > 0
    fmr_w   = fmr_weight if use_fmr else 0.0
    # Default ZORI weight makes the 2-leg case behave exactly as before; in the
    # 3-leg case the caller passes an explicit zori_weight. If the FMR leg is
    # requested but unavailable, its weight is reassigned to ZORI.
    if zori_weight is None:
        zori_w = 1.0 - cpi_w
    else:
        zori_w = zori_weight + (fmr_weight if not use_fmr else 0.0)

    blended_factor = cpi_w * bls_ratio + zori_w * zori_ratio
    if use_fmr:
        blended_factor += fmr_w * fmr_ratio

    return {
        "blended":      round(acs_anchor * blended_factor),
        "cpi_scaled":   round(acs_anchor * bls_ratio),
        "zori_implied": round(acs_anchor * zori_ratio),
        "fmr_implied":  round(acs_anchor * fmr_ratio) if use_fmr else None,
        "bls_ratio":    bls_ratio,
        "zori_ratio":   zori_ratio,
        "fmr_ratio":    fmr_ratio if use_fmr else None,
        "cpi_weight":   cpi_w,
        "zori_weight":  zori_w,
        "fmr_weight":   fmr_w,
    }


# ── Lease-turnover pass-through model (Q-audit item 4) ───────────────────────
# A convex blend `w·cpi + (1−w)·zori` can never leave the interval between its
# legs, so when BOTH proxies undershoot realized stock-rent growth (the Big
# Island 2022→24 case: ACS +31% vs CPI +10%, ZORI +16%) no weighting can reach
# the target. The pass-through model instead treats stock (existing-tenant) rent
# as converging on asking rent as leases turn over:
#
#   passthrough_factor = cpi_factor^(1−λ) · zori_factor^λ
#
# a log-space bridge between the realized CPI growth factor and the asking-rent
# (ZORI) growth factor since the anchor. λ is the pass-through completeness:
#   λ = 0   → pure CPI (no catch-up to asking)
#   λ = 1   → fully caught up to current asking
#   λ > 1   → overshoot — projects continued catch-up toward accumulated asking
#             growth even after asking flattens; THIS is what lets the model
#             exceed both contemporaneous legs (the convex blend cannot).
# One interpretable parameter instead of five hand-tuned county weights. λ is
# calibrated by scripts/backtest_rent_nowcast.py against ACS 1-yr ground truth
# and only promoted to production if it beats the blend within the 8% budget.
# Calibrated by scripts/backtest_rent_nowcast.py (2026-06-11 run): on the
# outer-island ACS 1-yr ground truth, λ=0.65 gives 5.59% MAPE — beating the best
# convex blend (5.64% at w=0.4) and well inside the 8% budget. λ>1 overshoot
# also cut the Big Island (Hawaiʻi) error 7.83%→6.42% by projecting continued
# catch-up to accumulated asking-rent growth, which no convex blend could reach.
RENT_PASSTHROUGH_LAMBDA = 0.65

# Which model drives the published `rent`. "blend" = the legacy convex
# CPI/ZORI(/FMR) blend; "passthrough" = the log-space pass-through model above.
# Promoted to "passthrough" after the 2026-06-11 backtest gate confirmed it beats
# the blend within the 8% MAPE budget (Q-audit item 4). Both paths are always
# computed for logging; this only selects what's written. To re-validate after a
# re-anchor, re-run scripts/backtest_rent_nowcast.py (see METHODOLOGY.md).
RENT_PRODUCTION_METHOD = "passthrough"


def passthrough_rent_nowcast(
    acs_anchor: float,
    cpi_factor: float,
    zori_factor: float,
    lam: float = RENT_PASSTHROUGH_LAMBDA,
) -> dict:
    """Lease-turnover pass-through nowcast (see RENT_PASSTHROUGH_LAMBDA).

    rent = acs_anchor · cpi_factor^(1−λ) · zori_factor^λ

    Both factors are growth ratios vs. the same ACS anchor year. Returns the
    same component keys as blend_rent_nowcast() (cpi_scaled/zori_implied) plus
    the realized `passthrough` value and the λ used, so callers can log all
    three and the methodology tooltip can show the method.
    """
    pt_factor = (cpi_factor ** (1.0 - lam)) * (zori_factor ** lam)
    return {
        "passthrough":  round(acs_anchor * pt_factor),
        "cpi_scaled":   round(acs_anchor * cpi_factor),
        "zori_implied": round(acs_anchor * zori_factor),
        "cpi_factor":   cpi_factor,
        "zori_factor":  zori_factor,
        "lambda":       lam,
    }


def round_to_25(x: float | int | None) -> int | None:
    """Round a rent dollar value to the nearest $25 (Q-audit item 8).

    Dollar-precise rents ($1,753) imply ±$1 confidence on a ±5–9% estimate;
    nearest-$25 quietly drops the false precision. None passes through.
    """
    if x is None:
        return None
    return int(round(x / 25.0) * 25)


def _load_ntr_atr_benchmarks() -> dict:
    """Load the manually-refreshed national NTR/ATR YoY benchmark file.

    Missing file or missing values → returns an empty-ish dict with `ntr_yoy_pct`
    and `atr_yoy_pct` both None. Callers degrade gracefully to a reduced audit.
    """
    import json
    empty = {"ntr_yoy_pct": None, "atr_yoy_pct": None,
             "latest_quarter": None, "last_refreshed": None,
             "sanity_band_pp": 8.0}
    if not NTR_ATR_BENCHMARKS_PATH.exists():
        return empty
    try:
        d = json.loads(NTR_ATR_BENCHMARKS_PATH.read_text())
    except (json.JSONDecodeError, OSError):
        return empty
    return {
        "ntr_yoy_pct":    d.get("ntr_yoy_pct"),
        "atr_yoy_pct":    d.get("atr_yoy_pct"),
        "latest_quarter": d.get("latest_quarter"),
        "last_refreshed": d.get("last_refreshed"),
        "sanity_band_pp": float(d.get("_sanity_band_pp") or 8.0),
    }


def audit_rent_nowcast_vs_ntr(
    hnl_cpi_yoy:  float | None,
    hnl_zori_yoy: float | None,
    cpi_weight:   float = BLENDED_RENT_CPI_WEIGHT,
) -> None:
    """Print a dev-facing sanity check: Honolulu rent signals vs national NTR/ATR.

    No HTML surface, no return value. Run after the blended nowcast so we can
    log what percentage change each component (existing tenant, asking, blended)
    is showing and compare it to the BLS national research series. A divergence
    greater than *sanity_band_pp* prints a WARNING — it doesn't block the run.

    BLS R-CPI-NTR/R-CPI-ATR are national only (no Hawaii cut exists), so this
    is a directional check, not an equality test. We expect Hawaii to run
    hotter than national during tight-supply periods and cooler when the
    mainland surges (post-2021).
    """
    bm = _load_ntr_atr_benchmarks()
    ntr, atr = bm["ntr_yoy_pct"], bm["atr_yoy_pct"]

    # Honolulu blended YoY: since blend is linear in the two ratios and both
    # ratios share the same ACS anchor, the blended 12-month % change equals
    # w·CPI_YoY + (1-w)·ZORI_YoY (first-order Taylor; ratios near 1 → the
    # approximation is within ~0.1 pp of the exact blended ratio-of-ratios).
    hnl_blended_yoy = None
    if hnl_cpi_yoy is not None and hnl_zori_yoy is not None:
        hnl_blended_yoy = cpi_weight * hnl_cpi_yoy + (1 - cpi_weight) * hnl_zori_yoy

    band = bm["sanity_band_pp"]
    q    = bm["latest_quarter"] or "— benchmark not yet refreshed —"

    def _fmt(v):
        return f"{v:+.2f}%" if v is not None else "   n/a  "

    print(f"\nRent sanity check — Honolulu vs national NTR/ATR (BLS {q})")
    print(f"  Honolulu BLS rent CPI  YoY: {_fmt(hnl_cpi_yoy)}   "
          f"← existing tenants ({BLS_RENT_SERIES})")
    print(f"  Honolulu ZORI asking   YoY: {_fmt(hnl_zori_yoy)}   "
          f"← new listings (Zillow ZORI)")
    print(f"  National R-CPI-NTR     YoY: {_fmt(ntr)}   "
          f"← new tenants (national research series)")
    print(f"  National R-CPI-ATR     YoY: {_fmt(atr)}   "
          f"← all tenants (national research series)")
    print(f"  Honolulu blended       YoY: {_fmt(hnl_blended_yoy)}   "
          f"← {int(cpi_weight*100)}·CPI + {int((1-cpi_weight)*100)}·ZORI")

    # Warn when Honolulu blended diverges sharply from national NTR — the closest
    # national analog to our nowcast (both emphasize new-tenant momentum). If no
    # benchmark, skip with a hint so the user knows why.
    if ntr is None:
        print(f"  (no NTR benchmark on file — refresh {NTR_ATR_BENCHMARKS_PATH.name} "
              f"from https://www.bls.gov/cpi/research-series/r-cpi-ntr.htm)")
        return
    if hnl_blended_yoy is None:
        return
    gap = hnl_blended_yoy - ntr
    if abs(gap) > band:
        print(f"  ⚠ WARNING: Honolulu blended YoY differs from national NTR by "
              f"{gap:+.2f} pp (band ±{band:.1f} pp). Investigate before publishing.")

"""Mortgage math: FRED live rate, P&I, derived idx/gap/mortgage/PTI."""
# Extracted from redfin-price-updater.py — see that file's docstring for the
# pipeline overview. Behavior-preserving split; function bodies are unchanged.
from ha_common.http_client import fetch_bytes

from .config import (
    DOWN_PAYMENT_FRAC, DTI_FRONT_FRAC, FRED_API_KEY, FRED_MORTGAGE_SERIES,
    MORTGAGE_RATE_PCT, MORTGAGE_TERM_MONTHS,
)


def _monthly_pi(price: float, rate_pct: float) -> float:
    """Monthly principal+interest on a 30-yr fixed loan at *rate_pct*, 20% down."""
    loan = price * (1.0 - DOWN_PAYMENT_FRAC)
    r    = rate_pct / 100.0 / 12.0
    n    = MORTGAGE_TERM_MONTHS
    if r == 0:
        return loan / n
    return loan * r * (1 + r) ** n / ((1 + r) ** n - 1)


def _afford_price(income: float, rate_pct: float) -> float:
    """Max purchase price a household at *income* can afford — mirrors the
    dashboard's calcAffordPrice(): 30% of gross income to P&I, 30-yr fixed,
    20% down."""
    monthly_max = income / 12.0 * DTI_FRONT_FRAC
    r = rate_pct / 100.0 / 12.0
    n = MORTGAGE_TERM_MONTHS
    loan_amt = monthly_max * n if r == 0 else monthly_max * (1 - (1 + r) ** -n) / r
    ltv = max(0.001, 1.0 - DOWN_PAYMENT_FRAC)
    return loan_amt / ltv


def fetch_mortgage_rate() -> float:
    """Fetch the latest weekly 30-yr fixed mortgage rate (Freddie Mac PMMS) from
    FRED series MORTGAGE30US. Returns a percent float (e.g. 6.38).

    This is the single source of truth for the rate that drives the static
    idx/gap/PTI literals AND the HTML slider default — removing the old footgun
    where MORTGAGE_RATE_PCT and the slider's value="…" had to be bumped by hand
    together. Requires a free FRED_API_KEY env var; on any failure (no key,
    network, parse, or an out-of-band value) falls back to MORTGAGE_RATE_PCT with
    a warning so a run never breaks on the rate alone.
    """
    if not FRED_API_KEY:
        print(f"  FRED_API_KEY unset — using fallback mortgage rate {MORTGAGE_RATE_PCT:.2f}%")
        return MORTGAGE_RATE_PCT
    import json
    url = (f"https://api.stlouisfed.org/fred/series/observations"
           f"?series_id={FRED_MORTGAGE_SERIES}&api_key={FRED_API_KEY}"
           f"&file_type=json&sort_order=desc&limit=1")
    try:
        data = json.loads(fetch_bytes(url))
        obs  = data.get("observations") or []
        raw  = obs[0]["value"] if obs else "."
        rate = float(raw)   # FRED uses "." for missing observations → ValueError
        if not (2.0 <= rate <= 15.0):
            raise ValueError(f"rate {rate} outside sane 2–15% band")
        date = obs[0].get("date", "?")
        print(f"  FRED {FRED_MORTGAGE_SERIES}: {rate:.2f}% (week of {date})")
        return round(rate, 2)
    except Exception as e:
        print(f"  WARNING: FRED mortgage-rate fetch failed ({e}) — "
              f"using fallback {MORTGAGE_RATE_PCT:.2f}%")
        return MORTGAGE_RATE_PCT


def compute_derived_affordability(all_prices: dict, rate_pct: float = MORTGAGE_RATE_PCT) -> None:
    """Recompute the price-derived affordability metrics in place so they track
    the (smoothed) Redfin price instead of remaining frozen literals.

    For each county and home type (sfh/condo) writes:
      • {type}Idx      — affordability index, affordPrice / price × 100
                         (100 = exactly affordable at median income; the UI
                         buckets <55 cost-burdened / <80 stretched / ≥80 ok)
      • {type}Gap      — income-dollar gap: extra annual income needed so the
                         household could afford the median price (0 if already
                         affordable). JS reads incomeNeeded = income + gap.
      • {type}Mortgage — monthly P&I at this price (20% down, 30-yr, rate_pct)
      • {type}PTI      — monthly P&I as a share of gross monthly income
                         (price-card diagnostic; not currently surfaced in UI)

    All four use the SAME rate the slider defaults to (MORTGAGE_RATE_PCT) so the
    static card values agree with the live calculator at first paint. Counties
    missing income or a price are skipped (their literals stay put + a warning).
    """
    print(f"\nRecomputing price-derived affordability metrics @ {rate_pct:.2f}% "
          f"(20% down, 30-yr P&I)…")
    pairs = (
        ("sfhPrice",   "sfhIdx",   "sfhGap",   "sfhMortgage",   "sfhPTI"),
        ("condoPrice", "condoIdx", "condoGap", "condoMortgage", "condoPTI"),
    )
    for key in ("State", "Honolulu", "Maui", "Hawaii", "Kauai"):
        v = all_prices.get(key)
        if not v:
            continue
        income = v.get("income")
        if not income:
            print(f"  {key:<9} skipped — no income")
            continue
        afford = _afford_price(income, rate_pct)
        for price_f, idx_f, gap_f, mort_f, pti_f in pairs:
            price = v.get(price_f)
            if not price:
                continue
            idx      = afford / price * 100.0
            mortgage = _monthly_pi(price, rate_pct)
            # incomeNeeded scales linearly with affordPrice, so the income that
            # would make `afford == price` is income × price/afford; the gap is
            # the shortfall (clamped at 0 once the home is affordable).
            income_needed = income * price / afford
            gap = max(0, int(round(income_needed - income)))
            v[idx_f]  = round(idx, 1)
            v[gap_f]  = gap
            v[mort_f] = int(round(mortgage))
            v[pti_f]  = round(mortgage / (income / 12.0), 4)
        print(f"  {key:<9} SFH idx {v.get('sfhIdx'):>5}  gap ${v.get('sfhGap'):>7,}  "
              f"P&I ${v.get('sfhMortgage'):>6,}   |  Condo idx {v.get('condoIdx'):>5}  "
              f"gap ${v.get('condoGap'):>7,}  P&I ${v.get('condoMortgage'):>6,}")

"""Housing-affordability updater package (split from redfin-price-updater.py).

Modules mirror the pipeline's data sources and stages:

    config         — every shared constant (URLs, anchors, weights, paths)
    redfin         — Redfin S3 TSV sale prices (3-mo median smoothing)
    zori           — Zillow ZORI asking rents + anchor-year averages
    census         — ACS contract rent / renter weights / bedroom rent / burden
    bls            — BLS CPI + wage series ratios, rent-CPI scaling
    nowcast        — blend / pass-through rent models, extrapolation, NTR audit
    gov            — DBEDT construction, HHFDC + HUD MFI PDFs, HUD FMR workbook
    affordability  — FRED mortgage rate, P&I math, derived idx/gap/PTI
    publish        — HTML patchers, summary table, dashboard.json snapshot

redfin-price-updater.py remains the entry point and re-exports the public
names so tests and docs keep a single import surface.
"""

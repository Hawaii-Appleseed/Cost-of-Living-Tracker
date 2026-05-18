# Housing-Affordability-Tracker — Claude rules

## Hard rules

- **Always bump `_CODE_VERSION` in `leaflet_component.py`** after any JS/CSS change. Streamlit serves stale HTML otherwise.
- **CPI projection cadence-aware damping**: monthly φ=0.92 (half-life ~8.3 months) for CPI; ACS uses φ=0.85/yr (half-life ~4.3 years). Never apply the same φ to both — they're on different sample cadences.
- **Recency-weighted geometric mean** for trend initialization, not naive linear regression. BLS rent CPI samples each unit only every 6 months — single-print noise breaks linear fits.
- **Repo-relative paths only** in commits and prompts (no `/Users/dtomkatsu/...`). Madison's workdir is `~/repos/Housing-Affordability-Tracker/` — absolute laptop paths are invisible.
- **Census forecasting must stay harmonized** with the standalone [Census-Forecaster](https://github.com/dtomkatsu/Census-Forecaster) repo. Last sync: commit `d7cbdf4`. Backtest must not regress past 6.76% MAPE.
- **Every UI change must be verified at 375px mobile width**, not just desktop. The dashboard ships to both, and prior edits have shipped clipped zone labels, overflowing pair-grid cards, and uncomfortably tight chrome because they were only checked at 1280px. Specifically: before reporting any layout/text/CSS change as done — (a) resize the preview to mobile (`preview_resize preset:mobile`), (b) screenshot or snapshot the affected section, (c) confirm no text clipping, no horizontal overflow on `<html>`, and that all badges/chips/bars fit. Use a `@media (max-width: 520px)` block to hide or shorten anything that doesn't fit. Existing breakpoints worth respecting: `≤520px` (phones), `≤640px` (header + KPI strip reflow), `≤750px` (PTI panels collapse to one column).

## Methodology source of truth

- `METHODOLOGY.md` (top level) — overall approach, half-life table.
- `census_forecasting/METHODOLOGY.md` — projection math.
- §2.3.1 covers recency-weighted init; cross-link with the Hawaii Grocery Price Tracker store-share weighting.

## Stack expectations

- Python (pandas, scipy), Streamlit, Leaflet via `leaflet_component.py`.
- Data: ACS 5-year, BLS CPI Honolulu, RPAD assessor extract, FRED rent series.
- Hosting: Streamlit Cloud + GitHub Pages mirror.

## Commit hygiene

- Tests must pass (185/185 currently). Run `pytest census_forecasting/` before committing methodology changes.
- Update `METHODOLOGY.md` sections affected by any parameter / formula change.

## Companion docs (in vault)

- `~/.openclaw/workspace/projects/Housing-Affordability-Tracker.md` — full project context.
- `~/.openclaw/workspace/tasks/Housing-Affordability-Tracker.md` — active worklist.

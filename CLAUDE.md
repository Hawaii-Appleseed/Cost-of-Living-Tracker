# Cost-of-Living-Tracker — Claude rules

## What this repo actually is

A **static, self-contained HTML dashboard** (no build step, no framework) plus
Python updaters that patch data into the HTML monthly via GitHub Actions.
There is no Streamlit app and no Leaflet map here — don't look for them.

- `index.html` and `squarespace-single-file.html` must stay **byte-identical**
  (CI enforces it). Edit `index.html`, then `cp index.html
  squarespace-single-file.html`. Every updater patches both.
- Updaters rewrite tagged blocks (`/* X_DATA_START */ … /* X_DATA_END */`)
  through `ha_common/html_patcher.py`; `redfin-price-updater.py` also writes
  the `data/dashboard.json` snapshot that `scripts/check_freshness.py` gates on.

## Hard rules

- **CPI projection cadence-aware damping**: monthly φ=0.92 (half-life ~8.3
  months) for CPI; ACS uses φ=0.85/yr (half-life ~4.3 years). Never apply the
  same φ to both — they're on different sample cadences.
- **Recency-weighted geometric mean** for trend initialization, not naive
  linear regression. BLS rent CPI samples each unit only every 6 months —
  single-print noise breaks linear fits.
- **Repo-relative paths only** in commits and prompts (no `/Users/dtomkatsu/...`).
  Madison's workdir is `~/repos/Cost-of-Living-Tracker/` — absolute
  laptop paths are invisible.
- **Census forecasting must stay harmonized** with the standalone
  [Census-Forecaster](https://github.com/Hawaii-Appleseed/Census-Forecaster) repo.
  The commit pinned in `requirements.txt` is the synced version — bump both
  pins together. Backtest must not regress past 6.76% MAPE.
- **Every UI change must be verified at 375px mobile width**, not just
  desktop. Prior edits have shipped clipped zone labels, overflowing pair-grid
  cards, and uncomfortably tight chrome because they were only checked at
  1280px. Before reporting any layout/text/CSS change as done: render the page
  at a 375px-wide viewport (headless Chromium is available), screenshot or
  snapshot the affected section, confirm no text clipping, no horizontal
  overflow on `<html>`, and that all badges/chips/bars fit. Use a
  `@media (max-width: 520px)` block to hide or shorten anything that doesn't
  fit. Existing breakpoints worth respecting: `≤520px` (phones), `≤640px`
  (header + KPI strip reflow), `≤750px` (PTI panels collapse to one column).

## Methodology source of truth

- `METHODOLOGY.md` (top level) — overall approach, half-life table.
- `census_forecasting/METHODOLOGY.md` — projection math.
- §2.3.1 covers recency-weighted init; cross-link with the Hawaii Grocery
  Price Tracker store-share weighting.
- `docs/how-it-works.md` — plain-language explainer; keep it in sync when
  sources or cadences change.

## Stack expectations

- Python (pandas), self-contained HTML/CSS/JS dashboard, Chart.js via CDN.
- Data: Redfin, Zillow ZORI, ACS 5-year, BLS CPI Honolulu, HUD FMR,
  HHFDC/HUD MFI, DBEDT, FRED, AAA gas, USDA TFP.
- Hosting: GitHub Pages + Squarespace embed (paste of the mirror file).
- Automation: `.github/workflows/monthly-update.yml` (day 22, commits data),
  `tests.yml` (pytest + mirror check on push/PR).

## Commit hygiene

- Tests must pass: run `python -m pytest` (repo root) before committing.
  CI runs the suite before any updater patches the HTML.
- `python scripts/check_freshness.py` must stay green — it gates the monthly
  publish (snapshot liveness, per-metric budgets, HTML data blocks).
- Update `METHODOLOGY.md` sections affected by any parameter / formula change.

## Companion docs (in vault)

- `~/.openclaw/workspace/projects/Cost-of-Living-Tracker.md` — full project context.
- `~/.openclaw/workspace/tasks/Cost-of-Living-Tracker.md` — active worklist.

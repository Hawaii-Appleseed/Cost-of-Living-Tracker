# Housing Affordability Tracker

A dashboard of Hawaiʻi housing affordability metrics across the four counties,
refreshed automatically every month from public data sources.

> 📖 **New here?** [**How it works (plain language)**](docs/how-it-works.md) explains where every number comes from and how fresh it is — no jargon. For the precise formulas, see [METHODOLOGY.md](METHODOLOGY.md).

## How it's built

The dashboard is a **single self-contained HTML file** — all CSS, JavaScript,
and data are inlined, with no build step and no runtime data fetches. The only
external dependencies are Google Fonts and the Chart.js CDN.

- `index.html` — the dashboard (GitHub Pages / local viewing).
- `squarespace-single-file.html` — byte-identical mirror of `index.html`,
  kept for pasting into a Squarespace Code Block. **Never edit one file
  without the other** — CI fails if they diverge. Edit `index.html`, then
  `cp index.html squarespace-single-file.html`.
- `squarespace-census-block.html` — optional companion block for Squarespace
  that live-refreshes income/rent from the Census API in the visitor's
  browser (bring your own key).

Data is injected by Python updaters that rewrite tagged blocks
(`/* CPI_DATA_START */ … /* CPI_DATA_END */`) in **both** HTML files via
`ha_common/html_patcher.py`:

| Updater | Source(s) | Feeds |
|---|---|---|
| `redfin-price-updater.py` | Redfin, Zillow ZORI, Census ACS, BLS rent CPI, HUD FMR, HHFDC/HUD MFI, DBEDT, FRED | prices, rents, income, affordability + `data/dashboard.json` snapshot |
| `bls-cpi-updater.py` | BLS Honolulu CPI | inflation chip + card badges |
| `grocery-price-updater.py` + `pipelines/grocery/` | store price baseline, CPI-adjusted | grocery cards |
| `gas-price-updater.py` | AAA daily averages | gas cards + `data/gas_prices_history.csv` |
| `tfp-updater.py` | USDA Thrifty Food Plan | groceries headline anchor |

## Automation

`.github/workflows/monthly-update.yml` runs on day 22 of each month (after
Redfin's third-Friday release): installs deps, runs the test suite, runs every
updater, gates on `scripts/check_freshness.py` (fails CI rather than publish
stale numbers) and on the two HTML files being byte-identical, then commits
and pushes. On failure it files a tracking issue. `tests.yml` runs the suite
plus the mirror check on pushes and PRs.

## Metrics tracked

- Median resale prices (SFH / condo, 3-mo median smoothed)
- Median family income; monthly P&I payment; payment-to-income share
- Blended rent nowcast per county + bedroom-level rents
- Cost-burden shares (renter and owner households)
- Grocery basket, gas prices, CPI inflation, USDA TFP food costs

## Local development

```bash
PIP_CONSTRAINT=build-constraints.txt pip install -r requirements.txt pytest
python -m pytest                   # test suite
python scripts/check_freshness.py  # staleness gate
open index.html                    # no server needed
```

The `PIP_CONSTRAINT` pin (hatchling < 1.26) is needed until an upstream
Census-Forecaster packaging fix lands — see `build-constraints.txt`. API keys
(`BLS_API_KEY`, `CENSUS_API_KEY`, `FRED_API_KEY`) are read from the
environment by the updaters, which degrade gracefully without them except
where noted in each script.

## Customization

The palette is declared as CSS custom properties at the top of `index.html`'s
inline `<style>`. Override the `:root` tokens to retheme:

| Token              | Default     | Role                                  |
|--------------------|-------------|---------------------------------------|
| `--ocean-700`      | `#0b5566`   | Primary chrome, header background     |
| `--ocean-500`      | `#1a8496`   | Secondary chrome, links               |
| `--seafoam-700`    | `#1e8a73`   | Brand accent, "affordable" semantic   |
| `--seafoam-500`    | `#3fc4a0`   | Bar fills, success highlights         |
| `--coral-500`      | `#c94f3a`   | "Cost-burdened" / warning             |
| `--coral-300`      | `#e08a5b`   | Moderate / stretched                  |
| `--gold-500`       | `#c08a1f`   | HOA disclaimer accent (legacy only)   |

## License

Free to use and modify for personal and commercial projects.

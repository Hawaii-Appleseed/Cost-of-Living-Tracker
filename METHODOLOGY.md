# Methodology

This document records the data-transformation choices that aren't self-evident
from the code — CPI series picks, forward-projection rules, rent-anchor
vintage, and the annual re-anchoring cadence. When a BLS release lags or a
fresh ACS vintage drops, this is the file to read before touching numbers.

## Data sources (authoritative)

| Domain | Source | Series / table | Cadence | Script |
|---|---|---|---|---|
| SFH & condo medians | Redfin Data Center (public S3) | `state_market_tracker.tsv000.gz`, `county_market_tracker.tsv000.gz` | monthly, 3rd-Friday release | `redfin-price-updater.py` |
| Contract rent (existing leases) | Census ACS 5-yr | `B25058_001E` | annual, December release | `redfin-price-updater.py` |
| Rent CPI (existing tenants) | BLS Honolulu MSA | `CUURS49ASEHA` | bimonthly (even months), NSA | `redfin-price-updater.py` |
| Asking rent | Zillow ZORI | `County_zori_uc_sfrcondomfr_sm_month.csv` | monthly | `redfin-price-updater.py` |
| HUD income limits | HHFDC county PDFs + HUD state PDF | FY 2025 MFI | annual | `redfin-price-updater.py` |
| Construction authorizations | DBEDT QSER | Table E-8 | annual (from quarterly data) | `redfin-price-updater.py` |
| All-items CPI (headline chip) | BLS Honolulu | `CUURS49ASA0` | bimonthly | `bls-cpi-updater.py` |
| Shelter / food / gasoline / transport CPI | BLS Honolulu | `CUURS49ASAH`, `CUURS49ASAF11`, `CUURS49ASETB01`, `CUURS49ASAT` | bimonthly | `bls-cpi-updater.py` |
| Thrifty Food Plan | USDA CNPP | Alaska-Hawaii monthly report | monthly | `tfp-updater.py` |
| Gas prices | AAA Hawaii | statewide average | daily | `gas-price-updater.py` |
| Grocery basket | In-house scrape, CPI-adjusted | `pipelines/grocery/` | ad-hoc + monthly CPI roll | `grocery-price-updater.py` |
| Typical-household FAH spending (side-stat) | BLS CE PUMD interview survey | Honolulu PSU `S49A`–`S49D`, FINLWT21-weighted, 5y pool | annual, target October | `pipelines/grocery/scripts/refresh_ce_pumd.py` |

The `CUURS49A*` prefix is **Honolulu Urban Hawaii, not seasonally adjusted**.
There is no neighbor-island CPI — every CPI adjustment applied to Maui,
Hawaii County, or Kauai uses the Honolulu ratio as a directional proxy.

The grocery pipeline's `cpi_series.json` still uses the **legacy area-426
codes** (`CUUSA426SAF11`, etc.). BLS continues to publish both the legacy
A426 series and the post-2018 S49A series in parallel; treat them as
equivalent for nowcast purposes. If BLS ever sunsets one of the prefixes,
mirror the other before re-running the pipeline.

---

## CPI release cadence (Honolulu, area S49A)

Every Honolulu CPI series consumed here is **bimonthly**, not monthly.

* **Data periods**: odd months only — Jan, Mar, May, Jul, Sep, Nov.
  There are no Feb / Apr / Jun / Aug / Oct / Dec observations.
* **Release**: each odd-month data point is published on or near the **15th
  of the following even month**. So Mar-2026 data lands ~Apr-15, 2026.
* **YoY**: same odd-month one year prior is always available, so
  `compute_yoy` in `bls-cpi-updater.py` doesn't need interpolation.

Two practical consequences for the pipeline:

1. `pipelines/grocery/src/cpi_fetcher.py :: expected_latest_period()` keys
   off the odd-month set (`BLS_DATA_MONTHS = {1,3,5,7,9,11}`). A previous
   bug had this set to even months, which made the cache check ask BLS for
   data points it never publishes — every run silently re-fetched.
2. When the dashboard's reference month is even (e.g. April), every
   downstream metric that depends on Honolulu CPI (groceries, TFP, BLS rent
   nowcast) is **always at least one month past the latest observation**.
   This is the case the projection / interpolation logic in
   `price_adjuster.py` and `tfp-updater.py` exists to handle — see the
   forward-projection rule below for the math and the per-month cap.

---

## Rent-anchor year

**Single source of truth**: `RENT_ANCHOR_YEAR` constant at the top of
`redfin-price-updater.py`. Everything downstream — the Census ACS endpoint URL
and the BLS base-year average — derives from it.

We fetch the Honolulu (and every other county's) ACS anchor dollar value
**live** from the Census API each run, so the dollar value cannot drift out
of sync with the anchor year. No hardcoded dollar figures live in the repo.

### Anchor vintage: ACS 1-year, not 5-year (Q-audit item 2)

The contract-rent anchor (table **B25058**) uses the ACS **1-year** estimate
for all five geographies (`COUNTY_ANCHOR_OVERRIDE`), with the 5-year only as a
per-geography fallback when a 1-year cell is suppressed. Reason: the 5-year
estimate pools 2020–2024, so its "level" is centred around ~2022 — but the
nowcast multiplies the anchor by a *2024→present* growth factor, which would
silently omit ~2 years of rent growth. The 1-year 2024 level is a true 2024
level, consistent with the calendar-2024 BLS base-year average and ZORI anchor
average the growth factors are built on. (All HI counties and the State exceed
the 65k-population threshold the 1-year requires.)

The **bedroom-rent tiles** (B25031) and **cost-burden distributions**
(B25070/B25091) intentionally stay on the 5-year — they hit small-cell
suppression on thin neighbor-island samples that the 5-year smooths over.

### Re-anchoring cadence (and backtest re-validation — item 5)

Update `RENT_ANCHOR_YEAR` **once per year, in December or January**, when
the new ACS vintage is published. Steps:

1. Bump the constant:
   ```python
   RENT_ANCHOR_YEAR = "2025"   # or whatever the new vintage is
   ```
2. Do a dry-run: `python3 redfin-price-updater.py --dry-run` and confirm the
   printed "anchor ACS {year} $X,XXX" lines reflect the new vintage.
3. Sanity-check the four counties: moving from vintage N to N+1 should shift
   each county's anchor by a small single-digit %. A 20%+ jump means Census
   hasn't published the new vintage yet, or you're hitting a cached URL.
4. **Re-run the backtest gate** so the model parameters stay validated against
   the new ground truth:
   `CENSUS_API_KEY=… python3 scripts/backtest_rent_nowcast.py`. Confirm the
   pass-through λ and the convex-blend weights are still within the noise floor
   of the optimum, and that the chosen method still beats the alternative inside
   the 8% MAPE budget. Update `RENT_PASSTHROUGH_LAMBDA` / `RENT_PRODUCTION_METHOD`
   if the verdict moves. (Kauaʻi weights stay provisional until it has ≥2 years
   of ZORI history, ≈2027.)
5. **Chain-link the level jump.** Re-anchoring shifts the absolute level by a
   step (the new vintage is a fresher, higher base). For one cycle, note the
   old-anchor and new-anchor rents in the commit message so the December
   discontinuity is visible and reviewable rather than a silent jump.
6. Run end-to-end and verify the dashboard's rent figures move sanely; the
   freshness check (`scripts/check_freshness.py`) must pass.

**Why re-anchor at all?** The BLS Honolulu rent CPI is an *index*, not a
dollar value — it only tells us "rent today is X% of rent in 1982-84." To
convert that into dollars we multiply by an ACS dollar anchor. The ratio
`BLS(now) / BLS(anchor_year_avg)` compounds any indexing error in proportion
to how far "now" is from "anchor_year". Re-anchoring annually keeps the
extrapolation window short and the absolute-dollar reading tight to the
most recent hard Census observation.

### Why the anchor year is duplicated in two constants

`CENSUS_ACS_YEAR` and `BLS_BASE_YEAR` both equal `RENT_ANCHOR_YEAR` today —
that's intentional and required: the index-to-dollar conversion is only
valid when the ACS dollar year and the BLS base-average year are the same.
The two named constants exist so the intent reads clearly at each use site.
**Never set them to different years** without fully re-deriving the scaling.

---

## Rent nowcast model

The published `rent` is the ACS 1-year anchor carried forward to the current
month. Three structural properties (Q-audit items 3, 4, 7):

### 1. One target month for every leg (item 3)

The two monthly signals end on different months — BLS Honolulu rent CPI is
bimonthly, ZORI is monthly — and HUD FMR is annual. Mixing growth-to-different-
endpoints understates or overstates the blend. We pick a single
`target_month = max(latest BLS-rent month, latest ZORI month)` and bring each
leg to it: the lagging leg is extrapolated with the project's canonical
damped-trend machinery (`smoothed_monthly_rate → clip ±PROJ_MONTHLY_CAP →
damped_compound_factor`, the same code the grocery/TFP side uses — imported from
`census_forecaster.bls.projection`). The published `rentAsOf` per county is this
single target month.

### 2. Pass-through model, not a convex blend (item 4)

A convex blend `w·cpi + (1−w)·zori` can never leave the interval between its
legs. When BOTH proxies undershoot realized growth — the Big Island 2022→24
case (ACS +31% vs CPI +10%, ZORI +16%) — no weighting can reach the target. We
instead use a **log-space pass-through**:

```
rent = anchor · cpi_factor^(1−λ) · zori_factor^λ
```

λ is the lease-turnover pass-through completeness. λ=0 → pure CPI; λ=1 → fully
caught up to asking; **λ>1 → overshoot**, projecting continued catch-up toward
accumulated asking-rent growth even after asking flattens — which is how the
model exceeds both contemporaneous legs.

λ is calibrated by `scripts/backtest_rent_nowcast.py` against ACS 1-year ground
truth and promoted to production (`RENT_PRODUCTION_METHOD = "passthrough"`) only
when it beats the convex blend within the 8% MAPE budget. **2026-06-11 run:**
outer-island pooled MAPE 5.59% at λ=0.65 (vs blend 5.64%); Big Island error
7.83%→6.42%. Both models are always computed; the constant selects what ships,
and each county records the method used in `rentMethod`.

### 3. State = renter-weighted aggregate (item 7)

The statewide rent is **not** an independent blend. It is the renter-household-
weighted average of the four county nowcasts, with weights from ACS **B25003**
(renter-occupied counts, fetched per run) — so the State figure reconciles with
its counties by construction, and the weights apply to a renter quantity (the
old hardcoded total-population weights over-counted low-renter-share islands).

### Display precision (item 8)

Rents are rounded to the nearest **$25**. The backtest noise floor (ACS 1-yr MoE
±5–9% on the neighbor islands) is far wider than $1, so dollar-precise display
would imply false confidence. The exact method used each month is written to
`rentMethod` and surfaced in the dashboard's data-freshness tooltip.

---

## Forward-projection rule (groceries)

### Why we project

The grocery pipeline CPI-adjusts baseline prices each month via Honolulu
bimonthly BLS series (food-at-home, dairy, meat-poultry-fish-eggs, etc.).
When the dashboard's target month falls **past the latest observed
bimonthly period** — e.g. target April, latest release February — there are
only two honest choices: refuse to update the card, or extrapolate with an
explicit flag.

The previous implementation silently took "no change since last
observation," which hid a flat-line assumption from the reader. We now
extrapolate **linearly** (in log space) and surface a `proj.` tag on the
card so the user knows.

### How it works

`pipelines/grocery/src/price_adjuster.py :: compute_cpi_ratio()` returns a
dict with `method ∈ {exact, interpolated, projected, unavailable}`. The
projection path computes a **recency-weighted smoothed monthly rate**
across the last few bimonthly observations, then applies **Gardner-McKenzie
damped-trend** compounding so the slope decays as the forecast horizon
grows. With exactly two points the smoothed rate collapses to the original
single-pair rate — a deliberate back-compat path — and with three or more
points the prior trend dilutes a single noisy bimonthly spike:

```
# (1) Pairwise compound rates from each adjacent pair
rates_i  = (p_i.value / p_{i-1}.value) ** (1 / months_i) - 1

# (2) Most recent pair gets weight 1.0; each step back halves it
weight_i = 0.5 ** ((n-1) - i)

# (3) Recency-weighted geometric mean
monthly_rate = Σ(rate_i * weight_i) / Σ(weight_i)

# (4) Cap and damp the projection slope each month forward
monthly_rate  = clamp(monthly_rate, ±0.0189)              # ≈ ±25%/yr cap
projected_idx = latest * Π_{h=1..H} (1 + monthly_rate * φ^(h-1))
                where φ = 0.92  (damping factor)
```

The **±0.0189/month cap** stops a single noisy bimonthly print from
compounding into an unrealistic three-month extrapolation. Concretely:

```
(1 + 0.0189) ** 12 ≈ 1.252   →   +25.2 %/yr ceiling
(1 − 0.0189) ** 12 ≈ 0.795   →   −20.5 %/yr floor
```

The **damping factor φ = 0.92** is from Gardner & McKenzie (1985) and is
the standard default in Holt damped-trend (`ets(damped=TRUE)` in R, the
`Holt(damped_trend=True)` initializer in `statsmodels`). It bounds the
open-ended risk of any positive trend compounding forever — by month 6
only ~61% of the latest momentum is applied; by month 12, ~37%. Hyndman &
Athanasopoulos (2018) and Cleveland Fed WP 24-06 both report damped trends
out-of-sample-beat undamped ones for short-horizon noisy macro series. For
the typical 1–2-month projection horizon in this repo the damping effect
is small (~1–2% on a 1%-per-month trend) but it eliminates a tail risk on
the rare runs where reference-month is 4+ months past the latest BLS print.

The same smoothing + cap + damping is applied in
`tfp-updater.py :: _cpi_value_for()` when the reference month is past the
latest BLS Honolulu food-CPI observation — keeps every CPI-driven projection
in this repo on the same momentum ceiling.

**Cross-module note.** The `census_forecasting/` package uses the same
Gardner-McKenzie damping discipline on its own cadence — φ=0.85 *per
year* there, vs φ=0.92 *per month* here. Trend half-lives (~8.3 months
for CPI, ~4.3 years for ACS) reflect each source's signal-to-noise. The
recency-weighted pairwise-rate smoother described above is also used to
initialize the damped-trend fit in census forecasting; see
`census_forecasting/METHODOLOGY.md` §2.3 and §2.3.1.

### What we do *not* use, and why

**Machine learning (LSTM, XGBoost, Random Forest)** for projecting Honolulu
CPI bimonthlies past the latest print: too little training data. The
Honolulu S49A series only goes back to ~2018 (CPI area-code restructuring
released the modern S49A codes that year), giving ~50 bimonthly
observations per series. Recent literature (e.g. *Modeling inflation with
machine learning: a cross-horizon systematic review*, IJDSA 2025) finds
LSTMs underperform AR/SARIMA and ridge on small-sample inflation data,
overfitting noise without a meaningful gain at short horizons. Tree
ensembles (RF, XGBoost) fare better but require multivariate features
(national CPI, oil futures, gas prices) that we already incorporate
upstream of the projection — adding the same signals back through a model
would double-count them. The `±0.0189/month` cap, recency-weighted slope,
and 0.92 damping together approximate a damped-Holt point forecast, which
the academic consensus says is the right baseline class for this kind of
short-horizon, small-sample series.

**Seasonal adjustment (X-13ARIMA-SEATS)** before projecting: the BLS
Honolulu S49A series we consume are NSA (not seasonally adjusted), but the
projection horizon is at most ~3 months and the YoY chip on the dashboard
already implicitly absorbs seasonality (same calendar month, year-over-year).
A seasonal decomposition would need ≥3 years of clean data; with only ~50
points the seasonal factor estimate is noisier than the noise it removes.

### How it surfaces in the UI

`scripts/update_prices.py` writes `data/output/cpi_status.json` — a small
sidecar containing `is_projected`, `latest_actual_period`, and per-category
method. `grocery-price-updater.py` reads that sidecar and writes
`projected: true`/`originalPeriod: "YYYY-MM"` into each county's
`groceryData` block. The HTML's as-of popover formatter
(`fmtPeriodText`) then renders an amber "proj." pill on the grocery row,
using the same period-tag style already used by the USDA TFP card.

If the sidecar is missing (older pipeline run), the updater treats the
state as "not projected" — graceful degradation.

---

## Realized housing burden (ACS B25071 / B25092 + BLS nowcast)

The "How much of income goes to {mortgage|rent}?" chart uses *realized*
burden metrics — what current renters and owners actually pay as a
share of *their own* income — rather than synthetic ratios built from
aggregate price ÷ aggregate income (which mismatch the household whose
rent is in the numerator with the household whose income is in the
denominator).

### Source tables (anchor)

| ACS table | What it measures | Used for |
|---|---|---|
| **B25071_001E** | Median Gross Rent As Percentage of Income (GRAPI) | Renter-side `tenantRentPTI` |
| **B25092_002E** | Median Selected Monthly Owner Costs As Percentage of Income (SMOCAPI), owners with mortgage | Owner-side `mortgageOwnerPTI` |
| **B25070** | Gross rent / income distribution, renters | `rentBurdenedPct` (≥30%), `rentSeverelyBurdenedPct` (≥50%) |
| **B25091** | Mortgage status × SMOCAPI distribution, owners-with-mortgage rows | `ownerBurdenedPct`, `ownerSeverelyBurdenedPct` |

Both medians (B25071 / B25092) are computed by Census directly from the
underlying microdata — each household's rent (or owner cost) is paired
with that same household's income, then the median is taken of the
resulting ratios. Computing this externally as
`median(rent) / median(income)` produces a different number because
renters and owners differ in income distribution; we use the Census-published medians.

Cost-burden shares are derived by collapsing the 30-34.9 / 35-39.9 /
40-49.9 / ≥50 buckets into "≥30%" and the ≥50 bucket into "severely
burdened", excluding the "not computed" pool from the denominator.

### Nowcasting the anchor to the current period

The ACS 5-year vintage is centered roughly 2.5 years behind today. To
bring the realized burden up to the current dashboard period we apply
a BLS-driven nowcast factor on the numerator and denominator:

```
rent_factor   = CPI_rent_HNL(latest)         / CPI_rent_HNL(anchor_year_avg)
cost_factor   = CPI_all_HNL(latest)          / CPI_all_HNL(anchor_year_avg)
income_factor = wage_HI(trailing-12mo mean)  / wage_HI(anchor_year_avg)

tenantRentPTI    = B25071 × (rent_factor / income_factor)
mortgageOwnerPTI = B25092 × (cost_factor / income_factor)
```

**Income factor uses a trailing-12-month wage mean (Q-audit item 6).** The CES
wage series is *not seasonally adjusted*, so a single latest month carries
bonus/seasonal noise that would move every county's burden in lockstep (the same
factor divides both PTIs). Averaging a full year removes that at the cost of ~6
months of extra lag — acceptable for a slow-moving denominator. The numerator
month still differs by series; the UI label tracks the wage series. (A better
concept is BEA quarterly state personal income — multiple earners, transfers,
retirees — but it is a heavier integration; the CES proxy assumes household
income tracks per-worker private earnings.)

| Series | Code | Role |
|---|---|---|
| Honolulu CPI, rent of primary residence | `CUURS49ASEHA` | Rent-burden numerator |
| Honolulu CPI, all items | `CUURS49ASA0` | Owner-burden numerator proxy — locked-in mortgage P&I + slow-growing tax / insurance / utilities ≈ general CPI |
| Hawaiʻi state private avg weekly earnings (NSA) | `SMU15000000500000011` | Income denominator (both sides), trailing-12mo mean |

Factors are statewide and applied uniformly across all five geographies —
BLS does not publish county-level CPI or wages for Hawaiʻi, and statewide
is the finest Hawaiʻi-specific series available.

**Why the burden numerator uses CPI-rent only, not the blended nowcast.**
The displayed tenant *rent dollars* (`rent`) grow by the blended CPI/ZORI(/FMR)
factor, but the rent-*burden* numerator (`tenantRentPTI`) grows the ACS GRAPI
anchor by the CPI-rent factor alone. This is deliberate: GRAPI measures what
*existing* tenants pay, and the Honolulu rent CPI (`CUURS49ASEHA`, rent of
primary residence) is the matching existing-tenant deflator. ZORI and FMR
describe *new-lease / asking* rent, which is the right signal for a forward
nowcast of market rent but overstates what sitting tenants actually pay. So the
two figures can diverge — the headline rent dollars run hotter than the burden
when asking rent leads — and that gap is expected, not a bug.

Cost-burden shares (B25070 / B25091) are **not** nowcasted — they're
distributional and move slowly. The UI tags them with the ACS 5-year
period so users know they're anchor-vintage figures.

Damping convention (per the project-wide rule): monthly damping
φ = 0.92 (half-life ~8.3 months) applies only when extrapolating past
the latest BLS print. As long as BLS publishes through the current
month, the multiplier is used live with no damping.

### Failure modes

- `CENSUS_API_KEY` missing → entire burden anchor fetch silently skipped;
  the dashboard renders last-known values from the prior monthly commit.
  CI must set the secret for monthly refreshes (free key, no approval).
- BLS series unavailable for the required anchor year → nowcast skipped;
  raw ACS anchor values are written without forward correction.
- Single county returns Census sentinel (-666666666) → that county's
  field stays at the prior value rather than overwriting with a
  meaningless number.

## Home sale prices: trailing-median smoothing + derived affordability

### 3-month trailing median (sale prices)

Redfin reports the **median sale price of whatever closed that month**, and the
neighbor-island submarkets transact in tiny volumes — roughly 27 single-family
sales/month on Kauaʻi and ~33 condo sales/month on Hawaiʻi Island. At those
counts a single luxury batch closing in one month moves the headline median
±15–20%. The April Kauaʻi SFH print, for example, sat ~19% above its own
3-month mean.

`extract_hawaii_prices()` therefore reports the **median of the most recent
three monthly prints** per (county, property type) rather than the single latest
month. Median (not mean) so one $5M outlier sale cannot drag the figure; a
3-month window so the signal still moves within a quarter. This mirrors the
trailing-mean treatment ZORI already gets in `fetch_zori_asking_rents()`. Deep
markets are barely affected (Honolulu SFH/condo moved 0.0%); the thin ones are
where it matters (latest live run: Kauaʻi SFH −12.5%, Hawaiʻi SFH −8.7%).

Redfin market-tracker files are monthly (`PERIOD_DURATION == 30`), so each
(region, type, month) is one row; the smoother still pins to the latest row's
cadence defensively in case Redfin ever mixes durations into one export.

### Derived affordability metrics (recomputed each run)

The per-county `sfhIdx` / `sfhGap` / `sfhMortgage` / `sfhPTI` fields (and condo
equivalents) are **recomputed every run** by `compute_derived_affordability()`
so they track the freshly smoothed price + current income. They were previously
frozen literals that drifted out of sync — e.g. Kauaʻi's stored monthly P&I read
$5,393 against a $1.5M home (true P&I ≈ $6,700) and its condo "gap" implied
$96k of extra income was needed for a $757k condo at a $133k income, both
artifacts of stale numbers no longer matching the price beside them.

All four reproduce the dashboard JS exactly (`calcAffordPrice()` / `mcardV2()`),
at the **same rate the rate-slider defaults to** so the static card values agree
with the live calculator on first paint:

- **Assumptions:** 30-yr fixed, 20% down (LTV 0.80), 30% of gross income to
  P&I, mortgage rate = `MORTGAGE_RATE_PCT` (current Freddie Mac PMMS, 6.38%).
  `MORTGAGE_RATE_PCT` **must stay in sync with the HTML `rate-slider` default**
  — bump both together when the PMMS rate is refreshed.
- **`{type}Idx`** = affordPrice ÷ price × 100 (100 = exactly affordable at
  median income; UI buckets <55 cost-burdened / <80 stretched / ≥80 ok).
- **`{type}Gap`** = income-dollar shortfall — extra annual income needed so the
  household could afford the median price (clamped at 0 once affordable). The JS
  reads `incomeNeeded = income + gap`.
- **`{type}Mortgage`** = monthly P&I at the median price.
- **`{type}PTI`** = monthly P&I as a share of gross monthly income. This is a
  price-card diagnostic and is **not currently surfaced in the UI** (the visible
  PTI bars use the ACS-derived `tenantRentPTI` / `mortgageOwnerPTI`); it is
  recomputed for internal consistency rather than display.

## Rent nowcast blend (per-county BLS CPI / ZORI weights)

The BLS Honolulu rent CPI lags market asking rent by roughly 12 months — it
samples each unit once every six months and averages continuing leases
alongside new ones. Zillow ZORI is an asking-rent index that leads CPI but
overreacts to turnover. There is only **one** BLS rent series for Hawaiʻi
(Honolulu MSA, `CUURS49ASEHA`), so the CPI growth leg is identical for every
county — the ZORI leg is the only county-specific growth signal.

We blend the legs, anchored to the same ACS dollar base. Most counties use a
2-leg CPI/ZORI blend; Hawaiʻi and Kauaʻi add a third county-specific HUD Fair
Market Rent (FMR) leg (see below):

```
2-leg:  blended_rent = ACS_anchor × ( w_cpi · BLS_ratio + w_zori · ZORI_ratio )
3-leg:  blended_rent = ACS_anchor × ( w_cpi · BLS_ratio + w_zori · ZORI_ratio + w_fmr · FMR_ratio )
```

where each ratio is `latest value / anchor_year_average` (BLS & ZORI use a
3-month trailing mean; FMR is the annual 2-BR fiscal-year value) and the weights
are **per-county** (`BLENDED_RENT_CPI_WEIGHTS` and, for the 3-leg counties,
`BLENDED_RENT_3LEG_WEIGHTS` in `redfin-price-updater.py`):

| County | CPI | ZORI | FMR | Rationale |
|---|---|---|---|---|
| Honolulu | 0.70 | 0.30 | — | CPI is the literal Honolulu series — regionally representative |
| State | 0.70 | 0.30 | — | Honolulu-dominated population |
| Maui | 0.50 | 0.50 | — | ZORI is the only county-specific source; best-validated outer island |
| Hawaiʻi | 0.34 | 0.33 | 0.33 | CPI/ZORI both undershot the Big-Island divergence; FMR captures it (see below) |
| Kauaʻi | 0.40 | 0.40 | 0.20 | ZORI is statewide-proxy only; FMR is Kauaʻi's first real local leg (modest weight — see below) |

**Smoothing (Q1).** Both legs use a 3-month trailing mean of their latest
prints (`BLS_RENT_SMOOTHING_WINDOW = ZORI_SMOOTHING_WINDOW = 3`) so a single
bumpy CPI or ZORI print doesn't swing the headline rent. The ACS anchor and
both anchor-year averages stay full-year means.

**Maui post-fire re-anchor (M2).** Maui's ACS anchor uses the **ACS 1-year**
2024 vintage (`COUNTY_ANCHOR_OVERRIDE = {"Maui": "acs1"}`) instead of the 5-year.
The 2023 Lahaina fire produced a single-year rent shock that the 5-year vintage
dilutes by averaging it with pre-fire years (1-yr $1,802 vs 5-yr $1,717). ACS
1-yr publishes only for ≥65k-population areas; all four counties qualify, but
only Maui is overridden today. A suppressed or failed 1-yr fetch reverts to the
5-yr value with a logged warning.

See Cleveland Fed WP 22-38r ("New-Tenant Repeat Rent Inflation") for the
academic basis of blending a lagging stock-rent index with a leading
asking-rent index.

### County-specific HUD FMR leg — Hawaiʻi & Kauaʻi only (targeted)

The 2-leg blend has only **one** county-specific signal (ZORI); the CPI leg is
Honolulu-only and applied identically to every island. That fails wherever a
neighbor island's rent path diverges from Honolulu. The M4 backtest exposed two
such cases, so each gets a third leg drawn from **HUD Fair Market Rent** (the
40th-percentile 2-bedroom gross rent, published annually per county). We use
only its fiscal-year **growth ratio** (`FMR(latest FY) / FMR(anchor FY)`), never
its dollar level. The leg is **targeted** — added only where the backtest shows
it helps, to keep surface area minimal:

- **Hawaiʻi (CPI 0.34 / ZORI 0.33 / FMR 0.33).** Realized Big-Island rent rose
  +27% (ACS 2021→24), outrunning *both* Honolulu CPI (+15%) and ZORI (+16%);
  only HUD FMR (+37%) captured it, cutting Hawaiʻi's backtest MAPE 9.21% → ~4.8%.
  Because the CPI leg cannot diverge from Honolulu, FMR is the Big Island's only
  means of tracking its own trajectory — in *either* direction. (Going forward,
  FY2024→FY2026 FMR is roughly flat, so the leg now gently restrains the nowcast
  rather than boosting it — the post-surge plateau Honolulu CPI would miss.)
- **Kauaʻi (CPI 0.40 / ZORI 0.40 / FMR 0.20).** Kauaʻi has no ZORI history (its
  ZORI leg is the statewide proxy), so FMR is its **first genuinely
  county-specific signal**. CAVEAT: FMR slightly *worsens* Kauaʻi's measured
  MAPE in the backtest (status-quo CPI/proxy-ZORI 4.00% vs CPI/FMR 5.74%),
  because Kauaʻi's realized growth was modest (+14%) while FMR overshot (+25%).
  FMR is therefore added at a deliberately **modest 0.20 weight** — for
  robustness (a real local leg instead of an all-proxy blend), not measured
  accuracy. Keep its weight small and re-validate annually.

Maui (ZORI is the better county signal there) and Honolulu/State keep their
2-leg blend. **Caveats:** FMR is ACS-derived and lags the market ~2 years, so
its FY label trails the period it actually describes; it is a slow,
partly-ACS-correlated check, weighted accordingly and never as the majority leg.
Engineering notes: HUD bot-blocks default User-Agents (we send a browser UA) and
ships a malformed `dcterms` date that breaks openpyxl (we strip it). We read the
single combined-history workbook (`FMR_2Bed_YYYY_YYYY.xlsx`, one `fmrNN_2` column
per fiscal year), whose link is resolved dynamically from the HUD FMR datasets
page so the annual filename bump doesn't break the pipeline. Any FMR fetch
failure silently reverts Hawaiʻi & Kauaʻi to their 2-leg blend.

### Kauaʻi is provisional

Kauaʻi's weights remain an **assumption, not a measured result**. Zillow only
began publishing Kauaʻi ZORI in 2025, so (a) the live pipeline falls back to the
*statewide* ZORI ratio as Kauaʻi's ZORI leg, and (b) there is no historical ZORI
to backtest the weight against (zero usable cases). The new FMR leg (above) gives
Kauaʻi its first county-specific input, but at a modest 0.20 weight and with a
known backtest tradeoff — so the overall Kauaʻi blend is still provisional.
Re-validate once Kauaʻi has ≥2 years of ZORI (≈2027).

Fallback chain:
- BLS fetch fails → ACS raw values stay (no monthly currency)
- ZORI fetch fails → CPI-only scaling (lagging but consistent)
- County missing anchor-year ZORI baseline (Kauaʻi today) → use state ZORI
  ratio as proxy, analogous to how Honolulu BLS rent CPI is already applied
  statewide
- HUD FMR fetch fails (Hawaiʻi, Kauaʻi) → drop the FMR leg and revert to the
  2-leg CPI/ZORI blend for those counties

### Backtests

Two harnesses validate the weights, with complementary ground truths:

1. **Independent ground truth — `scripts/backtest_rent_nowcast.py` (M4).**
   Compares the blended *growth factor* against realized **ACS 1-yr contract
   rent** (B25058), 2021→2024, per county. ACS is not one of the blend inputs,
   so this view is free of the circularity in (2). Result: outer-island pooled
   MAPE at the live w=0.50 is **5.93%**, with a shallow MAPE-vs-weight curve
   (optimum w≈0.4 at 5.64% — 0.29 pp better, inside the ACS noise floor). Full
   report + the ACS-MoE noise-floor analysis in `docs/rent_nowcast_backtest.md`.

2. **Self-consistency — `backtests/rent_blend_walkforward.py`.**
   Pseudo-out-of-sample over anchors {2022-04 … 2024-04}, scoring the 12-month
   nowcast against (BLS+ZORI)/2 and BLS-only proxies. These proxies are *built
   from the blend inputs*, so each is mechanically biased toward the weight that
   favors its dominant series — the two views bracket the truth rather than
   pinpoint it. Live weights sit at 3.28% (BLS-truth) / 5.75% (blend-truth).
   Results in `backtests/results/`.

Both harnesses agree directionally: the **outer islands want more ZORI weight
than Honolulu's 0.70**, which is what motivated the 0.50 outer-island split.

A third harness, **`scripts/backtest_rent_3leg.py`** (addendum in
`docs/rent_nowcast_backtest.md`), motivated the targeted HUD FMR leg: on the
ACS-truth outer cases a 3-leg CPI/ZORI/FMR blend beats the 2-leg 5.93% (≈5.35%
pooled), with the gain concentrated in Hawaiʻi (9.21% → ~4.8%) and Kauaʻi
gaining its first county-specific validation. The win is *not* uniform — Maui
and Honolulu are better without FMR — which is why the leg is applied only to
Hawaiʻi and Kauaʻi rather than blanket-added.

### Regression budget

- **Primary gate: outer-island pooled blended-rent MAPE ≤ 8%** (independent ACS
  ground truth). Current **5.93%** ✓. Re-run `scripts/backtest_rent_nowcast.py`.
- A flat **per-county** 8% gate is intentionally *not* adopted — Maui's ACS 1-yr
  MoE alone is ±10.5% (Kauaʻi ±14.8% at 90% CI), so the ground truth is blurrier
  than an 8% target. Track per-county MAPE for *direction* (flag a >3 pp jump
  between annual re-runs), not as a hard pass/fail.

Refresh cadence: rerun both harnesses annually after a new ACS vintage drops,
and any time the blend logic or weights change. Cached BLS/ACS responses for
the walk-forward live in `backtests/cache/`.

---

## Grocery basket: effective price

Published prices are the all-in consumer cost:
1. Start with **member/loyalty prices** (the prices actually paid at the
   register — Foodland Maika'i, Safeway Club, Costco membership).
2. Aggregate per county via **market-share weights**
   (`config/store_weights.json`, built from SNAP retailer list + Census CBP
   employment cross-check).
3. Apply Hawaii **General Excise Tax (4.5%)** at checkout — GET hits
   groceries at the register, unlike most US states that exempt food.

The dashboard's `basketWithTax` field is the post-GET, post-weighting number;
`basketPretax` is the pre-GET subtotal for audit.

---

## BLS CE PUMD "typical household" side-statistic

### What this is

`pipelines/grocery/data/pumd_honolulu_monthly.json` holds a **separate**
benchmark of average monthly food-at-home (FAH) spending per Honolulu
household, derived from the BLS Consumer Expenditure Public Use Microdata
(CE PUMD) interview-survey microdata. The dashboard's grocery card surfaces
this as a "Typical: $X/mo per BLS CE PUMD" line under the existing
`monthlyFamily4` derived from our receipt basket.

**This is a side-statistic only.** It does **not** drive any per-item
pricing, does **not** modify the receipt basket, and does **not** change
the headline `basketWithTax` or `monthlyFamily4` numbers. It exists so
readers can compare the basket-derived family-of-4 cost against an
independently measured household spending figure.

### Why it's separate from the basket

- **Receipts** measure *prices* — what a specific item costs at a specific
  store on a specific date. Per-item, per-category, per-county granularity.
- **PUMD** measures *spending* — what households actually pay for groceries
  per month, including substitution, brand choice, and basket composition
  effects we can't capture in a fixed basket. PSU resolution: only Urban
  Honolulu is identifiable in PUMD.

The two answer different questions, and we surface both rather than
calibrating one against the other.

### How the figures are derived

`pipelines/grocery/scripts/refresh_ce_pumd.py` orchestrates a full
microdata refresh:

1. **Download** the 5 most recent annual interview-survey ZIPs from
   `https://www.bls.gov/cex/pumd/data/comma/intrvw{yy}.zip` (default
   2019–2023; ~30 MB each, written to `data/pumd_raw/` which is
   git-ignored).
2. **Filter** FMLI rows to PSU codes for Urban Honolulu (`S49A`–`S49D`).
3. **Aggregate** food-at-home directly from MTBI (per BLS errata for
   2023+, the `FDHOMEPQ`/`FDHOMECQ` summary columns were stripped):
   sum UCCs whose hierarchical-grouping code starts with `19` and excludes
   `1909*` (groceries on trips).
4. **Per-household monthly FAH** = sum(MTBI FAH UCCs) / 3 (each FMLI row
   is a quarterly interview).
5. **Inflation-adjust** each year to the latest period via the Honolulu
   food CPI series `CUURS49ASAF11`.
6. **Apply CE-recommended `FINLWT21` weights** for population-representative
   means; pool 5 years to mitigate small Honolulu PSU sample size
   (~50–200 households/quarter; 5y pool gives ~1.5–4k Honolulu HH-quarters).
7. **Stratify** by family size: 1, 2, 3, 4+ buckets.

### Neighbor-island projection

PUMD only resolves to Honolulu; Maui, Hawaii, and Kauai household samples
don't exist. We project the Honolulu PUMD value to the neighbor islands
using the **receipt-derived basket gradient**:

```
county_factor[c]   = basket_total[c] / basket_total[Honolulu]
pumd_estimate[c]   = pumd_honolulu × county_factor[c]
state_estimate     = population-weighted mean over the four counties
```

This preserves PUMD as the **absolute-level anchor** (real measured
Honolulu spending) and the receipts as the **spatial gradient** (real
measured price gaps across counties). Both inputs are real data; the
combination is internally consistent.

### Refresh cadence

- **Timing**: annually, target October. BLS releases each PUMD year ~9–12
  months after collection ends; new full-year data typically lands in
  September–October.
- **Window**: each refresh shifts the 5-year pool forward by one year.
  E.g. the 2026 refresh uses 2020–2024 once 2024 is published.
- **Command**:
  ```bash
  python3 pipelines/grocery/scripts/refresh_ce_pumd.py --years 2020 2021 2022 2023 2024
  ```
  This downloads ~150 MB of raw data, runs the extractor, and overwrites
  `pumd_honolulu_monthly.json`.

### Bootstrap-vs-microdata distinction

The current `pumd_honolulu_monthly.json` carries
`method: "bootstrap_from_published_aggregates_pending_microdata_refresh"`.
That means the figures were derived from BLS CES 2022-23 published
Honolulu MSA aggregates (Table 3204 metro-area patterns), inflated to
2024-12 via the Honolulu food CPI, and projected across counties via the
basket gradient.

The bootstrap exists because the BLS PUMD ZIP endpoint is blocked from
this development environment by Akamai access controls. Running the
refresh script from an unblocked network (residential, etc.) will:

- Replace `method` with `5y_pooled_finlwt21_inflated_to_as_of`
- Populate `n_households_total` with the pooled sample count
- Populate `honolulu_ci_95_overall` and `honolulu_ci_95_family4` with
  bootstrap 95% confidence intervals from the FINLWT21 weighted means

The pipeline tolerates either form: the JSON's `byCounty` numbers feed the
dashboard tile regardless of method, and the methodology popover annotates
the source.

### Sample-size caveats

- Honolulu PSU draws ~50–200 households per quarterly interview wave.
- 5-year pooling gives ~1,500–4,000 HH-quarters of FAH observations — wide
  enough for a single Honolulu mean but **not** enough to support fine
  cross-tabulation (e.g. family size × dwelling type × income tertile).
- Family-size buckets (1 / 2 / 3 / 4+) are usable; deeper splits would
  shrink CIs past the point of usefulness.
- Neighbor-island projections inherit the basket gradient's uncertainty —
  treat them as directional rather than precise.

### Failure modes

- Missing JSON → grocery pipeline logs and continues; "Typical" line is
  omitted from the card. No exception, no broken render.
- Corrupt JSON → same graceful fallback.
- Refresh script can't reach BLS → bootstrap stays in place; the file's
  `note` field documents the situation.

---

## Quarterly NTR/ATR benchmark refresh

### What this is

`data/ntr_atr_benchmarks.json` is a hand-maintained sanity-check file holding
the latest **national** YoY from BLS's two research rent series:

- **R-CPI-NTR** — *New Tenant Repeat Rent*. Reprices only units that
  transitioned to a new tenant in the quarter. Closest national analog to
  our ZORI-heavy asking-rent signal.
- **R-CPI-ATR** — *All Tenant Regressed Rent*. Hedonic-regression-adjusted
  all-tenant rent. Leads the official CPI rent series by roughly one quarter.

Both are **national only** — BLS does not publish a Hawaii cut. We use them
as a directional guardrail on our Honolulu nowcast, not as ground truth.

### Why manual refresh

Both series are published as XLSX files on
[bls.gov/cpi/research-series](https://www.bls.gov/cpi/research-series/r-cpi-ntr.htm).
BLS's public API does **not** expose the research series, and the XLSX
endpoints are gated by Akamai anti-bot rules that reject `curl`/`urllib`/
WebFetch regardless of User-Agent. A quarterly human refresh is simpler
and more reliable than fighting the anti-bot layer in CI.

### Refresh cadence

- **Timing**: quarterly, on or after the 15th of the month following each
  quarter-end (Jan / Apr / Jul / Oct). Data has a 1-quarter lag.
- **Who**: anyone bumping data for the dashboard around that time; the
  `_refresh_howto` array in `ntr_atr_benchmarks.json` is the checklist.

### Steps

1. Visit <https://www.bls.gov/cpi/research-series/r-cpi-ntr.htm> and download
   the latest R-CPI-NTR and R-CPI-ATR XLSX files.
2. Open each XLSX. The rightmost column is the just-published quarterly
   release (e.g. `2025Q4`).
3. YoY % = (latest_quarter / same_quarter_prior_year − 1) × 100.
4. Edit `data/ntr_atr_benchmarks.json`:
   - `latest_quarter`  → release quarter string (e.g. `"2025Q4"`)
   - `ntr_yoy_pct`     → NTR YoY %
   - `atr_yoy_pct`     → ATR YoY %
   - `last_refreshed`  → today's ISO date
   - `refreshed_by`    → your name or email
5. Commit the change. The next `redfin-price-updater.py` run will consume
   the new values and print them in the "Rent sanity check" block.

### How the audit uses the benchmark

`audit_rent_nowcast_vs_ntr()` in `redfin-price-updater.py` runs after the
blended-nowcast block on every run. It prints a 5-row table: Honolulu rent
CPI YoY, Honolulu ZORI YoY, national NTR YoY, national ATR YoY, and the
first-order approximation of the Honolulu blended YoY
(`w·CPI_YoY + (1−w)·ZORI_YoY` with w=0.7).

If `|blended − ntr| > sanity_band_pp` (default ±8 pp), the updater prints
a `⚠ WARNING` line. The warning does **not** block the run — Hawaii rent
inflation routinely runs hotter or cooler than the national average — but
a gap far outside the band is the clearest signal that either our weights
need retuning or an upstream data source broke.

When the benchmark JSON still has null NTR/ATR values (e.g. first commit,
or a quarter you haven't refreshed yet), the audit prints the Honolulu
numbers anyway and hints at the refresh path so the blind spot is visible.

---

## Unit conventions (cadence + conversions)

To keep the dashboard internally consistent, every number flows through
one of three native cadences:

| Domain | Native cadence | Where to convert |
|---|---|---|
| Sale prices (Redfin) | monthly | reported as a 3-month trailing **median** (thin-market noise damping — see "Home sale prices") |
| Asking rent (ZORI) | monthly | n/a |
| Existing-tenant rent (BLS) | bimonthly (odd months) | always reported as nowcast for the latest odd month |
| Headline / shelter / food / energy / transport CPI | bimonthly (odd months) | YoY only; no resampling |
| TFP (USDA CNPP) | monthly | rolled forward via Honolulu food CPI when stale |
| Grocery basket | monthly target, weekly published | `WEEKS_PER_MONTH = 52/12` |
| HUD income limits | annual (FY) | annual % of income → /12 for monthly comparisons |
| DBEDT construction auth | annual | n/a |
| AAA gas | daily snapshot | n/a |

**`WEEKS_PER_MONTH` constant**: `52 / 12 = 4.3333…`. Used in two places
that must stay reciprocal:

* `grocery-price-updater.py` converts the priced basket from weekly to
  monthly: `monthly_family4 = weekly * WEEKS_PER_MONTH`.
* The HTML `renderGoodsPane()` does the inverse for the TFP-anchored
  weekly display: `tfpWeekly = tfpMonthly / WEEKS_PER_MONTH`.

If you change the constant in one place, change it in the other; otherwise
the headline weekly figure will silently drift away from `monthlyFamily4 /
4.33`.

**Annualized vs monthly growth**: every per-month rate in the projection
code (`price_adjuster.py`, `tfp-updater.py`) is a *compound* rate, not a
simple one. `monthly_rate = (latest / prev) ** (1 / months_between) - 1`
and `projected = latest * (1 + monthly_rate) ** months_beyond`. Don't mix
this with the annualized YoY surfaced in the headline chip — those are
12-month log-equivalent aggregations that already include compounding.

**Rent nowcast cadence**: even though BLS rent CPI is bimonthly and ZORI
is monthly, both ratios are applied to the same `RENT_ANCHOR_YEAR` ACS
dollar anchor and combined in *level space*, so the blended figure is
re-published on every monthly run regardless of whether BLS issued a fresh
print that month — the BLS half just carries the latest odd-month ratio
forward until the next release lands.

---

## Change control

Any time you bump a vintage, change a series ID, or alter a weight —
update this file **in the same commit** as the code change. Readers
(including future-you) look here first to understand why a reported number
moved.

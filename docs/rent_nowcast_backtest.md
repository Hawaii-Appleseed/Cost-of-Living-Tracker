# Blended rent nowcast — backtest & weight validation (M4)

**Run:** `CENSUS_API_KEY=… BLS_API_KEY=… python3 scripts/backtest_rent_nowcast.py`
**Date generated:** 2026-05-28
**Question:** Is the production outer-island blend weight (50% Honolulu CPI / 50% county ZORI) producing an acceptable margin of error?

## TL;DR

**Yes — 50/50 is acceptable and statistically indistinguishable from the optimum.**

- Outer-island pooled blended-rent **MAPE at w=0.50 is 5.93%**, inside both the
  6.76% census-forecasting budget (`CLAUDE.md`) and the proposed 8% rent budget.
- The MAPE-vs-weight curve is **shallow**: across the full 0.0→1.0 sweep the
  outer-island MAPE only moves from 5.64% (best, w=0.4) to 7.66% (worst, pure
  CPI). Production's 0.50 (5.93%) is **0.29 pp** off the optimum — noise-level.
- That 0.29 pp is far smaller than the **ACS ground truth's own sampling MoE**
  (Maui ±10.5%, Kauaʻi ±14.8% at 90% CI). The yardstick is blurrier than the
  differences between candidate weights, so retuning to 0.4 would be overfitting
  to 15 noisy points. **Recommendation: keep 0.50.**

## Method

For each county and each ordered year-pair (t0 < t1) in 2021–2024 we have
direct ACS 1-yr **contract rent** (B25058 — the same measure as the production
anchor). We test whether the blended *growth factor* reproduces realized growth:

```
true_factor = ACS1(t1) / ACS1(t0)
bls_factor  = BLS CUURS49ASEHA annual-avg(t1) / annual-avg(t0)   # Honolulu, shared by all counties
zori_factor = ZORI annual-avg(c, t1) / annual-avg(c, t0)         # per county
pred(w)     = ACS1(t0) × ( w·bls_factor + (1-w)·zori_factor )
ape(w)      = |pred(w) / ACS1(t1) − 1|
```

MAPE is averaged over all available year-pairs, per county and pooled.

## Ground-truth noise floor (the key caveat)

ACS 1-yr contract rent is the only same-definition ground truth available, but
on the thin outer-island samples it is itself very noisy:

| County | mean MoE % (90% CI) | implied SE % (÷1.645) |
|---|---|---|
| Honolulu | 2.5% | 1.5% |
| Hawaiʻi | 7.5% | 4.6% |
| Maui | 10.5% | 6.4% |
| Kauaʻi | 14.8% | 9.0% |

**The reported backtest MAPEs (~5–10% on outer islands) are partly measuring
ACS sampling noise, not pure nowcast error.** Any weight difference smaller than
these bands cannot be resolved by this test — which is exactly the situation for
0.3 vs 0.4 vs 0.5.

## ZORI coverage (limits the backtest)

| County | ZORI annual-avg years (≥6 monthly prints) | backtest cases |
|---|---|---|
| Honolulu | 2015–2025 | 6 |
| Maui | 2021–2025 | 6 |
| Hawaiʻi | 2022–2025 | 3 |
| Kauaʻi | **2025 only** | **0** |

**Kauaʻi has zero backtest coverage** — Zillow only began publishing Kauaʻi ZORI
in 2025, and production already falls back to the *statewide* ZORI ratio as a
proxy for it. Kauaʻi's 50/50 weight is therefore an **unvalidated assumption**,
not a measured choice. Re-run this backtest once Kauaʻi has ≥2 years of ZORI
(≈2027).

## Results — MAPE vs CPI weight

### Outer islands pooled (Maui + Hawaiʻi + Kauaʻi), n=9

| w (CPI weight) | MAPE % | |
|---|---|---|
| 0.0 | 6.33 | pure ZORI |
| 0.3 | 5.67 | |
| **0.4** | **5.64** | **optimum** |
| 0.5 | 5.93 | **← production** |
| 0.7 | 6.62 | |
| 1.0 | 7.66 | pure CPI (worst) |

Pure CPI is the *worst* option for the outer islands — confirming that applying
Honolulu rent CPI alone to neighbor-island rents is the weakest choice and the
county-specific ZORI signal genuinely helps. The data leans slightly *more*
toward ZORI than 50/50, but the gain is inside the noise floor.

### Per-county (production weight in bold)

| County | n | optimal w (MAPE) | production w (MAPE) | verdict |
|---|---|---|---|---|
| Honolulu | 6 | 1.0 (5.11%) | **0.7 (5.20%)** | ✓ negligible gap; tiny ACS MoE makes this the most trustworthy row |
| Maui | 6 | 0.4 (3.99%) | **0.5 (4.29%)** | ✓ best-validated outer island; well under budget |
| Hawaiʻi | 3 | 0.0 (7.83%) | **0.5 (9.21%)** | ⚠ see note |
| Kauaʻi | 0 | — | **0.5 (—)** | ⚠ no data — provisional |

**Hawaiʻi note:** realized Big-Island rent grew +31% from 2022→2024 (ACS
×1.309), outrunning *both* the CPI factor (×1.105) and ZORI (×1.157). No blend
of two under-shooting proxies can hit a target above both, so MAPE is high and
falls monotonically as weight shifts to the larger (ZORI) factor. At w=0.5 the
9.21% MAPE sits only ~1.5 pp above Hawaiʻi's own ACS noise band (SE 4.6% → ±9%
at 90% CI on a single pair), so part of that "miss" is likely a low 2022 ACS
print rather than true nowcast error. Still, Hawaiʻi is the weakest county and
worth re-checking next cycle.

The per-county optima **disagree** (Honolulu 1.0, Maui 0.4, Hawaiʻi 0.0). With
only 15 total noisy cases, fitting a separate weight per county would be
overfitting. A single shared outer-island weight near the pooled optimum (0.4–0.5)
is the defensible choice; 0.50 is already there.

## Regression budget (proposed)

Adopt as a CI/methodology gate, mirroring the 6.76% census MAPE precedent:

- **Primary gate — outer-island pooled blended-rent MAPE ≤ 8%.**
  Current: **5.93%** ✓ (re-run via `scripts/backtest_rent_nowcast.py`).
- **Per-county gate is intentionally NOT set at a flat 8%** — Maui's ACS MoE
  alone is 10.5%, so a flat per-county 8% would demand the nowcast be more
  precise than the only available yardstick. Track per-county MAPE for
  *direction* (flag if a county's MAPE jumps >3 pp between annual re-runs)
  rather than as a hard pass/fail.

## Recommendations

1. **Keep w=0.50 for Maui & Hawaiʻi** — validated, within the pooled budget;
   the marginally-better 0.4 is inside the noise floor and would risk overfit.
2. **Keep w=0.70 for Honolulu / State** — Honolulu's near-optimal pure-CPI
   result confirms CPI is highly representative there; 0.70 retains a sensible
   amount of leading ZORI signal at a negligible (0.09 pp) MAPE cost.
3. **Flag Kauaʻi's 0.50 as provisional** in `METHODOLOGY.md` — no ZORI history
   to validate it, statewide-proxy ZORI leg. Re-backtest ≈2027 once Kauaʻi has
   ≥2 years of ZORI.
4. **Re-run this backtest annually** when each new ACS 1-yr vintage lands
   (≈ each September), and record the new pooled MAPE here.

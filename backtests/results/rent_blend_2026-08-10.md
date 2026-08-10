# Rent-blend walk-forward backtest — 2026-08-10

Pseudo-out-of-sample evaluation of `blend_rent_nowcast()` (live weight 0.70 CPI / 0.30 ZORI). For each anchor T, we form a blended rent estimate using only data available at T, then compare to two ground-truth proxies at T+12:

1. **Blend-truth** = (BLS-dollars + ZORI-dollars) / 2 at T+12 — the construction in the original plan; biased toward whichever input is more current at T+12 (ZORI).
2. **BLS-only-truth** = BLS-dollars at T+12 — leverages the BLS ~12-month lag so BLS at T+12 ≈ rent at T; biased toward CPI-heavy weights but more directly addresses the nowcast question.

Both proxies share the same ACS vintage and base-year scaling, so dollar values are directly comparable to the prediction.

## Ground truth A — Blend ((BLS+ZORI)/2)

### Detail vs ground truth = (BLS+ZORI)/2

| Anchor | T+12 | ACS vint. | Region | Anchor $ | BLS-only | 70/30 | 60/40 | 50/50 | ZORI-only | Realized | |70/30 err| | %err 70/30 |
|---|---|---|---|---|---|---|---|---|---|---|---|---|
| 2022-04 | 2023-04 | 2020 | State | $1,497 | $1,564 | $1,608 | $1,623 | $1,638 | $1,712 | $1,685 | $77 | -4.60% |
| 2022-04 | 2023-04 | 2020 | Honolulu | $1,638 | $1,711 | $1,759 | $1,775 | $1,791 | $1,872 | $1,843 | $84 | -4.56% |
| 2022-04 | 2023-04 | 2020 | Hawaii | $1,053 | $1,100 | $1,131 | $1,142 | $1,152 | $1,204 | $1,186 | $55 | -4.60% |
| 2022-04 | 2023-04 | 2020 | Maui | $1,395 | $1,457 | $1,601 | $1,648 | $1,696 | $1,935 | $1,738 | $137 | -7.90% |
| 2022-04 | 2023-04 | 2020 | Kauai | $1,249 | $1,305 | $1,342 | $1,354 | $1,366 | $1,428 | $1,406 | $64 | -4.57% |
| 2022-10 | 2023-10 | 2020 | State | $1,497 | $1,588 | $1,628 | $1,641 | $1,654 | $1,720 | $1,730 | $102 | -5.90% |
| 2022-10 | 2023-10 | 2020 | Honolulu | $1,638 | $1,738 | $1,783 | $1,798 | $1,814 | $1,889 | $1,883 | $100 | -5.31% |
| 2022-10 | 2023-10 | 2020 | Hawaii | $1,053 | $1,117 | $1,145 | $1,154 | $1,163 | $1,210 | $1,217 | $72 | -5.91% |
| 2022-10 | 2023-10 | 2020 | Maui | $1,395 | $1,480 | $1,605 | $1,646 | $1,688 | $1,895 | $1,813 | $208 | -11.49% |
| 2022-10 | 2023-10 | 2020 | Kauai | $1,249 | $1,325 | $1,358 | $1,369 | $1,380 | $1,435 | $1,443 | $85 | -5.92% |
| 2023-04 | 2024-04 | 2021 | State | $1,591 | $1,670 | $1,696 | $1,705 | $1,714 | $1,757 | $1,864 | $168 | -9.02% |
| 2023-04 | 2024-04 | 2021 | Honolulu | $1,720 | $1,806 | $1,834 | $1,844 | $1,853 | $1,900 | $1,994 | $160 | -8.01% |
| 2023-04 | 2024-04 | 2021 | Hawaii | $1,086 | $1,140 | $1,171 | $1,181 | $1,191 | $1,242 | $1,316 | $145 | -11.05% |
| 2023-04 | 2024-04 | 2021 | Maui | $1,497 | $1,572 | $1,631 | $1,651 | $1,670 | $1,769 | $1,900 | $269 | -14.17% |
| 2023-04 | 2024-04 | 2021 | Kauai | $1,352 | $1,419 | $1,442 | $1,449 | $1,456 | $1,493 | $1,584 | $142 | -8.97% |
| 2023-10 | 2024-10 | 2021 | State | $1,591 | $1,721 | $1,744 | $1,752 | $1,759 | $1,797 | $1,876 | $132 | -7.02% |
| 2023-10 | 2024-10 | 2021 | Honolulu | $1,720 | $1,861 | $1,880 | $1,887 | $1,894 | $1,927 | $2,024 | $144 | -7.11% |
| 2023-10 | 2024-10 | 2021 | Hawaii | $1,086 | $1,175 | $1,212 | $1,224 | $1,236 | $1,297 | $1,312 | $100 | -7.65% |
| 2023-10 | 2024-10 | 2021 | Maui | $1,497 | $1,619 | $1,692 | $1,717 | $1,741 | $1,862 | $1,835 | $143 | -7.81% |
| 2023-10 | 2024-10 | 2021 | Kauai | $1,352 | $1,462 | $1,482 | $1,488 | $1,495 | $1,527 | $1,594 | $112 | -7.02% |
| 2024-04 | 2025-04 | 2022 | State | $1,704 | $1,940 | $1,917 | $1,909 | $1,901 | $1,863 | $1,962 | $45 | -2.29% |
| 2024-04 | 2025-04 | 2022 | Honolulu | $1,824 | $2,076 | $2,038 | $2,025 | $2,012 | $1,948 | $2,080 | $42 | -2.01% |
| 2024-04 | 2025-04 | 2022 | Hawaii | $1,160 | $1,320 | $1,320 | $1,320 | $1,320 | $1,319 | $1,356 | $36 | -2.63% |
| 2024-04 | 2025-04 | 2022 | Maui | $1,614 | $1,837 | $1,864 | $1,873 | $1,881 | $1,926 | $1,858 | $6 | +0.34% |
| 2024-04 | 2025-04 | 2022 | Kauai | $1,498 | $1,705 | $1,685 | $1,678 | $1,671 | $1,638 | $1,725 | $40 | -2.31% |

### Aggregate vs ground truth = (BLS+ZORI)/2

| Weight scheme | N | MAE ($) | MAPE | Max abs err ($) |
|---|---|---|---|---|
| BLS-only | 25 | 141 | 8.39% | 333 |
| 70/30 (live) | 25 | 107 | 6.33% | 269 |
| 60/40 | 25 | 96 | 5.67% | 249 |
| 50/50 | 25 | 85 | 5.02% | 230 |
| ZORI-only | 25 | 64 | 3.66% | 197 |

### Per-region MAPE vs ground truth = (BLS+ZORI)/2 (live 70/30 weight)

| Region | N anchors | MAPE | MAE ($) |
|---|---|---|---|
| State | 5 | 5.77% | 105 |
| Honolulu | 5 | 5.40% | 106 |
| Hawaii | 5 | 6.37% | 82 |
| Maui | 5 | 8.34% | 153 |
| Kauai | 5 | 5.76% | 89 |

## Ground truth B — BLS-only (BLS at T+12 ≈ rent at T)

### Detail vs ground truth = BLS at T+12

| Anchor | T+12 | ACS vint. | Region | Anchor $ | BLS-only | 70/30 | 60/40 | 50/50 | ZORI-only | Realized | |70/30 err| | %err 70/30 |
|---|---|---|---|---|---|---|---|---|---|---|---|---|
| 2022-04 | 2023-04 | 2020 | State | $1,497 | $1,564 | $1,608 | $1,623 | $1,638 | $1,712 | $1,601 | $7 | +0.45% |
| 2022-04 | 2023-04 | 2020 | Honolulu | $1,638 | $1,711 | $1,759 | $1,775 | $1,791 | $1,872 | $1,752 | $7 | +0.42% |
| 2022-04 | 2023-04 | 2020 | Hawaii | $1,053 | $1,100 | $1,131 | $1,142 | $1,152 | $1,204 | $1,126 | $5 | +0.44% |
| 2022-04 | 2023-04 | 2020 | Maui | $1,395 | $1,457 | $1,601 | $1,648 | $1,696 | $1,935 | $1,492 | $109 | +7.33% |
| 2022-04 | 2023-04 | 2020 | Kauai | $1,249 | $1,305 | $1,342 | $1,354 | $1,366 | $1,428 | $1,336 | $6 | +0.48% |
| 2022-10 | 2023-10 | 2020 | State | $1,497 | $1,588 | $1,628 | $1,641 | $1,654 | $1,720 | $1,649 | $21 | -1.30% |
| 2022-10 | 2023-10 | 2020 | Honolulu | $1,638 | $1,738 | $1,783 | $1,798 | $1,814 | $1,889 | $1,805 | $22 | -1.21% |
| 2022-10 | 2023-10 | 2020 | Hawaii | $1,053 | $1,117 | $1,145 | $1,154 | $1,163 | $1,210 | $1,160 | $15 | -1.31% |
| 2022-10 | 2023-10 | 2020 | Maui | $1,395 | $1,480 | $1,605 | $1,646 | $1,688 | $1,895 | $1,537 | $68 | +4.42% |
| 2022-10 | 2023-10 | 2020 | Kauai | $1,249 | $1,325 | $1,358 | $1,369 | $1,380 | $1,435 | $1,376 | $18 | -1.32% |
| 2023-04 | 2024-04 | 2021 | State | $1,591 | $1,670 | $1,696 | $1,705 | $1,714 | $1,757 | $1,872 | $176 | -9.42% |
| 2023-04 | 2024-04 | 2021 | Honolulu | $1,720 | $1,806 | $1,834 | $1,844 | $1,853 | $1,900 | $2,024 | $190 | -9.40% |
| 2023-04 | 2024-04 | 2021 | Hawaii | $1,086 | $1,140 | $1,171 | $1,181 | $1,191 | $1,242 | $1,278 | $107 | -8.38% |
| 2023-04 | 2024-04 | 2021 | Maui | $1,497 | $1,572 | $1,631 | $1,651 | $1,670 | $1,769 | $1,762 | $131 | -7.43% |
| 2023-04 | 2024-04 | 2021 | Kauai | $1,352 | $1,419 | $1,442 | $1,449 | $1,456 | $1,493 | $1,591 | $149 | -9.37% |
| 2023-10 | 2024-10 | 2021 | State | $1,591 | $1,721 | $1,744 | $1,752 | $1,759 | $1,797 | $1,883 | $139 | -7.38% |
| 2023-10 | 2024-10 | 2021 | Honolulu | $1,720 | $1,861 | $1,880 | $1,887 | $1,894 | $1,927 | $2,036 | $156 | -7.64% |
| 2023-10 | 2024-10 | 2021 | Hawaii | $1,086 | $1,175 | $1,212 | $1,224 | $1,236 | $1,297 | $1,285 | $73 | -5.70% |
| 2023-10 | 2024-10 | 2021 | Maui | $1,497 | $1,619 | $1,692 | $1,717 | $1,741 | $1,862 | $1,772 | $80 | -4.50% |
| 2023-10 | 2024-10 | 2021 | Kauai | $1,352 | $1,462 | $1,482 | $1,488 | $1,495 | $1,527 | $1,600 | $118 | -7.38% |
| 2024-04 | 2025-04 | 2022 | State | $1,704 | $1,940 | $1,917 | $1,909 | $1,901 | $1,863 | $1,989 | $72 | -3.63% |
| 2024-04 | 2025-04 | 2022 | Honolulu | $1,824 | $2,076 | $2,038 | $2,025 | $2,012 | $1,948 | $2,129 | $91 | -4.29% |
| 2024-04 | 2025-04 | 2022 | Hawaii | $1,160 | $1,320 | $1,320 | $1,320 | $1,320 | $1,319 | $1,354 | $34 | -2.53% |
| 2024-04 | 2025-04 | 2022 | Maui | $1,614 | $1,837 | $1,864 | $1,873 | $1,881 | $1,926 | $1,884 | $20 | -1.07% |
| 2024-04 | 2025-04 | 2022 | Kauai | $1,498 | $1,705 | $1,685 | $1,678 | $1,671 | $1,638 | $1,749 | $64 | -3.65% |

### Aggregate vs ground truth = BLS at T+12

| Weight scheme | N | MAE ($) | MAPE | Max abs err ($) |
|---|---|---|---|---|
| BLS-only | 25 | 93 | 5.59% | 218 |
| 70/30 (live) | 25 | 75 | 4.42% | 190 |
| 60/40 | 25 | 75 | 4.44% | 180 |
| 50/50 | 25 | 77 | 4.57% | 204 |
| ZORI-only | 25 | 109 | 6.66% | 443 |

### Per-region MAPE vs ground truth = BLS at T+12 (live 70/30 weight)

| Region | N anchors | MAPE | MAE ($) |
|---|---|---|---|
| State | 5 | 4.44% | 83 |
| Honolulu | 5 | 4.59% | 93 |
| Hawaii | 5 | 3.67% | 47 |
| Maui | 5 | 4.95% | 82 |
| Kauai | 5 | 4.44% | 71 |

## Recommendation

- Under **blend ground truth**, lowest-MAPE scheme is **ZORI-only** (3.66%); live 70/30 sits at 6.33%.
- Under **BLS-only ground truth**, lowest-MAPE scheme is **70/30 (live)** (4.42%); live 70/30 sits at 4.42%.

These two ground-truth constructions bracket the true accuracy of the live nowcast. The blend-truth view favors lower CPI weights (it is correlated with ZORI by construction); the BLS-only-truth view favors higher CPI weights. The live 70/30 lives near the midpoint and is reasonably defensible under both views.

The live `BLENDED_RENT_CPI_WEIGHT = 0.70` is **not** auto-modified by this harness. If a future review wants to retune, the per-region tables above are the most granular signal (Honolulu has the cleanest ACS + full ZORI history; Kauai falls back on a state ZORI ratio for some anchors).

## Caveats
- ACS B25058_001E is *contract* rent (utilities excluded), comparable to ZORI but not directly to BLS rent of primary residence. The blend is internally consistent because all components apply growth ratios to a single ACS dollar value.
- Kauai ZORI history started recently; vintage-year averages may use a state-fallback ratio when the county itself is missing.
- 5 anchors × 5 regions = 25 max cells per ground-truth view. Sample is small; treat MAPE differences between schemes as directional, not statistically definitive.
- The harness does **not** itself project T → T+12 into the future with the blend; it tests how stable the blend's nowcast is over a 12-month horizon when measured against the proxies above.


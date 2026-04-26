# Anchor calibration (schema v3)
**Run date:** 2026-04-26
**Anchor years:** [2015, 2016, 2017, 2019, 2021, 2022]
**Horizons:** [1, 2, 3]y
**Coverage band:** [85%, 95%]

## Per-(indicator, source) RMSE

Lower RMSE → higher weight in the multi-source anchor combiner.

### B19013_001E

| Source | RMSE (pct error) |
|---|---:|
| qcew_hawaii_wages | 7.22% |
| pce_deflator | 7.96% |
| cpi_honolulu_allitems | 8.02% |

### B25058_001E

| Source | RMSE (pct error) |
|---|---:|
| cpi_honolulu_rent | 9.24% |
| hud_fmr_honolulu | 9.28% |

### B25064_001E

| Source | RMSE (pct error) |
|---|---:|
| cpi_honolulu_rent | 8.78% |
| hud_fmr_honolulu | 8.95% |

### B25077_001E

| Source | RMSE (pct error) |
|---|---:|
| fred_hi_hpi | 7.11% |

## Per-(indicator, method) RMSE + CI90 coverage

### B19013_001E

| Method | RMSE | CI90 coverage |
|---|---:|---:|
| multi_anchor | 7.27% | 93.3% |
| trend_ensemble | 7.30% | 95.0% |

### B25058_001E

| Method | RMSE | CI90 coverage |
|---|---:|---:|
| multi_anchor | 8.47% | 93.3% |
| trend_ensemble | 9.78% | 90.0% |

### B25064_001E

| Method | RMSE | CI90 coverage |
|---|---:|---:|
| multi_anchor | 8.20% | 95.0% |
| trend_ensemble | 9.57% | 81.7% |

### B25077_001E

| Method | RMSE | CI90 coverage |
|---|---:|---:|
| multi_anchor | 6.99% | 93.3% |
| trend_ensemble | 7.65% | 93.3% |

## SE inflator overrides (where coverage outside [85%, 95%])

| Indicator | Method | Override factor |
|---|---|---:|
| B25064_001E | trend_ensemble | 2.600 |

## v3 bias corrections (cells where bias was applied)

Geometric bias `b = mean(log(point/actual))`, clamped to ±10% multiplicative. Applied as `point_corrected = point_raw / exp(b)`.

| Indicator | Method | Pop bucket | h bucket | b (log) | b (pct) | n | clamped |
|---|---|---|---|---:|---:|---:|---:|
| B19013_001E | multi_anchor | * | * | -0.0289 | -2.85% | 60 |  |
| B19013_001E | multi_anchor | medium | * | -0.0447 | -4.37% | 30 |  |
| B19013_001E | multi_anchor | medium | short | -0.0298 | -2.94% | 22 |  |
| B19013_001E | trend_ensemble | * | * | -0.0131 | -1.30% | 60 |  |
| B19013_001E | trend_ensemble | medium | * | -0.0292 | -2.88% | 30 |  |
| B19013_001E | trend_ensemble | medium | short | -0.0231 | -2.28% | 22 |  |
| B25058_001E | multi_anchor | * | * | -0.0424 | -4.16% | 60 |  |
| B25058_001E | multi_anchor | medium | * | -0.0595 | -5.78% | 30 |  |
| B25058_001E | multi_anchor | medium | short | -0.0463 | -4.53% | 22 |  |
| B25058_001E | trend_ensemble | * | * | -0.0447 | -4.37% | 60 |  |
| B25058_001E | trend_ensemble | medium | * | -0.0795 | -7.64% | 30 |  |
| B25058_001E | trend_ensemble | medium | short | -0.0659 | -6.38% | 22 |  |
| B25064_001E | multi_anchor | * | * | -0.0359 | -3.53% | 60 |  |
| B25064_001E | multi_anchor | medium | * | -0.0520 | -5.07% | 30 |  |
| B25064_001E | multi_anchor | medium | short | -0.0374 | -3.67% | 22 |  |
| B25064_001E | trend_ensemble | * | * | -0.0420 | -4.11% | 60 |  |
| B25064_001E | trend_ensemble | medium | * | -0.0734 | -7.08% | 30 |  |
| B25064_001E | trend_ensemble | medium | short | -0.0605 | -5.87% | 22 |  |
| B25077_001E | multi_anchor | * | * | -0.0115 | -1.14% | 60 |  |
| B25077_001E | multi_anchor | medium | * | -0.0293 | -2.89% | 30 |  |
| B25077_001E | multi_anchor | medium | short | -0.0127 | -1.26% | 22 |  |
| B25077_001E | trend_ensemble | * | * | -0.0609 | -5.91% | 60 |  |
| B25077_001E | trend_ensemble | medium | * | -0.0798 | -7.67% | 30 |  |
| B25077_001E | trend_ensemble | medium | short | -0.0552 | -5.37% | 22 |  |

## v3 SE inflators by stratum (κ ≠ 1.30)

| Indicator | Method | Pop bucket | h bucket | κ | n |
|---|---|---|---|---:|---:|
| B19013_001E | multi_anchor | medium | short | 1.950 | 22 |
| B25058_001E | multi_anchor | medium | short | 1.625 | 22 |
| B25058_001E | trend_ensemble | medium | * | 1.008 | 30 |
| B25058_001E | trend_ensemble | medium | short | 1.008 | 22 |
| B25077_001E | trend_ensemble | medium | * | 1.008 | 30 |
| B25077_001E | trend_ensemble | medium | short | 1.008 | 22 |


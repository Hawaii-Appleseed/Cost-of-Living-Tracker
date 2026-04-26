#!/usr/bin/env python3
"""Calibrate multi-source anchor weights and SE inflators on hold-out data.

Defaults to v3 (stratified, multi-horizon, geometric bias correction):
* Per-source RMSE — feeds inverse-variance weights inside the multi-anchor combiner.
* Per-(indicator, method, pop_bucket, h_bucket) cells — feed κ overrides
  and bias corrections for the v3 strata fallback chain.

Pass `--v2` to fall back to the legacy v2 single-horizon calibrator
(useful for regression-comparing against pre-v3 calibration vintages).

Output: `census_forecasting/data/anchors/calibration.json` (v3 schema by
default, v2 with `--v2`)
        `census_forecasting/backtests/results/calibration_<run-date>.md`

Run
---
    python3 census_forecasting/scripts/calibrate_anchors.py
    python3 census_forecasting/scripts/calibrate_anchors.py --horizons 1,2,3
    python3 census_forecasting/scripts/calibrate_anchors.py --v2 --horizon 2
"""
from __future__ import annotations

import argparse
import json
import sys
from collections import defaultdict
from datetime import date
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(ROOT))

from census_forecaster.acs.client import AcsClient
from census_forecaster.acs.calibration import (
    run_holdout_calibration,
    run_stratified_calibration,
    write_calibration,
    COVERAGE_LOWER_BOUND,
    COVERAGE_UPPER_BOUND,
)
from census_forecaster.models import AcsObservation


HAWAII_FIPS = "15"
INDICATORS = [
    # Detail tables (B*) — dollar-denominated and one rent-burden median
    "B19013_001E",  # Median household income
    "B25058_001E",  # Median contract rent
    "B25064_001E",  # Median gross rent
    "B25077_001E",  # Median home value
    "B25071_001E",  # Median gross rent as % of household income (renter cost burden)
    # Subject tables (S*) — pre-computed percentages
    "S1501_C02_014E",  # % age 25+ with HS or higher
    "S1501_C02_015E",  # % age 25+ with bachelor's or higher
    "S1701_C03_001E",  # % below poverty (all people)
]
TRAINING_YEARS = tuple(range(2010, 2025))
ANCHOR_YEARS = [2015, 2016, 2017, 2019, 2021, 2022]

# Hawaii county 2020 ACS B01003_001E (5-year vintage). Used to classify
# each county into the v3 population bucket. Frozen for the lifetime of
# the v3 calibration vintage. When the v3 multi-state panel is in use,
# `census_forecaster.scripts.load_calibration_panel.load_populations`
# returns a richer dict; this in-script constant ensures the Hawaii-only
# calibration still produces meaningful pop_bucket records.
HAWAII_POPULATIONS_2020: dict[str, int] = {
    "15001": 200_629,    # Hawaii County (Big Island) — large
    "15003": 1_009_506,  # Honolulu — xlarge
    "15007": 168_307,    # Maui — medium
    "15009": 73_135,     # Kauai — medium
}


def fetch_panel(client: AcsClient) -> dict[tuple[str, str], list[AcsObservation]]:
    panel: dict[tuple[str, str], list[AcsObservation]] = defaultdict(list)
    for indicator in INDICATORS:
        observations = client.fetch_series(
            indicator=indicator,
            years=TRAINING_YEARS,
            vintage="1y",
            state_fips=HAWAII_FIPS,
            county_fips=None,
        )
        for o in observations:
            panel[(o.geoid, o.indicator)].append(o)
    return panel


def write_report(
    payload: dict, out_dir: Path, run_date: str
) -> Path:
    out_dir.mkdir(parents=True, exist_ok=True)
    md_path = out_dir / f"calibration_{run_date}.md"

    lines = []
    schema_v = payload.get("schema_version", 2)
    lines.append(f"# Anchor calibration (schema v{schema_v})\n")
    lines.append(f"**Run date:** {run_date}\n")
    lines.append(f"**Anchor years:** {payload['anchor_years']}\n")
    if "horizons" in payload:
        lines.append(f"**Horizons:** {payload['horizons']}y\n")
    elif "horizon" in payload:
        lines.append(f"**Horizon:** {payload['horizon']}y\n")
    lines.append(f"**Coverage band:** [{COVERAGE_LOWER_BOUND * 100:.0f}%, {COVERAGE_UPPER_BOUND * 100:.0f}%]\n\n")

    lines.append("## Per-(indicator, source) RMSE\n\n")
    lines.append("Lower RMSE → higher weight in the multi-source anchor combiner.\n\n")
    src_table = payload.get("rmse_by_indicator_source", {})
    for ind in sorted(src_table.keys()):
        lines.append(f"### {ind}\n\n")
        lines.append("| Source | RMSE (pct error) |\n|---|---:|\n")
        for src, rmse in sorted(src_table[ind].items(), key=lambda x: x[1]):
            lines.append(f"| {src} | {rmse * 100:.2f}% |\n")
        lines.append("\n")

    lines.append("## Per-(indicator, method) RMSE + CI90 coverage\n\n")
    rmse_m = payload.get("rmse_by_indicator_method", {})
    cov_m = payload.get("ci90_coverage_by_indicator_method", {})
    for ind in sorted(rmse_m.keys()):
        lines.append(f"### {ind}\n\n")
        lines.append("| Method | RMSE | CI90 coverage |\n|---|---:|---:|\n")
        for m in sorted(rmse_m[ind].keys()):
            r = rmse_m[ind][m]
            c = cov_m.get(ind, {}).get(m, float("nan"))
            r_str = f"{r * 100:.2f}%" if r is not None and r == r else "—"
            c_str = f"{c * 100:.1f}%" if c is not None and c == c else "—"
            lines.append(f"| {m} | {r_str} | {c_str} |\n")
        lines.append("\n")

    overrides = payload.get("se_inflator_override_by_indicator_method", {})
    if overrides:
        lines.append("## SE inflator overrides (where coverage outside [85%, 95%])\n\n")
        lines.append("| Indicator | Method | Override factor |\n|---|---|---:|\n")
        for ind in sorted(overrides.keys()):
            for m, val in sorted(overrides[ind].items()):
                lines.append(f"| {ind} | {m} | {val:.3f} |\n")
        lines.append("\n")
    else:
        lines.append("All per-(indicator, method) coverage already inside [85%, 95%]; no overrides applied.\n\n")

    # v3 strata-aware sections
    if schema_v >= 3 and "strata_records" in payload:
        sr = payload["strata_records"]
        bias_records = sr.get("bias", [])
        non_zero_bias = [r for r in bias_records if r.get("value", 0) != 0]
        if non_zero_bias:
            lines.append("## v3 bias corrections (cells where bias was applied)\n\n")
            lines.append("Geometric bias `b = mean(log(point/actual))`, clamped to ±10% multiplicative. ")
            lines.append("Applied as `point_corrected = point_raw / exp(b)`.\n\n")
            lines.append("| Indicator | Method | Pop bucket | h bucket | b (log) | b (pct) | n | clamped |\n")
            lines.append("|---|---|---|---|---:|---:|---:|---:|\n")
            for r in sorted(non_zero_bias,
                            key=lambda x: (x["indicator"], x["method"],
                                            x["pop_bucket"], x["h_bucket"])):
                b = r["value"]
                import math as _m
                pct = (_m.exp(b) - 1) * 100
                clamped = "✓" if r.get("extra", {}).get("clamped", 0) > 0 else ""
                lines.append(
                    f"| {r['indicator']} | {r['method']} | {r['pop_bucket']} | "
                    f"{r['h_bucket']} | {b:+.4f} | {pct:+.2f}% | {r['n_folds']} | {clamped} |\n"
                )
            lines.append("\n")

        se_records = sr.get("se_inflator", [])
        # Cells that differ meaningfully from the global (1.30) inflator
        notable_se = [
            r for r in se_records
            if abs(r.get("value", 1.30) - 1.30) > 0.01 and r["pop_bucket"] != "*"
        ]
        if notable_se:
            lines.append("## v3 SE inflators by stratum (κ ≠ 1.30)\n\n")
            lines.append("| Indicator | Method | Pop bucket | h bucket | κ | n |\n")
            lines.append("|---|---|---|---|---:|---:|\n")
            for r in sorted(notable_se,
                            key=lambda x: (x["indicator"], x["method"],
                                            x["pop_bucket"], x["h_bucket"])):
                lines.append(
                    f"| {r['indicator']} | {r['method']} | {r['pop_bucket']} | "
                    f"{r['h_bucket']} | {r['value']:.3f} | {r['n_folds']} |\n"
                )
            lines.append("\n")

    md_path.write_text("".join(lines))
    return md_path


def main() -> int:
    p = argparse.ArgumentParser()
    p.add_argument("--horizon", type=int, default=2,
                    help="Single horizon for v2 mode (default 2).")
    p.add_argument("--horizons", type=str, default="1,2,3,4,5",
                    help="Comma-separated horizons for v3 mode.")
    p.add_argument("--v2", action="store_true",
                    help="Use legacy v2 single-horizon calibrator.")
    p.add_argument("--offline", action="store_true")
    args = p.parse_args()

    cache_path = ROOT / "census_forecasting" / "data" / "acs_cache.json"
    client = AcsClient(cache_path=cache_path, offline=args.offline)
    panel = fetch_panel(client)
    if not panel:
        print("[calibrate_anchors] No ACS observations available — exiting.", file=sys.stderr)
        return 1

    if args.v2:
        print("[calibrate_anchors] running v2 calibration (legacy)", file=sys.stderr)
        payload = run_holdout_calibration(
            series_by_key=panel,
            anchor_years=ANCHOR_YEARS,
            horizon=args.horizon,
        )
    else:
        horizons = tuple(int(h) for h in args.horizons.split(",") if h.strip())
        print(f"[calibrate_anchors] running v3 stratified calibration (horizons={horizons})",
                file=sys.stderr)
        payload = run_stratified_calibration(
            series_by_key=panel,
            anchor_years=ANCHOR_YEARS,
            horizons=horizons,
            populations=HAWAII_POPULATIONS_2020,
            n_threshold=20,
        )

    calib_path = ROOT / "census_forecasting" / "data" / "anchors" / "calibration.json"
    write_calibration(payload, calib_path)
    md = write_report(payload, ROOT / "census_forecasting" / "backtests" / "results", date.today().isoformat())
    print(f"Wrote {calib_path}")
    print(f"Wrote {md}")

    print()
    rmse_m = payload.get("rmse_by_indicator_method", {})
    for ind in sorted(rmse_m.keys()):
        for m in sorted(rmse_m[ind].keys()):
            cov = payload["ci90_coverage_by_indicator_method"].get(ind, {}).get(m, float("nan"))
            print(f"  {ind:14s}  {m:18s}  RMSE {rmse_m[ind][m] * 100:5.2f}%  cov {cov * 100:5.1f}%")
    return 0


if __name__ == "__main__":
    sys.exit(main())

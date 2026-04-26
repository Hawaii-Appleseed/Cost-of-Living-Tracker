"""Tests for the v3 cpi_diagnostics surface in HAT's grocery pipeline.

Verifies that:
* `AdjustedPrice.cpi_diagnostics` is None for legacy (v2) calls.
* When `adjust_prices` is called with a v3 BLS calibration, each output
  carries the κ source label, bias source label, and the final SE.
* Legacy callers (no `bls_calibration` kwarg) get back-compat behavior:
  cpi_diagnostics is None for non-projected paths.
"""
from __future__ import annotations

import math
import sys
from datetime import date
from pathlib import Path

import pytest

_GROCERY_ROOT = Path(__file__).resolve().parent.parent / "pipelines" / "grocery"
if str(_GROCERY_ROOT) not in sys.path:
    sys.path.insert(0, str(_GROCERY_ROOT))

from src.models import (  # noqa: E402
    BaselinePrice, BasketConfig, CPIConfig,
)
from src.price_adjuster import adjust_prices  # noqa: E402


# -----------------------------------------------------------------------------
# Fixtures
# -----------------------------------------------------------------------------

def _baseline_price(slot_id="apple_2lb", price=4.99) -> BaselinePrice:
    return BaselinePrice(
        slot_id=slot_id, chain="Foodland", store_id="01",
        county="Honolulu", geoid="15003",
        date="2020-01-01", product_name="apples",
        price=price, size_qty=2.0, size_unit="lb",
        per_unit_price=price / 2.0,
    )


def _cpi_config_one_cat(series_id: str = "CUUR0000SAF11") -> CPIConfig:
    """Minimal CPI config with one category that maps to a real BLS series."""
    return CPIConfig(categories={
        "food": {"series_id": series_id, "label": "Food at home"},
    })


def _basket_one_slot() -> BasketConfig:
    """Minimal basket config that maps slot_id → cpi_category."""
    return BasketConfig(items=[
        {"slot_id": "apple_2lb", "cpi_category": "food", "scale_factor": 1.0},
    ])


def _synth_monthly_cpi(series_id: str, n: int = 60, monthly_rate: float = 0.003,
                         noise_sd: float = 0.0015, seed: int = 1):
    """Build a synthetic monthly CPI series with log-normal noise so the
    projection's residual_log_std is positive and forecast_se is non-zero.
    """
    import math as _m
    import random as _r
    rng = _r.Random(seed)
    out = []
    y, m = 2020, 1
    value = 100.0
    for i in range(n):
        out.append({"year": y, "period": f"M{m:02d}", "value": value})
        # Apply both trend and noise; noise prevents residual_log_std=0.
        value *= (1.0 + monthly_rate) * _m.exp(rng.gauss(0, noise_sd))
        m += 1
        if m > 12:
            m = 1
            y += 1
    return {series_id: out}


# -----------------------------------------------------------------------------
# Test suite
# -----------------------------------------------------------------------------

class TestCpiDiagnosticsSurface:
    def test_no_calibration_diagnostics_unpopulated_for_unavailable(self):
        """No CPI data at all → method=unavailable; diagnostics None."""
        baseline = [_baseline_price()]
        cpi = {}  # empty
        cpi_config = _cpi_config_one_cat()
        basket = _basket_one_slot()
        adjusted, _ratios = adjust_prices(
            baseline, cpi, cpi_config, basket, target_date=date(2026, 1, 1),
        )
        assert len(adjusted) == 1
        # When ratio is unavailable, no projected SE → diagnostics None
        assert adjusted[0].cpi_diagnostics is None

    def test_v3_calibration_populates_diagnostics_on_projection(self):
        """When projecting forward and v3 calibration is provided, the
        AdjustedPrice gains a populated cpi_diagnostics dict."""
        baseline = [_baseline_price()]
        cpi = _synth_monthly_cpi("CUUR0000SAF11", n=48)
        cpi_config = _cpi_config_one_cat("CUUR0000SAF11")
        basket = _basket_one_slot()

        cal = {
            "vol_regime_thresholds": {"CUUR0000SAF11": 0.001},
            "strata_records": {
                "se_inflator": [{
                    "indicator": "", "method": "",
                    "pop_bucket": "*", "h_bucket": "*|*",
                    "value": 2.0, "n_folds": 1000,
                }],
                "bias": [{
                    "indicator": "", "method": "",
                    "pop_bucket": "*", "h_bucket": "*|*",
                    "value": 0.01, "n_folds": 1000,
                }],
            },
        }
        # target_date past the latest synthetic CPI obs → triggers projection
        adjusted, _ratios = adjust_prices(
            baseline, cpi, cpi_config, basket,
            target_date=date(2026, 1, 1),
            bls_calibration=cal,
        )
        assert len(adjusted) == 1
        diag = adjusted[0].cpi_diagnostics
        assert diag is not None
        # κ should be the global cell value (2.0), source label "global"
        assert diag["kappa_used"] == 2.0
        assert diag["kappa_source"] == "global"
        assert diag["bias_used"] == pytest.approx(0.01, rel=1e-9)
        assert diag["bias_source"] == "global"
        assert diag["forecast_se"] is not None and diag["forecast_se"] > 0
        assert diag["method"] == "projected"
        # CI bounds should be populated
        assert diag["ci90_low"] is not None
        assert diag["ci90_high"] is not None

    def test_v2_no_calibration_diagnostics_none_for_projection(self):
        """Legacy path with calibration=None: diagnostics surface still
        gets a dict (because forecast_se is non-None for projections),
        but kappa_used and bias_used are None."""
        baseline = [_baseline_price()]
        cpi = _synth_monthly_cpi("CUUR0000SAF11", n=48)
        cpi_config = _cpi_config_one_cat("CUUR0000SAF11")
        basket = _basket_one_slot()
        adjusted, _ratios = adjust_prices(
            baseline, cpi, cpi_config, basket,
            target_date=date(2026, 1, 1),
            bls_calibration=None,
        )
        assert len(adjusted) == 1
        diag = adjusted[0].cpi_diagnostics
        # forecast_se is populated by the legacy κ=1.50 path → diag exists
        assert diag is not None
        assert diag["kappa_used"] is None
        assert diag["bias_used"] is None
        assert diag["forecast_se"] is not None

    def test_back_compat_signature_still_works(self):
        """Legacy callers that don't pass `bls_calibration` get the same
        cpi_diagnostics behavior as if they had passed None."""
        baseline = [_baseline_price()]
        cpi = _synth_monthly_cpi("CUUR0000SAF11", n=48)
        cpi_config = _cpi_config_one_cat("CUUR0000SAF11")
        basket = _basket_one_slot()
        adjusted, _ratios = adjust_prices(
            baseline, cpi, cpi_config, basket,
            target_date=date(2026, 1, 1),
        )
        assert len(adjusted) == 1
        # Should still produce a result; cpi_ratio populated
        assert adjusted[0].cpi_ratio > 0

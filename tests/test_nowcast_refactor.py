"""Unit tests for the nowcasting structural refactor (Q-audit items 3/4/7/8).

Covers the new pure functions: the pass-through model, the $25 rounding, the
target-month extrapolation helper, and the string-field HTML patcher. These
feed the dashboard's published rent number, so they're the highest-trust
computations in the pipeline.
"""
import importlib.util
import sys
from pathlib import Path

_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(_ROOT))
_spec = importlib.util.spec_from_file_location("rpu", _ROOT / "redfin-price-updater.py")
_mod = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(_mod)

passthrough_rent_nowcast = _mod.passthrough_rent_nowcast
round_to_25 = _mod.round_to_25
extrapolate_ratio_to = _mod.extrapolate_ratio_to
patch_html = _mod.patch_html
_ym_of = _mod._ym_of
_months_ahead = _mod._months_ahead


class TestRoundTo25:
    def test_rounds_to_nearest_25(self):
        assert round_to_25(1753) == 1750
        assert round_to_25(1763) == 1775
        assert round_to_25(2012) == 2000
        assert round_to_25(2013) == 2025

    def test_none_passes_through(self):
        assert round_to_25(None) is None

    def test_already_multiple(self):
        assert round_to_25(1900) == 1900


class TestPassthrough:
    def test_lambda_zero_is_pure_cpi(self):
        r = passthrough_rent_nowcast(2000, cpi_factor=1.05, zori_factor=1.20, lam=0.0)
        assert r["passthrough"] == round(2000 * 1.05)

    def test_lambda_one_is_pure_zori(self):
        r = passthrough_rent_nowcast(2000, cpi_factor=1.05, zori_factor=1.20, lam=1.0)
        assert r["passthrough"] == round(2000 * 1.20)

    def test_half_is_geometric_mean(self):
        r = passthrough_rent_nowcast(2000, cpi_factor=1.0, zori_factor=4.0, lam=0.5)
        # 1.0^0.5 * 4.0^0.5 = 2.0
        assert r["passthrough"] == round(2000 * 2.0)

    def test_lambda_over_one_overshoots_both_legs(self):
        # The whole point of item 4: when asking (zori) outran realized (cpi),
        # λ>1 projects ABOVE the higher leg — a convex blend cannot.
        cpi_f, zori_f = 1.10, 1.16
        r = passthrough_rent_nowcast(1275, cpi_f, zori_f, lam=1.5)
        assert r["passthrough"] > round(1275 * zori_f)  # exceeds the larger leg

    def test_components_reported(self):
        r = passthrough_rent_nowcast(2000, 1.05, 1.20, lam=0.65)
        assert r["cpi_scaled"] == round(2000 * 1.05)
        assert r["zori_implied"] == round(2000 * 1.20)
        assert r["lambda"] == 0.65


class TestExtrapolate:
    def _pts(self, vals, start_month=1, year=2026):
        # ascending {year, period:'MNN', value}
        return [{"year": year, "period": f"M{start_month + i:02d}", "value": v}
                for i, v in enumerate(vals)]

    def test_target_at_latest_returns_latest_over_anchor(self):
        pts = self._pts([100, 101, 102])  # latest = 102, at M03
        r = extrapolate_ratio_to(pts, anchor_avg=100.0, target_ym=(2026, 3))
        assert abs(r - 1.02) < 1e-9

    def test_target_before_latest_uses_latest(self):
        pts = self._pts([100, 101, 102])
        r = extrapolate_ratio_to(pts, anchor_avg=100.0, target_ym=(2026, 1))
        assert abs(r - 1.02) < 1e-9  # never goes backwards

    def test_forward_extrapolation_rises_for_uptrend(self):
        pts = self._pts([100, 102, 104])  # ~+2/mo uptrend, latest M03
        at_latest = extrapolate_ratio_to(pts, 100.0, (2026, 3))
        ahead = extrapolate_ratio_to(pts, 100.0, (2026, 5))  # 2 months beyond
        assert ahead > at_latest  # projected upward

    def test_empty_or_zero_anchor_returns_none(self):
        assert extrapolate_ratio_to([], 100.0, (2026, 5)) is None
        assert extrapolate_ratio_to(self._pts([100]), 0.0, (2026, 5)) is None


class TestYmHelpers:
    def test_ym_of(self):
        assert _ym_of("2026-05") == (2026, 5)

    def test_months_ahead(self):
        assert _months_ahead((2026, 4), (2026, 5)) == 1
        assert _months_ahead((2026, 5), (2026, 4)) == -1
        assert _months_ahead((2025, 12), (2026, 1)) == 1


class TestStringFieldPatch:
    STUB = ('  Honolulu: { income:129300, rent:2000, '
            'bedroomRent:{br0:1458,br1:1605}, rentMethod:"cpi+zori", rentAsOf:"2026-01" },\n')

    def test_string_field_after_bedroomrent_is_patched(self):
        # Regression: the field sits AFTER the bedroomRent `}` so the old
        # `[^}]*` capture couldn't reach it.
        out, misses = patch_html(self.STUB, {"Honolulu": {"rentMethod": "passthrough",
                                                          "rentAsOf": "2026-05"}})
        assert misses == []
        assert 'rentMethod:"passthrough"' in out
        assert 'rentAsOf:"2026-05"' in out

    def test_missing_stub_is_reported_as_miss(self):
        no_stub = '  Maui: { income:110900, rent:1900, bedroomRent:{br0:1} },\n'
        out, misses = patch_html(no_stub, {"Maui": {"rentMethod": "passthrough"}})
        assert "Maui.rentMethod" in misses

    def test_int_field_still_works(self):
        out, misses = patch_html(self.STUB, {"Honolulu": {"rent": 2025}})
        assert "rent:2025" in out

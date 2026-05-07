"""Pure-function tests for HR-zone classification and DFA artifact guards.

These tests don't import Home Assistant — only the standalone helpers in
coordinator.py — so they can run with `pytest tests/` without an HA setup.
"""
from __future__ import annotations

import sys
from pathlib import Path

import numpy as np
import pytest

# Allow import without installing as a package.
sys.path.insert(
    0, str(Path(__file__).resolve().parents[1] / "custom_components")
)
from ble_heart_rate.coordinator import (  # noqa: E402
    DFA_MAX_PLAUSIBLE_ALPHA,
    DFA_MIN_BEATS,
    DFA_MIN_RR_STD_MS,
    classify_hr_zone,
    compute_dfa_alpha1,
)


class TestClassifyHrZone:
    """Karvonen %HRR thresholds (60 / 75 / 90)."""

    HRMAX = 173
    HRREST = 55  # HRR = 118

    def test_below_60pct_is_recovery(self):
        # 60% = 55 + 0.60·118 = 125.8 → 125 still recovery
        assert classify_hr_zone(125, self.HRMAX, self.HRREST) == "recovery"

    def test_60_to_75pct_is_aerobic(self):
        # 60% boundary → aerobic; 75% = 55 + 0.75·118 = 143.5
        assert classify_hr_zone(126, self.HRMAX, self.HRREST) == "aerobic"
        assert classify_hr_zone(143, self.HRMAX, self.HRREST) == "aerobic"

    def test_75_to_90pct_is_threshold(self):
        # 90% = 55 + 0.90·118 = 161.2
        assert classify_hr_zone(144, self.HRMAX, self.HRREST) == "threshold"
        assert classify_hr_zone(161, self.HRMAX, self.HRREST) == "threshold"

    def test_above_90pct_is_anaerobic(self):
        assert classify_hr_zone(162, self.HRMAX, self.HRREST) == "anaerobic"
        assert classify_hr_zone(173, self.HRMAX, self.HRREST) == "anaerobic"

    def test_replays_yesterday_outliers_correctly(self):
        # The misclassifications that motivated this rewrite must come out
        # right under the new HR-based zones.
        assert classify_hr_zone(153, self.HRMAX, self.HRREST) == "threshold"
        assert classify_hr_zone(156, self.HRMAX, self.HRREST) == "threshold"
        assert classify_hr_zone(158, self.HRMAX, self.HRREST) == "threshold"

    def test_none_hr_returns_none(self):
        assert classify_hr_zone(None, self.HRMAX, self.HRREST) is None

    def test_falls_back_to_pct_hrmax_when_hrrest_unset(self):
        # Without HRrest: 173·0.60=103.8, 173·0.75=129.75, 173·0.90=155.7
        assert classify_hr_zone(103, self.HRMAX, None) == "recovery"
        assert classify_hr_zone(104, self.HRMAX, None) == "aerobic"
        assert classify_hr_zone(155, self.HRMAX, None) == "threshold"
        assert classify_hr_zone(156, self.HRMAX, None) == "anaerobic"

    def test_invalid_config_returns_none(self):
        assert classify_hr_zone(150, 0, self.HRREST) is None
        assert classify_hr_zone(150, 100, 100) is None  # reserve=0
        assert classify_hr_zone(150, 100, 120) is None  # rest > max


class TestDfaAlpha1Guards:
    """Guards against the flat-signal Brownian-noise failure mode."""

    @staticmethod
    def _physiological_rr(n: int, mean_ms: float, std_ms: float) -> list[float]:
        rng = np.random.default_rng(seed=42)
        return list(rng.normal(mean_ms, std_ms, n))

    def test_short_window_returns_none(self):
        rr = self._physiological_rr(DFA_MIN_BEATS - 1, 600.0, 30.0)
        assert compute_dfa_alpha1(rr) is None

    def test_flat_signal_returns_none(self):
        # σ(RR) below the guard → must reject. This is the regression test
        # for the "153 bpm classified as recovery" bug.
        rr = self._physiological_rr(120, 400.0, DFA_MIN_RR_STD_MS - 1.0)
        assert compute_dfa_alpha1(rr) is None

    def test_brownian_artifact_returns_none(self):
        # Construct a series that yields α1 well above DFA_MAX_PLAUSIBLE_ALPHA:
        # cumulative sums of low-amplitude noise → near-Brownian trajectory.
        rng = np.random.default_rng(seed=7)
        # Use small-amplitude integrated noise as RR pattern; std is fine but
        # the integrated structure pushes α1 toward 1.5.
        steps = rng.normal(0.0, 8.0, 200)
        rr = list(400.0 + np.cumsum(steps))
        result = compute_dfa_alpha1(rr)
        # Either rejected (None) or, if computed, must be ≤ guard ceiling.
        assert result is None or result <= DFA_MAX_PLAUSIBLE_ALPHA

    def test_normal_resting_rr_returns_value_near_one(self):
        # Healthy rest: α1 ≈ 1.0. This sanity-checks we didn't over-guard.
        rng = np.random.default_rng(seed=1)
        # 1/f-ish synthesis: AR(1) with high autocorrelation produces α1 ≈ 1.
        n = 200
        x = np.zeros(n)
        for i in range(1, n):
            x[i] = 0.9 * x[i - 1] + rng.normal(0.0, 10.0)
        rr = list(900.0 + x)
        result = compute_dfa_alpha1(rr)
        assert result is not None
        assert 0.6 <= result <= DFA_MAX_PLAUSIBLE_ALPHA


if __name__ == "__main__":
    pytest.main([__file__, "-v"])

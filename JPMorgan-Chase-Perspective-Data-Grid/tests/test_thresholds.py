"""Unit tests for the rolling threshold machinery."""

from __future__ import annotations

import pytest

from jpm_perspective_grid.core.errors import AggregationError
from jpm_perspective_grid.core.thresholds import (
    PriceBaseline,
    RollingRatioTracker,
    ThresholdPolicy,
    mean,
    ratios,
    sample_stdev,
)


class TestThresholdPolicy:
    def test_defaults_are_valid(self):
        policy = ThresholdPolicy()
        assert policy.window_size == 20
        assert policy.sigma_multiplier == 3.0
        assert policy.min_half_width == 0.005

    def test_window_size_must_be_at_least_two(self):
        with pytest.raises(AggregationError):
            ThresholdPolicy(window_size=1)

    def test_window_size_must_be_positive(self):
        with pytest.raises(AggregationError):
            ThresholdPolicy(window_size=0)

    def test_sigma_multiplier_must_be_non_negative(self):
        with pytest.raises(AggregationError):
            ThresholdPolicy(sigma_multiplier=-1.0)

    def test_sigma_multiplier_must_be_finite(self):
        with pytest.raises(AggregationError):
            ThresholdPolicy(sigma_multiplier=float("nan"))

    def test_min_half_width_must_be_non_negative(self):
        with pytest.raises(AggregationError):
            ThresholdPolicy(min_half_width=-0.1)

    def test_min_half_width_must_be_finite(self):
        with pytest.raises(AggregationError):
            ThresholdPolicy(min_half_width=float("inf"))


class TestRollingRatioTracker:
    def test_first_observation_centres_the_band(self):
        tracker = RollingRatioTracker(ThresholdPolicy(window_size=5, min_half_width=0.01))
        band = tracker.update(1.0)
        assert band.center == pytest.approx(1.0)
        assert band.lower_bound == pytest.approx(0.99)
        assert band.upper_bound == pytest.approx(1.01)
        assert band.sigma == 0.0

    def test_first_observation_never_triggers(self):
        tracker = RollingRatioTracker(ThresholdPolicy(window_size=5, min_half_width=0.01))
        band = tracker.update(1.0)
        assert not band.breaches(1.0)

    def test_band_uses_history_only(self):
        """The band must be computed from prior observations, not from the
        value being evaluated (causality)."""
        tracker = RollingRatioTracker(ThresholdPolicy(window_size=5, min_half_width=0.0))
        tracker.update(1.0)
        band = tracker.update(5.0)
        assert band.center == pytest.approx(1.0)
        assert band.samples == 2

    def test_history_is_updated_after_the_band(self):
        tracker = RollingRatioTracker(ThresholdPolicy(window_size=5))
        tracker.update(1.0)
        assert tracker.history() == [1.0]
        tracker.update(2.0)
        assert tracker.history() == [1.0, 2.0]

    def test_window_is_bounded(self):
        tracker = RollingRatioTracker(ThresholdPolicy(window_size=3))
        for value in (1.0, 2.0, 3.0, 4.0):
            tracker.update(value)
        assert tracker.samples == 3
        assert tracker.history() == [2.0, 3.0, 4.0]

    def test_dispersion_widens_the_band(self):
        policy = ThresholdPolicy(window_size=10, sigma_multiplier=2.0, min_half_width=0.0)
        tracker = RollingRatioTracker(policy)
        tracker.update(1.0)
        tracker.update(3.0)
        band = tracker.update(2.0)
        # history is [1.0, 3.0]: mean 2.0, sample stdev ~1.414
        assert band.center == pytest.approx(2.0)
        assert band.sigma == pytest.approx(2.0**0.5)
        assert band.half_width == pytest.approx(2.0 * 2.0**0.5)

    def test_min_half_width_is_applied(self):
        tracker = RollingRatioTracker(ThresholdPolicy(window_size=10, min_half_width=0.5))
        band = tracker.update(1.0)
        assert band.half_width == pytest.approx(0.5)

    def test_zero_dispersion_still_yields_a_usable_band(self):
        tracker = RollingRatioTracker(ThresholdPolicy(window_size=10, min_half_width=0.02))
        for _ in range(5):
            band = tracker.update(1.0)
        assert band.sigma == pytest.approx(0.0)
        assert band.half_width == pytest.approx(0.02)

    def test_non_finite_value_is_rejected(self):
        tracker = RollingRatioTracker()
        with pytest.raises(AggregationError):
            tracker.update(float("nan"))
        with pytest.raises(AggregationError):
            tracker.update(float("inf"))

    def test_reset_clears_history(self):
        tracker = RollingRatioTracker()
        tracker.update(1.0)
        tracker.reset()
        assert tracker.samples == 0
        assert tracker.history() == []

    def test_policy_is_exposed(self):
        policy = ThresholdPolicy(window_size=7)
        assert RollingRatioTracker(policy).policy is policy


class TestPriceBaseline:
    def test_first_price_is_the_baseline(self):
        baseline = PriceBaseline(window_size=3)
        assert baseline.update(100.0) == pytest.approx(100.0)

    def test_mean_of_window(self):
        baseline = PriceBaseline(window_size=3)
        baseline.update(100.0)
        baseline.update(110.0)
        assert baseline.update(120.0) == pytest.approx(110.0)

    def test_window_evicts_old_values(self):
        baseline = PriceBaseline(window_size=2)
        baseline.update(100.0)
        baseline.update(110.0)
        assert baseline.update(120.0) == pytest.approx(115.0)
        assert baseline.samples == 2

    def test_window_size_must_be_positive(self):
        with pytest.raises(AggregationError):
            PriceBaseline(window_size=0)

    def test_non_positive_price_is_rejected(self):
        baseline = PriceBaseline()
        with pytest.raises(AggregationError):
            baseline.update(0.0)
        with pytest.raises(AggregationError):
            baseline.update(-1.0)

    def test_non_finite_price_is_rejected(self):
        baseline = PriceBaseline()
        with pytest.raises(AggregationError):
            baseline.update(float("nan"))

    def test_reset(self):
        baseline = PriceBaseline()
        baseline.update(100.0)
        baseline.reset()
        assert baseline.samples == 0


class TestRatios:
    def test_element_wise(self):
        assert ratios([10.0, 20.0], [5.0, 4.0]) == [2.0, 5.0]

    def test_zero_denominator_is_skipped(self):
        assert ratios([10.0, 20.0], [0.0, 4.0]) == [5.0]

    def test_different_lengths_are_truncated(self):
        assert ratios([10.0, 20.0], [5.0]) == [2.0]

    def test_empty_inputs(self):
        assert ratios([], []) == []


class TestNumericalAccuracy:
    """The float-native helpers must agree with the exact stdlib results."""

    @pytest.mark.parametrize(
        "values",
        [
            [1.0, 2.0],
            [1.0, 1.0, 1.0],
            [1.0, 2.0, 3.0, 4.0],
            [10.5, -3.25, 0.0, 7.125, 99.999],
            [0.1] * 25,
        ],
    )
    def test_sample_stdev_matches_the_exact_implementation(self, values):
        import statistics

        assert sample_stdev(values) == pytest.approx(
            statistics.stdev(values), rel=1e-9, abs=1e-12
        )

    @pytest.mark.parametrize(
        "values",
        [[1.0], [1.0, 2.0], [1.0, 2.0, 3.0], [5.0, 5.5, 5.25, 5.125]],
    )
    def test_mean_matches_the_exact_implementation(self, values):
        import statistics

        assert mean(values) == pytest.approx(statistics.fmean(values), rel=1e-12)

    def test_mean_of_an_empty_sequence_is_rejected(self):
        with pytest.raises(AggregationError):
            mean([])

    def test_stdev_of_a_single_observation_is_zero(self):
        assert sample_stdev([3.0]) == 0.0

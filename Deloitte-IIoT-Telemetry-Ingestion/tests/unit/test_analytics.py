"""Unit tests for the statistical analytics layer."""

from __future__ import annotations

from datetime import timedelta

import pytest

from iiot_telemetry.application.analytics import (
    DropoutDetector,
    HealthScorerConfig,
    MachineHealthScorer,
    MovingAverage,
    MovingAverageConfig,
    SigmaAnomalyDetector,
    SigmaDetectorConfig,
    group_by_sensor,
    moving_average_series,
)
from iiot_telemetry.domain.exceptions import AnalyticsError
from iiot_telemetry.domain.models import AnomalyFlag, SensorType, Severity


class TestMovingAverage:
    """Behaviour of the trailing moving average."""

    def test_average_of_first_value(self, moving_average: MovingAverage) -> None:
        assert moving_average.update(10.0) == 10.0

    def test_average_over_window(self, moving_average: MovingAverage) -> None:
        moving_average.update(10.0)
        moving_average.update(20.0)
        assert moving_average.update(30.0) == 20.0

    def test_window_slides(self, moving_average: MovingAverage) -> None:
        for value in (10.0, 20.0, 30.0):
            moving_average.update(value)
        assert moving_average.update(40.0) == 25.0

    def test_count_reflects_window_size(self, moving_average: MovingAverage) -> None:
        for value in range(10):
            moving_average.update(float(value))
        assert moving_average.count == 5

    def test_average_of_empty_window_is_zero(self) -> None:
        assert MovingAverage(MovingAverageConfig(window=3)).average == 0.0

    def test_ready_requires_min_samples(self) -> None:
        tracker = MovingAverage(MovingAverageConfig(window=5, min_samples=3))
        tracker.update(1.0)
        tracker.update(2.0)
        assert tracker.ready is False
        tracker.update(3.0)
        assert tracker.ready is True

    def test_reset_clears_window(self, moving_average: MovingAverage) -> None:
        moving_average.update(10.0)
        moving_average.reset()
        assert moving_average.count == 0

    def test_invalid_window_raises(self) -> None:
        with pytest.raises(AnalyticsError):
            MovingAverageConfig(window=0)

    def test_invalid_min_samples_raises(self) -> None:
        with pytest.raises(AnalyticsError):
            MovingAverageConfig(window=5, min_samples=0)

    def test_min_samples_above_window_raises(self) -> None:
        with pytest.raises(AnalyticsError):
            MovingAverageConfig(window=3, min_samples=5)

    def test_moving_average_series(self, make_reading) -> None:
        readings = [make_reading(value=v) for v in (10.0, 20.0, 30.0)]
        assert moving_average_series(readings, window=2) == [10.0, 15.0, 25.0]


class TestSigmaAnomalyDetector:
    """Behaviour of the 3-sigma anomaly detector."""

    def test_no_anomaly_before_baseline_is_ready(
        self, detector: SigmaAnomalyDetector, make_reading
    ) -> None:
        for i in range(3):
            assert detector.evaluate(make_reading(value=100.0, offset_seconds=i)) is None

    def test_anomaly_is_detected_above_threshold(
        self, detector: SigmaAnomalyDetector, make_reading
    ) -> None:
        for i in range(10):
            detector.evaluate(make_reading(value=100.0, offset_seconds=i))
        flag = detector.evaluate(make_reading(value=150.0, offset_seconds=10))
        assert flag is not None
        assert flag.z_score > 3.0
        assert flag.baseline == pytest.approx(100.0)

    def test_anomaly_uses_the_previous_baseline_only(
        self, detector: SigmaAnomalyDetector, make_reading
    ) -> None:
        for i in range(10):
            detector.evaluate(make_reading(value=100.0, offset_seconds=i))
        flag = detector.evaluate(make_reading(value=200.0, offset_seconds=10))
        assert flag is not None
        # The triggering reading must not have polluted the baseline.
        assert flag.baseline == pytest.approx(100.0)
        assert flag.std_dev == pytest.approx(0.0)

    def test_steady_values_are_not_flagged(
        self, detector: SigmaAnomalyDetector, make_reading
    ) -> None:
        for i in range(20):
            assert detector.evaluate(make_reading(value=100.0, offset_seconds=i)) is None

    def test_vibration_is_ignored_by_default(
        self, detector: SigmaAnomalyDetector, make_reading
    ) -> None:
        for i in range(10):
            detector.evaluate(
                make_reading(value=100.0, sensor_type=SensorType.VIBRATION, offset_seconds=i)
            )
        flag = detector.evaluate(
            make_reading(value=999.0, sensor_type=SensorType.VIBRATION, offset_seconds=10)
        )
        assert flag is None

    def test_error_code_is_ignored_by_default(
        self, detector: SigmaAnomalyDetector, make_reading
    ) -> None:
        for i in range(10):
            detector.evaluate(
                make_reading(value=0.0, sensor_type=SensorType.ERROR_CODE, offset_seconds=i)
            )
        flag = detector.evaluate(
            make_reading(value=500.0, sensor_type=SensorType.ERROR_CODE, offset_seconds=10)
        )
        assert flag is None

    def test_vibration_can_be_enabled(self, make_reading) -> None:
        detector = SigmaAnomalyDetector(
            SigmaDetectorConfig(
                baseline_window=20,
                min_baseline_samples=5,
                sensor_types=(SensorType.TEMPERATURE, SensorType.VIBRATION),
            )
        )
        for i in range(10):
            detector.evaluate(
                make_reading(value=10.0, sensor_type=SensorType.VIBRATION, offset_seconds=i)
            )
        flag = detector.evaluate(
            make_reading(value=50.0, sensor_type=SensorType.VIBRATION, offset_seconds=10)
        )
        assert flag is not None

    def test_baselines_are_isolated_per_sensor(
        self, detector: SigmaAnomalyDetector, make_reading
    ) -> None:
        for i in range(10):
            detector.evaluate(make_reading(value=100.0, sensor_id="TEMP-01", offset_seconds=i))
        # A different sensor has no baseline yet, so no anomaly is reported.
        flag = detector.evaluate(
            make_reading(value=999.0, sensor_id="TEMP-02", offset_seconds=10)
        )
        assert flag is None

    def test_baselines_are_isolated_per_machine(
        self, detector: SigmaAnomalyDetector, make_reading
    ) -> None:
        for i in range(10):
            detector.evaluate(make_reading(value=100.0, machine_id="PRESS-01", offset_seconds=i))
        flag = detector.evaluate(
            make_reading(value=999.0, machine_id="PRESS-02", offset_seconds=10)
        )
        assert flag is None

    @pytest.mark.parametrize(
        ("z_score", "expected"),
        [
            (3.5, Severity.INFO),
            (5.0, Severity.WARNING),
            (7.0, Severity.CRITICAL),
        ],
    )
    def test_severity_bands(self, make_reading, z_score: float, expected: Severity) -> None:
        detector = SigmaAnomalyDetector(
            SigmaDetectorConfig(baseline_window=20, min_baseline_samples=2)
        )
        # Baseline of [100.0, 101.0] => mean 100.5, population std dev 0.5.
        detector.evaluate(make_reading(value=100.0, offset_seconds=0))
        detector.evaluate(make_reading(value=101.0, offset_seconds=1))
        flag = detector.evaluate(make_reading(value=100.5 + z_score * 0.5, offset_seconds=2))
        assert flag is not None
        assert flag.z_score == pytest.approx(z_score)
        assert flag.severity is expected

    def test_baseline_for_returns_statistics(
        self, detector: SigmaAnomalyDetector, make_reading
    ) -> None:
        reading = make_reading(value=100.0)
        assert detector.baseline_for(reading) == (0.0, 0.0)
        detector.evaluate(reading)
        mean, std = detector.baseline_for(reading)
        assert mean == pytest.approx(100.0)
        assert std == pytest.approx(0.0)

    def test_reset_clears_baselines(
        self, detector: SigmaAnomalyDetector, make_reading
    ) -> None:
        detector.evaluate(make_reading(value=100.0))
        detector.reset()
        assert detector.baseline_for(make_reading(value=100.0)) == (0.0, 0.0)

    def test_anomaly_to_dict(self, detector: SigmaAnomalyDetector, make_reading) -> None:
        for i in range(10):
            detector.evaluate(make_reading(value=100.0, offset_seconds=i))
        flag = detector.evaluate(make_reading(value=150.0, offset_seconds=10))
        assert flag is not None
        payload = flag.to_dict()
        assert payload["severity"] in {"info", "warning", "critical"}
        assert payload["sensor_id"] == "TEMP-01"
        assert "z_score" in payload

    def test_rule_name_is_reported(self, detector: SigmaAnomalyDetector, make_reading) -> None:
        for i in range(10):
            detector.evaluate(make_reading(value=100.0, offset_seconds=i))
        flag = detector.evaluate(make_reading(value=150.0, offset_seconds=10))
        assert flag is not None
        assert flag.rule == "sigma_3"

    def test_invalid_sigma_threshold_raises(self) -> None:
        with pytest.raises(AnalyticsError):
            SigmaDetectorConfig(sigma_threshold=0)

    def test_invalid_baseline_window_raises(self) -> None:
        with pytest.raises(AnalyticsError):
            SigmaDetectorConfig(baseline_window=1)

    def test_invalid_min_baseline_samples_raises(self) -> None:
        with pytest.raises(AnalyticsError):
            SigmaDetectorConfig(min_baseline_samples=1)

    def test_min_samples_above_window_raises(self) -> None:
        with pytest.raises(AnalyticsError):
            SigmaDetectorConfig(baseline_window=5, min_baseline_samples=10)


class TestMachineHealthScorer:
    """Behaviour of the machine health score."""

    def test_unknown_machine_scores_zero(self) -> None:
        scorer = MachineHealthScorer()
        score = scorer.score("UNKNOWN")
        assert score.score == 0.0
        assert score.status == "unknown"
        assert score.reading_count == 0

    def test_healthy_machine_scores_100(self, make_reading) -> None:
        scorer = MachineHealthScorer()
        for i in range(10):
            scorer.observe(make_reading(value=100.0, offset_seconds=i))
        score = scorer.score("PRESS-01")
        assert score.score == 100.0
        assert score.status == "healthy"

    def test_error_codes_reduce_the_score(self, make_reading) -> None:
        scorer = MachineHealthScorer()
        for i in range(10):
            scorer.observe(
                make_reading(value=404.0, sensor_type=SensorType.ERROR_CODE, offset_seconds=i)
            )
        score = scorer.score("PRESS-01")
        assert score.score < 100.0
        assert score.status in {"degraded", "critical"}

    def test_zero_error_code_is_not_penalized(self, make_reading) -> None:
        scorer = MachineHealthScorer()
        for i in range(10):
            scorer.observe(
                make_reading(value=0.0, sensor_type=SensorType.ERROR_CODE, offset_seconds=i)
            )
        assert scorer.score("PRESS-01").score == 100.0

    def test_anomalies_reduce_the_score(self, detector: SigmaAnomalyDetector, make_reading) -> None:
        scorer = MachineHealthScorer()
        for i in range(10):
            reading = make_reading(value=100.0, offset_seconds=i)
            scorer.observe(reading)
            flag = detector.evaluate(reading)
            if flag is not None:
                scorer.observe_anomaly(flag)
        assert scorer.score("PRESS-01").anomaly_count == 0

    def test_observed_anomaly_reduces_the_score(self, make_reading) -> None:
        scorer = MachineHealthScorer()
        for i in range(10):
            scorer.observe(make_reading(value=100.0, offset_seconds=i))
        flag = AnomalyFlag(
            reading=make_reading(value=500.0),
            baseline=100.0,
            std_dev=1.0,
            z_score=400.0,
            moving_average=100.0,
            severity=Severity.CRITICAL,
            rule="sigma_3",
        )
        scorer.observe_anomaly(flag)
        score = scorer.score("PRESS-01")
        assert score.anomaly_count == 1
        assert score.score < 100.0

    def test_dropouts_reduce_the_score(
        self, health_scorer_config: HealthScorerConfig, make_reading
    ) -> None:
        from iiot_telemetry.domain.models import DropoutEvent, Timestamp

        scorer = MachineHealthScorer(health_scorer_config)
        scorer.observe(make_reading(value=100.0))
        scorer.observe_dropout(
            DropoutEvent(
                machine_id="PRESS-01",
                sensor_id="TEMP-01",
                sensor_type=SensorType.TEMPERATURE,
                last_seen=Timestamp(make_reading().timestamp.value),
                next_seen=Timestamp(make_reading().timestamp.value + timedelta(seconds=600)),
                gap_seconds=600.0,
            )
        )
        score = scorer.score("PRESS-01")
        assert score.dropout_count == 1
        assert score.score < 100.0

    def test_scores_are_ordered_by_machine_id(self, make_reading) -> None:
        scorer = MachineHealthScorer()
        scorer.observe(make_reading(machine_id="PRESS-02"))
        scorer.observe(make_reading(machine_id="PRESS-01"))
        assert [s.machine_id for s in scorer.scores()] == ["PRESS-01", "PRESS-02"]

    def test_score_to_dict(self, make_reading) -> None:
        scorer = MachineHealthScorer()
        scorer.observe(make_reading())
        payload = scorer.score("PRESS-01").to_dict()
        assert payload["machine_id"] == "PRESS-01"
        assert "factors" in payload

    def test_status_degraded_band(self, make_reading) -> None:
        # 10 readings, 5 of them error codes => error ratio 0.5 => penalty 30
        # => score 70, which falls into the degraded band [50, 80).
        scorer = MachineHealthScorer(HealthScorerConfig(error_weight=60.0))
        for i in range(10):
            value = 404.0 if i % 2 == 0 else 0.0
            scorer.observe(
                make_reading(value=value, sensor_type=SensorType.ERROR_CODE, offset_seconds=i)
            )
        score = scorer.score("PRESS-01")
        assert score.score == pytest.approx(70.0)
        assert score.status == "degraded"

    def test_status_critical_band(self, make_reading) -> None:
        scorer = MachineHealthScorer(HealthScorerConfig(error_weight=100.0))
        for i in range(10):
            scorer.observe(
                make_reading(value=404.0, sensor_type=SensorType.ERROR_CODE, offset_seconds=i)
            )
        assert scorer.score("PRESS-01").status == "critical"


class TestDropoutDetector:
    """Behaviour of the sensor dropout detector."""

    def test_no_dropout_for_the_first_reading(
        self, health_scorer_config: HealthScorerConfig, make_reading
    ) -> None:
        detector = DropoutDetector(health_scorer_config)
        assert detector.observe(make_reading(offset_seconds=0)) is None

    def test_no_dropout_within_the_expected_interval(
        self, health_scorer_config: HealthScorerConfig, make_reading
    ) -> None:
        detector = DropoutDetector(health_scorer_config)
        detector.observe(make_reading(offset_seconds=0))
        assert detector.observe(make_reading(offset_seconds=60)) is None

    def test_dropout_detected_beyond_the_gap_factor(
        self, health_scorer_config: HealthScorerConfig, make_reading
    ) -> None:
        detector = DropoutDetector(health_scorer_config)
        detector.observe(make_reading(offset_seconds=0))
        event = detector.observe(make_reading(offset_seconds=600))
        assert event is not None
        assert event.gap_seconds == pytest.approx(600.0)

    def test_dropout_is_isolated_per_sensor(
        self, health_scorer_config: HealthScorerConfig, make_reading
    ) -> None:
        detector = DropoutDetector(health_scorer_config)
        detector.observe(make_reading(sensor_id="TEMP-01", offset_seconds=0))
        assert detector.observe(make_reading(sensor_id="TEMP-02", offset_seconds=600)) is None

    def test_out_of_order_reading_is_not_a_dropout(
        self, health_scorer_config: HealthScorerConfig, make_reading
    ) -> None:
        detector = DropoutDetector(health_scorer_config)
        detector.observe(make_reading(offset_seconds=600))
        assert detector.observe(make_reading(offset_seconds=0)) is None

    def test_dropout_to_dict(
        self, health_scorer_config: HealthScorerConfig, make_reading
    ) -> None:
        detector = DropoutDetector(health_scorer_config)
        detector.observe(make_reading(offset_seconds=0))
        event = detector.observe(make_reading(offset_seconds=600))
        assert event is not None
        payload = event.to_dict()
        assert payload["gap_seconds"] == pytest.approx(600.0)
        assert "last_seen" in payload

    def test_reset_clears_state(
        self, health_scorer_config: HealthScorerConfig, make_reading
    ) -> None:
        detector = DropoutDetector(health_scorer_config)
        detector.observe(make_reading(offset_seconds=0))
        detector.reset()
        assert detector.observe(make_reading(offset_seconds=600)) is None


class TestGrouping:
    """Grouping helpers."""

    def test_group_by_sensor(self, make_reading) -> None:
        readings = [
            make_reading(sensor_id="A", offset_seconds=0),
            make_reading(sensor_id="B", offset_seconds=1),
            make_reading(sensor_id="A", offset_seconds=2),
        ]
        grouped = group_by_sensor(readings)
        assert len(grouped[("PRESS-01", "A")]) == 2
        assert len(grouped[("PRESS-01", "B")]) == 1

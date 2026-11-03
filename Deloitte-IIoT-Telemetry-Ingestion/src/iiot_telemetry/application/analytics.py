"""Statistical analytics over normalized telemetry.

Three capabilities are provided, each in its own focused class:

* :class:`MovingAverage` - trailing simple moving average over a fixed window.
* :class:`SigmaAnomalyDetector` - z-score detection against a rolling
  per-sensor baseline (temperature > 3 sigma above baseline by default).
* :class:`MachineHealthScorer` - composite 0-100 health score per machine.

All classes are streaming-friendly: they accept readings one at a time and
keep bounded internal state (deques), so memory does not grow with volume.
"""

from __future__ import annotations

import math
from collections import deque
from dataclasses import dataclass, field
from typing import Deque, Iterable, Mapping, Sequence

from ..domain.exceptions import AnalyticsError
from ..domain.models import (
    AnomalyFlag,
    DropoutEvent,
    HealthScore,
    SensorReading,
    SensorType,
    Severity,
)


@dataclass(frozen=True, slots=True)
class MovingAverageConfig:
    """Configuration of the trailing moving average."""

    window: int = 5
    min_samples: int = 1

    def __post_init__(self) -> None:
        if self.window < 1:
            raise AnalyticsError("moving average window must be >= 1")
        if self.min_samples < 1:
            raise AnalyticsError("min_samples must be >= 1")
        if self.min_samples > self.window:
            raise AnalyticsError("min_samples cannot exceed window")


class MovingAverage:
    """Trailing simple moving average over a bounded window.

    Examples
    --------
    >>> ma = MovingAverage(MovingAverageConfig(window=3))
    >>> ma.update(10.0), ma.update(20.0), ma.update(30.0)
    (10.0, 15.0, 20.0)
    """

    def __init__(self, config: MovingAverageConfig | None = None) -> None:
        self.config = config or MovingAverageConfig()
        self._values: Deque[float] = deque(maxlen=self.config.window)

    def update(self, value: float) -> float:
        """Push ``value`` into the window and return the new average."""
        self._values.append(float(value))
        return self.average

    @property
    def average(self) -> float:
        """Current average, or ``0.0`` when the window is empty."""
        if not self._values:
            return 0.0
        return sum(self._values) / len(self._values)

    @property
    def count(self) -> int:
        """Number of samples currently held in the window."""
        return len(self._values)

    @property
    def ready(self) -> bool:
        """Whether enough samples have been collected to trust the average."""
        return self.count >= self.config.min_samples

    def reset(self) -> None:
        """Clear the internal window."""
        self._values.clear()


@dataclass(frozen=True, slots=True)
class SigmaDetectorConfig:
    """Configuration of the sigma-based anomaly detector."""

    sigma_threshold: float = 3.0
    baseline_window: int = 50
    min_baseline_samples: int = 10
    min_std_dev: float = 1e-9
    absolute_min_delta: float = 0.0
    sensor_types: tuple[SensorType, ...] = (SensorType.TEMPERATURE,)

    def __post_init__(self) -> None:
        if self.sigma_threshold <= 0:
            raise AnalyticsError("sigma_threshold must be positive")
        if self.baseline_window < 2:
            raise AnalyticsError("baseline_window must be >= 2")
        if self.min_baseline_samples < 2:
            raise AnalyticsError("min_baseline_samples must be >= 2")
        if self.min_baseline_samples > self.baseline_window:
            raise AnalyticsError("min_baseline_samples cannot exceed baseline_window")


@dataclass
class _SensorBaseline:
    """Rolling baseline statistics for a single sensor stream."""

    values: Deque[float] = field(default_factory=deque)

    def mean(self) -> float:
        return sum(self.values) / len(self.values)

    def std_dev(self) -> float:
        """Population standard deviation of the baseline window."""
        if len(self.values) < 2:
            return 0.0
        mean = self.mean()
        variance = sum((v - mean) ** 2 for v in self.values) / len(self.values)
        return math.sqrt(variance)


class SigmaAnomalyDetector:
    """Detects statistical anomalies using a rolling per-sensor baseline.

    For every reading the detector maintains a bounded window of previous
    values for that sensor. Once the window holds at least
    ``min_baseline_samples`` points, the reading's z-score is computed against
    that baseline and compared against ``sigma_threshold``.

    The reading that triggers the detection is **not** added to the baseline
    before evaluation, so a single extreme value cannot mask itself.
    """

    def __init__(self, config: SigmaDetectorConfig | None = None) -> None:
        self.config = config or SigmaDetectorConfig()
        self._baselines: dict[tuple[str, str], _SensorBaseline] = {}

    def _baseline_for(self, key: tuple[str, str]) -> _SensorBaseline:
        baseline = self._baselines.get(key)
        if baseline is None:
            baseline = _SensorBaseline(deque(maxlen=self.config.baseline_window))
            self._baselines[key] = baseline
        return baseline

    def evaluate(self, reading: SensorReading) -> AnomalyFlag | None:
        """Evaluate a reading, returning a flag when it is anomalous."""
        if reading.sensor_type not in self.config.sensor_types:
            return None

        baseline = self._baseline_for(reading.key)
        flag: AnomalyFlag | None = None

        if len(baseline.values) >= self.config.min_baseline_samples:
            mean = baseline.mean()
            std_dev = baseline.std_dev()
            effective_std = max(std_dev, self.config.min_std_dev)
            z_score = (reading.value - mean) / effective_std
            delta = reading.value - mean

            exceeds_sigma = z_score > self.config.sigma_threshold
            exceeds_absolute = delta > self.config.absolute_min_delta > 0

            if exceeds_sigma and (not self.config.absolute_min_delta or exceeds_absolute):
                severity = self._severity(z_score)
                flag = AnomalyFlag(
                    reading=reading,
                    baseline=mean,
                    std_dev=std_dev,
                    z_score=z_score,
                    moving_average=mean,
                    severity=severity,
                    rule=f"sigma_{self.config.sigma_threshold:g}",
                )

        baseline.values.append(reading.value)
        return flag

    @staticmethod
    def _severity(z_score: float) -> Severity:
        """Map a z-score onto a severity band."""
        if z_score >= 6.0:
            return Severity.CRITICAL
        if z_score >= 4.5:
            return Severity.WARNING
        return Severity.INFO

    def baseline_for(self, reading: SensorReading) -> tuple[float, float]:
        """Return the current ``(mean, std_dev)`` baseline for a sensor."""
        baseline = self._baseline_for(reading.key)
        if not baseline.values:
            return 0.0, 0.0
        return baseline.mean(), baseline.std_dev()

    def reset(self) -> None:
        """Drop all accumulated baselines."""
        self._baselines.clear()


@dataclass(frozen=True, slots=True)
class HealthScorerConfig:
    """Weights and thresholds of the machine health score.

    The score starts at 100 and is reduced by weighted penalties:

    * anomaly penalty - proportional to the anomaly ratio,
    * error-code penalty - proportional to the error ratio,
    * dropout penalty - proportional to the dropout ratio.

    Status bands: ``healthy`` (>= healthy threshold), ``degraded`` (>=
    degraded threshold), otherwise ``critical``.
    """

    anomaly_weight: float = 50.0
    error_weight: float = 30.0
    dropout_weight: float = 20.0
    healthy_threshold: float = 80.0
    degraded_threshold: float = 50.0
    dropout_gap_factor: float = 3.0
    expected_interval_seconds: float = 60.0
    max_dropout_count: int = 10


class MachineHealthScorer:
    """Computes a composite health score (0-100) for each machine."""

    def __init__(self, config: HealthScorerConfig | None = None) -> None:
        self.config = config or HealthScorerConfig()
        self._readings: dict[str, list[SensorReading]] = {}
        self._anomalies: dict[str, int] = {}
        self._errors: dict[str, int] = {}
        self._dropouts: dict[str, int] = {}

    def observe(self, reading: SensorReading) -> None:
        """Register a reading for its machine."""
        self._readings.setdefault(reading.machine_id, []).append(reading)
        if reading.sensor_type is SensorType.ERROR_CODE and reading.value != 0:
            self._errors[reading.machine_id] = self._errors.get(reading.machine_id, 0) + 1

    def observe_anomaly(self, anomaly: AnomalyFlag) -> None:
        """Register a detected anomaly against its machine."""
        machine_id = anomaly.reading.machine_id
        self._anomalies[machine_id] = self._anomalies.get(machine_id, 0) + 1

    def observe_dropout(self, dropout: DropoutEvent) -> None:
        """Register a sensor dropout against its machine."""
        machine_id = dropout.machine_id
        self._dropouts[machine_id] = self._dropouts.get(machine_id, 0) + 1

    def score(self, machine_id: str) -> HealthScore:
        """Compute the health score of a single machine."""
        readings = self._readings.get(machine_id, [])
        reading_count = len(readings)
        anomaly_count = self._anomalies.get(machine_id, 0)
        error_count = self._errors.get(machine_id, 0)
        dropout_count = self._dropouts.get(machine_id, 0)

        if reading_count == 0:
            return HealthScore(
                machine_id=machine_id,
                score=0.0,
                status="unknown",
                factors={"anomaly": 0.0, "error": 0.0, "dropout": 0.0},
                reading_count=0,
                anomaly_count=0,
                dropout_count=0,
            )

        anomaly_ratio = min(1.0, anomaly_count / reading_count)
        error_ratio = min(1.0, error_count / reading_count)
        dropout_ratio = min(1.0, dropout_count / max(1, self.config.max_dropout_count))

        anomaly_penalty = self.config.anomaly_weight * anomaly_ratio
        error_penalty = self.config.error_weight * error_ratio
        dropout_penalty = self.config.dropout_weight * dropout_ratio

        score = max(0.0, min(100.0, 100.0 - anomaly_penalty - error_penalty - dropout_penalty))

        if score >= self.config.healthy_threshold:
            status = "healthy"
        elif score >= self.config.degraded_threshold:
            status = "degraded"
        else:
            status = "critical"

        return HealthScore(
            machine_id=machine_id,
            score=score,
            status=status,
            factors={
                "anomaly": anomaly_ratio,
                "error": error_ratio,
                "dropout": dropout_ratio,
            },
            reading_count=reading_count,
            anomaly_count=anomaly_count,
            dropout_count=dropout_count,
        )

    def scores(self) -> tuple[HealthScore, ...]:
        """Health scores for every observed machine, ordered by machine id."""
        return tuple(self.score(machine_id) for machine_id in sorted(self._readings))


class DropoutDetector:
    """Detects gaps in sensor streams caused by device/network dropouts.

    A dropout is reported when the interval between two consecutive readings
    of the same sensor exceeds ``gap_factor`` times the expected sampling
    interval. The detector operates on time-ordered readings.
    """

    def __init__(self, config: HealthScorerConfig | None = None) -> None:
        self.config = config or HealthScorerConfig()
        self._last: dict[tuple[str, str], SensorReading] = {}

    def observe(self, reading: SensorReading) -> DropoutEvent | None:
        """Feed a time-ordered reading; return a dropout event when detected."""
        key = reading.key
        previous = self._last.get(key)
        self._last[key] = reading
        if previous is None:
            return None

        gap = (reading.timestamp.value - previous.timestamp.value).total_seconds()
        if gap <= 0:
            return None
        threshold = self.config.expected_interval_seconds * self.config.dropout_gap_factor
        if gap <= threshold:
            return None
        return DropoutEvent(
            machine_id=reading.machine_id,
            sensor_id=reading.sensor_id,
            sensor_type=reading.sensor_type,
            last_seen=previous.timestamp,
            next_seen=reading.timestamp,
            gap_seconds=gap,
        )

    def reset(self) -> None:
        """Forget the last reading of every sensor."""
        self._last.clear()


def moving_average_series(
    readings: Sequence[SensorReading],
    window: int = 5,
) -> list[float]:
    """Compute the trailing moving average of an ordered reading sequence."""
    config = MovingAverageConfig(window=window)
    tracker = MovingAverage(config)
    return [tracker.update(reading.value) for reading in readings]


def group_by_sensor(readings: Iterable[SensorReading]) -> Mapping[tuple[str, str], list[SensorReading]]:
    """Group readings by ``(machine_id, sensor_id)`` preserving input order."""
    grouped: dict[tuple[str, str], list[SensorReading]] = {}
    for reading in readings:
        grouped.setdefault(reading.key, []).append(reading)
    return grouped

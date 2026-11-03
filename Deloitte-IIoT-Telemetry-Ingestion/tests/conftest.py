"""Shared pytest fixtures for the telemetry ingestion test-suite."""

from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

from iiot_telemetry.application.analytics import (
    HealthScorerConfig,
    MovingAverage,
    MovingAverageConfig,
    SigmaAnomalyDetector,
    SigmaDetectorConfig,
)
from iiot_telemetry.application.normalizer import TelemetryNormalizer
from iiot_telemetry.domain.models import SensorReading, SensorType, Timestamp

BASE_TIME = datetime(2024, 5, 1, 8, 0, 0, tzinfo=timezone.utc)
EXAMPLES_DIR = Path(__file__).resolve().parents[1] / "examples"


@pytest.fixture
def base_time() -> datetime:
    """A fixed UTC reference instant."""
    return BASE_TIME


@pytest.fixture
def normalizer() -> TelemetryNormalizer:
    """A normalizer using the default data contracts."""
    return TelemetryNormalizer()


@pytest.fixture
def detector() -> SigmaAnomalyDetector:
    """A sigma detector with a short baseline for fast tests."""
    return SigmaAnomalyDetector(
        SigmaDetectorConfig(
            sigma_threshold=3.0,
            baseline_window=20,
            min_baseline_samples=5,
        )
    )


@pytest.fixture
def moving_average() -> MovingAverage:
    """A moving average over a window of five samples."""
    return MovingAverage(MovingAverageConfig(window=5))


@pytest.fixture
def health_scorer_config() -> HealthScorerConfig:
    """Health scorer configuration used across the analytics tests."""
    return HealthScorerConfig(
        expected_interval_seconds=60.0,
        dropout_gap_factor=3.0,
        max_dropout_count=10,
    )


@pytest.fixture
def make_reading():
    """Factory building a :class:`SensorReading` with sensible defaults."""

    def _factory(
        value: float = 20.0,
        sensor_type: SensorType = SensorType.TEMPERATURE,
        sensor_id: str = "TEMP-01",
        machine_id: str = "PRESS-01",
        offset_seconds: float = 0.0,
        unit: str = "C",
    ) -> SensorReading:
        return SensorReading(
            sensor_id=sensor_id,
            machine_id=machine_id,
            sensor_type=sensor_type,
            timestamp=Timestamp(BASE_TIME + timedelta(seconds=offset_seconds)),
            value=value,
            unit=unit,
            source="test",
        )

    return _factory


@pytest.fixture
def examples_dir() -> Path:
    """Path of the shipped example payloads."""
    return EXAMPLES_DIR


@pytest.fixture
def plant_a_payloads() -> list[dict]:
    """The decoded contents of ``plant_a_readings.json``."""
    data = json.loads((EXAMPLES_DIR / "plant_a_readings.json").read_text(encoding="utf-8"))
    return data["readings"]

"""Application layer: use cases, ports and analytics services."""

from __future__ import annotations

from .analytics import (
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
from .normalizer import (
    NormalizationResult,
    NormalizationSettings,
    TelemetryNormalizer,
    deduplicate,
)
from .pipeline import IngestionPipeline, IngestionResult
from .ports import IngestionSettings, SinkConfig, SourceConfig, TelemetrySink, TelemetrySource
from .timestamp import parse_timestamp

__all__ = [
    "DropoutDetector",
    "HealthScorerConfig",
    "IngestionPipeline",
    "IngestionResult",
    "IngestionSettings",
    "MachineHealthScorer",
    "MovingAverage",
    "MovingAverageConfig",
    "NormalizationResult",
    "NormalizationSettings",
    "SigmaAnomalyDetector",
    "SigmaDetectorConfig",
    "SinkConfig",
    "SourceConfig",
    "TelemetryNormalizer",
    "TelemetrySink",
    "TelemetrySource",
    "deduplicate",
    "group_by_sensor",
    "moving_average_series",
    "parse_timestamp",
]

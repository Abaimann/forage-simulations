"""Daikibo Industrials - IIoT Telemetry Ingestion Pipeline.

A dependency-free, clean-architecture ETL pipeline that ingests heterogeneous
factory-floor telemetry (JSON, JSON Lines, CSV), normalizes it to a canonical
UTC ISO-8601 schema, validates it against data contracts and derives
statistical health metrics.
"""

from __future__ import annotations

from .application.analytics import (
    DropoutDetector,
    HealthScorerConfig,
    MachineHealthScorer,
    MovingAverage,
    MovingAverageConfig,
    SigmaAnomalyDetector,
    SigmaDetectorConfig,
)
from .application.normalizer import (
    NormalizationResult,
    NormalizationSettings,
    TelemetryNormalizer,
    deduplicate,
)
from .application.pipeline import IngestionPipeline, IngestionResult
from .application.ports import IngestionSettings, SinkConfig, SourceConfig, TelemetrySink, TelemetrySource
from .application.timestamp import parse_timestamp
from .domain.contracts import DataContract, SensorContract
from .domain.exceptions import (
    AnalyticsError,
    ConfigurationError,
    ContractViolation,
    NormalizationError,
    ParseError,
    TelemetryError,
)
from .domain.models import (
    AnomalyFlag,
    DropoutEvent,
    HealthScore,
    PipelineReport,
    RejectReason,
    RejectedRecord,
    SensorReading,
    SensorType,
    Severity,
    Timestamp,
)

__version__ = "1.0.0"

__all__ = [
    "AnalyticsError",
    "AnomalyFlag",
    "ConfigurationError",
    "ContractViolation",
    "DataContract",
    "DropoutDetector",
    "DropoutEvent",
    "HealthScore",
    "HealthScorerConfig",
    "IngestionPipeline",
    "IngestionResult",
    "IngestionSettings",
    "MachineHealthScorer",
    "MovingAverage",
    "MovingAverageConfig",
    "NormalizationError",
    "NormalizationResult",
    "NormalizationSettings",
    "ParseError",
    "PipelineReport",
    "RejectReason",
    "RejectedRecord",
    "SensorContract",
    "SensorReading",
    "SensorType",
    "Severity",
    "SigmaAnomalyDetector",
    "SigmaDetectorConfig",
    "SinkConfig",
    "SourceConfig",
    "TelemetryError",
    "TelemetryNormalizer",
    "TelemetrySink",
    "TelemetrySource",
    "Timestamp",
    "__version__",
    "deduplicate",
    "parse_timestamp",
]

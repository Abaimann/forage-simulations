"""Domain layer: entities, value objects, contracts and domain errors."""

from __future__ import annotations

from .contracts import DataContract, FieldSpec, SensorContract
from .exceptions import (
    AnalyticsError,
    ConfigurationError,
    ContractViolation,
    NormalizationError,
    ParseError,
    TelemetryError,
)
from .models import (
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

__all__ = [
    "AnalyticsError",
    "AnomalyFlag",
    "ConfigurationError",
    "ContractViolation",
    "DataContract",
    "DropoutEvent",
    "FieldSpec",
    "HealthScore",
    "NormalizationError",
    "ParseError",
    "PipelineReport",
    "RejectReason",
    "RejectedRecord",
    "SensorContract",
    "SensorReading",
    "SensorType",
    "Severity",
    "TelemetryError",
    "Timestamp",
]

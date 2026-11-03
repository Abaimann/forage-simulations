"""Core domain entities for the IIoT telemetry domain.

The domain layer is deliberately free of I/O, framework and persistence
concerns: it only describes *what* telemetry data is and the invariants it
must satisfy. Application services orchestrate, adapters perform I/O.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from typing import Any, Mapping

from .exceptions import ContractViolation

# --------------------------------------------------------------------------- #
# Enumerations
# --------------------------------------------------------------------------- #


class SensorType(str, Enum):
    """Canonical taxonomy of supported sensor modalities."""

    TEMPERATURE = "temperature"
    VIBRATION = "vibration"
    ERROR_CODE = "error_code"

    @classmethod
    def from_raw(cls, raw: Any) -> "SensorType":
        """Resolve a sensor type from a heterogeneous raw label.

        Handles casing, whitespace, hyphens/underscores and common legacy
        synonyms used across the four plant regions.

        Raises
        ------
        ContractViolation
            If the label cannot be mapped to a known sensor type.
        """
        if isinstance(raw, SensorType):
            return raw
        if not isinstance(raw, str):
            raise ContractViolation(f"sensor_type must be a string, got {type(raw).__name__}", "sensor_type.type")

        key = raw.strip().lower().replace("-", "_").replace(" ", "_")
        aliases: dict[str, SensorType] = {
            "temperature": cls.TEMPERATURE,
            "temp": cls.TEMPERATURE,
            "temps": cls.TEMPERATURE,
            "t": cls.TEMPERATURE,
            "temperature_c": cls.TEMPERATURE,
            "vibration": cls.VIBRATION,
            "vib": cls.VIBRATION,
            "vibrations": cls.VIBRATION,
            "vibration_hz": cls.VIBRATION,
            "vib_hz": cls.VIBRATION,
            "vib_frequency": cls.VIBRATION,
            "freq": cls.VIBRATION,
            "frequency": cls.VIBRATION,
            "error_code": cls.ERROR_CODE,
            "errorcode": cls.ERROR_CODE,
            "error": cls.ERROR_CODE,
            "err": cls.ERROR_CODE,
            "fault": cls.ERROR_CODE,
            "fault_code": cls.ERROR_CODE,
            "alarm": cls.ERROR_CODE,
        }
        if key in aliases:
            return aliases[key]
        raise ContractViolation(f"unknown sensor_type {raw!r}", "sensor_type.unknown")


class Severity(str, Enum):
    """Severity classification attached to detected anomalies."""

    INFO = "info"
    WARNING = "warning"
    CRITICAL = "critical"

    @property
    def rank(self) -> int:
        """Numeric rank used for ordering (higher is more severe)."""
        return {"info": 0, "warning": 1, "critical": 2}[self.value]


class RejectReason(str, Enum):
    """Why a raw record could not be promoted into the canonical telemetry model."""

    MALFORMED_JSON = "malformed_json"
    MALFORMED_CSV = "malformed_csv"
    MISSING_REQUIRED_FIELD = "missing_required_field"
    INVALID_TIMESTAMP = "invalid_timestamp"
    INVALID_NUMERIC_VALUE = "invalid_numeric_value"
    OUT_OF_RANGE = "out_of_range"
    UNKNOWN_SENSOR_TYPE = "unknown_sensor_type"
    SCHEMA_DRIFT = "schema_drift"
    DUPLICATE = "duplicate"
    EMPTY_PAYLOAD = "empty_payload"
    IO_ERROR = "io_error"


# --------------------------------------------------------------------------- #
# Value objects
# --------------------------------------------------------------------------- #


@dataclass(frozen=True, slots=True)
class Timestamp:
    """UTC-normalized timestamp value object.

    The pipeline always stores time as timezone-aware UTC. Local wall-clock
    readings are converted at ingestion time so downstream analytics never
    depend on the ambient timezone of the machine running the pipeline.
    """

    value: datetime

    def __post_init__(self) -> None:
        if not isinstance(self.value, datetime):
            raise ContractViolation("timestamp value must be a datetime", "timestamp.type")
        if self.value.tzinfo is None:
            raise ContractViolation("timestamp must be timezone-aware", "timestamp.naive")

    @property
    def iso8601(self) -> str:
        """Canonical ISO-8601 rendering, e.g. ``2024-05-01T10:15:30+00:00``."""
        return self.value.isoformat()

    @property
    def epoch_seconds(self) -> float:
        """POSIX timestamp in seconds with sub-second resolution."""
        return self.value.timestamp()

    def __str__(self) -> str:  # pragma: no cover - trivial
        return self.iso8601


@dataclass(frozen=True, slots=True)
class SensorReading:
    """A single normalized sensor observation.

    This is the canonical *value* produced by the normalization stage and
    consumed by every downstream analytics component.
    """

    sensor_id: str
    machine_id: str
    sensor_type: SensorType
    timestamp: Timestamp
    value: float
    unit: str = ""
    source: str = ""
    quality_flags: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        if not self.sensor_id or not self.sensor_id.strip():
            raise ContractViolation("sensor_id must not be empty", "sensor_id.empty")
        if not self.machine_id or not self.machine_id.strip():
            raise ContractViolation("machine_id must not be empty", "machine_id.empty")
        if isinstance(self.value, bool) or not isinstance(self.value, (int, float)):
            raise ContractViolation(f"value must be numeric, got {type(self.value).__name__}", "value.type")

    @property
    def key(self) -> tuple[str, str]:
        """Composite key identifying the emitting sensor stream."""
        return (self.machine_id, self.sensor_id)


@dataclass(frozen=True, slots=True)
class RejectedRecord:
    """A record that failed validation, retained for auditability."""

    reason: RejectReason
    detail: str
    source: str
    raw_payload: Mapping[str, Any] = field(default_factory=dict)
    record_index: int | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "reason": self.reason.value,
            "detail": self.detail,
            "source": self.source,
            "record_index": self.record_index,
        }


# --------------------------------------------------------------------------- #
# Analytics result entities
# --------------------------------------------------------------------------- #


@dataclass(frozen=True, slots=True)
class AnomalyFlag:
    """Flagged statistical anomaly on a single reading."""

    reading: SensorReading
    baseline: float
    std_dev: float
    z_score: float
    moving_average: float
    severity: Severity
    rule: str

    def to_dict(self) -> dict[str, Any]:
        return {
            "sensor_id": self.reading.sensor_id,
            "machine_id": self.reading.machine_id,
            "sensor_type": self.reading.sensor_type.value,
            "timestamp": self.reading.timestamp.iso8601,
            "value": self.reading.value,
            "unit": self.reading.unit,
            "baseline": round(self.baseline, 6),
            "std_dev": round(self.std_dev, 6),
            "z_score": round(self.z_score, 6),
            "moving_average": round(self.moving_average, 6),
            "severity": self.severity.value,
            "rule": self.rule,
        }


@dataclass(frozen=True, slots=True)
class HealthScore:
    """Machine health assessment derived from its telemetry window."""

    machine_id: str
    score: float
    status: str
    factors: Mapping[str, float]
    reading_count: int
    anomaly_count: int
    dropout_count: int

    def to_dict(self) -> dict[str, Any]:
        return {
            "machine_id": self.machine_id,
            "score": round(self.score, 2),
            "status": self.status,
            "factors": {k: round(v, 4) for k, v in self.factors.items()},
            "reading_count": self.reading_count,
            "anomaly_count": self.anomaly_count,
            "dropout_count": self.dropout_count,
        }


@dataclass(frozen=True, slots=True)
class DropoutEvent:
    """A detected gap in an otherwise regular sensor stream."""

    machine_id: str
    sensor_id: str
    sensor_type: SensorType
    last_seen: Timestamp
    next_seen: Timestamp
    gap_seconds: float

    def to_dict(self) -> dict[str, Any]:
        return {
            "machine_id": self.machine_id,
            "sensor_id": self.sensor_id,
            "sensor_type": self.sensor_type.value,
            "last_seen": self.last_seen.iso8601,
            "next_seen": self.next_seen.iso8601,
            "gap_seconds": round(self.gap_seconds, 3),
        }


@dataclass(frozen=True, slots=True)
class PipelineReport:
    """Aggregated outcome of a single ingestion run."""

    records_ingested: int
    records_rejected: int
    anomalies_detected: int
    dropouts_detected: int
    machines: int
    sensors: int
    rejected: tuple[RejectedRecord, ...] = ()
    health_scores: tuple[HealthScore, ...] = ()

    def to_dict(self) -> dict[str, Any]:
        return {
            "records_ingested": self.records_ingested,
            "records_rejected": self.records_rejected,
            "anomalies_detected": self.anomalies_detected,
            "dropouts_detected": self.dropouts_detected,
            "machines": self.machines,
            "sensors": self.sensors,
            "rejected": [r.to_dict() for r in self.rejected],
            "health_scores": [h.to_dict() for h in self.health_scores],
        }

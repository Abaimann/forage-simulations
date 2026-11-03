"""Ports (interfaces) defining the boundaries of the application core.

The application layer depends only on these abstractions. Concrete
implementations live in :mod:`iiot_telemetry.adapters` and may be swapped
for Kafka, MQTT, S3, REST, ... without touching the core logic.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Iterable, Iterator, Mapping, Sequence

from ..domain.models import AnomalyFlag, PipelineReport, RejectedRecord, SensorReading


@dataclass(frozen=True, slots=True)
class SourceConfig:
    """Location and decoding options of an ingestion source."""

    path: Path
    encoding: str = "utf-8"
    format: str = "auto"  # "auto" | "json" | "jsonl" | "csv"
    delimiter: str | None = None


@dataclass(frozen=True, slots=True)
class SinkConfig:
    """Location and encoding options of a write target."""

    path: Path
    encoding: str = "utf-8"
    format: str = "jsonl"  # "jsonl" | "json" | "csv"


class TelemetrySource(ABC):
    """Reads raw telemetry payloads from a transport."""

    @abstractmethod
    def read(self, config: SourceConfig) -> Iterator[Mapping[str, Any]]:
        """Yield raw payload mappings from the configured source."""


class TelemetrySink(ABC):
    """Persists pipeline results to a transport."""

    @abstractmethod
    def write_readings(self, readings: Sequence[SensorReading]) -> int:
        """Persist normalized readings; return the number of records written."""

    @abstractmethod
    def write_anomalies(self, anomalies: Sequence[AnomalyFlag]) -> int:
        """Persist detected anomalies; return the number of records written."""

    @abstractmethod
    def write_rejected(self, rejected: Sequence[RejectedRecord]) -> int:
        """Persist rejected records; return the number of records written."""

    @abstractmethod
    def write_report(self, report: PipelineReport) -> int:
        """Persist the run report; return the number of records written."""


@dataclass
class IngestionSettings:
    """Top-level configuration of an ingestion run."""

    moving_average_window: int = 5
    sigma_threshold: float = 3.0
    baseline_window: int = 50
    min_baseline_samples: int = 10
    dropout_gap_factor: float = 3.0
    expected_interval_seconds: float = 60.0
    dedupe: bool = True
    sort_readings: bool = True
    sources: tuple[SourceConfig, ...] = ()
    sink: SinkConfig | None = None
    extra: Mapping[str, Any] = field(default_factory=dict)

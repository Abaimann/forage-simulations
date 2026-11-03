"""In-memory telemetry sink used by tests and dry-run executions."""

from __future__ import annotations

from typing import Any, Sequence

from ...domain.models import AnomalyFlag, PipelineReport, RejectedRecord, SensorReading
from ...application.ports import TelemetrySink


class InMemoryTelemetrySink(TelemetrySink):
    """Collects pipeline artefacts in memory for assertions."""

    def __init__(self) -> None:
        self.readings: list[SensorReading] = []
        self.anomalies: list[AnomalyFlag] = []
        self.rejected: list[RejectedRecord] = []
        self.reports: list[PipelineReport] = []

    def write_readings(self, readings: Sequence[SensorReading]) -> int:
        """Store the readings."""
        self.readings.extend(readings)
        return len(readings)

    def write_anomalies(self, anomalies: Sequence[AnomalyFlag]) -> int:
        """Store the anomalies."""
        self.anomalies.extend(anomalies)
        return len(anomalies)

    def write_rejected(self, rejected: Sequence[RejectedRecord]) -> int:
        """Store the rejected records."""
        self.rejected.extend(rejected)
        return len(rejected)

    def write_report(self, report: PipelineReport) -> int:
        """Store the report."""
        self.reports.append(report)
        return 1

    @property
    def last_report(self) -> PipelineReport | None:
        """The most recently written report, if any."""
        return self.reports[-1] if self.reports else None

    def as_dict(self) -> dict[str, Any]:
        """Snapshot of the collected artefacts (test convenience)."""
        return {
            "readings": list(self.readings),
            "anomalies": list(self.anomalies),
            "rejected": list(self.rejected),
            "reports": list(self.reports),
        }

"""File-based telemetry sink.

Writes normalized readings, anomalies, rejected records and the run report
as separate files next to each other. Output formats: JSON Lines (default),
a single JSON document, or CSV.
"""

from __future__ import annotations

import csv
import io
import json
from pathlib import Path
from typing import Any, Iterable, Sequence

from ...application.ports import SinkConfig
from ...domain.models import AnomalyFlag, PipelineReport, RejectedRecord, SensorReading
from ...application.ports import TelemetrySink


def _readings_to_dict(reading: SensorReading) -> dict[str, Any]:
    """Flatten a reading into a serialisable dictionary."""
    return {
        "sensor_id": reading.sensor_id,
        "machine_id": reading.machine_id,
        "sensor_type": reading.sensor_type.value,
        "timestamp": reading.timestamp.iso8601,
        "value": reading.value,
        "unit": reading.unit,
        "source": reading.source,
        "quality_flags": list(reading.quality_flags),
    }


class FileTelemetrySink(TelemetrySink):
    """Persists pipeline artefacts to the local filesystem."""

    def __init__(self, config: SinkConfig) -> None:
        self.config = config
        self.path = Path(config.path)
        self.path.parent.mkdir(parents=True, exist_ok=True)

    # -- helpers ----------------------------------------------------------- #

    def _target(self, name: str) -> Path:
        """Resolve the output path of an artefact."""
        if self.config.format == "json":
            return self.path.with_name(f"{self.path.stem}_{name}.json")
        return self.path.with_name(f"{self.path.stem}_{name}.{self.config.format}")

    def _write_jsonl(self, target: Path, rows: Iterable[dict[str, Any]]) -> int:
        """Write rows as newline-delimited JSON; return the row count."""
        count = 0
        with target.open("w", encoding=self.config.encoding, newline="\n") as handle:
            for row in rows:
                handle.write(json.dumps(row, ensure_ascii=False, default=str) + "\n")
                count += 1
        return count

    def _write_json(self, target: Path, rows: Sequence[dict[str, Any]]) -> int:
        """Write rows as a single JSON document; return the row count."""
        with target.open("w", encoding=self.config.encoding, newline="\n") as handle:
            json.dump(list(rows), handle, ensure_ascii=False, indent=2, default=str)
            handle.write("\n")
        return len(rows)

    def _write_csv(self, target: Path, rows: Sequence[dict[str, Any]]) -> int:
        """Write rows as CSV with a union header; return the row count."""
        if not rows:
            target.write_text("", encoding=self.config.encoding)
            return 0
        fieldnames: list[str] = []
        for row in rows:
            for key in row:
                if key not in fieldnames:
                    fieldnames.append(key)
        buffer = io.StringIO()
        writer = csv.DictWriter(buffer, fieldnames=fieldnames, extrasaction="ignore")
        writer.writeheader()
        for row in rows:
            writer.writerow(row)
        target.write_text(buffer.getvalue(), encoding=self.config.encoding)
        return len(rows)

    def _write(self, name: str, rows: Sequence[dict[str, Any]]) -> int:
        """Dispatch the write according to the configured output format."""
        target = self._target(name)
        if self.config.format == "json":
            return self._write_json(target, rows)
        if self.config.format == "csv":
            return self._write_csv(target, rows)
        return self._write_jsonl(target, rows)

    # -- TelemetrySink ----------------------------------------------------- #

    def write_readings(self, readings: Sequence[SensorReading]) -> int:
        """Persist the normalized readings."""
        return self._write("readings", [_readings_to_dict(r) for r in readings])

    def write_anomalies(self, anomalies: Sequence[AnomalyFlag]) -> int:
        """Persist the detected anomalies."""
        return self._write("anomalies", [a.to_dict() for a in anomalies])

    def write_rejected(self, rejected: Sequence[RejectedRecord]) -> int:
        """Persist the rejected (dead-letter) records."""
        return self._write("rejected", [r.to_dict() for r in rejected])

    def write_report(self, report: PipelineReport) -> int:
        """Persist the run report."""
        return self._write("report", [report.to_dict()])

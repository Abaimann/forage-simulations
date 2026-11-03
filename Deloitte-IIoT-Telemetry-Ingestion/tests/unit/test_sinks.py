"""Unit tests for the sink adapters."""

from __future__ import annotations

import csv
import json
from pathlib import Path

import pytest

from iiot_telemetry.adapters.sinks.file_sink import FileTelemetrySink
from iiot_telemetry.adapters.sinks.memory_sink import InMemoryTelemetrySink
from iiot_telemetry.application.ports import SinkConfig
from iiot_telemetry.domain.models import (
    AnomalyFlag,
    PipelineReport,
    RejectReason,
    RejectedRecord,
    SensorType,
    Severity,
)


class TestInMemorySink:
    """The in-memory sink collects artefacts for assertions."""

    def test_collects_readings(self, make_reading) -> None:
        sink = InMemoryTelemetrySink()
        assert sink.write_readings([make_reading()]) == 1
        assert len(sink.readings) == 1

    def test_collects_anomalies(self, make_reading) -> None:
        sink = InMemoryTelemetrySink()
        anomaly = AnomalyFlag(
            reading=make_reading(),
            baseline=1.0,
            std_dev=0.1,
            z_score=10.0,
            moving_average=1.0,
            severity=Severity.CRITICAL,
            rule="sigma_3",
        )
        assert sink.write_anomalies([anomaly]) == 1
        assert len(sink.anomalies) == 1

    def test_collects_rejected(self) -> None:
        sink = InMemoryTelemetrySink()
        rejected = RejectedRecord(
            reason=RejectReason.INVALID_TIMESTAMP, detail="bad", source="f.json"
        )
        assert sink.write_rejected([rejected]) == 1
        assert len(sink.rejected) == 1

    def test_collects_report(self) -> None:
        sink = InMemoryTelemetrySink()
        report = PipelineReport(
            records_ingested=1,
            records_rejected=0,
            anomalies_detected=0,
            dropouts_detected=0,
            machines=1,
            sensors=1,
        )
        assert sink.write_report(report) == 1
        assert sink.last_report is report

    def test_last_report_is_none_initially(self) -> None:
        assert InMemoryTelemetrySink().last_report is None

    def test_as_dict_snapshot(self, make_reading) -> None:
        sink = InMemoryTelemetrySink()
        sink.write_readings([make_reading()])
        snapshot = sink.as_dict()
        assert len(snapshot["readings"]) == 1


class TestFileSink:
    """The file sink writes artefacts to disk."""

    def test_writes_jsonl_artefacts(self, tmp_path: Path, make_reading) -> None:
        sink = FileTelemetrySink(SinkConfig(path=tmp_path / "out.jsonl"))
        assert sink.write_readings([make_reading()]) == 1
        readings_file = tmp_path / "out_readings.jsonl"
        assert readings_file.exists()
        lines = readings_file.read_text(encoding="utf-8").strip().splitlines()
        payload = json.loads(lines[0])
        assert payload["sensor_id"] == "TEMP-01"
        assert payload["timestamp"].startswith("2024-05-01T08:00:00")

    def test_writes_json_artefacts(self, tmp_path: Path, make_reading) -> None:
        sink = FileTelemetrySink(SinkConfig(path=tmp_path / "out.json", format="json"))
        sink.write_readings([make_reading()])
        payload = json.loads((tmp_path / "out_readings.json").read_text(encoding="utf-8"))
        assert isinstance(payload, list)
        assert payload[0]["sensor_id"] == "TEMP-01"

    def test_writes_csv_artefacts(self, tmp_path: Path, make_reading) -> None:
        sink = FileTelemetrySink(SinkConfig(path=tmp_path / "out.csv", format="csv"))
        sink.write_readings([make_reading()])
        with (tmp_path / "out_readings.csv").open(encoding="utf-8", newline="") as handle:
            rows = list(csv.DictReader(handle))
        assert rows[0]["sensor_id"] == "TEMP-01"

    def test_csv_with_no_rows_writes_empty_file(self, tmp_path: Path) -> None:
        sink = FileTelemetrySink(SinkConfig(path=tmp_path / "out.csv", format="csv"))
        assert sink.write_readings([]) == 0
        assert (tmp_path / "out_readings.csv").read_text(encoding="utf-8") == ""

    def test_writes_anomalies(self, tmp_path: Path, make_reading) -> None:
        sink = FileTelemetrySink(SinkConfig(path=tmp_path / "out.jsonl"))
        anomaly = AnomalyFlag(
            reading=make_reading(),
            baseline=1.0,
            std_dev=0.1,
            z_score=10.0,
            moving_average=1.0,
            severity=Severity.WARNING,
            rule="sigma_3",
        )
        sink.write_anomalies([anomaly])
        payload = json.loads((tmp_path / "out_anomalies.jsonl").read_text(encoding="utf-8"))
        assert payload["severity"] == "warning"

    def test_writes_rejected(self, tmp_path: Path) -> None:
        sink = FileTelemetrySink(SinkConfig(path=tmp_path / "out.jsonl"))
        sink.write_rejected(
            [RejectedRecord(reason=RejectReason.DUPLICATE, detail="dup", source="f.json")]
        )
        payload = json.loads((tmp_path / "out_rejected.jsonl").read_text(encoding="utf-8"))
        assert payload["reason"] == "duplicate"

    def test_writes_report(self, tmp_path: Path) -> None:
        sink = FileTelemetrySink(SinkConfig(path=tmp_path / "out.jsonl"))
        report = PipelineReport(
            records_ingested=3,
            records_rejected=1,
            anomalies_detected=0,
            dropouts_detected=0,
            machines=1,
            sensors=2,
        )
        sink.write_report(report)
        payload = json.loads((tmp_path / "out_report.jsonl").read_text(encoding="utf-8"))
        assert payload["records_ingested"] == 3

    def test_creates_the_output_directory(self, tmp_path: Path, make_reading) -> None:
        target = tmp_path / "nested" / "deeper" / "out.jsonl"
        sink = FileTelemetrySink(SinkConfig(path=target))
        sink.write_readings([make_reading()])
        assert (tmp_path / "nested" / "deeper" / "out_readings.jsonl").exists()

    def test_csv_header_is_the_union_of_all_row_keys(self, tmp_path: Path) -> None:
        # Rows with differing key sets must produce a union header, with the
        # missing cells left empty.
        sink = FileTelemetrySink(SinkConfig(path=tmp_path / "out.csv", format="csv"))
        sink.write_readings([])  # ensure the artefact exists
        sink._write_csv(
            tmp_path / "mixed.csv",
            [{"a": 1, "b": 2}, {"b": 3, "c": 4}],
        )
        with (tmp_path / "mixed.csv").open(encoding="utf-8", newline="") as handle:
            rows = list(csv.DictReader(handle))
        assert list(rows[0].keys()) == ["a", "b", "c"]
        assert rows[0]["a"] == "1"
        assert rows[1]["c"] == "4"
        assert rows[1]["a"] == ""

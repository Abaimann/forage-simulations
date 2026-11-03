"""Integration tests exercising the full pipeline over realistic payloads."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from iiot_telemetry.adapters.sinks.file_sink import FileTelemetrySink
from iiot_telemetry.adapters.sinks.memory_sink import InMemoryTelemetrySink
from iiot_telemetry.application.pipeline import IngestionPipeline
from iiot_telemetry.application.ports import IngestionSettings, SinkConfig, SourceConfig
from iiot_telemetry.domain.models import RejectReason, SensorType

pytestmark = pytest.mark.integration


def _pipeline(*sources: Path, **overrides) -> IngestionPipeline:
    """Build a pipeline over ``sources`` with the given setting overrides."""
    settings = IngestionSettings(
        sources=tuple(SourceConfig(path=path) for path in sources),
        **overrides,
    )
    return IngestionPipeline(settings=settings)


class TestShippedExamples:
    """The example payloads shipped with the project must ingest cleanly."""

    def test_plant_a_json_is_fully_ingested(self, examples_dir: Path) -> None:
        result = _pipeline(examples_dir / "plant_a_readings.json").run()
        assert result.report.records_ingested == 60
        assert result.report.records_rejected == 0
        assert result.report.machines == 1
        assert result.report.sensors == 3

    def test_plant_a_timestamps_are_utc_iso8601(self, examples_dir: Path) -> None:
        result = _pipeline(examples_dir / "plant_a_readings.json").run()
        for reading in result.readings:
            assert reading.timestamp.iso8601.startswith("2024-05-01T")
            assert reading.timestamp.value.utcoffset().total_seconds() == 0

    def test_plant_b_legacy_csv_survives_schema_drift(
        self, examples_dir: Path
    ) -> None:
        result = _pipeline(examples_dir / "plant_b_legacy.csv").run()
        # 70 rows: 60 legacy headers + 10 renamed columns.
        assert result.report.records_ingested == 70
        assert result.report.records_rejected == 0
        assert result.report.machines == 1

    def test_plant_c_wide_jsonl_yields_two_readings_per_row(
        self, examples_dir: Path
    ) -> None:
        result = _pipeline(examples_dir / "plant_c_stream.jsonl").run()
        # 60 rows x (temperature + error_code) = 120 readings.
        assert result.report.records_ingested == 120
        types = {r.sensor_type for r in result.readings}
        assert types == {SensorType.TEMPERATURE, SensorType.ERROR_CODE}

    def test_plant_c_error_codes_penalise_the_machine(
        self, examples_dir: Path
    ) -> None:
        result = _pipeline(examples_dir / "plant_c_stream.jsonl").run()
        score = result.report.health_scores[0]
        assert score.machine_id == "LATHE-03"
        assert score.score < 100.0

    def test_all_examples_together(self, examples_dir: Path) -> None:
        result = _pipeline(
            examples_dir / "plant_a_readings.json",
            examples_dir / "plant_b_legacy.csv",
            examples_dir / "plant_c_stream.jsonl",
        ).run()
        assert result.report.records_ingested == 250
        assert result.report.machines == 3

    def test_thermal_excursion_is_flagged(self, examples_dir: Path) -> None:
        result = _pipeline(
            examples_dir / "plant_a_readings.json",
            baseline_window=30,
            min_baseline_samples=5,
        ).run()
        assert result.report.anomalies_detected >= 1
        flagged = [a for a in result.anomalies if a.reading.value > 100.0]
        assert flagged, "the 121.5 C excursion must be detected"
        assert flagged[0].severity in {"info", "warning", "critical"}


class TestCorruptAndHostileInputs:
    """Corrupt inputs must be quarantined without aborting the run."""

    def test_mixed_valid_and_corrupt_records(self, tmp_path: Path) -> None:
        path = tmp_path / "data.json"
        path.write_text(
            json.dumps(
                [
                    {
                        "sensor_id": "TEMP-01",
                        "machine_id": "PRESS-01",
                        "sensor_type": "temperature",
                        "timestamp": "2024-05-01T08:00:00Z",
                        "value": 80.0,
                    },
                    {
                        "sensor_id": "TEMP-02",
                        "machine_id": "PRESS-01",
                        "sensor_type": "temperature",
                        "timestamp": "not-a-timestamp",
                        "value": 80.0,
                    },
                    {
                        "sensor_id": "TEMP-03",
                        "machine_id": "PRESS-01",
                        "sensor_type": "temperature",
                        "timestamp": "2024-05-01T08:02:00Z",
                        "value": "N/A",
                    },
                    {
                        "sensor_id": "TEMP-04",
                        "machine_id": "PRESS-01",
                        "sensor_type": "pressure",
                        "timestamp": "2024-05-01T08:03:00Z",
                        "value": 10.0,
                    },
                    {
                        "machine_id": "PRESS-01",
                        "sensor_type": "temperature",
                        "timestamp": "2024-05-01T08:04:00Z",
                        "value": 10.0,
                    },
                ]
            ),
            encoding="utf-8",
        )
        result = _pipeline(path).run()
        assert result.report.records_ingested == 1
        assert result.report.records_rejected == 4
        reasons = {r.reason for r in result.rejected}
        assert RejectReason.INVALID_TIMESTAMP in reasons
        assert RejectReason.INVALID_NUMERIC_VALUE in reasons
        assert RejectReason.UNKNOWN_SENSOR_TYPE in reasons
        assert RejectReason.MISSING_REQUIRED_FIELD in reasons

    def test_empty_file_produces_an_empty_run(self, tmp_path: Path) -> None:
        path = tmp_path / "empty.json"
        path.write_text("[]", encoding="utf-8")
        result = _pipeline(path).run()
        assert result.report.records_ingested == 0
        assert result.report.records_rejected == 0

    def test_sensor_dropout_is_detected(self, tmp_path: Path) -> None:
        records = [
            {
                "sensor_id": "TEMP-01",
                "machine_id": "PRESS-01",
                "sensor_type": "temperature",
                "timestamp": f"2024-05-01T08:{minute:02d}:00Z",
                "value": 80.0,
            }
            for minute in (0, 1, 2, 3, 40)
        ]
        path = tmp_path / "data.json"
        path.write_text(json.dumps(records), encoding="utf-8")
        result = _pipeline(
            path, expected_interval_seconds=60.0, dropout_gap_factor=3.0
        ).run()
        assert result.report.dropouts_detected == 1
        dropout = result.dropouts[0]
        assert dropout.sensor_id == "TEMP-01"
        assert dropout.gap_seconds == pytest.approx(37 * 60)

    def test_out_of_order_records_are_sorted(self, tmp_path: Path) -> None:
        records = [
            {
                "sensor_id": "TEMP-01",
                "machine_id": "PRESS-01",
                "sensor_type": "temperature",
                "timestamp": f"2024-05-01T08:{minute:02d}:00Z",
                "value": 80.0,
            }
            for minute in (5, 0, 3, 1)
        ]
        path = tmp_path / "data.json"
        path.write_text(json.dumps(records), encoding="utf-8")
        result = _pipeline(path).run()
        minutes = [r.timestamp.value.minute for r in result.readings]
        assert minutes == sorted(minutes)

    def test_duplicate_records_across_files_are_removed(self, tmp_path: Path) -> None:
        record = {
            "sensor_id": "TEMP-01",
            "machine_id": "PRESS-01",
            "sensor_type": "temperature",
            "timestamp": "2024-05-01T08:00:00Z",
            "value": 80.0,
        }
        first = tmp_path / "a.json"
        second = tmp_path / "b.json"
        first.write_text(json.dumps([record]), encoding="utf-8")
        second.write_text(json.dumps([record]), encoding="utf-8")
        result = _pipeline(first, second).run()
        assert result.report.records_ingested == 1
        assert result.report.records_rejected == 1
        assert result.rejected[0].reason is RejectReason.DUPLICATE

    def test_empty_file_is_handled(self, tmp_path: Path) -> None:
        path = tmp_path / "empty.csv"
        path.write_text("", encoding="utf-8")
        result = _pipeline(path).run()
        assert result.report.records_ingested == 0


class TestArtefactWriting:
    """Artefacts written to disk must be complete and consistent."""

    def test_all_artefacts_are_written(self, tmp_path: Path, examples_dir: Path) -> None:
        output = tmp_path / "out" / "telemetry.jsonl"
        sink = FileTelemetrySink(SinkConfig(path=output))
        pipeline = IngestionPipeline(
            settings=IngestionSettings(
                sources=(SourceConfig(path=examples_dir / "plant_a_readings.json"),)
            ),
            sink=sink,
        )
        result = pipeline.run()

        readings = [
            json.loads(line)
            for line in (tmp_path / "out" / "telemetry_readings.jsonl")
            .read_text(encoding="utf-8")
            .splitlines()
            if line
        ]
        assert len(readings) == result.report.records_ingested
        assert readings[0]["timestamp"].endswith("+00:00")

        report = json.loads(
            (tmp_path / "out" / "telemetry_report.jsonl").read_text(encoding="utf-8")
        )
        assert report["records_ingested"] == result.report.records_ingested
        assert len(report["health_scores"]) == 1

    def test_memory_sink_receives_everything(self, examples_dir: Path) -> None:
        sink = InMemoryTelemetrySink()
        pipeline = IngestionPipeline(
            settings=IngestionSettings(
                sources=(SourceConfig(path=examples_dir / "plant_a_readings.json"),)
            ),
            sink=sink,
        )
        result = pipeline.run()
        assert len(sink.readings) == len(result.readings)
        assert sink.last_report is not None

    def test_rejected_records_are_written(self, tmp_path: Path) -> None:
        path = tmp_path / "data.json"
        path.write_text(json.dumps([{"garbage": 1}]), encoding="utf-8")
        output = tmp_path / "telemetry.jsonl"
        sink = FileTelemetrySink(SinkConfig(path=output))
        pipeline = IngestionPipeline(
            settings=IngestionSettings(sources=(SourceConfig(path=path),)), sink=sink
        )
        pipeline.run()
        rejected = (tmp_path / "telemetry_rejected.jsonl").read_text(encoding="utf-8")
        assert "missing_required_field" in rejected

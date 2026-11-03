"""Unit tests for the pipeline orchestrator."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from iiot_telemetry.adapters.sinks.memory_sink import InMemoryTelemetrySink
from iiot_telemetry.application.pipeline import IngestionPipeline
from iiot_telemetry.application.ports import IngestionSettings, SinkConfig, SourceConfig
from iiot_telemetry.domain.models import RejectReason, SensorType


def _write_json(path: Path, records: list[dict]) -> Path:
    """Write ``records`` as a JSON document and return the path."""
    path.write_text(json.dumps(records), encoding="utf-8")
    return path


def _reading(
    sensor_id: str = "TEMP-01",
    machine_id: str = "PRESS-01",
    value: float = 100.0,
    minute: int = 0,
    sensor_type: str = "temperature",
) -> dict:
    """Build a canonical raw payload."""
    return {
        "sensor_id": sensor_id,
        "machine_id": machine_id,
        "sensor_type": sensor_type,
        "timestamp": f"2024-05-01T08:{minute:02d}:00Z",
        "value": value,
    }


class TestPipelineRun:
    """End-to-end behaviour of a pipeline run."""

    def test_ingests_readings_from_a_json_source(self, tmp_path: Path) -> None:
        path = _write_json(tmp_path / "data.json", [_reading(minute=i) for i in range(5)])
        pipeline = IngestionPipeline(
            settings=IngestionSettings(sources=(SourceConfig(path=path),))
        )
        result = pipeline.run()
        assert result.report.records_ingested == 5
        assert result.report.machines == 1
        assert result.report.sensors == 1

    def test_readings_are_sorted_by_timestamp(self, tmp_path: Path) -> None:
        path = _write_json(
            tmp_path / "data.json",
            [_reading(minute=2), _reading(minute=0), _reading(minute=1)],
        )
        pipeline = IngestionPipeline(
            settings=IngestionSettings(sources=(SourceConfig(path=path),))
        )
        result = pipeline.run()
        timestamps = [r.timestamp.iso8601 for r in result.readings]
        assert timestamps == sorted(timestamps)

    def test_readings_carry_the_source_name(self, tmp_path: Path) -> None:
        path = _write_json(tmp_path / "data.json", [_reading()])
        pipeline = IngestionPipeline(
            settings=IngestionSettings(sources=(SourceConfig(path=path),))
        )
        result = pipeline.run()
        assert result.readings[0].source == str(path)

    def test_duplicates_are_removed(self, tmp_path: Path) -> None:
        path = _write_json(tmp_path / "data.json", [_reading(), _reading()])
        pipeline = IngestionPipeline(
            settings=IngestionSettings(sources=(SourceConfig(path=path),))
        )
        result = pipeline.run()
        assert result.report.records_ingested == 1
        assert result.report.records_rejected == 1
        assert result.rejected[0].reason is RejectReason.DUPLICATE

    def test_deduplication_can_be_disabled(self, tmp_path: Path) -> None:
        path = _write_json(tmp_path / "data.json", [_reading(), _reading()])
        pipeline = IngestionPipeline(
            settings=IngestionSettings(
                sources=(SourceConfig(path=path),), dedupe=False
            )
        )
        result = pipeline.run()
        assert result.report.records_ingested == 2

    def test_sorting_can_be_disabled(self, tmp_path: Path) -> None:
        path = _write_json(tmp_path / "data.json", [_reading(minute=2), _reading(minute=0)])
        pipeline = IngestionPipeline(
            settings=IngestionSettings(
                sources=(SourceConfig(path=path),), sort_readings=False
            )
        )
        result = pipeline.run()
        assert result.readings[0].timestamp.value.minute == 2

    def test_multiple_sources_are_merged(self, tmp_path: Path) -> None:
        first = _write_json(tmp_path / "a.json", [_reading(machine_id="PRESS-01")])
        second = _write_json(tmp_path / "b.json", [_reading(machine_id="PRESS-02")])
        pipeline = IngestionPipeline(
            settings=IngestionSettings(
                sources=(SourceConfig(path=first), SourceConfig(path=second))
            )
        )
        result = pipeline.run()
        assert result.report.records_ingested == 2
        assert result.report.machines == 2

    def test_malformed_source_is_quarantined_not_fatal(self, tmp_path: Path) -> None:
        bad = tmp_path / "bad.json"
        bad.write_text("{not json", encoding="utf-8")
        good = _write_json(tmp_path / "good.json", [_reading()])
        pipeline = IngestionPipeline(
            settings=IngestionSettings(
                sources=(SourceConfig(path=bad), SourceConfig(path=good))
            )
        )
        result = pipeline.run()
        assert result.report.records_ingested == 1
        assert result.report.records_rejected == 1
        assert result.rejected[0].reason is RejectReason.MALFORMED_JSON

    def test_malformed_csv_source_is_quarantined(self, tmp_path: Path) -> None:
        bad = tmp_path / "bad.csv"
        bad.write_text("a,b\n1,2\n", encoding="utf-8")
        pipeline = IngestionPipeline(
            settings=IngestionSettings(
                sources=(SourceConfig(path=bad, format="csv"),)
            )
        )
        result = pipeline.run()
        assert result.report.records_rejected == 1
        assert result.rejected[0].reason is RejectReason.MALFORMED_CSV

    def test_invalid_records_are_quarantined(self, tmp_path: Path) -> None:
        path = _write_json(
            tmp_path / "data.json",
            [_reading(), {"sensor_id": "X", "machine_id": "M"}],
        )
        pipeline = IngestionPipeline(
            settings=IngestionSettings(sources=(SourceConfig(path=path),))
        )
        result = pipeline.run()
        assert result.report.records_ingested == 1
        assert result.report.records_rejected == 1

    def test_sink_receives_all_artefacts(self, tmp_path: Path) -> None:
        path = _write_json(tmp_path / "data.json", [_reading(), {"bad": 1}])
        sink = InMemoryTelemetrySink()
        pipeline = IngestionPipeline(
            settings=IngestionSettings(sources=(SourceConfig(path=path),)), sink=sink
        )
        pipeline.run()
        assert len(sink.readings) == 1
        assert len(sink.rejected) == 1
        assert sink.last_report is not None

    def test_health_scores_are_computed_per_machine(self, tmp_path: Path) -> None:
        path = _write_json(
            tmp_path / "data.json",
            [_reading(machine_id="PRESS-01"), _reading(machine_id="PRESS-02")],
        )
        pipeline = IngestionPipeline(
            settings=IngestionSettings(sources=(SourceConfig(path=path),))
        )
        result = pipeline.run()
        assert {s.machine_id for s in result.report.health_scores} == {"PRESS-01", "PRESS-02"}

    def test_anomalies_are_detected(self, tmp_path: Path) -> None:
        # A stable 100 C baseline followed by a 250 C excursion.
        records = [_reading(value=100.0, minute=i) for i in range(12)]
        records.append(_reading(value=250.0, minute=12))
        path = _write_json(tmp_path / "data.json", records)
        pipeline = IngestionPipeline(
            settings=IngestionSettings(
                sources=(SourceConfig(path=path),),
                sigma_threshold=3.0,
                baseline_window=20,
                min_baseline_samples=5,
            )
        )
        result = pipeline.run()
        assert result.report.anomalies_detected >= 1
        assert result.anomalies[0].reading.value == 250.0

    def test_dropouts_are_detected(self, tmp_path: Path) -> None:
        records = [_reading(minute=0), _reading(minute=30)]
        path = _write_json(tmp_path / "data.json", records)
        pipeline = IngestionPipeline(
            settings=IngestionSettings(
                sources=(SourceConfig(path=path),),
                expected_interval_seconds=60.0,
                dropout_gap_factor=3.0,
            )
        )
        result = pipeline.run()
        assert result.report.dropouts_detected == 1

    def test_report_to_dict_is_serialisable(self, tmp_path: Path) -> None:
        path = _write_json(tmp_path / "data.json", [_reading()])
        pipeline = IngestionPipeline(
            settings=IngestionSettings(sources=(SourceConfig(path=path),))
        )
        result = pipeline.run()
        json.dumps(result.report.to_dict())


class TestPipelineWithFiles:
    """The file-oriented convenience wrapper."""

    def test_run_with_files_writes_to_disk(self, tmp_path: Path) -> None:
        source = _write_json(tmp_path / "data.json", [_reading()])
        output = tmp_path / "out" / "telemetry.jsonl"
        pipeline = IngestionPipeline()
        result = pipeline.run_with_files(
            [SourceConfig(path=source)], SinkConfig(path=output)
        )
        assert result.report.records_ingested == 1
        assert (tmp_path / "out" / "telemetry_readings.jsonl").exists()

    def test_run_with_files_without_sink(self, tmp_path: Path) -> None:
        source = _write_json(tmp_path / "data.json", [_reading()])
        pipeline = IngestionPipeline()
        result = pipeline.run_with_files([SourceConfig(path=source)])
        assert result.report.records_ingested == 1


class TestPipelineConfiguration:
    """Configuration handling of the pipeline."""

    def test_default_settings_are_applied(self) -> None:
        pipeline = IngestionPipeline()
        assert pipeline.settings.sigma_threshold == 3.0
        assert pipeline.settings.moving_average_window == 5

    def test_custom_contract_is_used(self, tmp_path: Path) -> None:
        from iiot_telemetry.domain.contracts import DataContract, SensorContract

        contract = DataContract(
            contracts={
                SensorType.TEMPERATURE: SensorContract(
                    sensor_type=SensorType.TEMPERATURE, unit="C", max_value=150.0
                )
            }
        )
        path = _write_json(tmp_path / "data.json", [_reading(value=500.0)])
        pipeline = IngestionPipeline(
            settings=IngestionSettings(sources=(SourceConfig(path=path),)),
            contract=contract,
        )
        result = pipeline.run()
        assert result.report.records_ingested == 0
        assert result.report.records_rejected == 1

    def test_result_exposes_health_scores(self, tmp_path: Path) -> None:
        path = _write_json(tmp_path / "data.json", [_reading()])
        pipeline = IngestionPipeline(
            settings=IngestionSettings(sources=(SourceConfig(path=path),))
        )
        result = pipeline.run()
        assert result.health_scores == result.report.health_scores

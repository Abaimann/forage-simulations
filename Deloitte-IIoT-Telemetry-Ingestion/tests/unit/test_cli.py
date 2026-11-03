"""Unit tests for the command-line interface."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from iiot_telemetry.cli import build_parser, main


def _write_json(path: Path, records: list[dict]) -> Path:
    """Write ``records`` as a JSON document and return the path."""
    path.write_text(json.dumps(records), encoding="utf-8")
    return path


def _reading(minute: int = 0) -> dict:
    """Build a canonical raw payload."""
    return {
        "sensor_id": "TEMP-01",
        "machine_id": "PRESS-01",
        "sensor_type": "temperature",
        "timestamp": f"2024-05-01T08:{minute:02d}:00Z",
        "value": 100.0,
    }


class TestArgumentParser:
    """The argument parser accepts the documented options."""

    def test_defaults(self) -> None:
        args = build_parser().parse_args(["-i", "data.json"])
        assert args.format == "auto"
        assert args.output_format == "jsonl"
        assert args.sigma == 3.0
        assert args.baseline_window == 50
        assert args.min_baseline_samples == 10
        assert args.moving_average_window == 5
        assert args.expected_interval == 60.0
        assert args.no_dedupe is False

    def test_input_is_required(self) -> None:
        with pytest.raises(SystemExit):
            build_parser().parse_args([])

    def test_custom_parameters(self) -> None:
        args = build_parser().parse_args(
            [
                "-i",
                "data.json",
                "-o",
                "out.jsonl",
                "--format",
                "csv",
                "--output-format",
                "json",
                "--sigma",
                "2.5",
                "--baseline-window",
                "100",
                "--min-baseline-samples",
                "20",
                "--moving-average-window",
                "10",
                "--expected-interval",
                "30",
                "--no-dedupe",
            ]
        )
        assert args.format == "csv"
        assert args.output_format == "json"
        assert args.sigma == 2.5
        assert args.baseline_window == 100
        assert args.min_baseline_samples == 20
        assert args.moving_average_window == 10
        assert args.expected_interval == 30
        assert args.no_dedupe is True


class TestMain:
    """The CLI entry point."""

    def test_ingests_a_single_file_and_prints_the_report(
        self, tmp_path: Path, capsys: pytest.CaptureFixture[str]
    ) -> None:
        source = _write_json(tmp_path / "data.json", [_reading(minute=i) for i in range(3)])
        exit_code = main(["-i", str(source)])
        assert exit_code == 0
        payload = json.loads(capsys.readouterr().out)
        assert payload["records_ingested"] == 3

    def test_writes_output_artefacts(self, tmp_path: Path) -> None:
        source = _write_json(tmp_path / "data.json", [_reading()])
        output = tmp_path / "out" / "telemetry.jsonl"
        exit_code = main(["-i", str(source), "-o", str(output)])
        assert exit_code == 0
        assert (tmp_path / "out" / "telemetry_readings.jsonl").exists()
        assert (tmp_path / "out" / "telemetry_anomalies.jsonl").exists()
        assert (tmp_path / "out" / "telemetry_rejected.jsonl").exists()
        assert (tmp_path / "out" / "telemetry_report.jsonl").exists()

    def test_ingests_a_directory(self, tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
        _write_json(tmp_path / "a.json", [_reading()])
        (tmp_path / "b.csv").write_text(
            "sensor_id,machine_id,timestamp,sensor_type,value\n"
            "TEMP-02,PRESS-02,2024-05-01T08:00:00Z,temperature,90.0\n",
            encoding="utf-8",
        )
        exit_code = main(["-i", str(tmp_path)])
        assert exit_code == 0
        payload = json.loads(capsys.readouterr().out)
        assert payload["records_ingested"] == 2

    def test_missing_input_returns_error_code(
        self, tmp_path: Path, capsys: pytest.CaptureFixture[str]
    ) -> None:
        exit_code = main(["-i", str(tmp_path / "missing.json")])
        assert exit_code == 2
        assert "error" in capsys.readouterr().err

    def test_empty_directory_returns_error_code(
        self, tmp_path: Path, capsys: pytest.CaptureFixture[str]
    ) -> None:
        exit_code = main(["-i", str(tmp_path)])
        assert exit_code == 2
        assert "no readable input files" in capsys.readouterr().err

    def test_malformed_input_is_quarantined(
        self, tmp_path: Path, capsys: pytest.CaptureFixture[str]
    ) -> None:
        bad = tmp_path / "bad.json"
        bad.write_text("{not json", encoding="utf-8")
        exit_code = main(["-i", str(bad)])
        assert exit_code == 0
        payload = json.loads(capsys.readouterr().out)
        assert payload["records_rejected"] == 1

    def test_output_format_json(self, tmp_path: Path) -> None:
        source = _write_json(tmp_path / "data.json", [_reading()])
        output = tmp_path / "telemetry.json"
        main(["-i", str(source), "-o", str(output), "--output-format", "json"])
        payload = json.loads((tmp_path / "telemetry_readings.json").read_text(encoding="utf-8"))
        assert payload[0]["sensor_id"] == "TEMP-01"

    def test_print_report_flag(self, tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
        source = _write_json(tmp_path / "data.json", [_reading()])
        output = tmp_path / "telemetry.jsonl"
        main(["-i", str(source), "-o", str(output), "--print-report"])
        payload = json.loads(capsys.readouterr().out)
        assert "records_ingested" in payload

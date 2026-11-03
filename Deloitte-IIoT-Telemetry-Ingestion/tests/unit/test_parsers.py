"""Unit tests for the format-specific parser adapters."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from iiot_telemetry.adapters.parsers.csv_parser import CsvTelemetryParser
from iiot_telemetry.adapters.parsers.json_parser import JsonTelemetryParser
from iiot_telemetry.adapters.parsers.jsonl_parser import JsonlTelemetryParser
from iiot_telemetry.adapters.parsers.registry import build_source, detect_format
from iiot_telemetry.application.ports import SourceConfig
from iiot_telemetry.domain.exceptions import ParseError


class TestJsonParser:
    """Behaviour of the JSON document parser."""

    def test_reads_array_of_readings(self, tmp_path: Path) -> None:
        path = tmp_path / "data.json"
        path.write_text(
            json.dumps([{"sensor_id": "A", "value": 1}, {"sensor_id": "B", "value": 2}]),
            encoding="utf-8",
        )
        records = list(JsonTelemetryParser().read(SourceConfig(path=path)))
        assert len(records) == 2
        assert records[0]["sensor_id"] == "A"

    def test_reads_wrapped_readings(self, tmp_path: Path) -> None:
        path = tmp_path / "data.json"
        path.write_text(
            json.dumps({"plant": "X", "readings": [{"sensor_id": "A", "value": 1}]}),
            encoding="utf-8",
        )
        records = list(JsonTelemetryParser().read(SourceConfig(path=path)))
        assert len(records) == 1

    @pytest.mark.parametrize("key", ["readings", "records", "data", "telemetry", "events", "items", "values"])
    def test_all_container_keys(self, tmp_path: Path, key: str) -> None:
        path = tmp_path / "data.json"
        path.write_text(json.dumps({key: [{"sensor_id": "A"}]}), encoding="utf-8")
        assert len(list(JsonTelemetryParser().read(SourceConfig(path=path)))) == 1

    def test_reads_single_object(self, tmp_path: Path) -> None:
        path = tmp_path / "data.json"
        path.write_text(json.dumps({"sensor_id": "A", "value": 1}), encoding="utf-8")
        records = list(JsonTelemetryParser().read(SourceConfig(path=path)))
        assert len(records) == 1

    def test_reads_nested_container_object(self, tmp_path: Path) -> None:
        path = tmp_path / "data.json"
        path.write_text(json.dumps({"data": {"sensor_id": "A"}}), encoding="utf-8")
        assert len(list(JsonTelemetryParser().read(SourceConfig(path=path)))) == 1

    def test_malformed_json_raises_parse_error(self, tmp_path: Path) -> None:
        path = tmp_path / "bad.json"
        path.write_text("{not json", encoding="utf-8")
        with pytest.raises(ParseError):
            list(JsonTelemetryParser().read(SourceConfig(path=path)))

    def test_missing_file_raises_parse_error(self, tmp_path: Path) -> None:
        with pytest.raises(ParseError):
            list(JsonTelemetryParser().read(SourceConfig(path=tmp_path / "nope.json")))

    def test_invalid_encoding_raises_parse_error(self, tmp_path: Path) -> None:
        path = tmp_path / "bad.json"
        path.write_bytes(b"\xff\xfe\x00bad")
        with pytest.raises(ParseError):
            list(JsonTelemetryParser().read(SourceConfig(path=path)))

    def test_scalar_root_raises_parse_error(self, tmp_path: Path) -> None:
        path = tmp_path / "bad.json"
        path.write_text("42", encoding="utf-8")
        with pytest.raises(ParseError):
            list(JsonTelemetryParser().read(SourceConfig(path=path)))

    def test_scalar_container_raises_parse_error(self, tmp_path: Path) -> None:
        path = tmp_path / "bad.json"
        path.write_text(json.dumps({"readings": 42}), encoding="utf-8")
        with pytest.raises(ParseError):
            list(JsonTelemetryParser().read(SourceConfig(path=path)))

    def test_parse_error_mentions_the_source(self, tmp_path: Path) -> None:
        path = tmp_path / "bad.json"
        path.write_text("{not json", encoding="utf-8")
        with pytest.raises(ParseError) as excinfo:
            list(JsonTelemetryParser().read(SourceConfig(path=path)))
        assert "bad.json" in str(excinfo.value)


class TestJsonlParser:
    """Behaviour of the newline-delimited JSON parser."""

    def test_reads_one_object_per_line(self, tmp_path: Path) -> None:
        path = tmp_path / "data.jsonl"
        path.write_text(
            '{"sensor_id": "A"}\n{"sensor_id": "B"}\n', encoding="utf-8"
        )
        records = list(JsonlTelemetryParser().read(SourceConfig(path=path)))
        assert len(records) == 2

    def test_blank_lines_are_skipped(self, tmp_path: Path) -> None:
        path = tmp_path / "data.jsonl"
        path.write_text('\n{"sensor_id": "A"}\n\n\n{"sensor_id": "B"}\n\n', encoding="utf-8")
        assert len(list(JsonlTelemetryParser().read(SourceConfig(path=path)))) == 2

    def test_malformed_line_is_skipped(self, tmp_path: Path) -> None:
        path = tmp_path / "data.jsonl"
        path.write_text('{"sensor_id": "A"}\nnot-json\n{"sensor_id": "B"}\n', encoding="utf-8")
        records = list(JsonlTelemetryParser().read(SourceConfig(path=path)))
        assert len(records) == 2

    def test_array_line_is_expanded(self, tmp_path: Path) -> None:
        path = tmp_path / "data.jsonl"
        path.write_text('[{"sensor_id": "A"}, {"sensor_id": "B"}]\n', encoding="utf-8")
        assert len(list(JsonlTelemetryParser().read(SourceConfig(path=path)))) == 2

    def test_non_object_line_is_ignored(self, tmp_path: Path) -> None:
        path = tmp_path / "data.jsonl"
        path.write_text('42\n{"sensor_id": "A"}\n', encoding="utf-8")
        records = list(JsonlTelemetryParser().read(SourceConfig(path=path)))
        assert len(records) == 1

    def test_array_line_with_non_object_items(self, tmp_path: Path) -> None:
        path = tmp_path / "data.jsonl"
        path.write_text('[1, "two", {"sensor_id": "A"}]\n', encoding="utf-8")
        records = list(JsonlTelemetryParser().read(SourceConfig(path=path)))
        assert len(records) == 1
        assert records[0]["sensor_id"] == "A"

    def test_empty_file_yields_nothing(self, tmp_path: Path) -> None:
        path = tmp_path / "data.jsonl"
        path.write_text("", encoding="utf-8")
        assert list(JsonlTelemetryParser().read(SourceConfig(path=path))) == []

    def test_missing_file_raises_parse_error(self, tmp_path: Path) -> None:
        with pytest.raises(ParseError):
            list(JsonlTelemetryParser().read(SourceConfig(path=tmp_path / "nope.jsonl")))

    def test_invalid_encoding_raises_parse_error(self, tmp_path: Path) -> None:
        path = tmp_path / "bad.jsonl"
        path.write_bytes(b"\xff\xfe\x00bad")
        with pytest.raises(ParseError):
            list(JsonlTelemetryParser().read(SourceConfig(path=path)))


class TestCsvParser:
    """Behaviour of the delimited-file parser."""

    def test_reads_standard_csv(self, tmp_path: Path) -> None:
        path = tmp_path / "data.csv"
        path.write_text(
            "sensor_id,machine_id,timestamp,value\nA,M1,2024-05-01T08:00:00Z,10\n",
            encoding="utf-8",
        )
        records = list(CsvTelemetryParser().read(SourceConfig(path=path)))
        assert records[0]["sensor_id"] == "A"
        assert records[0]["value"] == "10"

    def test_maps_legacy_headers(self, tmp_path: Path) -> None:
        path = tmp_path / "data.csv"
        path.write_text(
            "DeviceID,AssetID,eventTime,reading,units\n"
            "VIB-1,CONV-07,1714550400,12.5,Hz\n",
            encoding="utf-8",
        )
        records = list(CsvTelemetryParser().read(SourceConfig(path=path)))
        assert records[0]["sensor_id"] == "VIB-1"
        assert records[0]["machine_id"] == "CONV-07"
        assert records[0]["timestamp"] == "1714550400"
        assert records[0]["value"] == "12.5"
        assert records[0]["unit"] == "Hz"

    def test_semicolon_delimiter_is_detected(self, tmp_path: Path) -> None:
        path = tmp_path / "data.csv"
        path.write_text(
            "sensor_id;machine_id;timestamp;value\nA;M1;2024-05-01T08:00:00Z;10\n",
            encoding="utf-8",
        )
        records = list(CsvTelemetryParser().read(SourceConfig(path=path)))
        assert records[0]["sensor_id"] == "A"

    def test_tab_delimiter_is_detected(self, tmp_path: Path) -> None:
        path = tmp_path / "data.tsv"
        path.write_text(
            "sensor_id\tmachine_id\ttimestamp\tvalue\nA\tM1\t2024-05-01T08:00:00Z\t10\n",
            encoding="utf-8",
        )
        records = list(CsvTelemetryParser().read(SourceConfig(path=path)))
        assert records[0]["sensor_id"] == "A"

    def test_explicit_delimiter_is_used(self, tmp_path: Path) -> None:
        path = tmp_path / "data.csv"
        path.write_text(
            "sensor_id|machine_id|timestamp|value\nA|M1|2024-05-01T08:00:00Z|10\n",
            encoding="utf-8",
        )
        records = list(
            CsvTelemetryParser().read(SourceConfig(path=path, delimiter="|"))
        )
        assert records[0]["sensor_id"] == "A"

    def test_bom_is_stripped_from_header(self, tmp_path: Path) -> None:
        path = tmp_path / "data.csv"
        path.write_text(
            "\ufeffsensor_id,machine_id,timestamp,value\nA,M1,2024-05-01T08:00:00Z,10\n",
            encoding="utf-8",
        )
        records = list(CsvTelemetryParser().read(SourceConfig(path=path)))
        assert records[0]["sensor_id"] == "A"

    def test_blank_rows_are_skipped(self, tmp_path: Path) -> None:
        path = tmp_path / "data.csv"
        path.write_text(
            "sensor_id,machine_id,timestamp,value\n"
            "A,M1,2024-05-01T08:00:00Z,10\n"
            "\n"
            ",,,,\n"
            "B,M1,2024-05-01T08:01:00Z,11\n",
            encoding="utf-8",
        )
        records = list(CsvTelemetryParser().read(SourceConfig(path=path)))
        assert len(records) == 2

    def test_row_with_wrong_column_count_is_skipped(self, tmp_path: Path) -> None:
        path = tmp_path / "data.csv"
        path.write_text(
            "sensor_id,machine_id,timestamp,value\n"
            "A,M1,2024-05-01T08:00:00Z,10\n"
            "B,M1\n",
            encoding="utf-8",
        )
        records = list(CsvTelemetryParser().read(SourceConfig(path=path)))
        assert len(records) == 1

    def test_empty_file_yields_nothing(self, tmp_path: Path) -> None:
        path = tmp_path / "data.csv"
        path.write_text("", encoding="utf-8")
        assert list(CsvTelemetryParser().read(SourceConfig(path=path))) == []

    def test_whitespace_only_file_yields_nothing(self, tmp_path: Path) -> None:
        path = tmp_path / "data.csv"
        path.write_text("   \n  \n", encoding="utf-8")
        assert list(CsvTelemetryParser().read(SourceConfig(path=path))) == []

    def test_header_with_too_few_columns_raises(self, tmp_path: Path) -> None:
        path = tmp_path / "data.csv"
        path.write_text("a,b\n1,2\n", encoding="utf-8")
        with pytest.raises(ParseError):
            list(CsvTelemetryParser().read(SourceConfig(path=path)))

    def test_missing_file_raises_parse_error(self, tmp_path: Path) -> None:
        with pytest.raises(ParseError):
            list(CsvTelemetryParser().read(SourceConfig(path=tmp_path / "nope.csv")))

    def test_invalid_encoding_raises_parse_error(self, tmp_path: Path) -> None:
        path = tmp_path / "bad.csv"
        path.write_bytes(b"\xff\xfe\x00bad")
        with pytest.raises(ParseError):
            list(CsvTelemetryParser().read(SourceConfig(path=path)))

    def test_unknown_headers_are_kept_as_is(self, tmp_path: Path) -> None:
        path = tmp_path / "data.csv"
        path.write_text(
            "sensor_id,machine_id,timestamp,value,custom_field\n"
            "A,M1,2024-05-01T08:00:00Z,10,xyz\n",
            encoding="utf-8",
        )
        records = list(CsvTelemetryParser().read(SourceConfig(path=path)))
        assert records[0]["custom_field"] == "xyz"

    def test_empty_header_cell_is_skipped(self, tmp_path: Path) -> None:
        path = tmp_path / "data.csv"
        path.write_text(
            "sensor_id,,timestamp,value\n"
            "A,M1,2024-05-01T08:00:00Z,10\n",
            encoding="utf-8",
        )
        records = list(CsvTelemetryParser().read(SourceConfig(path=path)))
        assert "m1" not in records[0]
        assert records[0]["sensor_id"] == "A"


class TestRegistry:
    """Format detection and parser selection."""

    @pytest.mark.parametrize(
        ("filename", "expected"),
        [
            ("a.json", "json"),
            ("a.jsonl", "jsonl"),
            ("a.ndjson", "jsonl"),
            ("a.csv", "csv"),
            ("a.tsv", "csv"),
            ("a.txt", "csv"),
        ],
    )
    def test_detect_format_by_extension(self, tmp_path: Path, filename: str, expected: str) -> None:
        path = tmp_path / filename
        path.write_text("{}", encoding="utf-8")
        assert detect_format(path) == expected

    def test_detect_json_by_content(self, tmp_path: Path) -> None:
        path = tmp_path / "unknown.dat"
        path.write_text('[{"a": 1}]', encoding="utf-8")
        assert detect_format(path) == "json"

    def test_detect_jsonl_by_content(self, tmp_path: Path) -> None:
        path = tmp_path / "unknown.dat"
        path.write_text('{"a": 1}\n{"a": 2}\n', encoding="utf-8")
        assert detect_format(path) == "jsonl"

    def test_detect_csv_by_content(self, tmp_path: Path) -> None:
        path = tmp_path / "unknown.dat"
        path.write_text("a,b,c\n1,2,3\n", encoding="utf-8")
        assert detect_format(path) == "csv"

    def test_detect_csv_for_unreadable_file(self, tmp_path: Path) -> None:
        assert detect_format(tmp_path / "missing.dat") == "csv"

    @pytest.mark.parametrize(
        ("fmt", "expected_type"),
        [
            ("json", JsonTelemetryParser),
            ("jsonl", JsonlTelemetryParser),
            ("csv", CsvTelemetryParser),
        ],
    )
    def test_build_source_by_format(self, tmp_path: Path, fmt: str, expected_type: type) -> None:
        path = tmp_path / "data.txt"
        path.write_text("{}", encoding="utf-8")
        source = build_source(SourceConfig(path=path, format=fmt))
        assert isinstance(source, expected_type)

    def test_build_source_auto_detects(self, tmp_path: Path) -> None:
        path = tmp_path / "data.json"
        path.write_text("{}", encoding="utf-8")
        assert isinstance(build_source(SourceConfig(path=path, format="auto")), JsonTelemetryParser)

    def test_unknown_format_raises(self, tmp_path: Path) -> None:
        path = tmp_path / "data.json"
        path.write_text("{}", encoding="utf-8")
        with pytest.raises(ValueError):
            build_source(SourceConfig(path=path, format="avro"))

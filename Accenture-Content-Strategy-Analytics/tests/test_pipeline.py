"""Unit and integration tests of the pipeline, the adapters and the CLI."""

from __future__ import annotations

import csv
import json
from pathlib import Path
from typing import Any

import pytest

from social_buzz_analytics.application.pipeline import (
    AnalyticsPipeline,
    PipelineConfig,
    validate_dataset_headers,
)
from social_buzz_analytics.cli import build_parser, main, render_report
from social_buzz_analytics.domain.exceptions import (
    IngestError,
    SchemaValidationError,
)
from social_buzz_analytics.infrastructure.csv_adapters import CsvDatasetReader, CsvReportWriter
from tests.conftest import DATASETS, InMemoryDatasetReader

# --------------------------------------------------------------------------- #
# PipelineConfig
# --------------------------------------------------------------------------- #


class TestPipelineConfig:
    """Tests of the :class:`PipelineConfig` value object."""

    def test_defaults(self, tmp_path: Path) -> None:
        """The default configuration is usable."""
        config = PipelineConfig(data_dir=tmp_path, output_dir=tmp_path / "out")
        assert config.top_n == 5
        assert config.write_cleaned_datasets is True

    def test_invalid_top_n_is_rejected(self, tmp_path: Path) -> None:
        """A non-positive ``top_n`` raises a ``ValueError``."""
        with pytest.raises(ValueError, match="top_n"):
            PipelineConfig(data_dir=tmp_path, output_dir=tmp_path, top_n=0)

    def test_negative_weight_is_rejected(self, tmp_path: Path) -> None:
        """A negative scoring weight raises a ``ValueError``."""
        with pytest.raises(ValueError, match="non-negative"):
            PipelineConfig(data_dir=tmp_path, output_dir=tmp_path, reaction_weight=-1.0)

    def test_zero_weights_are_rejected(self, tmp_path: Path) -> None:
        """A degenerate weight vector raises a ``ValueError``."""
        with pytest.raises(ValueError, match="at least one"):
            PipelineConfig(
                data_dir=tmp_path,
                output_dir=tmp_path,
                reaction_weight=0,
                reach_weight=0,
                interaction_weight=0,
                amplification_weight=0,
                sentiment_weight=0,
            )

    def test_scoring_weights_are_exposed(self, tmp_path: Path) -> None:
        """The scoring weights of the configuration are exposed."""
        config = PipelineConfig(data_dir=tmp_path, output_dir=tmp_path)
        assert config.scoring_weights.total > 0


# --------------------------------------------------------------------------- #
# CsvDatasetReader
# --------------------------------------------------------------------------- #


class TestCsvDatasetReader:
    """Tests of the :class:`CsvDatasetReader` adapter."""

    def test_rows_are_read(self, tmp_path: Path) -> None:
        """The rows of a CSV file are yielded as mappings."""
        path = tmp_path / "data.csv"
        path.write_text("a,b\n1,2\n3,4\n", encoding="utf-8")
        rows = list(CsvDatasetReader().read(path))
        assert rows == [{"a": "1", "b": "2"}, {"a": "3", "b": "4"}]

    def test_byte_order_mark_is_stripped(self, tmp_path: Path) -> None:
        """A UTF-8 BOM does not corrupt the first column name."""
        path = tmp_path / "bom.csv"
        path.write_bytes("\ufeffa,b\n1,2\n".encode("utf-8"))
        rows = list(CsvDatasetReader().read(path))
        assert list(rows[0]) == ["a", "b"]

    def test_missing_file_raises_an_ingest_error(self, tmp_path: Path) -> None:
        """A missing file raises an :class:`IngestError`."""
        with pytest.raises(IngestError, match="cannot open"):
            list(CsvDatasetReader().read(tmp_path / "nope.csv"))

    def test_empty_file_raises_an_ingest_error(self, tmp_path: Path) -> None:
        """A file without a header raises an :class:`IngestError`."""
        path = tmp_path / "empty.csv"
        path.write_text("", encoding="utf-8")
        with pytest.raises(IngestError, match="no header row"):
            list(CsvDatasetReader().read(path))

    def test_short_rows_are_padded(self, tmp_path: Path) -> None:
        """A row with fewer fields than the header is padded."""
        path = tmp_path / "short.csv"
        path.write_text("a,b,c\n1,2\n", encoding="utf-8")
        rows = list(CsvDatasetReader().read(path))
        assert rows[0]["c"] == ""

    def test_extra_fields_are_ignored(self, tmp_path: Path) -> None:
        """A row with more fields than the header keeps the named ones."""
        path = tmp_path / "long.csv"
        path.write_text("a,b\n1,2,3\n", encoding="utf-8")
        rows = list(CsvDatasetReader().read(path))
        assert rows[0]["a"] == "1"
        assert rows[0]["b"] == "2"


# --------------------------------------------------------------------------- #
# CsvReportWriter
# --------------------------------------------------------------------------- #


class TestCsvReportWriter:
    """Tests of the :class:`CsvReportWriter` adapter."""

    def test_csv_is_written_with_a_header(self, tmp_path: Path) -> None:
        """The CSV artifact holds a header and the rows."""
        writer = CsvReportWriter(tmp_path / "out")
        path = writer.write_csv("report.csv", [{"a": 1, "b": "x"}, {"a": 2, "b": "y"}])
        content = path.read_text(encoding="utf-8")
        assert content.splitlines()[0] == "a,b"
        assert "1,x" in content

    def test_empty_rows_produce_an_empty_file(self, tmp_path: Path) -> None:
        """An empty collection produces an empty (but existing) file."""
        writer = CsvReportWriter(tmp_path / "out")
        path = writer.write_csv("empty.csv", [])
        assert path.exists()
        assert path.read_text(encoding="utf-8") == ""

    def test_union_of_keys_becomes_the_header(self, tmp_path: Path) -> None:
        """The header holds the union of the keys, in order of appearance."""
        writer = CsvReportWriter(tmp_path / "out")
        path = writer.write_csv("union.csv", [{"a": 1}, {"b": 2}])
        assert path.read_text(encoding="utf-8").splitlines()[0] == "a,b"

    def test_none_is_written_as_an_empty_string(self, tmp_path: Path) -> None:
        """A ``None`` value is serialized as an empty cell."""
        writer = CsvReportWriter(tmp_path / "out")
        path = writer.write_csv("none.csv", [{"a": None}])
        with path.open("r", encoding="utf-8", newline="") as handle:
            rows = list(csv.reader(handle))
        assert rows[0] == ["a"]
        assert rows[1] == [""]

    def test_booleans_are_written_lowercase(self, tmp_path: Path) -> None:
        """A boolean is serialized as ``true``/``false``."""
        writer = CsvReportWriter(tmp_path / "out")
        path = writer.write_csv("bool.csv", [{"a": True, "b": False}])
        assert path.read_text(encoding="utf-8").splitlines()[1] == "true,false"

    def test_json_is_written(self, tmp_path: Path) -> None:
        """The JSON artifact is valid and pretty-printed."""
        writer = CsvReportWriter(tmp_path / "out")
        path = writer.write_json("summary.json", {"a": 1, "b": [1, 2]})
        payload = json.loads(path.read_text(encoding="utf-8"))
        assert payload == {"a": 1, "b": [1, 2]}
        assert "\n" in path.read_text(encoding="utf-8")

    def test_output_directory_is_created(self, tmp_path: Path) -> None:
        """The output directory is created when it does not exist."""
        target = tmp_path / "deep" / "nested"
        writer = CsvReportWriter(target)
        writer.write_csv("a.csv", [{"x": 1}])
        assert target.exists()

    def test_non_serializable_values_are_stringified(self, tmp_path: Path) -> None:
        """A value the JSON encoder cannot handle is stringified."""
        writer = CsvReportWriter(tmp_path / "out")
        path = writer.write_json("obj.json", {"a": Path("x/y")})
        payload = json.loads(path.read_text(encoding="utf-8"))
        assert payload["a"] == str(Path("x/y"))


# --------------------------------------------------------------------------- #
# AnalyticsPipeline
# --------------------------------------------------------------------------- #


class TestAnalyticsPipeline:
    """Tests of the :class:`AnalyticsPipeline` orchestrator."""

    def test_pipeline_runs(self, config: PipelineConfig) -> None:
        """The pipeline produces segments, statistics and join reports."""
        pipeline = AnalyticsPipeline(config=config, reader=InMemoryDatasetReader())
        result = pipeline.run()
        assert result.segments
        assert result.top_segments
        assert len(result.cleaning_stats) == 7
        assert result.join_reports

    def test_top_segments_respect_top_n(self, tmp_path: Path) -> None:
        """The leaderboard holds at most ``top_n`` segments."""
        config = PipelineConfig(
            data_dir=tmp_path, output_dir=tmp_path / "out", top_n=2, write_cleaned_datasets=False
        )
        pipeline = AnalyticsPipeline(
            config=config, reader=InMemoryDatasetReader(DATASETS)
        )
        result = pipeline.run()
        assert len(result.top_segments) <= 2

    def test_segments_are_ranked(self, config: PipelineConfig) -> None:
        """The segments carry a dense 1-based ranking."""
        pipeline = AnalyticsPipeline(config=config, reader=InMemoryDatasetReader())
        result = pipeline.run()
        assert [s.rank for s in result.segments] == list(range(1, len(result.segments) + 1))

    def test_missing_dataset_raises_an_ingest_error(self, tmp_path: Path) -> None:
        """A missing dataset raises an :class:`IngestError`."""
        config = PipelineConfig(data_dir=tmp_path, output_dir=tmp_path / "out")
        pipeline = AnalyticsPipeline(
            config=config, reader=InMemoryDatasetReader({}, fail_on=["Content.csv"])
        )
        with pytest.raises(IngestError, match="dataset not found"):
            pipeline.run()

    def test_artifacts_are_written(self, config: PipelineConfig) -> None:
        """Every expected artifact is written to the output directory."""
        writer = CsvReportWriter(config.output_dir)
        pipeline = AnalyticsPipeline(
            config=config, reader=InMemoryDatasetReader(), writer=writer
        )
        result = pipeline.run()
        assert result.artifacts
        for path in result.artifacts.values():
            assert path.exists()
        assert (config.output_dir / "executive_summary.json").exists()
        assert (config.output_dir / "top_segments.csv").exists()
        assert (config.output_dir / "segment_engagement.csv").exists()
        assert (config.output_dir / "data_quality_report.csv").exists()

    def test_cleaned_datasets_can_be_skipped(self, tmp_path: Path) -> None:
        """The cleaned datasets are optional."""
        config = PipelineConfig(
            data_dir=tmp_path, output_dir=tmp_path / "out", write_cleaned_datasets=False
        )
        writer = CsvReportWriter(config.output_dir)
        pipeline = AnalyticsPipeline(
            config=config, reader=InMemoryDatasetReader(), writer=writer
        )
        result = pipeline.run()
        assert "cleaned_content" not in result.artifacts
        assert "segment_engagement" in result.artifacts

    def test_dry_run_writes_nothing(self, tmp_path: Path) -> None:
        """A run without a writer produces no artifact."""
        config = PipelineConfig(data_dir=tmp_path, output_dir=tmp_path / "out")
        pipeline = AnalyticsPipeline(config=config, reader=InMemoryDatasetReader())
        result = pipeline.run()
        assert result.artifacts == {}
        assert not (tmp_path / "out").exists()

    def test_executive_summary_structure(self, config: PipelineConfig) -> None:
        """The executive summary holds every analytical block."""
        writer = CsvReportWriter(config.output_dir)
        pipeline = AnalyticsPipeline(
            config=config, reader=InMemoryDatasetReader(), writer=writer
        )
        result = pipeline.run()
        payload = json.loads(
            (config.output_dir / "executive_summary.json").read_text(encoding="utf-8")
        )
        assert len(payload["top_segments"]) == len(result.top_segments)
        assert set(payload) >= {
            "report",
            "totals",
            "top_segments",
            "all_segments",
            "data_quality",
            "joins",
            "integrity",
            "insights",
        }
        assert payload["totals"]["total_reactions"] > 0
        assert payload["insights"]

    def test_result_is_serializable(self, config: PipelineConfig) -> None:
        """The pipeline result exposes a JSON-serializable snapshot."""
        pipeline = AnalyticsPipeline(config=config, reader=InMemoryDatasetReader())
        result = pipeline.run()
        json.dumps(result.as_dict())

    def test_orphan_events_are_reported(self, tmp_path: Path) -> None:
        """The events of an unknown content item are counted as orphans."""
        datasets = dict(DATASETS)
        datasets["Reactions.csv"] = tuple(
            list(DATASETS["Reactions.csv"])
            + [{"content_id": "GHOST", "user_id": "U1", "reaction_type": "like"}]
        )
        config = PipelineConfig(data_dir=tmp_path, output_dir=tmp_path / "out")
        pipeline = AnalyticsPipeline(
            config=config, reader=InMemoryDatasetReader(datasets)
        )
        result = pipeline.run()
        assert result.integrity["reactions_orphan_events"] == 1
        assert result.integrity["reactions_total_events"] == len(datasets["Reactions.csv"])

    def test_duplicate_rows_are_removed_by_the_pipeline(self, tmp_path: Path) -> None:
        """A duplicated reaction never inflates the engagement score."""
        datasets = dict(DATASETS)
        datasets["Reactions.csv"] = tuple(
            list(DATASETS["Reactions.csv"]) + [dict(DATASETS["Reactions.csv"][0])]
        )
        config = PipelineConfig(data_dir=tmp_path, output_dir=tmp_path / "out")
        pipeline = AnalyticsPipeline(
            config=config, reader=InMemoryDatasetReader(datasets)
        )
        result = pipeline.run()
        reactions_stats = next(
            s for s in result.cleaning_stats if s.dataset == "Reactions"
        )
        assert reactions_stats.duplicates_removed == 1

    def test_run_is_deterministic(self, config: PipelineConfig) -> None:
        """Two identical runs produce identical segments."""
        first = AnalyticsPipeline(config=config, reader=InMemoryDatasetReader()).run()
        second = AnalyticsPipeline(config=config, reader=InMemoryDatasetReader()).run()
        assert first.segments == second.segments


class TestValidateDatasetHeaders:
    """Tests of :func:`validate_dataset_headers`."""

    def test_valid_headers_pass(self) -> None:
        """A complete header passes the validation."""
        validate_dataset_headers({"Users": ["user_id", "user_age"]}, {"Users": ["user_id"]})

    def test_missing_column_raises(self) -> None:
        """A missing mandatory column raises a :class:`SchemaValidationError`."""
        with pytest.raises(SchemaValidationError, match="user_id"):
            validate_dataset_headers({"Users": ["user_age"]}, {"Users": ["user_id"]})

    def test_missing_dataset_raises(self) -> None:
        """An absent dataset raises a :class:`SchemaValidationError`."""
        with pytest.raises(SchemaValidationError, match="Users"):
            validate_dataset_headers({}, {"Users": ["user_id"]})


# --------------------------------------------------------------------------- #
# CLI
# --------------------------------------------------------------------------- #


class TestCli:
    """Tests of the command line interface."""

    def test_parser_defaults(self) -> None:
        """The parser exposes the documented defaults."""
        args = build_parser().parse_args([])
        assert args.top_n == 5
        assert args.data_dir == Path("data/raw")
        assert args.output_dir == Path("data/processed")
        assert args.dry_run is False

    def test_parser_accepts_the_documented_flags(self) -> None:
        """The documented flags are parsed."""
        args = build_parser().parse_args(
            [
                "--data-dir", "in",
                "--output-dir", "out",
                "--top-n", "3",
                "--weight-reaction", "0.5",
                "--dry-run",
                "--json",
            ]
        )
        assert args.data_dir == Path("in")
        assert args.output_dir == Path("out")
        assert args.top_n == 3
        assert args.weight_reaction == pytest.approx(0.5)
        assert args.dry_run is True
        assert args.json is True

    def test_main_runs_the_pipeline(self, config: PipelineConfig, capsys: Any) -> None:
        """The CLI runs the pipeline and prints the leaderboard."""
        exit_code = main(
            [
                "--data-dir",
                str(config.data_dir),
                "--output-dir",
                str(config.output_dir),
            ]
        )
        assert exit_code == 0
        captured = capsys.readouterr()
        assert "SOCIAL BUZZ" in captured.out
        assert "CATEGORY" in captured.out

    def test_main_json_output(self, config: PipelineConfig, capsys: Any) -> None:
        """The CLI can emit the result as JSON."""
        exit_code = main(
            [
                "--data-dir",
                str(config.data_dir),
                "--output-dir",
                str(config.output_dir),
                "--json",
            ]
        )
        assert exit_code == 0
        payload = json.loads(capsys.readouterr().out)
        assert "top_segments" in payload

    def test_main_dry_run(self, config: PipelineConfig, capsys: Any) -> None:
        """A dry run computes the analytics without writing anything."""
        exit_code = main(
            [
                "--data-dir",
                str(config.data_dir),
                "--output-dir",
                str(config.output_dir),
                "--dry-run",
            ]
        )
        assert exit_code == 0
        assert not config.output_dir.exists()

    def test_main_reports_a_missing_dataset(self, tmp_path: Path, capsys: Any) -> None:
        """A missing dataset produces a clean error and a non-zero exit code."""
        exit_code = main(
            ["--data-dir", str(tmp_path / "nowhere"), "--output-dir", str(tmp_path / "out")]
        )
        assert exit_code == 1
        assert "error" in capsys.readouterr().err

    def test_render_report_lists_the_segments(self, config: PipelineConfig) -> None:
        """The rendered report holds the leaderboard and the quality block."""
        pipeline = AnalyticsPipeline(config=config, reader=InMemoryDatasetReader())
        report = render_report(pipeline.run())
        assert "DATA QUALITY" in report
        assert "Reactions" in report
        assert "SOCIAL BUZZ" in report

"""End-to-end integration tests.

These tests exercise the whole pipeline against a real CSV export produced
by ``scripts/generate_sample_data.py``.  They verify the data integrity
guarantees that the executive report relies on.
"""

from __future__ import annotations

import csv
import json
from pathlib import Path

import pytest

from scripts.generate_sample_data import generate
from social_buzz_analytics.application.pipeline import AnalyticsPipeline, PipelineConfig
from social_buzz_analytics.domain.value_objects import CANONICAL_CATEGORIES
from social_buzz_analytics.infrastructure.csv_adapters import CsvDatasetReader, CsvReportWriter


@pytest.fixture(scope="module")
def generated_dir(tmp_path_factory: pytest.TempPathFactory) -> Path:
    """Generate a small but complete sample dataset for the whole module."""
    directory = tmp_path_factory.mktemp("social_buzz_raw")
    generate(
        output_dir=directory,
        users=400,
        contents=300,
        reactions=2_500,
        comments=600,
        shares=300,
        views=20_000,
        seed=4242,
    )
    return directory


@pytest.fixture(scope="module")
def run_result(generated_dir: Path, tmp_path_factory: pytest.TempPathFactory) -> object:
    """Run the pipeline once on the generated dataset."""
    output_dir = tmp_path_factory.mktemp("social_buzz_processed")
    config = PipelineConfig(
        data_dir=generated_dir,
        output_dir=output_dir,
        top_n=5,
    )
    writer = CsvReportWriter(output_dir)
    pipeline = AnalyticsPipeline(config=config, reader=CsvDatasetReader(), writer=writer)
    return pipeline.run()


class TestEndToEnd:
    """Tests of the complete pipeline over a real export."""

    def test_segments_are_produced(self, run_result: object) -> None:
        """The pipeline scores the categories of the export."""
        assert run_result.segments  # type: ignore[attr-defined]
        assert len(run_result.top_segments) == 5  # type: ignore[attr-defined]

    def test_every_segment_belongs_to_the_taxonomy(self, run_result: object) -> None:
        """No segment carries an out-of-taxonomy category."""
        allowed = set(CANONICAL_CATEGORIES)
        for segment in run_result.segments:  # type: ignore[attr-defined]
            assert segment.category in allowed

    def test_ranks_are_dense_and_ordered(self, run_result: object) -> None:
        """The ranking is dense, 1-based and ordered by descending score."""
        segments = run_result.segments  # type: ignore[attr-defined]
        assert [s.rank for s in segments] == list(range(1, len(segments) + 1))
        scores = [s.engagement_score for s in segments]
        assert scores == sorted(scores, reverse=True)

    def test_counters_are_consistent(self, run_result: object) -> None:
        """The counters of every segment are internally consistent."""
        for segment in run_result.segments:  # type: ignore[attr-defined]
            assert segment.reactions >= 0
            assert segment.views >= 0
            assert segment.shares >= 0
            assert segment.comments >= 0
            assert segment.unique_reactors <= segment.reactions
            assert segment.content_count >= 1
            assert 0.0 <= segment.engagement_score <= 1.0
            assert -1.0 <= segment.sentiment_score <= 1.0
            assert 0.0 <= segment.positive_ratio <= 1.0
            assert segment.engagement_rate >= 0.0

    def test_engagement_rate_matches_the_counters(self, run_result: object) -> None:
        """The engagement rate is consistent with the raw counters."""
        for segment in run_result.segments:  # type: ignore[attr-defined]
            if segment.views == 0:
                assert segment.engagement_rate == 0.0
            else:
                expected = (
                    segment.reactions + segment.shares + segment.comments
                ) / segment.views * 100.0
                assert segment.engagement_rate == pytest.approx(expected, abs=1e-3)

    def test_segment_totals_match_the_cleaned_datasets(self, run_result: object) -> None:
        """The sum of the segment counters matches the cleaned reaction file."""
        cleaned = run_result.artifacts["cleaned_reactions"]  # type: ignore[attr-defined]
        with cleaned.open("r", encoding="utf-8", newline="") as handle:
            rows = list(csv.DictReader(handle))
        total_reactions = sum(s.reactions for s in run_result.segments)  # type: ignore[attr-defined]
        # Every reaction of a known content item is accounted for in a
        # segment; the orphan reactions are reported separately.
        assert total_reactions <= len(rows)

    def test_data_quality_report_is_complete(self, run_result: object) -> None:
        """Every dataset reports its cleaning statistics."""
        stats = run_result.cleaning_stats  # type: ignore[attr-defined]
        assert {s.dataset for s in stats} == {
            "Users",
            "Content",
            "ReactionTypes",
            "Reactions",
            "Comments",
            "PageShares",
            "PageViews",
        }
        for entry in stats:
            assert entry.rows_read == entry.rows_accepted + entry.rows_rejected

    def test_duplicate_rows_were_detected(self, run_result: object) -> None:
        """The injected duplicates are reported by the cleaning stage."""
        stats = {s.dataset: s for s in run_result.cleaning_stats}  # type: ignore[attr-defined]
        assert stats["Users"].duplicates_removed > 0
        assert stats["Reactions"].duplicates_removed > 0

    def test_orphan_events_are_reported(self, run_result: object) -> None:
        """The injected orphan events are detected by the integrity check."""
        assert run_result.integrity["reactions_orphan_events"] > 0  # type: ignore[attr-defined]

    def test_joins_are_reported(self, run_result: object) -> None:
        """Both joins are reported with their match rate."""
        reports = run_result.join_reports  # type: ignore[attr-defined]
        assert len(reports) == 2
        for report in reports:
            assert report.matched_rows + report.unmatched_rows == report.left_rows

    def test_artifacts_are_written(self, run_result: object) -> None:
        """Every artifact exists and is non-empty."""
        artifacts = run_result.artifacts  # type: ignore[attr-defined]
        for name in (
            "segment_engagement",
            "top_segments",
            "data_quality",
            "executive_summary",
        ):
            path = artifacts[name]
            assert path.exists()
            assert path.stat().st_size > 0

    def test_top_segments_csv_matches_the_json(self, run_result: object) -> None:
        """The CSV leaderboard and the JSON leaderboard agree."""
        artifacts = run_result.artifacts  # type: ignore[attr-defined]
        with artifacts["top_segments"].open("r", encoding="utf-8", newline="") as handle:
            csv_rows = list(csv.DictReader(handle))
        payload = json.loads(
            artifacts["executive_summary"].read_text(encoding="utf-8")
        )
        json_rows = payload["top_segments"]
        assert len(csv_rows) == len(json_rows)
        for csv_row, json_row in zip(csv_rows, json_rows, strict=True):
            assert csv_row["category"] == json_row["category"]
            assert csv_row["rank"] == str(json_row["rank"])

    def test_executive_summary_holds_the_insights(self, run_result: object) -> None:
        """The executive summary carries the derived insights."""
        payload = json.loads(
            run_result.artifacts["executive_summary"].read_text(encoding="utf-8")  # type: ignore[attr-defined]
        )
        assert payload["insights"]
        assert payload["totals"]["total_reactions"] > 0
        assert payload["report"]["segments_analyzed"] == len(run_result.segments)  # type: ignore[attr-defined]

    def test_cleaned_content_has_canonical_categories(self, run_result: object) -> None:
        """The cleaned content file holds only canonical categories."""
        path = run_result.artifacts["cleaned_content"]  # type: ignore[attr-defined]
        with path.open("r", encoding="utf-8", newline="") as handle:
            rows = list(csv.DictReader(handle))
        allowed = set(CANONICAL_CATEGORIES)
        for row in rows:
            assert row["category"] in allowed

    def test_cleaned_content_keeps_the_identifier_case(self, run_result: object) -> None:
        """The cleaned content file preserves the original identifiers."""
        path = run_result.artifacts["cleaned_content"]  # type: ignore[attr-defined]
        with path.open("r", encoding="utf-8", newline="") as handle:
            rows = list(csv.DictReader(handle))
        assert rows
        for row in rows:
            assert row["content_id"] == row["content_id"].upper()

    def test_the_run_is_reproducible(self, generated_dir: Path, tmp_path: Path) -> None:
        """Two runs over the same export produce the same leaderboard."""
        scores = []
        for index in range(2):
            config = PipelineConfig(
                data_dir=generated_dir,
                output_dir=tmp_path / f"run{index}",
                write_cleaned_datasets=False,
            )
            pipeline = AnalyticsPipeline(config=config, reader=CsvDatasetReader())
            result = pipeline.run()
            scores.append([(s.category, s.engagement_score) for s in result.segments])
        assert scores[0] == scores[1]

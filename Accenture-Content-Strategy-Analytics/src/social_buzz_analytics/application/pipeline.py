"""Pipeline orchestration.

:class:`AnalyticsPipeline` wires the stages of the pipeline together:

1. **Ingest** - read the seven raw datasets through a
   :class:`~social_buzz_analytics.application.ports.DatasetReader`.
2. **Clean** - apply the per-dataset cleaning rules.
3. **Merge** - relate the datasets through ``content_id`` and
   ``reaction_type``.
4. **Aggregate** - score the content categories and rank the top segments.
5. **Report** - persist the analytical summaries as CSV and JSON.

The orchestrator only depends on the ports, so it can be driven by an
in-memory reader in the tests and by a CSV reader in production.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from ..domain.entities import (
    Comment,
    ContentItem,
    EngagementSegment,
    PageShare,
    PageView,
    Reaction,
    ReactionTypeDefinition,
    User,
)
from ..domain.exceptions import IngestError, SchemaValidationError
from ..domain.scoring import EngagementScoringService, ScoringWeights
from .datasets import (
    clean_comments,
    clean_content,
    clean_page_shares,
    clean_page_views,
    clean_reaction_types,
    clean_reactions,
    clean_users,
)
from .merging import (
    LEFT_JOIN,
    build_reaction_type_map,
    join_on_key,
    referential_integrity_report,
)
from .ports import (
    CleaningStats,
    DatasetReader,
    JoinReport,
    ReportWriter,
)

__all__ = [
    "AnalyticsPipeline",
    "PipelineConfig",
    "PipelineResult",
]


@dataclass(frozen=True, slots=True)
class PipelineConfig:
    """Configuration of a pipeline run.

    Attributes:
        data_dir: Directory holding the raw CSV datasets.
        output_dir: Directory receiving the analytical summaries.
        top_n: Number of segments kept in the executive leaderboard.
        max_rejection_rate: Maximum share of rows a dataset may lose.
        reaction_weight: Weight of the reaction volume in the composite score.
        reach_weight: Weight of the unique reach in the composite score.
        interaction_weight: Weight of the interaction rate in the composite score.
        amplification_weight: Weight of the share volume in the composite score.
        sentiment_weight: Weight of the sentiment polarity in the composite score.
        write_cleaned_datasets: Whether the cleaned datasets are exported.
    """

    data_dir: Path
    output_dir: Path
    top_n: int = 5
    max_rejection_rate: float = 0.95
    reaction_weight: float = 0.30
    reach_weight: float = 0.20
    interaction_weight: float = 0.25
    amplification_weight: float = 0.15
    sentiment_weight: float = 0.10
    write_cleaned_datasets: bool = True

    def __post_init__(self) -> None:
        """Validate the configuration.

        Raises
        ------
        ValueError
            If ``top_n`` is not strictly positive or if the scoring weights
            are invalid.
        """
        if self.top_n <= 0:
            raise ValueError("top_n must be strictly positive")
        ScoringWeights(
            volume=self.reaction_weight,
            reach=self.reach_weight,
            interaction=self.interaction_weight,
            amplification=self.amplification_weight,
            sentiment=self.sentiment_weight,
        )

    @property
    def scoring_weights(self) -> ScoringWeights:
        """The composite scoring weights described by this configuration."""
        return ScoringWeights(
            volume=self.reaction_weight,
            reach=self.reach_weight,
            interaction=self.interaction_weight,
            amplification=self.amplification_weight,
            sentiment=self.sentiment_weight,
        )


@dataclass(slots=True)
class PipelineResult:
    """Everything a pipeline run produced.

    Attributes:
        segments: All scored segments, ordered by descending score.
        top_segments: The ``top_n`` best segments.
        cleaning_stats: The cleaning statistics of every dataset.
        join_reports: The statistics of every join performed.
        integrity: Referential-integrity counters of the event datasets.
        artifacts: The paths of the written output files.
    """

    segments: list[EngagementSegment] = field(default_factory=list)
    top_segments: list[EngagementSegment] = field(default_factory=list)
    cleaning_stats: list[CleaningStats] = field(default_factory=list)
    join_reports: list[JoinReport] = field(default_factory=list)
    integrity: dict[str, int] = field(default_factory=dict)
    artifacts: dict[str, Path] = field(default_factory=dict)

    def as_dict(self) -> dict[str, Any]:
        """Return a JSON-serializable snapshot of the result."""
        return {
            "segments": [_segment_to_dict(s) for s in self.segments],
            "top_segments": [_segment_to_dict(s) for s in self.top_segments],
            "cleaning": [stats.as_dict() for stats in self.cleaning_stats],
            "joins": [report.as_dict() for report in self.join_reports],
            "integrity": dict(sorted(self.integrity.items())),
            "artifacts": {name: str(path) for name, path in sorted(self.artifacts.items())},
        }


class AnalyticsPipeline:
    """Orchestrates the end-to-end engagement and sentiment analytics run."""

    def __init__(
        self,
        config: PipelineConfig,
        reader: DatasetReader,
        writer: ReportWriter | None = None,
        scoring_service: EngagementScoringService | None = None,
    ) -> None:
        """Initialize the pipeline.

        Parameters
        ----------
        config:
            The configuration of the run.
        reader:
            The adapter used to read the raw datasets.
        writer:
            The adapter used to persist the summaries.  When ``None``, the
            run computes the analytics but writes nothing.
        scoring_service:
            The scoring service.  Defaults to a service configured with the
            weights of ``config``.
        """
        self._config = config
        self._reader = reader
        self._writer = writer
        self._scoring = scoring_service or EngagementScoringService(config.scoring_weights)

    @property
    def config(self) -> PipelineConfig:
        """The configuration of the run."""
        return self._config

    def run(self) -> PipelineResult:
        """Execute the whole pipeline and return its result.

        Returns
        -------
        PipelineResult
            The segments, the statistics and the produced artifacts.
        """
        users, stats_users = self._clean_users()
        contents, stats_content = self._clean_content()
        reaction_types, stats_reaction_types = self._clean_reaction_types()
        reactions, stats_reactions = self._clean_reactions()
        comments, stats_comments = self._clean_comments()
        shares, stats_shares = self._clean_page_shares()
        views, stats_views = self._clean_page_views()

        join_reports = self._perform_joins(contents, reactions, reaction_types)
        integrity = self._check_integrity(contents, reactions, comments, shares, views)

        segments = self._scoring.score_segments(
            contents=contents,
            reactions=reactions,
            views=views,
            shares=shares,
            comments=comments,
            reaction_types=build_reaction_type_map(reaction_types),
        )

        result = PipelineResult(
            segments=segments,
            top_segments=segments[: self._config.top_n],
            cleaning_stats=[
                stats_users,
                stats_content,
                stats_reaction_types,
                stats_reactions,
                stats_comments,
                stats_shares,
                stats_views,
            ],
            join_reports=join_reports,
            integrity=integrity,
        )

        if self._writer is not None:
            result.artifacts = self._write_artifacts(
                result,
                users=users,
                contents=contents,
                reactions=reactions,
                reaction_types=reaction_types,
                comments=comments,
                shares=shares,
                views=views,
            )
        return result

    # ------------------------------------------------------------------ #
    # Stage helpers
    # ------------------------------------------------------------------ #

    def _read(self, filename: str) -> list[Mapping[str, Any]]:
        """Read a raw dataset from the configured data directory.

        Raises
        ------
        IngestError
            If the dataset cannot be read.
        """
        path = self._config.data_dir / filename
        try:
            return list(self._reader.read(path))
        except FileNotFoundError as exc:
            raise IngestError(f"dataset not found: {path}") from exc
        except OSError as exc:
            raise IngestError(f"dataset could not be read: {path} ({exc})") from exc

    def _clean_users(self) -> tuple[list[User], CleaningStats]:
        """Read and clean the ``Users`` dataset."""
        return clean_users(self._read("Users.csv"), self._config.max_rejection_rate)

    def _clean_content(self) -> tuple[list[ContentItem], CleaningStats]:
        """Read and clean the ``Content`` dataset."""
        return clean_content(self._read("Content.csv"), self._config.max_rejection_rate)

    def _clean_reaction_types(self) -> tuple[list[ReactionTypeDefinition], CleaningStats]:
        """Read and clean the ``ReactionTypes`` dataset."""
        return clean_reaction_types(
            self._read("ReactionTypes.csv"), self._config.max_rejection_rate
        )

    def _clean_reactions(self) -> tuple[list[Reaction], CleaningStats]:
        """Read and clean the ``Reactions`` dataset."""
        return clean_reactions(self._read("Reactions.csv"), self._config.max_rejection_rate)

    def _clean_comments(self) -> tuple[list[Comment], CleaningStats]:
        """Read and clean the ``Comments`` dataset."""
        return clean_comments(self._read("Comments.csv"), self._config.max_rejection_rate)

    def _clean_page_shares(self) -> tuple[list[PageShare], CleaningStats]:
        """Read and clean the ``PageShares`` dataset."""
        return clean_page_shares(self._read("PageShares.csv"), self._config.max_rejection_rate)

    def _clean_page_views(self) -> tuple[list[PageView], CleaningStats]:
        """Read and clean the ``PageViews`` dataset."""
        return clean_page_views(self._read("PageViews.csv"), self._config.max_rejection_rate)

    def _perform_joins(
        self,
        contents: Sequence[ContentItem],
        reactions: Sequence[Reaction],
        reaction_types: Sequence[ReactionTypeDefinition],
    ) -> list[JoinReport]:
        """Relate the datasets through ``content_id`` and ``reaction_type``."""
        reports: list[JoinReport] = []

        _, report = join_on_key(
            left=list(reactions),
            right=list(reaction_types),
            left_key=lambda r: r.reaction_type,
            right_key=lambda d: d.reaction_type,
            strategy=LEFT_JOIN,
            name="Reactions x ReactionTypes (reaction_type)",
        )
        reports.append(report)

        _, report = join_on_key(
            left=list(reactions),
            right=list(contents),
            left_key=lambda r: r.content_id,
            right_key=lambda c: c.content_id,
            strategy=LEFT_JOIN,
            name="Reactions x Content (content_id)",
        )
        reports.append(report)

        return reports

    def _check_integrity(
        self,
        contents: Sequence[ContentItem],
        reactions: Sequence[Reaction],
        comments: Sequence[Comment],
        shares: Sequence[PageShare],
        views: Sequence[PageView],
    ) -> dict[str, int]:
        """Count the orphan events of every event dataset."""
        content_ids = {content.content_id for content in contents}
        integrity: dict[str, int] = {}
        integrity.update(
            referential_integrity_report(
                reactions, content_ids, lambda r: r.content_id, "reactions"
            )
        )
        integrity.update(
            referential_integrity_report(comments, content_ids, lambda c: c.content_id, "comments")
        )
        integrity.update(
            referential_integrity_report(shares, content_ids, lambda s: s.content_id, "shares")
        )
        integrity.update(
            referential_integrity_report(views, content_ids, lambda v: v.content_id, "views")
        )
        return integrity

    def _write_artifacts(
        self,
        result: PipelineResult,
        users: Sequence[User],
        contents: Sequence[ContentItem],
        reactions: Sequence[Reaction],
        reaction_types: Sequence[ReactionTypeDefinition],
        comments: Sequence[Comment],
        shares: Sequence[PageShare],
        views: Sequence[PageView],
    ) -> dict[str, Path]:
        """Persist the analytical summaries."""
        assert self._writer is not None  # noqa: S101 - guarded by the caller
        artifacts: dict[str, Path] = {}

        artifacts["segment_engagement"] = self._writer.write_csv(
            "segment_engagement.csv",
            [_segment_to_dict(segment) for segment in result.segments],
        )
        artifacts["top_segments"] = self._writer.write_csv(
            "top_segments.csv",
            [_segment_to_dict(segment) for segment in result.top_segments],
        )
        artifacts["data_quality"] = self._writer.write_csv(
            "data_quality_report.csv", [stats.as_dict() for stats in result.cleaning_stats]
        )
        artifacts["executive_summary"] = self._writer.write_json(
            "executive_summary.json", self._build_executive_summary(result)
        )

        if self._config.write_cleaned_datasets:
            artifacts["cleaned_content"] = self._writer.write_csv(
                "cleaned_content.csv",
                [
                    {
                        "content_id": c.content_id,
                        "content_type": str(c.content_type),
                        "category": c.category,
                        "category_id": c.category_id,
                        "score": c.score,
                        "content_author_id": c.content_author_id,
                        "url": c.url,
                        "created_at": c.created_at.isoformat() if c.created_at else "",
                    }
                    for c in contents
                ],
            )
            artifacts["cleaned_users"] = self._writer.write_csv(
                "cleaned_users.csv",
                [
                    {
                        "user_id": u.user_id,
                        "segment": str(u.segment),
                        "country": u.country,
                        "age": "" if u.age is None else u.age,
                        "followers": u.followers,
                        "created_at": u.created_at.isoformat() if u.created_at else "",
                    }
                    for u in users
                ],
            )
            artifacts["cleaned_reactions"] = self._writer.write_csv(
                "cleaned_reactions.csv",
                [
                    {
                        "content_id": r.content_id,
                        "user_id": r.user_id,
                        "reaction_type": str(r.reaction_type),
                    }
                    for r in reactions
                ],
            )
            artifacts["cleaned_comments"] = self._writer.write_csv(
                "cleaned_comments.csv",
                [
                    {
                        "comment_id": c.comment_id,
                        "content_id": c.content_id,
                        "user_id": c.user_id,
                        "sentiment": c.sentiment,
                        "sentiment_label": str(c.label),
                        "commented_at": c.commented_at.isoformat() if c.commented_at else "",
                    }
                    for c in comments
                ],
            )
            artifacts["cleaned_shares"] = self._writer.write_csv(
                "cleaned_shares.csv",
                [
                    {
                        "content_id": s.content_id,
                        "share_user_id": s.share_user_id,
                        "shared_at": s.shared_at.isoformat() if s.shared_at else "",
                    }
                    for s in shares
                ],
            )
            artifacts["cleaned_views"] = self._writer.write_csv(
                "cleaned_views.csv",
                [
                    {
                        "content_id": v.content_id,
                        "view_user_id": v.view_user_id,
                        "view_seconds": v.view_seconds,
                        "viewed_at": v.viewed_at.isoformat() if v.viewed_at else "",
                    }
                    for v in views
                ],
            )
            artifacts["reaction_types"] = self._writer.write_csv(
                "cleaned_reaction_types.csv",
                [
                    {
                        "reaction_type": str(d.reaction_type),
                        "score": d.score,
                        "sentiment": str(d.sentiment),
                    }
                    for d in reaction_types
                ],
            )
        return artifacts

    def _build_executive_summary(self, result: PipelineResult) -> dict[str, Any]:
        """Build the JSON payload consumed by the executive reporting layer."""
        segments = result.segments
        total_reactions = sum(s.reactions for s in segments)
        total_views = sum(s.views for s in segments)
        total_shares = sum(s.shares for s in segments)
        total_comments = sum(s.comments for s in segments)
        return {
            "report": {
                "title": "Social Buzz - Content Engagement & Sentiment Analytics",
                "client": "Social Buzz",
                "segments_analyzed": len(segments),
                "top_n": self._config.top_n,
                "scoring_weights": {
                    "volume": self._scoring.weights.volume,
                    "reach": self._scoring.weights.reach,
                    "interaction": self._scoring.weights.interaction,
                    "amplification": self._scoring.weights.amplification,
                    "sentiment": self._scoring.weights.sentiment,
                },
            },
            "totals": {
                "total_reactions": total_reactions,
                "total_views": total_views,
                "total_shares": total_shares,
                "total_comments": total_comments,
                "total_content": sum(s.content_count for s in segments),
            },
            "top_segments": [_segment_to_dict(s) for s in result.top_segments],
            "all_segments": [_segment_to_dict(s) for s in segments],
            "data_quality": [stats.as_dict() for stats in result.cleaning_stats],
            "joins": [report.as_dict() for report in result.join_reports],
            "integrity": dict(sorted(result.integrity.items())),
            "insights": _build_insights(result),
        }


def _build_insights(result: PipelineResult) -> list[str]:
    """Derive the executive insights from the scored segments."""
    segments = result.segments
    if not segments:
        return ["No segment could be scored: every dataset was empty or fully rejected."]

    insights: list[str] = []
    leader = segments[0]
    insights.append(
        f"'{leader.category}' is the top performing segment with an engagement score of "
        f"{leader.engagement_score:.4f} across {leader.content_count} content items."
    )

    if len(segments) > 1:
        runner_up = segments[1]
        gap = leader.engagement_score - runner_up.engagement_score
        insights.append(
            f"'{runner_up.category}' follows at {runner_up.engagement_score:.4f} "
            f"(gap of {gap:.4f} to the leader)."
        )

    most_negative = min(segments, key=lambda s: s.sentiment_score)
    if most_negative.sentiment_score < 0:
        insights.append(
            f"'{most_negative.category}' carries the weakest sentiment "
            f"({most_negative.sentiment_score:.4f}) and needs a content-quality review."
        )
    else:
        insights.append(
            f"All segments carry a non-negative sentiment; the weakest is "
            f"'{most_negative.category}' at {most_negative.sentiment_score:.4f}."
        )

    best_rate = max(segments, key=lambda s: s.engagement_rate)
    insights.append(
        f"'{best_rate.category}' has the highest interaction rate "
        f"({best_rate.engagement_rate:.2f}% of views convert into an interaction)."
    )

    total_rejected = sum(stats.rows_rejected for stats in result.cleaning_stats)
    total_read = sum(stats.rows_read for stats in result.cleaning_stats)
    if total_read:
        rate = total_rejected / total_read * 100.0
        insights.append(
            f"Data quality: {total_rejected:,} of {total_read:,} source rows "
            f"({rate:.2f}%) were rejected during harmonization."
        )
    return insights


def _segment_to_dict(segment: EngagementSegment) -> dict[str, Any]:
    """Convert a segment entity into a flat, serializable mapping."""
    return {
        "rank": segment.rank,
        "category": segment.category,
        "engagement_score": segment.engagement_score,
        "engagement_rate": segment.engagement_rate,
        "sentiment_score": segment.sentiment_score,
        "positive_ratio": segment.positive_ratio,
        "reactions": segment.reactions,
        "weighted_reaction_score": segment.weighted_reaction_score,
        "unique_reactors": segment.unique_reactors,
        "content_count": segment.content_count,
        "views": segment.views,
        "shares": segment.shares,
        "comments": segment.comments,
    }


def validate_dataset_headers(
    headers: Mapping[str, Sequence[str]], expected: Mapping[str, Sequence[str]]
) -> None:
    """Validate that every dataset exposes its mandatory columns.

    Parameters
    ----------
    headers:
        The header of each dataset, keyed by dataset name.
    expected:
        The mandatory columns of each dataset, keyed by dataset name.

    Raises
    ------
    SchemaValidationError
        If a mandatory column is missing.
    """
    for name, required in expected.items():
        actual = set(headers.get(name, ()))
        missing = [column for column in required if column not in actual]
        if missing:
            raise SchemaValidationError(
                f"dataset {name!r} is missing the mandatory column(s): {', '.join(missing)}"
            )

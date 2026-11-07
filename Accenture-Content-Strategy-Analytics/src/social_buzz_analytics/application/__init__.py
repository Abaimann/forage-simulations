"""Application layer of the Social Buzz analytics pipeline.

This layer orchestrates the use cases (cleaning, merging, aggregating and
reporting) and depends only on the domain and on the ports declared in
:mod:`social_buzz_analytics.application.ports`.
"""

from __future__ import annotations

from .cleaning import (
    CleaningContext,
    harmonize_category,
    parse_bool,
    parse_datetime,
    parse_float,
    parse_int,
    parse_non_negative_int,
    winsorize,
)
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
    INNER_JOIN,
    LEFT_JOIN,
    JoinStrategy,
    join_on_key,
    referential_integrity_report,
)
from .pipeline import AnalyticsPipeline, PipelineConfig, PipelineResult
from .ports import (
    CleaningStats,
    ContentRepository,
    DatasetReader,
    JoinReport,
    ReactionRepository,
    ReactionTypeRepository,
    ReportWriter,
    UserRepository,
)

__all__ = [
    "AnalyticsPipeline",
    "CleaningContext",
    "CleaningStats",
    "ContentRepository",
    "DatasetReader",
    "INNER_JOIN",
    "LEFT_JOIN",
    "JoinReport",
    "JoinStrategy",
    "PipelineConfig",
    "PipelineResult",
    "ReactionRepository",
    "ReactionTypeRepository",
    "ReportWriter",
    "UserRepository",
    "clean_comments",
    "clean_content",
    "clean_page_shares",
    "clean_page_views",
    "clean_reaction_types",
    "clean_reactions",
    "clean_users",
    "harmonize_category",
    "join_on_key",
    "parse_bool",
    "parse_datetime",
    "parse_float",
    "parse_int",
    "parse_non_negative_int",
    "referential_integrity_report",
    "winsorize",
]

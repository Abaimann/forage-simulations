"""Domain layer of the Social Buzz analytics pipeline."""

from __future__ import annotations

from .entities import (
    Comment,
    ContentItem,
    EngagementSegment,
    PageShare,
    PageView,
    Reaction,
    ReactionTypeDefinition,
    User,
)
from .exceptions import (
    AnalyticsError,
    CategoryNotFoundError,
    DataQualityError,
    DuplicateRecordError,
    IngestError,
    JoinKeyError,
    SchemaValidationError,
)
from .scoring import EngagementScoringService, ScoringWeights, SegmentAccumulator
from .value_objects import (
    CANONICAL_CATEGORIES,
    CATEGORY_ALIASES,
    Channel,
    ContentType,
    ReactionType,
    SentimentLabel,
    UserSegment,
    canonical_text,
    normalize_category,
)

__all__ = [
    "AnalyticsError",
    "CANONICAL_CATEGORIES",
    "CATEGORY_ALIASES",
    "CategoryNotFoundError",
    "Channel",
    "Comment",
    "ContentItem",
    "ContentType",
    "DataQualityError",
    "DuplicateRecordError",
    "EngagementScoringService",
    "EngagementSegment",
    "IngestError",
    "JoinKeyError",
    "PageShare",
    "PageView",
    "Reaction",
    "ReactionType",
    "ReactionTypeDefinition",
    "SchemaValidationError",
    "ScoringWeights",
    "SegmentAccumulator",
    "SentimentLabel",
    "User",
    "UserSegment",
    "canonical_text",
    "normalize_category",
]

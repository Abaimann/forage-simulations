"""Core domain entities of the Social Buzz content-engagement domain.

The entities mirror the seven source datasets of the Social Buzz platform
(``Content``, ``Reactions``, ``ReactionTypes``, ``Users``, ``Comments``,
``PageShares``, ``PageViews``) after cleaning.

Each entity is an immutable dataclass that carries already-validated data.
Entities never contain raw, unclean values: the cleaning layer is
responsible for converting raw CSV cells into these types and guarantees
that the invariants documented on each attribute hold.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime

from .value_objects import ContentType, ReactionType, SentimentLabel, UserSegment

__all__ = [
    "Comment",
    "ContentItem",
    "EngagementSegment",
    "PageShare",
    "PageView",
    "Reaction",
    "ReactionTypeDefinition",
    "User",
]


@dataclass(frozen=True, slots=True)
class ReactionTypeDefinition:
    """Reference definition of a reaction type and its engagement weight.

    Attributes:
        reaction_type: The canonical reaction type.
        score: The engagement weight of the reaction (positive = amplifying).
        sentiment: Sentiment polarity of the reaction.
    """

    reaction_type: ReactionType
    score: int
    sentiment: SentimentLabel

    @classmethod
    def default(cls, reaction_type: ReactionType) -> ReactionTypeDefinition:
        """Build the canonical definition of ``reaction_type``."""
        return cls(
            reaction_type=reaction_type,
            score=reaction_type.score,
            sentiment=reaction_type.sentiment,
        )


@dataclass(frozen=True, slots=True)
class User:
    """An audience member interacting with the platform.

    Attributes:
        user_id: Primary key of the user.
        segment: Lifecycle segment of the user.
        country: ISO country code of the user (``Unknown`` when missing).
        age: Age of the user in years (``None`` when missing or out of range).
        followers: Number of followers of the user (never negative).
        created_at: Account creation timestamp (may be ``None``).
    """

    user_id: str
    segment: UserSegment
    country: str
    age: int | None
    followers: int
    created_at: datetime | None


@dataclass(frozen=True, slots=True)
class ContentItem:
    """A piece of content published on the platform.

    Attributes:
        content_id: Primary key of the content item.
        content_type: Format of the content.
        category: Canonical category display name.
        category_id: Raw category identifier as exported by the platform.
        content_body: Body text of the content (may be empty).
        url: Canonical URL of the content (may be empty).
        score: Editorial score of the content (never negative).
        content_author_id: Identifier of the author (may be empty).
        created_at: Publication timestamp (may be ``None``).
    """

    content_id: str
    content_type: ContentType
    category: str
    category_id: str
    content_body: str
    url: str
    score: int
    content_author_id: str
    created_at: datetime | None


@dataclass(frozen=True, slots=True)
class Reaction:
    """A single reaction event emitted by a user against a content item.

    Attributes:
        content_id: Foreign key referencing a :class:`ContentItem`.
        user_id: Foreign key referencing a :class:`User`.
        reaction_type: Canonical reaction type.
    """

    content_id: str
    user_id: str
    reaction_type: ReactionType


@dataclass(frozen=True, slots=True)
class Comment:
    """A comment written by a user on a content item.

    Attributes:
        comment_id: Primary key of the comment.
        content_id: Foreign key referencing a :class:`ContentItem`.
        user_id: Foreign key referencing a :class:`User`.
        sentiment: Continuous sentiment polarity in the ``[-1, 1]`` range.
        label: Coarse sentiment label derived from ``sentiment``.
        commented_at: Timestamp of the comment (may be ``None``).
    """

    comment_id: str
    content_id: str
    user_id: str
    sentiment: float
    label: SentimentLabel
    commented_at: datetime | None


@dataclass(frozen=True, slots=True)
class PageShare:
    """A share of a content item by a user.

    Attributes:
        content_id: Foreign key referencing a :class:`ContentItem`.
        share_user_id: Foreign key referencing a :class:`User`.
        shared_at: Timestamp of the share (may be ``None``).
    """

    content_id: str
    share_user_id: str
    shared_at: datetime | None


@dataclass(frozen=True, slots=True)
class PageView:
    """A page view of a content item by a user.

    Attributes:
        content_id: Foreign key referencing a :class:`ContentItem`.
        view_user_id: Foreign key referencing a :class:`User`.
        view_seconds: Dwell time of the view in seconds (never negative).
        viewed_at: Timestamp of the view (may be ``None``).
    """

    content_id: str
    view_user_id: str
    view_seconds: int
    viewed_at: datetime | None


@dataclass(frozen=True, slots=True)
class EngagementSegment:
    """Aggregated engagement score of one content category.

    Attributes:
        category: Canonical category display name.
        rank: 1-based rank of the segment in the engagement leaderboard.
        content_count: Number of distinct content items in the segment.
        reactions: Number of reaction events in the segment.
        weighted_reaction_score: Sum of the reaction weights in the segment.
        unique_reactors: Number of distinct reacting users.
        views: Number of page views in the segment.
        shares: Number of shares in the segment.
        comments: Number of comments in the segment.
        engagement_rate: Interactions (reactions + shares + comments) per
            view, expressed in percent.
        sentiment_score: Mean sentiment polarity in the ``[-1, 1]`` range.
        positive_ratio: Share of the comments classified as positive.
        engagement_score: Composite engagement score of the segment.
    """

    category: str
    rank: int
    content_count: int
    reactions: int
    weighted_reaction_score: int
    unique_reactors: int
    views: int
    shares: int
    comments: int
    engagement_rate: float
    sentiment_score: float
    positive_ratio: float
    engagement_score: float

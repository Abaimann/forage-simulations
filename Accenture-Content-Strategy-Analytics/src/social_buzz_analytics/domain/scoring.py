"""Domain services implementing the engagement scoring business rules.

The scoring model is deliberately transparent and auditable: every number
that reaches the executive report can be traced back to a documented formula
and to the raw counters that feed it.  This is a hard requirement for a
pre-IPO client, where an engagement number may end up in an investor deck.
"""

from __future__ import annotations

from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass

from .entities import (
    Comment,
    ContentItem,
    EngagementSegment,
    PageShare,
    PageView,
    Reaction,
    ReactionTypeDefinition,
)
from .value_objects import ReactionType, SentimentLabel

__all__ = [
    "EngagementScoringService",
    "ScoringWeights",
    "SegmentAccumulator",
    "sentiment_label_for",
]


@dataclass(frozen=True, slots=True)
class ScoringWeights:
    """Relative weights of the composite engagement score.

    The composite score is a convex combination of five min-max normalized
    signals.  The weights must be non-negative and are normalized to sum to
    ``1.0`` before use, so a caller may pass raw ratios.

    Attributes:
        volume: Weight of the weighted reaction volume.
        reach: Weight of the unique-reach signal (distinct reactors).
        interaction: Weight of the view-driven interaction rate.
        amplification: Weight of the share volume.
        sentiment: Weight of the sentiment polarity.
    """

    volume: float = 0.30
    reach: float = 0.20
    interaction: float = 0.25
    amplification: float = 0.15
    sentiment: float = 0.10

    def __post_init__(self) -> None:
        """Validate that the weights are usable.

        Raises
        ------
        ValueError
            If any weight is negative or if all weights are zero.
        """
        if any(w < 0 for w in self._raw_values()):
            raise ValueError("scoring weights must be non-negative")
        if self.total == 0:
            raise ValueError("at least one scoring weight must be positive")

    def _raw_values(self) -> tuple[float, ...]:
        """Return the raw weight values."""
        return (self.volume, self.reach, self.interaction, self.amplification, self.sentiment)

    @property
    def total(self) -> float:
        """Sum of the raw weights."""
        return sum(self._raw_values())

    def normalized(self) -> ScoringWeights:
        """Return the weights rescaled so that they sum to ``1.0``."""
        total = self.total
        return ScoringWeights(
            volume=self.volume / total,
            reach=self.reach / total,
            interaction=self.interaction / total,
            amplification=self.amplification / total,
            sentiment=self.sentiment / total,
        )


class SegmentAccumulator:
    """Mutable accumulator of the counters of a single content category.

    The accumulator is a write-heavy hot-spot that is updated once per
    interaction event.  It is exposed through a read-only
    :meth:`to_segment` method so that the rest of the application only ever
    sees immutable entities.

    Attributes:
        category: Canonical category display name.
    """

    __slots__ = (
        "_category",
        "_comment_count",
        "_content_ids",
        "_positive_comments",
        "_reactions",
        "_sentiment_sum",
        "_shares",
        "_unique_reactors",
        "_views",
        "_weighted_score",
    )

    def __init__(self, category: str) -> None:
        """Create an empty accumulator for ``category``."""
        self._category = category
        self._content_ids: set[str] = set()
        self._unique_reactors: set[str] = set()
        self._reactions = 0
        self._weighted_score = 0
        self._sentiment_sum = 0.0
        self._views = 0
        self._shares = 0
        self._comment_count = 0
        self._positive_comments = 0

    @property
    def category(self) -> str:
        """Canonical category display name."""
        return self._category

    @property
    def content_count(self) -> int:
        """Number of distinct content items in the segment."""
        return len(self._content_ids)

    @property
    def reactions(self) -> int:
        """Number of reaction events in the segment."""
        return self._reactions

    @property
    def weighted_score(self) -> int:
        """Sum of the reaction weights in the segment."""
        return self._weighted_score

    @property
    def unique_reactors(self) -> int:
        """Number of distinct reacting users."""
        return len(self._unique_reactors)

    @property
    def views(self) -> int:
        """Number of page views in the segment."""
        return self._views

    @property
    def shares(self) -> int:
        """Number of shares in the segment."""
        return self._shares

    @property
    def comments(self) -> int:
        """Number of comments in the segment."""
        return self._comment_count

    @property
    def interactions(self) -> int:
        """Total interactions (reactions + shares + comments)."""
        return self._reactions + self._shares + self._comment_count

    @property
    def engagement_rate(self) -> float:
        """Interactions per view, expressed in percent."""
        if self._views == 0:
            return 0.0
        return self.interactions / self._views * 100.0

    @property
    def mean_sentiment(self) -> float:
        """Mean sentiment polarity of the segment."""
        if self._comment_count == 0:
            return 0.0
        return self._sentiment_sum / self._comment_count

    @property
    def positive_ratio(self) -> float:
        """Share of the comments classified as positive."""
        if self._comment_count == 0:
            return 0.0
        return self._positive_comments / self._comment_count

    def add_content(self, content_id: str) -> None:
        """Register a content item as belonging to this segment."""
        self._content_ids.add(content_id)

    def add_reaction(self, user_id: str, definition: ReactionTypeDefinition) -> None:
        """Fold a reaction into the accumulator."""
        self._reactions += 1
        self._weighted_score += definition.score
        self._unique_reactors.add(user_id)

    def add_view(self) -> None:
        """Fold a page view into the accumulator."""
        self._views += 1

    def add_share(self) -> None:
        """Fold a share into the accumulator."""
        self._shares += 1

    def add_comment(self, comment: Comment) -> None:
        """Fold a comment into the accumulator."""
        self._comment_count += 1
        self._sentiment_sum += comment.sentiment
        if comment.label is SentimentLabel.POSITIVE:
            self._positive_comments += 1

    def to_segment(self, rank: int, engagement_score: float) -> EngagementSegment:
        """Materialize the immutable segment entity.

        Parameters
        ----------
        rank:
            1-based rank of the segment.
        engagement_score:
            Composite engagement score computed by the scoring service.

        Returns
        -------
        EngagementSegment
            The immutable snapshot of the accumulator.
        """
        engagement_rate = (self.interactions / self._views * 100.0) if self._views > 0 else 0.0
        return EngagementSegment(
            category=self._category,
            rank=rank,
            content_count=self.content_count,
            reactions=self._reactions,
            weighted_reaction_score=self._weighted_score,
            unique_reactors=self.unique_reactors,
            views=self._views,
            shares=self._shares,
            comments=self._comment_count,
            engagement_rate=round(engagement_rate, 4),
            sentiment_score=round(self.mean_sentiment, 4),
            positive_ratio=round(self.positive_ratio, 4),
            engagement_score=round(engagement_score, 4),
        )


class EngagementScoringService:
    """Computes the composite engagement score of every content category.

    The service is stateless and therefore safe to reuse across runs.

    The composite score of a segment is a convex combination of five
    min-max normalized signals::

        engagement_score = 0.30 * volume
                        + 0.20 * reach
                        + 0.25 * interaction
                        + 0.15 * amplification
                        + 0.10 * sentiment

    where ``volume`` is the weighted reaction score, ``reach`` the number of
    distinct reactors, ``interaction`` the interactions per view,
    ``amplification`` the share volume and ``sentiment`` the mean comment
    polarity shifted into ``[0, 1]``.
    """

    def __init__(self, weights: ScoringWeights | None = None) -> None:
        """Initialize the service with the composite scoring weights."""
        self._weights = (weights or ScoringWeights()).normalized()

    @property
    def weights(self) -> ScoringWeights:
        """The normalized scoring weights in use."""
        return self._weights

    def score_segments(
        self,
        contents: Sequence[ContentItem],
        reactions: Sequence[Reaction],
        views: Sequence[PageView],
        shares: Sequence[PageShare],
        comments: Sequence[Comment],
        reaction_types: Mapping[ReactionType, ReactionTypeDefinition] | None = None,
    ) -> list[EngagementSegment]:
        """Aggregate, score and rank the content categories.

        Orphan events (those whose ``content_id`` is unknown) are skipped:
        they must not pollute the segment statistics.

        Parameters
        ----------
        contents:
            The cleaned content items.
        reactions:
            The cleaned reaction events.
        views:
            The cleaned page views.
        shares:
            The cleaned shares.
        comments:
            The cleaned comments.
        reaction_types:
            Optional mapping of reaction type to its definition.  When
            omitted, the canonical built-in definitions are used.

        Returns
        -------
        list[EngagementSegment]
            The segments ordered by descending engagement score, with a
            1-based ``rank`` assigned.  Ties are broken deterministically by
            category name so that the output is reproducible.
        """
        definitions = dict(reaction_types or {})
        for reaction_type in ReactionType:
            definitions.setdefault(reaction_type, ReactionTypeDefinition.default(reaction_type))

        category_by_content = {content.content_id: content.category for content in contents}

        accumulators: dict[str, SegmentAccumulator] = {}
        for content in contents:
            accumulator = accumulators.setdefault(
                content.category, SegmentAccumulator(content.category)
            )
            accumulator.add_content(content.content_id)

        for reaction in reactions:
            category = category_by_content.get(reaction.content_id)
            if category is None:
                continue
            definition = definitions.get(reaction.reaction_type)
            if definition is None:
                definition = ReactionTypeDefinition.default(reaction.reaction_type)
            accumulators.setdefault(category, SegmentAccumulator(category)).add_reaction(
                reaction.user_id, definition
            )

        for view in views:
            category = category_by_content.get(view.content_id)
            if category is None:
                continue
            accumulators.setdefault(category, SegmentAccumulator(category)).add_view()

        for share in shares:
            category = category_by_content.get(share.content_id)
            if category is None:
                continue
            accumulators.setdefault(category, SegmentAccumulator(category)).add_share()

        for comment in comments:
            category = category_by_content.get(comment.content_id)
            if category is None:
                continue
            accumulators.setdefault(category, SegmentAccumulator(category)).add_comment(comment)

        scored = self._score(accumulators)
        scored.sort(key=lambda segment: (-segment.engagement_score, segment.category))
        return [_with_rank(segment, rank) for rank, segment in enumerate(scored, start=1)]

    def _score(self, accumulators: Mapping[str, SegmentAccumulator]) -> list[EngagementSegment]:
        """Compute the composite score of every accumulator and materialize it."""
        if not accumulators:
            return []

        norm_volume = _min_max_normalize(
            {name: float(acc.weighted_score) for name, acc in accumulators.items()}
        )
        norm_reach = _min_max_normalize(
            {name: float(acc.unique_reactors) for name, acc in accumulators.items()}
        )
        norm_interaction = _min_max_normalize(
            {name: acc.engagement_rate for name, acc in accumulators.items()}
        )
        norm_amplification = _min_max_normalize(
            {name: float(acc.shares) for name, acc in accumulators.items()}
        )
        norm_sentiment = _min_max_normalize(
            {name: (acc.mean_sentiment + 1.0) / 2.0 for name, acc in accumulators.items()}
        )

        segments: list[EngagementSegment] = []
        for name, acc in accumulators.items():
            score = (
                self._weights.volume * norm_volume[name]
                + self._weights.reach * norm_reach[name]
                + self._weights.interaction * norm_interaction[name]
                + self._weights.amplification * norm_amplification[name]
                + self._weights.sentiment * norm_sentiment[name]
            )
            segments.append(acc.to_segment(rank=0, engagement_score=score))
        return segments


def _with_rank(segment: EngagementSegment, rank: int) -> EngagementSegment:
    """Return a copy of ``segment`` with a different ``rank``."""
    return EngagementSegment(
        category=segment.category,
        rank=rank,
        content_count=segment.content_count,
        reactions=segment.reactions,
        weighted_reaction_score=segment.weighted_reaction_score,
        unique_reactors=segment.unique_reactors,
        views=segment.views,
        shares=segment.shares,
        comments=segment.comments,
        engagement_rate=segment.engagement_rate,
        sentiment_score=segment.sentiment_score,
        positive_ratio=segment.positive_ratio,
        engagement_score=segment.engagement_score,
    )


def _min_max_normalize(values: Mapping[str, float]) -> dict[str, float]:
    """Normalize ``values`` into the ``[0, 1]`` range using min-max scaling.

    Degenerate inputs are handled explicitly:

    * an empty mapping yields an empty result;
    * a mapping whose values are all equal yields ``0.5`` for every entry,
      because no segment can be distinguished from another.
    """
    if not values:
        return {}
    numbers = list(values.values())
    low = min(numbers)
    high = max(numbers)
    if high == low:
        return {key: 0.5 for key in values}
    span = high - low
    return {key: (value - low) / span for key, value in values.items()}


def sentiment_label_for(score: float, neutral_band: float = 0.1) -> SentimentLabel:
    """Translate a continuous sentiment score into a coarse label."""
    return SentimentLabel.from_score(score, neutral_band)


def iter_or_empty(items: Iterable[object]) -> list[object]:
    """Materialize an iterable into a list (convenience helper)."""
    return list(items)

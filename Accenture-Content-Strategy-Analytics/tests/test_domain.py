"""Unit tests of the domain layer.

The suite covers the value objects, the entities and the engagement
scoring service, including every documented edge case.
"""

from __future__ import annotations

import dataclasses
from datetime import datetime, timezone

import pytest

from social_buzz_analytics.domain.entities import (
    Comment,
    ContentItem,
    EngagementSegment,
    PageShare,
    PageView,
    Reaction,
    ReactionTypeDefinition,
    User,
)
from social_buzz_analytics.domain.scoring import (
    EngagementScoringService,
    ScoringWeights,
    SegmentAccumulator,
    sentiment_label_for,
)
from social_buzz_analytics.domain.value_objects import (
    CATEGORY_ALIASES,
    Channel,
    ContentType,
    ReactionType,
    SentimentLabel,
    UserSegment,
    canonical_text,
    normalize_category,
)

# --------------------------------------------------------------------------- #
# canonical_text
# --------------------------------------------------------------------------- #


class TestCanonicalText:
    """Tests of :func:`canonical_text`."""

    @pytest.mark.parametrize(
        ("raw", "expected"),
        [
            (None, ""),
            ("", ""),
            ("  Hello   World ", "hello world"),
            ("TABS\t\tAND\nNEWLINES", "tabs and newlines"),
            ("Ünïcödé", "ünïcödé"),
            (123, "123"),
            (12.5, "12.5"),
            (True, "true"),
        ],
    )
    def test_canonical_forms(self, raw: object, expected: str) -> None:
        """The canonical form is lower-cased, collapsed and trimmed."""
        assert canonical_text(raw) == expected

    def test_is_idempotent(self) -> None:
        """Canonicalizing an already canonical value changes nothing."""
        once = canonical_text("  Social   Buzz  ")
        assert canonical_text(once) == once


# --------------------------------------------------------------------------- #
# ReactionType
# --------------------------------------------------------------------------- #


class TestReactionType:
    """Tests of the :class:`ReactionType` value object."""

    @pytest.mark.parametrize(
        ("raw", "expected"),
        [
            ("like", ReactionType.LIKE),
            ("LIKE", ReactionType.LIKE),
            ("  Like ", ReactionType.LIKE),
            ("likes", ReactionType.LIKE),
            ("thumbs_up", ReactionType.LIKE),
            ("love", ReactionType.LOVE),
            ("heart", ReactionType.LOVE),
            ("lol", ReactionType.HAHA),
            ("insight", ReactionType.INSIGHTFUL),
            ("curiosity", ReactionType.CURIOUS),
            ("mad", ReactionType.ANGRY),
        ],
    )
    def test_from_raw_resolves_aliases(self, raw: str, expected: ReactionType) -> None:
        """Aliases and casing variants resolve to the canonical type."""
        assert ReactionType.from_raw(raw) is expected

    def test_from_raw_accepts_an_enum_member(self) -> None:
        """An enum member is returned unchanged."""
        assert ReactionType.from_raw(ReactionType.LOVE) is ReactionType.LOVE

    def test_from_raw_rejects_unknown_labels(self) -> None:
        """An unknown label raises a ``ValueError``."""
        with pytest.raises(ValueError, match="unknown reaction type"):
            ReactionType.from_raw("confused")

    def test_from_raw_rejects_empty_labels(self) -> None:
        """An empty label raises a ``ValueError``."""
        with pytest.raises(ValueError):
            ReactionType.from_raw("   ")

    def test_scores_are_signed(self) -> None:
        """Amplifying reactions score positive, hostile ones negative."""
        assert ReactionType.LIKE.score > 0
        assert ReactionType.INSIGHTFUL.score > 0
        assert ReactionType.SAD.score < 0
        assert ReactionType.ANGRY.score < 0

    def test_sentiment_polarity(self) -> None:
        """Every reaction carries the expected sentiment polarity."""
        assert ReactionType.LOVE.sentiment is SentimentLabel.POSITIVE
        assert ReactionType.CURIOUS.sentiment is SentimentLabel.NEUTRAL
        assert ReactionType.ANGRY.sentiment is SentimentLabel.NEGATIVE

    def test_str_is_the_value(self) -> None:
        """``str()`` returns the raw value."""
        assert str(ReactionType.LOVE) == "love"


# --------------------------------------------------------------------------- #
# SentimentLabel
# --------------------------------------------------------------------------- #


class TestSentimentLabel:
    """Tests of the :class:`SentimentLabel` value object."""

    @pytest.mark.parametrize(
        ("score", "expected"),
        [
            (0.9, SentimentLabel.POSITIVE),
            (0.11, SentimentLabel.POSITIVE),
            (0.1, SentimentLabel.NEUTRAL),
            (0.0, SentimentLabel.NEUTRAL),
            (-0.1, SentimentLabel.NEUTRAL),
            (-0.11, SentimentLabel.NEGATIVE),
            (-1.0, SentimentLabel.NEGATIVE),
        ],
    )
    def test_from_score(self, score: float, expected: SentimentLabel) -> None:
        """A continuous score is mapped onto a coarse polarity."""
        assert SentimentLabel.from_score(score) is expected

    @pytest.mark.parametrize("score", [5.0, -5.0, 1e9, -1e9])
    def test_from_score_clamps_out_of_range(self, score: float) -> None:
        """Scores outside ``[-1, 1]`` are clamped, not rejected."""
        assert SentimentLabel.from_score(score) in {
            SentimentLabel.POSITIVE,
            SentimentLabel.NEUTRAL,
            SentimentLabel.NEGATIVE,
        }
        assert SentimentLabel.from_score(5.0) is SentimentLabel.POSITIVE
        assert SentimentLabel.from_score(-5.0) is SentimentLabel.NEGATIVE

    def test_custom_neutral_band(self) -> None:
        """The neutral band is configurable."""
        assert SentimentLabel.from_score(0.2, neutral_band=0.3) is SentimentLabel.NEUTRAL
        assert SentimentLabel.from_score(0.2, neutral_band=0.1) is SentimentLabel.POSITIVE

    def test_sign(self) -> None:
        """Every label exposes its numeric sign."""
        assert SentimentLabel.POSITIVE.sign == 1
        assert SentimentLabel.NEUTRAL.sign == 0
        assert SentimentLabel.NEGATIVE.sign == -1

    def test_sentiment_label_for_helper(self) -> None:
        """The module level helper delegates to the value object."""
        assert sentiment_label_for(0.5) is SentimentLabel.POSITIVE
        assert sentiment_label_for(-0.5) is SentimentLabel.NEGATIVE


# --------------------------------------------------------------------------- #
# ContentType / UserSegment / Channel
# --------------------------------------------------------------------------- #


class TestContentType:
    """Tests of the :class:`ContentType` value object."""

    @pytest.mark.parametrize(
        ("raw", "expected"),
        [
            ("video", ContentType.VIDEO),
            ("VIDEO", ContentType.VIDEO),
            ("photo", ContentType.IMAGE),
            ("blog", ContentType.ARTICLE),
            ("url", ContentType.LINK),
            ("status", ContentType.POST),
            ("stories", ContentType.STORY),
            ("short", ContentType.REEL),
            ("livestream", ContentType.LIVE),
        ],
    )
    def test_from_raw(self, raw: str, expected: ContentType) -> None:
        """Aliases resolve to the canonical content type."""
        assert ContentType.from_raw(raw) is expected

    def test_from_raw_rejects_unknown(self) -> None:
        """An unknown type raises a ``ValueError``."""
        with pytest.raises(ValueError, match="unknown content type"):
            ContentType.from_raw("hologram")


class TestUserSegment:
    """Tests of the :class:`UserSegment` value object."""

    @pytest.mark.parametrize(
        ("raw", "expected"),
        [
            ("new", UserSegment.NEW),
            ("Newcomer", UserSegment.NEW),
            ("power_user", UserSegment.POWER_USER),
            ("Power User", UserSegment.POWER_USER),
            ("VIP", UserSegment.VIP),
            ("at_risk", UserSegment.CHURN_RISK),
        ],
    )
    def test_from_raw(self, raw: str, expected: UserSegment) -> None:
        """Aliases resolve to the canonical segment."""
        assert UserSegment.from_raw(raw) is expected

    @pytest.mark.parametrize("raw", ["", "   ", "unknown-segment", None])
    def test_unknown_degrades_to_active(self, raw: object) -> None:
        """An unknown segment never removes a user from the funnel."""
        assert UserSegment.from_raw(raw) is UserSegment.ACTIVE

    def test_from_raw_accepts_an_enum_member(self) -> None:
        """An enum member is returned unchanged."""
        assert UserSegment.from_raw(UserSegment.VIP) is UserSegment.VIP


class TestChannel:
    """Tests of the :class:`Channel` value object."""

    @pytest.mark.parametrize(
        ("raw", "expected"),
        [
            ("instagram", Channel.INSTAGRAM),
            ("IG", Channel.INSTAGRAM),
            ("twitter", Channel.X),
            ("x", Channel.X),
            ("tt", Channel.TIKTOK),
            ("email", Channel.NEWSLETTER),
        ],
    )
    def test_from_raw(self, raw: str, expected: Channel) -> None:
        """Aliases resolve to the canonical channel."""
        assert Channel.from_raw(raw) is expected

    def test_from_raw_rejects_unknown(self) -> None:
        """An unknown channel raises a ``ValueError``."""
        with pytest.raises(ValueError, match="unknown channel"):
            Channel.from_raw("carrier-pigeon")


# --------------------------------------------------------------------------- #
# Categories
# --------------------------------------------------------------------------- #


class TestNormalizeCategory:
    """Tests of the category taxonomy."""

    @pytest.mark.parametrize(
        ("raw", "expected"),
        [
            ("Technology", "Technology"),
            ("technology", "Technology"),
            ("tech", "Technology"),
            ("TECH", "Technology"),
            ("entertainment", "Entertainment"),
            ("entertaiment", "Entertainment"),
            ("ENT", "Entertainment"),
            ("sports", "Sports"),
            ("Sport", "Sports"),
            ("Life Style", "Lifestyle"),
            ("Health & Wellness", "Health"),
            ("Food & Drink", "Food"),
            ("games", "Gaming"),
            ("Educational", "Education"),
        ],
    )
    def test_known_labels(self, raw: str, expected: str) -> None:
        """The known labels resolve onto the canonical taxonomy."""
        assert normalize_category(raw) == expected

    @pytest.mark.parametrize("raw", ["", "   ", None, "completely-unknown-topic"])
    def test_unknown_labels_fall_back(self, raw: object) -> None:
        """An unresolvable label falls back to ``Other``."""
        assert normalize_category(raw) == "Other"

    def test_custom_default(self) -> None:
        """The fallback display name is configurable."""
        assert normalize_category("zzz", default="Uncategorised") == "Uncategorised"

    def test_alias_table_is_consistent(self) -> None:
        """Every alias maps onto a non-empty display name."""
        for alias, display in CATEGORY_ALIASES.items():
            assert alias == alias.strip().lower()
            assert display


# --------------------------------------------------------------------------- #
# Entities
# --------------------------------------------------------------------------- #


class TestEntities:
    """Tests of the domain entities."""

    def test_entities_are_immutable(self) -> None:
        """The entities are frozen dataclasses."""
        user = User(
            user_id="U1",
            segment=UserSegment.ACTIVE,
            country="ID",
            age=30,
            followers=10,
            created_at=None,
        )
        with pytest.raises(dataclasses.FrozenInstanceError):
            user.followers = 11  # type: ignore[misc]

    def test_reaction_type_definition_default(self) -> None:
        """The default definition mirrors the value object."""
        definition = ReactionTypeDefinition.default(ReactionType.LOVE)
        assert definition.score == ReactionType.LOVE.score
        assert definition.sentiment is ReactionType.LOVE.sentiment

    def test_entities_accept_optional_timestamps(self) -> None:
        """A missing timestamp is represented by ``None``."""
        content = ContentItem(
            content_id="C1",
            content_type=ContentType.POST,
            category="Other",
            category_id="",
            content_body="",
            url="",
            score=0,
            content_author_id="",
            created_at=None,
        )
        assert content.created_at is None

    def test_segment_equality(self) -> None:
        """Two segments with identical fields compare equal."""
        args = {
            "category": "Technology",
            "rank": 1,
            "content_count": 1,
            "reactions": 2,
            "weighted_reaction_score": 3,
            "unique_reactors": 1,
            "views": 10,
            "shares": 1,
            "comments": 1,
            "engagement_rate": 40.0,
            "sentiment_score": 0.5,
            "positive_ratio": 0.5,
            "engagement_score": 0.9,
        }
        assert EngagementSegment(**args) == EngagementSegment(**args)


# --------------------------------------------------------------------------- #
# ScoringWeights
# --------------------------------------------------------------------------- #


class TestScoringWeights:
    """Tests of the :class:`ScoringWeights` value object."""

    def test_defaults_are_valid(self) -> None:
        """The default weights are usable."""
        assert ScoringWeights().total > 0

    def test_negative_weight_is_rejected(self) -> None:
        """A negative weight raises a ``ValueError``."""
        with pytest.raises(ValueError, match="non-negative"):
            ScoringWeights(volume=-0.1)

    def test_all_zero_weights_are_rejected(self) -> None:
        """A degenerate weight vector raises a ``ValueError``."""
        with pytest.raises(ValueError, match="at least one"):
            ScoringWeights(volume=0, reach=0, interaction=0, amplification=0, sentiment=0)

    def test_normalization_sums_to_one(self) -> None:
        """The normalized weights form a convex combination."""
        normalized = ScoringWeights(volume=2, reach=2, interaction=2, amplification=2, sentiment=2)
        assert normalized.normalized().total == pytest.approx(1.0)

    def test_normalization_preserves_the_ratios(self) -> None:
        """Normalizing does not change the relative order of the weights."""
        weights = ScoringWeights(
            volume=0.4, reach=0.3, interaction=0.2, amplification=0.1, sentiment=0
        )
        normalized = weights.normalized()
        assert normalized.volume > normalized.reach > normalized.interaction
        assert normalized.amplification > normalized.sentiment


# --------------------------------------------------------------------------- #
# SegmentAccumulator
# --------------------------------------------------------------------------- #


class TestSegmentAccumulator:
    """Tests of the :class:`SegmentAccumulator`."""

    def test_empty_accumulator(self) -> None:
        """A fresh accumulator holds zeros and a neutral sentiment."""
        accumulator = SegmentAccumulator("Technology")
        assert accumulator.reactions == 0
        assert accumulator.unique_reactors == 0
        assert accumulator.content_count == 0
        assert accumulator.views == 0
        assert accumulator.interactions == 0
        assert accumulator.mean_sentiment == 0.0
        assert accumulator.positive_ratio == 0.0
        assert accumulator.engagement_rate == 0.0

    def test_counts_are_accumulated(self) -> None:
        """Reactions, content, views and shares are folded in."""
        accumulator = SegmentAccumulator("Technology")
        definition = ReactionTypeDefinition.default(ReactionType.LIKE)
        accumulator.add_content("C1")
        accumulator.add_content("C1")
        accumulator.add_content("C2")
        accumulator.add_reaction("U1", definition)
        accumulator.add_reaction("U2", definition)
        accumulator.add_view()
        accumulator.add_view()
        accumulator.add_share()

        assert accumulator.reactions == 2
        assert accumulator.weighted_score == 2
        assert accumulator.unique_reactors == 2
        assert accumulator.content_count == 2
        assert accumulator.views == 2
        assert accumulator.shares == 1
        # interactions = reactions + shares + comments (the views are the
        # denominator of the engagement rate, not an interaction).
        assert accumulator.interactions == 3

    def test_engagement_rate_is_interactions_per_view(self) -> None:
        """The engagement rate is expressed in percent."""
        accumulator = SegmentAccumulator("Technology")
        definition = ReactionTypeDefinition.default(ReactionType.LIKE)
        accumulator.add_reaction("U1", definition)
        for _ in range(4):
            accumulator.add_view()
        assert accumulator.engagement_rate == pytest.approx(25.0)

    def test_to_segment_materializes_an_entity(self) -> None:
        """The accumulator materializes an immutable segment."""
        accumulator = SegmentAccumulator("Technology")
        accumulator.add_content("C1")
        accumulator.add_view()
        segment = accumulator.to_segment(rank=1, engagement_score=0.75)
        assert isinstance(segment, EngagementSegment)
        assert segment.rank == 1
        assert segment.engagement_score == pytest.approx(0.75)
        assert segment.category == "Technology"


# --------------------------------------------------------------------------- #
# EngagementScoringService
# --------------------------------------------------------------------------- #


def _content(content_id: str, category: str) -> ContentItem:
    """Build a minimal content item for the scoring tests."""
    return ContentItem(
        content_id=content_id,
        content_type=ContentType.POST,
        category=category,
        category_id=category,
        content_body="",
        url="",
        score=0,
        content_author_id="",
        created_at=None,
    )


def _reaction(content_id: str, user_id: str, reaction_type: ReactionType) -> Reaction:
    """Build a reaction for the scoring tests."""
    return Reaction(content_id=content_id, user_id=user_id, reaction_type=reaction_type)


class TestEngagementScoringService:
    """Tests of the :class:`EngagementScoringService`."""

    def test_empty_input_yields_no_segment(self) -> None:
        """An empty corpus produces no segment at all."""
        service = EngagementScoringService()
        assert service.score_segments([], [], [], [], []) == []

    def test_single_segment_is_scored(self) -> None:
        """A single segment is scored and ranked first."""
        service = EngagementScoringService()
        segments = service.score_segments(
            contents=[_content("C1", "Technology")],
            reactions=[_reaction("C1", "U1", ReactionType.LIKE)],
            views=[],
            shares=[],
            comments=[],
        )
        assert len(segments) == 1
        assert segments[0].rank == 1
        assert segments[0].reactions == 1
        assert segments[0].weighted_reaction_score == ReactionType.LIKE.score

    def test_segments_are_ranked_by_descending_score(self) -> None:
        """The segments are ordered by descending engagement score."""
        service = EngagementScoringService()
        segments = service.score_segments(
            contents=[
                _content("C1", "Technology"),
                _content("C2", "Sports"),
                _content("C3", "Food"),
            ],
            reactions=[
                _reaction("C1", "U1", ReactionType.LOVE),
                _reaction("C1", "U2", ReactionType.LOVE),
                _reaction("C1", "U3", ReactionType.WOW),
                _reaction("C2", "U4", ReactionType.LIKE),
            ],
            views=[],
            shares=[],
            comments=[],
        )
        assert [s.category for s in segments] == ["Technology", "Sports", "Food"]
        assert [s.rank for s in segments] == [1, 2, 3]
        assert segments[0].engagement_score >= segments[1].engagement_score
        assert segments[1].engagement_score >= segments[2].engagement_score

    def test_orphan_reactions_are_ignored(self) -> None:
        """A reaction pointing at an unknown content item is skipped."""
        service = EngagementScoringService()
        segments = service.score_segments(
            contents=[_content("C1", "Technology")],
            reactions=[
                _reaction("C1", "U1", ReactionType.LIKE),
                _reaction("GHOST", "U2", ReactionType.LOVE),
            ],
            views=[],
            shares=[],
            comments=[],
        )
        assert segments[0].reactions == 1
        assert segments[0].weighted_reaction_score == ReactionType.LIKE.score

    def test_orphan_views_shares_and_comments_are_ignored(self) -> None:
        """Every event type ignores the events of an unknown content item."""
        service = EngagementScoringService()
        segments = service.score_segments(
            contents=[_content("C1", "Technology")],
            reactions=[],
            views=[PageView("GHOST", "U1", 10, None)],
            shares=[PageShare("GHOST", "U1", None)],
            comments=[
                Comment(
                    "CM1", "GHOST", "U1", 0.5, SentimentLabel.POSITIVE, None
                )
            ],
        )
        assert segments[0].views == 0
        assert segments[0].shares == 0
        assert segments[0].comments == 0

    def test_custom_reaction_type_definitions_are_honoured(self) -> None:
        """A custom definition overrides the built-in weight."""
        service = EngagementScoringService()
        definitions = {
            ReactionType.LIKE: ReactionTypeDefinition(
                ReactionType.LIKE, 99, SentimentLabel.POSITIVE
            )
        }
        segments = service.score_segments(
            contents=[_content("C1", "Technology")],
            reactions=[_reaction("C1", "U1", ReactionType.LIKE)],
            views=[],
            shares=[],
            comments=[],
            reaction_types=definitions,
        )
        assert segments[0].weighted_reaction_score == 99

    def test_sentiment_reflects_the_reaction_polarity(self) -> None:
        """The mean sentiment of a segment follows the reaction polarity."""
        service = EngagementScoringService()
        segments = service.score_segments(
            contents=[_content("C1", "Technology")],
            reactions=[
                _reaction("C1", "U1", ReactionType.LOVE),
                _reaction("C1", "U2", ReactionType.ANGRY),
            ],
            views=[],
            shares=[],
            comments=[],
        )
        assert segments[0].sentiment_score == pytest.approx(0.0)

    def test_comment_sentiment_drives_positive_ratio(self) -> None:
        """The positive ratio is computed over the comments."""
        service = EngagementScoringService()
        segments = service.score_segments(
            contents=[_content("C1", "Technology")],
            reactions=[],
            views=[],
            shares=[],
            comments=[
                Comment("CM1", "C1", "U1", 0.9, SentimentLabel.POSITIVE, None),
                Comment("CM2", "C1", "U2", -0.8, SentimentLabel.NEGATIVE, None),
            ],
        )
        assert segments[0].positive_ratio == pytest.approx(0.5)
        assert segments[0].sentiment_score == pytest.approx(0.05)

    def test_ties_are_broken_deterministically(self) -> None:
        """Two identical segments are ordered by category name."""
        service = EngagementScoringService()
        segments = service.score_segments(
            contents=[_content("C1", "Sports"), _content("C2", "Technology")],
            reactions=[
                _reaction("C1", "U1", ReactionType.LIKE),
                _reaction("C2", "U2", ReactionType.LIKE),
            ],
            views=[],
            shares=[],
            comments=[],
        )
        assert [s.category for s in segments] == ["Sports", "Technology"]
        assert segments[0].engagement_score == segments[1].engagement_score

    def test_ranking_is_reproducible(self) -> None:
        """Two identical runs produce identical results."""
        service = EngagementScoringService()
        args = (
            [_content("C1", "Technology"), _content("C2", "Sports")],
            [_reaction("C1", "U1", ReactionType.LIKE)],
            [PageView("C1", "U1", 10, None)],
            [],
            [],
        )
        first = service.score_segments(*args)
        second = service.score_segments(*args)
        assert first == second

    def test_scores_are_bounded(self) -> None:
        """The composite score always lies in ``[0, 1]``."""
        service = EngagementScoringService()
        segments = service.score_segments(
            contents=[_content("C1", "Technology"), _content("C2", "Sports")],
            reactions=[
                _reaction("C1", "U1", ReactionType.INSIGHTFUL),
                _reaction("C2", "U2", ReactionType.ANGRY),
            ],
            views=[PageView("C1", "U1", 10, None)],
            shares=[],
            comments=[],
        )
        for segment in segments:
            assert 0.0 <= segment.engagement_score <= 1.0

    def test_normalized_weights_are_used(self) -> None:
        """The service normalizes the weights it is given."""
        service = EngagementScoringService(
            ScoringWeights(volume=2, reach=2, interaction=2, amplification=2, sentiment=2)
        )
        assert service.weights.total == pytest.approx(1.0)

    def test_datetime_aware_entities_are_supported(self) -> None:
        """Entities carrying timestamps are scored without issue."""
        service = EngagementScoringService()
        content = ContentItem(
            content_id="C1",
            content_type=ContentType.VIDEO,
            category="Technology",
            category_id="Technology",
            content_body="",
            url="",
            score=1,
            content_author_id="",
            created_at=datetime(2025, 1, 1, tzinfo=timezone.utc),
        )
        segments = service.score_segments(
            contents=[content],
            reactions=[],
            views=[PageView("C1", "U1", 10, datetime(2025, 1, 2, tzinfo=timezone.utc))],
            shares=[PageShare("C1", "U1", datetime(2025, 1, 2, tzinfo=timezone.utc))],
            comments=[],
        )
        assert segments[0].views == 1
        assert segments[0].shares == 1

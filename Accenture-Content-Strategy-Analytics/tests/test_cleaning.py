"""Unit tests of the cleaning and harmonization layer.

The suite exercises the generic cleaning primitives and the per-dataset
cleaners, including every documented edge case: missing values, inconsistent
categories, outliers, duplicates and unparsable records.
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

import pytest

from social_buzz_analytics.application.cleaning import (
    CleaningContext,
    harmonize_category,
    parse_bool,
    parse_datetime,
    parse_float,
    parse_int,
    parse_non_negative_int,
    winsorize,
)
from social_buzz_analytics.application.datasets import (
    clean_comments,
    clean_content,
    clean_page_shares,
    clean_page_views,
    clean_reaction_types,
    clean_reactions,
    clean_users,
)
from social_buzz_analytics.domain.exceptions import DataQualityError
from social_buzz_analytics.domain.value_objects import (
    ContentType,
    ReactionType,
    SentimentLabel,
    UserSegment,
)

# --------------------------------------------------------------------------- #
# Parsing primitives
# --------------------------------------------------------------------------- #


class TestParseInt:
    """Tests of :func:`parse_int`."""

    @pytest.mark.parametrize(
        ("raw", "expected"),
        [
            (42, 42),
            (42.9, 42),
            ("42", 42),
            ("  42  ", 42),
            ("1,234", 1234),
            ("1 234", 1234),
            ("12.7", 12),
            ("-7", -7),
            ("abc", 0),
            ("", 0),
            (None, 0),
        ],
    )
    def test_parsing(self, raw: Any, expected: int) -> None:
        """The parser copes with the shapes found in the exports."""
        assert parse_int(raw) == expected

    def test_default_none_signals_absence(self) -> None:
        """``default=None`` reports the absence of a value."""
        assert parse_int("abc", default=None) is None
        assert parse_int("", default=None) is None

    def test_extracted_number_from_text(self) -> None:
        """A number embedded in a sentence is extracted."""
        assert parse_int("about 42 items") == 42

    def test_boolean_is_cast(self) -> None:
        """Booleans are cast to integers."""
        assert parse_int(True) == 1
        assert parse_int(False) == 0

    def test_nan_and_inf_fall_back(self) -> None:
        """``NaN`` and ``inf`` fall back to the default."""
        assert parse_int(float("nan"), default=-1) == -1
        assert parse_int(float("inf"), default=-1) == -1


class TestParseNonNegativeInt:
    """Tests of :func:`parse_non_negative_int`."""

    def test_negative_values_are_floored(self) -> None:
        """A negative counter is clamped to zero."""
        assert parse_non_negative_int(-5) == 0
        assert parse_non_negative_int("-12") == 0

    def test_positive_values_are_preserved(self) -> None:
        """A positive counter is preserved."""
        assert parse_non_negative_int("1,500") == 1500

    def test_invalid_values_use_the_default(self) -> None:
        """An invalid counter falls back to the default."""
        assert parse_non_negative_int("n/a", default=7) == 7


class TestParseFloat:
    """Tests of :func:`parse_float`."""

    @pytest.mark.parametrize(
        ("raw", "expected"),
        [(1.5, 1.5), ("1.5", 1.5), ("-2.25", -2.25), ("  3.5  ", 3.5), ("1,5.5", 15.5)],
    )
    def test_parsing(self, raw: Any, expected: float) -> None:
        """The parser copes with the shapes found in the exports."""
        assert parse_float(raw) == pytest.approx(expected)

    @pytest.mark.parametrize("raw", [None, "", "abc", "n/a"])
    def test_invalid_values_return_the_default(self, raw: Any) -> None:
        """An unparsable value returns the default."""
        assert parse_float(raw, default=-1.0) == -1.0

    def test_nan_returns_the_default(self) -> None:
        """``NaN`` returns the default instead of poisoning the statistics."""
        assert parse_float(float("nan"), default=0.0) == 0.0


class TestParseBool:
    """Tests of :func:`parse_bool`."""

    @pytest.mark.parametrize("raw", ["true", "TRUE", "yes", "Y", "1", True])
    def test_true_tokens(self, raw: Any) -> None:
        """Every truthy token is recognized."""
        assert parse_bool(raw) is True

    @pytest.mark.parametrize("raw", ["false", "FALSE", "no", "N", "0", False])
    def test_false_tokens(self, raw: Any) -> None:
        """Every falsy token is recognized."""
        assert parse_bool(raw) is False

    @pytest.mark.parametrize("raw", [None, "", "maybe", "2"])
    def test_invalid_tokens_return_the_default(self, raw: Any) -> None:
        """An unrecognized token returns the default."""
        assert parse_bool(raw, default=None) is None


class TestParseDatetime:
    """Tests of :func:`parse_datetime`."""

    @pytest.mark.parametrize(
        "raw",
        [
            "2025-02-01 09:30:00",
            "2025-02-01T09:30:00",
            "2025-02-01",
            "01/02/2025 09:30:00",
            "2025-02-01T09:30:00+00:00",
        ],
    )
    def test_supported_layouts(self, raw: str) -> None:
        """Every supported layout yields a UTC timestamp."""
        parsed = parse_datetime(raw)
        assert parsed is not None
        assert parsed.tzinfo is timezone.utc
        assert parsed.year == 2025

    def test_naive_datetime_gets_utc(self) -> None:
        """A naive datetime is assumed to be UTC."""
        parsed = parse_datetime(datetime(2025, 2, 1, 9, 30))
        assert parsed == datetime(2025, 2, 1, 9, 30, tzinfo=timezone.utc)

    def test_aware_datetime_is_preserved(self) -> None:
        """An aware datetime keeps its instant."""
        parsed = parse_datetime(datetime(2025, 2, 1, 9, 30, tzinfo=timezone.utc))
        assert parsed is not None
        assert parsed.tzinfo is timezone.utc

    def test_epoch_seconds(self) -> None:
        """A numeric epoch is interpreted as seconds."""
        parsed = parse_datetime("1738407000")
        assert parsed is not None
        assert parsed.year == 2025

    def test_epoch_milliseconds(self) -> None:
        """A large numeric epoch is interpreted as milliseconds."""
        parsed = parse_datetime("1738407000000")
        assert parsed is not None
        assert parsed.year == 2025

    @pytest.mark.parametrize("raw", [None, "", "not a date", "13/45/2025"])
    def test_invalid_values_return_the_default(self, raw: Any) -> None:
        """An unparsable timestamp returns the default."""
        assert parse_datetime(raw, default=None) is None

    def test_out_of_range_epoch_returns_the_default(self) -> None:
        """An out-of-range epoch returns the default instead of raising."""
        assert parse_datetime("99999999999999999999", default=None) is None


class TestHarmonizeCategory:
    """Tests of :func:`harmonize_category`."""

    @pytest.mark.parametrize(
        ("raw", "expected"),
        [
            ("Technology", "Technology"),
            ("tech", "Technology"),
            ("  SPORTS  ", "Sports"),
            ("Sport", "Sports"),
            ("entertaiment", "Entertainment"),
            ("ENT", "Entertainment"),
            ("Technolgy", "Technology"),
            ("Financial", "Finance"),
            ("Educational", "Education"),
            ("Games", "Gaming"),
            ("Health & Wellness", "Health"),
            ("Food & Drink", "Food"),
        ],
    )
    def test_known_labels(self, raw: str, expected: str) -> None:
        """The known labels are harmonized onto the taxonomy."""
        assert harmonize_category(raw) == expected

    @pytest.mark.parametrize("raw", ["", "   ", None])
    def test_empty_labels_use_the_default(self, raw: Any) -> None:
        """An empty label uses the default category."""
        assert harmonize_category(raw) == "Other"
        assert harmonize_category(raw, default="Uncategorised") == "Uncategorised"

    def test_completely_unknown_label_uses_the_default(self) -> None:
        """An unmappable label uses the default category."""
        assert harmonize_category("qwertyuiop") == "Other"

    def test_fuzzy_match_does_not_merge_distinct_categories(self) -> None:
        """The fuzzy step never merges two different categories."""
        assert harmonize_category("sportz") == "Sports"
        assert harmonize_category("zzzqqq") == "Other"


class TestWinsorize:
    """Tests of :func:`winsorize`."""

    def test_outliers_are_clipped(self) -> None:
        """The extreme values are mapped onto the fences."""
        values = [float(v) for v in range(100)] + [10_000.0, -10_000.0]
        clipping, low, high = winsorize(values)
        assert low < high
        assert clipping[10_000.0] == high
        assert clipping[-10_000.0] == low

    def test_normal_values_are_untouched(self) -> None:
        """The inliers are not part of the clipping map.

        Winsorization deliberately clips the extreme tails, so the test
        uses a series whose bulk sits well inside the fences.
        """
        values = [float(v) for v in range(1, 100)]
        clipping, low, high = winsorize(values, lower_quantile=0.05, upper_quantile=0.95)
        # Only the 5% tails are clipped, the bulk is untouched.
        assert set(clipping) == {1.0, 2.0, 3.0, 4.0, 96.0, 97.0, 98.0, 99.0}
        assert 10.0 not in clipping
        assert 50.0 not in clipping
        assert low == 5.0
        assert high == 95.0

    def test_small_series_is_not_winsorized(self) -> None:
        """A series of less than four values is left alone."""
        clipping, low, high = winsorize([1.0, 2.0, 3.0])
        assert clipping == {}
        assert (low, high) == (1.0, 3.0)

    def test_empty_series(self) -> None:
        """An empty series yields an empty clipping map."""
        clipping, low, high = winsorize([])
        assert clipping == {}
        assert (low, high) == (0.0, 0.0)

    @pytest.mark.parametrize(
        ("lower", "upper"),
        [(1.5, 0.5), (-0.1, 0.5), (0.5, 1.5), (0.5, 0.5)],
    )
    def test_invalid_quantiles_are_rejected(self, lower: float, upper: float) -> None:
        """An out-of-range quantile raises a ``ValueError``."""
        with pytest.raises(ValueError):
            winsorize([1.0, 2.0, 3.0, 4.0], lower, upper)


class TestCleaningContext:
    """Tests of the :class:`CleaningContext` accumulator."""

    def test_counters_start_at_zero(self) -> None:
        """A fresh context holds zeroed counters."""
        context = CleaningContext()
        assert context.missing_filled == 0
        assert context.values_normalized == 0
        assert context.outliers_clipped == 0
        assert context.notes == []

    def test_note_appends(self) -> None:
        """A note is appended to the report."""
        context = CleaningContext()
        context.note("something happened")
        assert context.notes == ["something happened"]


# --------------------------------------------------------------------------- #
# clean_users
# --------------------------------------------------------------------------- #


class TestCleanUsers:
    """Tests of :func:`clean_users`."""

    def test_valid_rows_are_accepted(self) -> None:
        """A valid row is turned into a user."""
        users, stats = clean_users(
            [
                {
                    "user_id": "U1",
                    "user_segment": "active",
                    "user_country": "id",
                    "user_age": "30",
                    "user_followers": "10",
                    "user_created_at": "2025-01-01 00:00:00",
                }
            ]
        )
        assert len(users) == 1
        assert users[0].user_id == "U1"
        assert users[0].segment is UserSegment.ACTIVE
        assert users[0].country == "ID"
        assert users[0].age == 30
        assert users[0].followers == 10
        assert stats.rows_accepted == 1
        assert stats.rows_rejected == 0

    def test_missing_user_id_is_rejected(self) -> None:
        """A row without an identifier is rejected."""
        _, stats = clean_users([{"user_id": "", "user_segment": "active"}])
        assert stats.rows_rejected == 1
        assert stats.rejection_reasons["missing_user_id"] == 1

    def test_duplicated_users_are_dropped(self) -> None:
        """A duplicated identifier is rejected."""
        row = {
            "user_id": "U1",
            "user_segment": "active",
            "user_country": "ID",
            "user_age": "30",
            "user_followers": "10",
        }
        users, stats = clean_users([row, dict(row)])
        assert len(users) == 1
        assert stats.duplicates_removed == 1
        assert stats.rejection_reasons["duplicate_user_id"] == 1

    def test_unknown_segment_degrades_to_active(self) -> None:
        """An unknown segment does not remove the user."""
        users, _ = clean_users(
            [{"user_id": "U1", "user_segment": "wizard", "user_country": "ID"}]
        )
        assert users[0].segment is UserSegment.ACTIVE

    def test_missing_country_is_imputed_with_the_mode(self) -> None:
        """A missing country is imputed with the modal country."""
        users, stats = clean_users(
            [
                {"user_id": "U1", "user_segment": "active", "user_country": "ID"},
                {"user_id": "U2", "user_segment": "active", "user_country": "ID"},
                {"user_id": "U3", "user_segment": "active", "user_country": ""},
            ]
        )
        assert users[2].country == "ID"
        assert stats.missing_filled >= 1

    def test_out_of_range_age_is_imputed(self) -> None:
        """An impossible age is replaced by the median age."""
        users, stats = clean_users(
            [
                {"user_id": "U1", "user_segment": "active", "user_age": "30"},
                {"user_id": "U2", "user_segment": "active", "user_age": "40"},
                {"user_id": "U3", "user_segment": "active", "user_age": "999"},
            ]
        )
        assert users[2].age == 35
        assert stats.outliers_clipped >= 1

    def test_missing_age_is_imputed(self) -> None:
        """A missing age is imputed with the median age."""
        users, stats = clean_users(
            [
                {"user_id": "U1", "user_segment": "active", "user_age": "30"},
                {"user_id": "U2", "user_segment": "active", "user_age": ""},
            ]
        )
        assert users[1].age == 30
        assert stats.missing_filled >= 1

    def test_negative_followers_are_floored(self) -> None:
        """A negative follower count is clamped to zero."""
        users, _ = clean_users(
            [{"user_id": "U1", "user_segment": "active", "user_followers": "-9"}]
        )
        assert users[0].followers == 0

    def test_absurd_followers_are_clipped(self) -> None:
        """An implausible follower count is clipped."""
        users, stats = clean_users(
            [{"user_id": "U1", "user_segment": "active", "user_followers": "99999999"}]
        )
        assert users[0].followers == 1_000_000
        assert stats.outliers_clipped >= 1

    def test_unparsable_timestamp_becomes_none(self) -> None:
        """An unparsable timestamp does not reject the row."""
        users, _ = clean_users(
            [{"user_id": "U1", "user_segment": "active", "user_created_at": "n/a"}]
        )
        assert users[0].created_at is None

    def test_empty_dataset(self) -> None:
        """An empty dataset yields no user and no error."""
        users, stats = clean_users([])
        assert users == []
        assert stats.rows_read == 0

    def test_too_many_rejections_raise(self) -> None:
        """A dataset that loses too many rows raises an error."""
        rows = [{"user_id": "", "user_segment": "active"} for _ in range(200)]
        rows.append({"user_id": "U1", "user_segment": "active"})
        with pytest.raises(DataQualityError, match="rejected"):
            clean_users(rows)


# --------------------------------------------------------------------------- #
# clean_content
# --------------------------------------------------------------------------- #


class TestCleanContent:
    """Tests of :func:`clean_content`."""

    def test_valid_row_is_accepted(self) -> None:
        """A valid row is turned into a content item."""
        contents, stats = clean_content(
            [
                {
                    "content_id": "C1",
                    "content_type": "video",
                    "url": "https://x",
                    "created_at": "2025-01-01 00:00:00",
                    "content_body": "body",
                    "score": "10",
                    "category_id": "Technology",
                    "content_author_id": "U1",
                }
            ]
        )
        assert len(contents) == 1
        assert contents[0].content_type is ContentType.VIDEO
        assert contents[0].category == "Technology"
        assert contents[0].score == 10
        assert stats.rows_accepted == 1

    def test_missing_content_id_is_rejected(self) -> None:
        """A row without an identifier is rejected."""
        _, stats = clean_content([{"content_id": "", "category_id": "Technology"}])
        assert stats.rejection_reasons["missing_content_id"] == 1

    def test_missing_category_is_kept_as_other(self) -> None:
        """A content item without a category is kept under ``Other``."""
        contents, stats = clean_content([{"content_id": "C1", "category_id": ""}])
        assert len(contents) == 1
        assert contents[0].category == "Other"
        assert stats.missing_filled >= 1

    def test_unknown_content_type_degrades_to_post(self) -> None:
        """An unknown content type degrades to ``post``."""
        contents, _ = clean_content(
            [{"content_id": "C1", "content_type": "hologram", "category_id": "Technology"}]
        )
        assert contents[0].content_type is ContentType.POST

    def test_duplicated_content_is_dropped(self) -> None:
        """A duplicated identifier is rejected."""
        row = {"content_id": "C1", "category_id": "Technology"}
        contents, stats = clean_content([row, dict(row)])
        assert len(contents) == 1
        assert stats.duplicates_removed == 1

    def test_negative_score_is_floored(self) -> None:
        """A negative score is clamped to zero."""
        contents, _ = clean_content(
            [{"content_id": "C1", "category_id": "Technology", "score": "-3"}]
        )
        assert contents[0].score == 0

    def test_outliers_are_winsorized(self) -> None:
        """An extreme score is clipped onto the upper fence."""
        rows = [
            {"content_id": f"C{i}", "category_id": "Technology", "score": str(i)}
            for i in range(50)
        ]
        rows.append({"content_id": "C999", "category_id": "Technology", "score": "999999"})
        contents, stats = clean_content(rows)
        assert contents[-1].score < 999999
        assert stats.outliers_clipped >= 1


# --------------------------------------------------------------------------- #
# clean_reaction_types / clean_reactions
# --------------------------------------------------------------------------- #


class TestCleanReactionTypes:
    """Tests of :func:`clean_reaction_types`."""

    def test_valid_definitions_are_accepted(self) -> None:
        """A valid definition is accepted."""
        definitions, stats = clean_reaction_types([{"reaction_type": "like", "score": "1"}])
        assert len(definitions) == 1
        assert definitions[0].reaction_type is ReactionType.LIKE
        assert definitions[0].score == 1
        assert stats.rows_accepted == 1

    def test_missing_score_falls_back_to_the_canonical_weight(self) -> None:
        """A missing score falls back to the built-in weight."""
        definitions, stats = clean_reaction_types([{"reaction_type": "love"}])
        assert definitions[0].score == ReactionType.LOVE.score
        assert stats.missing_filled == 1

    def test_unknown_type_is_rejected(self) -> None:
        """An unknown reaction type is rejected."""
        _, stats = clean_reaction_types([{"reaction_type": "confused", "score": "0"}])
        assert stats.rejection_reasons["unknown_reaction_type"] == 1

    def test_duplicate_definition_is_rejected(self) -> None:
        """A duplicated reaction type is rejected."""
        _, stats = clean_reaction_types(
            [{"reaction_type": "like", "score": "1"}, {"reaction_type": "like", "score": "1"}]
        )
        assert stats.duplicates_removed == 1


class TestCleanReactions:
    """Tests of :func:`clean_reactions`."""

    def test_valid_reaction_is_accepted(self) -> None:
        """A valid reaction is accepted."""
        reactions, stats = clean_reactions(
            [{"content_id": "C1", "user_id": "U1", "reaction_type": "like"}]
        )
        assert len(reactions) == 1
        assert reactions[0].reaction_type is ReactionType.LIKE
        assert stats.rows_accepted == 1

    @pytest.mark.parametrize(
        ("row", "reason"),
        [
            ({"content_id": "", "user_id": "U1", "reaction_type": "like"}, "missing_content_id"),
            ({"content_id": "C1", "user_id": "", "reaction_type": "like"}, "missing_user_id"),
            (
                {"content_id": "C1", "user_id": "U1", "reaction_type": ""},
                "missing_reaction_type",
            ),
            (
                {"content_id": "C1", "user_id": "U1", "reaction_type": "spooked"},
                "unknown_reaction_type",
            ),
        ],
    )
    def test_invalid_reactions_are_rejected(self, row: dict[str, str], reason: str) -> None:
        """Every invalid reaction is rejected with the right reason."""
        _, stats = clean_reactions([row])
        assert stats.rejection_reasons[reason] == 1

    def test_duplicate_reaction_is_dropped(self) -> None:
        """A duplicated natural key is rejected."""
        row = {"content_id": "C1", "user_id": "U1", "reaction_type": "like"}
        reactions, stats = clean_reactions([row, dict(row)])
        assert len(reactions) == 1
        assert stats.duplicates_removed == 1

    def test_same_user_may_react_differently(self) -> None:
        """A user may react to the same content with two different types."""
        reactions, _ = clean_reactions(
            [
                {"content_id": "C1", "user_id": "U1", "reaction_type": "like"},
                {"content_id": "C1", "user_id": "U1", "reaction_type": "love"},
            ]
        )
        assert len(reactions) == 2

    def test_case_variant_is_normalized(self) -> None:
        """A casing variant is normalized and counted."""
        reactions, stats = clean_reactions(
            [{"content_id": "C1", "user_id": "U1", "reaction_type": "LIKE"}]
        )
        assert reactions[0].reaction_type is ReactionType.LIKE
        assert stats.values_normalized >= 1


# --------------------------------------------------------------------------- #
# clean_comments / clean_page_shares / clean_page_views
# --------------------------------------------------------------------------- #


class TestCleanComments:
    """Tests of :func:`clean_comments`."""

    def test_valid_comment_is_accepted(self) -> None:
        """A valid comment is accepted."""
        comments, stats = clean_comments(
            [
                {
                    "comment_id": "CM1",
                    "content_id": "C1",
                    "user_id": "U1",
                    "comment_time": "2025-01-01 00:00:00",
                    "comment_sentiment": "0.5",
                }
            ]
        )
        assert len(comments) == 1
        assert comments[0].sentiment == pytest.approx(0.5)
        assert comments[0].label is SentimentLabel.POSITIVE
        assert stats.rows_accepted == 1

    def test_missing_sentiment_is_rejected(self) -> None:
        """A comment without a sentiment score is rejected."""
        _, stats = clean_comments(
            [{"comment_id": "CM1", "content_id": "C1", "user_id": "U1", "comment_sentiment": ""}]
        )
        assert stats.rejection_reasons["missing_comment_sentiment"] == 1

    def test_out_of_range_sentiment_is_clipped(self) -> None:
        """A sentiment outside ``[-1, 1]`` is clipped."""
        comments, stats = clean_comments(
            [
                {
                    "comment_id": "CM1",
                    "content_id": "C1",
                    "user_id": "U1",
                    "comment_sentiment": "4.2",
                }
            ]
        )
        assert comments[0].sentiment == pytest.approx(1.0)
        assert comments[0].label is SentimentLabel.POSITIVE
        assert stats.outliers_clipped >= 1

    def test_duplicate_comment_is_dropped(self) -> None:
        """A duplicated natural key is rejected."""
        row = {
            "comment_id": "CM1",
            "content_id": "C1",
            "user_id": "U1",
            "comment_sentiment": "0.5",
        }
        comments, stats = clean_comments([row, dict(row)])
        assert len(comments) == 1
        assert stats.duplicates_removed == 1


class TestCleanPageShares:
    """Tests of :func:`clean_page_shares`."""

    def test_valid_share_is_accepted(self) -> None:
        """A valid share is accepted."""
        shares, stats = clean_page_shares(
            [{"content_id": "C1", "share_date": "2025-01-01", "share_user_id": "U1"}]
        )
        assert len(shares) == 1
        assert stats.rows_accepted == 1

    def test_missing_keys_are_rejected(self) -> None:
        """A share without a content or a user is rejected."""
        _, stats = clean_page_shares([{"content_id": "C1", "share_user_id": ""}])
        assert stats.rejection_reasons["missing_share_user_id"] == 1

    def test_duplicate_share_is_dropped(self) -> None:
        """A duplicated natural key is rejected."""
        row = {"content_id": "C1", "share_date": "2025-01-01", "share_user_id": "U1"}
        shares, stats = clean_page_shares([row, dict(row)])
        assert len(shares) == 1
        assert stats.duplicates_removed == 1


class TestCleanPageViews:
    """Tests of :func:`clean_page_views`."""

    def test_valid_view_is_accepted(self) -> None:
        """A valid view is accepted."""
        views, stats = clean_page_views(
            [
                {
                    "content_id": "C1",
                    "view_date": "2025-01-01",
                    "view_user_id": "U1",
                    "view_seconds": "30",
                }
            ]
        )
        assert len(views) == 1
        assert views[0].view_seconds == 30
        assert stats.rows_accepted == 1

    def test_negative_duration_is_floored(self) -> None:
        """A negative dwell time is clamped to zero."""
        views, _ = clean_page_views(
            [
                {
                    "content_id": "C1",
                    "view_date": "2025-01-01",
                    "view_user_id": "U1",
                    "view_seconds": "-12",
                }
            ]
        )
        assert views[0].view_seconds == 0

    def test_absurd_duration_is_clipped(self) -> None:
        """A dwell time above one day is clipped."""
        views, stats = clean_page_views(
            [
                {
                    "content_id": "C1",
                    "view_date": "2025-01-01",
                    "view_user_id": "U1",
                    "view_seconds": "9999999",
                }
            ]
        )
        assert views[0].view_seconds == 86_400
        assert stats.outliers_clipped >= 1

    def test_same_day_duplicate_is_dropped(self) -> None:
        """Two views of the same content by the same user on the same day are duplicates."""
        row = {
            "content_id": "C1",
            "view_date": "2025-01-01",
            "view_user_id": "U1",
            "view_seconds": "30",
        }
        views, stats = clean_page_views([row, dict(row)])
        assert len(views) == 1
        assert stats.duplicates_removed == 1

    def test_different_day_is_not_a_duplicate(self) -> None:
        """The same user may view the same content on two different days."""
        views, _ = clean_page_views(
            [
                {
                    "content_id": "C1",
                    "view_date": "2025-01-01",
                    "view_user_id": "U1",
                    "view_seconds": "30",
                },
                {
                    "content_id": "C1",
                    "view_date": "2025-01-02",
                    "view_user_id": "U1",
                    "view_seconds": "30",
                },
            ]
        )
        assert len(views) == 2

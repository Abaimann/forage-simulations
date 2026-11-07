"""Per-dataset cleaners.

Each cleaner takes the raw rows of one dataset and returns the cleaned
domain entities together with a :class:`CleaningStats` report.  The
cleaners encapsulate the *business* rules of each dataset (which columns are
required, which values are plausible, how duplicates are handled) while
reusing the generic primitives of :mod:`..application.cleaning`.

All cleaners follow the same contract:

* a row that violates a *hard* rule is rejected and counted;
* a row that violates a *soft* rule is repaired (imputed, normalized or
  clipped) and the repair is counted;
* the cleaners never raise on dirty data - the pipeline is designed to
  survive a partial or corrupted export.
"""

from __future__ import annotations

from collections import Counter
from collections.abc import Mapping, Sequence
from typing import Any

from ..domain.entities import (
    Comment,
    ContentItem,
    PageShare,
    PageView,
    Reaction,
    ReactionTypeDefinition,
    User,
)
from ..domain.exceptions import DataQualityError
from ..domain.value_objects import (
    ContentType,
    ReactionType,
    SentimentLabel,
    UserSegment,
    canonical_text,
    normalize_identifier,
)
from .cleaning import (
    CleaningContext,
    harmonize_category,
    iqr_outlier_map,
    parse_datetime,
    parse_float,
    parse_int,
    parse_non_negative_int,
)
from .ports import CleaningStats

__all__ = [
    "clean_comments",
    "clean_content",
    "clean_page_shares",
    "clean_page_views",
    "clean_reaction_types",
    "clean_reactions",
    "clean_users",
]


def _require(row: Mapping[str, Any], column: str) -> str:
    """Return a non-empty identifier of ``column``.

    The case of the identifier is preserved: identifiers are business
    keys, not descriptive labels.

    Raises
    ------
    KeyError
        If the column is absent from the row.
    ValueError
        If the value is missing or empty.
    """
    value = normalize_identifier(row.get(column))
    if not value:
        raise ValueError(f"missing required column {column!r}")
    return value


def _optional_text(row: Mapping[str, Any], column: str) -> str:
    """Return the trimmed text of ``column`` (empty string when missing)."""
    raw = row.get(column)
    if raw is None:
        return ""
    return str(raw).strip()


def _impute_users_country(rows: Sequence[Mapping[str, Any]]) -> str:
    """Impute the missing country of the users with the modal country."""
    countries = [
        canonical_text(row.get("user_country")).upper()
        for row in rows
        if canonical_text(row.get("user_country"))
    ]
    if not countries:
        return "Unknown"
    counter = Counter(countries)
    return counter.most_common(1)[0][0]


def _impute_users_age(rows: Sequence[Mapping[str, Any]]) -> int:
    """Impute the missing age of the users with the median age."""
    ages = [
        age
        for age in (parse_int(row.get("user_age"), default=None) for row in rows)
        if age is not None and 13 <= age <= 99
    ]
    if not ages:
        return 0
    ordered = sorted(ages)
    middle = len(ordered) // 2
    if len(ordered) % 2 == 1:
        return int(ordered[middle])
    return int((ordered[middle - 1] + ordered[middle]) / 2)


def clean_users(
    rows: Sequence[Mapping[str, Any]],
    max_rejection_rate: float = 0.95,
) -> tuple[list[User], CleaningStats]:
    """Clean the ``Users`` dataset.

    Rules applied:

    * ``user_id`` is required and must be unique (duplicates are dropped,
      keeping the first occurrence);
    * ``user_segment`` is harmonized onto :class:`UserSegment`; unknown
      labels degrade to ``active`` instead of dropping the user;
    * ``user_country`` is upper-cased; missing values are imputed with the
      modal country of the dataset;
    * ``user_age`` must be within ``[13, 99]``; out-of-range and missing
      values are imputed with the median age;
    * ``user_followers`` is clamped to ``>= 0``; implausible values above
      ``1_000_000`` are treated as outliers and clipped;
    * ``user_created_at`` is parsed into a UTC timestamp.

    Parameters
    ----------
    rows:
        The raw rows of the dataset.
    max_rejection_rate:
        Upper bound of the share of rows that may be rejected before the
        dataset is considered unusable.

    Returns
    -------
    tuple[list[User], CleaningStats]
        The cleaned users and the statistics of the cleaning run.

    Raises
    ------
    DataQualityError
        If more than ``1 - max_rejection_rate`` of the rows are rejected.
    """
    stats = CleaningStats(dataset="Users")
    context = CleaningContext()
    default_country = _impute_users_country(rows)
    default_age = _impute_users_age(rows)
    seen: set[str] = set()
    users: list[User] = []

    for row in rows:
        stats.rows_read += 1
        try:
            user_id = _require(row, "user_id")
        except (KeyError, ValueError):
            stats.reject("missing_user_id")
            continue

        if user_id in seen:
            stats.duplicates_removed += 1
            stats.reject("duplicate_user_id")
            continue
        seen.add(user_id)

        raw_segment = canonical_text(row.get("user_segment"))
        segment = UserSegment.from_raw(raw_segment)
        if raw_segment and str(segment) != raw_segment.replace(" ", "_").replace("-", "_"):
            context.values_normalized += 1

        raw_country = canonical_text(row.get("user_country"))
        if raw_country:
            country = raw_country.upper()
            if country != raw_country:
                context.values_normalized += 1
        else:
            country = default_country
            context.missing_filled += 1

        raw_age = parse_int(row.get("user_age"), default=None)
        if raw_age is None:
            age: int | None = default_age
            context.missing_filled += 1
        elif not 13 <= raw_age <= 99:
            age = default_age
            context.outliers_clipped += 1
        else:
            age = raw_age

        followers = parse_non_negative_int(row.get("user_followers"), default=0)
        if followers > 1_000_000:
            followers = 1_000_000
            context.outliers_clipped += 1

        created_at = parse_datetime(row.get("user_created_at"), default=None)

        users.append(
            User(
                user_id=user_id,
                segment=segment,
                country=country,
                age=age,
                followers=followers,
                created_at=created_at,
            )
        )
        stats.rows_accepted += 1

    _apply_stats(stats, context)
    _guard_rejection_rate(stats, max_rejection_rate)
    return users, stats


def clean_content(
    rows: Sequence[Mapping[str, Any]],
    max_rejection_rate: float = 0.95,
) -> tuple[list[ContentItem], CleaningStats]:
    """Clean the ``Content`` dataset.

    Rules applied:

    * ``content_id`` is required and unique;
    * ``content_type`` is harmonized onto :class:`ContentType`; unknown types
      degrade to ``post``;
    * ``category_id`` is harmonized onto the canonical taxonomy; a *missing*
      category does not reject the row - the content is kept under the
      ``Other`` segment, because dropping it would silently discard every
      reaction it received;
    * ``score`` is clamped to ``>= 0`` and winsorized against the dataset
      distribution to neutralize outliers;
    * ``created_at`` is parsed into a UTC timestamp.

    Parameters
    ----------
    rows:
        The raw rows of the dataset.
    max_rejection_rate:
        Upper bound of the share of rows that may be rejected.

    Returns
    -------
    tuple[list[ContentItem], CleaningStats]
        The cleaned content items and the statistics of the cleaning run.

    Raises
    ------
    DataQualityError
        If more than ``1 - max_rejection_rate`` of the rows are rejected.
    """
    stats = CleaningStats(dataset="Content")
    context = CleaningContext()
    seen: set[str] = set()
    contents: list[ContentItem] = []

    raw_scores = [
        score
        for score in (parse_non_negative_int(row.get("score"), default=0) for row in rows)
    ]
    clipping, _low, _high = _winsorize_scores(raw_scores)

    for row in rows:
        stats.rows_read += 1
        try:
            content_id = _require(row, "content_id")
        except (KeyError, ValueError):
            stats.reject("missing_content_id")
            continue

        if content_id in seen:
            stats.duplicates_removed += 1
            stats.reject("duplicate_content_id")
            continue
        seen.add(content_id)

        raw_category = canonical_text(row.get("category_id"))
        if raw_category:
            category_id = raw_category
            category = harmonize_category(category_id)
            if canonical_text(category) != raw_category:
                context.values_normalized += 1
        else:
            # A content item without a category is still a content item:
            # it is kept under the ``Other`` segment instead of being
            # dropped, so that its reactions are not silently lost.
            category_id = ""
            category = harmonize_category("", default="Other")
            context.missing_filled += 1

        raw_type = row.get("content_type")
        label = canonical_text(raw_type)
        try:
            content_type = ContentType.from_raw(label)
        except ValueError:
            content_type = ContentType.POST
            context.values_normalized += 1
        else:
            if str(raw_type).strip() != str(content_type):
                context.values_normalized += 1

        score = parse_non_negative_int(row.get("score"), default=0)
        if score in clipping:
            score = clipping[score]
            context.outliers_clipped += 1

        created_at = parse_datetime(row.get("created_at"), default=None)
        body = _optional_text(row, "content_body")
        url = _optional_text(row, "url")
        author = _optional_text(row, "content_author_id")

        contents.append(
            ContentItem(
                content_id=content_id,
                content_type=content_type,
                category=category,
                category_id=category_id,
                content_body=body,
                url=url,
                score=score,
                content_author_id=author,
                created_at=created_at,
            )
        )
        stats.rows_accepted += 1

    _apply_stats(stats, context)
    _guard_rejection_rate(stats, max_rejection_rate)
    return contents, stats


def clean_reaction_types(
    rows: Sequence[Mapping[str, Any]],
    max_rejection_rate: float = 0.95,
) -> tuple[list[ReactionTypeDefinition], CleaningStats]:
    """Clean the ``ReactionTypes`` reference dataset.

    Rules applied:

    * ``reaction_type`` is required and unique;
    * ``score`` is required; a missing score falls back to the canonical
      weight of the reaction type;
    * the reaction type label is harmonized onto :class:`ReactionType`.

    Parameters
    ----------
    rows:
        The raw rows of the dataset.
    max_rejection_rate:
        Upper bound of the share of rows that may be rejected.

    Returns
    -------
    tuple[list[ReactionTypeDefinition], CleaningStats]
        The cleaned definitions and the statistics of the cleaning run.

    Raises
    ------
    DataQualityError
        If more than ``1 - max_rejection_rate`` of the rows are rejected.
    """
    stats = CleaningStats(dataset="ReactionTypes")
    context = CleaningContext()
    seen: set[ReactionType] = set()
    definitions: list[ReactionTypeDefinition] = []

    for row in rows:
        stats.rows_read += 1
        raw_label = row.get("reaction_type")
        label = canonical_text(raw_label)
        if not label:
            stats.reject("missing_reaction_type")
            continue
        try:
            reaction_type = ReactionType.from_raw(label)
        except ValueError:
            stats.reject("unknown_reaction_type")
            continue
        if reaction_type in seen:
            stats.duplicates_removed += 1
            stats.reject("duplicate_reaction_type")
            continue
        seen.add(reaction_type)

        # The *original* label is compared with the canonical one so that
        # the rows that needed a harmonization ("LIKE" -> "like") are
        # counted.
        if str(raw_label).strip() != str(reaction_type):
            context.values_normalized += 1

        raw_score = parse_int(row.get("score"), default=None)
        if raw_score is None:
            score = reaction_type.score
            context.missing_filled += 1
        else:
            score = raw_score

        definitions.append(
            ReactionTypeDefinition(
                reaction_type=reaction_type,
                score=score,
                sentiment=reaction_type.sentiment,
            )
        )
        stats.rows_accepted += 1

    _apply_stats(stats, context)
    _guard_rejection_rate(stats, max_rejection_rate)
    return definitions, stats


def clean_reactions(
    rows: Sequence[Mapping[str, Any]],
    max_rejection_rate: float = 0.95,
) -> tuple[list[Reaction], CleaningStats]:
    """Clean the ``Reactions`` dataset.

    Rules applied:

    * ``content_id`` and ``user_id`` are required;
    * ``reaction_type`` is required and harmonized onto
      :class:`ReactionType`; unknown types are rejected;
    * the natural key ``(content_id, user_id, reaction_type)`` must be
      unique; duplicates are dropped.

    Parameters
    ----------
    rows:
        The raw rows of the dataset.
    max_rejection_rate:
        Upper bound of the share of rows that may be rejected.

    Returns
    -------
    tuple[list[Reaction], CleaningStats]
        The cleaned reactions and the statistics of the cleaning run.

    Raises
    ------
    DataQualityError
        If more than ``1 - max_rejection_rate`` of the rows are rejected.
    """
    stats = CleaningStats(dataset="Reactions")
    context = CleaningContext()
    seen: set[tuple[str, str, ReactionType]] = set()
    reactions: list[Reaction] = []

    for row in rows:
        stats.rows_read += 1
        try:
            content_id = _require(row, "content_id")
        except (KeyError, ValueError):
            stats.reject("missing_content_id")
            continue
        try:
            user_id = _require(row, "user_id")
        except (KeyError, ValueError):
            stats.reject("missing_user_id")
            continue
        raw_type = row.get("reaction_type")
        label = canonical_text(raw_type)
        if not label:
            stats.reject("missing_reaction_type")
            continue
        try:
            reaction_type = ReactionType.from_raw(label)
        except ValueError:
            stats.reject("unknown_reaction_type")
            continue

        key = (content_id, user_id, reaction_type)
        if key in seen:
            stats.duplicates_removed += 1
            stats.reject("duplicate_reaction")
            continue
        seen.add(key)

        if str(raw_type).strip() != str(reaction_type):
            context.values_normalized += 1

        reactions.append(
            Reaction(
                content_id=content_id,
                user_id=user_id,
                reaction_type=reaction_type,
            )
        )
        stats.rows_accepted += 1

    _apply_stats(stats, context)
    _guard_rejection_rate(stats, max_rejection_rate)
    return reactions, stats


def clean_comments(
    rows: Sequence[Mapping[str, Any]],
    max_rejection_rate: float = 0.95,
) -> tuple[list[Comment], CleaningStats]:
    """Clean the ``Comments`` dataset.

    Rules applied:

    * ``comment_id``, ``content_id`` and ``user_id`` are required;
    * ``comment_sentiment`` is required and clamped into ``[-1, 1]``;
    * the natural key ``(content_id, user_id)`` must be unique - a user may
      comment a given content item only once.

    Parameters
    ----------
    rows:
        The raw rows of the dataset.
    max_rejection_rate:
        Upper bound of the share of rows that may be rejected.

    Returns
    -------
    tuple[list[Comment], CleaningStats]
        The cleaned comments and the statistics of the cleaning run.

    Raises
    ------
    DataQualityError
        If more than ``1 - max_rejection_rate`` of the rows are rejected.
    """
    stats = CleaningStats(dataset="Comments")
    context = CleaningContext()
    seen: set[tuple[str, str]] = set()
    comments: list[Comment] = []

    for row in rows:
        stats.rows_read += 1
        try:
            comment_id = _require(row, "comment_id")
        except (KeyError, ValueError):
            stats.reject("missing_comment_id")
            continue
        try:
            content_id = _require(row, "content_id")
        except (KeyError, ValueError):
            stats.reject("missing_content_id")
            continue
        try:
            user_id = _require(row, "user_id")
        except (KeyError, ValueError):
            stats.reject("missing_user_id")
            continue

        raw_sentiment = parse_float(row.get("comment_sentiment"), default=None)
        if raw_sentiment is None:
            stats.reject("missing_comment_sentiment")
            continue
        sentiment = max(-1.0, min(1.0, raw_sentiment))
        if sentiment != raw_sentiment:
            context.outliers_clipped += 1

        key = (content_id, user_id)
        if key in seen:
            stats.duplicates_removed += 1
            stats.reject("duplicate_comment")
            continue
        seen.add(key)

        commented_at = parse_datetime(row.get("comment_time"), default=None)

        comments.append(
            Comment(
                comment_id=comment_id,
                content_id=content_id,
                user_id=user_id,
                sentiment=sentiment,
                label=SentimentLabel.from_score(sentiment),
                commented_at=commented_at,
            )
        )
        stats.rows_accepted += 1

    _apply_stats(stats, context)
    _guard_rejection_rate(stats, max_rejection_rate)
    return comments, stats


def clean_page_shares(
    rows: Sequence[Mapping[str, Any]],
    max_rejection_rate: float = 0.95,
) -> tuple[list[PageShare], CleaningStats]:
    """Clean the ``PageShares`` dataset.

    Rules applied:

    * ``content_id`` and ``share_user_id`` are required;
    * the natural key ``(content_id, share_user_id)`` must be unique.

    Parameters
    ----------
    rows:
        The raw rows of the dataset.
    max_rejection_rate:
        Upper bound of the share of rows that may be rejected.

    Returns
    -------
    tuple[list[PageShare], CleaningStats]
        The cleaned shares and the statistics of the cleaning run.

    Raises
    ------
    DataQualityError
        If more than ``1 - max_rejection_rate`` of the rows are rejected.
    """
    stats = CleaningStats(dataset="PageShares")
    context = CleaningContext()
    seen: set[tuple[str, str]] = set()
    shares: list[PageShare] = []

    for row in rows:
        stats.rows_read += 1
        try:
            content_id = _require(row, "content_id")
        except (KeyError, ValueError):
            stats.reject("missing_content_id")
            continue
        try:
            user_id = _require(row, "share_user_id")
        except (KeyError, ValueError):
            stats.reject("missing_share_user_id")
            continue

        key = (content_id, user_id)
        if key in seen:
            stats.duplicates_removed += 1
            stats.reject("duplicate_share")
            continue
        seen.add(key)

        shared_at = parse_datetime(row.get("share_date"), default=None)
        shares.append(
            PageShare(content_id=content_id, share_user_id=user_id, shared_at=shared_at)
        )
        stats.rows_accepted += 1

    _apply_stats(stats, context)
    _guard_rejection_rate(stats, max_rejection_rate)
    return shares, stats


def clean_page_views(
    rows: Sequence[Mapping[str, Any]],
    max_rejection_rate: float = 0.95,
) -> tuple[list[PageView], CleaningStats]:
    """Clean the ``PageViews`` dataset.

    Rules applied:

    * ``content_id`` and ``view_user_id`` are required;
    * ``view_seconds`` is clamped to ``>= 0`` and clipped at
      ``86_400`` (one day) to neutralize corrupted durations;
    * the natural key ``(content_id, view_user_id, view_date)`` must be
      unique.  A user may legitimately view the same content on several
      days, so only the *same-day* repetitions are treated as duplicates.

    Parameters
    ----------
    rows:
        The raw rows of the dataset.
    max_rejection_rate:
        Upper bound of the share of rows that may be rejected.

    Returns
    -------
    tuple[list[PageView], CleaningStats]
        The cleaned views and the statistics of the cleaning run.

    Raises
    ------
    DataQualityError
        If more than ``1 - max_rejection_rate`` of the rows are rejected.
    """
    stats = CleaningStats(dataset="PageViews")
    context = CleaningContext()
    seen: set[tuple[str, str, str]] = set()
    views: list[PageView] = []

    for row in rows:
        stats.rows_read += 1
        try:
            content_id = _require(row, "content_id")
        except (KeyError, ValueError):
            stats.reject("missing_content_id")
            continue
        try:
            user_id = _require(row, "view_user_id")
        except (KeyError, ValueError):
            stats.reject("missing_view_user_id")
            continue

        view_date = normalize_identifier(row.get("view_date"))
        key = (content_id, user_id, view_date)
        if key in seen:
            stats.duplicates_removed += 1
            stats.reject("duplicate_view")
            continue
        seen.add(key)

        seconds = parse_non_negative_int(row.get("view_seconds"), default=0)
        if seconds > 86_400:
            seconds = 86_400
            context.outliers_clipped += 1

        viewed_at = parse_datetime(row.get("view_date"), default=None)
        views.append(
            PageView(
                content_id=content_id,
                view_user_id=user_id,
                view_seconds=seconds,
                viewed_at=viewed_at,
            )
        )
        stats.rows_accepted += 1

    _apply_stats(stats, context)
    _guard_rejection_rate(stats, max_rejection_rate)
    return views, stats


def _winsorize_scores(scores: Sequence[int]) -> tuple[dict[int, int], float, float]:
    """Compute the outlier-clipping map of the content scores.

    The *tukey* rule (Q1 - 1.5*IQR / Q3 + 1.5*IQR) is used: it keeps
    working on the small catalogues that a single export can contain,
    where a quantile-based fence would coincide with the minimum and the
    maximum and would therefore never clip anything.
    """
    if len(scores) < 20:
        return {}, float(min(scores, default=0)), float(max(scores, default=0))
    clipping, lower, upper = iqr_outlier_map([float(score) for score in scores], factor=3.0)
    integer_clipping = {
        int(value): max(0, int(round(target))) for value, target in clipping.items()
    }
    return integer_clipping, lower, upper


def _apply_stats(stats: CleaningStats, context: CleaningContext) -> None:
    """Copy the counters of a cleaning context into the statistics."""
    stats.missing_filled += context.missing_filled
    stats.values_normalized += context.values_normalized
    stats.outliers_clipped += context.outliers_clipped


def _guard_rejection_rate(
    stats: CleaningStats,
    max_rejection_rate: float,
    rate_check_min_rows: int = 100,
    max_rejected_rows_small: int = 10,
) -> None:
    """Raise when too many rows of a dataset have been rejected.

    The guard uses two complementary rules, because a single *rate* is a
    poor guard for small reference datasets: rejecting 2 of the 10 rows of
    a ``ReactionTypes`` lookup table is harmless, while rejecting 2 of 10
    rows of a 120k-row event dataset is a disaster.

    * a dataset with at least ``rate_check_min_rows`` rows must not lose
      more than ``1 - max_rejection_rate`` of them;
    * a smaller dataset must not lose more than ``max_rejected_rows_small``
      rows in absolute terms.

    Raises
    ------
    DataQualityError
        If one of the two rules is violated.
    """
    if stats.rows_read == 0:
        return
    rejection_rate = stats.rows_rejected / stats.rows_read
    if stats.rows_read >= rate_check_min_rows:
        if rejection_rate > 1.0 - max_rejection_rate:
            raise DataQualityError(
                f"dataset {stats.dataset!r} rejected {rejection_rate:.1%} of its rows, "
                f"which exceeds the allowed {1.0 - max_rejection_rate:.1%}"
            )
    elif stats.rows_rejected > max_rejected_rows_small:
        raise DataQualityError(
            f"dataset {stats.dataset!r} rejected {stats.rows_rejected} of its "
            f"{stats.rows_read} rows, which exceeds the absolute budget of "
            f"{max_rejected_rows_small} rows"
        )

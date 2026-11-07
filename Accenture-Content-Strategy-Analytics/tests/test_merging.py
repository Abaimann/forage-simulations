"""Unit tests of the relational merge layer."""

from __future__ import annotations

from dataclasses import dataclass

import pytest

from social_buzz_analytics.application.merging import (
    INNER_JOIN,
    LEFT_JOIN,
    build_reaction_type_map,
    count_duplicate_reactions,
    join_on_key,
    referential_integrity_report,
)
from social_buzz_analytics.domain.entities import Reaction, ReactionTypeDefinition
from social_buzz_analytics.domain.exceptions import JoinKeyError
from social_buzz_analytics.domain.value_objects import ReactionType


@dataclass(frozen=True)
class _Row:
    """A minimal row used by the join tests."""

    key: str
    payload: str = ""


class TestJoinStrategy:
    """Tests of the :class:`JoinStrategy` enumeration."""

    def test_values(self) -> None:
        """The strategies carry the expected values."""
        assert LEFT_JOIN.value == "left"
        assert INNER_JOIN.value == "inner"

    def test_str_is_the_value(self) -> None:
        """``str()`` returns the raw value."""
        assert str(LEFT_JOIN) == "left"


class TestJoinOnKey:
    """Tests of :func:`join_on_key`."""

    def test_matching_rows_are_paired(self) -> None:
        """A matching pair is returned."""
        left = [_Row("a"), _Row("b")]
        right = [_Row("a", "payload")]
        pairs, report = join_on_key(left, right, lambda r: r.key, lambda r: r.key)
        assert len(pairs) == 2
        assert pairs[0][1] is not None
        assert pairs[0][1].payload == "payload"
        assert report.matched_rows == 1
        assert report.unmatched_rows == 1

    def test_left_join_keeps_unmatched_rows(self) -> None:
        """A left join keeps the unmatched left rows."""
        left = [_Row("a"), _Row("z")]
        right = [_Row("a")]
        pairs, report = join_on_key(left, right, lambda r: r.key, lambda r: r.key)
        assert len(pairs) == 2
        assert pairs[1][1] is None
        assert report.unmatched_rows == 1

    def test_inner_join_drops_unmatched_rows(self) -> None:
        """An inner join drops the unmatched left rows."""
        left = [_Row("a"), _Row("z")]
        right = [_Row("a")]
        pairs, report = join_on_key(
            left, right, lambda r: r.key, lambda r: r.key, strategy=INNER_JOIN
        )
        assert len(pairs) == 1
        assert report.unmatched_rows == 1

    def test_empty_left_side(self) -> None:
        """Joining an empty left side yields an empty result."""
        pairs, report = join_on_key([], [_Row("a")], lambda r: r.key, lambda r: r.key)
        assert pairs == []
        assert report.matched_rows == 0
        assert report.match_rate == 0.0

    def test_empty_right_side(self) -> None:
        """Joining against an empty right side leaves every row unmatched."""
        pairs, report = join_on_key([_Row("a")], [], lambda r: r.key, lambda r: r.key)
        assert len(pairs) == 1
        assert pairs[0][1] is None
        assert report.right_rows == 0

    def test_duplicate_right_keys_are_counted(self) -> None:
        """The duplicated right keys are reported."""
        left = [_Row("a")]
        right = [_Row("a"), _Row("a")]
        _, report = join_on_key(left, right, lambda r: r.key, lambda r: r.key)
        assert report.duplicate_keys == 1

    def test_first_right_row_wins_on_duplicates(self) -> None:
        """The join never inflates the left side."""
        left = [_Row("a")]
        right = [_Row("a", "first"), _Row("a", "second")]
        pairs, _ = join_on_key(left, right, lambda r: r.key, lambda r: r.key)
        assert len(pairs) == 1
        assert pairs[0][1].payload == "first"

    def test_null_key_raises(self) -> None:
        """A null join key raises a :class:`JoinKeyError`."""
        left = [_Row("")]
        with pytest.raises(JoinKeyError, match="null join key"):
            join_on_key(left, [], lambda r: r.key, lambda r: r.key)

    def test_match_rate_is_computed(self) -> None:
        """The match rate is expressed in percent."""
        left = [_Row("a"), _Row("b"), _Row("c"), _Row("d")]
        right = [_Row("a"), _Row("b")]
        _, report = join_on_key(left, right, lambda r: r.key, lambda r: r.key)
        assert report.match_rate == pytest.approx(50.0)

    def test_report_is_serializable(self) -> None:
        """The report exposes a JSON-serializable snapshot."""
        _, report = join_on_key([_Row("a")], [_Row("a")], lambda r: r.key, lambda r: r.key)
        payload = report.as_dict()
        assert payload["name"] == "join"
        assert payload["matched_rows"] == 1


class TestReferentialIntegrityReport:
    """Tests of :func:`referential_integrity_report`."""

    def test_orphans_are_counted(self) -> None:
        """The events pointing at an unknown content item are counted."""
        events = [_Row("a"), _Row("ghost"), _Row("ghost")]
        report = referential_integrity_report(events, {"a"}, lambda r: r.key, "reactions")
        assert report["reactions_orphan_events"] == 2
        assert report["reactions_total_events"] == 3

    def test_no_orphan(self) -> None:
        """A consistent dataset reports no orphan."""
        events = [_Row("a")]
        report = referential_integrity_report(events, {"a"}, lambda r: r.key, "views")
        assert report["views_orphan_events"] == 0

    def test_empty_event_set(self) -> None:
        """An empty dataset reports zeros."""
        report = referential_integrity_report([], set(), lambda r: r.key, "shares")
        assert report["shares_orphan_events"] == 0
        assert report["shares_total_events"] == 0


class TestReactionTypeMap:
    """Tests of :func:`build_reaction_type_map`."""

    def test_definitions_are_indexed(self) -> None:
        """The definitions are indexed by reaction type."""
        definitions = [
            ReactionTypeDefinition(ReactionType.LIKE, 1, ReactionType.LIKE.sentiment),
            ReactionTypeDefinition(ReactionType.LOVE, 3, ReactionType.LOVE.sentiment),
        ]
        mapping = build_reaction_type_map(definitions)
        assert mapping[ReactionType.LIKE].score == 1
        assert mapping[ReactionType.LOVE].score == 3

    def test_empty_definitions(self) -> None:
        """An empty sequence yields an empty map."""
        assert build_reaction_type_map([]) == {}


class TestCountDuplicateReactions:
    """Tests of :func:`count_duplicate_reactions`."""

    def test_duplicates_are_counted(self) -> None:
        """The duplicated natural keys are counted."""
        reactions = [
            Reaction("C1", "U1", ReactionType.LIKE),
            Reaction("C1", "U1", ReactionType.LIKE),
            Reaction("C2", "U1", ReactionType.LIKE),
        ]
        report = count_duplicate_reactions(reactions)
        assert report["duplicate_reaction_keys"] == 1
        assert report["distinct_reaction_keys"] == 2

    def test_empty_collection(self) -> None:
        """An empty collection reports zeros."""
        report = count_duplicate_reactions([])
        assert report["duplicate_reaction_keys"] == 0
        assert report["distinct_reaction_keys"] == 0

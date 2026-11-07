"""Relational merge strategies.

The seven Social Buzz datasets are related through two keys:

* ``content_id`` links ``Reactions``, ``Comments``, ``PageShares`` and
  ``PageViews`` to ``Content``;
* ``reaction_type`` links ``Reactions`` to the ``ReactionTypes`` reference
  dataset.

The module implements the join strategies in a way that is explicit about
the *cardinality* of every join, because a silent many-to-many join is the
classic source of inflated engagement numbers in social analytics.
"""

from __future__ import annotations

from collections import Counter
from collections.abc import Callable, Hashable, Mapping, Sequence
from dataclasses import dataclass
from enum import Enum
from typing import Generic, TypeVar

from ..domain.entities import Reaction, ReactionTypeDefinition
from ..domain.exceptions import JoinKeyError
from ..domain.value_objects import ReactionType
from .ports import JoinReport

__all__ = [
    "JoinStrategy",
    "LEFT_JOIN",
    "INNER_JOIN",
    "join_on_key",
    "referential_integrity_report",
]

T = TypeVar("T")
U = TypeVar("U")


class JoinStrategy(str, Enum):
    """Enumeration of the supported join semantics."""

    LEFT = "left"
    INNER = "inner"

    def __str__(self) -> str:
        return self.value


LEFT_JOIN: JoinStrategy = JoinStrategy.LEFT
INNER_JOIN: JoinStrategy = JoinStrategy.INNER


@dataclass(frozen=True, slots=True)
class _Index(Generic[U]):
    """Pre-built hash index of the right side of a join.

    Attributes:
        mapping: The rows, grouped by join key.
        duplicate_keys: Number of keys held by more than one row.
    """

    mapping: Mapping[Hashable, list[U]]
    duplicate_keys: int

    @classmethod
    def build(cls, rows: Sequence[U], key: Callable[[U], Hashable]) -> _Index[U]:
        """Index ``rows`` by the value returned by ``key``.

        Parameters
        ----------
        rows:
            The right side of the join.
        key:
            Extracts the join key from a row.

        Returns
        -------
        _Index[U]
            The index, including the count of keys held by more than one row.
        """
        buckets: dict[Hashable, list[U]] = {}
        for row in rows:
            buckets.setdefault(key(row), []).append(row)
        duplicates = sum(1 for bucket in buckets.values() if len(bucket) > 1)
        return cls(mapping=buckets, duplicate_keys=duplicates)


def join_on_key(
    left: Sequence[T],
    right: Sequence[U],
    left_key: Callable[[T], Hashable],
    right_key: Callable[[U], Hashable],
    strategy: JoinStrategy = LEFT_JOIN,
    name: str = "join",
) -> tuple[list[tuple[T, U | None]], JoinReport]:
    """Join two collections on a key with an explicit cardinality contract.

    Parameters
    ----------
    left:
        The left side of the join.
    right:
        The right side of the join.
    left_key:
        Extracts the join key from a left row.
    right_key:
        Extracts the join key from a right row.
    strategy:
        :data:`LEFT_JOIN` keeps unmatched left rows with a ``None`` partner,
        :data:`INNER_JOIN` drops them.
    name:
        Label used in the returned :class:`JoinReport`.

    Returns
    -------
    tuple[list[tuple[T, U | None]], JoinReport]
        The joined pairs and the statistics of the join.

    Raises
    ------
    JoinKeyError
        If a join key is ``None`` or empty.
    """
    index = _Index.build(right, right_key)
    pairs: list[tuple[T, U | None]] = []
    matched = 0
    unmatched = 0

    for row in left:
        key = left_key(row)
        if key is None or key == "":
            raise JoinKeyError(f"null join key encountered in join {name!r}")
        candidates = index.mapping.get(key)
        if candidates:
            matched += 1
            partner = candidates[0]
            pairs.append((row, partner))
        else:
            unmatched += 1
            if strategy is LEFT_JOIN:
                pairs.append((row, None))

    report = JoinReport(
        name=name,
        left_rows=len(left),
        right_rows=len(right),
        matched_rows=matched,
        unmatched_rows=unmatched,
        duplicate_keys=index.duplicate_keys,
    )
    return pairs, report


def referential_integrity_report(
    events: Sequence[T],
    content_ids: set[str],
    key: Callable[[T], str],
    label: str,
) -> dict[str, int]:
    """Count the events whose foreign key does not resolve to a content item.

    Parameters
    ----------
    events:
        The events to check.
    content_ids:
        The set of known content identifiers.
    key:
        Extracts the foreign key from an event.
    label:
        The name of the dataset, used as the key of the returned mapping.

    Returns
    -------
    dict[str, int]
        A mapping with the number of orphan events and the total number of
        checked events.
    """
    total = 0
    orphans = 0
    for event in events:
        total += 1
        if key(event) not in content_ids:
            orphans += 1
    return {f"{label}_orphan_events": orphans, f"{label}_total_events": total}


def build_reaction_type_map(
    definitions: Sequence[ReactionTypeDefinition],
) -> dict[ReactionType, ReactionTypeDefinition]:
    """Index the reaction type definitions by reaction type."""
    return {definition.reaction_type: definition for definition in definitions}


def count_duplicate_reactions(reactions: Sequence[Reaction]) -> dict[str, int]:
    """Count the duplicated reaction keys of a reaction collection."""
    counter = Counter((r.content_id, r.user_id, r.reaction_type) for r in reactions)
    duplicated = sum(1 for count in counter.values() if count > 1)
    return {"duplicate_reaction_keys": duplicated, "distinct_reaction_keys": len(counter)}

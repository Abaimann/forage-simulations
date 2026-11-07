"""Ports (interfaces) that define the boundaries of the application core.

The application layer depends only on these abstractions.  Concrete
implementations live in :mod:`social_buzz_analytics.infrastructure` and may
be swapped for S3, Snowflake, BigQuery, a message bus, ... without touching
the business logic.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from collections.abc import Iterator, Mapping, Sequence
from dataclasses import dataclass, field
from pathlib import Path
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

__all__ = [
    "CommentRepository",
    "ContentRepository",
    "DatasetReader",
    "PageShareRepository",
    "PageViewRepository",
    "ReactionRepository",
    "ReactionTypeRepository",
    "ReportWriter",
    "UserRepository",
]


class DatasetReader(ABC):
    """Reads a raw dataset from a storage medium."""

    @abstractmethod
    def read(self, path: Path) -> Iterator[Mapping[str, Any]]:
        """Yield the raw rows of the dataset located at ``path``.

        Parameters
        ----------
        path:
            Location of the dataset.

        Yields
        ------
        Mapping[str, Any]
            One raw row per record.  Keys are the column names of the file.
        """


class ReactionTypeRepository(ABC):
    """Provides the reference definitions of the reaction types."""

    @abstractmethod
    def all(self) -> Sequence[ReactionTypeDefinition]:
        """Return every known reaction type definition."""


class ContentRepository(ABC):
    """Provides the cleaned content items."""

    @abstractmethod
    def all(self) -> Sequence[ContentItem]:
        """Return every content item."""


class CommentRepository(ABC):
    """Provides the cleaned comments."""

    @abstractmethod
    def all(self) -> Sequence[Comment]:
        """Return every comment."""


class PageShareRepository(ABC):
    """Provides the cleaned shares."""

    @abstractmethod
    def all(self) -> Sequence[PageShare]:
        """Return every share."""


class PageViewRepository(ABC):
    """Provides the cleaned page views."""

    @abstractmethod
    def all(self) -> Sequence[PageView]:
        """Return every page view."""


class ReactionRepository(ABC):
    """Provides the cleaned reaction events."""

    @abstractmethod
    def all(self) -> Sequence[Reaction]:
        """Return every reaction event."""


class UserRepository(ABC):
    """Provides the cleaned audience members."""

    @abstractmethod
    def all(self) -> Sequence[User]:
        """Return every user."""


class ReportWriter(ABC):
    """Persists the analytical summaries of a pipeline run."""

    @abstractmethod
    def write_csv(self, name: str, rows: Sequence[Mapping[str, Any]]) -> Path:
        """Write ``rows`` as a CSV file and return the created path.

        Parameters
        ----------
        name:
            File name (with extension) of the artifact.
        rows:
            The rows to persist, in output order.

        Returns
        -------
        Path
            The path of the written file.
        """

    @abstractmethod
    def write_json(self, name: str, payload: Mapping[str, Any]) -> Path:
        """Write ``payload`` as a JSON file and return the created path.

        Parameters
        ----------
        name:
            File name (with extension) of the artifact.
        payload:
            The JSON-serializable payload.

        Returns
        -------
        Path
            The path of the written file.
        """


@dataclass(slots=True)
class CleaningStats:
    """Per-dataset counters describing what the cleaning stage did.

    Attributes:
        dataset: Name of the dataset the statistics belong to.
        rows_read: Number of raw rows read from the source.
        rows_accepted: Number of rows that survived the cleaning rules.
        rows_rejected: Number of rows dropped by the cleaning rules.
        missing_filled: Number of individual cells imputed.
        values_normalized: Number of individual cells normalized.
        outliers_clipped: Number of individual cells clipped.
        duplicates_removed: Number of duplicate rows removed.
        rejection_reasons: Counter of the reasons that caused a rejection.
    """

    dataset: str
    rows_read: int = 0
    rows_accepted: int = 0
    rows_rejected: int = 0
    missing_filled: int = 0
    values_normalized: int = 0
    outliers_clipped: int = 0
    duplicates_removed: int = 0
    rejection_reasons: dict[str, int] = field(default_factory=dict)

    def reject(self, reason: str) -> None:
        """Record the rejection of one row for ``reason``."""
        self.rows_rejected += 1
        self.rejection_reasons[reason] = self.rejection_reasons.get(reason, 0) + 1

    def as_dict(self) -> dict[str, Any]:
        """Return a JSON-serializable snapshot of the statistics."""
        return {
            "dataset": self.dataset,
            "rows_read": self.rows_read,
            "rows_accepted": self.rows_accepted,
            "rows_rejected": self.rows_rejected,
            "missing_filled": self.missing_filled,
            "values_normalized": self.values_normalized,
            "outliers_clipped": self.outliers_clipped,
            "duplicates_removed": self.duplicates_removed,
            "rejection_reasons": dict(sorted(self.rejection_reasons.items())),
        }


@dataclass(frozen=True, slots=True)
class JoinReport:
    """Statistics of a relational join.

    Attributes:
        name: Name of the join operation.
        left_rows: Number of rows on the left side of the join.
        right_rows: Number of rows on the right side of the join.
        matched_rows: Number of left rows that found a partner.
        unmatched_rows: Number of left rows without a partner.
        duplicate_keys: Number of right-side keys used by more than one row.
    """

    name: str
    left_rows: int
    right_rows: int
    matched_rows: int
    unmatched_rows: int
    duplicate_keys: int

    @property
    def match_rate(self) -> float:
        """Share of left rows that found a partner, in percent."""
        if self.left_rows == 0:
            return 0.0
        return round(self.matched_rows / self.left_rows * 100.0, 4)

    def as_dict(self) -> dict[str, Any]:
        """Return a JSON-serializable snapshot of the join statistics."""
        return {
            "name": self.name,
            "left_rows": self.left_rows,
            "right_rows": self.right_rows,
            "matched_rows": self.matched_rows,
            "unmatched_rows": self.unmatched_rows,
            "duplicate_keys": self.duplicate_keys,
            "match_rate": self.match_rate,
        }

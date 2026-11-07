"""Domain exceptions of the Social Buzz analytics pipeline.

All domain errors inherit from :class:`AnalyticsError` so that a caller can
catch the whole family with a single ``except`` clause, while still being
able to discriminate between the individual failure modes.
"""

from __future__ import annotations

__all__ = [
    "AnalyticsError",
    "CategoryNotFoundError",
    "DataQualityError",
    "DuplicateRecordError",
    "IngestError",
    "JoinKeyError",
    "SchemaValidationError",
]


class AnalyticsError(Exception):
    """Base class of every error raised by the analytics pipeline."""


class IngestError(AnalyticsError):
    """Raised when a raw dataset cannot be read or decoded at all."""


class SchemaValidationError(AnalyticsError):
    """Raised when a dataset does not satisfy its declared schema."""


class DataQualityError(AnalyticsError):
    """Raised when data quality rules reject more records than allowed."""


class DuplicateRecordError(AnalyticsError):
    """Raised when a uniqueness constraint is violated and cannot be repaired."""


class JoinKeyError(AnalyticsError):
    """Raised when a join is attempted on a missing or null key column."""


class CategoryNotFoundError(AnalyticsError):
    """Raised when a segment lookup cannot resolve a requested category."""

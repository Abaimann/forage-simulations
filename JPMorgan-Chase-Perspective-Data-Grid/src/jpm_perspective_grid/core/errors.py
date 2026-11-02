"""Domain-level errors raised across the package.

The domain layer never raises library-specific exceptions: adapters translate
transport/runtime failures into the errors declared here so that the
application layer can stay free of I/O details.
"""

from __future__ import annotations


class GridError(Exception):
    """Base class for every error raised by this package."""


class TickValidationError(GridError, ValueError):
    """A raw tick payload failed validation.

    Attributes
    ----------
    field:
        Name of the offending field when it can be determined, otherwise
        ``None``.
    reason:
        Human readable explanation of *why* the payload was rejected.
    """

    def __init__(self, reason: str, field: str | None = None) -> None:
        self.reason = reason
        self.field = field
        location = f" ({field})" if field else ""
        super().__init__(f"invalid tick{location}: {reason}")


class AggregationError(GridError):
    """Raised when the aggregation engine is used in an inconsistent way."""


class FeedError(GridError):
    """Base class for transport level failures of the tick feed."""


class FeedConnectionError(FeedError):
    """The client could not establish or keep a connection to the feed."""


class FeedProtocolError(FeedError):
    """The peer sent a frame that does not conform to the wire protocol."""

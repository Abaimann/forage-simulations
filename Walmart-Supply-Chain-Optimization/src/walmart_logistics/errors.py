"""Domain-specific exceptions raised by the logistics platform.

The hierarchy keeps a single root (:class:`LogisticsError`) so that callers can
trap every failure of the library with one ``except`` clause, while the
individual error types still inherit from the built-in exception that best
describes them (``IndexError``, ``ValueError``, ``TypeError``).  That keeps
the data structure drop-in compatible with code that already handles
``heapq`` failures.
"""

from __future__ import annotations

__all__ = [
    "EmptyHeapError",
    "InvalidArityError",
    "InvalidPriorityError",
    "LogisticsError",
    "SimulationError",
    "ConfigurationError",
]


class LogisticsError(Exception):
    """Base class for every error raised by :mod:`walmart_logistics`."""


class ConfigurationError(LogisticsError, ValueError):
    """Raised when a configuration object holds an inconsistent value."""


class SimulationError(LogisticsError):
    """Raised when a dispatch simulation cannot produce a valid result."""


class EmptyHeapError(LogisticsError, IndexError):
    """Raised when ``peek``/``pop`` is called on an empty heap.

    It derives from :class:`IndexError` because that is what :mod:`heapq`
    raises in the same situation, so existing ``except IndexError`` blocks
    keep working.
    """


class InvalidArityError(LogisticsError, ValueError):
    """Raised when the requested arity is not a valid power of two."""


class InvalidPriorityError(LogisticsError, TypeError):
    """Raised when a priority cannot be derived from an element.

    Examples: a ``key`` function that returns a non-numeric value while a
    reversed (max) heap was requested, or elements that do not implement
    ``<`` at all.
    """

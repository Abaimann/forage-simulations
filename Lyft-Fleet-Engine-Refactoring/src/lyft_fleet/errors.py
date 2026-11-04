"""Exception hierarchy for the Lyft fleet maintenance domain.

All errors raised by this package inherit from :class:`FleetError` so callers
can catch the whole family with a single ``except`` clause.
"""

from __future__ import annotations


class FleetError(Exception):
    """Base class for every error raised by :mod:`lyft_fleet`."""


class UnknownComponentError(FleetError, KeyError):
    """Raised when a factory is asked for a component/model it does not know.

    It also inherits from :class:`KeyError` so that registry lookups behave
    like mapping lookups for callers used to that idiom.
    """

    def __str__(self) -> str:  # pragma: no cover - trivial
        return ", ".join(str(arg) for arg in self.args)


class InvalidServiceContextError(FleetError, ValueError):
    """Raised when service readings violate a domain invariant.

    For example a negative odometer value, a last-service mileage greater
    than the current mileage, or a tyre wear value outside ``[0.0, 1.0]``.
    """


class InvalidSpecificationError(FleetError, ValueError):
    """Raised when a component is configured with an unusable specification."""

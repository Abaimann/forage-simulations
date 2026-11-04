"""Immutable value objects shared by the whole domain layer.

The domain never mutates state: every service decision is derived from an
immutable :class:`ServiceContext` snapshot.  This makes the system trivially
thread-safe, trivially serialisable and easy to reason about in tests.
"""

from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass, field
from datetime import date

from lyft_fleet.errors import InvalidServiceContextError

__all__ = ["ServiceContext", "add_years"]


def add_years(base: date, years: int) -> date:
    """Return ``base`` shifted by ``years`` calendar years.

    ``date.replace`` raises :class:`ValueError` for ``29 February`` in a
    non-leap target year.  Rather than crashing a maintenance decision we
    clamp the day to the 28th, which is the conventional business rule.

    Args:
        base: The reference date.
        years: Number of calendar years to add. Must be non-negative.

    Returns:
        The shifted date.

    Raises:
        ValueError: If ``years`` is negative.
    """
    if years < 0:
        raise ValueError("years must be non-negative")
    try:
        return base.replace(year=base.year + years)
    except ValueError:
        # 29 February in a non-leap target year -> clamp to 28 February.
        return base.replace(year=base.year + years, day=28)


@dataclass(frozen=True)
class ServiceContext:
    """An immutable snapshot of every reading required to service a vehicle.

    Attributes:
        current_mileage: Odometer reading now, in miles.
        last_service_mileage: Odometer reading at the previous service.
        current_date: The date the vehicle is being evaluated on.
        last_service_date: The date of the previous service.
        tire_wear: Per-wheel wear ratios in ``[0.0, 1.0]``.  May be empty when
            a vehicle is inspected without tyre sensors available.
        warning_light_on: State of the engine warning light (dashboard telltale).
    """

    current_mileage: int
    last_service_mileage: int
    current_date: date
    last_service_date: date
    tire_wear: tuple[float, ...] = field(default_factory=tuple)
    warning_light_on: bool = False

    def __post_init__(self) -> None:
        object.__setattr__(self, "tire_wear", tuple(self.tire_wear))

        if isinstance(self.current_mileage, bool) or not isinstance(self.current_mileage, int):
            raise InvalidServiceContextError("current_mileage must be an int")
        if isinstance(self.last_service_mileage, bool) or not isinstance(
            self.last_service_mileage, int
        ):
            raise InvalidServiceContextError("last_service_mileage must be an int")
        if self.current_mileage < 0:
            raise InvalidServiceContextError("current_mileage must be non-negative")
        if self.last_service_mileage < 0:
            raise InvalidServiceContextError("last_service_mileage must be non-negative")
        if self.last_service_mileage > self.current_mileage:
            raise InvalidServiceContextError(
                "last_service_mileage cannot be greater than current_mileage"
            )
        if self.current_date < self.last_service_date:
            raise InvalidServiceContextError(
                "current_date cannot be earlier than last_service_date"
            )
        for index, wear in enumerate(self.tire_wear):
            if isinstance(wear, bool) or not isinstance(wear, (int, float)):
                raise InvalidServiceContextError(f"tire_wear[{index}] must be a number")
            if not 0.0 <= float(wear) <= 1.0:
                raise InvalidServiceContextError(
                    f"tire_wear[{index}] must be between 0.0 and 1.0 inclusive"
                )

    @property
    def miles_since_service(self) -> int:
        """Miles driven since the previous service."""
        return self.current_mileage - self.last_service_mileage

    @property
    def days_since_service(self) -> int:
        """Whole days elapsed since the previous service."""
        return (self.current_date - self.last_service_date).days

    @property
    def max_tire_wear(self) -> float:
        """Highest wear ratio across all wheels (``0.0`` when no data)."""
        return max(self.tire_wear) if self.tire_wear else 0.0

    @property
    def total_tire_wear(self) -> float:
        """Sum of the wear ratios across all wheels (``0.0`` when no data)."""
        return sum(self.tire_wear)

    @classmethod
    def build(
        cls,
        *,
        current_mileage: int,
        last_service_mileage: int,
        current_date: date,
        last_service_date: date,
        tire_wear: Iterable[float] = (),
        warning_light_on: bool = False,
    ) -> ServiceContext:
        """Construct a context from loose keyword arguments.

        This mirrors the constructor but accepts any iterable for
        ``tire_wear`` and normalises it to a tuple, which keeps call sites in
        tests and factories terse.
        """
        return cls(
            current_mileage=current_mileage,
            last_service_mileage=last_service_mileage,
            current_date=current_date,
            last_service_date=last_service_date,
            tire_wear=tuple(tire_wear),
            warning_light_on=warning_light_on,
        )

    def __str__(self) -> str:
        return (
            f"ServiceContext(mileage={self.current_mileage}, "
            f"last_service_mileage={self.last_service_mileage}, "
            f"current_date={self.current_date.isoformat()}, "
            f"last_service_date={self.last_service_date.isoformat()}, "
            f"tire_wear={self.tire_wear}, "
            f"warning_light_on={self.warning_light_on})"
        )

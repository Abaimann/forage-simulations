"""Strategy pattern for service criteria.

A *criterion* is a single, self-contained rule that answers one question:
"given this :class:`~lyft_fleet.domain.value_objects.ServiceContext`, is this
component due for service?"

The three families required by the business are modelled here:

============================  ==========================================
Criterion                     Business trigger
============================  ==========================================
:class:`MileageCriterion`     mileage based trigger (distance driven)
:class:`CalendarCriterion`    calendar based interval (time elapsed)
:class:`WearThresholdCriterion`  sensor wear threshold (tyre wear sensors)
============================  ==========================================

:class:`WarningLightCriterion` covers the remaining dashboard-telltale signal,
and :class:`AnyCriterion` / :class:`AllCriterion` allow rules to be composed
without subclassing.

Adding a new rule therefore never requires touching an existing component:
implement the :class:`ServiceCriterion` interface and inject it.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from collections.abc import Iterable
from dataclasses import dataclass
from enum import Enum

from lyft_fleet.domain.value_objects import ServiceContext, add_years
from lyft_fleet.errors import InvalidSpecificationError

__all__ = [
    "Aggregation",
    "AllCriterion",
    "AnyCriterion",
    "CalendarCriterion",
    "MileageCriterion",
    "ServiceCriterion",
    "WarningLightCriterion",
    "WearThresholdCriterion",
]


class Aggregation(str, Enum):
    """How multiple sensor readings are combined into a single wear figure."""

    MAX = "max"
    """Use the worst reading of the set (any wheel over the limit)."""

    SUM = "sum"
    """Use the total of all readings (combined wear across the set)."""


class ServiceCriterion(ABC):
    """A single service rule.

    Criteria are immutable, stateless and side-effect free: given the same
    context they always produce the same answer.
    """

    @abstractmethod
    def is_due(self, context: ServiceContext) -> bool:
        """Return ``True`` when this criterion requires a service."""

    @abstractmethod
    def describe(self) -> str:
        """Return a short human readable description of the rule."""

    def __str__(self) -> str:
        return self.describe()

    def __repr__(self) -> str:
        return f"{type(self).__name__}()"


@dataclass(frozen=True)
class MileageCriterion(ServiceCriterion):
    """Distance based trigger.

    The criterion is due once the vehicle has driven **strictly more** than
    ``interval_miles`` since the previous service.  Using a strict comparison
    matches the historical Lyft rule ("more than 30 000 miles") and keeps the
    boundary case (exactly at the limit) out of service.

    Args:
        interval_miles: Number of miles allowed between two services.
    """

    interval_miles: int

    def __post_init__(self) -> None:
        if self.interval_miles < 0:
            raise InvalidSpecificationError("interval_miles must be non-negative")

    def is_due(self, context: ServiceContext) -> bool:
        """Return ``True`` when more than ``interval_miles`` have been driven."""
        return context.miles_since_service > self.interval_miles

    def describe(self) -> str:
        """Describe the rule in human readable terms."""
        return f"more than {self.interval_miles} miles driven since last service"


@dataclass(frozen=True)
class CalendarCriterion(ServiceCriterion):
    """Time based trigger.

    The criterion is due once **strictly more** than ``interval_years`` have
    elapsed since the previous service date.

    Args:
        interval_years: Number of years allowed between two services.
    """

    interval_years: int

    def __post_init__(self) -> None:
        if self.interval_years < 0:
            raise InvalidSpecificationError("interval_years must be non-negative")

    def is_due(self, context: ServiceContext) -> bool:
        """Return ``True`` when more than ``interval_years`` have elapsed."""
        threshold = add_years(context.last_service_date, self.interval_years)
        return context.current_date > threshold

    def describe(self) -> str:
        """Describe the rule in human readable terms."""
        return f"more than {self.interval_years} year(s) elapsed since last service"


@dataclass(frozen=True)
class WearThresholdCriterion(ServiceCriterion):
    """Sensor wear threshold.

    Args:
        threshold: The wear limit that trips the rule.
        aggregation: Whether the threshold applies to the worst wheel
            (:attr:`Aggregation.MAX`) or to the combined wear of the set
            (:attr:`Aggregation.SUM`).
    """

    threshold: float
    aggregation: Aggregation = Aggregation.MAX

    def __post_init__(self) -> None:
        if self.threshold < 0:
            raise InvalidSpecificationError("threshold must be non-negative")
        if not isinstance(self.aggregation, Aggregation):
            raise InvalidSpecificationError(
                f"aggregation must be an Aggregation, got {type(self.aggregation).__name__}"
            )

    def is_due(self, context: ServiceContext) -> bool:
        """Return ``True`` when the aggregated wear reaches the threshold."""
        if not context.tire_wear:
            # No sensor data -> the rule cannot trip.
            return False
        if self.aggregation is Aggregation.MAX:
            return context.max_tire_wear >= self.threshold
        return context.total_tire_wear >= self.threshold

    def describe(self) -> str:
        """Describe the rule in human readable terms."""
        if self.aggregation is Aggregation.MAX:
            return f"any wheel wear at or above {self.threshold}"
        return f"combined wheel wear at or above {self.threshold}"


@dataclass(frozen=True)
class WarningLightCriterion(ServiceCriterion):
    """Dashboard telltale trigger (engine warning light)."""

    def is_due(self, context: ServiceContext) -> bool:
        """Return ``True`` when the engine warning light is on."""
        return context.warning_light_on

    def describe(self) -> str:
        """Describe the rule in human readable terms."""
        return "engine warning light is on"


@dataclass(frozen=True)
class AnyCriterion(ServiceCriterion):
    """Composite criterion: due when **any** child criterion is due."""

    criteria: tuple[ServiceCriterion, ...]

    def __init__(self, criteria: Iterable[ServiceCriterion]) -> None:
        normalised = tuple(criteria)
        if not normalised:
            raise InvalidSpecificationError("AnyCriterion requires at least one criterion")
        for criterion in normalised:
            if not isinstance(criterion, ServiceCriterion):
                raise InvalidSpecificationError(
                    f"expected ServiceCriterion, got {type(criterion).__name__}"
                )
        object.__setattr__(self, "criteria", normalised)

    def is_due(self, context: ServiceContext) -> bool:
        """Return ``True`` when any child criterion is due."""
        return any(criterion.is_due(context) for criterion in self.criteria)

    def describe(self) -> str:
        """Describe the rule in human readable terms."""
        return "any of (" + "; ".join(c.describe() for c in self.criteria) + ")"


@dataclass(frozen=True)
class AllCriterion(ServiceCriterion):
    """Composite criterion: due only when **every** child criterion is due."""

    criteria: tuple[ServiceCriterion, ...]

    def __init__(self, criteria: Iterable[ServiceCriterion]) -> None:
        normalised = tuple(criteria)
        if not normalised:
            raise InvalidSpecificationError("AllCriterion requires at least one criterion")
        for criterion in normalised:
            if not isinstance(criterion, ServiceCriterion):
                raise InvalidSpecificationError(
                    f"expected ServiceCriterion, got {type(criterion).__name__}"
                )
        object.__setattr__(self, "criteria", normalised)

    def is_due(self, context: ServiceContext) -> bool:
        """Return ``True`` when every child criterion is due."""
        return all(criterion.is_due(context) for criterion in self.criteria)

    def describe(self) -> str:
        """Describe the rule in human readable terms."""
        return "all of (" + "; ".join(c.describe() for c in self.criteria) + ")"

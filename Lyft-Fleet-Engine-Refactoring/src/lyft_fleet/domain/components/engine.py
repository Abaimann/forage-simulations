"""Engine components.

All engines share one implementation: the difference between a Capulet, a
Willoughby and a Sternman is *only* the set of :class:`ServiceCriterion`
objects they are built with.  This is the Strategy pattern applied to the
domain: the rule lives outside the component.
"""

from __future__ import annotations

from collections.abc import Sequence

from lyft_fleet import config
from lyft_fleet.domain.criteria import (
    MileageCriterion,
    ServiceCriterion,
    WarningLightCriterion,
)
from lyft_fleet.domain.serviceable import Serviceable
from lyft_fleet.domain.value_objects import ServiceContext
from lyft_fleet.errors import InvalidSpecificationError

__all__ = ["CapuletEngine", "Engine", "SternmanEngine", "WilloughbyEngine"]


class Engine(Serviceable):
    """Base engine.

    An engine is judged by the criteria it is configured with.  Subclasses
    supply the domain rules; the evaluation logic is inherited unchanged.

    Args:
        criteria: The rules that decide whether the engine is due for service.
        name: Human readable identifier, used in service reports.

    Raises:
        InvalidSpecificationError: If ``criteria`` is empty or contains an
            object that is not a :class:`ServiceCriterion`.
    """

    def __init__(self, criteria: Sequence[ServiceCriterion], *, name: str = "engine") -> None:
        normalised = tuple(criteria)
        if not normalised:
            raise InvalidSpecificationError("an engine requires at least one criterion")
        for criterion in normalised:
            if not isinstance(criterion, ServiceCriterion):
                raise InvalidSpecificationError(
                    f"expected ServiceCriterion, got {type(criterion).__name__}"
                )
        self._criteria = normalised
        self._name = name

    @property
    def name(self) -> str:
        """Human readable identifier of the engine."""
        return self._name

    @property
    def criteria(self) -> tuple[ServiceCriterion, ...]:
        """The immutable rule set backing this engine."""
        return self._criteria

    @property
    def component_type(self) -> str:
        """Category of the component, used for reporting."""
        return "engine"

    def needs_service(self, context: ServiceContext) -> bool:
        """Return ``True`` when any configured criterion is due."""
        return any(criterion.is_due(context) for criterion in self._criteria)

    def service_reasons(self, context: ServiceContext) -> tuple[str, ...]:
        """Explain which criteria tripped for this engine."""
        return tuple(
            f"Engine {self._name}: {criterion.describe()}"
            for criterion in self._criteria
            if criterion.is_due(context)
        )

    def __repr__(self) -> str:
        return f"{type(self).__name__}(name={self._name!r})"


class CapuletEngine(Engine):
    """Capulet engine: serviced after more than 30 000 miles.

    Args:
        interval_miles: Optional override of the service interval.
    """

    def __init__(self, interval_miles: int = config.CAPULET_SERVICE_INTERVAL_MILES) -> None:
        super().__init__((MileageCriterion(interval_miles),), name="Capulet")


class WilloughbyEngine(Engine):
    """Willoughby engine: serviced after more than 60 000 miles.

    Args:
        interval_miles: Optional override of the service interval.
    """

    def __init__(self, interval_miles: int = config.WILLOUGHBY_SERVICE_INTERVAL_MILES) -> None:
        super().__init__((MileageCriterion(interval_miles),), name="Willoughby")


class SternmanEngine(Engine):
    """Sternman engine: serviced when the engine warning light is on.

    Args:
        criteria: Optional override of the rule set; defaults to the
            dashboard telltale check.
    """

    def __init__(self, criteria: Sequence[ServiceCriterion] | None = None) -> None:
        rules: tuple[ServiceCriterion, ...] = (
            (WarningLightCriterion(),) if criteria is None else tuple(criteria)
        )
        super().__init__(rules, name="Sternman")

"""Battery components.

Batteries are governed by calendar based intervals: their chemistry ages with
time, not with distance driven.
"""

from __future__ import annotations

from collections.abc import Sequence

from lyft_fleet import config
from lyft_fleet.domain.criteria import CalendarCriterion, ServiceCriterion
from lyft_fleet.domain.serviceable import Serviceable
from lyft_fleet.domain.value_objects import ServiceContext
from lyft_fleet.errors import InvalidSpecificationError

__all__ = ["Battery", "NubbinBattery", "SpindlerBattery"]


class Battery(Serviceable):
    """Base battery.

    Args:
        criteria: The rules that decide whether the battery is due for service.
        name: Human readable identifier, used in service reports.

    Raises:
        InvalidSpecificationError: If ``criteria`` is empty or contains an
            object that is not a :class:`ServiceCriterion`.
    """

    def __init__(self, criteria: Sequence[ServiceCriterion], *, name: str = "battery") -> None:
        normalised = tuple(criteria)
        if not normalised:
            raise InvalidSpecificationError("a battery requires at least one criterion")
        for criterion in normalised:
            if not isinstance(criterion, ServiceCriterion):
                raise InvalidSpecificationError(
                    f"expected ServiceCriterion, got {type(criterion).__name__}"
                )
        self._criteria = normalised
        self._name = name

    @property
    def name(self) -> str:
        """Human readable identifier of the battery."""
        return self._name

    @property
    def criteria(self) -> tuple[ServiceCriterion, ...]:
        """The immutable rule set backing this battery."""
        return self._criteria

    @property
    def component_type(self) -> str:
        """Category of the component, used for reporting."""
        return "battery"

    def needs_service(self, context: ServiceContext) -> bool:
        """Return ``True`` when any configured criterion is due."""
        return any(criterion.is_due(context) for criterion in self._criteria)

    def service_reasons(self, context: ServiceContext) -> tuple[str, ...]:
        """Explain which criteria tripped for this battery."""
        return tuple(
            f"Battery {self._name}: {criterion.describe()}"
            for criterion in self._criteria
            if criterion.is_due(context)
        )

    def __repr__(self) -> str:
        return f"{type(self).__name__}(name={self._name!r})"


class NubbinBattery(Battery):
    """Nubbin battery: four year calendar lifetime.

    Args:
        lifetime_years: Optional override of the calendar lifetime.
    """

    def __init__(self, lifetime_years: int = config.NUBBIN_BATTERY_LIFETIME_YEARS) -> None:
        super().__init__((CalendarCriterion(lifetime_years),), name="Nubbin")


class SpindlerBattery(Battery):
    """Spindler battery: three year calendar lifetime.

    Args:
        lifetime_years: Optional override of the calendar lifetime.
    """

    def __init__(self, lifetime_years: int = config.SPINDLER_BATTERY_LIFETIME_YEARS) -> None:
        super().__init__((CalendarCriterion(lifetime_years),), name="Spindler")

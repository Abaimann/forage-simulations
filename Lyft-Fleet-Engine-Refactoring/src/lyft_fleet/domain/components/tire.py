"""Tyre components.

Tyres wear according to sensor readings rather than time or distance.  Two
aggregation strategies exist in the fleet:

* :class:`CarriganTire` trips when **any single wheel** is worn out.
* :class:`OctoprimeTire` trips when the **combined** wear of the set is too
  high, allowing a moderate amount of wear spread over all wheels.
"""

from __future__ import annotations

from collections.abc import Sequence

from lyft_fleet import config
from lyft_fleet.domain.criteria import Aggregation, ServiceCriterion, WearThresholdCriterion
from lyft_fleet.domain.serviceable import Serviceable
from lyft_fleet.domain.value_objects import ServiceContext
from lyft_fleet.errors import InvalidSpecificationError

__all__ = ["CarriganTire", "OctoprimeTire", "Tire"]


class Tire(Serviceable):
    """Base tyre.

    Args:
        criteria: The rules that decide whether the tyre is due for service.
        name: Human readable identifier, used in service reports.

    Raises:
        InvalidSpecificationError: If ``criteria`` is empty or contains an
            object that is not a :class:`ServiceCriterion`.
    """

    def __init__(self, criteria: Sequence[ServiceCriterion], *, name: str = "tire") -> None:
        normalised = tuple(criteria)
        if not normalised:
            raise InvalidSpecificationError("a tire requires at least one criterion")
        for criterion in normalised:
            if not isinstance(criterion, ServiceCriterion):
                raise InvalidSpecificationError(
                    f"expected ServiceCriterion, got {type(criterion).__name__}"
                )
        self._criteria = normalised
        self._name = name

    @property
    def name(self) -> str:
        """Human readable identifier of the tyre."""
        return self._name

    @property
    def criteria(self) -> tuple[ServiceCriterion, ...]:
        """The immutable rule set backing this tyre."""
        return self._criteria

    @property
    def component_type(self) -> str:
        """Category of the component, used for reporting."""
        return "tire"

    def needs_service(self, context: ServiceContext) -> bool:
        """Return ``True`` when any configured criterion is due."""
        return any(criterion.is_due(context) for criterion in self._criteria)

    def service_reasons(self, context: ServiceContext) -> tuple[str, ...]:
        """Explain which criteria tripped for this tyre."""
        return tuple(
            f"Tire {self._name}: {criterion.describe()}"
            for criterion in self._criteria
            if criterion.is_due(context)
        )

    def __repr__(self) -> str:
        return f"{type(self).__name__}(name={self._name!r})"


class CarriganTire(Tire):
    """Carrigan tyre: trips when a single wheel reaches 90 % wear.

    Args:
        threshold: Optional override of the per-wheel wear limit.
    """

    def __init__(self, threshold: float = config.CARRIGAN_TIRE_WEAR_THRESHOLD) -> None:
        super().__init__(
            (WearThresholdCriterion(threshold, Aggregation.MAX),),
            name="Carrigan",
        )


class OctoprimeTire(Tire):
    """Octoprime tyre: trips when the combined wear reaches 3.0.

    Args:
        threshold: Optional override of the combined wear limit.
    """

    def __init__(self, threshold: float = config.OCTOPRIME_TIRE_TOTAL_WEAR_THRESHOLD) -> None:
        super().__init__(
            (WearThresholdCriterion(threshold, Aggregation.SUM),),
            name="Octoprime",
        )

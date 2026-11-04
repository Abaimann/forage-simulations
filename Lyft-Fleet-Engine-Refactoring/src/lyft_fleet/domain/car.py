"""The :class:`Car` aggregate and the five models of the Lyft rental fleet.

A car is a *composition* of a engine, a battery and a tyre set, plus any
number of fleet-wide inspection criteria.  The aggregate holds no servicing
logic of its own: it delegates to its parts and to its inspection criteria.

This is deliberate.  The legacy design made every model inherit from an engine
class (``class Calliope(CapuletEngine)``), which forced a car to be an
engine, duplicated the service rules five times and made it impossible to
compose a car from parts that were not already hard-wired together.  Here the
models only *declare* their parts; all behaviour is inherited from
:class:`Car`.
"""

from __future__ import annotations

from abc import ABC
from collections.abc import Iterable, Sequence

from lyft_fleet import config
from lyft_fleet.domain.components.battery import Battery
from lyft_fleet.domain.components.engine import Engine
from lyft_fleet.domain.components.tire import Tire
from lyft_fleet.domain.criteria import CalendarCriterion, ServiceCriterion
from lyft_fleet.domain.serviceable import Serviceable
from lyft_fleet.domain.value_objects import ServiceContext

__all__ = [
    "Calliope",
    "Car",
    "Glissando",
    "Palindrome",
    "Rorschach",
    "Thovex",
]


class Car(Serviceable):
    """A vehicle built from an engine, a battery and a tyre set.

    Args:
        engine: The engine installed in the vehicle.
        battery: The battery installed in the vehicle.
        tire: The tyre set installed on the vehicle.
        inspection_criteria: Fleet-wide inspection rules evaluated against the
            car as a whole (e.g. the periodic safety inspection).
        name: Human readable model name.

    Raises:
        TypeError: If any component is not of the expected type.
    """

    def __init__(
        self,
        engine: Engine,
        battery: Battery,
        tire: Tire,
        *,
        inspection_criteria: Sequence[ServiceCriterion] = (),
        name: str = "Car",
    ) -> None:
        if not isinstance(engine, Engine):
            raise TypeError(f"engine must be an Engine, got {type(engine).__name__}")
        if not isinstance(battery, Battery):
            raise TypeError(f"battery must be a Battery, got {type(battery).__name__}")
        if not isinstance(tire, Tire):
            raise TypeError(f"tire must be a Tire, got {type(tire).__name__}")
        for criterion in inspection_criteria:
            if not isinstance(criterion, ServiceCriterion):
                raise TypeError(
                    f"inspection criteria must be ServiceCriterion, "
                    f"got {type(criterion).__name__}"
                )
        self._engine = engine
        self._battery = battery
        self._tire = tire
        self._inspection_criteria = tuple(inspection_criteria)
        self._name = name

    # ------------------------------------------------------------------ #
    # Structure
    # ------------------------------------------------------------------ #
    @property
    def name(self) -> str:
        """Human readable model name."""
        return self._name

    @property
    def engine(self) -> Engine:
        """The engine installed in the vehicle."""
        return self._engine

    @property
    def battery(self) -> Battery:
        """The battery installed in the vehicle."""
        return self._battery

    @property
    def tire(self) -> Tire:
        """The tyre set installed on the vehicle."""
        return self._tire

    @property
    def components(self) -> tuple[Serviceable, ...]:
        """Every serviceable part of the vehicle."""
        return (self._engine, self._battery, self._tire)

    @property
    def inspection_criteria(self) -> tuple[ServiceCriterion, ...]:
        """Fleet-wide inspection rules applied to the vehicle as a whole."""
        return self._inspection_criteria

    @property
    def component_type(self) -> str:
        """Category of the component, used for reporting."""
        return "car"

    # ------------------------------------------------------------------ #
    # Behaviour
    # ------------------------------------------------------------------ #
    def needs_service(self, context: ServiceContext) -> bool:
        """Return ``True`` when any part or inspection rule is due.

        A vehicle requires attention as soon as *one* of its systems is due,
        not only when all of them are due simultaneously.
        """
        if any(component.needs_service(context) for component in self.components):
            return True
        return any(criterion.is_due(context) for criterion in self._inspection_criteria)

    def service_reasons(self, context: ServiceContext) -> tuple[str, ...]:
        """Explain every tripped rule, component by component."""
        reasons: list[str] = []
        for component in self.components:
            reasons.extend(component.service_reasons(context))
        for criterion in self._inspection_criteria:
            if criterion.is_due(context):
                reasons.append(f"Inspection {self._name}: {criterion.describe()}")
        return tuple(reasons)

    def __repr__(self) -> str:
        return (
            f"{type(self).__name__}(name={self._name!r}, engine={self._engine!r}, "
            f"battery={self._battery!r}, tire={self._tire!r})"
        )


class _ModelCar(Car, ABC):
    """Base class for the concrete fleet models.

    It exists purely to give the five models a shared declaration point; all
    behaviour lives in :class:`Car`.
    """

    #: Default fleet inspection interval in years, overridden per model.
    INSPECTION_INTERVAL_YEARS: int = 0

    def _default_inspection_criteria(self) -> tuple[ServiceCriterion, ...]:
        if self.INSPECTION_INTERVAL_YEARS <= 0:
            return ()
        return (CalendarCriterion(self.INSPECTION_INTERVAL_YEARS),)


class Calliope(_ModelCar):
    """Calliope: Capulet engine, Spindler battery, Carrigan tyres, 2 year inspection."""

    INSPECTION_INTERVAL_YEARS = config.CALLIOPE_INSPECTION_INTERVAL_YEARS

    def __init__(
        self,
        engine: Engine | None = None,
        battery: Battery | None = None,
        tire: Tire | None = None,
        *,
        inspection_criteria: Iterable[ServiceCriterion] | None = None,
    ) -> None:
        super().__init__(
            engine if engine is not None else self._default_engine(),
            battery if battery is not None else self._default_battery(),
            tire if tire is not None else self._default_tire(),
            inspection_criteria=(
                self._default_inspection_criteria()
                if inspection_criteria is None
                else tuple(inspection_criteria)
            ),
            name="Calliope",
        )

    @staticmethod
    def _default_engine() -> Engine:
        from lyft_fleet.domain.components.engine import CapuletEngine

        return CapuletEngine()

    @staticmethod
    def _default_battery() -> Battery:
        from lyft_fleet.domain.components.battery import SpindlerBattery

        return SpindlerBattery()

    @staticmethod
    def _default_tire() -> Tire:
        from lyft_fleet.domain.components.tire import CarriganTire

        return CarriganTire()


class Glissando(_ModelCar):
    """Glissando: Willoughby engine, Spindler battery, Octoprime tyres, 2 year inspection."""

    INSPECTION_INTERVAL_YEARS = config.GLISSANDO_INSPECTION_INTERVAL_YEARS

    def __init__(
        self,
        engine: Engine | None = None,
        battery: Battery | None = None,
        tire: Tire | None = None,
        *,
        inspection_criteria: Iterable[ServiceCriterion] | None = None,
    ) -> None:
        super().__init__(
            engine if engine is not None else self._default_engine(),
            battery if battery is not None else self._default_battery(),
            tire if tire is not None else self._default_tire(),
            inspection_criteria=(
                self._default_inspection_criteria()
                if inspection_criteria is None
                else tuple(inspection_criteria)
            ),
            name="Glissando",
        )

    @staticmethod
    def _default_engine() -> Engine:
        from lyft_fleet.domain.components.engine import WilloughbyEngine

        return WilloughbyEngine()

    @staticmethod
    def _default_battery() -> Battery:
        from lyft_fleet.domain.components.battery import SpindlerBattery

        return SpindlerBattery()

    @staticmethod
    def _default_tire() -> Tire:
        from lyft_fleet.domain.components.tire import OctoprimeTire

        return OctoprimeTire()


class Palindrome(_ModelCar):
    """Palindrome: Sternman engine, Nubbin battery, Carrigan tyres, 4 year inspection."""

    INSPECTION_INTERVAL_YEARS = config.PALINDROME_INSPECTION_INTERVAL_YEARS

    def __init__(
        self,
        engine: Engine | None = None,
        battery: Battery | None = None,
        tire: Tire | None = None,
        *,
        inspection_criteria: Iterable[ServiceCriterion] | None = None,
    ) -> None:
        super().__init__(
            engine if engine is not None else self._default_engine(),
            battery if battery is not None else self._default_battery(),
            tire if tire is not None else self._default_tire(),
            inspection_criteria=(
                self._default_inspection_criteria()
                if inspection_criteria is None
                else tuple(inspection_criteria)
            ),
            name="Palindrome",
        )

    @staticmethod
    def _default_engine() -> Engine:
        from lyft_fleet.domain.components.engine import SternmanEngine

        return SternmanEngine()

    @staticmethod
    def _default_battery() -> Battery:
        from lyft_fleet.domain.components.battery import NubbinBattery

        return NubbinBattery()

    @staticmethod
    def _default_tire() -> Tire:
        from lyft_fleet.domain.components.tire import CarriganTire

        return CarriganTire()


class Rorschach(_ModelCar):
    """Rorschach: Willoughby engine, Nubbin battery, Octoprime tyres, 4 year inspection."""

    INSPECTION_INTERVAL_YEARS = config.RORSCHACH_INSPECTION_INTERVAL_YEARS

    def __init__(
        self,
        engine: Engine | None = None,
        battery: Battery | None = None,
        tire: Tire | None = None,
        *,
        inspection_criteria: Iterable[ServiceCriterion] | None = None,
    ) -> None:
        super().__init__(
            engine if engine is not None else self._default_engine(),
            battery if battery is not None else self._default_battery(),
            tire if tire is not None else self._default_tire(),
            inspection_criteria=(
                self._default_inspection_criteria()
                if inspection_criteria is None
                else tuple(inspection_criteria)
            ),
            name="Rorschach",
        )

    @staticmethod
    def _default_engine() -> Engine:
        from lyft_fleet.domain.components.engine import WilloughbyEngine

        return WilloughbyEngine()

    @staticmethod
    def _default_battery() -> Battery:
        from lyft_fleet.domain.components.battery import NubbinBattery

        return NubbinBattery()

    @staticmethod
    def _default_tire() -> Tire:
        from lyft_fleet.domain.components.tire import OctoprimeTire

        return OctoprimeTire()


class Thovex(_ModelCar):
    """Thovex: Capulet engine, Nubbin battery, Carrigan tyres, 4 year inspection."""

    INSPECTION_INTERVAL_YEARS = config.THOVEX_INSPECTION_INTERVAL_YEARS

    def __init__(
        self,
        engine: Engine | None = None,
        battery: Battery | None = None,
        tire: Tire | None = None,
        *,
        inspection_criteria: Iterable[ServiceCriterion] | None = None,
    ) -> None:
        super().__init__(
            engine if engine is not None else self._default_engine(),
            battery if battery is not None else self._default_battery(),
            tire if tire is not None else self._default_tire(),
            inspection_criteria=(
                self._default_inspection_criteria()
                if inspection_criteria is None
                else tuple(inspection_criteria)
            ),
            name="Thovex",
        )

    @staticmethod
    def _default_engine() -> Engine:
        from lyft_fleet.domain.components.engine import CapuletEngine

        return CapuletEngine()

    @staticmethod
    def _default_battery() -> Battery:
        from lyft_fleet.domain.components.battery import NubbinBattery

        return NubbinBattery()

    @staticmethod
    def _default_tire() -> Tire:
        from lyft_fleet.domain.components.tire import CarriganTire

        return CarriganTire()

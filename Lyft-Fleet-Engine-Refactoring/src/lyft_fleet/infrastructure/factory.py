"""Factory pattern for fleet components.

Three registries (:class:`EngineFactory`, :class:`BatteryFactory`,
:class:`TireFactory`) build individual parts, and :class:`CarFactory` composes
them into vehicles.  Every factory is an open registry: a new part or a new
model is added by *registering* it, never by editing the factory.

All factories share the same naming convention: names are normalised to
lower case with separators removed, so ``"Calliope"``, ``"calliope"`` and
``"calliope"`` all resolve to the same model.
"""

from __future__ import annotations

from collections.abc import Callable, Iterable, Mapping

from lyft_fleet import config
from lyft_fleet.domain.car import (
    Calliope,
    Car,
    Glissando,
    Palindrome,
    Rorschach,
    Thovex,
)
from lyft_fleet.domain.components.battery import Battery, NubbinBattery, SpindlerBattery
from lyft_fleet.domain.components.engine import (
    CapuletEngine,
    Engine,
    SternmanEngine,
    WilloughbyEngine,
)
from lyft_fleet.domain.components.tire import CarriganTire, OctoprimeTire, Tire
from lyft_fleet.errors import UnknownComponentError

__all__ = [
    "BatteryFactory",
    "CarFactory",
    "EngineFactory",
    "TireFactory",
    "normalize_name",
]

#: A builder produces a component.  It takes no arguments so that a factory
#: can always rebuild a fresh, independent instance.
Builder = Callable[[], object]


def normalize_name(name: str) -> str:
    """Normalise a component or model name for registry lookups.

    Lower-cases the name and removes spaces, underscores and hyphens.

    Args:
        name: The raw name.

    Returns:
        The normalised name.

    Raises:
        TypeError: If ``name`` is not a string.
    """
    if not isinstance(name, str):
        raise TypeError(f"name must be a str, got {type(name).__name__}")
    return name.strip().lower().replace(" ", "").replace("_", "").replace("-", "")


class _Registry:
    """Base class for the name -> builder registries.

    Args:
        builders: Initial mapping of normalised name to builder.

    Raises:
        UnknownComponentError: If two different names normalise to the same
            key, which would silently shadow a registration.
    """

    #: Human readable noun used in error messages, e.g. ``"engine"``.
    kind = "component"

    def __init__(self, builders: Mapping[str, Builder] | None = None) -> None:
        self._builders: dict[str, Builder] = {}
        for name, builder in (builders or {}).items():
            self.register(name, builder)

    def register(self, name: str, builder: Builder) -> None:
        """Register ``builder`` under ``name``.

        Args:
            name: The public name of the component.
            builder: A zero-argument callable returning a new instance.

        Raises:
            TypeError: If ``builder`` is not callable.
            UnknownComponentError: If the name is already registered.
        """
        if not callable(builder):
            raise TypeError("builder must be callable")
        key = normalize_name(name)
        if key in self._builders:
            raise UnknownComponentError(f"{self.kind} '{name}' is already registered")
        self._builders[key] = builder

    def create(self, name: str) -> object:
        """Build the component registered under ``name``.

        Args:
            name: The public name of the component.

        Returns:
            A newly built component.

        Raises:
            UnknownComponentError: If ``name`` is not registered.
        """
        key = normalize_name(name)
        try:
            builder = self._builders[key]
        except KeyError:
            raise UnknownComponentError(
                f"unknown {self.kind} '{name}'; available: {', '.join(self.available())}"
            ) from None
        return builder()

    def available(self) -> tuple[str, ...]:
        """Return the sorted names of every registered component."""
        return tuple(sorted(self._builders))

    def __contains__(self, name: object) -> bool:
        if not isinstance(name, str):
            return False
        return normalize_name(name) in self._builders

    def __len__(self) -> int:
        return len(self._builders)


class EngineFactory(_Registry):
    """Factory for :class:`Engine` components."""

    kind = "engine"

    def __init__(self, builders: Mapping[str, Builder] | None = None) -> None:
        if builders is None:
            builders = {
                "capulet": CapuletEngine,
                "willoughby": WilloughbyEngine,
                "sternman": SternmanEngine,
            }
        super().__init__(builders)

    def create(self, name: str) -> Engine:
        """Build the engine registered under ``name``."""
        engine = super().create(name)
        assert isinstance(engine, Engine)  # noqa: S101 - registry is typed by construction
        return engine


class BatteryFactory(_Registry):
    """Factory for :class:`Battery` components."""

    kind = "battery"

    def __init__(self, builders: Mapping[str, Builder] | None = None) -> None:
        if builders is None:
            builders = {
                "nubbin": NubbinBattery,
                "spindler": SpindlerBattery,
            }
        super().__init__(builders)

    def create(self, name: str) -> Battery:
        """Build the battery registered under ``name``."""
        battery = super().create(name)
        assert isinstance(battery, Battery)  # noqa: S101 - registry is typed by construction
        return battery


class TireFactory(_Registry):
    """Factory for :class:`Tire` components."""

    kind = "tire"

    def __init__(self, builders: Mapping[str, Builder] | None = None) -> None:
        if builders is None:
            builders = {
                "carrigan": CarriganTire,
                "octoprime": OctoprimeTire,
            }
        super().__init__(builders)

    def create(self, name: str) -> Tire:
        """Build the tyre registered under ``name``."""
        tire = super().create(name)
        assert isinstance(tire, Tire)  # noqa: S101 - registry is typed by construction
        return tire


class CarFactory(_Registry):
    """Factory that assembles complete vehicles.

    The default registry contains the five models of the Lyft rental fleet.
    New models are added with :meth:`register` and immediately become
    available to every caller of :meth:`create`.

    Args:
        builders: Initial mapping of model name to builder.  Defaults to the
            five fleet models.
    """

    kind = "car model"

    def __init__(self, builders: Mapping[str, Builder] | None = None) -> None:
        if builders is None:
            builders = {
                "calliope": Calliope,
                "glissando": Glissando,
                "palindrome": Palindrome,
                "rorschach": Rorschach,
                "thovex": Thovex,
            }
        super().__init__(builders)
        self._aliases: dict[str, str] = {
            normalize_name(alias): normalize_name(target)
            for alias, target in config.MODEL_ALIASES.items()
        }

    def register_alias(self, alias: str, model: str) -> None:
        """Register an alternative name for an existing model.

        Args:
            alias: The alternative name (e.g. ``"glissade"``).
            model: The canonical model name (e.g. ``"glissando"``).

        Raises:
            UnknownComponentError: If ``model`` is not a registered model.
        """
        key = normalize_name(model)
        if key not in self._builders:
            raise UnknownComponentError(f"cannot alias unknown car model '{model}'")
        self._aliases[normalize_name(alias)] = key

    def create(self, name: str) -> Car:
        """Build the vehicle model registered under ``name``.

        Args:
            name: The public name of the model.  Historical spellings such as
                ``"glissade"`` resolve to the canonical model.

        Returns:
            A newly assembled vehicle.

        Raises:
            UnknownComponentError: If ``name`` is not registered.
        """
        key = normalize_name(name)
        key = self._aliases.get(key, key)
        try:
            builder = self._builders[key]
        except KeyError:
            raise UnknownComponentError(
                f"unknown car model '{name}'; available: {', '.join(self.available())}"
            ) from None
        car = builder()
        assert isinstance(car, Car)  # noqa: S101 - registry is typed by construction
        return car

    def create_many(self, names: Iterable[str]) -> tuple[Car, ...]:
        """Build several vehicles in order.

        Args:
            names: The model names to build.

        Returns:
            The built vehicles, in the order requested.

        Raises:
            UnknownComponentError: If any name is not registered.
        """
        return tuple(self.create(name) for name in names)

    @property
    def aliases(self) -> tuple[str, ...]:
        """The alternative names understood by this factory."""
        return tuple(sorted(self._aliases))

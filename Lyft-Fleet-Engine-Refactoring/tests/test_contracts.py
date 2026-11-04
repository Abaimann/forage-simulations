"""Tests for the shared contracts, public API surface and configuration.

These tests close the remaining branches of the domain contracts and guard
the public API of the package against accidental breakage.
"""

from __future__ import annotations

from datetime import date

import pytest

import lyft_fleet
from lyft_fleet import config
from lyft_fleet.domain.criteria import ServiceCriterion
from lyft_fleet.domain.serviceable import Serviceable
from lyft_fleet.domain.value_objects import ServiceContext
from lyft_fleet.errors import (
    FleetError,
    InvalidServiceContextError,
    InvalidSpecificationError,
    UnknownComponentError,
)
from lyft_fleet.infrastructure.factory import BatteryFactory, TireFactory

pytestmark = pytest.mark.unit


class TestServiceableContract:
    """The default implementation of the ``Serviceable`` interface."""

    def test_service_reasons_defaults_to_empty(self) -> None:
        class Bare(Serviceable):
            def needs_service(self, context: ServiceContext) -> bool:
                return False

        context = ServiceContext(
            current_mileage=0,
            last_service_mileage=0,
            current_date=date(2024, 6, 1),
            last_service_date=date(2022, 6, 1),
        )
        assert Bare().service_reasons(context) == ()

    def test_serviceable_cannot_be_instantiated_directly(self) -> None:
        with pytest.raises(TypeError):
            Serviceable()  # type: ignore[abstract]


class TestCriterionFallbacks:
    """The default ``__str__``/``__repr__`` of a hand written criterion."""

    def test_str_and_repr_fall_back_to_the_base_implementation(self) -> None:
        class Custom(ServiceCriterion):
            def is_due(self, context: ServiceContext) -> bool:
                return False

            def describe(self) -> str:
                return "custom rule"

        criterion = Custom()
        assert str(criterion) == "custom rule"
        assert repr(criterion) == "Custom()"


class TestServiceContextValidationBranches:
    """Remaining validation branches of the context."""

    def test_rejects_a_non_integer_last_service_mileage(self) -> None:
        with pytest.raises(InvalidServiceContextError, match="last_service_mileage"):
            ServiceContext(
                current_mileage=100,
                last_service_mileage="0",  # type: ignore[arg-type]
                current_date=date(2024, 6, 1),
                last_service_date=date(2022, 6, 1),
            )

    def test_rejects_a_boolean_last_service_mileage(self) -> None:
        with pytest.raises(InvalidServiceContextError, match="last_service_mileage"):
            ServiceContext(
                current_mileage=100,
                last_service_mileage=True,  # type: ignore[arg-type]
                current_date=date(2024, 6, 1),
                last_service_date=date(2022, 6, 1),
            )


class TestCustomComponentRegistries:
    """Every registry accepts a custom set of builders."""

    def test_a_custom_battery_registry_can_be_built(self) -> None:
        factory = BatteryFactory({"only": lambda: None})
        assert factory.available() == ("only",)

    def test_a_custom_tire_registry_can_be_built(self) -> None:
        factory = TireFactory({"only": lambda: None})
        assert factory.available() == ("only",)


class TestErrorHierarchy:
    """Every error is catchable as a :class:`FleetError`."""

    @pytest.mark.parametrize(
        "error",
        [UnknownComponentError, InvalidServiceContextError, InvalidSpecificationError],
    )
    def test_every_error_is_a_fleet_error(self, error: type[FleetError]) -> None:
        assert issubclass(error, FleetError)

    def test_unknown_component_error_is_a_key_error(self) -> None:
        assert issubclass(UnknownComponentError, KeyError)

    def test_invalid_errors_are_value_errors(self) -> None:
        assert issubclass(InvalidServiceContextError, ValueError)
        assert issubclass(InvalidSpecificationError, ValueError)

    def test_unknown_component_error_renders_cleanly(self) -> None:
        error = UnknownComponentError("unknown engine 'banana'")
        assert str(error) == "unknown engine 'banana'"


class TestPublicApi:
    """The package exposes a stable, documented public surface."""

    def test_exposes_a_version(self) -> None:
        assert lyft_fleet.__version__ == "1.0.0"

    @pytest.mark.parametrize(
        "name",
        [
            "Aggregation",
            "AllCriterion",
            "AnyCriterion",
            "Battery",
            "BatteryFactory",
            "CalendarCriterion",
            "Calliope",
            "CapuletEngine",
            "Car",
            "CarFactory",
            "CarriganTire",
            "Engine",
            "EngineFactory",
            "FleetError",
            "FleetMaintenanceService",
            "Glissando",
            "InvalidServiceContextError",
            "InvalidSpecificationError",
            "MileageCriterion",
            "NubbinBattery",
            "OctoprimeTire",
            "Palindrome",
            "Rorschach",
            "ServiceContext",
            "ServiceCriterion",
            "ServiceReport",
            "Serviceable",
            "SpindlerBattery",
            "SternmanEngine",
            "Thovex",
            "Tire",
            "TireFactory",
            "UnknownComponentError",
            "VehicleInspection",
            "WarningLightCriterion",
            "WearThresholdCriterion",
            "WilloughbyEngine",
        ],
    )
    def test_exposes_the_expected_names(self, name: str) -> None:
        assert hasattr(lyft_fleet, name)
        assert name in lyft_fleet.__all__

    def test_all_names_are_resolvable(self) -> None:
        for name in lyft_fleet.__all__:
            assert getattr(lyft_fleet, name) is not None


class TestConfiguration:
    """The tunable thresholds are centralised in :mod:`lyft_fleet.config`."""

    def test_engine_intervals(self) -> None:
        assert config.CAPULET_SERVICE_INTERVAL_MILES == 30_000
        assert config.WILLOUGHBY_SERVICE_INTERVAL_MILES == 60_000

    def test_battery_lifetimes(self) -> None:
        assert config.NUBBIN_BATTERY_LIFETIME_YEARS == 4
        assert config.SPINDLER_BATTERY_LIFETIME_YEARS == 3

    def test_tyre_thresholds(self) -> None:
        assert config.CARRIGAN_TIRE_WEAR_THRESHOLD == 0.9
        assert config.OCTOPRIME_TIRE_TOTAL_WEAR_THRESHOLD == 3.0

    def test_inspection_intervals(self) -> None:
        assert config.CALLIOPE_INSPECTION_INTERVAL_YEARS == 2
        assert config.GLISSANDO_INSPECTION_INTERVAL_YEARS == 2
        assert config.PALINDROME_INSPECTION_INTERVAL_YEARS == 4
        assert config.RORSCHACH_INSPECTION_INTERVAL_YEARS == 4
        assert config.THOVEX_INSPECTION_INTERVAL_YEARS == 4

    def test_model_aliases_point_at_known_models(self) -> None:
        from lyft_fleet.infrastructure.factory import CarFactory

        factory = CarFactory()
        for alias, target in config.MODEL_ALIASES.items():
            assert target in factory.available()
            assert factory.create(alias).name == factory.create(target).name

"""Unit tests for the application layer (fleet maintenance use cases)."""

from __future__ import annotations

from datetime import date

import pytest

from lyft_fleet.application.fleet_service import (
    FleetMaintenanceService,
    ServiceReport,
    VehicleInspection,
)
from lyft_fleet.domain.car import Calliope, Car
from lyft_fleet.domain.components.battery import SpindlerBattery
from lyft_fleet.domain.components.engine import CapuletEngine
from lyft_fleet.domain.components.tire import CarriganTire
from lyft_fleet.domain.value_objects import ServiceContext
from lyft_fleet.errors import UnknownComponentError
from lyft_fleet.infrastructure.factory import CarFactory

pytestmark = pytest.mark.unit


@pytest.fixture
def service() -> FleetMaintenanceService:
    return FleetMaintenanceService()


class TestInspect:
    """Tests for the single-vehicle inspection use case."""

    def test_reports_a_healthy_vehicle(self, service: FleetMaintenanceService) -> None:
        context = ServiceContext(
            current_mileage=0,
            last_service_mileage=0,
            current_date=date(2024, 6, 1),
            last_service_date=date(2022, 6, 1),
            tire_wear=(0.1, 0.1, 0.1, 0.1),
        )
        report = service.inspect(Calliope(), context)
        assert report.needs_service is False
        assert report.reasons == ()
        assert report.model == "Calliope"

    def test_reports_a_vehicle_that_needs_service(
        self, service: FleetMaintenanceService
    ) -> None:
        context = ServiceContext(
            current_mileage=40_000,
            last_service_mileage=0,
            current_date=date(2024, 6, 1),
            last_service_date=date(2022, 6, 1),
            tire_wear=(0.1, 0.1, 0.1, 0.1),
        )
        report = service.inspect(Calliope(), context)
        assert report.needs_service is True
        assert len(report.reasons) == 1

    def test_a_report_is_truthy_when_service_is_needed(self) -> None:
        assert bool(ServiceReport(model="Calliope", needs_service=True)) is True
        assert bool(ServiceReport(model="Calliope", needs_service=False)) is False

    def test_the_report_renders_readably(self) -> None:
        report = ServiceReport(
            model="Calliope", needs_service=True, reasons=("Engine Capulet: too old",)
        )
        rendered = str(report)
        assert "Calliope" in rendered
        assert "NEEDS SERVICE" in rendered
        assert "Engine Capulet: too old" in rendered

    def test_a_healthy_report_renders_readably(self) -> None:
        rendered = str(ServiceReport(model="Thovex", needs_service=False))
        assert "OK" in rendered


class TestInspectFleet:
    """Tests for the fleet-wide inspection use case."""

    def test_returns_one_report_per_vehicle(self, service: FleetMaintenanceService) -> None:
        context = ServiceContext(
            current_mileage=0,
            last_service_mileage=0,
            current_date=date(2024, 6, 1),
            last_service_date=date(2022, 6, 1),
        )
        inspections = [
            VehicleInspection(vehicle=Calliope(), context=context, vehicle_id="CAR-1"),
            VehicleInspection(vehicle=Calliope(), context=context, vehicle_id="CAR-2"),
        ]
        reports = service.inspect_fleet(inspections)
        assert len(reports) == 2
        assert [report.vehicle_id for report in reports] == ["CAR-1", "CAR-2"]

    def test_an_empty_fleet_produces_no_reports(
        self, service: FleetMaintenanceService
    ) -> None:
        assert service.inspect_fleet([]) == ()

    def test_mixed_fleet_results(
        self, service: FleetMaintenanceService
    ) -> None:
        healthy = ServiceContext(
            current_mileage=0,
            last_service_mileage=0,
            current_date=date(2024, 6, 1),
            last_service_date=date(2022, 6, 1),
        )
        broken = ServiceContext(
            current_mileage=90_000,
            last_service_mileage=0,
            current_date=date(2024, 6, 1),
            last_service_date=date(2022, 6, 1),
        )
        reports = service.inspect_fleet(
            [
                VehicleInspection(vehicle=Calliope(), context=healthy, vehicle_id="OK-1"),
                VehicleInspection(vehicle=Calliope(), context=broken, vehicle_id="BAD-1"),
            ]
        )
        assert [report.needs_service for report in reports] == [False, True]
        assert reports[0].reasons == ()
        assert reports[1].reasons


class TestVehicleInspection:
    """Tests for the inspection DTO."""

    def test_rejects_a_non_car(self) -> None:
        with pytest.raises(TypeError, match="vehicle must be a Car"):
            VehicleInspection(vehicle="not-a-car", context=ServiceContext(  # type: ignore[arg-type]
                current_mileage=0,
                last_service_mileage=0,
                current_date=date(2024, 6, 1),
                last_service_date=date(2022, 6, 1),
            ))

    def test_rejects_a_non_context(self) -> None:
        with pytest.raises(TypeError, match="context must be a ServiceContext"):
            VehicleInspection(vehicle=Calliope(), context={})  # type: ignore[arg-type]

    def test_keeps_the_vehicle_id(self) -> None:
        inspection = VehicleInspection(
            vehicle=Calliope(),
            context=ServiceContext(
                current_mileage=0,
                last_service_mileage=0,
                current_date=date(2024, 6, 1),
                last_service_date=date(2022, 6, 1),
            ),
            vehicle_id="CAR-9",
        )
        assert inspection.vehicle_id == "CAR-9"


class TestBuildInspection:
    """Tests for the convenience entry point that replaces the legacy factory."""

    def test_builds_a_vehicle_from_its_model_name(
        self, service: FleetMaintenanceService
    ) -> None:
        inspection = service.build_inspection(
            "calliope",
            current_mileage=40_000,
            last_service_mileage=0,
            current_date=date(2024, 6, 1),
            last_service_date=date(2022, 6, 1),
        )
        assert isinstance(inspection.vehicle, Car)
        assert inspection.vehicle.needs_service(inspection.context) is True

    def test_accepts_the_historical_model_spelling(
        self, service: FleetMaintenanceService
    ) -> None:
        inspection = service.build_inspection(
            "glissade",
            current_mileage=0,
            last_service_mileage=0,
            current_date=date(2024, 6, 1),
            last_service_date=date(2022, 6, 1),
        )
        assert inspection.vehicle.name == "Glissando"

    def test_raises_for_an_unknown_model(self, service: FleetMaintenanceService) -> None:
        with pytest.raises(UnknownComponentError):
            service.build_inspection(
                "banana",
                current_mileage=0,
                last_service_mileage=0,
                current_date=date(2024, 6, 1),
                last_service_date=date(2022, 6, 1),
            )

    def test_forwards_the_warning_light(self, service: FleetMaintenanceService) -> None:
        inspection = service.build_inspection(
            "palindrome",
            current_mileage=0,
            last_service_mileage=0,
            current_date=date(2024, 6, 1),
            last_service_date=date(2022, 6, 1),
            warning_light_on=True,
        )
        assert inspection.vehicle.needs_service(inspection.context) is True

    def test_forwards_the_tyre_wear(self, service: FleetMaintenanceService) -> None:
        inspection = service.build_inspection(
            "calliope",
            current_mileage=0,
            last_service_mileage=0,
            current_date=date(2024, 6, 1),
            last_service_date=date(2022, 6, 1),
            tire_wear=(0.95, 0.1, 0.1, 0.1),
        )
        assert inspection.vehicle.needs_service(inspection.context) is True

    def test_keeps_the_vehicle_id(self, service: FleetMaintenanceService) -> None:
        inspection = service.build_inspection(
            "thovex",
            current_mileage=0,
            last_service_mileage=0,
            current_date=date(2024, 6, 1),
            last_service_date=date(2022, 6, 1),
            vehicle_id="CAR-42",
        )
        assert inspection.vehicle_id == "CAR-42"


class TestServiceWiring:
    """Tests for the dependency wiring of the application service."""

    def test_uses_a_default_factory(self) -> None:
        assert isinstance(FleetMaintenanceService().car_factory, CarFactory)

    def test_accepts_an_injected_factory(self) -> None:
        factory = CarFactory()
        service = FleetMaintenanceService(factory)
        assert service.car_factory is factory

    def test_an_injected_factory_can_add_models(self) -> None:
        factory = CarFactory()
        factory.register("custom", Calliope)
        service = FleetMaintenanceService(factory)
        inspection = service.build_inspection(
            "custom",
            current_mileage=0,
            last_service_mileage=0,
            current_date=date(2024, 6, 1),
            last_service_date=date(2022, 6, 1),
        )
        assert inspection.vehicle.name == "Calliope"


@pytest.mark.integration
class TestEndToEnd:
    """An integration test spanning the whole stack."""

    def test_a_whole_fleet_can_be_inspected(
        self, service: FleetMaintenanceService
    ) -> None:
        inspections = [
            service.build_inspection(
                model,
                current_mileage=mileage,
                last_service_mileage=0,
                current_date=date(2024, 6, 1),
                last_service_date=date(2022, 6, 1),
                tire_wear=wear,
                warning_light_on=warning,
                vehicle_id=f"CAR-{index}",
            )
            for index, (model, mileage, wear, warning) in enumerate(
                [
                    ("calliope", 40_000, (0.1, 0.1, 0.1, 0.1), False),
                    ("glissando", 0, (0.1, 0.1, 0.1, 0.1), False),
                    ("palindrome", 0, (0.1, 0.1, 0.1, 0.1), True),
                    ("rorschach", 70_000, (0.1, 0.1, 0.1, 0.1), False),
                    ("thovex", 0, (0.9, 0.9, 0.9, 0.9), False),
                ]
            )
        ]
        reports = service.inspect_fleet(inspections)
        assert len(reports) == 5
        assert [report.needs_service for report in reports] == [
            True,
            False,
            True,
            True,
            True,
        ]

    def test_a_hand_built_car_can_be_inspected(
        self, service: FleetMaintenanceService
    ) -> None:
        car = Calliope(
            engine=CapuletEngine(),
            battery=SpindlerBattery(),
            tire=CarriganTire(),
        )
        context = ServiceContext(
            current_mileage=40_000,
            last_service_mileage=0,
            current_date=date(2024, 6, 1),
            last_service_date=date(2022, 6, 1),
            tire_wear=(0.1,),
        )
        report = service.inspect(car, context)
        assert report.model == "Calliope"
        assert report.needs_service is True
        assert any("Capulet" in reason for reason in report.reasons)

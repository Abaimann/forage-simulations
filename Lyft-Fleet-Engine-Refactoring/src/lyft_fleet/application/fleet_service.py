"""Application layer: use cases for the fleet maintenance domain.

This layer orchestrates the domain.  It knows *what* a service report looks
like and *how* to evaluate a fleet, but it contains no servicing rules of its
own - those live in the domain layer.
"""

from __future__ import annotations

from collections.abc import Iterable, Sequence
from dataclasses import dataclass
from datetime import date

from lyft_fleet.domain.car import Car
from lyft_fleet.domain.serviceable import Serviceable
from lyft_fleet.domain.value_objects import ServiceContext
from lyft_fleet.infrastructure.factory import CarFactory

__all__ = [
    "FleetMaintenanceService",
    "ServiceReport",
    "VehicleInspection",
]


@dataclass(frozen=True)
class ServiceReport:
    """The outcome of inspecting one vehicle.

    Attributes:
        model: The vehicle model name.
        vehicle_id: Optional identifier of the inspected vehicle.
        needs_service: Whether the vehicle requires a service.
        reasons: Human readable explanations for every tripped rule.
    """

    model: str
    needs_service: bool
    reasons: tuple[str, ...] = ()
    vehicle_id: str | None = None

    def __bool__(self) -> bool:
        """Return ``True`` when the vehicle needs service."""
        return self.needs_service

    def __str__(self) -> str:
        status = "NEEDS SERVICE" if self.needs_service else "OK"
        identifier = f" [{self.vehicle_id}]" if self.vehicle_id else ""
        lines = [f"{self.model}{identifier}: {status}"]
        lines.extend(f"  - {reason}" for reason in self.reasons)
        return "\n".join(lines)


@dataclass(frozen=True)
class VehicleInspection:
    """A vehicle plus the readings taken from it.

    Attributes:
        vehicle: The vehicle to inspect.
        context: The readings captured during the inspection.
        vehicle_id: Optional identifier used in reports.
    """

    vehicle: Car
    context: ServiceContext
    vehicle_id: str | None = None

    def __post_init__(self) -> None:
        if not isinstance(self.vehicle, Car):
            raise TypeError(f"vehicle must be a Car, got {type(self.vehicle).__name__}")
        if not isinstance(self.context, ServiceContext):
            raise TypeError(
                f"context must be a ServiceContext, got {type(self.context).__name__}"
            )


class FleetMaintenanceService:
    """Use case: inspect vehicles and report what is due for service.

    The service depends on the :class:`~lyft_fleet.domain.car.Car` domain
    model and on a :class:`~lyft_fleet.infrastructure.factory.CarFactory`;
    it never reaches into the internals of a component.

    Args:
        car_factory: Factory used to build vehicles by model name.
    """

    def __init__(self, car_factory: CarFactory | None = None) -> None:
        self._car_factory = car_factory if car_factory is not None else CarFactory()

    @property
    def car_factory(self) -> CarFactory:
        """The factory used to build vehicles."""
        return self._car_factory

    def inspect(self, vehicle: Serviceable, context: ServiceContext) -> ServiceReport:
        """Inspect a single serviceable component.

        Args:
            vehicle: The component to inspect.
            context: The readings captured during the inspection.

        Returns:
            The resulting :class:`ServiceReport`.
        """
        needs_service = vehicle.needs_service(context)
        reasons = vehicle.service_reasons(context) if needs_service else ()
        model = getattr(vehicle, "name", type(vehicle).__name__)
        return ServiceReport(model=model, needs_service=needs_service, reasons=tuple(reasons))

    def inspect_fleet(
        self, inspections: Iterable[VehicleInspection]
    ) -> tuple[ServiceReport, ...]:
        """Inspect a fleet of vehicles.

        Args:
            inspections: The vehicles and their readings.

        Returns:
            One report per vehicle, in the order supplied.
        """
        return tuple(
            ServiceReport(
                model=inspection.vehicle.name,
                needs_service=inspection.vehicle.needs_service(inspection.context),
                reasons=inspection.vehicle.service_reasons(inspection.context)
                if inspection.vehicle.needs_service(inspection.context)
                else (),
                vehicle_id=inspection.vehicle_id,
            )
            for inspection in inspections
        )

    def build_inspection(
        self,
        model: str,
        *,
        current_mileage: int,
        last_service_mileage: int,
        current_date: date,
        last_service_date: date,
        tire_wear: Sequence[float] = (),
        warning_light_on: bool = False,
        vehicle_id: str | None = None,
    ) -> VehicleInspection:
        """Build a vehicle from its model name and the readings taken from it.

        This is the convenience entry point that replaces the five duplicated
        ``create_<model>`` methods of the legacy factory.

        Args:
            model: The model name.
            current_mileage: Odometer reading now.
            last_service_mileage: Odometer reading at the previous service.
            current_date: Date of the inspection.
            last_service_date: Date of the previous service.
            tire_wear: Per-wheel wear ratios.
            warning_light_on: State of the engine warning light.
            vehicle_id: Optional identifier used in reports.

        Returns:
            The ready-to-inspect vehicle.
        """
        vehicle = self._car_factory.create(model)
        context = ServiceContext(
            current_mileage=current_mileage,
            last_service_mileage=last_service_mileage,
            current_date=current_date,
            last_service_date=last_service_date,
            tire_wear=tuple(tire_wear),
            warning_light_on=warning_light_on,
        )
        return VehicleInspection(vehicle=vehicle, context=context, vehicle_id=vehicle_id)

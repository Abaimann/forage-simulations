"""Lyft fleet maintenance domain.

A clean-architecture refactoring of the Lyft rental-car fleet maintenance
service, built around the Strategy and Factory patterns.

Layers
------
``lyft_fleet.domain``
    Pure business rules: entities, value objects and the service criteria
    (strategies).  No dependency on any other layer.
``lyft_fleet.application``
    Use cases that orchestrate the domain and shape the results.
``lyft_fleet.infrastructure``
    Factories and adapters that build the domain objects.

Quick start
-----------
>>> from datetime import date
>>> from lyft_fleet import FleetMaintenanceService
>>> service = FleetMaintenanceService()
>>> inspection = service.build_inspection(
...     "calliope",
...     current_mileage=40_000,
...     last_service_mileage=0,
...     current_date=date(2024, 6, 1),
...     last_service_date=date(2022, 6, 1),
... )
>>> inspection.vehicle.needs_service(inspection.context)
True
"""

from __future__ import annotations

from lyft_fleet.application.fleet_service import (
    FleetMaintenanceService,
    ServiceReport,
    VehicleInspection,
)
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
from lyft_fleet.domain.criteria import (
    Aggregation,
    AllCriterion,
    AnyCriterion,
    CalendarCriterion,
    MileageCriterion,
    ServiceCriterion,
    WarningLightCriterion,
    WearThresholdCriterion,
)
from lyft_fleet.domain.serviceable import Serviceable
from lyft_fleet.domain.value_objects import ServiceContext
from lyft_fleet.errors import (
    FleetError,
    InvalidServiceContextError,
    InvalidSpecificationError,
    UnknownComponentError,
)
from lyft_fleet.infrastructure.factory import (
    BatteryFactory,
    CarFactory,
    EngineFactory,
    TireFactory,
)

__version__ = "1.0.0"

__all__ = [
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
    "__version__",
]

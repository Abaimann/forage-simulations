"""Verify every code example in README.md actually runs.

Each snippet is extracted and executed, so the documentation cannot drift
away from the implementation.
"""

import sys
from datetime import date
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "src"))

import lyft_fleet as _pkg  # noqa: E402 - needs the src path set up first

# --- README section 6.1: CarFactory ----------------------------------------- #
from lyft_fleet import CarFactory, FleetMaintenanceService  # noqa: E402
from lyft_fleet.domain.car import _ModelCar  # noqa: E402
from lyft_fleet.domain.components.battery import NubbinBattery  # noqa: E402
from lyft_fleet.domain.components.engine import CapuletEngine, Engine  # noqa: E402
from lyft_fleet.domain.components.tire import CarriganTire, Tire  # noqa: E402
from lyft_fleet.domain.criteria import (  # noqa: E402
    Aggregation,
    MileageCriterion,
    ServiceCriterion,
    WearThresholdCriterion,
)

factory = CarFactory()
assert factory.create("calliope").name == "Calliope"
assert factory.create("CALLIOPE").name == "Calliope"
assert factory.create("call-iope").name == "Calliope"
assert factory.create("glissade").name == "Glissando"
cars = factory.create_many(["calliope", "thovex"])
assert [c.name for c in cars] == ["Calliope", "Thovex"]

# --- README section 6.2 -------------------------------------------------- #
from lyft_fleet.infrastructure.factory import (  # noqa: E402
    BatteryFactory,
    EngineFactory,
    TireFactory,
)

assert isinstance(EngineFactory().create("capulet"), CapuletEngine)
assert isinstance(BatteryFactory().create("nubbin"), NubbinBattery)
assert isinstance(TireFactory().create("octoprime"), Tire)

# --- README section 6.3 -------------------------------------------------- #
factory2 = CarFactory()


class Limo(_ModelCar):
    INSPECTION_INTERVAL_YEARS = 0

    def __init__(self):
        super().__init__(
            CapuletEngine(),
            NubbinBattery(),
            CarriganTire(),
            inspection_criteria=self._default_inspection_criteria(),
            name="Limo",
        )


factory2.register("limo", Limo)
factory2.register_alias("gliss", "glissando")
assert factory2.create("limo").name == "Limo"
assert factory2.create("gliss").name == "Glissando"

# --- README section 6.4 -------------------------------------------------- #
service = FleetMaintenanceService()

inspection = service.build_inspection(
    "calliope",
    current_mileage=40_000,
    last_service_mileage=0,
    current_date=date(2024, 6, 1),
    last_service_date=date(2022, 6, 1),
    tire_wear=(0.1, 0.2, 0.3, 0.4),
    warning_light_on=False,
    vehicle_id="LYFT-1001",
)

report = service.inspect(inspection.vehicle, inspection.context)
assert report.needs_service is True
assert report.reasons == ("Engine Capulet: more than 30000 miles driven since last service",)

# --- README section 9: library usage ------------------------------------- #
service = FleetMaintenanceService(CarFactory())
inspection = service.build_inspection(
    "rorschach",
    current_mileage=95_000,
    last_service_mileage=0,
    current_date=date(2024, 6, 1),
    last_service_date=date(2022, 6, 1),
    tire_wear=(0.8, 0.8, 0.8, 0.8),
    vehicle_id="LYFT-1004",
)
for rep in service.inspect_fleet([inspection]):
    assert rep.needs_service is True
    assert len(rep.reasons) == 2

# --- README section 11.1: new criterion ---------------------------------- #


class FrequentServiceCriterion(ServiceCriterion):
    """Service when the vehicle has been driven at all since a long inspection."""

    def is_due(self, context) -> bool:
        return context.days_since_service > 730 and context.miles_since_service > 0

    def describe(self) -> str:
        return "driven since the last long inspection"


engine = Engine((FrequentServiceCriterion(), MileageCriterion(30_000)), name="Capulet")
assert engine.name == "Capulet"

# --- README section 11.2: new component ---------------------------------- #


class HybridEngine(Engine):
    def __init__(self, interval_miles: int = 40_000) -> None:
        super().__init__((MileageCriterion(interval_miles),), name="Hybrid")


assert HybridEngine().name == "Hybrid"

# --- README section 11.4: new tyre --------------------------------------- #


class EnduranceTire(Tire):
    def __init__(self, threshold: float = 0.95) -> None:
        super().__init__(
            (WearThresholdCriterion(threshold, Aggregation.MAX),), name="Endurance"
        )


assert EnduranceTire().name == "Endurance"

# --- README public API import block -------------------------------------- #
# The README shows a flat `from lyft_fleet import (...)` block; verify every
# name in it resolves, without shadowing the imports above.
README_PUBLIC_API = (
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
)
for _name in README_PUBLIC_API:
    assert hasattr(_pkg, _name), f"README public API name missing: {_name}"
    assert _name in _pkg.__all__, f"README public API name not exported: {_name}"

print("ALL README EXAMPLES VERIFIED")

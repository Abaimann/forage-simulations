import sys
from datetime import date

sys.path.insert(0, "src")

import lyft_fleet
from lyft_fleet import CarFactory, FleetMaintenanceService, ServiceContext

print("version:", lyft_fleet.__version__)

factory = CarFactory()
print("models:", factory.available())

ctx = ServiceContext(
    current_mileage=40_000,
    last_service_mileage=0,
    current_date=date(2024, 6, 1),
    last_service_date=date(2022, 6, 1),
    tire_wear=(0.1, 0.2, 0.3, 0.4),
)

for model in factory.available():
    car = factory.create(model)
    print(model, "->", car.needs_service(ctx), car.service_reasons(ctx))

service = FleetMaintenanceService()
insp = service.build_inspection(
    "calliope",
    current_mileage=40_000,
    last_service_mileage=0,
    current_date=date(2024, 6, 1),
    last_service_date=date(2022, 6, 1),
)
print(insp.vehicle.needs_service(insp.context))
print("SMOKE OK")

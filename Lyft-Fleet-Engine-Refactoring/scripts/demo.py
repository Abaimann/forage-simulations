"""Runnable demonstration of the Lyft fleet maintenance domain.

Usage
-----
    python scripts/demo.py

The script builds a small fleet, inspects every vehicle and prints a service
report.  It is intentionally dependency-free so it can be run straight from a
checkout without installing the package.
"""

from __future__ import annotations

import sys
from datetime import date
from pathlib import Path

SRC = Path(__file__).resolve().parent.parent / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from lyft_fleet import CarFactory, FleetMaintenanceService  # noqa: E402
from lyft_fleet.domain.value_objects import ServiceContext  # noqa: E402

#: The fleet under inspection: (vehicle id, model, mileage, tyre wear, warning light).
FLEET: tuple[tuple[str, str, int, tuple[float, ...], bool], ...] = (
    ("LYFT-1001", "calliope", 40_000, (0.10, 0.15, 0.20, 0.25), False),
    ("LYFT-1002", "glissando", 12_000, (0.30, 0.35, 0.40, 0.45), False),
    ("LYFT-1003", "palindrome", 0, (0.05, 0.05, 0.05, 0.05), True),
    ("LYFT-1004", "rorschach", 95_000, (0.80, 0.80, 0.80, 0.80), False),
    ("LYFT-1005", "thovex", 5_000, (0.95, 0.20, 0.25, 0.30), False),
)

CURRENT_DATE = date(2024, 6, 1)
LAST_SERVICE_DATE = date(2022, 6, 1)


def main() -> int:
    """Build the fleet, inspect it and print the report."""
    service = FleetMaintenanceService(CarFactory())

    inspections = [
        service.build_inspection(
            model,
            current_mileage=mileage,
            last_service_mileage=0,
            current_date=CURRENT_DATE,
            last_service_date=LAST_SERVICE_DATE,
            tire_wear=wear,
            warning_light_on=warning,
            vehicle_id=vehicle_id,
        )
        for vehicle_id, model, mileage, wear, warning in FLEET
    ]

    reports = service.inspect_fleet(inspections)

    print("=" * 72)
    print("LYFT FLEET MAINTENANCE REPORT")
    print(f"Inspection date : {CURRENT_DATE.isoformat()}")
    print(f"Last service    : {LAST_SERVICE_DATE.isoformat()}")
    print("=" * 72)

    for report in reports:
        print(report)
        print("-" * 72)

    due = [report for report in reports if report.needs_service]
    print(f"{len(due)} of {len(reports)} vehicles require a service.")
    print("=" * 72)

    # The domain is fully decoupled: components can be inspected on their own.
    from lyft_fleet.domain.components.engine import CapuletEngine

    engine = CapuletEngine()
    context = ServiceContext(
        current_mileage=40_000,
        last_service_mileage=0,
        current_date=CURRENT_DATE,
        last_service_date=LAST_SERVICE_DATE,
    )
    print(f"Standalone Capulet engine needs service: {engine.needs_service(context)}")
    for reason in engine.service_reasons(context):
        print(f"  - {reason}")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())

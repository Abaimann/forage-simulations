"""Shared pytest fixtures for the fleet maintenance test suite."""

from __future__ import annotations

from datetime import date

import pytest

from lyft_fleet.domain.value_objects import ServiceContext

#: A "healthy" reference date pair used across the suite.
LAST_SERVICE_DATE = date(2022, 6, 1)
CURRENT_DATE = date(2024, 6, 1)


@pytest.fixture
def base_context() -> ServiceContext:
    """Return a context where nothing is due for service.

    0 miles driven since the last service, 2 years elapsed, fresh tyres and
    no warning light.
    """
    return ServiceContext(
        current_mileage=0,
        last_service_mileage=0,
        current_date=CURRENT_DATE,
        last_service_date=LAST_SERVICE_DATE,
        tire_wear=(0.1, 0.1, 0.1, 0.1),
        warning_light_on=False,
    )


@pytest.fixture
def context_factory():
    """Return a helper that builds a context with sensible defaults.

    Any keyword argument may be overridden; unspecified readings are neutral
    (no mileage, no time elapsed, no wear, no warning light).
    """

    def _make(**overrides: object) -> ServiceContext:
        params: dict[str, object] = {
            "current_mileage": 0,
            "last_service_mileage": 0,
            "current_date": CURRENT_DATE,
            "last_service_date": LAST_SERVICE_DATE,
            "tire_wear": (0.1, 0.1, 0.1, 0.1),
            "warning_light_on": False,
        }
        params.update(overrides)
        return ServiceContext(**params)  # type: ignore[arg-type]

    return _make

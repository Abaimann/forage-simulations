"""Unit tests for the domain value objects (:mod:`lyft_fleet.domain.value_objects`)."""

from __future__ import annotations

from dataclasses import FrozenInstanceError
from datetime import date

import pytest

from lyft_fleet.domain.value_objects import ServiceContext, add_years
from lyft_fleet.errors import InvalidServiceContextError

pytestmark = pytest.mark.unit


# --------------------------------------------------------------------------- #
# add_years
# --------------------------------------------------------------------------- #
class TestAddYears:
    """Tests for the leap-safe calendar helper."""

    @pytest.mark.parametrize(
        ("base", "years", "expected"),
        [
            (date(2020, 1, 1), 1, date(2021, 1, 1)),
            (date(2020, 6, 1), 4, date(2024, 6, 1)),
            (date(2020, 6, 1), 0, date(2020, 6, 1)),
            (date(2020, 12, 31), 1, date(2021, 12, 31)),
            (date(2019, 2, 28), 1, date(2020, 2, 28)),
            # 29 February in a non-leap target year is clamped to the 28th.
            (date(2020, 2, 29), 1, date(2021, 2, 28)),
            (date(2020, 2, 29), 4, date(2024, 2, 29)),
        ],
    )
    def test_adds_years(self, base: date, years: int, expected: date) -> None:
        assert add_years(base, years) == expected

    def test_rejects_negative_years(self) -> None:
        with pytest.raises(ValueError, match="non-negative"):
            add_years(date(2020, 1, 1), -1)


# --------------------------------------------------------------------------- #
# ServiceContext
# --------------------------------------------------------------------------- #
class TestServiceContextConstruction:
    """Tests for validation performed when a context is created."""

    def test_accepts_valid_readings(self) -> None:
        context = ServiceContext(
            current_mileage=100,
            last_service_mileage=40,
            current_date=date(2024, 6, 1),
            last_service_date=date(2023, 6, 1),
            tire_wear=(0.0, 0.5, 1.0),
            warning_light_on=True,
        )
        assert context.current_mileage == 100
        assert context.warning_light_on is True

    def test_normalises_tire_wear_to_a_tuple(self) -> None:
        context = ServiceContext(
            current_mileage=0,
            last_service_mileage=0,
            current_date=date(2024, 6, 1),
            last_service_date=date(2023, 6, 1),
            tire_wear=[0.2, 0.3],  # type: ignore[arg-type]
        )
        assert context.tire_wear == (0.2, 0.3)
        assert isinstance(context.tire_wear, tuple)

    def test_rejects_negative_current_mileage(self) -> None:
        with pytest.raises(InvalidServiceContextError, match="current_mileage"):
            ServiceContext(
                current_mileage=-1,
                last_service_mileage=0,
                current_date=date(2024, 6, 1),
                last_service_date=date(2023, 6, 1),
            )

    def test_rejects_negative_last_service_mileage(self) -> None:
        with pytest.raises(InvalidServiceContextError, match="last_service_mileage"):
            ServiceContext(
                current_mileage=100,
                last_service_mileage=-5,
                current_date=date(2024, 6, 1),
                last_service_date=date(2023, 6, 1),
            )

    def test_rejects_last_service_mileage_above_current(self) -> None:
        with pytest.raises(InvalidServiceContextError, match="cannot be greater"):
            ServiceContext(
                current_mileage=100,
                last_service_mileage=200,
                current_date=date(2024, 6, 1),
                last_service_date=date(2023, 6, 1),
            )

    def test_rejects_current_date_before_last_service_date(self) -> None:
        with pytest.raises(InvalidServiceContextError, match="earlier than"):
            ServiceContext(
                current_mileage=100,
                last_service_mileage=0,
                current_date=date(2022, 6, 1),
                last_service_date=date(2023, 6, 1),
            )

    @pytest.mark.parametrize("wear", [-0.1, 1.1, 2.0])
    def test_rejects_out_of_range_tire_wear(self, wear: float) -> None:
        with pytest.raises(InvalidServiceContextError, match="between 0.0 and 1.0"):
            ServiceContext(
                current_mileage=0,
                last_service_mileage=0,
                current_date=date(2024, 6, 1),
                last_service_date=date(2023, 6, 1),
                tire_wear=(0.5, wear),
            )

    def test_rejects_non_numeric_tire_wear(self) -> None:
        with pytest.raises(InvalidServiceContextError, match="must be a number"):
            ServiceContext(
                current_mileage=0,
                last_service_mileage=0,
                current_date=date(2024, 6, 1),
                last_service_date=date(2023, 6, 1),
                tire_wear=("high",),  # type: ignore[arg-type]
            )

    def test_rejects_non_integer_mileage(self) -> None:
        with pytest.raises(InvalidServiceContextError, match="must be an int"):
            ServiceContext(
                current_mileage=1.5,  # type: ignore[arg-type]
                last_service_mileage=0,
                current_date=date(2024, 6, 1),
                last_service_date=date(2023, 6, 1),
            )

    def test_rejects_boolean_mileage(self) -> None:
        # bool is a subclass of int; accepting it would silently mis-read data.
        with pytest.raises(InvalidServiceContextError, match="must be an int"):
            ServiceContext(
                current_mileage=True,  # type: ignore[arg-type]
                last_service_mileage=0,
                current_date=date(2024, 6, 1),
                last_service_date=date(2023, 6, 1),
            )


class TestServiceContextDerivedValues:
    """Tests for the computed properties of a context."""

    def test_miles_since_service(self, context_factory) -> None:
        context = context_factory(current_mileage=50_000, last_service_mileage=12_345)
        assert context.miles_since_service == 37_655

    def test_miles_since_service_is_zero_at_last_service(self, context_factory) -> None:
        context = context_factory(current_mileage=100, last_service_mileage=100)
        assert context.miles_since_service == 0

    def test_days_since_service(self, context_factory) -> None:
        context = context_factory(
            current_date=date(2024, 6, 1), last_service_date=date(2023, 6, 2)
        )
        assert context.days_since_service == 365

    def test_days_since_service_is_zero_on_the_service_day(self, context_factory) -> None:
        context = context_factory(
            current_date=date(2024, 6, 1), last_service_date=date(2024, 6, 1)
        )
        assert context.days_since_service == 0

    def test_max_tire_wear(self, context_factory) -> None:
        context = context_factory(tire_wear=(0.1, 0.95, 0.3, 0.2))
        assert context.max_tire_wear == 0.95

    def test_total_tire_wear(self, context_factory) -> None:
        context = context_factory(tire_wear=(0.1, 0.95, 0.3, 0.2))
        assert context.total_tire_wear == pytest.approx(1.55)

    def test_wear_aggregates_default_to_zero_without_sensor_data(
        self, context_factory
    ) -> None:
        context = context_factory(tire_wear=())
        assert context.max_tire_wear == 0.0
        assert context.total_tire_wear == 0.0


class TestServiceContextBehaviour:
    """Tests for immutability, equality and the alternate constructor."""

    def test_is_immutable(self, base_context: ServiceContext) -> None:
        with pytest.raises(FrozenInstanceError):
            base_context.current_mileage = 5  # type: ignore[misc]

    def test_equality_is_by_value(self, context_factory) -> None:
        assert context_factory() == context_factory()

    def test_build_helper_matches_the_constructor(self, context_factory) -> None:
        built = ServiceContext.build(
            current_mileage=10,
            last_service_mileage=0,
            current_date=date(2024, 6, 1),
            last_service_date=date(2023, 6, 1),
            tire_wear=[0.5, 0.5],
        )
        assert built == context_factory(
            current_mileage=10,
            last_service_mileage=0,
            current_date=date(2024, 6, 1),
            last_service_date=date(2023, 6, 1),
            tire_wear=(0.5, 0.5),
        )

    def test_str_is_informative(self, base_context: ServiceContext) -> None:
        rendered = str(base_context)
        assert "ServiceContext" in rendered
        assert "tire_wear" in rendered

"""Unit tests for battery components."""

from __future__ import annotations

from datetime import date

import pytest

from lyft_fleet.domain.components.battery import Battery, NubbinBattery, SpindlerBattery
from lyft_fleet.domain.criteria import CalendarCriterion
from lyft_fleet.domain.serviceable import Serviceable
from lyft_fleet.errors import InvalidSpecificationError

pytestmark = pytest.mark.unit


class TestNubbinBattery:
    """Nubbin: four year calendar lifetime."""

    def test_is_a_serviceable_battery(self) -> None:
        assert isinstance(NubbinBattery(), Battery)
        assert isinstance(NubbinBattery(), Serviceable)

    def test_does_not_need_service_before_the_lifetime(self, context_factory) -> None:
        battery = NubbinBattery()
        context = context_factory(
            current_date=date(2025, 5, 31), last_service_date=date(2021, 6, 1)
        )
        assert battery.needs_service(context) is False

    def test_does_not_need_service_exactly_on_the_expiry_date(self, context_factory) -> None:
        battery = NubbinBattery()
        context = context_factory(
            current_date=date(2025, 6, 1), last_service_date=date(2021, 6, 1)
        )
        assert battery.needs_service(context) is False

    def test_needs_service_one_day_after_the_expiry_date(self, context_factory) -> None:
        battery = NubbinBattery()
        context = context_factory(
            current_date=date(2025, 6, 2), last_service_date=date(2021, 6, 1)
        )
        assert battery.needs_service(context) is True

    def test_needs_service_long_after_the_expiry_date(self, context_factory) -> None:
        battery = NubbinBattery()
        context = context_factory(
            current_date=date(2030, 1, 1), last_service_date=date(2021, 6, 1)
        )
        assert battery.needs_service(context) is True

    def test_is_unaffected_by_mileage(self, context_factory) -> None:
        battery = NubbinBattery()
        assert battery.needs_service(context_factory(current_mileage=5_000_000)) is False

    def test_the_lifetime_is_configurable(self, context_factory) -> None:
        battery = NubbinBattery(lifetime_years=1)
        context = context_factory(
            current_date=date(2024, 6, 2), last_service_date=date(2023, 6, 1)
        )
        assert battery.needs_service(context) is True

    def test_reports_the_reason(self, context_factory) -> None:
        battery = NubbinBattery()
        context = context_factory(
            current_date=date(2026, 6, 1), last_service_date=date(2020, 6, 1)
        )
        reasons = battery.service_reasons(context)
        assert len(reasons) == 1
        assert "Nubbin" in reasons[0]
        assert "4 year" in reasons[0]

    def test_reports_no_reason_when_not_due(self, context_factory) -> None:
        assert NubbinBattery().service_reasons(context_factory()) == ()


class TestSpindlerBattery:
    """Spindler: three year calendar lifetime."""

    def test_does_not_need_service_exactly_on_the_expiry_date(self, context_factory) -> None:
        battery = SpindlerBattery()
        context = context_factory(
            current_date=date(2025, 6, 1), last_service_date=date(2022, 6, 1)
        )
        assert battery.needs_service(context) is False

    def test_needs_service_one_day_after_the_expiry_date(self, context_factory) -> None:
        battery = SpindlerBattery()
        context = context_factory(
            current_date=date(2025, 6, 2), last_service_date=date(2022, 6, 1)
        )
        assert battery.needs_service(context) is True

    def test_the_lifetime_is_configurable(self, context_factory) -> None:
        battery = SpindlerBattery(lifetime_years=20)
        context = context_factory(
            current_date=date(2035, 6, 1), last_service_date=date(2022, 6, 1)
        )
        # 13 years elapsed is below the extended 20 year lifetime.
        assert battery.needs_service(context) is False

    def test_reports_the_reason(self, context_factory) -> None:
        battery = SpindlerBattery()
        context = context_factory(
            current_date=date(2026, 6, 1), last_service_date=date(2020, 6, 1)
        )
        reasons = battery.service_reasons(context)
        assert "Spindler" in reasons[0]
        assert "3 year" in reasons[0]


class TestBatteryBase:
    """Behaviour shared by every battery."""

    def test_rejects_an_empty_criterion_set(self) -> None:
        with pytest.raises(InvalidSpecificationError, match="at least one criterion"):
            Battery(())

    def test_rejects_a_non_criterion(self) -> None:
        with pytest.raises(InvalidSpecificationError, match="expected ServiceCriterion"):
            Battery(("nope",))  # type: ignore[arg-type]

    def test_exposes_its_criteria(self) -> None:
        battery = NubbinBattery()
        assert len(battery.criteria) == 1
        assert isinstance(battery.criteria[0], CalendarCriterion)

    def test_exposes_its_name_and_component_type(self) -> None:
        battery = SpindlerBattery()
        assert battery.name == "Spindler"
        assert battery.component_type == "battery"

    def test_repr_is_stable(self) -> None:
        assert repr(NubbinBattery()) == "NubbinBattery(name='Nubbin')"

    def test_a_custom_battery_can_be_built_from_any_criteria(self, context_factory) -> None:
        battery = Battery((CalendarCriterion(1),), name="Custom")
        context = context_factory(
            current_date=date(2024, 6, 2), last_service_date=date(2023, 6, 1)
        )
        assert battery.needs_service(context) is True
        assert battery.name == "Custom"

    def test_battery_is_immutable_in_practice(self) -> None:
        battery = NubbinBattery()
        with pytest.raises(AttributeError):
            battery.name = "Other"  # type: ignore[misc]

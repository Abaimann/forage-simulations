"""Unit tests for engine components."""

from __future__ import annotations

from datetime import date

import pytest

from lyft_fleet.domain.components.engine import (
    CapuletEngine,
    Engine,
    SternmanEngine,
    WilloughbyEngine,
)
from lyft_fleet.domain.criteria import MileageCriterion, WarningLightCriterion
from lyft_fleet.domain.serviceable import Serviceable
from lyft_fleet.errors import InvalidSpecificationError

pytestmark = pytest.mark.unit


class TestCapuletEngine:
    """Capulet: serviced after more than 30 000 miles."""

    def test_is_a_serviceable_engine(self) -> None:
        assert isinstance(CapuletEngine(), Engine)
        assert isinstance(CapuletEngine(), Serviceable)

    def test_does_not_need_service_below_the_interval(self, context_factory) -> None:
        engine = CapuletEngine()
        assert engine.needs_service(context_factory(current_mileage=29_999)) is False

    def test_does_not_need_service_exactly_at_the_interval(self, context_factory) -> None:
        engine = CapuletEngine()
        assert engine.needs_service(context_factory(current_mileage=30_000)) is False

    def test_needs_service_above_the_interval(self, context_factory) -> None:
        engine = CapuletEngine()
        assert engine.needs_service(context_factory(current_mileage=30_001)) is True

    def test_uses_the_distance_since_the_last_service(self, context_factory) -> None:
        engine = CapuletEngine()
        context = context_factory(current_mileage=100_000, last_service_mileage=70_000)
        assert engine.needs_service(context) is False
        context = context_factory(current_mileage=100_000, last_service_mileage=69_999)
        assert engine.needs_service(context) is True

    def test_the_interval_is_configurable(self, context_factory) -> None:
        engine = CapuletEngine(interval_miles=100)
        assert engine.needs_service(context_factory(current_mileage=101)) is True
        assert engine.needs_service(context_factory(current_mileage=100)) is False

    def test_reports_the_reason(self, context_factory) -> None:
        engine = CapuletEngine()
        reasons = engine.service_reasons(context_factory(current_mileage=40_000))
        assert len(reasons) == 1
        assert "Capulet" in reasons[0]
        assert "30000" in reasons[0]

    def test_reports_no_reason_when_not_due(self, context_factory) -> None:
        assert CapuletEngine().service_reasons(context_factory()) == ()


class TestWilloughbyEngine:
    """Willoughby: serviced after more than 60 000 miles."""

    def test_does_not_need_service_exactly_at_the_interval(self, context_factory) -> None:
        engine = WilloughbyEngine()
        assert engine.needs_service(context_factory(current_mileage=60_000)) is False

    def test_needs_service_above_the_interval(self, context_factory) -> None:
        engine = WilloughbyEngine()
        assert engine.needs_service(context_factory(current_mileage=60_001)) is True

    def test_uses_the_distance_since_the_last_service(self, context_factory) -> None:
        engine = WilloughbyEngine()
        context = context_factory(current_mileage=200_000, last_service_mileage=140_001)
        assert engine.needs_service(context) is False

    def test_the_interval_is_configurable(self, context_factory) -> None:
        engine = WilloughbyEngine(interval_miles=1_000)
        assert engine.needs_service(context_factory(current_mileage=1_001)) is True

    def test_reports_the_reason(self, context_factory) -> None:
        reasons = WilloughbyEngine().service_reasons(context_factory(current_mileage=90_000))
        assert "Willoughby" in reasons[0]


class TestSternmanEngine:
    """Sternman: serviced when the engine warning light is on."""

    def test_does_not_need_service_when_the_light_is_off(self, context_factory) -> None:
        engine = SternmanEngine()
        assert engine.needs_service(context_factory(warning_light_on=False)) is False

    def test_needs_service_when_the_light_is_on(self, context_factory) -> None:
        engine = SternmanEngine()
        assert engine.needs_service(context_factory(warning_light_on=True)) is True

    def test_is_unaffected_by_mileage(self, context_factory) -> None:
        engine = SternmanEngine()
        assert engine.needs_service(context_factory(current_mileage=999_999)) is False

    def test_reports_the_reason(self, context_factory) -> None:
        reasons = SternmanEngine().service_reasons(context_factory(warning_light_on=True))
        assert "Sternman" in reasons[0]
        assert "warning light" in reasons[0]

    def test_criteria_can_be_overridden(self, context_factory) -> None:
        engine = SternmanEngine(criteria=(MileageCriterion(100),))
        assert engine.needs_service(context_factory(current_mileage=101)) is True
        assert engine.needs_service(context_factory(warning_light_on=True)) is False

    def test_overridden_criteria_must_be_non_empty(self) -> None:
        with pytest.raises(InvalidSpecificationError, match="at least one criterion"):
            SternmanEngine(criteria=())


class TestEngineBase:
    """Behaviour shared by every engine."""

    def test_rejects_an_empty_criterion_set(self) -> None:
        with pytest.raises(InvalidSpecificationError, match="at least one criterion"):
            Engine(())

    def test_rejects_a_non_criterion(self) -> None:
        with pytest.raises(InvalidSpecificationError, match="expected ServiceCriterion"):
            Engine((object(),))  # type: ignore[arg-type]

    def test_exposes_its_criteria(self) -> None:
        engine = CapuletEngine()
        assert len(engine.criteria) == 1
        assert isinstance(engine.criteria[0], MileageCriterion)

    def test_exposes_its_name_and_component_type(self) -> None:
        engine = CapuletEngine()
        assert engine.name == "Capulet"
        assert engine.component_type == "engine"

    def test_repr_is_stable(self) -> None:
        assert repr(CapuletEngine()) == "CapuletEngine(name='Capulet')"

    def test_a_custom_engine_can_be_built_from_any_criteria(self, context_factory) -> None:
        engine = Engine((WarningLightCriterion(), MileageCriterion(10)), name="Custom")
        assert engine.name == "Custom"
        assert engine.needs_service(context_factory(current_mileage=11)) is True

    def test_engine_is_immutable_in_practice(self) -> None:
        engine = CapuletEngine()
        with pytest.raises(AttributeError):
            engine.name = "Other"  # type: ignore[misc]

    def test_calendar_rules_are_not_applied_to_engines_by_default(
        self, context_factory
    ) -> None:
        # An engine that is four years old but barely driven is still fine.
        engine = CapuletEngine()
        context = context_factory(
            current_date=date(2026, 6, 1), last_service_date=date(2020, 6, 1)
        )
        assert engine.needs_service(context) is False

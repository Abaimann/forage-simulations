"""Unit tests for tyre components."""

from __future__ import annotations

import pytest

from lyft_fleet.domain.components.tire import CarriganTire, OctoprimeTire, Tire
from lyft_fleet.domain.criteria import Aggregation, WearThresholdCriterion
from lyft_fleet.domain.serviceable import Serviceable
from lyft_fleet.errors import InvalidSpecificationError

pytestmark = pytest.mark.unit


class TestCarriganTire:
    """Carrigan: trips when any single wheel reaches 90 % wear."""

    def test_is_a_serviceable_tire(self) -> None:
        assert isinstance(CarriganTire(), Tire)
        assert isinstance(CarriganTire(), Serviceable)

    def test_does_not_need_service_with_fresh_tyres(self, context_factory) -> None:
        tire = CarriganTire()
        assert tire.needs_service(context_factory(tire_wear=(0.1, 0.2, 0.3, 0.4))) is False

    def test_needs_service_when_one_wheel_is_worn_out(self, context_factory) -> None:
        tire = CarriganTire()
        assert tire.needs_service(context_factory(tire_wear=(0.1, 0.95, 0.1, 0.1))) is True

    def test_needs_service_exactly_at_the_threshold(self, context_factory) -> None:
        tire = CarriganTire()
        assert tire.needs_service(context_factory(tire_wear=(0.9,))) is True

    def test_does_not_need_service_just_below_the_threshold(self, context_factory) -> None:
        tire = CarriganTire()
        assert tire.needs_service(context_factory(tire_wear=(0.89,))) is False

    def test_does_not_need_service_without_sensor_data(self, context_factory) -> None:
        tire = CarriganTire()
        assert tire.needs_service(context_factory(tire_wear=())) is False

    def test_the_threshold_is_configurable(self, context_factory) -> None:
        tire = CarriganTire(threshold=0.5)
        assert tire.needs_service(context_factory(tire_wear=(0.6,))) is True

    def test_reports_the_reason(self, context_factory) -> None:
        tire = CarriganTire()
        reasons = tire.service_reasons(context_factory(tire_wear=(0.95,)))
        assert len(reasons) == 1
        assert "Carrigan" in reasons[0]

    def test_reports_no_reason_when_not_due(self, context_factory) -> None:
        assert CarriganTire().service_reasons(context_factory()) == ()


class TestOctoprimeTire:
    """Octoprime: trips when the combined wear reaches 3.0."""

    def test_does_not_need_service_with_fresh_tyres(self, context_factory) -> None:
        tire = OctoprimeTire()
        assert tire.needs_service(context_factory(tire_wear=(0.1, 0.1, 0.1, 0.1))) is False

    def test_needs_service_when_combined_wear_is_high(self, context_factory) -> None:
        tire = OctoprimeTire()
        assert tire.needs_service(context_factory(tire_wear=(0.8, 0.8, 0.8, 0.8))) is True

    def test_needs_service_exactly_at_the_threshold(self, context_factory) -> None:
        tire = OctoprimeTire()
        assert tire.needs_service(context_factory(tire_wear=(0.75, 0.75, 0.75, 0.75))) is True

    def test_a_single_worn_wheel_is_not_enough(self, context_factory) -> None:
        tire = OctoprimeTire()
        assert tire.needs_service(context_factory(tire_wear=(1.0, 0.5, 0.5, 0.5))) is False

    def test_does_not_need_service_without_sensor_data(self, context_factory) -> None:
        tire = OctoprimeTire()
        assert tire.needs_service(context_factory(tire_wear=())) is False

    def test_the_threshold_is_configurable(self, context_factory) -> None:
        tire = OctoprimeTire(threshold=1.0)
        assert tire.needs_service(context_factory(tire_wear=(0.6, 0.6))) is True

    def test_reports_the_reason(self, context_factory) -> None:
        tire = OctoprimeTire()
        reasons = tire.service_reasons(context_factory(tire_wear=(0.8, 0.8, 0.8, 0.8)))
        assert "Octoprime" in reasons[0]


class TestTireBase:
    """Behaviour shared by every tyre."""

    def test_rejects_an_empty_criterion_set(self) -> None:
        with pytest.raises(InvalidSpecificationError, match="at least one criterion"):
            Tire(())

    def test_rejects_a_non_criterion(self) -> None:
        with pytest.raises(InvalidSpecificationError, match="expected ServiceCriterion"):
            Tire((42,))  # type: ignore[arg-type]

    def test_exposes_its_criteria(self) -> None:
        tire = CarriganTire()
        assert len(tire.criteria) == 1
        criterion = tire.criteria[0]
        assert isinstance(criterion, WearThresholdCriterion)
        assert criterion.aggregation is Aggregation.MAX

    def test_exposes_its_name_and_component_type(self) -> None:
        tire = OctoprimeTire()
        assert tire.name == "Octoprime"
        assert tire.component_type == "tire"

    def test_repr_is_stable(self) -> None:
        assert repr(CarriganTire()) == "CarriganTire(name='Carrigan')"

    def test_a_custom_tire_can_be_built_from_any_criteria(self, context_factory) -> None:
        tire = Tire((WearThresholdCriterion(0.4, Aggregation.SUM),), name="Custom")
        assert tire.needs_service(context_factory(tire_wear=(0.2, 0.3))) is True

    def test_tire_is_immutable_in_practice(self) -> None:
        tire = CarriganTire()
        with pytest.raises(AttributeError):
            tire.name = "Other"  # type: ignore[misc]

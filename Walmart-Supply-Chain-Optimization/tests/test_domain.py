"""Unit tests for the domain layer: entities, policies and configuration."""

from __future__ import annotations

import pytest

from walmart_logistics.config import DispatchConfig
from walmart_logistics.domain.entities import (
    DispatchPolicy,
    ExpressFirstPolicy,
    PackageRequest,
    PriorityClass,
    SlaUrgencyPolicy,
    SmallestFirstPolicy,
    TruckLoadEvent,
    Zone,
    build_policy,
)
from walmart_logistics.errors import ConfigurationError


class TestPriorityClass:
    """The service tier enumeration."""

    def test_base_weight_is_ordered(self) -> None:
        assert (
            PriorityClass.EXPRESS.base_weight
            > PriorityClass.STANDARD.base_weight
            > PriorityClass.ECONOMY.base_weight
        )

    def test_str_returns_the_value(self) -> None:
        assert str(PriorityClass.EXPRESS) == "express"


class TestZone:
    """The zone enumeration."""

    def test_str_returns_the_value(self) -> None:
        assert str(Zone.NORTH) == "north"


class TestPackageRequest:
    """The package value object."""

    def test_slack_is_the_remaining_time(self) -> None:
        package = PackageRequest(
            package_id="P1",
            arrival_time=10.0,
            sla_deadline=100.0,
            priority=PriorityClass.STANDARD,
        )
        assert package.slack == 90.0

    def test_slack_can_be_negative(self) -> None:
        package = PackageRequest(
            package_id="P1",
            arrival_time=100.0,
            sla_deadline=50.0,
            priority=PriorityClass.STANDARD,
        )
        assert package.slack == -50.0

    def test_is_late_at(self) -> None:
        package = PackageRequest(
            package_id="P1",
            arrival_time=0.0,
            sla_deadline=50.0,
            priority=PriorityClass.STANDARD,
        )
        assert package.is_late_at(49.0) is False
        assert package.is_late_at(50.0) is False
        assert package.is_late_at(51.0) is True

    def test_is_immutable(self) -> None:
        package = PackageRequest(
            package_id="P1",
            arrival_time=0.0,
            sla_deadline=50.0,
            priority=PriorityClass.STANDARD,
        )
        with pytest.raises(AttributeError):
            package.package_id = "P2"  # type: ignore[misc]

    def test_equality_is_by_value(self) -> None:
        def build() -> PackageRequest:
            return PackageRequest(
                package_id="P1",
                arrival_time=0.0,
                sla_deadline=50.0,
                priority=PriorityClass.STANDARD,
            )

        assert build() == build()


class TestTruckLoadEvent:
    """The truck value object."""

    def test_capacity_and_zone(self) -> None:
        truck = TruckLoadEvent(
            truck_id="T1", ready_time=5.0, capacity=30, zone=Zone.NORTH
        )
        assert truck.capacity == 30
        assert truck.zone is Zone.NORTH


class TestPolicies:
    """The dispatch strategies."""

    def test_base_policy_is_abstract(self) -> None:
        with pytest.raises(NotImplementedError):
            DispatchPolicy().urgency(
                PackageRequest("P", 0.0, 1.0, PriorityClass.STANDARD)
            )

    def test_express_first_prefers_the_higher_tier(self) -> None:
        policy = ExpressFirstPolicy()
        express = PackageRequest("A", 0.0, 100.0, PriorityClass.EXPRESS)
        economy = PackageRequest("B", 0.0, 100.0, PriorityClass.ECONOMY)
        assert policy.urgency(express) > policy.urgency(economy)

    def test_sla_urgency_prefers_the_tighter_deadline(self) -> None:
        policy = SlaUrgencyPolicy()
        tight = PackageRequest("A", 0.0, 50.0, PriorityClass.STANDARD)
        loose = PackageRequest("B", 0.0, 900.0, PriorityClass.STANDARD)
        assert policy.urgency(tight) > policy.urgency(loose)

    def test_sla_urgency_keeps_the_tier_bonus(self) -> None:
        policy = SlaUrgencyPolicy()
        express = PackageRequest("A", 0.0, 900.0, PriorityClass.EXPRESS)
        economy = PackageRequest("B", 0.0, 100.0, PriorityClass.ECONOMY)
        assert policy.urgency(express) > policy.urgency(economy)

    def test_smallest_first_prefers_the_smaller_package(self) -> None:
        policy = SmallestFirstPolicy()
        small = PackageRequest("A", 0.0, 100.0, PriorityClass.STANDARD, size=1)
        large = PackageRequest("B", 0.0, 100.0, PriorityClass.STANDARD, size=9)
        assert policy.urgency(small) > policy.urgency(large)

    def test_build_policy_by_name(self) -> None:
        assert isinstance(build_policy("express_first"), ExpressFirstPolicy)
        assert isinstance(build_policy("sla_urgency"), SlaUrgencyPolicy)
        assert isinstance(build_policy("smallest_first"), SmallestFirstPolicy)

    def test_build_policy_rejects_unknown_names(self) -> None:
        with pytest.raises(ValueError, match="unknown dispatch policy"):
            build_policy("does_not_exist")

    def test_policy_repr(self) -> None:
        assert "express_first" in repr(ExpressFirstPolicy())


class TestDispatchConfig:
    """Validation of the simulation configuration."""

    def test_defaults_are_valid(self) -> None:
        config = DispatchConfig()
        assert config.arity == 8
        assert config.arity_exponent == 3

    @pytest.mark.parametrize(
        "overrides",
        [
            {"packages": -1},
            {"trucks": -1},
            {"arity_exponent": 0},
            {"arrival_window": 0.0},
            {"arrival_window": -5.0},
            {"sla_min": 0.0},
            {"sla_max": 10.0, "sla_min": 20.0},
            {"truck_capacity_min": 0},
            {"truck_capacity_max": 5, "truck_capacity_min": 10},
            {"truck_ready_min": -1.0},
            {"truck_ready_max": 5.0, "truck_ready_min": 10.0},
            {"max_packages_per_truck": 0},
        ],
    )
    def test_invalid_configurations_are_rejected(self, overrides: dict[str, object]) -> None:
        with pytest.raises(ConfigurationError):
            DispatchConfig(**overrides)  # type: ignore[arg-type]

    def test_zero_packages_and_trucks_are_allowed(self) -> None:
        config = DispatchConfig(packages=0, trucks=0)
        assert config.packages == 0

    def test_with_overrides_returns_a_new_instance(self) -> None:
        config = DispatchConfig()
        other = config.with_overrides(packages=10)
        assert other.packages == 10
        assert config.packages != 10

    def test_with_overrides_validates_the_result(self) -> None:
        config = DispatchConfig()
        with pytest.raises(ConfigurationError):
            config.with_overrides(arity_exponent=0)

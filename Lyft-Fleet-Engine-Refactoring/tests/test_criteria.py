"""Unit tests for the service criteria (the Strategy pattern)."""

from __future__ import annotations

from dataclasses import FrozenInstanceError
from datetime import date

import pytest

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
from lyft_fleet.domain.value_objects import ServiceContext
from lyft_fleet.errors import InvalidSpecificationError

pytestmark = pytest.mark.unit


# --------------------------------------------------------------------------- #
# MileageCriterion
# --------------------------------------------------------------------------- #
class TestMileageCriterion:
    """Distance based triggers."""

    def test_is_not_due_without_miles_driven(self, context_factory) -> None:
        criterion = MileageCriterion(30_000)
        assert criterion.is_due(context_factory(current_mileage=0)) is False

    def test_is_not_due_exactly_at_the_boundary(self, context_factory) -> None:
        # The rule is "more than 30 000 miles", so exactly 30 000 is fine.
        criterion = MileageCriterion(30_000)
        assert criterion.is_due(context_factory(current_mileage=30_000)) is False

    def test_is_due_one_mile_past_the_boundary(self, context_factory) -> None:
        criterion = MileageCriterion(30_000)
        assert criterion.is_due(context_factory(current_mileage=30_001)) is True

    def test_uses_the_distance_since_the_last_service(self, context_factory) -> None:
        criterion = MileageCriterion(30_000)
        context = context_factory(current_mileage=100_000, last_service_mileage=70_001)
        assert criterion.is_due(context) is False
        context = context_factory(current_mileage=100_000, last_service_mileage=69_999)
        assert criterion.is_due(context) is True

    def test_zero_interval_trips_immediately_after_any_mile(self, context_factory) -> None:
        criterion = MileageCriterion(0)
        assert criterion.is_due(context_factory(current_mileage=1)) is True
        assert criterion.is_due(context_factory(current_mileage=0)) is False

    def test_rejects_a_negative_interval(self) -> None:
        with pytest.raises(InvalidSpecificationError, match="interval_miles"):
            MileageCriterion(-1)

    def test_describe_mentions_the_interval(self) -> None:
        assert "30000" in MileageCriterion(30_000).describe()


# --------------------------------------------------------------------------- #
# CalendarCriterion
# --------------------------------------------------------------------------- #
class TestCalendarCriterion:
    """Time based triggers."""

    def test_is_not_due_before_the_threshold(self, context_factory) -> None:
        criterion = CalendarCriterion(3)
        context = context_factory(
            current_date=date(2024, 5, 31), last_service_date=date(2021, 6, 1)
        )
        assert criterion.is_due(context) is False

    def test_is_not_due_exactly_on_the_threshold_date(self, context_factory) -> None:
        criterion = CalendarCriterion(3)
        context = context_factory(
            current_date=date(2024, 6, 1), last_service_date=date(2021, 6, 1)
        )
        assert criterion.is_due(context) is False

    def test_is_due_one_day_past_the_threshold(self, context_factory) -> None:
        criterion = CalendarCriterion(3)
        context = context_factory(
            current_date=date(2024, 6, 2), last_service_date=date(2021, 6, 1)
        )
        assert criterion.is_due(context) is True

    def test_handles_the_leap_day_clamping(self, context_factory) -> None:
        criterion = CalendarCriterion(1)
        context = context_factory(
            current_date=date(2021, 3, 1), last_service_date=date(2020, 2, 29)
        )
        # 29 Feb 2020 + 1 year clamps to 28 Feb 2021, so 1 March is due.
        assert criterion.is_due(context) is True

    def test_zero_year_interval_trips_after_any_elapsed_time(self, context_factory) -> None:
        criterion = CalendarCriterion(0)
        # Same day: the threshold equals the last service date, so not due.
        context = context_factory(
            current_date=date(2024, 6, 1), last_service_date=date(2024, 6, 1)
        )
        assert criterion.is_due(context) is False
        # One day later the criterion trips.
        context = context_factory(
            current_date=date(2024, 6, 2), last_service_date=date(2024, 6, 1)
        )
        assert criterion.is_due(context) is True

    def test_rejects_a_negative_interval(self) -> None:
        with pytest.raises(InvalidSpecificationError, match="interval_years"):
            CalendarCriterion(-1)

    def test_describe_mentions_the_interval(self) -> None:
        assert "3" in CalendarCriterion(3).describe()


# --------------------------------------------------------------------------- #
# WearThresholdCriterion
# --------------------------------------------------------------------------- #
class TestWearThresholdCriterion:
    """Sensor wear thresholds."""

    def test_max_aggregation_trips_on_a_single_worn_wheel(self, context_factory) -> None:
        criterion = WearThresholdCriterion(0.9, Aggregation.MAX)
        context = context_factory(tire_wear=(0.1, 0.95, 0.1, 0.1))
        assert criterion.is_due(context) is True

    def test_max_aggregation_is_not_due_when_every_wheel_is_below(self, context_factory) -> None:
        criterion = WearThresholdCriterion(0.9, Aggregation.MAX)
        context = context_factory(tire_wear=(0.1, 0.89, 0.5, 0.2))
        assert criterion.is_due(context) is False

    def test_max_aggregation_trips_exactly_at_the_threshold(self, context_factory) -> None:
        criterion = WearThresholdCriterion(0.9, Aggregation.MAX)
        assert criterion.is_due(context_factory(tire_wear=(0.9,))) is True

    def test_sum_aggregation_trips_on_combined_wear(self, context_factory) -> None:
        criterion = WearThresholdCriterion(3.0, Aggregation.SUM)
        context = context_factory(tire_wear=(0.8, 0.8, 0.8, 0.8))
        assert criterion.is_due(context) is True

    def test_sum_aggregation_ignores_a_single_worn_wheel(self, context_factory) -> None:
        criterion = WearThresholdCriterion(3.0, Aggregation.SUM)
        context = context_factory(tire_wear=(1.0, 0.5, 0.5, 0.5))
        assert criterion.is_due(context) is False

    def test_sum_aggregation_trips_exactly_at_the_threshold(self, context_factory) -> None:
        criterion = WearThresholdCriterion(3.0, Aggregation.SUM)
        assert criterion.is_due(context_factory(tire_wear=(0.75, 0.75, 0.75, 0.75))) is True

    def test_without_sensor_data_the_rule_cannot_trip(self, context_factory) -> None:
        criterion = WearThresholdCriterion(0.0, Aggregation.MAX)
        assert criterion.is_due(context_factory(tire_wear=())) is False

    def test_rejects_a_negative_threshold(self) -> None:
        with pytest.raises(InvalidSpecificationError, match="threshold"):
            WearThresholdCriterion(-0.1)

    def test_rejects_an_invalid_aggregation(self) -> None:
        with pytest.raises(InvalidSpecificationError, match="aggregation"):
            WearThresholdCriterion(0.9, "max")  # type: ignore[arg-type]

    def test_describe_distinguishes_the_aggregation(self) -> None:
        assert "any wheel" in WearThresholdCriterion(0.9, Aggregation.MAX).describe()
        assert "combined" in WearThresholdCriterion(3.0, Aggregation.SUM).describe()


# --------------------------------------------------------------------------- #
# WarningLightCriterion
# --------------------------------------------------------------------------- #
class TestWarningLightCriterion:
    """Dashboard telltale trigger."""

    def test_is_due_when_the_light_is_on(self, context_factory) -> None:
        criterion = WarningLightCriterion()
        assert criterion.is_due(context_factory(warning_light_on=True)) is True

    def test_is_not_due_when_the_light_is_off(self, context_factory) -> None:
        criterion = WarningLightCriterion()
        assert criterion.is_due(context_factory(warning_light_on=False)) is False


# --------------------------------------------------------------------------- #
# Composite criteria
# --------------------------------------------------------------------------- #
class TestCompositeCriteria:
    """Composition of criteria without inheritance."""

    def test_any_is_due_when_one_child_is_due(self, context_factory) -> None:
        criterion = AnyCriterion((MileageCriterion(30_000), WarningLightCriterion()))
        assert criterion.is_due(context_factory(warning_light_on=True)) is True

    def test_any_is_not_due_when_no_child_is_due(self, context_factory) -> None:
        criterion = AnyCriterion((MileageCriterion(30_000), WarningLightCriterion()))
        assert criterion.is_due(context_factory()) is False

    def test_all_is_due_only_when_every_child_is_due(self, context_factory) -> None:
        criterion = AllCriterion((MileageCriterion(30_000), WarningLightCriterion()))
        assert criterion.is_due(context_factory(current_mileage=40_000)) is False
        assert (
            criterion.is_due(
                context_factory(current_mileage=40_000, warning_light_on=True)
            )
            is True
        )

    def test_any_rejects_an_empty_rule_set(self) -> None:
        with pytest.raises(InvalidSpecificationError, match="at least one criterion"):
            AnyCriterion(())

    def test_all_rejects_an_empty_rule_set(self) -> None:
        with pytest.raises(InvalidSpecificationError, match="at least one criterion"):
            AllCriterion(())

    def test_any_rejects_a_non_criterion(self) -> None:
        with pytest.raises(InvalidSpecificationError, match="expected ServiceCriterion"):
            AnyCriterion(("not-a-criterion",))  # type: ignore[arg-type]

    def test_all_rejects_a_non_criterion(self) -> None:
        with pytest.raises(InvalidSpecificationError, match="expected ServiceCriterion"):
            AllCriterion((object(),))  # type: ignore[arg-type]

    def test_describe_lists_the_children(self) -> None:
        criterion = AnyCriterion((MileageCriterion(30_000), WarningLightCriterion()))
        described = criterion.describe()
        assert described.startswith("any of")
        assert "30000" in described


# --------------------------------------------------------------------------- #
# Contract
# --------------------------------------------------------------------------- #
class TestServiceCriterionContract:
    """The contract every criterion must honour."""

    @pytest.mark.parametrize(
        "criterion",
        [
            MileageCriterion(30_000),
            CalendarCriterion(3),
            WearThresholdCriterion(0.9),
            WarningLightCriterion(),
            AnyCriterion((MileageCriterion(1),)),
            AllCriterion((MileageCriterion(1),)),
        ],
    )
    def test_every_criterion_implements_the_interface(self, criterion) -> None:
        assert isinstance(criterion, ServiceCriterion)
        assert isinstance(criterion.describe(), str)
        assert criterion.describe() != ""

    def test_criteria_are_immutable(self) -> None:
        criterion = MileageCriterion(30_000)
        with pytest.raises(FrozenInstanceError):
            criterion.interval_miles = 5  # type: ignore[misc]

    def test_str_delegates_to_describe(self) -> None:
        criterion = MileageCriterion(30_000)
        assert str(criterion) == criterion.describe()

    def test_repr_includes_the_criterion_type(self) -> None:
        # ``ServiceCriterion.__repr__`` is overridden by the dataclass repr,
        # which carries the configured threshold.
        assert repr(MileageCriterion(30_000)) == "MileageCriterion(interval_miles=30000)"
        assert repr(WarningLightCriterion()) == "WarningLightCriterion()"
        assert repr(WearThresholdCriterion(0.9)) == (
            "WearThresholdCriterion(threshold=0.9, aggregation=<Aggregation.MAX: 'max'>)"
        )


class TestContextIsIndependentOfCriteria:
    """A criterion must never mutate the context it inspects."""

    def test_evaluation_does_not_mutate_the_context(self, context_factory) -> None:
        context = context_factory(current_mileage=40_000, tire_wear=(0.1, 0.95))
        before = str(context)
        MileageCriterion(30_000).is_due(context)
        WearThresholdCriterion(0.9, Aggregation.MAX).is_due(context)
        assert str(context) == before
        assert isinstance(context, ServiceContext)

"""Unit tests for the :class:`Car` aggregate and the five fleet models.

These tests cover the acceptance criterion of the task: the servicing logic
of every car model (Calliope, Glissando, Palindrome, Rorschach, Thovex).
"""

from __future__ import annotations

from collections.abc import Callable
from datetime import date

import pytest

from lyft_fleet.domain.car import (
    Calliope,
    Car,
    Glissando,
    Palindrome,
    Rorschach,
    Thovex,
)
from lyft_fleet.domain.components.battery import NubbinBattery, SpindlerBattery
from lyft_fleet.domain.components.engine import (
    CapuletEngine,
    SternmanEngine,
    WilloughbyEngine,
)
from lyft_fleet.domain.components.tire import CarriganTire, OctoprimeTire
from lyft_fleet.domain.criteria import CalendarCriterion, MileageCriterion
from lyft_fleet.domain.serviceable import Serviceable
from lyft_fleet.domain.value_objects import ServiceContext

pytestmark = pytest.mark.unit

ALL_MODELS = (Calliope, Glissando, Palindrome, Rorschach, Thovex)

#: A model is any zero-argument callable returning a car.
ModelFactory = Callable[[], Car]


# --------------------------------------------------------------------------- #
# Composition
# --------------------------------------------------------------------------- #
class TestCarComposition:
    """The aggregate is built from parts, not from inheritance."""

    def test_calliope_is_composed_from_the_expected_parts(self) -> None:
        car = Calliope()
        assert isinstance(car.engine, CapuletEngine)
        assert isinstance(car.battery, SpindlerBattery)
        assert isinstance(car.tire, CarriganTire)

    def test_glissando_is_composed_from_the_expected_parts(self) -> None:
        car = Glissando()
        assert isinstance(car.engine, WilloughbyEngine)
        assert isinstance(car.battery, SpindlerBattery)
        assert isinstance(car.tire, OctoprimeTire)

    def test_palindrome_is_composed_from_the_expected_parts(self) -> None:
        car = Palindrome()
        assert isinstance(car.engine, SternmanEngine)
        assert isinstance(car.battery, NubbinBattery)
        assert isinstance(car.tire, CarriganTire)

    def test_rorschach_is_composed_from_the_expected_parts(self) -> None:
        car = Rorschach()
        assert isinstance(car.engine, WilloughbyEngine)
        assert isinstance(car.battery, NubbinBattery)
        assert isinstance(car.tire, OctoprimeTire)

    def test_thovex_is_composed_from_the_expected_parts(self) -> None:
        car = Thovex()
        assert isinstance(car.engine, CapuletEngine)
        assert isinstance(car.battery, NubbinBattery)
        assert isinstance(car.tire, CarriganTire)

    @pytest.mark.parametrize("model", ALL_MODELS)
    def test_every_model_is_a_car_and_a_serviceable(self, model: ModelFactory) -> None:
        car = model()
        assert isinstance(car, Car)
        assert isinstance(car, Serviceable)
        assert car.component_type == "car"

    @pytest.mark.parametrize("model", ALL_MODELS)
    def test_every_model_exposes_its_three_components(self, model: ModelFactory) -> None:
        car = model()
        assert len(car.components) == 3

    @pytest.mark.parametrize(
        ("model", "expected_name"),
        [
            (Calliope, "Calliope"),
            (Glissando, "Glissando"),
            (Palindrome, "Palindrome"),
            (Rorschach, "Rorschach"),
            (Thovex, "Thovex"),
        ],
    )
    def test_every_model_reports_its_name(
        self, model: ModelFactory, expected_name: str
    ) -> None:
        assert model().name == expected_name

    def test_parts_can_be_injected(self) -> None:
        car = Calliope(
            engine=WilloughbyEngine(),
            battery=NubbinBattery(),
            tire=OctoprimeTire(),
        )
        assert isinstance(car.engine, WilloughbyEngine)
        assert isinstance(car.battery, NubbinBattery)
        assert isinstance(car.tire, OctoprimeTire)

    def test_rejects_a_non_engine(self) -> None:
        with pytest.raises(TypeError, match="engine must be an Engine"):
            Car(engine="not-an-engine", battery=SpindlerBattery(), tire=CarriganTire())  # type: ignore[arg-type]

    def test_rejects_a_non_battery(self) -> None:
        with pytest.raises(TypeError, match="battery must be a Battery"):
            Car(engine=CapuletEngine(), battery="nope", tire=CarriganTire())  # type: ignore[arg-type]

    def test_rejects_a_non_tire(self) -> None:
        with pytest.raises(TypeError, match="tire must be a Tire"):
            Car(engine=CapuletEngine(), battery=SpindlerBattery(), tire=object())  # type: ignore[arg-type]

    def test_rejects_a_non_criterion_inspection_rule(self) -> None:
        with pytest.raises(TypeError, match="inspection criteria"):
            Car(
                engine=CapuletEngine(),
                battery=SpindlerBattery(),
                tire=CarriganTire(),
                inspection_criteria=("nope",),  # type: ignore[arg-type]
            )


# --------------------------------------------------------------------------- #
# Aggregate behaviour
# --------------------------------------------------------------------------- #
class TestCarServiceLogic:
    """A car is due as soon as *one* of its systems is due."""

    @pytest.mark.parametrize("model", ALL_MODELS)
    def test_a_healthy_car_needs_no_service(self, model: ModelFactory, context_factory) -> None:
        car = model()
        assert car.needs_service(context_factory()) is False

    @pytest.mark.parametrize("model", ALL_MODELS)
    def test_a_healthy_car_reports_no_reasons(
        self, model: ModelFactory, context_factory
    ) -> None:
        assert model().service_reasons(context_factory()) == ()

    @pytest.mark.parametrize("model", ALL_MODELS)
    def test_a_car_with_an_overdue_engine_needs_service(
        self, model: ModelFactory, context_factory
    ) -> None:
        car = model()
        # 90 000 miles breaks both the Capulet (30k) and Willoughby (60k) rules.
        context = context_factory(current_mileage=90_000)
        if isinstance(car.engine, SternmanEngine):
            # The Sternman engine only reacts to the warning light.
            assert car.needs_service(context) is False
        else:
            assert car.needs_service(context) is True

    @pytest.mark.parametrize("model", ALL_MODELS)
    def test_a_car_with_an_expired_battery_needs_service(
        self, model: ModelFactory, context_factory
    ) -> None:
        car = model()
        # 5 years after the last service breaks both battery lifetimes.
        context = context_factory(
            current_date=date(2027, 6, 1), last_service_date=date(2022, 6, 1)
        )
        assert car.needs_service(context) is True

    @pytest.mark.parametrize("model", ALL_MODELS)
    def test_a_car_with_worn_tyres_needs_service(
        self, model: ModelFactory, context_factory
    ) -> None:
        car = model()
        context = context_factory(tire_wear=(1.0, 1.0, 1.0, 1.0))
        assert car.needs_service(context) is True

    @pytest.mark.parametrize("model", ALL_MODELS)
    def test_reasons_are_reported_for_every_due_system(
        self, model: ModelFactory, context_factory
    ) -> None:
        car = model()
        context = context_factory(
            current_mileage=90_000,
            current_date=date(2027, 6, 1),
            last_service_date=date(2022, 6, 1),
            tire_wear=(1.0, 1.0, 1.0, 1.0),
        )
        reasons = car.service_reasons(context)
        assert len(reasons) >= 3
        assert any("Battery" in reason for reason in reasons)
        assert any("Tire" in reason for reason in reasons)


class TestCalliopeServicing:
    """Calliope: Capulet + Spindler + Carrigan, two year inspection."""

    def test_needs_no_service_when_everything_is_fresh(self, context_factory) -> None:
        assert Calliope().needs_service(context_factory()) is False

    def test_needs_service_after_thirty_thousand_miles(self, context_factory) -> None:
        car = Calliope()
        assert car.needs_service(context_factory(current_mileage=30_001)) is True

    def test_does_not_need_service_at_exactly_thirty_thousand_miles(
        self, context_factory
    ) -> None:
        assert Calliope().needs_service(context_factory(current_mileage=30_000)) is False

    def test_needs_service_after_three_years(self, context_factory) -> None:
        car = Calliope()
        context = context_factory(
            current_date=date(2025, 6, 2), last_service_date=date(2022, 6, 1)
        )
        assert car.needs_service(context) is True

    def test_needs_service_when_a_tyre_reaches_the_wear_limit(
        self, context_factory
    ) -> None:
        car = Calliope()
        assert car.needs_service(context_factory(tire_wear=(0.1, 0.91, 0.1, 0.1))) is True

    def test_does_not_need_service_for_moderate_even_wear(
        self, context_factory
    ) -> None:
        car = Calliope()
        # Combined wear 2.0 is below the Octoprime limit and no single wheel
        # reaches the Carrigan limit.
        assert car.needs_service(context_factory(tire_wear=(0.5, 0.5, 0.5, 0.5))) is False


class TestGlissandoServicing:
    """Glissando: Willoughby + Spindler + Octoprime, two year inspection."""

    def test_needs_no_service_when_everything_is_fresh(self, context_factory) -> None:
        assert Glissando().needs_service(context_factory()) is False

    def test_needs_service_after_sixty_thousand_miles(self, context_factory) -> None:
        car = Glissando()
        assert car.needs_service(context_factory(current_mileage=60_001)) is True

    def test_does_not_need_service_at_exactly_sixty_thousand_miles(
        self, context_factory
    ) -> None:
        assert Glissando().needs_service(context_factory(current_mileage=60_000)) is False

    def test_needs_service_when_combined_wear_reaches_three(
        self, context_factory
    ) -> None:
        car = Glissando()
        assert car.needs_service(context_factory(tire_wear=(0.75, 0.75, 0.75, 0.75))) is True

    def test_does_not_need_service_for_a_single_worn_wheel(self, context_factory) -> None:
        car = Glissando()
        # The Octoprime rule uses the combined wear, so 1.0 + 3 x 0.5 = 2.5 < 3.
        assert car.needs_service(context_factory(tire_wear=(1.0, 0.5, 0.5, 0.5))) is False

    def test_needs_service_after_three_years(self, context_factory) -> None:
        car = Glissando()
        context = context_factory(
            current_date=date(2025, 6, 2), last_service_date=date(2022, 6, 1)
        )
        assert car.needs_service(context) is True


class TestPalindromeServicing:
    """Palindrome: Sternman + Nubbin + Carrigan, four year inspection."""

    def test_needs_no_service_when_everything_is_fresh(self, context_factory) -> None:
        assert Palindrome().needs_service(context_factory()) is False

    def test_needs_service_when_the_warning_light_is_on(self, context_factory) -> None:
        car = Palindrome()
        assert car.needs_service(context_factory(warning_light_on=True)) is True

    def test_does_not_need_service_however_far_it_is_driven(
        self, context_factory
    ) -> None:
        # The Sternman engine has no mileage rule.
        car = Palindrome()
        assert car.needs_service(context_factory(current_mileage=1_000_000)) is False

    def test_needs_service_after_four_years(self, context_factory) -> None:
        car = Palindrome()
        context = context_factory(
            current_date=date(2026, 6, 2), last_service_date=date(2022, 6, 1)
        )
        assert car.needs_service(context) is True

    def test_does_not_need_service_after_three_years(self, context_factory) -> None:
        car = Palindrome()
        context = context_factory(
            current_date=date(2025, 6, 1), last_service_date=date(2022, 6, 1)
        )
        assert car.needs_service(context) is False

    def test_needs_service_when_a_tyre_reaches_the_wear_limit(
        self, context_factory
    ) -> None:
        car = Palindrome()
        assert car.needs_service(context_factory(tire_wear=(0.95, 0.1, 0.1, 0.1))) is True


class TestRorschachServicing:
    """Rorschach: Willoughby + Nubbin + Octoprime, four year inspection."""

    def test_needs_no_service_when_everything_is_fresh(self, context_factory) -> None:
        assert Rorschach().needs_service(context_factory()) is False

    def test_needs_service_after_sixty_thousand_miles(self, context_factory) -> None:
        car = Rorschach()
        assert car.needs_service(context_factory(current_mileage=60_001)) is True

    def test_needs_service_after_four_years(self, context_factory) -> None:
        car = Rorschach()
        context = context_factory(
            current_date=date(2026, 6, 2), last_service_date=date(2022, 6, 1)
        )
        assert car.needs_service(context) is True

    def test_needs_service_when_combined_wear_reaches_three(
        self, context_factory
    ) -> None:
        car = Rorschach()
        assert car.needs_service(context_factory(tire_wear=(0.75, 0.75, 0.75, 0.75))) is True


class TestThovexServicing:
    """Thovex: Capulet + Nubbin + Carrigan, four year inspection."""

    def test_needs_no_service_when_everything_is_fresh(self, context_factory) -> None:
        assert Thovex().needs_service(context_factory()) is False

    def test_needs_service_after_thirty_thousand_miles(self, context_factory) -> None:
        car = Thovex()
        assert car.needs_service(context_factory(current_mileage=30_001)) is True

    def test_needs_service_after_four_years(self, context_factory) -> None:
        car = Thovex()
        context = context_factory(
            current_date=date(2026, 6, 2), last_service_date=date(2022, 6, 1)
        )
        assert car.needs_service(context) is True

    def test_does_not_need_service_after_three_years(self, context_factory) -> None:
        car = Thovex()
        context = context_factory(
            current_date=date(2025, 6, 1), last_service_date=date(2022, 6, 1)
        )
        assert car.needs_service(context) is False


# --------------------------------------------------------------------------- #
# Fleet-wide inspections
# --------------------------------------------------------------------------- #
class TestInspectionCriteria:
    """The periodic fleet inspection is a criterion on the aggregate."""

    def test_calliope_has_a_two_year_inspection(self) -> None:
        assert len(Calliope().inspection_criteria) == 1
        criterion = Calliope().inspection_criteria[0]
        assert isinstance(criterion, CalendarCriterion)
        assert criterion.interval_years == 2

    def test_thovex_has_a_four_year_inspection(self) -> None:
        criterion = Thovex().inspection_criteria[0]
        assert isinstance(criterion, CalendarCriterion)
        assert criterion.interval_years == 4

    def test_the_inspection_is_reported_as_a_reason(self, context_factory) -> None:
        car = Calliope()
        context = context_factory(
            current_date=date(2024, 6, 2), last_service_date=date(2022, 6, 1)
        )
        reasons = car.service_reasons(context)
        assert any("Inspection" in reason for reason in reasons)

    def test_inspection_criteria_can_be_replaced(self, context_factory) -> None:
        car = Calliope(inspection_criteria=(MileageCriterion(100_000),))
        assert car.needs_service(context_factory(current_mileage=100_001)) is True
        assert car.needs_service(context_factory(current_mileage=1)) is False

    def test_inspection_criteria_can_be_emptied(self, context_factory) -> None:
        car = Calliope(inspection_criteria=())
        context = context_factory(
            current_date=date(2030, 6, 1), last_service_date=date(2022, 6, 1)
        )
        # The battery rule still applies, but the 2 year inspection does not.
        assert not any("Inspection" in reason for reason in car.service_reasons(context))


class TestExtensibility:
    """A new model is added by declaring its parts - no core code changes."""

    def test_a_new_model_can_be_declared_outside_the_package(self, context_factory) -> None:
        from lyft_fleet.domain.car import _ModelCar

        class Limo(_ModelCar):
            """A bespoke model with no periodic inspection."""

            INSPECTION_INTERVAL_YEARS = 0

            def __init__(self) -> None:
                super().__init__(
                    CapuletEngine(),
                    NubbinBattery(),
                    OctoprimeTire(),
                    inspection_criteria=self._default_inspection_criteria(),
                    name="Limo",
                )

        limo = Limo()
        assert limo.name == "Limo"
        assert limo.inspection_criteria == ()
        assert limo.needs_service(context_factory()) is False

    def test_a_new_model_can_be_registered_in_the_factory(self) -> None:
        from lyft_fleet.infrastructure.factory import CarFactory

        factory = CarFactory()
        factory.register("limo", Calliope)
        assert factory.create("limo").name == "Calliope"

    def test_a_new_criterion_can_be_used_without_touching_the_core(
        self, context_factory
    ) -> None:
        from lyft_fleet.domain.criteria import ServiceCriterion

        class OverheatCriterion(ServiceCriterion):
            """A bespoke rule: the coolant temperature is too high."""

            def is_due(self, context: ServiceContext) -> bool:
                return context.warning_light_on

            def describe(self) -> str:
                return "coolant temperature too high"

        car = Calliope(inspection_criteria=(OverheatCriterion(),))
        assert car.needs_service(context_factory(warning_light_on=True)) is True
        assert car.needs_service(context_factory(warning_light_on=False)) is False


class TestCarImmutability:
    """Cars expose read-only views of their parts."""

    def test_the_engine_reference_cannot_be_replaced(self) -> None:
        car = Calliope()
        with pytest.raises(AttributeError):
            car.engine = WilloughbyEngine()  # type: ignore[misc]

    def test_repr_mentions_the_model(self) -> None:
        assert "Calliope" in repr(Calliope())

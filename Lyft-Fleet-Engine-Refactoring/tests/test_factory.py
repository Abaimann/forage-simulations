"""Unit tests for the factories (the Factory pattern)."""

from __future__ import annotations

import pytest

from lyft_fleet.domain.car import (
    Calliope,
    Car,
    Glissando,
    Palindrome,
    Rorschach,
    Thovex,
)
from lyft_fleet.domain.components.battery import Battery, NubbinBattery, SpindlerBattery
from lyft_fleet.domain.components.engine import (
    CapuletEngine,
    Engine,
    SternmanEngine,
    WilloughbyEngine,
)
from lyft_fleet.domain.components.tire import CarriganTire, OctoprimeTire, Tire
from lyft_fleet.errors import UnknownComponentError
from lyft_fleet.infrastructure.factory import (
    BatteryFactory,
    CarFactory,
    EngineFactory,
    TireFactory,
    normalize_name,
)

pytestmark = pytest.mark.unit


class TestNormalizeName:
    """Registry lookups are case- and separator-insensitive."""

    @pytest.mark.parametrize(
        ("raw", "expected"),
        [
            ("Calliope", "calliope"),
            ("  calliope  ", "calliope"),
            ("CAPULET", "capulet"),
            ("Capulet_Engine", "capuletengine"),
            ("capulet-engine", "capuletengine"),
            ("capulet engine", "capuletengine"),
        ],
    )
    def test_normalises(self, raw: str, expected: str) -> None:
        assert normalize_name(raw) == expected

    def test_rejects_a_non_string(self) -> None:
        with pytest.raises(TypeError, match="must be a str"):
            normalize_name(42)  # type: ignore[arg-type]


class TestEngineFactory:
    """Tests for the engine registry."""

    @pytest.mark.parametrize(
        ("name", "expected_type"),
        [
            ("capulet", CapuletEngine),
            ("willoughby", WilloughbyEngine),
            ("sternman", SternmanEngine),
        ],
    )
    def test_builds_the_expected_engine(self, name: str, expected_type: type[Engine]) -> None:
        engine = EngineFactory().create(name)
        assert isinstance(engine, expected_type)

    def test_is_case_insensitive(self) -> None:
        assert isinstance(EngineFactory().create("CAPULET"), CapuletEngine)

    def test_raises_for_an_unknown_engine(self) -> None:
        with pytest.raises(UnknownComponentError, match="unknown engine"):
            EngineFactory().create("banana")

    def test_the_error_lists_the_available_engines(self) -> None:
        with pytest.raises(UnknownComponentError) as excinfo:
            EngineFactory().create("banana")
        assert "capulet" in str(excinfo.value)

    def test_each_call_returns_a_new_instance(self) -> None:
        factory = EngineFactory()
        assert factory.create("capulet") is not factory.create("capulet")

    def test_lists_the_available_engines(self) -> None:
        assert EngineFactory().available() == ("capulet", "sternman", "willoughby")

    def test_supports_membership_checks(self) -> None:
        factory = EngineFactory()
        assert "capulet" in factory
        assert "banana" not in factory
        assert 42 not in factory  # type: ignore[operator]

    def test_reports_its_size(self) -> None:
        assert len(EngineFactory()) == 3

    def test_a_custom_engine_can_be_registered(self) -> None:
        factory = EngineFactory()
        factory.register("turbo", lambda: WilloughbyEngine(interval_miles=1))
        assert isinstance(factory.create("turbo"), WilloughbyEngine)

    def test_registering_a_duplicate_name_is_rejected(self) -> None:
        factory = EngineFactory()
        with pytest.raises(UnknownComponentError, match="already registered"):
            factory.register("capulet", CapuletEngine)

    def test_registering_a_non_callable_is_rejected(self) -> None:
        with pytest.raises(TypeError, match="must be callable"):
            EngineFactory().register("bad", "not-callable")  # type: ignore[arg-type]

    def test_a_custom_registry_can_be_built(self) -> None:
        factory = EngineFactory({"only": SternmanEngine})
        assert factory.available() == ("only",)


class TestBatteryFactory:
    """Tests for the battery registry."""

    @pytest.mark.parametrize(
        ("name", "expected_type"),
        [("nubbin", NubbinBattery), ("spindler", SpindlerBattery)],
    )
    def test_builds_the_expected_battery(self, name: str, expected_type: type[Battery]) -> None:
        assert isinstance(BatteryFactory().create(name), expected_type)

    def test_raises_for_an_unknown_battery(self) -> None:
        with pytest.raises(UnknownComponentError, match="unknown battery"):
            BatteryFactory().create("banana")


class TestTireFactory:
    """Tests for the tyre registry."""

    @pytest.mark.parametrize(
        ("name", "expected_type"),
        [("carrigan", CarriganTire), ("octoprime", OctoprimeTire)],
    )
    def test_builds_the_expected_tire(self, name: str, expected_type: type[Tire]) -> None:
        assert isinstance(TireFactory().create(name), expected_type)

    def test_raises_for_an_unknown_tire(self) -> None:
        with pytest.raises(UnknownComponentError, match="unknown tire"):
            TireFactory().create("banana")


class TestCarFactory:
    """Tests for the vehicle registry."""

    @pytest.mark.parametrize(
        ("name", "expected_type"),
        [
            ("calliope", Calliope),
            ("glissando", Glissando),
            ("palindrome", Palindrome),
            ("rorschach", Rorschach),
            ("thovex", Thovex),
        ],
    )
    def test_builds_the_expected_model(self, name: str, expected_type: type[Car]) -> None:
        assert isinstance(CarFactory().create(name), expected_type)

    def test_lists_the_five_fleet_models(self) -> None:
        assert CarFactory().available() == (
            "calliope",
            "glissando",
            "palindrome",
            "rorschach",
            "thovex",
        )

    def test_is_case_insensitive(self) -> None:
        assert isinstance(CarFactory().create("CALLIOPE"), Calliope)

    def test_tolerates_separators(self) -> None:
        factory = CarFactory()
        assert isinstance(factory.create("call-iope"), Calliope)
        assert isinstance(factory.create(" glissando "), Glissando)
        assert isinstance(factory.create("CALLIOPE"), Calliope)

    def test_raises_for_an_unknown_model(self) -> None:
        with pytest.raises(UnknownComponentError, match="unknown car model"):
            CarFactory().create("banana")

    def test_each_call_returns_a_new_instance(self) -> None:
        factory = CarFactory()
        first = factory.create("calliope")
        second = factory.create("calliope")
        assert first is not second
        assert first.engine is not second.engine

    def test_builds_several_models_in_order(self) -> None:
        cars = CarFactory().create_many(["calliope", "thovex"])
        assert [car.name for car in cars] == ["Calliope", "Thovex"]

    def test_create_many_propagates_unknown_models(self) -> None:
        with pytest.raises(UnknownComponentError):
            CarFactory().create_many(["calliope", "banana"])

    def test_historical_spellings_resolve_to_the_canonical_model(self) -> None:
        factory = CarFactory()
        assert isinstance(factory.create("glissade"), Glissando)
        assert isinstance(factory.create("glissado"), Glissando)

    def test_lists_the_aliases(self) -> None:
        assert "glissade" in CarFactory().aliases

    def test_a_new_alias_can_be_registered(self) -> None:
        factory = CarFactory()
        factory.register_alias("gliss", "glissando")
        assert isinstance(factory.create("gliss"), Glissando)

    def test_aliasing_an_unknown_model_is_rejected(self) -> None:
        with pytest.raises(UnknownComponentError, match="cannot alias unknown"):
            CarFactory().register_alias("x", "banana")

    def test_a_new_model_can_be_registered(self) -> None:
        factory = CarFactory()
        factory.register("my-model", Calliope)
        assert isinstance(factory.create("my-model"), Calliope)

    def test_registering_a_duplicate_model_is_rejected(self) -> None:
        with pytest.raises(UnknownComponentError, match="already registered"):
            CarFactory().register("calliope", Calliope)

    def test_a_custom_registry_can_be_built(self) -> None:
        factory = CarFactory({"only": Thovex})
        assert factory.available() == ("only",)
        assert isinstance(factory.create("only"), Thovex)

    def test_the_error_is_also_a_key_error(self) -> None:
        with pytest.raises(KeyError):
            CarFactory().create("banana")

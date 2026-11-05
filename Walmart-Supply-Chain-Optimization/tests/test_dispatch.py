"""Unit tests for the dispatch simulation and the workload generator."""

from __future__ import annotations

import pytest

from walmart_logistics.application.dispatch_engine import (
    DispatchEngine,
    DispatchMetrics,
    SimulationRunner,
)
from walmart_logistics.application.ports import WorkloadSource
from walmart_logistics.config import DispatchConfig
from walmart_logistics.domain.entities import (
    PackageRequest,
    PriorityClass,
    SlaUrgencyPolicy,
    TruckLoadEvent,
)
from walmart_logistics.infrastructure.workload import (
    SyntheticWorkloadSource,
    build_package,
    build_truck,
)


def package(
    package_id: str,
    arrival: float,
    deadline: float,
    priority: PriorityClass = PriorityClass.STANDARD,
    size: int = 1,
) -> PackageRequest:
    """Build a package for the tests."""
    return PackageRequest(
        package_id=package_id,
        arrival_time=arrival,
        sla_deadline=deadline,
        priority=priority,
        size=size,
    )


class TestDispatchEngineBasics:
    """Basic dispatch behaviour."""

    def test_empty_simulation(self) -> None:
        engine = DispatchEngine(DispatchConfig(packages=0, trucks=0))
        result = engine.run([], [])
        assert result.metrics.packages_arrived == 0
        assert result.metrics.packages_dispatched == 0
        assert result.metrics.packages_pending == 0
        assert result.metrics.on_time_ratio == 0.0
        assert result.metrics.average_wait == 0.0
        assert result.plans == []

    def test_packages_without_trucks_stay_pending(self) -> None:
        engine = DispatchEngine(DispatchConfig(packages=3, trucks=0))
        result = engine.run(
            [package("A", 0.0, 100.0), package("B", 1.0, 100.0)], []
        )
        assert result.metrics.packages_pending == 2
        assert result.metrics.packages_dispatched == 0

    def test_trucks_without_packages_are_ignored(self) -> None:
        engine = DispatchEngine(DispatchConfig(packages=0, trucks=2))
        result = engine.run([], [TruckLoadEvent("T1", 0.0, 10)])
        assert result.metrics.trucks_used == 0
        assert result.plans == []

    def test_packages_are_loaded_onto_the_truck(self) -> None:
        engine = DispatchEngine(DispatchConfig(packages=3, trucks=1))
        result = engine.run(
            [package("A", 0.0, 100.0), package("B", 1.0, 100.0), package("C", 2.0, 100.0)],
            [TruckLoadEvent("T1", 10.0, 10)],
        )
        assert result.metrics.packages_dispatched == 3
        assert result.metrics.trucks_used == 1
        assert len(result.plans) == 1
        assert result.plans[0].truck_id == "T1"
        assert result.metrics.total_capacity_used == 3

    def test_capacity_is_respected(self) -> None:
        engine = DispatchEngine(DispatchConfig(packages=5, trucks=1))
        result = engine.run(
            [package(f"P{index}", 0.0, 100.0) for index in range(5)],
            [TruckLoadEvent("T1", 10.0, 2)],
        )
        assert result.metrics.packages_dispatched == 2
        assert result.metrics.packages_pending == 3
        assert result.plans[0].unused_capacity == 0

    def test_wait_times_are_measured_from_the_arrival(self) -> None:
        engine = DispatchEngine(DispatchConfig(packages=1, trucks=1))
        result = engine.run([package("A", 5.0, 100.0)], [TruckLoadEvent("T1", 25.0, 5)])
        assert result.metrics.average_wait == 20.0
        assert result.metrics.max_wait == 20.0

    def test_wait_time_is_never_negative(self) -> None:
        engine = DispatchEngine(DispatchConfig(packages=1, trucks=1))
        result = engine.run([package("A", 50.0, 100.0)], [TruckLoadEvent("T1", 10.0, 5)])
        assert result.metrics.average_wait == 0.0

    def test_late_packages_are_counted(self) -> None:
        engine = DispatchEngine(DispatchConfig(packages=1, trucks=1))
        result = engine.run([package("A", 0.0, 10.0)], [TruckLoadEvent("T1", 50.0, 5)])
        assert result.metrics.packages_late == 1
        assert result.metrics.on_time_ratio == 0.0

    def test_on_time_packages_are_counted(self) -> None:
        engine = DispatchEngine(DispatchConfig(packages=1, trucks=1))
        result = engine.run([package("A", 0.0, 100.0)], [TruckLoadEvent("T1", 50.0, 5)])
        assert result.metrics.packages_late == 0
        assert result.metrics.on_time_ratio == 1.0

    def test_peak_queue_depth_is_tracked(self) -> None:
        engine = DispatchEngine(DispatchConfig(packages=4, trucks=1))
        result = engine.run(
            [package(f"P{index}", float(index), 100.0) for index in range(4)],
            [TruckLoadEvent("T1", 100.0, 10)],
        )
        assert result.metrics.peak_queue_depth == 4

    def test_arrivals_are_processed_before_a_truck_at_the_same_time(self) -> None:
        engine = DispatchEngine(DispatchConfig(packages=1, trucks=1))
        result = engine.run([package("A", 10.0, 100.0)], [TruckLoadEvent("T1", 10.0, 5)])
        assert result.metrics.packages_dispatched == 1
        assert result.metrics.average_wait == 0.0

    def test_input_order_does_not_matter(self) -> None:
        packages = [package("A", 30.0, 100.0), package("B", 10.0, 100.0)]
        trucks = [TruckLoadEvent("T1", 20.0, 5)]
        first = DispatchEngine(DispatchConfig()).run(packages, trucks)
        second = DispatchEngine(DispatchConfig()).run(list(reversed(packages)), trucks)
        assert first.metrics.packages_dispatched == second.metrics.packages_dispatched
        assert first.metrics.average_wait == second.metrics.average_wait

    def test_max_packages_per_truck_caps_the_load(self) -> None:
        config = DispatchConfig(packages=10, trucks=1, max_packages_per_truck=3)
        engine = DispatchEngine(config)
        result = engine.run(
            [package(f"P{index}", 0.0, 100.0) for index in range(10)],
            [TruckLoadEvent("T1", 10.0, 100)],
        )
        assert len(result.plans[0].packages) == 3

    def test_oversized_package_does_not_block_the_queue(self) -> None:
        config = DispatchConfig(packages=2, trucks=1, max_packages_per_truck=10)
        engine = DispatchEngine(config)
        engine.enqueue(package("BIG", 0.0, 100.0, size=50))
        engine.enqueue(package("SMALL", 0.0, 100.0, size=1))
        plan = engine.dispatch_truck(TruckLoadEvent("T1", 10.0, 100))
        assert [pkg.package_id for pkg in plan.packages] == ["SMALL"]
        assert engine.queue_depth == 1

    def test_engine_exposes_its_configuration(self) -> None:
        config = DispatchConfig(packages=1, trucks=1)
        engine = DispatchEngine(config)
        assert engine.config is config
        assert engine.policy.name == config.policy

    def test_a_custom_policy_can_be_injected(self) -> None:
        engine = DispatchEngine(DispatchConfig(packages=1, trucks=1), SlaUrgencyPolicy())
        assert isinstance(engine.policy, SlaUrgencyPolicy)

    def test_run_resets_the_queue(self) -> None:
        engine = DispatchEngine(DispatchConfig(packages=1, trucks=1))
        engine.run([package("A", 0.0, 100.0)], [TruckLoadEvent("T1", 1.0, 5)])
        assert engine.queue_depth == 0


class TestDispatchOrdering:
    """The policy actually drives the dispatch order."""

    def test_express_packages_are_loaded_first(self) -> None:
        config = DispatchConfig(packages=3, trucks=1, policy="express_first")
        engine = DispatchEngine(config)
        result = engine.run(
            [
                package("ECON", 0.0, 500.0, PriorityClass.ECONOMY),
                package("EXP", 0.0, 500.0, PriorityClass.EXPRESS),
                package("STD", 0.0, 500.0, PriorityClass.STANDARD),
            ],
            [TruckLoadEvent("T1", 10.0, 10)],
        )
        assert [pkg.package_id for pkg in result.plans[0].packages] == [
            "EXP",
            "STD",
            "ECON",
        ]

    def test_sla_policy_dispatches_the_tightest_deadline_first(self) -> None:
        config = DispatchConfig(packages=2, trucks=1, policy="sla_urgency")
        engine = DispatchEngine(config)
        result = engine.run(
            [package("LOOSE", 0.0, 900.0), package("TIGHT", 0.0, 50.0)],
            [TruckLoadEvent("T1", 10.0, 10)],
        )
        assert result.plans[0].packages[0].package_id == "TIGHT"

    def test_smallest_first_policy_dispatches_the_small_package_first(self) -> None:
        config = DispatchConfig(packages=2, trucks=1, policy="smallest_first")
        engine = DispatchEngine(config)
        result = engine.run(
            [package("BIG", 0.0, 500.0, size=3), package("SMALL", 0.0, 500.0, size=1)],
            [TruckLoadEvent("T1", 10.0, 10)],
        )
        assert result.plans[0].packages[0].package_id == "SMALL"


class TestSimulationRunner:
    """The composition root used by the CLI and the tests."""

    def test_runner_produces_metrics(self) -> None:
        config = DispatchConfig(packages=100, trucks=20)
        result = SimulationRunner(config).run()
        assert result.metrics.packages_arrived == 100
        assert result.metrics.packages_dispatched > 0
        assert result.config is config

    def test_runner_is_deterministic(self) -> None:
        config = DispatchConfig(packages=200, trucks=40)
        first = SimulationRunner(config).run()
        second = SimulationRunner(config).run()
        assert first.metrics == second.metrics

    def test_runner_with_no_packages(self) -> None:
        result = SimulationRunner(DispatchConfig(packages=0, trucks=5)).run()
        assert result.metrics.packages_arrived == 0
        assert result.metrics.packages_dispatched == 0

    def test_runner_accepts_a_custom_source(self) -> None:
        class EmptySource:
            def packages(self, config: DispatchConfig) -> list[PackageRequest]:
                return []

            def trucks(self, config: DispatchConfig) -> list[TruckLoadEvent]:
                return []

        runner = SimulationRunner(DispatchConfig(), source=EmptySource())
        assert isinstance(runner.engine, DispatchEngine)
        assert runner.run().metrics.packages_arrived == 0

    def test_the_default_source_satisfies_the_port(self) -> None:
        assert isinstance(SyntheticWorkloadSource(), WorkloadSource)


class TestSyntheticWorkloadSource:
    """The deterministic workload generator."""

    def test_package_count_matches_the_configuration(self) -> None:
        config = DispatchConfig(packages=25)
        packages = SyntheticWorkloadSource().packages(config)
        assert len(packages) == 25

    def test_truck_count_matches_the_configuration(self) -> None:
        config = DispatchConfig(trucks=7)
        trucks = SyntheticWorkloadSource().trucks(config)
        assert len(trucks) == 7

    def test_zero_produces_empty_collections(self) -> None:
        source = SyntheticWorkloadSource()
        config = DispatchConfig(packages=0, trucks=0)
        assert source.packages(config) == []
        assert source.trucks(config) == []

    def test_arrivals_are_sorted_by_time(self) -> None:
        packages = SyntheticWorkloadSource().packages(DispatchConfig(packages=100))
        times = [pkg.arrival_time for pkg in packages]
        assert times == sorted(times)

    def test_trucks_are_sorted_by_ready_time(self) -> None:
        trucks = SyntheticWorkloadSource().trucks(DispatchConfig(trucks=50))
        times = [truck.ready_time for truck in trucks]
        assert times == sorted(times)

    def test_the_source_is_deterministic(self) -> None:
        config = DispatchConfig(packages=50)
        first = SyntheticWorkloadSource().packages(config)
        second = SyntheticWorkloadSource().packages(config)
        assert first == second

    def test_different_seeds_produce_different_workloads(self) -> None:
        first = SyntheticWorkloadSource().packages(DispatchConfig(packages=50, seed=1))
        second = SyntheticWorkloadSource().packages(DispatchConfig(packages=50, seed=2))
        assert first != second

    def test_arrivals_stay_inside_the_window(self) -> None:
        config = DispatchConfig(packages=100, arrival_window=500.0)
        packages = SyntheticWorkloadSource().packages(config)
        assert all(0.0 <= pkg.arrival_time <= 500.0 for pkg in packages)

    def test_sla_window_is_respected(self) -> None:
        config = DispatchConfig(packages=100, sla_min=100.0, sla_max=200.0)
        packages = SyntheticWorkloadSource().packages(config)
        for pkg in packages:
            slack = pkg.sla_deadline - pkg.arrival_time
            assert 100.0 - 1e-9 <= slack <= 200.0 + 1e-9

    def test_truck_capacity_is_respected(self) -> None:
        config = DispatchConfig(
            trucks=50, truck_capacity_min=10, truck_capacity_max=20
        )
        trucks = SyntheticWorkloadSource().trucks(config)
        assert all(10 <= truck.capacity <= 20 for truck in trucks)

    def test_package_ids_are_unique(self) -> None:
        packages = SyntheticWorkloadSource().packages(DispatchConfig(packages=100))
        assert len({pkg.package_id for pkg in packages}) == 100

    def test_build_package_is_deterministic(self) -> None:
        config = DispatchConfig()
        first = build_package(3, 10.0, config)
        second = build_package(3, 10.0, config)
        assert first == second

    def test_build_truck_is_deterministic(self) -> None:
        config = DispatchConfig()
        first = build_truck(3, 10.0, config)
        second = build_truck(3, 10.0, config)
        assert first == second

    def test_build_package_uses_a_valid_size(self) -> None:
        config = DispatchConfig()
        for index in range(50):
            assert 1 <= build_package(index, 0.0, config).size <= 3


class TestMetricsDataclass:
    """The metrics value object."""

    def test_metrics_are_immutable(self) -> None:
        metrics = DispatchMetrics(0, 0, 0, 0, 0.0, 0.0, 0.0, 0, 0, 0)
        with pytest.raises(AttributeError):
            metrics.packages_dispatched = 5  # type: ignore[misc]

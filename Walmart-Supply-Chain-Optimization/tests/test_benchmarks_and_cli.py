"""Unit tests for the benchmark harness and the command line interface."""

from __future__ import annotations

import json

import pytest

from walmart_logistics.cli import build_parser, main, render_metrics
from walmart_logistics.config import DispatchConfig
from walmart_logistics.data_structures.kary_heap import KaryHeap
from walmart_logistics.infrastructure.benchmarks import (
    BenchmarkResult,
    benchmark_mixed_workload,
    benchmark_scaling,
    compare_implementations,
    heapq_builder,
    kary_builder,
    measure_memory,
)


class TestBenchmarkHarness:
    """The measurement helpers must be correct, not just fast."""

    def test_result_computes_the_throughput(self) -> None:
        result = BenchmarkResult(
            name="x", arity=2, size=10, operations=1000, seconds=2.0, payload_bytes=100
        )
        assert result.ops_per_second == 500.0
        assert result.bytes_per_element == 10.0

    def test_result_handles_a_zero_duration(self) -> None:
        result = BenchmarkResult(
            name="x", arity=2, size=0, operations=0, seconds=0.0, payload_bytes=0
        )
        assert result.ops_per_second == float("inf")
        assert result.bytes_per_element == 0.0

    def test_heapq_builder_returns_an_empty_list(self) -> None:
        assert heapq_builder()( [1, 2, 3]) == []

    def test_kary_builder_returns_an_empty_heap(self) -> None:
        heap = kary_builder(2)([1, 2, 3])
        assert isinstance(heap, KaryHeap)
        assert heap.is_empty

    def test_measure_memory_of_a_heap(self) -> None:
        heap = KaryHeap[int](2, capacity=64)
        assert measure_memory(heap) > 0

    def test_measure_memory_of_a_list(self) -> None:
        assert measure_memory([1, 2, 3]) > 0

    def test_mixed_workload_reports_the_operation_count(self) -> None:
        values = [5, 3, 9, 1]
        result = benchmark_mixed_workload(values, kary_builder(2), "kary-4", arity=4)
        assert result.operations == 2 * len(values)
        assert result.size == len(values)
        assert result.arity == 4
        assert result.seconds >= 0.0

    def test_mixed_workload_measures_a_full_container(self) -> None:
        values = [5, 3, 9, 1]
        heap_result = benchmark_mixed_workload(values, kary_builder(2), "kary-4", arity=4)
        heapq_result = benchmark_mixed_workload(values, heapq_builder(), "heapq", arity=2)
        assert heap_result.payload_bytes > 0
        assert heapq_result.payload_bytes > 0

    def test_scaling_returns_one_row_per_size(self) -> None:
        rows = benchmark_scaling((100, 200), arity_exponent=2)
        assert len(rows) == 2
        for size, per_op, per_second in rows:
            assert size in (100, 200)
            assert per_op >= 0.0
            assert per_second > 0.0

    def test_scaling_is_deterministic(self) -> None:
        first = benchmark_scaling((100,), arity_exponent=2, seed=7)
        second = benchmark_scaling((100,), arity_exponent=2, seed=7)
        assert first[0][0] == second[0][0]

    def test_compare_implementations_covers_every_combination(self) -> None:
        results = compare_implementations(sizes=(50,), arity_exponents=(1, 3))
        names = {result.name for result in results}
        assert names == {"heapq", "kary-2", "kary-8"}

    @pytest.mark.slow
    def test_full_comparison_matrix_runs(self) -> None:
        results = compare_implementations(sizes=(500,), arity_exponents=(1, 2, 3))
        assert len(results) == 4

    def test_dispatch_simulation_benchmark_runs(self) -> None:
        from walmart_logistics.infrastructure.benchmarks import (
            benchmark_dispatch_simulation,
        )

        rows = benchmark_dispatch_simulation(
            packages=200, trucks=20, arity_exponents=(1, 3), seed=7
        )
        assert len(rows) == 2
        for arity, seconds, dispatched in rows:
            assert arity in (2, 8)
            assert seconds >= 0.0
            assert dispatched > 0


class TestCommandLineInterface:
    """The CLI contract."""

    def test_parser_defaults(self) -> None:
        args = build_parser().parse_args([])
        assert args.packages == 5_000
        assert args.trucks == 250
        assert args.arity_exponent == 3

    def test_parser_accepts_overrides(self) -> None:
        args = build_parser().parse_args(
            ["--packages", "10", "--trucks", "2", "--arity-exponent", "2"]
        )
        assert args.packages == 10
        assert args.trucks == 2
        assert args.arity_exponent == 2

    def test_main_runs_the_simulation(self, capsys: pytest.CaptureFixture[str]) -> None:
        exit_code = main(["--packages", "20", "--trucks", "5"])
        assert exit_code == 0
        assert "WAREHOUSE DISPATCH SIMULATION" in capsys.readouterr().out

    def test_main_emits_json(self, capsys: pytest.CaptureFixture[str]) -> None:
        exit_code = main(["--packages", "20", "--trucks", "5", "--json"])
        assert exit_code == 0
        payload = json.loads(capsys.readouterr().out)
        assert payload["packages_arrived"] == 20

    def test_main_rejects_an_invalid_arity(self, capsys: pytest.CaptureFixture[str]) -> None:
        exit_code = main(["--arity-exponent", "0"])
        assert exit_code == 2
        assert "configuration error" in capsys.readouterr().err

    def test_main_rejects_an_unknown_policy(self, capsys: pytest.CaptureFixture[str]) -> None:
        exit_code = main(["--policy", "nope"])
        assert exit_code == 2
        assert "configuration error" in capsys.readouterr().err

    def test_render_metrics_produces_a_report(self) -> None:
        from walmart_logistics.application.dispatch_engine import SimulationRunner

        result = SimulationRunner(DispatchConfig(packages=10, trucks=2)).run()
        report = render_metrics(result.metrics)
        assert "packages dispatched" in report
        assert "=" * 10 in report

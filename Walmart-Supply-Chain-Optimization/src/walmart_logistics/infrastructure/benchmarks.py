"""Benchmark suite comparing the ``2**k``-ary heap against :mod:`heapq`.

Three dimensions are measured, matching the requirements of the task:

1. **Throughput** — operations per second for a push/pop mixed workload.
2. **Memory footprint** — the bytes retained by a *full* container.
3. **Scaling** — how the per-operation cost grows with ``n``, which is the
   empirical evidence of the ``O(log_d n)`` complexity claim.

Every benchmark is deterministic: the same seed produces the same workload,
so two runs can be compared directly.

Fairness notes
--------------
* Both implementations execute the *same* workload: push every value, then
  pop every value.  The ``heapq`` baseline is a binary heap, so it is
  compared against the ``k = 1`` kary heap and against the wider ones.
* Memory is measured on a **full** container.  Measuring after the drain
  would report an empty list for ``heapq`` and the retained capacity for the
  kary heap, which is not a like-for-like comparison.
* The timed section is preceded by a garbage collection so that a previous
  iteration cannot distort the measurement.
"""

from __future__ import annotations

import gc
import heapq
import random
import time
from collections.abc import Callable, Sequence
from dataclasses import dataclass

from walmart_logistics.data_structures.kary_heap import KaryHeap

__all__ = [
    "BenchmarkResult",
    "benchmark_dispatch_simulation",
    "benchmark_mixed_workload",
    "benchmark_scaling",
    "compare_implementations",
    "heapq_builder",
    "kary_builder",
    "measure_memory",
]


@dataclass(frozen=True, slots=True)
class BenchmarkResult:
    """Outcome of a single benchmark run.

    Attributes:
        name: Name of the implementation under test.
        arity: Arity of the heap (``2`` for the ``heapq`` baseline).
        size: Number of elements in the workload.
        operations: Number of heap operations performed.
        seconds: Wall-clock duration of the measured section.
        payload_bytes: Memory retained by a full container, in bytes.
    """

    name: str
    arity: int
    size: int
    operations: int
    seconds: float
    payload_bytes: int

    @property
    def ops_per_second(self) -> float:
        """Throughput of the measured section, in operations per second."""
        if self.seconds <= 0:
            return float("inf")
        return self.operations / self.seconds

    @property
    def bytes_per_element(self) -> float:
        """Retained memory per element, in bytes."""
        return self.payload_bytes / self.size if self.size else 0.0


def heapq_builder(arity_exponent: int = 1) -> Callable[[Sequence[int]], list[int]]:
    """Return a factory building an **empty** ``heapq`` heap.

    ``arity_exponent`` is accepted so that both implementations can be
    driven through the same harness; ``heapq`` is always a binary heap and
    ignores the exponent.
    """

    def build(values: Sequence[int]) -> list[int]:
        return []

    return build


def kary_builder(arity_exponent: int) -> Callable[[Sequence[int]], KaryHeap[int]]:
    """Return a factory building an **empty** kary heap."""

    def build(values: Sequence[int]) -> KaryHeap[int]:
        return KaryHeap(arity_exponent, capacity=max(len(values), 1))

    return build


def _timed(function: Callable[[], None]) -> float:
    """Run ``function`` and return the elapsed wall-clock time in seconds."""
    gc.collect()
    start = time.perf_counter()
    function()
    return time.perf_counter() - start


def measure_memory(container: object) -> int:
    """Return the retained memory of a **full** ``container`` in bytes.

    For :class:`KaryHeap` the two backing arrays are measured; for a
    ``heapq`` list the list object itself is measured.
    """
    import sys

    if isinstance(container, KaryHeap):
        return container.footprint_bytes()
    return sys.getsizeof(container)


def benchmark_mixed_workload(
    values: Sequence[int],
    builder: Callable[[Sequence[int]], object],
    name: str,
    arity: int = 0,
) -> BenchmarkResult:
    """Measure a push/pop mixed workload.

    The timed section pushes every value and then pops every value.

    Args:
        values: The workload (already shuffled).
        builder: Factory building an empty container.
        name: Name of the implementation.
        arity: Arity of the implementation, for reporting.

    Returns:
        The measured result.
    """
    # Memory is measured on a full container for a like-for-like comparison.
    full = builder(values)
    if isinstance(full, KaryHeap):
        for value in values:
            full.push(value)
    else:
        full_list = full
        assert isinstance(full_list, list)
        for value in values:
            heapq.heappush(full_list, value)
    payload_bytes = measure_memory(full)
    del full

    container = builder(values)

    def workload() -> None:
        if isinstance(container, KaryHeap):
            for value in values:
                container.push(value)
            while container:
                container.pop()
        else:
            heap_list = container
            assert isinstance(heap_list, list)
            for value in values:
                heapq.heappush(heap_list, value)
            while heap_list:
                heapq.heappop(heap_list)

    seconds = _timed(workload)
    operations = 2 * len(values)
    return BenchmarkResult(
        name=name,
        arity=arity,
        size=len(values),
        operations=operations,
        seconds=seconds,
        payload_bytes=payload_bytes,
    )


def benchmark_scaling(
    sizes: Sequence[int],
    arity_exponent: int,
    seed: int = 1337,
) -> list[tuple[int, float, float]]:
    """Measure the per-operation cost for growing heap sizes.

    Args:
        sizes: Heap sizes to measure.
        arity_exponent: ``k`` of the ``2**k``-ary heap.
        seed: Seed of the workload generator.

    Returns:
        A list of ``(size, seconds_per_pop, pops_per_second)`` tuples.
    """
    rng = random.Random(seed)
    results: list[tuple[int, float, float]] = []
    for size in sizes:
        values = [rng.randrange(1 << 30) for _ in range(size)]
        container = KaryHeap.from_iterable(values, arity_exponent=arity_exponent)
        operations = size  # one pop per element

        def workload(target: KaryHeap[int] = container) -> None:
            while target:
                target.pop()

        seconds = _timed(workload)
        per_op = seconds / operations if operations else 0.0
        results.append((size, per_op, (1 / per_op) if per_op else float("inf")))
    return results


def compare_implementations(
    sizes: Sequence[int] = (10_000, 100_000),
    arity_exponents: Sequence[int] = (1, 2, 3, 4),
    seed: int = 20240,
) -> list[BenchmarkResult]:
    """Run the full comparison matrix.

    Args:
        sizes: Workload sizes to measure.
        arity_exponents: ``k`` values of the ``2**k``-ary heap.
        seed: Seed of the workload generator.

    Returns:
        One :class:`BenchmarkResult` per (size, implementation) pair.
    """
    rng = random.Random(seed)
    results: list[BenchmarkResult] = []
    for size in sizes:
        values = [rng.randrange(1 << 30) for _ in range(size)]
        results.append(benchmark_mixed_workload(values, heapq_builder(), "heapq", arity=2))
        for exponent in arity_exponents:
            results.append(
                benchmark_mixed_workload(
                    values,
                    kary_builder(exponent),
                    f"kary-{2 ** exponent}",
                    arity=2**exponent,
                )
            )
    return results


def benchmark_dispatch_simulation(
    packages: int = 50_000,
    trucks: int = 2_500,
    arity_exponents: Sequence[int] = (1, 2, 3, 4),
    seed: int = 20240,
) -> list[tuple[int, float, int]]:
    """Measure the end-to-end dispatch simulation for each arity.

    This is the workload that actually matters for the business case: a
    continuous stream of arrivals and truck dockings, each of which
    triggers a burst of heap operations.

    Args:
        packages: Number of simulated package arrivals.
        trucks: Number of simulated truck loading events.
        arity_exponents: ``k`` values of the ``2**k``-ary heap.
        seed: Seed of the workload generator.

    Returns:
        A list of ``(arity, seconds, packages_dispatched)`` tuples.
    """
    from walmart_logistics.application.dispatch_engine import SimulationRunner
    from walmart_logistics.config import DispatchConfig

    results: list[tuple[int, float, int]] = []
    for exponent in arity_exponents:
        config = DispatchConfig(
            packages=packages,
            trucks=trucks,
            arity_exponent=exponent,
            seed=seed,
        )
        runner = SimulationRunner(config)

        def workload(target: SimulationRunner = runner) -> None:
            target.run()

        seconds = _timed(workload)
        dispatched = runner.run().metrics.packages_dispatched
        results.append((2**exponent, seconds, dispatched))
    return results

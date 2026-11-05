"""Profiling script: produce the reproducible numbers quoted in the README.

Usage::

    python scripts/profile.py --sizes 10000 100000

The script runs the whole measurement matrix several times and reports the
*median* of the repetitions, so the numbers are stable enough to be quoted
in the documentation.
"""

from __future__ import annotations

import argparse
import os
import statistics
import sys
from collections.abc import Sequence

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

from walmart_logistics.infrastructure.benchmarks import (  # noqa: E402
    benchmark_dispatch_simulation,
    benchmark_mixed_workload,
    benchmark_scaling,
    heapq_builder,
    kary_builder,
)


def _median(values: Sequence[float]) -> float:
    return statistics.median(values)


def profile_throughput(
    sizes: Sequence[int],
    arity_exponents: Sequence[int],
    repetitions: int,
    seed: int,
) -> None:
    """Print the median throughput and memory for every implementation."""
    print("=" * 78)
    print(f"  THROUGHPUT (median of {repetitions} runs)")
    print("=" * 78)
    header = (
        f"{'size':>10} {'impl':>12} {'ops/sec':>14} {'vs heapq':>10} "
        f"{'bytes/elem':>11} {'levels':>8}"
    )
    print(header)
    print("-" * len(header))

    import random

    for size in sizes:
        rng = random.Random(seed)
        values = [rng.randrange(1 << 30) for _ in range(size)]
        results = {}
        for name, builder, arity in [
            ("heapq", heapq_builder(), 2),
            *[
                (f"kary-{2 ** exp}", kary_builder(exp), 2**exp)
                for exp in arity_exponents
            ],
        ]:
            runs = [
                benchmark_mixed_workload(values, builder, name, arity=arity)
                for _ in range(repetitions)
            ]
            results[name] = (
                _median([run.ops_per_second for run in runs]),
                runs[0].bytes_per_element,
            )

        baseline = results["heapq"][0]
        for name, (ops, per_element) in results.items():
            arity = 2 if name == "heapq" else int(name.split("-")[1])
            levels = 1.0
            if size > 1:
                levels = len(str(size - 1)) and __import__("math").log2(size) / (
                    __import__("math").log2(arity)
                )
            print(
                f"{size:>10,} {name:>12} {ops:>14,.0f} {ops / baseline:>9.2f}x "
                f"{per_element:>11.1f} {levels:>8.2f}"
            )
    print()


def profile_scaling(sizes: Sequence[int], repetitions: int, seed: int) -> None:
    """Print the per-pop cost curve of the 8-ary heap."""
    print("=" * 78)
    print(f"  SCALING - 8-ary heap (k=3), median of {repetitions} runs")
    print("=" * 78)
    header = f"{'size':>12} {'sec/pop':>14} {'pops/sec':>14} {'log2(n)':>10}"
    print(header)
    print("-" * len(header))
    import math

    for size in sizes:
        runs = [benchmark_scaling((size,), 3, seed)[0][1] for _ in range(repetitions)]
        per_op = _median(runs)
        print(
            f"{size:>12,} {per_op:>14.3e} {1 / per_op:>14,.0f} "
            f"{math.log2(size):>10.2f}"
        )
    print()


def profile_end_to_end(
    packages: int, trucks: int, arity_exponents: Sequence[int], repetitions: int, seed: int
) -> None:
    """Print the end-to-end dispatch simulation timings."""
    print("=" * 78)
    print(f"  END-TO-END dispatch simulation (median of {repetitions} runs)")
    print("=" * 78)
    header = f"{'arity':>8} {'seconds':>12} {'vs arity-2':>12} {'packages':>12}"
    print(header)
    print("-" * len(header))
    baseline = None
    for exponent in arity_exponents:
        runs = [
            benchmark_dispatch_simulation(
                packages=packages, trucks=trucks, arity_exponents=(exponent,), seed=seed
            )[0][1]
            for _ in range(repetitions)
        ]
        seconds = _median(runs)
        dispatched = benchmark_dispatch_simulation(
            packages=packages, trucks=trucks, arity_exponents=(exponent,), seed=seed
        )[0][2]
        if baseline is None:
            baseline = seconds
        print(
            f"{2 ** exponent:>8} {seconds:>12.3f} {baseline / seconds:>11.2f}x "
            f"{dispatched:>12,}"
        )
    print()


def main(argv: list[str] | None = None) -> int:
    """Run the profiling matrix."""
    parser = argparse.ArgumentParser(prog="profile.py", description=__doc__)
    parser.add_argument("--sizes", type=int, nargs="+", default=[10_000, 100_000])
    parser.add_argument("--arities", type=int, nargs="+", default=[1, 2, 3, 4])
    parser.add_argument("--repetitions", type=int, default=3)
    parser.add_argument("--seed", type=int, default=20240)
    parser.add_argument("--packages", type=int, default=50_000)
    parser.add_argument("--trucks", type=int, default=2_500)
    args = parser.parse_args(argv)

    profile_throughput(args.sizes, args.arities, args.repetitions, args.seed)
    profile_scaling(args.sizes, args.repetitions, args.seed)
    profile_end_to_end(
        args.packages, args.trucks, args.arities, args.repetitions, args.seed
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

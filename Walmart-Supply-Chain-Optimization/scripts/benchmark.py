"""Benchmark script: compare the kary heap against :mod:`heapq`.

Usage::

    python scripts/benchmark.py --sizes 10000 100000 --arities 1 2 3 4

The output has three sections: the throughput matrix, the memory footprint
and the scaling curve.
"""

from __future__ import annotations

import argparse
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

from walmart_logistics.infrastructure.benchmarks import (  # noqa: E402
    benchmark_dispatch_simulation,
    benchmark_scaling,
    compare_implementations,
)


def _parse_sizes(raw: str) -> int:
    """Parse one size argument into an integer."""
    return int(raw)


def main(argv: list[str] | None = None) -> int:
    """Run the benchmark matrix and print the report."""
    parser = argparse.ArgumentParser(prog="benchmark.py", description=__doc__)
    parser.add_argument("--sizes", type=_parse_sizes, nargs="+", default=[10_000, 100_000])
    parser.add_argument("--arities", type=_parse_sizes, nargs="+", default=[1, 2, 3, 4])
    parser.add_argument("--seed", type=int, default=20240)
    args = parser.parse_args(argv)

    print("=" * 78)
    print("  THROUGHPUT AND MEMORY - kary heap vs heapq")
    print("=" * 78)
    header = f"{'size':>10} {'implementation':>16} {'ops/sec':>14} {'bytes/elem':>12}"
    print(header)
    print("-" * len(header))
    for result in compare_implementations(args.sizes, args.arities, args.seed):
        print(
            f"{result.size:>10,} {result.name:>16} "
            f"{result.ops_per_second:>14,.0f} {result.bytes_per_element:>12.1f}"
        )

    print()
    print("=" * 78)
    print("  SCALING - per-pop cost for the 8-ary heap (k=3)")
    print("=" * 78)
    header = f"{'size':>12} {'sec/pop':>14} {'pops/sec':>14}"
    print(header)
    print("-" * len(header))
    for size, per_op, per_second in benchmark_scaling(args.sizes, 3, args.seed):
        print(f"{size:>12,} {per_op:>14.3e} {per_second:>14,.0f}")

    print()
    print("=" * 78)
    print("  END-TO-END - dispatch simulation per heap arity")
    print("=" * 78)
    header = f"{'arity':>8} {'seconds':>12} {'packages':>12}"
    print(header)
    print("-" * len(header))
    for arity, seconds, dispatched in benchmark_dispatch_simulation(
        packages=max(args.sizes),
        trucks=max(50, max(args.sizes) // 20),
        arity_exponents=args.arities,
        seed=args.seed,
    ):
        print(f"{arity:>8} {seconds:>12.3f} {dispatched:>12,}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

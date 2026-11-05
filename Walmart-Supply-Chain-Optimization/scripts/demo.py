"""Demonstration script: run the dispatch simulation and print a report.

Usage::

    python scripts/demo.py --packages 5000 --trucks 250 --arity-exponent 3
"""

from __future__ import annotations

import argparse
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

from walmart_logistics.application.dispatch_engine import SimulationRunner  # noqa: E402
from walmart_logistics.cli import render_metrics  # noqa: E402
from walmart_logistics.config import DispatchConfig  # noqa: E402
from walmart_logistics.domain.entities import build_policy  # noqa: E402


def main(argv: list[str] | None = None) -> int:
    """Run the demo and print the KPI report."""
    parser = argparse.ArgumentParser(prog="demo.py", description=__doc__)
    parser.add_argument("--packages", type=int, default=5_000)
    parser.add_argument("--trucks", type=int, default=250)
    parser.add_argument("--arity-exponent", type=int, default=3)
    parser.add_argument("--policy", default="express_first")
    parser.add_argument("--seed", type=int, default=20240)
    args = parser.parse_args(argv)

    config = DispatchConfig(
        packages=args.packages,
        trucks=args.trucks,
        arity_exponent=args.arity_exponent,
        policy=args.policy,
        seed=args.seed,
    )
    build_policy(args.policy)

    result = SimulationRunner(config).run()
    print(render_metrics(result.metrics))
    print(f"  heap arity             : {config.arity} (k={config.arity_exponent})")
    print(f"  dispatch policy        : {args.policy}")
    print()
    for plan in result.plans[:5]:
        ids = ", ".join(package.package_id for package in plan.packages[:6])
        more = "" if len(plan.packages) <= 6 else ", ..."
        print(f"  {plan.truck_id}: {len(plan.packages):>3} packages -> {ids}{more}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

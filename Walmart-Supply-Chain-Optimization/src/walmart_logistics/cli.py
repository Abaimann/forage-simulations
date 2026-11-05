"""Command line interface of the Walmart logistics simulation."""

from __future__ import annotations

import argparse
import json
import sys
from dataclasses import asdict

from walmart_logistics.application.dispatch_engine import SimulationRunner
from walmart_logistics.config import DispatchConfig
from walmart_logistics.domain.entities import build_policy

__all__ = ["build_parser", "main", "render_metrics"]


def build_parser() -> argparse.ArgumentParser:
    """Build the argument parser of the CLI."""
    parser = argparse.ArgumentParser(
        prog="walmart-logistics",
        description="Run the warehouse dispatch simulation on a 2**k-ary priority queue.",
    )
    parser.add_argument("--packages", type=int, default=5_000, help="number of arrivals")
    parser.add_argument("--trucks", type=int, default=250, help="number of truck events")
    parser.add_argument(
        "--arity-exponent",
        type=int,
        default=3,
        help="k of the 2**k-ary heap (k=1 -> binary, k=3 -> 8-ary)",
    )
    parser.add_argument(
        "--policy",
        default="express_first",
        help="dispatch policy: express_first, sla_urgency or smallest_first",
    )
    parser.add_argument("--seed", type=int, default=20240, help="workload seed")
    parser.add_argument("--json", action="store_true", help="emit the metrics as JSON")
    return parser


def render_metrics(metrics: object) -> str:
    """Render the metrics of a simulation as a human readable block."""
    lines = [
        "=" * 62,
        "  WAREHOUSE DISPATCH SIMULATION - KPI REPORT",
        "=" * 62,
        f"  packages arrived       : {metrics.packages_arrived:>12,}",  # type: ignore[attr-defined]
        f"  packages dispatched    : {metrics.packages_dispatched:>12,}",  # type: ignore[attr-defined]
        f"  packages pending       : {metrics.packages_pending:>12,}",  # type: ignore[attr-defined]
        f"  packages late          : {metrics.packages_late:>12,}",  # type: ignore[attr-defined]
        f"  on-time ratio          : {metrics.on_time_ratio:>12.2%}",  # type: ignore[attr-defined]
        f"  average wait (s)       : {metrics.average_wait:>12.2f}",  # type: ignore[attr-defined]
        f"  maximum wait (s)       : {metrics.max_wait:>12.2f}",  # type: ignore[attr-defined]
        f"  trucks used            : {metrics.trucks_used:>12,}",  # type: ignore[attr-defined]
        f"  peak queue depth       : {metrics.peak_queue_depth:>12,}",  # type: ignore[attr-defined]
        f"  loading slots consumed : {metrics.total_capacity_used:>12,}",  # type: ignore[attr-defined]
        "=" * 62,
    ]
    return "\n".join(lines)


def main(argv: list[str] | None = None) -> int:
    """Run the simulation and print the report."""
    args = build_parser().parse_args(argv)
    try:
        config = DispatchConfig(
            packages=args.packages,
            trucks=args.trucks,
            arity_exponent=args.arity_exponent,
            policy=args.policy,
            seed=args.seed,
        )
        build_policy(args.policy)
    except ValueError as exc:
        print(f"configuration error: {exc}", file=sys.stderr)
        return 2

    result = SimulationRunner(config).run()
    if args.json:
        print(json.dumps(asdict(result.metrics), indent=2, sort_keys=True))
    else:
        print(render_metrics(result.metrics))
    return 0


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())

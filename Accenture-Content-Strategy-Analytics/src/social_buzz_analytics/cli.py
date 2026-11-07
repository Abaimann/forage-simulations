"""Command line interface of the Social Buzz engagement analytics pipeline.

Examples::

    # Full run on the sample dataset, writing the summaries to data/processed
    python -m social_buzz_analytics --data-dir data/raw --output-dir data/processed

    # Custom ranking size and JSON output on stdout
    python -m social_buzz_analytics --top-n 10 --json

    # Only print the executive leaderboard, write nothing
    python -m social_buzz_analytics --dry-run
"""

from __future__ import annotations

import argparse
import json
import sys
from collections.abc import Sequence
from pathlib import Path
from typing import Any

from .application.pipeline import AnalyticsPipeline, PipelineConfig, PipelineResult
from .domain.exceptions import AnalyticsError
from .infrastructure.csv_adapters import CsvDatasetReader, CsvReportWriter

__all__ = ["build_parser", "main", "render_report"]

EXIT_OK = 0
EXIT_ERROR = 1


def build_parser() -> argparse.ArgumentParser:
    """Build the argument parser of the CLI."""
    parser = argparse.ArgumentParser(
        prog="social-buzz-analytics",
        description=(
            "Run the Social Buzz content engagement & sentiment analytics pipeline "
            "over the seven raw datasets."
        ),
    )
    parser.add_argument(
        "--data-dir",
        type=Path,
        default=Path("data/raw"),
        help="directory holding the raw CSV datasets (default: data/raw)",
    )
    parser.add_argument(
        "--output-dir",
        type=Path,
        default=Path("data/processed"),
        help="directory receiving the analytical summaries (default: data/processed)",
    )
    parser.add_argument(
        "--top-n",
        type=int,
        default=5,
        help="number of segments kept in the executive leaderboard (default: 5)",
    )
    parser.add_argument(
        "--max-rejection-rate",
        type=float,
        default=0.95,
        help="maximum share of rows a dataset may lose before it is rejected (default: 0.95)",
    )
    parser.add_argument(
        "--weight-reaction",
        type=float,
        default=0.30,
        help="weight of the reaction volume in the composite score",
    )
    parser.add_argument(
        "--weight-reach",
        type=float,
        default=0.20,
        help="weight of the unique reach in the composite score",
    )
    parser.add_argument(
        "--weight-interaction",
        type=float,
        default=0.25,
        help="weight of the interaction rate in the composite score",
    )
    parser.add_argument(
        "--weight-amplification",
        type=float,
        default=0.15,
        help="weight of the share volume in the composite score",
    )
    parser.add_argument(
        "--weight-sentiment",
        type=float,
        default=0.10,
        help="weight of the sentiment polarity in the composite score",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="compute the analytics without writing any file",
    )
    parser.add_argument(
        "--no-cleaned-datasets",
        action="store_true",
        help="do not export the cleaned datasets, only the analytical summaries",
    )
    parser.add_argument(
        "--json",
        action="store_true",
        help="print the executive summary as JSON on stdout",
    )
    return parser


def render_report(result: PipelineResult) -> str:
    """Render the executive leaderboard as a human readable block."""
    lines: list[str] = []
    lines.append("=" * 78)
    lines.append("  SOCIAL BUZZ - CONTENT ENGAGEMENT & SENTIMENT LEADERBOARD")
    lines.append("=" * 78)
    header = (
        f"  {'#':>2}  {'CATEGORY':<16} {'SCORE':>9} {'RATE%':>8} "
        f"{'SENT':>7} {'REACT':>9} {'VIEWS':>10}"
    )
    lines.append(header)
    lines.append("-" * 78)
    for segment in result.top_segments:
        lines.append(
            f"  {segment.rank:>2}  {segment.category:<16} "
            f"{segment.engagement_score:>9.4f} {segment.engagement_rate:>8.2f} "
            f"{segment.sentiment_score:>7.3f} {segment.reactions:>9,} {segment.views:>10,}"
        )
    lines.append("-" * 78)
    lines.append("  DATA QUALITY")
    for stats in result.cleaning_stats:
        lines.append(
            f"    {stats.dataset:<16} read {stats.rows_read:>9,}  "
            f"accepted {stats.rows_accepted:>9,}  rejected {stats.rows_rejected:>7,}"
        )
    lines.append("=" * 78)
    return "\n".join(lines)


def _build_config(args: argparse.Namespace) -> PipelineConfig:
    """Build the pipeline configuration from the parsed arguments."""
    return PipelineConfig(
        data_dir=args.data_dir,
        output_dir=args.output_dir,
        top_n=args.top_n,
        max_rejection_rate=args.max_rejection_rate,
        reaction_weight=args.weight_reaction,
        reach_weight=args.weight_reach,
        interaction_weight=args.weight_interaction,
        amplification_weight=args.weight_amplification,
        sentiment_weight=args.weight_sentiment,
        write_cleaned_datasets=not args.no_cleaned_datasets,
    )


def main(argv: Sequence[str] | None = None) -> int:
    """Run the pipeline and print the report.

    Returns
    -------
    int
        ``0`` on success, ``1`` when the pipeline raised an analytics error.
    """
    args = build_parser().parse_args(argv)
    try:
        config = _build_config(args)
        writer = None if args.dry_run else CsvReportWriter(config.output_dir)
        pipeline = AnalyticsPipeline(
            config=config,
            reader=CsvDatasetReader(),
            writer=writer,
        )
        result = pipeline.run()
    except AnalyticsError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return EXIT_ERROR
    except OSError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return EXIT_ERROR

    if args.json:
        payload: dict[str, Any] = result.as_dict()
        print(json.dumps(payload, indent=2, default=str))
    else:
        print(render_report(result))
        if result.artifacts:
            print("  ARTIFACTS")
            for name, path in sorted(result.artifacts.items()):
                print(f"    {name:<26} {path}")
            print("=" * 78)
    return EXIT_OK


if __name__ == "__main__":
    raise SystemExit(main())

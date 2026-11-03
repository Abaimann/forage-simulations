"""Command-line interface for the telemetry ingestion pipeline.

Examples
--------
Ingest a directory of mixed-format files::

    iiot-ingest --input ./data --output ./out/telemetry.jsonl

Ingest a single CSV with custom analytics parameters::

    iiot-ingest -i line3.csv -o out.jsonl --sigma 2.5 --baseline-window 100
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Sequence

from .application.pipeline import IngestionPipeline
from .application.ports import IngestionSettings, SinkConfig, SourceConfig
from .domain.exceptions import TelemetryError

#: File extensions picked up when a directory is supplied as ``--input``.
_SUPPORTED_SUFFIXES: tuple[str, ...] = (".json", ".jsonl", ".ndjson", ".csv", ".tsv")


def build_parser() -> argparse.ArgumentParser:
    """Construct the CLI argument parser."""
    parser = argparse.ArgumentParser(
        prog="iiot-ingest",
        description="Daikibo Industrials IIoT telemetry ingestion pipeline.",
    )
    parser.add_argument(
        "-i",
        "--input",
        required=True,
        type=Path,
        help="Input file or directory containing telemetry payloads.",
    )
    parser.add_argument(
        "-o",
        "--output",
        type=Path,
        help="Output base path. Artefacts are written as <name>_readings.jsonl, "
        "<name>_anomalies.jsonl, <name>_rejected.jsonl and <name>_report.jsonl.",
    )
    parser.add_argument(
        "--format",
        choices=("auto", "json", "jsonl", "csv"),
        default="auto",
        help="Payload format of the input (default: auto-detect).",
    )
    parser.add_argument(
        "--output-format",
        choices=("jsonl", "json", "csv"),
        default="jsonl",
        help="Format of the written artefacts (default: jsonl).",
    )
    parser.add_argument(
        "--sigma",
        type=float,
        default=3.0,
        help="Sigma threshold for anomaly detection (default: 3.0).",
    )
    parser.add_argument(
        "--baseline-window",
        type=int,
        default=50,
        help="Number of samples used for the rolling baseline (default: 50).",
    )
    parser.add_argument(
        "--min-baseline-samples",
        type=int,
        default=10,
        help="Minimum baseline samples before detection activates (default: 10).",
    )
    parser.add_argument(
        "--moving-average-window",
        type=int,
        default=5,
        help="Trailing moving-average window (default: 5).",
    )
    parser.add_argument(
        "--expected-interval",
        type=float,
        default=60.0,
        help="Expected sampling interval in seconds, used for dropout detection (default: 60).",
    )
    parser.add_argument(
        "--no-dedupe",
        action="store_true",
        help="Disable duplicate-record removal.",
    )
    parser.add_argument(
        "--print-report",
        action="store_true",
        help="Print the run report to stdout as JSON.",
    )
    return parser


def _collect_sources(input_path: Path, fmt: str) -> list[SourceConfig]:
    """Resolve the input path into a list of source configurations."""
    if input_path.is_dir():
        files = sorted(
            p for p in input_path.rglob("*") if p.is_file() and p.suffix.lower() in _SUPPORTED_SUFFIXES
        )
    elif input_path.is_file():
        files = [input_path]
    else:
        raise TelemetryError(f"input path does not exist: {input_path}")
    return [SourceConfig(path=f, format=fmt) for f in files]


def main(argv: Sequence[str] | None = None) -> int:
    """CLI entry point. Returns the process exit code."""
    args = build_parser().parse_args(argv)

    try:
        sources = _collect_sources(args.input, args.format)
    except TelemetryError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2

    if not sources:
        print(f"error: no readable input files found under {args.input}", file=sys.stderr)
        return 2

    settings = IngestionSettings(
        moving_average_window=args.moving_average_window,
        sigma_threshold=args.sigma,
        baseline_window=args.baseline_window,
        min_baseline_samples=args.min_baseline_samples,
        expected_interval_seconds=args.expected_interval,
        dedupe=not args.no_dedupe,
        sources=tuple(sources),
    )

    pipeline = IngestionPipeline(settings=settings)
    result = pipeline.run()

    if args.output:
        from .adapters.sinks.file_sink import FileTelemetrySink

        sink = FileTelemetrySink(SinkConfig(path=args.output, format=args.output_format))
        sink.write_readings(result.readings)
        sink.write_anomalies(result.anomalies)
        sink.write_rejected(result.rejected)
        sink.write_report(result.report)

    if args.print_report or not args.output:
        print(json.dumps(result.report.to_dict(), indent=2, default=str))

    return 0


if __name__ == "__main__":  # pragma: no cover - exercised through the console script
    raise SystemExit(main())

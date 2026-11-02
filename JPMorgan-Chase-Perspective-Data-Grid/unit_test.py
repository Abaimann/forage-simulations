"""Standalone unit-test entry point for the J.P. Morgan Perspective data grid.

This module is a thin convenience wrapper around the pytest suite in
``tests/``.  It exists so that the whole verification can be executed with a
single command that works on every platform::

    python unit_test.py                # run everything
    python unit_test.py --verbose      # per-test output
    python unit_test.py --coverage     # with a branch-coverage report
    python unit_test.py -k aggregator  # only the tests matching a pattern

The canonical test files live in ``tests/``:

======================================  ==========================================
``tests/test_models.py``               validation, serialisation, band semantics
``tests/test_thresholds.py``           rolling statistics and the alert band
``tests/test_aggregator.py``           the aggregation engine
``tests/test_feed.py``                 mock generator and the TCP transport
``tests/test_pipeline.py``             pipeline, sinks, throughput and latency
``tests/test_perspective_sink.py``     the live Perspective table
``tests/test_dashboard.py``            the browser dashboard
``tests/test_cli.py``                  the command line interface
======================================  ==========================================
"""

from __future__ import annotations

import argparse
import os
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent
TESTS = ROOT / "tests"
SRC = ROOT / "src"


def _ensure_import_path() -> None:
    """Make the ``src`` layout importable without installing the package."""
    path = str(SRC)
    if path not in sys.path:
        sys.path.insert(0, path)
    env_path = os.environ.get("PYTHONPATH", "")
    if path not in env_path.split(os.pathsep):
        os.environ["PYTHONPATH"] = (
            f"{path}{os.pathsep}{env_path}" if env_path else path
        )


def build_parser() -> argparse.ArgumentParser:
    """Build the argument parser of the standalone runner."""
    parser = argparse.ArgumentParser(
        prog="unit_test.py",
        description="Run the unit test suite of the Perspective data grid.",
    )
    parser.add_argument(
        "-v", "--verbose", action="store_true", help="print one line per test"
    )
    parser.add_argument(
        "-k",
        "--keyword",
        default=None,
        help="only run the tests whose name matches this expression",
    )
    parser.add_argument(
        "--coverage",
        action="store_true",
        help="measure branch coverage of the src/ package",
    )
    parser.add_argument(
        "--no-skip-slow",
        action="store_true",
        help="also run the throughput budgets while coverage is attached",
    )
    parser.add_argument(
        "--stop-on-failure",
        action="store_true",
        help="abort the run at the first failing test",
    )
    return parser


def main(argv: list[str] | None = None) -> int:
    """Run the test suite and return the process exit code."""
    args = build_parser().parse_args(argv)
    _ensure_import_path()

    command = [sys.executable, "-m", "pytest", str(TESTS)]
    if args.verbose:
        command.append("-v")
    if args.keyword:
        command += ["-k", args.keyword]
    if args.stop_on_failure:
        command.append("-x")
    if args.coverage:
        command += [
            "--cov=src/jpm_perspective_grid",
            "--cov-branch",
            "--cov-report=term-missing",
        ]
        if not args.no_skip_slow:
            # The throughput budgets are not meaningful under a tracer.
            os.environ["COVERAGE_RUN"] = "1"

    print("running:", " ".join(command), flush=True)
    return subprocess.call(command, cwd=str(ROOT))


if __name__ == "__main__":
    raise SystemExit(main())

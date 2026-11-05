"""Standalone unit-test entry point for the Walmart logistics simulation.

This module is a thin convenience wrapper around the pytest suite in
``tests/``.  It exists so that the whole verification can be executed with
a single command that works on every platform::

    python unit_test.py                # run everything
    python unit_test.py --verbose      # per-test output
    python unit_test.py --coverage     # with a branch-coverage report
    python unit_test.py -k heap        # only the tests matching a pattern

The canonical test files live in ``tests/``:

======================================  ==========================================
``tests/test_kary_heap.py``             the 2**k-ary heap: contract, ordering,
                                        operations, index arithmetic, properties
``tests/test_domain.py``                entities, dispatch policies, configuration
``tests/test_dispatch.py``              the dispatch simulation and the workload
``tests/test_benchmarks_and_cli.py``    the benchmark harness and the CLI
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
        os.environ["PYTHONPATH"] = f"{path}{os.pathsep}{env_path}"


def build_parser() -> argparse.ArgumentParser:
    """Build the argument parser of the standalone runner."""
    parser = argparse.ArgumentParser(
        prog="unit_test.py",
        description="Run the unit test suite of the Walmart logistics simulation.",
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
        help="also run the slow benchmark comparisons",
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
            "--cov=src/walmart_logistics",
            "--cov-branch",
            "--cov-report=term-missing",
        ]
    elif not args.no_skip_slow:
        command.append("-m")
        command.append("not slow")

    print("running:", " ".join(command), flush=True)
    return subprocess.call(command, cwd=str(ROOT))


if __name__ == "__main__":
    raise SystemExit(main())

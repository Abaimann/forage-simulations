"""Command-line entry point for the credential audit pipeline.

Usage examples::

    python -m crypto_audit.cli demo
    python -m crypto_audit.cli audit --json
    python -m crypto_audit.cli benchmark
    python -m crypto_audit.cli collision --algorithm argon2id
"""

from __future__ import annotations

import argparse
import json
import sys
from typing import Sequence

from .application.auditor import CredentialAuditor
from .application.brute_force import BruteForceEstimate, BruteForceTester
from .domain.algorithms import HashAlgorithm
from .domain.policy import HashingPolicy
from .infrastructure.hasher_factory import HasherRegistry
from .infrastructure.repository import InMemoryCredentialRepository
from .infrastructure.sample_data import SAMPLE_PASSWORDS, build_sample_repository

__all__ = ["main", "build_parser"]


def build_parser() -> argparse.ArgumentParser:
    """Build the argument parser for the CLI."""
    parser = argparse.ArgumentParser(
        prog="crypto_audit",
        description=(
            "Credential security audit pipeline: analyse a credential estate, "
            "simulate brute-force resilience and benchmark algorithms."
        ),
    )
    parser.add_argument(
        "--target",
        choices=[a.value for a in HashAlgorithm],
        default=HashAlgorithm.ARGON2ID.value,
        help="Target hashing algorithm for the policy (default: argon2id).",
    )
    sub = parser.add_subparsers(dest="command", required=True)

    demo = sub.add_parser("demo", help="Run the full end-to-end demonstration.")
    demo.add_argument("--json", action="store_true", help="Emit JSON output.")

    audit = sub.add_parser("audit", help="Audit the sample credential estate.")
    audit.add_argument("--json", action="store_true", help="Emit JSON output.")

    benchmark = sub.add_parser(
        "benchmark", help="Estimate attacker effort for each algorithm."
    )
    benchmark.add_argument("--json", action="store_true", help="Emit JSON output.")

    collision = sub.add_parser(
        "collision", help="Check salt/collision resilience of an algorithm."
    )
    collision.add_argument(
        "--algorithm",
        choices=[a.value for a in HashAlgorithm],
        default=HashAlgorithm.ARGON2ID.value,
    )
    collision.add_argument("--samples", type=int, default=64)

    return parser


def _policy(args: argparse.Namespace) -> HashingPolicy:
    return HashingPolicy().with_target(HashAlgorithm(args.target))


def _cmd_audit(args: argparse.Namespace) -> int:
    repository = build_sample_repository()
    auditor = CredentialAuditor(_policy(args))
    report = auditor.audit(repository, candidates=SAMPLE_PASSWORDS)

    if args.json:
        print(json.dumps(report.to_dict(), indent=2))
        return 0 if report.compliant else 1

    print("=" * 78)
    print("CREDENTIAL SECURITY AUDIT REPORT")
    print("=" * 78)
    print(f"Credentials audited : {report.total_credentials}")
    counts = report.severity_counts()
    print(
        "Findings            : "
        f"critical={counts['critical']} high={counts['high']} "
        f"medium={counts['medium']} low={counts['low']} info={counts['info']}"
    )
    print(f"Overall compliance  : {'PASS' if report.compliant else 'FAIL'}")
    print("-" * 78)
    for finding in report.findings:
        print(f"[{finding.severity.value.upper():<8}] {finding.username:<18} {finding.message}")
        if finding.recommendation:
            print(f"{'':>11}-> {finding.recommendation}")
    print("=" * 78)
    return 0 if report.compliant else 1


def _cmd_demo(args: argparse.Namespace) -> int:
    repository = build_sample_repository()
    policy = _policy(args)
    auditor = CredentialAuditor(policy)
    report = auditor.audit(repository, candidates=SAMPLE_PASSWORDS)

    payload = {
        "audit": report.to_dict(),
        "brute_force": {
            algorithm: estimate.to_dict()
            for algorithm, estimate in _benchmarks(policy).items()
        },
    }

    if args.json:
        print(json.dumps(payload, indent=2))
        return 0

    print("=" * 78)
    print("STEP 1 - AUDIT OF THE LEGACY ESTATE")
    print("=" * 78)
    print(f"Credentials audited : {report.total_credentials}")
    print(
        "Findings            : "
        f"critical={report.severity_counts()['critical']} "
        f"high={report.severity_counts()['high']} "
        f"medium={report.severity_counts()['medium']} "
        f"info={report.severity_counts()['info']}"
    )
    for finding in report.findings:
        print(f"  [{finding.severity.value.upper():<8}] {finding.username:<18} {finding.category.value}")

    print()
    print("=" * 78)
    print("STEP 2 - BRUTE-FORCE RESILIENCE")
    print("=" * 78)
    for algorithm, estimate in _benchmarks(policy).items():
        print(
            f"{algorithm:<16} "
            f"{estimate.guesses_per_second:>14,.0f} guesses/s  "
            f"60-bit keyspace: {estimate.keyspace_years_to_crack:.3e} years"
        )

    print()
    print("=" * 78)
    print("STEP 3 - TRANSPARENT UPGRADE ON SUCCESSFUL LOGIN")
    print("=" * 78)
    from .application.upgrade_pipeline import UpgradePipeline

    pipeline = UpgradePipeline(repository, policy)
    for username, password in SAMPLE_PASSWORDS.items():
        result = pipeline.authenticate(username, password)
        print(
            f"  {username:<18} authenticated={str(result.authenticated):<5} "
            f"{result.previous_algorithm or '-':<10} -> "
            f"{result.current_algorithm or '-':<10} {result.reason}"
        )

    print()
    print("=" * 78)
    print("STEP 4 - RE-AUDIT AFTER MIGRATION")
    print("=" * 78)
    post = auditor.audit(repository, candidates=SAMPLE_PASSWORDS)
    print(f"Critical findings before : {report.severity_counts()['critical']}")
    print(f"Critical findings after  : {post.severity_counts()['critical']}")
    return 0


def _benchmarks(policy: HashingPolicy) -> dict[str, BruteForceEstimate]:
    registry = HasherRegistry(policy)
    tester = BruteForceTester(policy, benchmark_iterations=2)
    hashers = [
        registry.get(HashAlgorithm.MD5),
        registry.get(HashAlgorithm.SHA1),
        registry.get(HashAlgorithm.PBKDF2_SHA256),
        registry.get(HashAlgorithm.BCRYPT),
        registry.get(HashAlgorithm.ARGON2ID),
    ]
    return tester.compare(hashers)


def _cmd_benchmark(args: argparse.Namespace) -> int:
    results = _benchmarks(_policy(args))
    if args.json:
        print(
            json.dumps(
                {k: v.to_dict() for k, v in results.items()},
                indent=2,
            )
        )
        return 0
    print(f"{'algorithm':<16}{'guesses/s':>18}{'60-bit keyspace (years)':>28}")
    print("-" * 62)
    for algorithm, estimate in results.items():
        print(
            f"{algorithm:<16}{estimate.guesses_per_second:>18,.0f}"
            f"{estimate.keyspace_years_to_crack:>28,.3e}"
        )
    return 0


def _cmd_collision(args: argparse.Namespace) -> int:
    policy = _policy(args)
    registry = HasherRegistry(policy)
    hasher = registry.get(HashAlgorithm(args.algorithm))
    tester = BruteForceTester(policy)
    report = tester.collision_report(hasher, samples=args.samples)
    print(json.dumps(report.to_dict(), indent=2))
    return 0 if report.is_collision_resistant else 1


def main(argv: Sequence[str] | None = None) -> int:
    """CLI entry point. Returns a process exit code."""
    parser = build_parser()
    args = parser.parse_args(argv)
    handlers = {
        "demo": _cmd_demo,
        "audit": _cmd_audit,
        "benchmark": _cmd_benchmark,
        "collision": _cmd_collision,
    }
    return handlers[args.command](args)


if __name__ == "__main__":  # pragma: no cover
    sys.exit(main())

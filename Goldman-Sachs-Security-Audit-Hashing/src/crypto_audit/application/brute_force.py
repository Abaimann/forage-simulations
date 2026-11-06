"""Brute-force and dictionary collision resilience testing.

The tester answers two questions:

1. **Collision resilience** - does the algorithm produce distinct digests for
   distinct passwords (no collisions) and distinct digests for *identical*
   passwords (salt effectiveness)?
2. **Brute-force resilience** - how much work does an attacker need? By
   benchmarking the cost of a single verification and extrapolating, the
   tester estimates the number of guesses per second and the time required
   to exhaust a dictionary or a full keyspace.
"""

from __future__ import annotations

import math
import time
from dataclasses import dataclass, field
from typing import Callable, Iterable, Sequence

from ..domain.algorithms import HashAlgorithm
from ..domain.digest import HashDigest
from ..domain.policy import HashingPolicy
from .ports import PasswordHasher

__all__ = [
    "CollisionReport",
    "BruteForceEstimate",
    "BruteForceTester",
    "DictionaryAttackResult",
]


@dataclass(frozen=True)
class CollisionReport:
    """Result of the salt/collision resilience experiment."""

    algorithm: HashAlgorithm
    samples: int
    unique_digests: int
    unique_salts: int
    identical_password_digest_stable: bool
    identical_password_digests_distinct: bool

    @property
    def collision_count(self) -> int:
        return self.samples - self.unique_digests

    @property
    def is_collision_resistant(self) -> bool:
        """No digest collisions and identical passwords still hash differently."""
        return (
            self.collision_count == 0
            and self.unique_salts == self.samples
            and self.identical_password_digests_distinct
        )

    def to_dict(self) -> dict[str, object]:
        return {
            "algorithm": self.algorithm.value,
            "samples": self.samples,
            "unique_digests": self.unique_digests,
            "unique_salts": self.unique_salts,
            "collision_count": self.collision_count,
            "identical_password_digest_stable": self.identical_password_digest_stable,
            "identical_password_digests_distinct": self.identical_password_digests_distinct,
            "is_collision_resistant": self.is_collision_resistant,
        }


@dataclass(frozen=True)
class BruteForceEstimate:
    """Extrapolated attacker effort against a single algorithm."""

    algorithm: HashAlgorithm
    guesses_per_second: float
    seconds_per_guess: float
    dictionary_size: int
    dictionary_seconds_to_crack: float
    keyspace_bits: int
    keyspace_seconds_to_crack: float
    keyspace_years_to_crack: float

    def to_dict(self) -> dict[str, object]:
        return {
            "algorithm": self.algorithm.value,
            "guesses_per_second": self.guesses_per_second,
            "seconds_per_guess": self.seconds_per_guess,
            "dictionary_size": self.dictionary_size,
            "dictionary_seconds_to_crack": self.dictionary_seconds_to_crack,
            "keyspace_bits": self.keyspace_bits,
            "keyspace_seconds_to_crack": self.keyspace_seconds_to_crack,
            "keyspace_years_to_crack": self.keyspace_years_to_crack,
        }


@dataclass(frozen=True)
class DictionaryAttackResult:
    """Outcome of a simulated dictionary attack."""

    algorithm: HashAlgorithm
    cracked: bool
    recovered_password: str | None
    attempts: int
    dictionary_size: int
    elapsed_seconds: float
    guesses_per_second: float

    def to_dict(self) -> dict[str, object]:
        return {
            "algorithm": self.algorithm.value,
            "cracked": self.cracked,
            "recovered_password": self.recovered_password,
            "attempts": self.attempts,
            "dictionary_size": self.dictionary_size,
            "elapsed_seconds": self.elapsed_seconds,
            "guesses_per_second": self.guesses_per_second,
        }


@dataclass(frozen=True)
class _Benchmark:
    seconds_per_guess: float
    iterations: int

    @property
    def guesses_per_second(self) -> float:
        if self.seconds_per_guess <= 0:
            return float("inf")
        return 1.0 / self.seconds_per_guess


class BruteForceTester:
    """Benchmarks and stress-tests password hashing algorithms.

    Args:
        policy: Policy used to derive keyspace assumptions (minimum salt and
            password length policy).
        benchmark_iterations: Number of verification rounds used to measure
            the per-guess cost. Kept small by default so tests stay fast.
    """

    def __init__(
        self,
        policy: HashingPolicy | None = None,
        *,
        benchmark_iterations: int = 3,
    ) -> None:
        self._policy = policy or HashingPolicy()
        if benchmark_iterations < 1:
            raise ValueError("benchmark_iterations must be >= 1")
        self._benchmark_iterations = benchmark_iterations

    # ------------------------------------------------------------------
    def collision_report(
        self,
        hasher: PasswordHasher,
        password: str = "Correct-Horse-Battery-Staple",
        *,
        samples: int = 64,
    ) -> CollisionReport:
        """Hash the same password *samples* times and check for collisions.

        A compliant salted KDF must return a *different* digest every time
        (because the salt differs) while remaining deterministic for a fixed
        salt.

        Args:
            hasher: The hasher under test.
            password: Password used for every sample.
            samples: Number of hashes to perform.

        Returns:
            A :class:`CollisionReport`.
        """
        if samples < 1:
            raise ValueError("samples must be >= 1")

        digests: list[bytes] = []
        salts: set[bytes] = set()
        round_trip_ok = True
        for _ in range(samples):
            digest = hasher.hash(password)
            digests.append(digest.hash)
            salts.add(digest.salt or b"")
            # Every produced digest must verify against the original password:
            # this proves the hashing function is deterministic for a fixed salt.
            if not hasher.verify(password, digest):
                round_trip_ok = False

        return CollisionReport(
            algorithm=hasher.algorithm,
            samples=samples,
            unique_digests=len(set(digests)),
            unique_salts=len(salts),
            identical_password_digest_stable=round_trip_ok,
            identical_password_digests_distinct=len(set(digests)) == samples,
        )

    # ------------------------------------------------------------------
    def benchmark(self, hasher: PasswordHasher, password: str = "benchmark") -> _Benchmark:
        """Measure the cost of a single verification.

        The digest used for the benchmark is produced once; only the
        verification (the attacker-relevant operation) is timed.
        """
        digest = hasher.hash(password)
        start = time.perf_counter()
        for _ in range(self._benchmark_iterations):
            hasher.verify(password, digest)
        elapsed = time.perf_counter() - start
        return _Benchmark(
            seconds_per_guess=elapsed / self._benchmark_iterations,
            iterations=self._benchmark_iterations,
        )

    # ------------------------------------------------------------------
    def estimate(
        self,
        hasher: object,
        *,
        dictionary_size: int = 10_000_000,
        keyspace_bits: int = 60,
    ) -> BruteForceEstimate:
        """Estimate attacker effort against *hasher*.

        Args:
            hasher: The hasher under test.
            dictionary_size: Size of the assumed attack dictionary.
            keyspace_bits: Size of the assumed full keyspace in bits.

        Returns:
            A :class:`BruteForceEstimate`.
        """
        if dictionary_size < 1:
            raise ValueError("dictionary_size must be >= 1")
        if keyspace_bits < 1:
            raise ValueError("keyspace_bits must be >= 1")

        bench = self.benchmark(hasher)
        gps = bench.guesses_per_second
        dictionary_seconds = dictionary_size / gps
        keyspace_seconds = (2**keyspace_bits) / gps
        years = keyspace_seconds / (365.25 * 24 * 3600)
        return BruteForceEstimate(
            algorithm=hasher.algorithm,
            guesses_per_second=gps,
            seconds_per_guess=bench.seconds_per_guess,
            dictionary_size=dictionary_size,
            dictionary_seconds_to_crack=dictionary_seconds,
            keyspace_bits=keyspace_bits,
            keyspace_seconds_to_crack=keyspace_seconds,
            keyspace_years_to_crack=years,
        )

    # ------------------------------------------------------------------
    def dictionary_attack(
        self,
        hasher: PasswordHasher,
        digest: HashDigest,
        dictionary: Sequence[str],
    ) -> DictionaryAttackResult:
        """Simulate an offline dictionary attack against *digest*.

        Args:
            hasher: The hasher under test.
            digest: The target digest.
            dictionary: Candidate passwords, ordered by likelihood.

        Returns:
            A :class:`DictionaryAttackResult`.
        """
        start = time.perf_counter()
        attempts = 0
        recovered: str | None = None
        for candidate in dictionary:
            attempts += 1
            if hasher.verify(candidate, digest):
                recovered = candidate
                break
        elapsed = time.perf_counter() - start
        gps = attempts / elapsed if elapsed > 0 else float("inf")
        return DictionaryAttackResult(
            algorithm=hasher.algorithm,
            cracked=recovered is not None,
            recovered_password=recovered,
            attempts=attempts,
            dictionary_size=len(dictionary),
            elapsed_seconds=elapsed,
            guesses_per_second=gps,
        )

    # ------------------------------------------------------------------
    def compare(
        self,
        hashers: Iterable[PasswordHasher],
        *,
        dictionary_size: int = 10_000_000,
        keyspace_bits: int = 60,
    ) -> dict[str, BruteForceEstimate]:
        """Benchmark several hashers and return the estimates keyed by algorithm."""
        results: dict[str, BruteForceEstimate] = {}
        for hasher in hashers:
            estimate = self.estimate(
                hasher,
                dictionary_size=dictionary_size,
                keyspace_bits=keyspace_bits,
            )
            results[estimate.algorithm.value] = estimate
        return results

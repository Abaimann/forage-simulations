"""Tests for brute-force / dictionary collision resilience testing."""

from __future__ import annotations

import pytest

from crypto_audit.application.brute_force import BruteForceTester
from crypto_audit.domain.algorithms import HashAlgorithm
from crypto_audit.infrastructure.argon2_hasher import Argon2idHasher
from crypto_audit.infrastructure.bcrypt_hasher import BcryptHasher
from crypto_audit.infrastructure.legacy_hashers import LegacyHashHasher
from crypto_audit.infrastructure.pbkdf2_hasher import Pbkdf2Hasher

DICTIONARY = [
    "123456",
    "password",
    "qwerty",
    "letmein",
    "welcome",
    "admin",
    "iloveyou",
    "monkey",
    "dragon",
    "correct horse battery staple",
]


@pytest.fixture
def tester(fast_policy) -> BruteForceTester:
    return BruteForceTester(fast_policy, benchmark_iterations=2)


class TestCollisionResilience:
    def test_argon2_is_collision_resistant(self, tester: BruteForceTester) -> None:
        hasher = Argon2idHasher(memory_kib=256, time_cost=1, parallelism=1)
        report = tester.collision_report(hasher, samples=32)
        assert report.collision_count == 0
        assert report.unique_digests == 32
        assert report.unique_salts == 32
        assert report.identical_password_digests_distinct is True
        assert report.is_collision_resistant is True

    def test_bcrypt_is_collision_resistant(self, tester: BruteForceTester) -> None:
        report = tester.collision_report(BcryptHasher(cost=4), samples=16)
        assert report.is_collision_resistant is True

    def test_pbkdf2_is_collision_resistant(self, tester: BruteForceTester) -> None:
        report = tester.collision_report(Pbkdf2Hasher(iterations=1_000), samples=16)
        assert report.is_collision_resistant is True

    def test_unsalted_legacy_algorithm_shows_no_salt_variety(self, tester) -> None:
        hasher = LegacyHashHasher(HashAlgorithm.MD5, salted=False)
        report = tester.collision_report(hasher, samples=16)
        assert report.unique_digests == 1
        assert report.unique_salts == 1
        assert report.identical_password_digests_distinct is False
        assert report.is_collision_resistant is False

    def test_salted_legacy_algorithm_is_collision_resistant(self, tester) -> None:
        hasher = LegacyHashHasher(HashAlgorithm.MD5, salted=True)
        report = tester.collision_report(hasher, samples=16)
        assert report.is_collision_resistant is True

    def test_report_serialises(self, tester: BruteForceTester) -> None:
        hasher = Argon2idHasher(memory_kib=256, time_cost=1, parallelism=1)
        payload = tester.collision_report(hasher, samples=8).to_dict()
        assert payload["algorithm"] == "argon2id"
        assert payload["samples"] == 8
        assert payload["collision_count"] == 0

    def test_zero_samples_is_rejected(self, tester: BruteForceTester) -> None:
        hasher = Argon2idHasher(memory_kib=256, time_cost=1, parallelism=1)
        with pytest.raises(ValueError):
            tester.collision_report(hasher, samples=0)


class TestBruteForceEstimates:
    def test_modern_algorithm_is_slower_than_legacy(self, tester) -> None:
        legacy = LegacyHashHasher(HashAlgorithm.MD5, salted=False)
        modern = Argon2idHasher(memory_kib=256, time_cost=1, parallelism=1)

        legacy_estimate = tester.estimate(legacy)
        modern_estimate = tester.estimate(modern)

        assert modern_estimate.guesses_per_second < legacy_estimate.guesses_per_second
        assert (
            modern_estimate.keyspace_years_to_crack
            > legacy_estimate.keyspace_years_to_crack
        )

    def test_estimate_values_are_positive(self, tester: BruteForceTester) -> None:
        hasher = Argon2idHasher(memory_kib=256, time_cost=1, parallelism=1)
        estimate = tester.estimate(hasher)
        assert estimate.guesses_per_second > 0
        assert estimate.seconds_per_guess > 0
        assert estimate.keyspace_seconds_to_crack > 0
        assert estimate.keyspace_years_to_crack > 0

    def test_invalid_dictionary_size_is_rejected(self, tester) -> None:
        hasher = Argon2idHasher(memory_kib=256, time_cost=1, parallelism=1)
        with pytest.raises(ValueError):
            tester.estimate(hasher, dictionary_size=0)

    def test_invalid_keyspace_is_rejected(self, tester: BruteForceTester) -> None:
        hasher = Argon2idHasher(memory_kib=256, time_cost=1, parallelism=1)
        with pytest.raises(ValueError):
            tester.estimate(hasher, keyspace_bits=0)

    def test_compare_returns_one_entry_per_algorithm(self, tester) -> None:
        hashers = [
            LegacyHashHasher(HashAlgorithm.MD5, salted=False),
            Argon2idHasher(memory_kib=256, time_cost=1, parallelism=1),
        ]
        results = tester.compare(hashers)
        assert set(results) == {"md5", "argon2id"}

    def test_benchmark_rejects_zero_iterations(self, fast_policy) -> None:
        with pytest.raises(ValueError):
            BruteForceTester(fast_policy, benchmark_iterations=0)


class TestDictionaryAttack:
    def test_attack_recovers_the_password(self, tester: BruteForceTester) -> None:
        hasher = Argon2idHasher(memory_kib=256, time_cost=1, parallelism=1)
        secret = "correct horse battery staple"
        digest = hasher.hash(secret)

        result = tester.dictionary_attack(hasher, digest, DICTIONARY)
        assert result.cracked is True
        assert result.recovered_password == secret
        assert result.attempts == len(DICTIONARY)

    def test_attack_fails_when_password_is_absent(self, tester: BruteForceTester) -> None:
        hasher = Argon2idHasher(memory_kib=256, time_cost=1, parallelism=1)
        digest = hasher.hash("not-in-any-dictionary-9f3a")

        result = tester.dictionary_attack(hasher, digest, DICTIONARY)
        assert result.cracked is False
        assert result.recovered_password is None
        assert result.attempts == len(DICTIONARY)

    def test_attack_stops_at_first_match(self, tester: BruteForceTester) -> None:
        hasher = Argon2idHasher(memory_kib=256, time_cost=1, parallelism=1)
        digest = hasher.hash("admin")
        result = tester.dictionary_attack(hasher, digest, DICTIONARY)
        assert result.attempts == DICTIONARY.index("admin") + 1

    def test_result_serialises(self, tester: BruteForceTester) -> None:
        hasher = Argon2idHasher(memory_kib=256, time_cost=1, parallelism=1)
        digest = hasher.hash("admin")
        payload = tester.dictionary_attack(hasher, digest, DICTIONARY).to_dict()
        assert payload["cracked"] is True
        assert payload["algorithm"] == "argon2id"


class TestResilienceNarrative:
    def test_legacy_algorithm_is_cracked_far_sooner(self, tester) -> None:
        """The core security argument: modern KDFs must dominate legacy ones."""
        legacy = LegacyHashHasher(HashAlgorithm.MD5, salted=False)
        # Production-strength Argon2id (64 MiB, t=3) - the numbers an
        # assessor would actually quote.
        modern = Argon2idHasher(memory_kib=65_536, time_cost=3, parallelism=1)

        legacy_estimate = tester.estimate(legacy, keyspace_bits=40)
        modern_estimate = tester.estimate(modern, keyspace_bits=40)

        speedup = (
            modern_estimate.keyspace_years_to_crack
            / legacy_estimate.keyspace_years_to_crack
        )
        assert speedup > 1_000, f"expected a large slowdown, measured {speedup:.1f}x"

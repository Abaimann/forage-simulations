"""Tests for the transparent upgrade pipeline."""

from __future__ import annotations

import time

import pytest

from crypto_audit.application.upgrade_pipeline import UpgradePipeline
from crypto_audit.domain.algorithms import HashAlgorithm
from crypto_audit.domain.credential import Credential
from crypto_audit.domain.digest import HashDigest
from crypto_audit.domain.policy import HashingPolicy
from crypto_audit.infrastructure.argon2_hasher import Argon2idHasher
from crypto_audit.infrastructure.hasher_factory import HasherRegistry
from crypto_audit.infrastructure.legacy_hashers import LegacyHashHasher
from crypto_audit.infrastructure.pbkdf2_hasher import Pbkdf2Hasher
from crypto_audit.infrastructure.repository import InMemoryCredentialRepository

LEGACY_PASSWORD = "LegacyPass123!"


@pytest.fixture
def legacy_repo() -> InMemoryCredentialRepository:
    repo = InMemoryCredentialRepository()
    hasher = LegacyHashHasher(HashAlgorithm.MD5, salted=False)
    repo.save(Credential("legacy.user", hasher.hash(LEGACY_PASSWORD)))
    return repo


@pytest.fixture
def registry(fast_policy: HashingPolicy) -> HasherRegistry:
    """Registry shared with the pipeline so tests can instrument hashers."""
    return HasherRegistry(fast_policy)


@pytest.fixture
def pipeline(
    legacy_repo: InMemoryCredentialRepository,
    fast_policy: HashingPolicy,
    registry: HasherRegistry,
):
    return UpgradePipeline(legacy_repo, fast_policy, registry=registry)


class TestTransparentUpgrade:
    def test_successful_login_upgrades_legacy_digest(self, pipeline, legacy_repo) -> None:
        result = pipeline.authenticate("legacy.user", LEGACY_PASSWORD)

        assert result.authenticated is True
        assert result.upgraded is True
        assert result.reason == "upgraded"
        assert result.previous_algorithm == "md5"
        assert result.current_algorithm == "argon2id"

        stored = legacy_repo.get("legacy.user")
        assert stored is not None
        assert stored.digest.algorithm is HashAlgorithm.ARGON2ID
        assert stored.digest.salt is not None
        assert len(stored.digest.salt) >= 16

    def test_upgrade_bumps_credential_version(self, pipeline, legacy_repo) -> None:
        before = legacy_repo.get("legacy.user")
        assert before is not None
        pipeline.authenticate("legacy.user", LEGACY_PASSWORD)
        after = legacy_repo.get("legacy.user")
        assert after is not None
        assert after.version == before.version + 1

    def test_upgraded_credential_still_authenticates(self, pipeline) -> None:
        pipeline.authenticate("legacy.user", LEGACY_PASSWORD)
        second = pipeline.authenticate("legacy.user", LEGACY_PASSWORD)
        assert second.authenticated is True
        assert second.upgraded is False
        assert second.reason == "up_to_date"

    def test_upgrade_does_not_store_plaintext(self, pipeline, legacy_repo) -> None:
        pipeline.authenticate("legacy.user", LEGACY_PASSWORD)
        stored = legacy_repo.get("legacy.user")
        assert stored is not None
        assert LEGACY_PASSWORD.encode() not in stored.digest.hash
        assert LEGACY_PASSWORD not in stored.digest.encode()

    def test_wrong_password_does_not_upgrade(self, pipeline, legacy_repo) -> None:
        result = pipeline.authenticate("legacy.user", "WrongPassword!")
        assert result.authenticated is False
        assert result.upgraded is False
        assert result.reason == "invalid_password"

        stored = legacy_repo.get("legacy.user")
        assert stored is not None
        assert stored.digest.algorithm is HashAlgorithm.MD5

    def test_unknown_user_is_rejected(self, pipeline) -> None:
        result = pipeline.authenticate("ghost", "whatever")
        assert result.authenticated is False
        assert result.reason == "unknown_user"
        assert result.upgraded is False


class TestPolicyDrivenUpgrade:
    def test_weak_parameters_trigger_rehash(self, fast_policy: HashingPolicy) -> None:
        repo = InMemoryCredentialRepository()
        weak = Pbkdf2Hasher(iterations=1_000)
        repo.save(Credential("weak.user", weak.hash("pw12345678")))
        pipeline = UpgradePipeline(repo, fast_policy)

        result = pipeline.authenticate("weak.user", "pw12345678")
        assert result.authenticated is True
        assert result.upgraded is True
        assert result.current_algorithm == "argon2id"

    def test_target_algorithm_is_respected(self, fast_policy: HashingPolicy) -> None:
        repo = InMemoryCredentialRepository()
        legacy = LegacyHashHasher(HashAlgorithm.MD5, salted=False)
        repo.save(Credential("legacy.user", legacy.hash(LEGACY_PASSWORD)))

        bcrypt_policy = fast_policy.with_target(HashAlgorithm.BCRYPT)
        pipeline = UpgradePipeline(repo, bcrypt_policy)
        result = pipeline.authenticate("legacy.user", LEGACY_PASSWORD)
        assert result.current_algorithm == "bcrypt"


class TestTimingAttackMitigation:
    def test_unknown_user_performs_decoy_verification(
        self, pipeline, registry: HasherRegistry
    ) -> None:
        """An unknown user must still cost one verification (no enumeration)."""
        calls: list[str] = []
        argon2 = registry.get(HashAlgorithm.ARGON2ID)
        original_verify = argon2.verify

        def spy_verify(password: str, digest: HashDigest) -> bool:
            calls.append("verify")
            return original_verify(password, digest)

        argon2.verify = spy_verify  # type: ignore[method-assign]
        try:
            pipeline.authenticate("does-not-exist", "candidate")
        finally:
            argon2.verify = original_verify  # type: ignore[method-assign]

        assert len(calls) == 1, "unknown user must trigger a decoy verification"

    def test_known_user_also_performs_exactly_one_verification(
        self, pipeline, registry: HasherRegistry
    ) -> None:
        calls: list[str] = []
        argon2 = registry.get(HashAlgorithm.ARGON2ID)
        original_verify = argon2.verify

        def spy_verify(password: str, digest: HashDigest) -> bool:
            calls.append("verify")
            return original_verify(password, digest)

        argon2.verify = spy_verify  # type: ignore[method-assign]
        try:
            pipeline.authenticate("legacy.user", LEGACY_PASSWORD)
        finally:
            argon2.verify = original_verify  # type: ignore[method-assign]

        assert len(calls) == 1

    def test_unknown_and_known_user_timing_are_comparable(self, pipeline) -> None:
        """Response time must not reveal whether the account exists."""
        def measure(username: str, password: str) -> float:
            rounds = 5
            start = time.perf_counter()
            for _ in range(rounds):
                pipeline.authenticate(username, password)
            return (time.perf_counter() - start) / rounds

        # Warm-up so lazy imports / decoy construction are not measured.
        measure("legacy.user", LEGACY_PASSWORD)
        measure("ghost", "candidate")

        known = measure("legacy.user", LEGACY_PASSWORD)
        unknown = measure("ghost", "candidate")
        ratio = unknown / known if known > 0 else 1.0
        assert 0.2 < ratio < 5.0, f"timing ratio {ratio:.3f} leaks account existence"


class TestBulkMigration:
    def test_migrate_all_upgrades_every_known_credential(
        self, fast_policy: HashingPolicy
    ) -> None:
        repo = InMemoryCredentialRepository()
        legacy = LegacyHashHasher(HashAlgorithm.MD5, salted=False)
        repo.save(Credential("a", legacy.hash("PasswordA1!")))
        repo.save(Credential("b", legacy.hash("PasswordB1!")))

        pipeline = UpgradePipeline(repo, fast_policy)
        results = pipeline.migrate_all({"a": "PasswordA1!", "b": "PasswordB1!"})

        assert all(r.upgraded for r in results.values())
        assert repo.get("a").digest.algorithm is HashAlgorithm.ARGON2ID
        assert repo.get("b").digest.algorithm is HashAlgorithm.ARGON2ID

    def test_migrate_all_skips_compliant_credentials(
        self, fast_policy: HashingPolicy
    ) -> None:
        repo = InMemoryCredentialRepository()
        good = Argon2idHasher(memory_kib=65_536, time_cost=3, parallelism=1)
        repo.save(Credential("good", good.hash("AlreadyGood1!")))

        pipeline = UpgradePipeline(repo, fast_policy)
        results = pipeline.migrate_all({"good": "AlreadyGood1!"})
        assert results["good"].upgraded is False
        assert results["good"].reason == "up_to_date"

    def test_migrate_all_reports_unknown_users(self, fast_policy: HashingPolicy) -> None:
        repo = InMemoryCredentialRepository()
        pipeline = UpgradePipeline(repo, fast_policy)
        results = pipeline.migrate_all({"ghost": "pw"})
        assert results["ghost"].authenticated is False
        assert results["ghost"].reason == "unknown_user"

    def test_migrate_all_never_downgrades(
        self, fast_policy: HashingPolicy
    ) -> None:
        repo = InMemoryCredentialRepository()
        good = Argon2idHasher(memory_kib=65_536, time_cost=3, parallelism=1)
        repo.save(Credential("good", good.hash("AlreadyGood1!")))
        pipeline = UpgradePipeline(repo, fast_policy)
        pipeline.migrate_all({"good": "AlreadyGood1!"})
        stored = repo.get("good")
        assert stored is not None
        assert stored.digest.algorithm is HashAlgorithm.ARGON2ID


class TestSecretComparison:
    def test_verify_secret_matches(self, pipeline) -> None:
        assert pipeline.verify_secret("abc", "abc") is True

    def test_verify_secret_rejects_mismatch(self, pipeline) -> None:
        assert pipeline.verify_secret("abc", "abd") is False

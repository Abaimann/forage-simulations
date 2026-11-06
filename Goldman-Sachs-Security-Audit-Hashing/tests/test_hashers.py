"""Tests for every password hasher implementation."""

from __future__ import annotations

import pytest

from crypto_audit.domain.algorithms import HashAlgorithm
from crypto_audit.domain.digest import HashDigest
from crypto_audit.domain.exceptions import PasswordTooLongError
from crypto_audit.infrastructure.argon2_hasher import Argon2idHasher
from crypto_audit.infrastructure.bcrypt_hasher import BcryptHasher
from crypto_audit.infrastructure.legacy_hashers import (
    LegacyHashHasher,
    UnsupportedLegacyAlgorithm,
)
from crypto_audit.infrastructure.pbkdf2_hasher import Pbkdf2Hasher

ALL_HASHERS = ["argon2", "bcrypt", "pbkdf2", "legacy_md5", "legacy_md5_unsalted"]


@pytest.fixture(params=ALL_HASHERS)
def hasher(request: pytest.FixtureRequest):
    if request.param == "argon2":
        return Argon2idHasher(memory_kib=256, time_cost=1, parallelism=1)
    if request.param == "bcrypt":
        return BcryptHasher(cost=4)
    if request.param == "pbkdf2":
        return Pbkdf2Hasher(iterations=10_000)
    if request.param == "legacy_md5":
        return LegacyHashHasher(HashAlgorithm.MD5, salted=True)
    return LegacyHashHasher(HashAlgorithm.MD5, salted=False)


class TestHasherContract:
    """Behaviour that every hasher implementation must share."""

    def test_correct_password_verifies(self, hasher) -> None:
        digest = hasher.hash("S3cret!Passphrase")
        assert hasher.verify("S3cret!Passphrase", digest) is True

    def test_wrong_password_is_rejected(self, hasher) -> None:
        digest = hasher.hash("S3cret!Passphrase")
        assert hasher.verify("S3cret!Passphras", digest) is False

    def test_wrong_password_case_sensitive(self, hasher) -> None:
        digest = hasher.hash("S3cret!Passphrase")
        assert hasher.verify("s3cret!passphrase", digest) is False

    def test_empty_password_round_trip(self, hasher) -> None:
        digest = hasher.hash("")
        assert hasher.verify("", digest) is True
        assert hasher.verify("x", digest) is False

    def test_long_password_within_algorithm_limit_round_trips(self, hasher) -> None:
        # bcrypt truncates at 72 bytes, so the shared ceiling is respected by
        # each algorithm's own documented limit.
        password = "a" * min(hasher.max_password_bytes, 200)
        digest = hasher.hash(password)
        assert hasher.verify(password, digest) is True

    def test_password_beyond_algorithm_limit_is_rejected(self, hasher) -> None:
        if hasher.max_password_bytes >= 4096:
            pytest.skip("algorithm has no tighter-than-policy byte limit")
        from crypto_audit.domain.exceptions import PasswordTooLongError

        with pytest.raises(PasswordTooLongError):
            hasher.hash("a" * (hasher.max_password_bytes + 1))

    def test_verify_rejects_digest_of_other_algorithm(self, hasher) -> None:
        other = HashDigest(algorithm=HashAlgorithm.SHA256, hash=b"z" * 32, salt=b"s" * 16)
        assert hasher.verify("anything", other) is False

    def test_verify_rejects_digest_without_salt(self, hasher) -> None:
        if hasher.algorithm is HashAlgorithm.MD5 and not hasher.salted:
            pytest.skip("unsalted legacy hasher legitimately supports salt=None")
        digest = HashDigest(algorithm=hasher.algorithm, hash=b"z" * 32, salt=None)
        assert hasher.verify("anything", digest) is False

    def test_hash_uses_fresh_salt_each_time(self, hasher) -> None:
        if not hasher.salted:
            pytest.skip("unsalted legacy hasher legitimately has no salt")
        first = hasher.hash("same-password")
        second = hasher.hash("same-password")
        assert first.salt != second.salt
        assert first.hash != second.hash

    def test_digest_reports_algorithm(self, hasher) -> None:
        assert hasher.hash("x").algorithm is hasher.algorithm

    def test_digest_round_trips_through_wire_format(self, hasher) -> None:
        digest = hasher.hash("wire-format")
        restored = HashDigest.decode(digest.encode())
        assert restored == digest
        assert hasher.verify("wire-format", restored) is True


class TestArgon2idHasher:
    def test_rejects_tiny_memory(self) -> None:
        with pytest.raises(ValueError):
            Argon2idHasher(memory_kib=4)

    def test_rejects_zero_time_cost(self) -> None:
        with pytest.raises(ValueError):
            Argon2idHasher(time_cost=0)

    def test_rejects_zero_parallelism(self) -> None:
        with pytest.raises(ValueError):
            Argon2idHasher(parallelism=0)

    def test_rejects_short_hash_length(self) -> None:
        with pytest.raises(ValueError):
            Argon2idHasher(hash_length=8)

    def test_rejects_short_salt(self) -> None:
        with pytest.raises(ValueError):
            Argon2idHasher(salt_bytes=4)

    def test_parameters_are_recorded(self) -> None:
        hasher = Argon2idHasher(memory_kib=512, time_cost=2, parallelism=1, hash_length=16)
        digest = hasher.hash("param-check")
        assert digest.params["m"] == 512
        assert digest.params["t"] == 2
        assert digest.params["p"] == 1
        assert digest.params["length"] == 16
        assert len(digest.hash) == 16

    def test_verify_survives_tampered_digest(self) -> None:
        hasher = Argon2idHasher(memory_kib=256, time_cost=1, parallelism=1)
        digest = hasher.hash("tamper")
        tampered = HashDigest(
            algorithm=digest.algorithm,
            hash=bytes(len(digest.hash)),
            salt=digest.salt,
            params=digest.params,
        )
        assert hasher.verify("tamper", tampered) is False

    def test_unicode_password_round_trip(self) -> None:
        hasher = Argon2idHasher(memory_kib=256, time_cost=1, parallelism=1)
        password = "pässwörd-🔐-日本語"
        digest = hasher.hash(password)
        assert hasher.verify(password, digest) is True


class TestBcryptHasher:
    def test_rejects_invalid_cost(self) -> None:
        with pytest.raises(ValueError):
            BcryptHasher(cost=3)
        with pytest.raises(ValueError):
            BcryptHasher(cost=32)

    def test_password_over_72_bytes_is_rejected(self) -> None:
        hasher = BcryptHasher(cost=4)
        with pytest.raises(PasswordTooLongError):
            hasher.hash("a" * 73)

    def test_verify_returns_false_for_oversized_password(self) -> None:
        hasher = BcryptHasher(cost=4)
        digest = hasher.hash("short")
        assert hasher.verify("a" * 100, digest) is False

    def test_max_password_bytes_is_72(self) -> None:
        assert BcryptHasher(cost=4).max_password_bytes == 72

    def test_salt_prefix_length_is_29(self) -> None:
        digest = BcryptHasher(cost=4).hash("prefix")
        assert len(digest.salt) == 29
        assert len(digest.hash) == 31

    def test_cost_is_recorded(self) -> None:
        digest = BcryptHasher(cost=5).hash("cost")
        assert digest.params["cost"] == 5


class TestPbkdf2Hasher:
    def test_rejects_too_few_iterations(self) -> None:
        with pytest.raises(ValueError):
            Pbkdf2Hasher(iterations=10)

    def test_rejects_short_salt(self) -> None:
        with pytest.raises(ValueError):
            Pbkdf2Hasher(salt_bytes=4)

    def test_rejects_short_hash_length(self) -> None:
        with pytest.raises(ValueError):
            Pbkdf2Hasher(hash_length=8)

    def test_iterations_are_recorded(self) -> None:
        digest = Pbkdf2Hasher(iterations=12_345).hash("iter")
        assert digest.params["iterations"] == 12_345

    def test_verification_uses_stored_iteration_count(self) -> None:
        hasher = Pbkdf2Hasher(iterations=5_000)
        digest = hasher.hash("stored-iterations")
        assert hasher.verify("stored-iterations", digest) is True


class TestLegacyHashHasher:
    def test_rejects_non_legacy_algorithm(self) -> None:
        with pytest.raises(UnsupportedLegacyAlgorithm):
            LegacyHashHasher(HashAlgorithm.ARGON2ID)

    def test_rejects_negative_salt_length(self) -> None:
        with pytest.raises(ValueError):
            LegacyHashHasher(HashAlgorithm.MD5, salt_bytes=-1)

    def test_unsalted_mode_produces_none_salt(self) -> None:
        hasher = LegacyHashHasher(HashAlgorithm.MD5, salted=False)
        digest = hasher.hash("no-salt")
        assert digest.salt is None
        assert hasher.verify("no-salt", digest) is True

    def test_salted_mode_differs_from_unsalted(self) -> None:
        salted = LegacyHashHasher(HashAlgorithm.MD5, salted=True).hash("same")
        unsalted = LegacyHashHasher(HashAlgorithm.MD5, salted=False).hash("same")
        assert salted.hash != unsalted.hash

    def test_sha1_supported(self) -> None:
        hasher = LegacyHashHasher(HashAlgorithm.SHA1, salted=False)
        digest = hasher.hash("sha1")
        assert len(digest.hash) == 20
        assert hasher.verify("sha1", digest) is True

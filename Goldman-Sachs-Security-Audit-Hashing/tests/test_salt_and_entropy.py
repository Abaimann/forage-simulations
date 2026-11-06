"""Salt collision resistance and entropy analysis tests."""

from __future__ import annotations

import pytest

from crypto_audit.application.entropy import (
    analyse_password_entropy,
    charset_size,
    entropy_density,
    entropy_profile,
    estimate_password_entropy_bits,
    normalised_entropy_bits_per_byte,
    shannon_entropy_bits,
    unique_ratio,
)
from crypto_audit.domain.algorithms import HashAlgorithm
from crypto_audit.infrastructure.argon2_hasher import Argon2idHasher
from crypto_audit.infrastructure.bcrypt_hasher import BcryptHasher
from crypto_audit.infrastructure.pbkdf2_hasher import Pbkdf2Hasher

SALTED_HASHERS = ["argon2", "bcrypt", "pbkdf2"]


@pytest.fixture(params=SALTED_HASHERS)
def salted_hasher(request: pytest.FixtureRequest):
    if request.param == "argon2":
        return Argon2idHasher(memory_kib=256, time_cost=1, parallelism=1, salt_bytes=16)
    if request.param == "bcrypt":
        return BcryptHasher(cost=4)
    return Pbkdf2Hasher(iterations=1_000, salt_bytes=16)


class TestSaltCollisionResistance:
    """A salt must be unique per credential; collisions defeat their purpose."""

    def test_salts_are_unique_across_many_hashes(self, salted_hasher) -> None:
        salts = {salted_hasher.hash("same-password").salt for _ in range(200)}
        assert len(salts) == 200

    def test_salt_length_meets_policy_minimum(self, salted_hasher) -> None:
        digest = salted_hasher.hash("salt-length")
        assert digest.salt is not None
        assert len(digest.salt) >= 16

    def test_identical_passwords_yield_distinct_digests(self, salted_hasher) -> None:
        digests = {salted_hasher.hash("identical").hash for _ in range(100)}
        assert len(digests) == 100

    def test_distinct_passwords_yield_distinct_digests(self, salted_hasher) -> None:
        digests = {
            salted_hasher.hash(f"password-{index}").hash for index in range(100)
        }
        assert len(digests) == 100

    def test_collision_ratio_is_zero(self, salted_hasher) -> None:
        hashes = [salted_hasher.hash("collision-check").hash for _ in range(150)]
        assert unique_ratio(hashes) == 1.0

    def test_salted_legacy_hashers_also_use_unique_salts(self) -> None:
        from crypto_audit.infrastructure.legacy_hashers import LegacyHashHasher

        hasher = LegacyHashHasher(HashAlgorithm.MD5, salted=True, salt_bytes=16)
        salts = {hasher.hash("legacy").salt for _ in range(100)}
        assert len(salts) == 100

    def test_salt_bytes_are_not_low_entropy(self, salted_hasher) -> None:
        digest = salted_hasher.hash("entropy")
        assert digest.salt is not None
        # A random 128-bit salt must reach the maximum entropy that a
        # 16-byte sample can possibly express.
        assert entropy_density(digest.salt) > 0.85


class TestShannonEntropy:
    def test_empty_input_has_zero_entropy(self) -> None:
        assert shannon_entropy_bits(b"") == 0.0

    def test_uniform_bytes_have_maximum_entropy(self) -> None:
        assert shannon_entropy_bits(bytes(range(256))) == pytest.approx(8.0)

    def test_single_repeated_byte_has_zero_entropy(self) -> None:
        assert shannon_entropy_bits(b"A" * 100) == 0.0

    def test_two_equiprobable_symbols_have_one_bit(self) -> None:
        assert shannon_entropy_bits(b"AB" * 50) == pytest.approx(1.0)

    def test_normalised_entropy_of_empty_is_zero(self) -> None:
        assert normalised_entropy_bits_per_byte(b"") == 0.0

    def test_normalised_entropy_is_bounded_by_eight(self) -> None:
        assert normalised_entropy_bits_per_byte(bytes(range(256))) <= 8.0


class TestPasswordEntropy:
    def test_empty_password_has_zero_estimate(self) -> None:
        assert estimate_password_entropy_bits("") == 0.0

    def test_longer_password_has_more_entropy(self) -> None:
        short = estimate_password_entropy_bits("Ab1!")
        long = estimate_password_entropy_bits("Ab1!Ab1!Ab1!")
        assert long > short

    def test_charset_size_grows_with_character_classes(self) -> None:
        assert charset_size("abcdef") == 26
        assert charset_size("abcdefABCDEF") == 52
        assert charset_size("abcdefABCDEF123") == 62
        assert charset_size("abcdefABCDEF123!") > 62

    def test_charset_size_never_zero(self) -> None:
        assert charset_size("") == 1

    def test_assessment_reports_length_and_entropy(self) -> None:
        assessment = analyse_password_entropy("Correct-Horse-Battery")
        assert assessment.length == 21
        assert assessment.entropy_bits > 0
        assert assessment.density > 0.0

    def test_assessment_of_weak_password(self) -> None:
        assessment = analyse_password_entropy("password")
        assert assessment.is_strong is False

    def test_assessment_of_strong_password(self) -> None:
        assessment = analyse_password_entropy("Xk9!vQ2#mZ7@pL4$wR8!", minimum_bits=60)
        assert assessment.is_strong is True

    def test_entropy_profile_of_empty_collection(self) -> None:
        profile = entropy_profile([])
        assert profile["count"] == 0
        assert profile["mean_density"] == 0.0

    def test_entropy_profile_of_digests(self) -> None:
        hasher = Argon2idHasher(memory_kib=256, time_cost=1, parallelism=1)
        digests = [hasher.hash("profile").hash for _ in range(10)]
        profile = entropy_profile(digests)
        assert profile["count"] == 10
        assert profile["min_density"] > 0.85

    def test_unique_ratio_of_empty_is_one(self) -> None:
        assert unique_ratio([]) == 1.0

    def test_unique_ratio_detects_duplicates(self) -> None:
        assert unique_ratio([b"a", b"a", b"b"]) == pytest.approx(2 / 3)

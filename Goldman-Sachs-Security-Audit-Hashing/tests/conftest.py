"""Shared pytest fixtures.

All hashers used in tests run with reduced cost parameters so the suite stays
fast while preserving the *shape* of the production configuration.
"""

from __future__ import annotations

import sys
from dataclasses import replace
from pathlib import Path

import pytest

SRC = Path(__file__).resolve().parents[1] / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from crypto_audit.domain.algorithms import HashAlgorithm  # noqa: E402
from crypto_audit.domain.credential import Credential  # noqa: E402
from crypto_audit.domain.policy import AlgorithmParameters, HashingPolicy  # noqa: E402
from crypto_audit.infrastructure.argon2_hasher import Argon2idHasher  # noqa: E402
from crypto_audit.infrastructure.bcrypt_hasher import BcryptHasher  # noqa: E402
from crypto_audit.infrastructure.legacy_hashers import LegacyHashHasher  # noqa: E402
from crypto_audit.infrastructure.pbkdf2_hasher import Pbkdf2Hasher  # noqa: E402
from crypto_audit.infrastructure.repository import (  # noqa: E402
    InMemoryCredentialRepository,
)


@pytest.fixture(scope="session")
def fast_policy() -> HashingPolicy:
    """Policy with reduced cost parameters (still policy-shaped).

    Both the *cost parameters* and the *audit thresholds* are lowered, so a
    digest produced by this policy is considered compliant by it.
    """
    return replace(
        HashingPolicy(),
        parameters=AlgorithmParameters(
            pbkdf2_iterations=10_000,
            bcrypt_cost=4,
            argon2_memory_kib=256,
            argon2_time_cost=1,
            argon2_parallelism=1,
        ),
        minimum_pbkdf2_iterations=10_000,
        minimum_bcrypt_cost=4,
        minimum_argon2_memory_kib=256,
        minimum_argon2_time_cost=1,
    )


@pytest.fixture(scope="session")
def argon2_hasher() -> Argon2idHasher:
    return Argon2idHasher(memory_kib=256, time_cost=1, parallelism=1, salt_bytes=16)


@pytest.fixture(scope="session")
def bcrypt_hasher() -> BcryptHasher:
    return BcryptHasher(cost=4)


@pytest.fixture(scope="session")
def pbkdf2_hasher() -> Pbkdf2Hasher:
    return Pbkdf2Hasher(iterations=10_000, salt_bytes=16)


@pytest.fixture(scope="session")
def legacy_md5_hasher() -> LegacyHashHasher:
    return LegacyHashHasher(HashAlgorithm.MD5, salted=True)


@pytest.fixture(scope="session")
def legacy_md5_unsalted_hasher() -> LegacyHashHasher:
    return LegacyHashHasher(HashAlgorithm.MD5, salted=False)


@pytest.fixture
def empty_repository() -> InMemoryCredentialRepository:
    return InMemoryCredentialRepository()


@pytest.fixture
def repository() -> InMemoryCredentialRepository:
    """Repository with one legacy MD5 credential."""
    repo = InMemoryCredentialRepository()
    hasher = LegacyHashHasher(HashAlgorithm.MD5, salted=False)
    repo.save(Credential("legacy.user", hasher.hash("LegacyPass123!")))
    return repo

"""Deterministic sample estate used by the CLI demo and by the tests.

The sample intentionally contains every weakness the auditor is designed to
detect: unsalted MD5/SHA-1, weak salt, low-iteration PBKDF2, low-cost
bcrypt, reused passwords and a fully compliant Argon2id account.
"""

from __future__ import annotations

import hashlib
from typing import Mapping

from ..domain.algorithms import HashAlgorithm
from ..domain.credential import Credential
from ..domain.digest import HashDigest
from ..infrastructure.argon2_hasher import Argon2idHasher
from ..infrastructure.bcrypt_hasher import BcryptHasher
from ..infrastructure.legacy_hashers import LegacyHashHasher
from ..infrastructure.pbkdf2_hasher import Pbkdf2Hasher
from ..infrastructure.repository import InMemoryCredentialRepository

__all__ = ["SAMPLE_PASSWORDS", "build_sample_repository"]


#: Plaintexts for the sample accounts. Never used in production code paths.
SAMPLE_PASSWORDS: Mapping[str, str] = {
    "alice.legacy": "Password123",
    "bob.legacy": "qwerty123",
    "carol.legacy": "Summer2024!",
    "dave.salted": "Tr0ub4dor&3",
    "erin.weak": "letmein",
    "grace.reuse": "Password123",
    "heidi.reuse": "Password123",
    "frank.compliant": "correct horse battery staple",
}


def _unsalted_md5(password: str) -> HashDigest:
    return HashDigest(
        algorithm=HashAlgorithm.MD5,
        hash=hashlib.md5(password.encode("utf-8")).digest(),
        salt=None,
        params={"salted": 0},
    )


def _unsalted_sha1(password: str) -> HashDigest:
    return HashDigest(
        algorithm=HashAlgorithm.SHA1,
        hash=hashlib.sha1(password.encode("utf-8")).digest(),
        salt=None,
        params={"salted": 0},
    )


def build_sample_repository() -> InMemoryCredentialRepository:
    """Build the sample credential estate.

    Returns:
        A repository pre-populated with eight representative accounts.
    """
    repository = InMemoryCredentialRepository()

    # 1-2: unsalted MD5 / SHA-1 (critical weakness).
    repository.save(Credential("alice.legacy", _unsalted_md5(SAMPLE_PASSWORDS["alice.legacy"])))
    repository.save(Credential("bob.legacy", _unsalted_sha1(SAMPLE_PASSWORDS["bob.legacy"])))

    # 3: salted MD5 with a short salt.
    legacy = LegacyHashHasher(HashAlgorithm.MD5, salt_bytes=4, salted=True)
    repository.save(
        Credential("carol.legacy", legacy.hash(SAMPLE_PASSWORDS["carol.legacy"]))
    )

    # 4: PBKDF2 with far too few iterations.
    weak_pbkdf2 = Pbkdf2Hasher(iterations=1_000, salt_bytes=16)
    repository.save(
        Credential("dave.salted", weak_pbkdf2.hash(SAMPLE_PASSWORDS["dave.salted"]))
    )

    # 5: bcrypt with an insufficient cost.
    weak_bcrypt = BcryptHasher(cost=6)
    repository.save(Credential("erin.weak", weak_bcrypt.hash(SAMPLE_PASSWORDS["erin.weak"])))

    # 6: fully compliant Argon2id account.
    argon2 = Argon2idHasher(
        memory_kib=65_536,
        time_cost=3,
        parallelism=4,
        salt_bytes=16,
    )
    repository.save(
        Credential("frank.compliant", argon2.hash(SAMPLE_PASSWORDS["frank.compliant"]))
    )

    # 7-8: identical unsalted MD5 digest -> password reuse across accounts.
    repository.save(Credential("grace.reuse", _unsalted_md5("Password123")))
    repository.save(Credential("heidi.reuse", _unsalted_md5("Password123")))

    return repository

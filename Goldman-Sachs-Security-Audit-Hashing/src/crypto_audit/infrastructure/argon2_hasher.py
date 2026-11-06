"""Argon2id hasher - the preferred password KDF.

Parameters follow the OWASP Password Storage Cheat Sheet recommendation
(Argon2id, m=64 MiB, t=3, p=4). The low-level API is used so the salt and
the derived key stay separable, which lets the auditor inspect salt entropy
and lets verification use an explicit constant-time comparison.
"""

from __future__ import annotations

import secrets

from argon2 import low_level

from ..application.constant_time import secure_compare_bytes
from ..domain.algorithms import HashAlgorithm
from ..domain.digest import HashDigest
from ..domain.password import MAX_PASSWORD_BYTES, encode_password

__all__ = ["Argon2idHasher"]

_DEFAULT_SALT_BYTES = 16
_DEFAULT_MEMORY_KIB = 65_536
_DEFAULT_TIME_COST = 3
_DEFAULT_PARALLELISM = 4
_DEFAULT_HASH_LENGTH = 32
_MIN_SALT_BYTES = 8


class Argon2idHasher:
    """Argon2id implementation.

    Args:
        memory_kib: Memory budget in KiB.
        time_cost: Number of passes over the memory.
        parallelism: Number of lanes.
        hash_length: Derived key length in bytes.
        salt_bytes: Per-credential salt length.
    """

    def __init__(
        self,
        *,
        memory_kib: int = _DEFAULT_MEMORY_KIB,
        time_cost: int = _DEFAULT_TIME_COST,
        parallelism: int = _DEFAULT_PARALLELISM,
        hash_length: int = _DEFAULT_HASH_LENGTH,
        salt_bytes: int = _DEFAULT_SALT_BYTES,
    ) -> None:
        if memory_kib < 8:
            raise ValueError("memory_kib must be at least 8")
        if time_cost < 1:
            raise ValueError("time_cost must be at least 1")
        if parallelism < 1:
            raise ValueError("parallelism must be at least 1")
        if hash_length < 16:
            raise ValueError("hash_length must be at least 16")
        if salt_bytes < _MIN_SALT_BYTES:
            raise ValueError(f"salt_bytes must be at least {_MIN_SALT_BYTES}")
        self._memory_kib = memory_kib
        self._time_cost = time_cost
        self._parallelism = parallelism
        self._hash_length = hash_length
        self._salt_bytes = salt_bytes

    @property
    def algorithm(self) -> HashAlgorithm:
        return HashAlgorithm.ARGON2ID

    @property
    def salted(self) -> bool:
        """Argon2 always mixes a per-credential salt into the digest."""
        return True

    @property
    def max_password_bytes(self) -> int:
        """Maximum number of password bytes this KDF will process."""
        return MAX_PASSWORD_BYTES

    @property
    def memory_kib(self) -> int:
        return self._memory_kib

    @property
    def time_cost(self) -> int:
        return self._time_cost

    @property
    def parallelism(self) -> int:
        return self._parallelism

    def hash(self, password: str) -> HashDigest:
        """Hash *password* with a fresh random salt."""
        salt = secrets.token_bytes(self._salt_bytes)
        return self._hash_with_salt(password, salt)

    def verify(self, password: str, digest: HashDigest) -> bool:
        """Verify *password* against an Argon2id *digest* in constant time."""
        if digest.algorithm is not HashAlgorithm.ARGON2ID:
            return False
        if digest.salt is None:
            return False
        memory_kib = digest.param_int("m", self._memory_kib)
        time_cost = digest.param_int("t", self._time_cost)
        parallelism = digest.param_int("p", self._parallelism)
        length = digest.param_int("length", len(digest.hash))
        try:
            computed = low_level.hash_secret_raw(
                secret=encode_password(password),
                salt=digest.salt,
                time_cost=time_cost,
                memory_cost=memory_kib,
                parallelism=parallelism,
                hash_len=length,
                type=low_level.Type.ID,
            )
        except (ValueError, MemoryError):
            return False
        return secure_compare_bytes(computed, digest.hash)

    def _hash_with_salt(self, password: str, salt: bytes) -> HashDigest:
        derived = low_level.hash_secret_raw(
            secret=encode_password(password),
            salt=salt,
            time_cost=self._time_cost,
            memory_cost=self._memory_kib,
            parallelism=self._parallelism,
            hash_len=self._hash_length,
            type=low_level.Type.ID,
        )
        return HashDigest(
            algorithm=HashAlgorithm.ARGON2ID,
            hash=derived,
            salt=salt,
            params={
                "m": self._memory_kib,
                "t": self._time_cost,
                "p": self._parallelism,
                "length": self._hash_length,
            },
        )

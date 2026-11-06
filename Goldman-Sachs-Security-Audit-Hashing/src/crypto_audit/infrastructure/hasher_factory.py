"""Hasher factory: resolves a :class:`PasswordHasher` for an algorithm.

The factory is the only place that knows about concrete implementations, so
the application layer stays free of infrastructure imports.
"""

from __future__ import annotations

from ..application.ports import PasswordHasher
from ..domain.algorithms import HashAlgorithm
from ..domain.exceptions import UnsupportedAlgorithmError
from ..domain.policy import HashingPolicy
from .argon2_hasher import Argon2idHasher
from .bcrypt_hasher import BcryptHasher
from .legacy_hashers import LegacyHashHasher
from .pbkdf2_hasher import Pbkdf2Hasher

__all__ = ["HasherRegistry"]


class HasherRegistry:
    """Registry of password hashers keyed by algorithm.

    Args:
        policy: Policy supplying the cost parameters for modern algorithms.

    Example:
        >>> registry = HasherRegistry()
        >>> registry.get(HashAlgorithm.ARGON2ID).algorithm
        <HashAlgorithm.ARGON2ID: 'argon2id'>
    """

    def __init__(self, policy: HashingPolicy | None = None) -> None:
        self._policy = policy or HashingPolicy()
        self._hashers: dict[HashAlgorithm, PasswordHasher] = {}

    # ------------------------------------------------------------------
    def get(self, algorithm: HashAlgorithm) -> PasswordHasher:
        """Return the hasher for *algorithm*.

        Raises:
            UnsupportedAlgorithmError: if the algorithm is unknown.
        """
        try:
            algorithm = HashAlgorithm(algorithm)
        except ValueError as exc:
            raise UnsupportedAlgorithmError(
                f"unsupported algorithm: {algorithm!r}"
            ) from exc
        hasher = self._hashers.get(algorithm)
        if hasher is not None:
            return hasher
        hasher = self._build(algorithm)
        self._hashers[algorithm] = hasher
        return hasher

    def register(self, algorithm: HashAlgorithm, hasher: PasswordHasher) -> None:
        """Override the hasher for *algorithm* (used in tests and migrations)."""
        self._hashers[HashAlgorithm(algorithm)] = hasher

    def _build(self, algorithm: HashAlgorithm) -> PasswordHasher:
        params = self._policy.parameters
        if algorithm is HashAlgorithm.ARGON2ID:
            return Argon2idHasher(
                memory_kib=params.argon2_memory_kib,
                time_cost=params.argon2_time_cost,
                parallelism=params.argon2_parallelism,
                hash_length=params.argon2_hash_length,
                salt_bytes=params.salt_bytes,
            )
        if algorithm is HashAlgorithm.BCRYPT:
            return BcryptHasher(cost=params.bcrypt_cost)
        if algorithm is HashAlgorithm.PBKDF2_SHA256:
            return Pbkdf2Hasher(
                iterations=params.pbkdf2_iterations,
                salt_bytes=params.salt_bytes,
            )
        if algorithm in (HashAlgorithm.MD5, HashAlgorithm.SHA1, HashAlgorithm.SHA256):
            # Legacy credential stores were overwhelmingly unsalted; the hasher
            # still verifies salted legacy digests because verification uses
            # the salt carried by the digest itself.
            return LegacyHashHasher(algorithm, salted=False)
        raise UnsupportedAlgorithmError(f"unsupported algorithm: {algorithm!r}")

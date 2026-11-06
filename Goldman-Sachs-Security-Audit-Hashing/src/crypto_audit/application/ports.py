"""Application-layer ports (interfaces required by the services)."""

from __future__ import annotations

from typing import Protocol, runtime_checkable

from ..domain.algorithms import HashAlgorithm
from ..domain.digest import HashDigest

__all__ = ["PasswordHasher", "HasherFactory"]


@runtime_checkable
class PasswordHasher(Protocol):
    """Port for a password hashing algorithm implementation."""

    @property
    def algorithm(self) -> HashAlgorithm:
        """The algorithm this hasher implements."""
        ...

    def hash(self, password: str) -> HashDigest:
        """Hash *password* with a fresh random salt."""
        ...

    def verify(self, password: str, digest: HashDigest) -> bool:
        """Verify *password* against *digest* in constant time."""
        ...


@runtime_checkable
class HasherFactory(Protocol):
    """Port for resolving a hasher by algorithm."""

    def get(self, algorithm: HashAlgorithm) -> PasswordHasher:
        """Return the hasher implementing *algorithm*."""
        ...

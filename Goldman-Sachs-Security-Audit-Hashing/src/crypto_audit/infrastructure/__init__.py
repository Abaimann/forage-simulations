"""Infrastructure layer: concrete hashing adapters and repository adapters."""

from __future__ import annotations

from .argon2_hasher import Argon2idHasher
from .bcrypt_hasher import BcryptHasher
from .hasher_factory import HasherRegistry
from .legacy_hashers import LegacyHashHasher, UnsupportedLegacyAlgorithm
from .pbkdf2_hasher import Pbkdf2Hasher
from .repository import InMemoryCredentialRepository

__all__ = [
    "Argon2idHasher",
    "BcryptHasher",
    "Pbkdf2Hasher",
    "LegacyHashHasher",
    "UnsupportedLegacyAlgorithm",
    "HasherRegistry",
    "InMemoryCredentialRepository",
]

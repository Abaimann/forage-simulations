"""Domain layer: hash algorithm metadata and classification.

This module contains no I/O and no third-party dependencies. It is the
"vocabulary" of the audit pipeline and is safe to import from anywhere.
"""

from __future__ import annotations

from enum import Enum

__all__ = ["HashAlgorithm", "ALGORITHM_REGISTRY"]


class HashAlgorithm(str, Enum):
    """Password hashing algorithms understood by the pipeline.

    The enum is a :class:`str` subclass so it serialises transparently in
    JSON reports and compares equal to its wire value.
    """

    MD5 = "md5"
    SHA1 = "sha1"
    SHA256 = "sha256"
    PBKDF2_SHA256 = "pbkdf2_sha256"
    BCRYPT = "bcrypt"
    ARGON2ID = "argon2id"

    def __str__(self) -> str:  # pragma: no cover - trivial
        return self.value

    # ------------------------------------------------------------------
    # classification helpers
    # ------------------------------------------------------------------
    @property
    def is_legacy(self) -> bool:
        """True for fast, non-keyed hashes that must never protect credentials."""
        return self in _LEGACY_ALGORITHMS

    @property
    def is_salted(self) -> bool:
        """True if the algorithm is *designed* to use a per-credential salt."""
        return self not in _LEGACY_ALGORITHMS

    @property
    def is_memory_hard(self) -> bool:
        """True if the algorithm consumes a tunable amount of memory per hash."""
        return self in _MEMORY_HARD_ALGORITHMS

    @property
    def is_keyed(self) -> bool:
        """True if the algorithm uses a secret key / pepper (not portable here)."""
        return False

    @property
    def is_approved_for_new_credentials(self) -> bool:
        """NIST SP 800-63B accepted password KDFs."""
        return self in {
            HashAlgorithm.PBKDF2_SHA256,
            HashAlgorithm.BCRYPT,
            HashAlgorithm.ARGON2ID,
        }

    @property
    def min_salt_bytes(self) -> int:
        """Minimum recommended salt length in bytes (NIST SP 800-132)."""
        if self is HashAlgorithm.BCRYPT:
            # bcrypt embeds a fixed 128-bit salt.
            return 16
        return 16

    @property
    def description(self) -> str:
        return _DESCRIPTIONS[self]


_LEGACY_ALGORITHMS = frozenset(
    {
        HashAlgorithm.MD5,
        HashAlgorithm.SHA1,
        HashAlgorithm.SHA256,
    }
)

_MEMORY_HARD_ALGORITHMS = frozenset(
    {
        HashAlgorithm.ARGON2ID,
    }
)

_DESCRIPTIONS = {
    HashAlgorithm.MD5: "MD5 - broken for security use; rainbow-table trivial.",
    HashAlgorithm.SHA1: "SHA-1 - collision attacks are practical; unsuited for passwords.",
    HashAlgorithm.SHA256: "SHA-256 - not a password KDF; no work factor, no salting.",
    HashAlgorithm.PBKDF2_SHA256: "PBKDF2-HMAC-SHA256 - approved, tunable work factor.",
    HashAlgorithm.BCRYPT: "bcrypt - approved, memory-hard-ish, 128-bit embedded salt.",
    HashAlgorithm.ARGON2ID: "Argon2id - preferred; memory-hard, side-channel resistant.",
}

ALGORITHM_REGISTRY: dict[str, HashAlgorithm] = {a.value: a for a in HashAlgorithm}

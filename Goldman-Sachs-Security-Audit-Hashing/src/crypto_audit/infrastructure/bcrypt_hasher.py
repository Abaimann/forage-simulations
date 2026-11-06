"""bcrypt hasher (cost parameter configurable, 128-bit embedded salt).

bcrypt truncates its input at 72 bytes. The truncation is documented in the
NIST SP 800-63B caveat list; this implementation rejects over-long passwords
explicitly rather than silently weakening them.
"""

from __future__ import annotations

import secrets

import bcrypt

from ..application.constant_time import secure_compare_bytes
from ..domain.algorithms import HashAlgorithm
from ..domain.digest import HashDigest
from ..domain.exceptions import PasswordTooLongError
from ..domain.password import encode_password

__all__ = ["BcryptHasher"]

_BCRYPT_MAX_BYTES = 72
#: Length of the "$2b$<cost>$<22-char salt>" prefix in bcrypt's output.
_BCRYPT_SALT_PREFIX_LEN = 29
_MIN_COST = 4
_MAX_COST = 31


class BcryptHasher:
    """bcrypt implementation backed by the ``bcrypt`` package.

    Args:
        cost: Logarithmic work factor (2**cost iterations).
        prefix: bcrypt variant prefix (``b"2b"`` by default).
    """

    def __init__(self, *, cost: int = 12, prefix: bytes = b"2b") -> None:
        if not _MIN_COST <= cost <= _MAX_COST:
            raise ValueError(
                f"cost must be between {_MIN_COST} and {_MAX_COST} (got {cost})"
            )
        self._cost = cost
        self._prefix = prefix

    @property
    def algorithm(self) -> HashAlgorithm:
        return HashAlgorithm.BCRYPT

    @property
    def salted(self) -> bool:
        """bcrypt always embeds a 128-bit salt in its output."""
        return True

    @property
    def cost(self) -> int:
        return self._cost

    @property
    def max_password_bytes(self) -> int:
        """Maximum number of password bytes bcrypt will consider."""
        return _BCRYPT_MAX_BYTES

    def hash(self, password: str) -> HashDigest:
        """Hash *password* with a fresh random salt."""
        encoded = self._encode(password)
        salt = bcrypt.gensalt(rounds=self._cost, prefix=self._prefix)
        raw = bcrypt.hashpw(encoded, salt)
        # bcrypt output layout: "$2b$<cost>$<22-char salt><31-char hash>"
        # The salt prefix is the first 29 bytes; the digest is the last 31.
        salt_part = raw[:_BCRYPT_SALT_PREFIX_LEN]
        hash_part = raw[_BCRYPT_SALT_PREFIX_LEN:]
        return HashDigest(
            algorithm=HashAlgorithm.BCRYPT,
            hash=hash_part,
            salt=salt_part,
            params={"cost": self._cost, "prefix": self._prefix.decode("ascii")},
        )

    def verify(self, password: str, digest: HashDigest) -> bool:
        """Verify *password* against a bcrypt *digest* in constant time."""
        if digest.algorithm is not HashAlgorithm.BCRYPT:
            return False
        if digest.salt is None:
            return False
        try:
            encoded = self._encode(password)
        except PasswordTooLongError:
            return False
        try:
            computed = bcrypt.hashpw(encoded, digest.salt)
        except (ValueError, TypeError):
            return False
        return secure_compare_bytes(computed, digest.salt + digest.hash)

    def _encode(self, password: str) -> bytes:
        encoded = encode_password(password)
        if len(encoded) > _BCRYPT_MAX_BYTES:
            raise PasswordTooLongError(
                "bcrypt truncates passwords at 72 bytes; use Argon2id or "
                f"pre-hash before bcrypt (got {len(encoded)} bytes)"
            )
        return encoded

    @staticmethod
    def random_salt(cost: int = 12) -> bytes:
        """Return a standalone bcrypt salt (useful for migration tooling)."""
        return bcrypt.gensalt(rounds=cost)

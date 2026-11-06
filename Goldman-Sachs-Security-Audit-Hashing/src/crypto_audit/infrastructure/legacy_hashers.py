"""Legacy hashers (MD5 / SHA-1 / SHA-256) used to *verify* old credentials.

These implementations exist only to keep authenticating users whose
credentials were migrated from a legacy store. They must never be used to
create new credentials - the auditor flags every digest they produce.

Both salted and unsalted variants are supported because the legacy estate
contains both. The salted variant uses the standard
``salt || message`` construction.
"""

from __future__ import annotations

import hashlib
import secrets

from ..application.constant_time import secure_compare_bytes
from ..application.ports import PasswordHasher
from ..domain.algorithms import HashAlgorithm
from ..domain.digest import HashDigest
from ..domain.exceptions import InvalidDigestError
from ..domain.password import MAX_PASSWORD_BYTES

__all__ = ["LegacyHashHasher", "UnsupportedLegacyAlgorithm"]

_DEFAULT_SALT_BYTES = 16


class UnsupportedLegacyAlgorithm(ValueError):
    """Raised when an unsupported algorithm is requested."""


class LegacyHashHasher:
    """MD5 / SHA-1 / SHA-256 hasher with optional salting.

    Args:
        algorithm: One of MD5, SHA1 or SHA256.
        salt_bytes: Salt length when salting is enabled.
        salted: Whether to mix a salt into the digest.
    """

    def __init__(
        self,
        algorithm: HashAlgorithm,
        *,
        salt_bytes: int = _DEFAULT_SALT_BYTES,
        salted: bool = True,
    ) -> None:
        if algorithm not in {
            HashAlgorithm.MD5,
            HashAlgorithm.SHA1,
            HashAlgorithm.SHA256,
        }:
            raise UnsupportedLegacyAlgorithm(
                f"{algorithm!r} is not a legacy hash algorithm"
            )
        if salt_bytes < 0:
            raise ValueError("salt_bytes must be non-negative")
        self._algorithm = algorithm
        self._salt_bytes = salt_bytes
        self._salted = salted

    # ------------------------------------------------------------------
    @property
    def algorithm(self) -> HashAlgorithm:
        return self._algorithm

    @property
    def salted(self) -> bool:
        return self._salted

    @property
    def salt_bytes(self) -> int:
        return self._salt_bytes

    @property
    def max_password_bytes(self) -> int:
        """Maximum number of password bytes this KDF will process."""
        return MAX_PASSWORD_BYTES

    # ------------------------------------------------------------------
    def _digest_name(self) -> str:
        return {
            HashAlgorithm.MD5: "md5",
            HashAlgorithm.SHA1: "sha1",
            HashAlgorithm.SHA256: "sha256",
        }[self._algorithm]

    def hash(self, password: str) -> HashDigest:
        """Hash *password*; used only to reproduce legacy digests in tests."""
        encoded = password.encode("utf-8")
        salt = secrets.token_bytes(self._salt_bytes) if self._salted else None
        return HashDigest(
            algorithm=self._algorithm,
            hash=self._compute(encoded, salt),
            salt=salt,
            params={"salted": int(self._salted)},
        )

    def verify(self, password: str, digest: HashDigest) -> bool:
        """Verify *password* against a legacy *digest*.

        Comparison is constant time. A digest whose algorithm differs from the
        hasher's own is rejected without computing anything.
        """
        if digest.algorithm is not self._algorithm:
            return False
        try:
            computed = self._compute(password.encode("utf-8"), digest.salt)
        except (UnicodeEncodeError, ValueError):
            return False
        return secure_compare_bytes(computed, digest.hash)

    def _compute(self, encoded: bytes, salt: bytes | None) -> bytes:
        hasher = hashlib.new(self._digest_name())
        if salt:
            hasher.update(salt)
        hasher.update(encoded)
        return hasher.digest()


def parse_legacy_digest(payload: str) -> HashDigest:
    """Parse a legacy digest from its wire format.

    Raises:
        InvalidDigestError: when the payload cannot be parsed.
    """
    return HashDigest.decode(payload)

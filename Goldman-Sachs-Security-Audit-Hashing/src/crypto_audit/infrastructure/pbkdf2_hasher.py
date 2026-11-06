"""PBKDF2-HMAC-SHA256 hasher.

PBKDF2 is approved by NIST SP 800-63B as a fallback when Argon2id is not
available. The recommended iteration count is 600,000 for SHA-256 (2025
revision of SP 800-63B section 3.1.1.2).
"""

from __future__ import annotations

import hashlib
import secrets

from ..application.constant_time import secure_compare_bytes
from ..domain.algorithms import HashAlgorithm
from ..domain.digest import HashDigest
from ..domain.password import MAX_PASSWORD_BYTES, encode_password

__all__ = ["Pbkdf2Hasher"]

_DEFAULT_SALT_BYTES = 16
_DEFAULT_ITERATIONS = 600_000
_DEFAULT_LENGTH = 32
_MIN_ITERATIONS = 1_000


class Pbkdf2Hasher:
    """PBKDF2-HMAC-SHA256 implementation.

    Args:
        iterations: HMAC iteration count.
        salt_bytes: Per-credential salt length.
        hash_length: Derived key length in bytes.
    """

    def __init__(
        self,
        *,
        iterations: int = _DEFAULT_ITERATIONS,
        salt_bytes: int = _DEFAULT_SALT_BYTES,
        hash_length: int = _DEFAULT_LENGTH,
    ) -> None:
        if iterations < _MIN_ITERATIONS:
            raise ValueError(
                f"iterations must be >= {_MIN_ITERATIONS} (got {iterations})"
            )
        if salt_bytes < 8:
            raise ValueError("salt_bytes must be at least 8")
        if hash_length < 16:
            raise ValueError("hash_length must be at least 16")
        self._iterations = iterations
        self._salt_bytes = salt_bytes
        self._hash_length = hash_length

    @property
    def algorithm(self) -> HashAlgorithm:
        return HashAlgorithm.PBKDF2_SHA256

    @property
    def salted(self) -> bool:
        """PBKDF2 always mixes a per-credential salt into the digest."""
        return True

    @property
    def max_password_bytes(self) -> int:
        """Maximum number of password bytes this KDF will process."""
        return MAX_PASSWORD_BYTES

    @property
    def iterations(self) -> int:
        return self._iterations

    @property
    def salt_bytes(self) -> int:
        return self._salt_bytes

    def hash(self, password: str) -> HashDigest:
        """Hash *password* with a fresh 128-bit salt."""
        salt = secrets.token_bytes(self._salt_bytes)
        return self._hash_with_salt(password, salt)

    def verify(self, password: str, digest: HashDigest) -> bool:
        """Verify *password* against a PBKDF2 *digest* in constant time."""
        if digest.algorithm is not HashAlgorithm.PBKDF2_SHA256:
            return False
        if digest.salt is None:
            return False
        iterations = digest.param_int("iterations", self._iterations)
        if iterations < 1:
            return False
        length = digest.param_int("length", len(digest.hash))
        try:
            computed = hashlib.pbkdf2_hmac(
                "sha256",
                encode_password(password),
                digest.salt,
                iterations,
                dklen=length,
            )
        except (ValueError, UnicodeEncodeError):
            return False
        return secure_compare_bytes(computed, digest.hash)

    def _hash_with_salt(self, password: str, salt: bytes) -> HashDigest:
        derived = hashlib.pbkdf2_hmac(
            "sha256",
            encode_password(password),
            salt,
            self._iterations,
            dklen=self._hash_length,
        )
        return HashDigest(
            algorithm=HashAlgorithm.PBKDF2_SHA256,
            hash=derived,
            salt=salt,
            params={"iterations": self._iterations, "length": self._hash_length},
        )

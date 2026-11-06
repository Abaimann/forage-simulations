"""Canonical password handling (encoding + normalisation).

Centralising normalisation avoids the classic "unicode confusable" bypass where
a password is hashed in NFC at registration and in NFD at login.
"""

from __future__ import annotations

import unicodedata

from ..domain.exceptions import PasswordTooLongError

__all__ = ["normalize_password", "encode_password", "MAX_PASSWORD_BYTES"]

#: Hard ceiling applied to every KDF to bound attacker-controlled work.
#: bcrypt itself truncates at 72 bytes, which would be a silent weakening.
MAX_PASSWORD_BYTES = 4096


def normalize_password(password: str) -> str:
    """Return the canonical form of *password*.

    Normalisation applies Unicode NFKC, which folds compatibility characters
    (e.g. full-width Latin) onto their canonical equivalents. Two passwords
    that look identical to a human therefore hash identically.
    """
    if not isinstance(password, str):
        raise TypeError("password must be a str")
    return unicodedata.normalize("NFKC", password)


def encode_password(password: str, *, max_bytes: int = MAX_PASSWORD_BYTES) -> bytes:
    """Normalise and UTF-8 encode *password*, enforcing a byte ceiling.

    Raises:
        PasswordTooLongError: if the encoded form exceeds *max_bytes*.
    """
    encoded = normalize_password(password).encode("utf-8")
    if len(encoded) > max_bytes:
        raise PasswordTooLongError(
            f"password exceeds {max_bytes} bytes after UTF-8 encoding "
            f"(got {len(encoded)} bytes)"
        )
    return encoded

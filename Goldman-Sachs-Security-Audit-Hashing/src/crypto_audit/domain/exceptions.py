"""Domain exceptions raised by the credential audit pipeline."""

from __future__ import annotations

__all__ = [
    "CryptoAuditError",
    "InvalidDigestError",
    "UnsupportedAlgorithmError",
    "PasswordPolicyError",
    "PasswordTooLongError",
    "RepositoryError",
]


class CryptoAuditError(Exception):
    """Base class for every error raised by this package."""


class InvalidDigestError(CryptoAuditError):
    """A stored credential digest is malformed and cannot be parsed."""


class UnsupportedAlgorithmError(CryptoAuditError):
    """The digest references an algorithm the pipeline does not implement."""


class PasswordPolicyError(CryptoAuditError):
    """A candidate password violates the configured acceptance policy."""


class PasswordTooLongError(PasswordPolicyError):
    """A candidate password exceeds the byte limit of the target algorithm."""


class RepositoryError(CryptoAuditError):
    """The credential repository failed to satisfy a request."""

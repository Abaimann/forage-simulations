"""Domain layer: entities, value objects, policy and findings."""

from __future__ import annotations

from .algorithms import ALGORITHM_REGISTRY, HashAlgorithm
from .credential import Credential, CredentialRepository
from .digest import HashDigest
from .exceptions import (
    CryptoAuditError,
    InvalidDigestError,
    PasswordPolicyError,
    PasswordTooLongError,
    RepositoryError,
    UnsupportedAlgorithmError,
)
from .findings import AuditFinding, AuditReport, FindingCategory, Severity
from .password import MAX_PASSWORD_BYTES, encode_password, normalize_password
from .policy import AlgorithmParameters, HashingPolicy

__all__ = [
    "ALGORITHM_REGISTRY",
    "HashAlgorithm",
    "Credential",
    "CredentialRepository",
    "HashDigest",
    "CryptoAuditError",
    "InvalidDigestError",
    "UnsupportedAlgorithmError",
    "PasswordPolicyError",
    "PasswordTooLongError",
    "RepositoryError",
    "AuditFinding",
    "AuditReport",
    "FindingCategory",
    "Severity",
    "MAX_PASSWORD_BYTES",
    "encode_password",
    "normalize_password",
    "AlgorithmParameters",
    "HashingPolicy",
]

"""Cryptographic Verification & Credential Security Audit Pipeline.

A modular reference implementation of a credential security audit pipeline:

* :mod:`crypto_audit.domain`      - entities, value objects and policy.
* :mod:`crypto_audit.application` - use cases (audit, upgrade, brute force).
* :mod:`crypto_audit.infrastructure` - hashing adapters and repositories.

The public API is re-exported here for convenience.
"""

from __future__ import annotations

from .application.auditor import AuditStatistics, CredentialAuditor
from .application.brute_force import (
    BruteForceEstimate,
    BruteForceTester,
    CollisionReport,
    DictionaryAttackResult,
)
from .application.constant_time import secure_compare, secure_compare_bytes
from .application.entropy import (
    EntropyAssessment,
    analyse_password_entropy,
    estimate_password_entropy_bits,
    shannon_entropy_bits,
)
from .application.upgrade_pipeline import AuthenticationResult, UpgradePipeline
from .domain.algorithms import HashAlgorithm
from .domain.credential import Credential, CredentialRepository
from .domain.digest import HashDigest
from .domain.exceptions import (
    CryptoAuditError,
    InvalidDigestError,
    PasswordTooLongError,
    UnsupportedAlgorithmError,
)
from .domain.findings import AuditFinding, AuditReport, FindingCategory, Severity
from .domain.policy import AlgorithmParameters, HashingPolicy
from .infrastructure.argon2_hasher import Argon2idHasher
from .infrastructure.bcrypt_hasher import BcryptHasher
from .infrastructure.hasher_factory import HasherRegistry
from .infrastructure.legacy_hashers import LegacyHashHasher
from .infrastructure.pbkdf2_hasher import Pbkdf2Hasher
from .infrastructure.repository import InMemoryCredentialRepository

__version__ = "1.0.0"

__all__ = [
    "__version__",
    # domain
    "HashAlgorithm",
    "HashDigest",
    "Credential",
    "CredentialRepository",
    "HashingPolicy",
    "AlgorithmParameters",
    "AuditFinding",
    "AuditReport",
    "FindingCategory",
    "Severity",
    "CryptoAuditError",
    "InvalidDigestError",
    "UnsupportedAlgorithmError",
    "PasswordTooLongError",
    # application
    "CredentialAuditor",
    "AuditStatistics",
    "UpgradePipeline",
    "AuthenticationResult",
    "BruteForceTester",
    "BruteForceEstimate",
    "CollisionReport",
    "DictionaryAttackResult",
    "secure_compare",
    "secure_compare_bytes",
    "shannon_entropy_bits",
    "estimate_password_entropy_bits",
    "analyse_password_entropy",
    "EntropyAssessment",
    # infrastructure
    "Argon2idHasher",
    "BcryptHasher",
    "Pbkdf2Hasher",
    "LegacyHashHasher",
    "HasherRegistry",
    "InMemoryCredentialRepository",
]

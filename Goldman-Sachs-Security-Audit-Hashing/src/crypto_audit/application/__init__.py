"""Application layer: use cases orchestrating domain logic and ports."""

from __future__ import annotations

from .auditor import AuditStatistics, CredentialAuditor
from .brute_force import (
    BruteForceEstimate,
    BruteForceTester,
    CollisionReport,
    DictionaryAttackResult,
)
from .constant_time import (
    TimingAttackError,
    constant_time_equals,
    secure_compare,
    secure_compare_bytes,
)
from .entropy import (
    EntropyAssessment,
    analyse_password_entropy,
    entropy_profile,
    estimate_password_entropy_bits,
    normalised_entropy_bits_per_byte,
    shannon_entropy_bits,
)
from .ports import HasherFactory, PasswordHasher
from .upgrade_pipeline import AuthenticationResult, UpgradePipeline

__all__ = [
    "CredentialAuditor",
    "AuditStatistics",
    "BruteForceTester",
    "BruteForceEstimate",
    "CollisionReport",
    "DictionaryAttackResult",
    "secure_compare",
    "secure_compare_bytes",
    "constant_time_equals",
    "TimingAttackError",
    "EntropyAssessment",
    "analyse_password_entropy",
    "entropy_profile",
    "estimate_password_entropy_bits",
    "normalised_entropy_bits_per_byte",
    "shannon_entropy_bits",
    "PasswordHasher",
    "HasherFactory",
    "UpgradePipeline",
    "AuthenticationResult",
]

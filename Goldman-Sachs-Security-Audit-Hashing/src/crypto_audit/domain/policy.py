"""Cryptographic policy: parameters, thresholds and minimum acceptable settings.

The policy object is the single source of truth for "what is good enough".
It is deliberately data-only and immutable so it can be serialised into audit
reports and compared across environments (dev vs. prod).
"""

from __future__ import annotations

from dataclasses import dataclass, field, replace
from typing import Any, Mapping

from .algorithms import HashAlgorithm
from .digest import HashDigest

__all__ = ["AlgorithmParameters", "HashingPolicy"]


@dataclass(frozen=True)
class AlgorithmParameters:
    """Cost parameters for a single algorithm.

    Attributes:
        salt_bytes: Length of the per-credential random salt.
        pbkdf2_iterations: HMAC-SHA256 iteration count for PBKDF2.
        bcrypt_cost: bcrypt logarithmic cost (2**cost rounds).
        argon2_memory_kib: Argon2 memory budget in KiB.
        argon2_time_cost: Argon2 number of passes over memory.
        argon2_parallelism: Argon2 lane count.
        argon2_hash_length: Argon2 output length in bytes.
    """

    salt_bytes: int = 16
    pbkdf2_iterations: int = 600_000
    bcrypt_cost: int = 12
    argon2_memory_kib: int = 65_536
    argon2_time_cost: int = 3
    argon2_parallelism: int = 4
    argon2_hash_length: int = 32

    def for_algorithm(self, algorithm: HashAlgorithm) -> dict[str, Any]:
        """Return the parameter subset that applies to *algorithm*."""
        if algorithm is HashAlgorithm.PBKDF2_SHA256:
            return {"iterations": self.pbkdf2_iterations}
        if algorithm is HashAlgorithm.BCRYPT:
            return {"cost": self.bcrypt_cost}
        if algorithm is HashAlgorithm.ARGON2ID:
            return {
                "m": self.argon2_memory_kib,
                "t": self.argon2_time_cost,
                "p": self.argon2_parallelism,
                "length": self.argon2_hash_length,
            }
        return {}


@dataclass(frozen=True)
class HashingPolicy:
    """Target algorithm, cost parameters and audit thresholds.

    The default values follow NIST SP 800-63B section 3.1.1.2 (updated 2025):
    Argon2id is the preferred KDF, with PBKDF2-HMAC-SHA256 (>= 600,000
    iterations) and bcrypt as acceptable alternatives.
    """

    target_algorithm: HashAlgorithm = HashAlgorithm.ARGON2ID
    parameters: AlgorithmParameters = field(default_factory=AlgorithmParameters)

    # --- audit thresholds -------------------------------------------------
    #: Minimum salt length (bytes) required by the policy.
    minimum_salt_bytes: int = 16
    #: Minimum PBKDF2 iteration count accepted during an audit.
    minimum_pbkdf2_iterations: int = 600_000
    #: Minimum bcrypt cost accepted during an audit.
    minimum_bcrypt_cost: int = 10
    #: Minimum Argon2 memory (KiB) accepted during an audit.
    minimum_argon2_memory_kib: int = 32_768
    #: Minimum Argon2 time cost accepted during an audit.
    minimum_argon2_time_cost: int = 3
    #: Minimum entropy *density* (0..1) required from a stored digest.
    #: Density is used rather than raw bits/byte because the Shannon entropy
    #: of a short sample is bounded by log2(sample length).
    minimum_digest_entropy_density: float = 0.85
    #: Minimum password length accepted by the verifier.
    minimum_password_length: int = 12
    #: Minimum estimated entropy (bits) accepted for a memorised secret.
    #: NIST SP 800-63B section 3.1.1.1 recommends at least 64 bits.
    minimum_password_entropy_bits: float = 64.0
    #: Maximum password length accepted by the verifier (bytes of UTF-8).
    maximum_password_length: int = 4096

    # ------------------------------------------------------------------
    def with_target(self, algorithm: HashAlgorithm) -> "HashingPolicy":
        """Return a copy targeting *algorithm*."""
        return replace(self, target_algorithm=algorithm)

    def with_parameters(self, **overrides: Any) -> "HashingPolicy":
        """Return a copy with individual cost parameters overridden."""
        return replace(
            self,
            parameters=replace(self.parameters, **overrides),
        )

    def target_parameters(self) -> dict[str, Any]:
        """Cost parameters for the configured target algorithm."""
        return self.parameters.for_algorithm(self.target_algorithm)

    # ------------------------------------------------------------------
    # digest evaluation
    # ------------------------------------------------------------------
    def digest_is_acceptable(self, digest: HashDigest) -> bool:
        """True when *digest* satisfies every policy requirement."""
        if not digest.algorithm.is_approved_for_new_credentials:
            return False
        if digest.salt is None or len(digest.salt) < self.minimum_salt_bytes:
            return False
        return self.parameters_are_acceptable(digest)

    def parameters_are_acceptable(self, digest: HashDigest) -> bool:
        """True when the stored cost parameters meet the policy minima."""
        if digest.algorithm is HashAlgorithm.PBKDF2_SHA256:
            return digest.param_int("iterations", 0) >= self.minimum_pbkdf2_iterations
        if digest.algorithm is HashAlgorithm.BCRYPT:
            return digest.param_int("cost", 0) >= self.minimum_bcrypt_cost
        if digest.algorithm is HashAlgorithm.ARGON2ID:
            memory_ok = (
                digest.param_int("m", 0) >= self.minimum_argon2_memory_kib
            )
            time_ok = (
                digest.param_int("t", 0) >= self.minimum_argon2_time_cost
            )
            return memory_ok and time_ok
        return False

    def needs_rehash(self, digest: HashDigest) -> bool:
        """True when *digest* must be replaced by a fresh, policy-compliant one.

        This covers: legacy algorithms, missing/short salts, outdated cost
        parameters and any algorithm that is not the configured target.
        """
        if digest.algorithm is not self.target_algorithm:
            return True
        if digest.salt is None or len(digest.salt) < self.minimum_salt_bytes:
            return True
        return not self.parameters_are_acceptable(digest)

    def describe(self) -> Mapping[str, Any]:
        """Human/machine readable description used in audit reports."""
        return {
            "target_algorithm": self.target_algorithm.value,
            "minimum_salt_bytes": self.minimum_salt_bytes,
            "minimum_pbkdf2_iterations": self.minimum_pbkdf2_iterations,
            "minimum_bcrypt_cost": self.minimum_bcrypt_cost,
            "minimum_argon2_memory_kib": self.minimum_argon2_memory_kib,
            "minimum_argon2_time_cost": self.minimum_argon2_time_cost,
            "minimum_digest_entropy_density": self.minimum_digest_entropy_density,
            "minimum_password_length": self.minimum_password_length,
            "minimum_password_entropy_bits": self.minimum_password_entropy_bits,
            "maximum_password_length": self.maximum_password_length,
            "target_parameters": self.target_parameters(),
        }

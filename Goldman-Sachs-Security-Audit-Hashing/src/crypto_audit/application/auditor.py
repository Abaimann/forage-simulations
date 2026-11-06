"""Security auditor: analyses a credential estate and reports findings.

The auditor is a pure read-only analysis service. It never mutates stored
credentials; remediation is performed by :class:`UpgradePipeline`.
"""

from __future__ import annotations

from collections import Counter, defaultdict
from dataclasses import dataclass
from typing import Iterable, Mapping, Sequence

from ..domain.algorithms import HashAlgorithm
from ..domain.credential import Credential, CredentialRepository
from ..domain.digest import HashDigest
from ..domain.findings import AuditFinding, AuditReport, FindingCategory, Severity
from ..domain.policy import HashingPolicy
from .entropy import entropy_density, entropy_profile, unique_ratio

__all__ = ["CredentialAuditor", "AuditStatistics"]


@dataclass(frozen=True)
class AuditStatistics:
    """Quantitative summary of the audited estate."""

    algorithm_distribution: Mapping[str, int]
    salted_count: int
    unsalted_count: int
    salt_lengths: Mapping[int, int]
    digest_entropy: Mapping[str, float]
    duplicate_digest_groups: int
    duplicate_digest_count: int
    salt_reuse_groups: int
    salt_reuse_count: int

    def to_dict(self) -> dict[str, object]:
        return {
            "algorithm_distribution": dict(self.algorithm_distribution),
            "salted_count": self.salted_count,
            "unsalted_count": self.unsalted_count,
            "salt_lengths": {str(k): v for k, v in self.salt_lengths.items()},
            "digest_entropy": dict(self.digest_entropy),
            "duplicate_digest_groups": self.duplicate_digest_groups,
            "duplicate_digest_count": self.duplicate_digest_count,
            "salt_reuse_groups": self.salt_reuse_groups,
            "salt_reuse_count": self.salt_reuse_count,
        }


class CredentialAuditor:
    """Analyses stored credentials for cryptographic weakness.

    Args:
        policy: The policy that defines acceptable hashing practice.
    """

    def __init__(self, policy: HashingPolicy | None = None) -> None:
        self._policy = policy or HashingPolicy()

    @property
    def policy(self) -> HashingPolicy:
        return self._policy

    # ------------------------------------------------------------------
    def audit(
        self,
        repository: CredentialRepository,
        *,
        candidates: Mapping[str, str] | None = None,
    ) -> AuditReport:
        """Audit every credential in *repository*.

        Args:
            repository: Source of credentials.
            candidates: Optional mapping of ``username -> plaintext`` used to
                perform offline strength checks (dictionary screening) for
                accounts whose legacy digest has already been cracked. The
                audit never stores or reports the plaintext itself.

        Returns:
            A populated :class:`AuditReport`.
        """
        credentials = repository.list_all()
        findings: list[AuditFinding] = []
        findings.extend(self._audit_algorithm_usage(credentials))
        findings.extend(self._audit_salting(credentials))
        findings.extend(self._audit_parameters(credentials))
        findings.extend(self._audit_entropy(credentials))
        findings.extend(self._audit_reuse(credentials))
        findings.extend(self._audit_candidates(candidates or {}))
        findings.extend(self._audit_compliance(credentials))

        findings.sort(key=lambda f: f.sort_key)
        return AuditReport(
            findings=tuple(findings),
            total_credentials=len(credentials),
            policy=self._policy.describe(),
            statistics=self._statistics(credentials).to_dict(),
        )

    # ------------------------------------------------------------------
    # individual checks
    # ------------------------------------------------------------------
    def _audit_algorithm_usage(
        self, credentials: Sequence[Credential]
    ) -> Iterable[AuditFinding]:
        for credential in credentials:
            algorithm = credential.digest.algorithm
            if algorithm.is_legacy:
                yield AuditFinding(
                    category=FindingCategory.WEAK_ALGORITHM,
                    severity=Severity.CRITICAL,
                    username=credential.username,
                    message=(
                        f"Credential uses {algorithm.value.upper()}, which is not a "
                        "password KDF: it is fast, unsalted by default and "
                        "trivially reversible via rainbow tables."
                    ),
                    recommendation=(
                        "Re-hash with Argon2id (preferred), PBKDF2-HMAC-SHA256 "
                        "(>=600,000 iterations) or bcrypt (cost >= 12) using a "
                        "per-credential random salt."
                    ),
                    evidence={
                        "algorithm": algorithm.value,
                        "salted": credential.digest.is_salted,
                        "digest_length_bits": len(credential.digest.hash) * 8,
                    },
                )

    def _audit_salting(self, credentials: Sequence[Credential]) -> Iterable[AuditFinding]:
        for credential in credentials:
            digest = credential.digest
            if digest.salt is None:
                yield AuditFinding(
                    category=FindingCategory.MISSING_SALT,
                    severity=Severity.CRITICAL,
                    username=credential.username,
                    message=(
                        f"Credential is stored without a salt: identical passwords "
                        f"produce identical digests and pre-computation tables apply "
                        f"to every account."
                    ),
                    recommendation=(
                        "Re-hash with a unique, cryptographically random salt of at "
                        f"least {self._policy.minimum_salt_bytes} bytes per credential."
                    ),
                    evidence={
                        "algorithm": digest.algorithm.value,
                        "salt": None,
                    },
                )
            elif len(digest.salt) < self._policy.minimum_salt_bytes:
                yield AuditFinding(
                    category=FindingCategory.SHORT_SALT,
                    severity=Severity.HIGH,
                    username=credential.username,
                    message=(
                        f"Salt is only {len(digest.salt)} bytes; the policy requires "
                        f"at least {self._policy.minimum_salt_bytes} bytes."
                    ),
                    recommendation=(
                        "Re-hash with a fresh salt of at least "
                        f"{self._policy.minimum_salt_bytes} random bytes."
                    ),
                    evidence={
                        "algorithm": digest.algorithm.value,
                        "salt_length": len(digest.salt),
                    },
                )

    def _audit_parameters(self, credentials: Sequence[Credential]) -> Iterable[AuditFinding]:
        for credential in credentials:
            digest = credential.digest
            algorithm = digest.algorithm
            if not algorithm.is_approved_for_new_credentials:
                continue
            if self._policy.parameters_are_acceptable(digest):
                continue
            if algorithm is HashAlgorithm.PBKDF2_SHA256:
                detail = (
                    f"iterations={digest.param_int('iterations', 0)} < "
                    f"{self._policy.minimum_pbkdf2_iterations}"
                )
            elif algorithm is HashAlgorithm.BCRYPT:
                detail = (
                    f"cost={digest.param_int('cost', 0)} < "
                    f"{self._policy.minimum_bcrypt_cost}"
                )
            else:
                detail = (
                    f"memory={digest.param_int('m', 0)} KiB / "
                    f"time={digest.param_int('t', 0)} below policy "
                    f"({self._policy.minimum_argon2_memory_kib} KiB / "
                    f"{self._policy.minimum_argon2_time_cost} passes)"
                )
            yield AuditFinding(
                category=FindingCategory.WEAK_PARAMETERS,
                severity=Severity.HIGH,
                username=credential.username,
                message=(
                    f"{algorithm.value} work factor is below the policy minimum "
                    f"({detail}); it is too cheap for offline cracking."
                ),
                recommendation=(
                    "Re-hash with policy-compliant parameters "
                    f"{self._policy.target_parameters()}."
                ),
                evidence={
                    "algorithm": algorithm.value,
                    "parameters": dict(digest.params),
                },
            )

    def _audit_entropy(self, credentials: Sequence[Credential]) -> Iterable[AuditFinding]:
        for credential in credentials:
            digest = credential.digest
            density = entropy_density(digest.hash)
            if density < self._policy.minimum_digest_entropy_density:
                yield AuditFinding(
                    category=FindingCategory.LOW_ENTROPY,
                    severity=Severity.HIGH,
                    username=credential.username,
                    message=(
                        f"Stored digest shows only {density:.3f} entropy density "
                        f"(policy requires {self._policy.minimum_digest_entropy_density}); "
                        "this pattern is typical of a truncated or constant hash."
                    ),
                    recommendation=(
                        "Re-hash with a modern KDF producing a full-length, "
                        "high-entropy digest."
                    ),
                    evidence={
                        "algorithm": digest.algorithm.value,
                        "entropy_density": density,
                        "digest_length_bits": len(digest.hash) * 8,
                    },
                )

    def _audit_reuse(self, credentials: Sequence[Credential]) -> Iterable[AuditFinding]:
        by_digest: dict[bytes, list[Credential]] = defaultdict(list)
        by_salt: dict[bytes, list[Credential]] = defaultdict(list)
        for credential in credentials:
            by_digest[credential.digest.hash].append(credential)
            if credential.digest.salt:
                by_salt[credential.digest.salt].append(credential)

        for digest_hash, group in by_digest.items():
            if len(group) < 2:
                continue
            usernames = sorted(c.username for c in group)
            yield AuditFinding(
                category=FindingCategory.PASSWORD_REUSE,
                severity=Severity.HIGH,
                username="*",
                message=(
                    f"{len(group)} accounts share an identical digest "
                    f"({', '.join(usernames)}); unsalted hashes reveal that these "
                    "users share the same password."
                ),
                recommendation=(
                    "Force a password reset for every affected account and require "
                    "unique, high-entropy credentials."
                ),
                evidence={
                    "usernames": usernames,
                    "digest_hex": digest_hash.hex()[:32],
                },
            )

        for salt, group in by_salt.items():
            if len(group) < 2:
                continue
            usernames = sorted(c.username for c in group)
            yield AuditFinding(
                category=FindingCategory.TIMING_RISK,
                severity=Severity.MEDIUM,
                username="*",
                message=(
                    f"A salt is reused across {len(group)} accounts "
                    f"({', '.join(usernames)}); a reused salt weakens the "
                    "protection that salting is supposed to provide."
                ),
                recommendation=(
                    "Ensure each credential is hashed with an independent, "
                    "cryptographically random salt."
                ),
                evidence={"usernames": usernames},
            )

    def _audit_candidates(
        self, candidates: Mapping[str, str]
    ) -> Iterable[AuditFinding]:
        from .entropy import analyse_password_entropy

        for username, plaintext in candidates.items():
            # NIST SP 800-63B: require at least 64 bits of estimated entropy
            # for a single-factor secret.
            assessment = analyse_password_entropy(
                plaintext, minimum_bits=self._policy.minimum_password_entropy_bits
            )
            if len(plaintext) < self._policy.minimum_password_length:
                yield AuditFinding(
                    category=FindingCategory.POLICY_NON_COMPLIANT,
                    severity=Severity.HIGH,
                    username=username,
                    message=(
                        f"Password length is {len(plaintext)} characters; the policy "
                        f"requires at least {self._policy.minimum_password_length}."
                    ),
                    recommendation=(
                        "Require a passphrase of at least "
                        f"{self._policy.minimum_password_length} characters."
                    ),
                    evidence={"length": len(plaintext)},
                )
            elif not assessment.is_strong:
                yield AuditFinding(
                    category=FindingCategory.LOW_ENTROPY,
                    severity=Severity.MEDIUM,
                    username=username,
                    message=(
                        "Recovered password has an estimated "
                        f"{assessment.entropy_bits:.0f} bits of entropy and a "
                        f"restricted character set ({assessment.charset_size} symbols); "
                        "it is susceptible to dictionary attacks."
                    ),
                    recommendation=(
                        "Require generated passphrases from a wordlist or "
                        "random generator instead of user-chosen strings."
                    ),
                    evidence=assessment.to_dict(),
                )

    def _audit_compliance(self, credentials: Sequence[Credential]) -> Iterable[AuditFinding]:
        for credential in credentials:
            digest = credential.digest
            if not self._policy.digest_is_acceptable(digest):
                continue
            yield AuditFinding(
                category=FindingCategory.COMPLIANT,
                severity=Severity.INFO,
                username=credential.username,
                message=(
                    f"Credential is compliant: {digest.algorithm.value} with a "
                    f"{len(digest.salt or b'')}-byte salt and policy-compliant "
                    "parameters."
                ),
                recommendation="No action required; keep the credential current.",
                evidence={
                    "algorithm": digest.algorithm.value,
                    "parameters": dict(digest.params),
                },
            )

    # ------------------------------------------------------------------
    def _statistics(self, credentials: Sequence[Credential]) -> AuditStatistics:
        algorithms = Counter(c.digest.algorithm.value for c in credentials)
        salt_lengths: Counter[int] = Counter()
        salted = unsalted = 0
        for credential in credentials:
            digest = credential.digest
            if digest.salt is None:
                unsalted += 1
            else:
                salted += 1
                salt_lengths[len(digest.salt)] += 1

        digests = [c.digest.hash for c in credentials]
        salts = [c.digest.salt for c in credentials if c.digest.salt]

        digest_groups = Counter(digests)
        salt_groups = Counter(salts)
        return AuditStatistics(
            algorithm_distribution=dict(algorithms),
            salted_count=salted,
            unsalted_count=unsalted,
            salt_lengths=dict(salt_lengths),
            digest_entropy=entropy_profile(digests),
            duplicate_digest_groups=sum(1 for v in digest_groups.values() if v > 1),
            duplicate_digest_count=sum(v for v in digest_groups.values() if v > 1),
            salt_reuse_groups=sum(1 for v in salt_groups.values() if v > 1),
            salt_reuse_count=sum(v for v in salt_groups.values() if v > 1),
        )

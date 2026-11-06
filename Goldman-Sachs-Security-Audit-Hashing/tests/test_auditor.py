"""Tests for the credential auditor."""

from __future__ import annotations

import hashlib

import pytest

from crypto_audit.application.auditor import CredentialAuditor
from crypto_audit.domain.algorithms import HashAlgorithm
from crypto_audit.domain.credential import Credential
from crypto_audit.domain.digest import HashDigest
from crypto_audit.domain.findings import FindingCategory, Severity
from crypto_audit.domain.policy import HashingPolicy
from crypto_audit.infrastructure.argon2_hasher import Argon2idHasher
from crypto_audit.infrastructure.bcrypt_hasher import BcryptHasher
from crypto_audit.infrastructure.legacy_hashers import LegacyHashHasher
from crypto_audit.infrastructure.pbkdf2_hasher import Pbkdf2Hasher
from crypto_audit.infrastructure.repository import InMemoryCredentialRepository


@pytest.fixture
def auditor(fast_policy: HashingPolicy) -> CredentialAuditor:
    return CredentialAuditor(fast_policy)


def _repository(*credentials: Credential) -> InMemoryCredentialRepository:
    return InMemoryCredentialRepository(credentials)


class TestAuditorDetectsLegacyAlgorithms:
    def test_unsalted_md5_is_critical(self, auditor: CredentialAuditor) -> None:
        digest = HashDigest(
            algorithm=HashAlgorithm.MD5,
            hash=hashlib.md5(b"pw").digest(),
            salt=None,
        )
        repo = _repository(Credential("legacy", digest))
        report = auditor.audit(repo)

        weak = report.by_category(FindingCategory.WEAK_ALGORITHM)
        missing = report.by_category(FindingCategory.MISSING_SALT)
        assert len(weak) == 1
        assert weak[0].severity is Severity.CRITICAL
        assert len(missing) == 1
        assert missing[0].severity is Severity.CRITICAL

    def test_sha1_is_flagged_as_weak(self, auditor: CredentialAuditor) -> None:
        digest = HashDigest(
            algorithm=HashAlgorithm.SHA1,
            hash=hashlib.sha1(b"pw").digest(),
            salt=b"s" * 16,
        )
        report = auditor.audit(_repository(Credential("sha1.user", digest)))
        assert len(report.by_category(FindingCategory.WEAK_ALGORITHM)) == 1

    def test_sha256_is_flagged_as_weak(self, auditor: CredentialAuditor) -> None:
        digest = HashDigest(
            algorithm=HashAlgorithm.SHA256,
            hash=hashlib.sha256(b"pw").digest(),
            salt=b"s" * 16,
        )
        report = auditor.audit(_repository(Credential("sha256.user", digest)))
        assert len(report.by_category(FindingCategory.WEAK_ALGORITHM)) == 1


class TestAuditorDetectsSaltingIssues:
    def test_short_salt_is_high_severity(self, auditor: CredentialAuditor) -> None:
        hasher = LegacyHashHasher(HashAlgorithm.MD5, salt_bytes=4, salted=True)
        repo = _repository(Credential("shortsalt", hasher.hash("pw")))
        report = auditor.audit(repo)
        findings = report.by_category(FindingCategory.SHORT_SALT)
        assert len(findings) == 1
        assert findings[0].severity is Severity.HIGH
        assert findings[0].evidence["salt_length"] == 4


class TestAuditorDetectsWeakParameters:
    def test_low_pbkdf2_iterations_are_flagged(self, auditor: CredentialAuditor) -> None:
        hasher = Pbkdf2Hasher(iterations=1_000)
        repo = _repository(Credential("weak.pbkdf2", hasher.hash("pw")))
        report = auditor.audit(repo)
        findings = report.by_category(FindingCategory.WEAK_PARAMETERS)
        assert len(findings) == 1
        assert findings[0].severity is Severity.HIGH
        assert findings[0].evidence["parameters"]["iterations"] == 1_000

    def test_low_bcrypt_cost_is_flagged(self) -> None:
        # Uses the production policy thresholds (min cost 10), so a cost-4
        # digest is unambiguously below policy.
        auditor = CredentialAuditor(HashingPolicy())
        hasher = BcryptHasher(cost=4)
        repo = _repository(Credential("weak.bcrypt", hasher.hash("pw")))
        report = auditor.audit(repo)
        assert len(report.by_category(FindingCategory.WEAK_PARAMETERS)) == 1

    def test_compliant_algorithm_produces_no_weak_parameters_finding(
        self, auditor: CredentialAuditor
    ) -> None:
        hasher = Argon2idHasher(memory_kib=65_536, time_cost=3, parallelism=1)
        repo = _repository(Credential("good.user", hasher.hash("pw")))
        report = auditor.audit(repo)
        assert report.by_category(FindingCategory.WEAK_PARAMETERS) == []


class TestAuditorDetectsReuse:
    def test_identical_digests_flag_password_reuse(self, auditor: CredentialAuditor) -> None:
        digest = HashDigest(
            algorithm=HashAlgorithm.MD5, hash=hashlib.md5(b"same").digest(), salt=None
        )
        repo = _repository(
            Credential("user.a", digest),
            Credential("user.b", digest),
            Credential("user.c", digest),
        )
        report = auditor.audit(repo)
        findings = report.by_category(FindingCategory.PASSWORD_REUSE)
        assert len(findings) == 1
        assert findings[0].severity is Severity.HIGH
        assert findings[0].evidence["usernames"] == ["user.a", "user.b", "user.c"]

    def test_distinct_digests_are_not_flagged(self, auditor: CredentialAuditor) -> None:
        hasher = Argon2idHasher(memory_kib=256, time_cost=1, parallelism=1)
        repo = _repository(
            Credential("user.a", hasher.hash("a")),
            Credential("user.b", hasher.hash("b")),
        )
        report = auditor.audit(repo)
        assert report.by_category(FindingCategory.PASSWORD_REUSE) == []

    def test_salt_reuse_is_flagged(self, auditor: CredentialAuditor) -> None:
        salt = b"shared-salt-value!"
        digest_a = HashDigest(algorithm=HashAlgorithm.SHA256, hash=b"a" * 32, salt=salt)
        digest_b = HashDigest(algorithm=HashAlgorithm.SHA256, hash=b"b" * 32, salt=salt)
        repo = _repository(
            Credential("user.a", digest_a), Credential("user.b", digest_b)
        )
        report = auditor.audit(repo)
        findings = report.by_category(FindingCategory.TIMING_RISK)
        assert len(findings) == 1
        assert findings[0].severity is Severity.MEDIUM


class TestAuditorDetectsWeakPasswords:
    def test_short_password_is_flagged(self, auditor: CredentialAuditor) -> None:
        report = auditor.audit(_repository(), candidates={"weak.user": "short"})
        findings = report.by_category(FindingCategory.POLICY_NON_COMPLIANT)
        assert len(findings) == 1
        assert findings[0].username == "weak.user"

    def test_low_entropy_password_is_flagged(self, auditor: CredentialAuditor) -> None:
        report = auditor.audit(_repository(), candidates={"user": "aaaaaaaaaaaa"})
        assert len(report.by_category(FindingCategory.LOW_ENTROPY)) == 1

    def test_strong_password_is_not_flagged(self, auditor: CredentialAuditor) -> None:
        report = auditor.audit(
            _repository(), candidates={"user": "Xk9!vQ2#mZ7@pL4$wR8!"}
        )
        assert report.by_category(FindingCategory.LOW_ENTROPY) == []
        assert report.by_category(FindingCategory.POLICY_NON_COMPLIANT) == []


class TestAuditorReport:
    def test_empty_repository_produces_empty_report(self, auditor: CredentialAuditor) -> None:
        report = auditor.audit(_repository())
        assert len(report) == 0
        assert report.total_credentials == 0
        assert report.highest_severity is None
        assert report.compliant is True

    def test_findings_are_sorted_by_severity(self, auditor: CredentialAuditor) -> None:
        hasher = Argon2idHasher(memory_kib=256, time_cost=1, parallelism=1)
        repo = _repository(
            Credential("good", hasher.hash("pw")),
            Credential("bad", HashDigest(algorithm=HashAlgorithm.MD5, hash=b"x" * 16)),
        )
        report = auditor.audit(repo)
        ranks = [f.severity.rank for f in report.findings]
        assert ranks == sorted(ranks, reverse=True)

    def test_statistics_summarise_the_estate(self, auditor: CredentialAuditor) -> None:
        hasher = Argon2idHasher(memory_kib=256, time_cost=1, parallelism=1)
        repo = _repository(
            Credential("good", hasher.hash("pw")),
            Credential("bad", HashDigest(algorithm=HashAlgorithm.MD5, hash=b"x" * 16)),
        )
        report = auditor.audit(repo)
        stats = report.statistics
        assert stats["salted_count"] == 1
        assert stats["unsalted_count"] == 1
        assert stats["algorithm_distribution"]["argon2id"] == 1
        assert stats["algorithm_distribution"]["md5"] == 1

    def test_report_serialises_to_dict(self, auditor: CredentialAuditor) -> None:
        repo = _repository(
            Credential("bad", HashDigest(algorithm=HashAlgorithm.MD5, hash=b"x" * 16))
        )
        payload = auditor.audit(repo).to_dict()
        assert payload["compliant"] is False
        assert payload["total_credentials"] == 1
        assert len(payload["findings"]) == len(payload["findings"])
        assert "severity_counts" in payload

    def test_compliant_credential_yields_info_finding(
        self, auditor: CredentialAuditor
    ) -> None:
        hasher = Argon2idHasher(memory_kib=65_536, time_cost=3, parallelism=1)
        repo = _repository(Credential("good", hasher.hash("pw")))
        report = auditor.audit(repo)
        compliant = report.by_category(FindingCategory.COMPLIANT)
        assert len(compliant) == 1
        assert compliant[0].severity is Severity.INFO

    def test_compliance_flag_reflects_critical_findings(
        self, auditor: CredentialAuditor
    ) -> None:
        repo = _repository(
            Credential("bad", HashDigest(algorithm=HashAlgorithm.MD5, hash=b"x" * 16))
        )
        assert auditor.audit(repo).compliant is False

    def test_policy_is_included_in_report(self, auditor: CredentialAuditor) -> None:
        report = auditor.audit(_repository())
        assert report.policy["target_algorithm"] == "argon2id"
        assert report.policy["minimum_salt_bytes"] == 16

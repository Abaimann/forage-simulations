"""Tests for the policy object, the repository adapter and the CLI."""

from __future__ import annotations

import json

import pytest

from crypto_audit.cli import build_parser, main
from crypto_audit.domain.algorithms import HashAlgorithm
from crypto_audit.domain.credential import Credential
from crypto_audit.domain.digest import HashDigest
from crypto_audit.domain.exceptions import RepositoryError, UnsupportedAlgorithmError
from crypto_audit.domain.policy import HashingPolicy
from crypto_audit.infrastructure.hasher_factory import HasherRegistry
from crypto_audit.infrastructure.repository import InMemoryCredentialRepository
from crypto_audit.infrastructure.sample_data import (
    SAMPLE_PASSWORDS,
    build_sample_repository,
)


class TestHashingPolicy:
    def test_default_target_is_argon2id(self) -> None:
        assert HashingPolicy().target_algorithm is HashAlgorithm.ARGON2ID

    def test_with_target_returns_new_instance(self) -> None:
        policy = HashingPolicy()
        changed = policy.with_target(HashAlgorithm.BCRYPT)
        assert changed.target_algorithm is HashAlgorithm.BCRYPT
        assert policy.target_algorithm is HashAlgorithm.ARGON2ID

    def test_with_parameters_overrides_cost(self) -> None:
        policy = HashingPolicy().with_parameters(pbkdf2_iterations=1_234)
        assert policy.parameters.pbkdf2_iterations == 1_234

    def test_target_parameters_for_argon2(self) -> None:
        params = HashingPolicy().target_parameters()
        assert set(params) == {"m", "t", "p", "length"}

    def test_target_parameters_for_pbkdf2(self) -> None:
        params = HashingPolicy().with_target(HashAlgorithm.PBKDF2_SHA256).target_parameters()
        assert set(params) == {"iterations"}

    def test_target_parameters_for_bcrypt(self) -> None:
        params = HashingPolicy().with_target(HashAlgorithm.BCRYPT).target_parameters()
        assert set(params) == {"cost"}

    def test_legacy_digest_is_never_acceptable(self) -> None:
        policy = HashingPolicy()
        digest = HashDigest(algorithm=HashAlgorithm.MD5, hash=b"x" * 16, salt=b"s" * 16)
        assert policy.digest_is_acceptable(digest) is False

    def test_missing_salt_is_not_acceptable(self) -> None:
        policy = HashingPolicy()
        digest = HashDigest(
            algorithm=HashAlgorithm.ARGON2ID,
            hash=b"x" * 32,
            salt=None,
            params={"m": 65536, "t": 3},
        )
        assert policy.digest_is_acceptable(digest) is False

    def test_short_salt_is_not_acceptable(self) -> None:
        policy = HashingPolicy()
        digest = HashDigest(
            algorithm=HashAlgorithm.ARGON2ID,
            hash=b"x" * 32,
            salt=b"s" * 8,
            params={"m": 65536, "t": 3},
        )
        assert policy.digest_is_acceptable(digest) is False

    def test_compliant_digest_is_acceptable(self) -> None:
        policy = HashingPolicy()
        digest = HashDigest(
            algorithm=HashAlgorithm.ARGON2ID,
            hash=b"x" * 32,
            salt=b"s" * 16,
            params={"m": 65536, "t": 3},
        )
        assert policy.digest_is_acceptable(digest) is True

    def test_needs_rehash_for_legacy_algorithm(self) -> None:
        policy = HashingPolicy()
        digest = HashDigest(algorithm=HashAlgorithm.SHA1, hash=b"x" * 20, salt=b"s" * 16)
        assert policy.needs_rehash(digest) is True

    def test_needs_rehash_for_weak_pbkdf2(self) -> None:
        policy = HashingPolicy()
        digest = HashDigest(
            algorithm=HashAlgorithm.PBKDF2_SHA256,
            hash=b"x" * 32,
            salt=b"s" * 16,
            params={"iterations": 1_000},
        )
        assert policy.needs_rehash(digest) is True

    def test_does_not_need_rehash_when_compliant(self) -> None:
        policy = HashingPolicy()
        digest = HashDigest(
            algorithm=HashAlgorithm.ARGON2ID,
            hash=b"x" * 32,
            salt=b"s" * 16,
            params={"m": 65536, "t": 3},
        )
        assert policy.needs_rehash(digest) is False

    def test_describe_exposes_thresholds(self) -> None:
        described = HashingPolicy().describe()
        assert described["target_algorithm"] == "argon2id"
        assert described["minimum_salt_bytes"] == 16
        assert described["minimum_pbkdf2_iterations"] == 600_000


class TestInMemoryRepository:
    def test_save_and_get(self) -> None:
        repo = InMemoryCredentialRepository()
        digest = HashDigest(algorithm=HashAlgorithm.MD5, hash=b"x" * 16)
        repo.save(Credential("user", digest))
        assert repo.get("user").digest == digest

    def test_get_unknown_returns_none(self) -> None:
        assert InMemoryCredentialRepository().get("ghost") is None

    def test_list_all_returns_everything(self) -> None:
        repo = InMemoryCredentialRepository()
        digest = HashDigest(algorithm=HashAlgorithm.MD5, hash=b"x" * 16)
        repo.save(Credential("a", digest))
        repo.save(Credential("b", digest))
        assert len(repo.list_all()) == 2

    def test_save_replaces_existing(self) -> None:
        repo = InMemoryCredentialRepository()
        digest = HashDigest(algorithm=HashAlgorithm.MD5, hash=b"x" * 16)
        repo.save(Credential("a", digest))
        repo.save(Credential("a", digest))
        assert len(repo.list_all()) == 1

    def test_delete_removes_and_reports(self) -> None:
        repo = InMemoryCredentialRepository()
        digest = HashDigest(algorithm=HashAlgorithm.MD5, hash=b"x" * 16)
        repo.save(Credential("a", digest))
        assert repo.delete("a") is True
        assert repo.delete("a") is False

    def test_contains_operator(self) -> None:
        repo = InMemoryCredentialRepository()
        digest = HashDigest(algorithm=HashAlgorithm.MD5, hash=b"x" * 16)
        repo.save(Credential("a", digest))
        assert "a" in repo
        assert "b" not in repo

    def test_contains_rejects_non_string(self) -> None:
        with pytest.raises(RepositoryError):
            123 in InMemoryCredentialRepository()  # type: ignore[operator]

    def test_credential_rejects_blank_username(self) -> None:
        digest = HashDigest(algorithm=HashAlgorithm.MD5, hash=b"x" * 16)
        with pytest.raises(ValueError):
            Credential("   ", digest)


class TestHasherRegistry:
    def test_returns_hasher_for_every_known_algorithm(self) -> None:
        registry = HasherRegistry()
        for algorithm in HashAlgorithm:
            hasher = registry.get(algorithm)
            assert hasher.algorithm is algorithm

    def test_same_instance_is_returned_for_repeated_calls(self) -> None:
        registry = HasherRegistry()
        assert registry.get(HashAlgorithm.ARGON2ID) is registry.get(
            HashAlgorithm.ARGON2ID
        )

    def test_unknown_algorithm_is_rejected(self) -> None:
        with pytest.raises(UnsupportedAlgorithmError):
            HasherRegistry().get("rot13")  # type: ignore[arg-type]

    def test_registry_can_be_overridden(self) -> None:
        registry = HasherRegistry()
        sentinel = object()
        registry.register(HashAlgorithm.ARGON2ID, sentinel)  # type: ignore[arg-type]
        assert registry.get(HashAlgorithm.ARGON2ID) is sentinel


class TestSampleData:
    def test_sample_repository_contains_expected_accounts(self) -> None:
        repo = build_sample_repository()
        assert len(repo) == 8
        assert "alice.legacy" in repo

    def test_sample_passwords_cover_every_account(self) -> None:
        repo = build_sample_repository()
        assert set(SAMPLE_PASSWORDS) == set(repo.usernames())


class TestCLI:
    def test_parser_builds(self) -> None:
        parser = build_parser()
        assert parser.prog == "crypto_audit"

    def test_audit_command_runs(self, capsys: pytest.CaptureFixture[str]) -> None:
        exit_code = main(["audit"])
        captured = capsys.readouterr()
        assert exit_code == 1, "the sample estate is intentionally non-compliant"
        assert "CREDENTIAL SECURITY AUDIT REPORT" in captured.out

    def test_audit_json_output_is_valid_json(
        self, capsys: pytest.CaptureFixture[str]
    ) -> None:
        main(["audit", "--json"])
        payload = json.loads(capsys.readouterr().out)
        assert payload["total_credentials"] == 8
        assert payload["compliant"] is False
        assert len(payload["findings"]) > 0

    def test_benchmark_command_runs(self, capsys: pytest.CaptureFixture[str]) -> None:
        assert main(["benchmark"]) == 0
        assert "guesses/s" in capsys.readouterr().out

    def test_collision_command_runs(self, capsys: pytest.CaptureFixture[str]) -> None:
        assert main(["collision", "--algorithm", "argon2id", "--samples", "8"]) == 0
        payload = json.loads(capsys.readouterr().out)
        assert payload["is_collision_resistant"] is True

    def test_collision_command_detects_legacy_failure(
        self, capsys: pytest.CaptureFixture[str]
    ) -> None:
        exit_code = main(["collision", "--algorithm", "md5", "--samples", "8"])
        payload = json.loads(capsys.readouterr().out)
        assert exit_code == 1
        assert payload["is_collision_resistant"] is False

    def test_demo_command_runs(self, capsys: pytest.CaptureFixture[str]) -> None:
        assert main(["demo"]) == 0
        captured = capsys.readouterr()
        assert "STEP 1 - AUDIT" in captured.out
        assert "STEP 3 - TRANSPARENT UPGRADE" in captured.out

    def test_demo_json_output_is_valid_json(
        self, capsys: pytest.CaptureFixture[str]
    ) -> None:
        main(["demo", "--json"])
        payload = json.loads(capsys.readouterr().out)
        assert "audit" in payload
        assert "brute_force" in payload

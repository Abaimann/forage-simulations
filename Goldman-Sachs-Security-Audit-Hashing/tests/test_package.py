"""Package-level contract tests (public API surface)."""

from __future__ import annotations

import crypto_audit


class TestReadmeExample:
    """The example published in README.md must keep working verbatim."""

    def test_readme_library_example(self) -> None:
        from crypto_audit import (
            CredentialAuditor,
            HashAlgorithm,
            HashingPolicy,
            InMemoryCredentialRepository,
            LegacyHashHasher,
            UpgradePipeline,
        )
        from crypto_audit.domain.credential import Credential

        legacy = LegacyHashHasher(HashAlgorithm.MD5, salted=False)
        repository = InMemoryCredentialRepository()
        repository.save(Credential("alice", legacy.hash("the-real-password")))

        report = CredentialAuditor().audit(repository)
        assert len(report.findings) == 2

        pipeline = UpgradePipeline(repository, HashingPolicy())
        result = pipeline.authenticate("alice", "the-real-password")
        assert result.authenticated and result.upgraded


class TestPublicAPI:
    def test_version_is_exposed(self) -> None:
        assert isinstance(crypto_audit.__version__, str)
        assert crypto_audit.__version__.count(".") == 2

    def test_all_exports_are_importable(self) -> None:
        for name in crypto_audit.__all__:
            assert hasattr(crypto_audit, name), f"missing export: {name}"

    def test_key_classes_are_exported(self) -> None:
        assert crypto_audit.CredentialAuditor is not None
        assert crypto_audit.UpgradePipeline is not None
        assert crypto_audit.BruteForceTester is not None
        assert crypto_audit.HashingPolicy is not None
        assert crypto_audit.HashAlgorithm is not None

    def test_domain_layer_has_no_infrastructure_dependency(self) -> None:
        import crypto_audit.domain as domain

        for module_name in ("bcrypt", "argon2"):
            assert module_name not in dir(domain)

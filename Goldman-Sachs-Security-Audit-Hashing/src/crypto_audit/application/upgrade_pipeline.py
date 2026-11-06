"""Transparent password upgrade pipeline.

The pipeline performs *opportunistic* credential migration: whenever a user
successfully authenticates, the stored digest is transparently replaced with
a modern, policy-compliant digest. Users never notice, and legacy accounts
are migrated only when the real secret is known (i.e. during a successful
login) - no plaintext is ever stored or transmitted.

Timing-attack mitigation: authentication of an unknown user performs a
decoy verification against a pre-computed digest, so that the response time
does not reveal whether the account exists.
"""

from __future__ import annotations

import secrets
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Callable, Mapping

from ..domain.credential import Credential, CredentialRepository
from ..domain.digest import HashDigest
from ..domain.policy import HashingPolicy
from ..infrastructure.hasher_factory import HasherRegistry
from .constant_time import secure_compare

__all__ = ["AuthenticationResult", "UpgradePipeline"]


@dataclass(frozen=True)
class AuthenticationResult:
    """Outcome of an authentication attempt.

    Attributes:
        authenticated: Whether the supplied secret was correct.
        upgraded: Whether the stored digest was replaced during this call.
        previous_algorithm: Algorithm used before the (possible) upgrade.
        current_algorithm: Algorithm used after the (possible) upgrade.
        credential: The credential record after the call, if it exists.
        reason: Short machine-readable explanation.
    """

    authenticated: bool
    upgraded: bool = False
    previous_algorithm: str | None = None
    current_algorithm: str | None = None
    credential: Credential | None = None
    reason: str = ""

    def to_dict(self) -> dict[str, object]:
        return {
            "authenticated": self.authenticated,
            "upgraded": self.upgraded,
            "previous_algorithm": self.previous_algorithm,
            "current_algorithm": self.current_algorithm,
            "username": self.credential.username if self.credential else None,
            "reason": self.reason,
        }


class UpgradePipeline:
    """Authenticates users and transparently upgrades their stored digests.

    Args:
        repository: Credential store (read/write).
        policy: Target hashing policy.
        registry: Hasher registry; defaults to one built from *policy*.
        clock: Injectable clock returning timezone-aware datetimes.
    """

    def __init__(
        self,
        repository: CredentialRepository,
        policy: HashingPolicy | None = None,
        *,
        registry: HasherRegistry | None = None,
        clock: Callable[[], datetime] | None = None,
    ) -> None:
        self._repository = repository
        self._policy = policy or HashingPolicy()
        self._registry = registry or HasherRegistry(self._policy)
        self._clock = clock or (lambda: datetime.now(timezone.utc))
        self._decoy_digest: HashDigest | None = None

    @property
    def policy(self) -> HashingPolicy:
        return self._policy

    # ------------------------------------------------------------------
    def _decoy(self) -> HashDigest:
        """Lazily built digest used to equalise timing for unknown users."""
        if self._decoy_digest is None:
            hasher = self._registry.get(self._policy.target_algorithm)
            self._decoy_digest = hasher.hash(secrets.token_urlsafe(32))
        return self._decoy_digest

    # ------------------------------------------------------------------
    def authenticate(self, username: str, password: str) -> AuthenticationResult:
        """Authenticate *username* / *password* and upgrade the digest if needed.

        Timing-attack mitigation: authentication always performs one
        verification with the *target* algorithm. For accounts still stored
        with a legacy digest this decoy verification is performed in addition
        to the legacy verification, so the response time is dominated by the
        target algorithm and does not reveal either the existence of the
        account or the algorithm its credential is stored with.

        Args:
            username: Account identifier.
            password: Candidate secret.

        Returns:
            An :class:`AuthenticationResult`.
        """
        credential = self._repository.get(username)
        target = self._registry.get(self._policy.target_algorithm)

        if credential is None:
            # Decoy work: make an unknown user cost the same as a known one.
            target.verify(password, self._decoy())
            return AuthenticationResult(
                authenticated=False,
                reason="unknown_user",
            )

        digest = credential.digest
        verifier = self._registry.get(digest.algorithm)

        if digest.algorithm is not self._policy.target_algorithm:
            # Equalisation work for legacy credentials (see docstring).
            target.verify(password, self._decoy())

        verified = verifier.verify(password, digest)

        if not verified:
            return AuthenticationResult(
                authenticated=False,
                previous_algorithm=digest.algorithm.value,
                current_algorithm=digest.algorithm.value,
                credential=credential,
                reason="invalid_password",
            )

        if not self._policy.needs_rehash(digest):
            return AuthenticationResult(
                authenticated=True,
                upgraded=False,
                previous_algorithm=digest.algorithm.value,
                current_algorithm=digest.algorithm.value,
                credential=credential,
                reason="up_to_date",
            )

        upgraded_credential = self.upgrade(credential, password)
        return AuthenticationResult(
            authenticated=True,
            upgraded=True,
            previous_algorithm=digest.algorithm.value,
            current_algorithm=upgraded_credential.digest.algorithm.value,
            credential=upgraded_credential,
            reason="upgraded",
        )

    # ------------------------------------------------------------------
    def upgrade(self, credential: Credential, password: str) -> Credential:
        """Re-hash *password* with the policy target algorithm and persist it.

        Args:
            credential: The credential to upgrade.
            password: The plaintext secret (available at login time).

        Returns:
            The persisted, upgraded credential.
        """
        target = self._registry.get(self._policy.target_algorithm)
        new_digest = target.hash(password)
        upgraded = credential.with_digest(new_digest, updated_at=self._clock())
        self._repository.save(upgraded)
        return upgraded

    # ------------------------------------------------------------------
    def migrate_all(
        self, credentials: Mapping[str, str]
    ) -> dict[str, AuthenticationResult]:
        """Bulk-migrate accounts whose plaintext is already known.

        This is the offline migration path used for service accounts during a
        maintenance window. It never downgrades a credential.

        Args:
            credentials: Mapping of ``username -> plaintext``.

        Returns:
            Mapping of ``username -> AuthenticationResult``.
        """
        results: dict[str, AuthenticationResult] = {}
        for username, password in credentials.items():
            credential = self._repository.get(username)
            if credential is None:
                results[username] = AuthenticationResult(
                    authenticated=False, reason="unknown_user"
                )
                continue
            if not self._policy.needs_rehash(credential.digest):
                results[username] = AuthenticationResult(
                    authenticated=True,
                    upgraded=False,
                    previous_algorithm=credential.digest.algorithm.value,
                    current_algorithm=credential.digest.algorithm.value,
                    credential=credential,
                    reason="up_to_date",
                )
                continue
            upgraded = self.upgrade(credential, password)
            results[username] = AuthenticationResult(
                authenticated=True,
                upgraded=True,
                previous_algorithm=credential.digest.algorithm.value,
                current_algorithm=upgraded.digest.algorithm.value,
                credential=upgraded,
                reason="upgraded",
            )
        return results

    # ------------------------------------------------------------------
    def verify_secret(self, password: str, expected: str) -> bool:
        """Constant-time comparison of two secrets.

        Exposed so that callers can compare secrets without importing the
        low-level constant-time module.
        """
        return secure_compare(password, expected)

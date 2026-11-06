"""Credential record and repository port definitions."""

from __future__ import annotations

from dataclasses import dataclass, field, replace
from datetime import datetime, timezone
from typing import Iterable, Protocol, runtime_checkable

from .digest import HashDigest

__all__ = ["Credential", "CredentialRepository"]


@dataclass(frozen=True)
class Credential:
    """A single stored credential.

    Attributes:
        username: Login identifier.
        digest: The stored password digest.
        created_at: Creation timestamp (UTC, timezone-aware).
        updated_at: Last modification timestamp (UTC, timezone-aware).
        version: Monotonic revision counter, bumped on every digest rotation.
        metadata: Free-form annotations (e.g. source system, employee id).
    """

    username: str
    digest: HashDigest
    created_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))
    updated_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))
    version: int = 1
    metadata: dict[str, str] = field(default_factory=dict)

    def __post_init__(self) -> None:
        if not self.username or not self.username.strip():
            raise ValueError("username must be a non-empty string")
        object.__setattr__(self, "metadata", dict(self.metadata))

    def with_digest(self, digest: HashDigest, *, updated_at: datetime) -> "Credential":
        """Return a copy carrying *digest*, with version bumped."""
        return replace(
            self,
            digest=digest,
            updated_at=updated_at,
            version=self.version + 1,
        )


@runtime_checkable
class CredentialRepository(Protocol):
    """Persistence port for credentials (implemented by adapters)."""

    def get(self, username: str) -> Credential | None:
        """Return the credential for *username* or ``None`` when unknown."""
        ...

    def list_all(self) -> list[Credential]:
        """Return every stored credential."""
        ...

    def save(self, credential: Credential) -> None:
        """Insert or replace a credential."""
        ...

    def usernames(self) -> Iterable[str]:
        """Return the known usernames."""
        ...

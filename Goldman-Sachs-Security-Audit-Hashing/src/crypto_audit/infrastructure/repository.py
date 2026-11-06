"""In-memory credential repository adapter.

Implements the :class:`CredentialRepository` port. A production deployment
would swap this for a database adapter; the application services depend only
on the port.
"""

from __future__ import annotations

import threading
from typing import Iterable

from ..domain.credential import Credential
from ..domain.exceptions import RepositoryError

__all__ = ["InMemoryCredentialRepository"]


class InMemoryCredentialRepository:
    """Thread-safe dictionary-backed credential store.

    Args:
        credentials: Optional initial credential set.
    """

    def __init__(self, credentials: Iterable[Credential] | None = None) -> None:
        self._lock = threading.RLock()
        self._credentials: dict[str, Credential] = {}
        for credential in credentials or ():
            self.save(credential)

    # ------------------------------------------------------------------
    def get(self, username: str) -> Credential | None:
        with self._lock:
            return self._credentials.get(username)

    def list_all(self) -> list[Credential]:
        with self._lock:
            return list(self._credentials.values())

    def save(self, credential: Credential) -> None:
        with self._lock:
            self._credentials[credential.username] = credential

    def usernames(self) -> Iterable[str]:
        with self._lock:
            return list(self._credentials.keys())

    def delete(self, username: str) -> bool:
        """Remove a credential; returns ``True`` when something was removed."""
        with self._lock:
            return self._credentials.pop(username, None) is not None

    def __len__(self) -> int:
        with self._lock:
            return len(self._credentials)

    def __contains__(self, username: object) -> bool:
        if not isinstance(username, str):
            raise RepositoryError("username must be a string")
        with self._lock:
            return username in self._credentials

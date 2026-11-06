"""Self-describing, parseable credential digest.

Wire format (``$``-separated, four fields)::

    <algorithm>$<params>$<base64 salt>$<base64 hash>

Example::

    argon2id$m=65536,t=3,p=4$0Q4d...$kJ9F...

The salt field is empty for legacy unsalted digests, which is precisely the
condition the auditor reports as ``MISSING_SALT``.
"""

from __future__ import annotations

import base64
import binascii
from dataclasses import dataclass, field
from typing import Any, Mapping

from .algorithms import ALGORITHM_REGISTRY, HashAlgorithm
from .exceptions import InvalidDigestError, UnsupportedAlgorithmError

__all__ = ["HashDigest", "encode_base64", "decode_base64"]

_PARAMS_SEPARATOR = ","
_FIELD_SEPARATOR = "$"


def encode_base64(raw: bytes) -> str:
    """Standard base64 with padding - deterministic and URL-safe enough."""
    return base64.b64encode(raw).decode("ascii")


def decode_base64(text: str) -> bytes:
    """Strict base64 decode; raises :class:`InvalidDigestError` on garbage."""
    try:
        return base64.b64decode(text.encode("ascii"), validate=True)
    except (binascii.Error, UnicodeEncodeError, ValueError) as exc:
        raise InvalidDigestError(f"invalid base64 payload: {exc}") from exc


@dataclass(frozen=True)
class HashDigest:
    """An immutable credential digest plus everything needed to re-verify it."""

    algorithm: HashAlgorithm
    hash: bytes
    salt: bytes | None = None
    params: Mapping[str, Any] = field(default_factory=dict)

    # ------------------------------------------------------------------
    # construction
    # ------------------------------------------------------------------
    def __post_init__(self) -> None:
        if not isinstance(self.algorithm, HashAlgorithm):
            object.__setattr__(self, "algorithm", HashAlgorithm(self.algorithm))
        if not self.hash:
            raise InvalidDigestError("digest hash payload must not be empty")
        if self.salt is not None and not self.salt:
            raise InvalidDigestError("digest salt must be either None or non-empty")
        object.__setattr__(self, "params", dict(self.params))

    # ------------------------------------------------------------------
    # serialisation
    # ------------------------------------------------------------------
    def encode(self) -> str:
        """Render the digest to its canonical wire format."""
        params = ",".join(
            f"{key}={self.params[key]}" for key in sorted(self.params, key=str)
        )
        salt = encode_base64(self.salt) if self.salt else ""
        return _FIELD_SEPARATOR.join(
            [
                self.algorithm.value,
                params,
                salt,
                encode_base64(self.hash),
            ]
        )

    @classmethod
    def decode(cls, payload: str) -> "HashDigest":
        """Parse the canonical wire format produced by :meth:`encode`."""
        if not isinstance(payload, str) or not payload:
            raise InvalidDigestError("digest payload must be a non-empty string")
        fields = payload.split(_FIELD_SEPARATOR)
        if len(fields) != 4:
            raise InvalidDigestError(
                f"malformed digest: expected 4 '$'-separated fields, got {len(fields)}"
            )
        algo_raw, params_raw, salt_raw, hash_raw = fields

        try:
            algorithm = ALGORITHM_REGISTRY[algo_raw.strip().lower()]
        except KeyError as exc:
            raise UnsupportedAlgorithmError(
                f"unsupported hash algorithm: {algo_raw!r}"
            ) from exc

        params: dict[str, Any] = {}
        if params_raw.strip():
            for chunk in params_raw.split(_PARAMS_SEPARATOR):
                if not chunk.strip():
                    continue
                if "=" not in chunk:
                    raise InvalidDigestError(f"malformed digest parameter: {chunk!r}")
                key, _, value = chunk.partition("=")
                key = key.strip()
                if not key:
                    raise InvalidDigestError(f"malformed digest parameter: {chunk!r}")
                params[key] = _coerce_param(value.strip())

        salt = decode_base64(salt_raw) if salt_raw else None
        if salt is not None and not salt:
            raise InvalidDigestError("salt field decoded to zero bytes")
        return cls(algorithm=algorithm, hash=decode_base64(hash_raw), salt=salt, params=params)

    # ------------------------------------------------------------------
    # helpers
    # ------------------------------------------------------------------
    @property
    def is_salted(self) -> bool:
        return self.salt is not None

    def param_int(self, name: str, default: int) -> int:
        """Read an integer parameter, falling back to *default*."""
        value = self.params.get(name, default)
        try:
            return int(value)
        except (TypeError, ValueError):
            return default

    def __str__(self) -> str:  # pragma: no cover - convenience
        return self.encode()


def _coerce_param(value: str) -> Any:
    """Keep integer parameters as ints so policy comparisons stay numeric."""
    if not value:
        return ""
    try:
        return int(value)
    except ValueError:
        return value

"""Constant-time comparison utilities.

All credential comparisons in this package MUST go through :func:`secure_compare`
(or :func:`secure_compare_bytes`). Python's ``==`` on ``bytes`` short-circuits
on the first differing byte, which leaks the length of the matching prefix -
the classic timing side channel used to recover HMACs byte-by-byte.
"""

from __future__ import annotations

import hmac
from typing import Any

__all__ = [
    "secure_compare",
    "secure_compare_bytes",
    "TimingAttackError",
    "constant_time_equals",
]


class TimingAttackError(RuntimeError):
    """Raised when a comparison is requested between incompatible types."""


def secure_compare_bytes(left: bytes, right: bytes) -> bool:
    """Compare two byte strings in constant time.

    Uses :func:`hmac.compare_digest`, which is implemented in C and does not
    short-circuit. Length differences are detected without leaking *where*
    the difference occurred.

    Args:
        left: First operand.
        right: Second operand.

    Returns:
        ``True`` when the operands are byte-for-byte equal.
    """
    if not isinstance(left, (bytes, bytearray, memoryview)):
        raise TimingAttackError("left operand must be bytes-like")
    if not isinstance(right, (bytes, bytearray, memoryview)):
        raise TimingAttackError("right operand must be bytes-like")
    return hmac.compare_digest(bytes(left), bytes(right))


def secure_compare(left: str | bytes, right: str | bytes) -> bool:
    """Compare two credentials (strings or bytes) in constant time.

    Strings are encoded as UTF-8 before comparison so that Unicode
    normalisation differences do not silently bypass the check.

    Args:
        left: Candidate value.
        right: Expected value.

    Returns:
        ``True`` when both values are equal.

    Raises:
        TimingAttackError: if the operand types are not compatible.
    """
    left_bytes = _coerce(left)
    right_bytes = _coerce(right)
    return secure_compare_bytes(left_bytes, right_bytes)


def constant_time_equals(left: Any, right: Any) -> bool:
    """Type-safe wrapper around :func:`secure_compare`.

    Non ``str``/``bytes`` operands are compared with ``==`` because they carry
    no secret material.
    """
    if isinstance(left, (str, bytes)) and isinstance(right, (str, bytes)):
        return secure_compare(left, right)
    return bool(left == right)


def _coerce(value: str | bytes) -> bytes:
    if isinstance(value, str):
        return value.encode("utf-8")
    if isinstance(value, (bytes, bytearray, memoryview)):
        return bytes(value)
    raise TimingAttackError(
        f"cannot compare value of type {type(value).__name__!r} in constant time"
    )

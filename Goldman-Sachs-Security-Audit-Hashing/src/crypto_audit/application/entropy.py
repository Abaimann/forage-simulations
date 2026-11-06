"""Entropy analysis for digests, salts and candidate passwords.

Important subtlety: Shannon entropy of a *sample* is bounded by
``log2(sample_length)``. A 32-byte digest can therefore never exceed
5 bits/byte, and a 16-byte salt never more than 4 bits/byte, no matter how
random it is. Comparing such samples against the theoretical 8 bits/byte
ceiling would flag every correctly generated credential.

This module therefore reports two distinct quantities:

* :func:`shannon_entropy_bits` / :func:`normalised_entropy_bits_per_byte`
  - the raw measured entropy (useful for detecting constant / patterned data).
* :func:`entropy_density` - the measured entropy expressed as a fraction of
  the maximum achievable for a sample of that length, i.e. a 0..1 "how uniform
  is this sample" score. This is the value the audit policy compares against.
"""

from __future__ import annotations

import math
from collections import Counter
from dataclasses import dataclass
from typing import Iterable, Sequence

__all__ = [
    "shannon_entropy_bits",
    "normalised_entropy_bits_per_byte",
    "entropy_density",
    "estimate_password_entropy_bits",
    "EntropyAssessment",
    "analyse_password_entropy",
    "charset_size",
    "entropy_profile",
    "unique_ratio",
]


def shannon_entropy_bits(data: bytes) -> float:
    """Return the Shannon entropy of *data* in bits.

    ``H = -sum(p * log2(p))`` over the byte distribution.

    Args:
        data: Bytes to measure.

    Returns:
        Entropy in bits; ``0.0`` for empty input.
    """
    if not data:
        return 0.0
    length = len(data)
    counts = Counter(data)
    entropy = 0.0
    for count in counts.values():
        probability = count / length
        entropy -= probability * math.log2(probability)
    return entropy


def normalised_entropy_bits_per_byte(data: bytes) -> float:
    """Entropy of *data* normalised to the 0..8 bits-per-byte range."""
    if not data:
        return 0.0
    return shannon_entropy_bits(data) / 8.0


def entropy_density(data: bytes) -> float:
    """Return how uniform *data* is, as a fraction in ``0.0..1.0``.

    The ceiling for a sample of ``n`` bytes is ``min(log2(n), 8)`` bits, so a
    fully random 16-byte salt scores ``~1.0`` while a 16-byte constant
    buffer scores ``0.0``. This is the metric the audit policy uses, because
    the raw bits/byte figure is bounded by the sample length.
    """
    if not data:
        return 0.0
    ceiling = min(math.log2(len(data)), 8.0)
    if ceiling <= 0:
        return 0.0
    return min(1.0, shannon_entropy_bits(data) / ceiling)


def charset_size(password: str) -> int:
    """Return the size of the character alphabet implied by *password*."""
    size = 0
    if any(c.islower() and c.isascii() for c in password):
        size += 26
    if any(c.isupper() and c.isascii() for c in password):
        size += 26
    if any(c.isdigit() and c.isascii() for c in password):
        size += 10
    symbols = sum(
        1 for c in password if not c.isalnum() and not c.isspace()
    )
    if symbols:
        size += 33
    if any(not c.isascii() for c in password):
        size += 100
    return max(size, 1)


def estimate_password_entropy_bits(password: str) -> float:
    """Estimate the brute-force entropy of *password* in bits.

    The estimate is ``length * log2(charset_size)`` - a generic-crack
    estimate assuming the attacker knows the character classes but not the
    pattern. It is an upper bound on attacker effort for human-chosen
    passwords and should be combined with dictionary screening.
    """
    if not password:
        return 0.0
    return len(password) * math.log2(charset_size(password))


@dataclass(frozen=True)
class EntropyAssessment:
    """Outcome of an entropy evaluation.

    Attributes:
        entropy_bits: Estimated brute-force entropy in bits.
        entropy_bits_per_byte: Raw Shannon entropy of the UTF-8 encoding.
        density: Uniformity of the encoding in the 0..1 range.
        length: Password length in characters.
        charset_size: Size of the implied character alphabet.
        is_strong: Whether the password meets the configured entropy target.
    """

    entropy_bits: float
    entropy_bits_per_byte: float
    density: float
    length: int
    charset_size: int
    is_strong: bool

    def to_dict(self) -> dict[str, float | int | bool]:
        return {
            "entropy_bits": self.entropy_bits,
            "entropy_bits_per_byte": self.entropy_bits_per_byte,
            "density": self.density,
            "length": self.length,
            "charset_size": self.charset_size,
            "is_strong": self.is_strong,
        }


def analyse_password_entropy(
    password: str, *, minimum_bits: float = 60.0
) -> EntropyAssessment:
    """Assess the entropy of a candidate *password*.

    Args:
        password: The candidate secret.
        minimum_bits: Estimated-bits threshold used for the ``is_strong`` flag.

    Returns:
        An :class:`EntropyAssessment`.
    """
    encoded = password.encode("utf-8")
    bits = shannon_entropy_bits(encoded)
    per_byte = normalised_entropy_bits_per_byte(encoded)
    density = entropy_density(encoded)
    estimate = estimate_password_entropy_bits(password)
    return EntropyAssessment(
        entropy_bits=estimate,
        entropy_bits_per_byte=per_byte,
        density=density,
        length=len(password),
        charset_size=charset_size(password),
        is_strong=estimate >= minimum_bits,
    )


def entropy_profile(samples: Iterable[bytes]) -> dict[str, float]:
    """Aggregate entropy statistics over a collection of digests."""
    values = [entropy_density(sample) for sample in samples]
    if not values:
        return {
            "count": 0,
            "min_density": 0.0,
            "max_density": 0.0,
            "mean_density": 0.0,
        }
    return {
        "count": len(values),
        "min_density": min(values),
        "max_density": max(values),
        "mean_density": sum(values) / len(values),
    }


def unique_ratio(values: Sequence[bytes]) -> float:
    """Fraction of distinct elements in *values* (collision indicator)."""
    if not values:
        return 1.0
    return len(set(values)) / len(values)

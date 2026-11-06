"""Tests for constant-time comparison and timing-attack mitigation."""

from __future__ import annotations

import time

import pytest

from crypto_audit.application.constant_time import (
    TimingAttackError,
    constant_time_equals,
    secure_compare,
    secure_compare_bytes,
)


class TestSecureCompare:
    def test_equal_strings_match(self) -> None:
        assert secure_compare("swordfish", "swordfish") is True

    def test_different_strings_do_not_match(self) -> None:
        assert secure_compare("swordfish", "swordfisl") is False

    def test_empty_strings_match(self) -> None:
        assert secure_compare("", "") is True

    def test_different_lengths_do_not_match(self) -> None:
        assert secure_compare("short", "much-longer-value") is False

    def test_empty_and_non_empty_do_not_match(self) -> None:
        assert secure_compare("", "x") is False

    def test_bytes_and_str_are_interchangeable(self) -> None:
        assert secure_compare("abc", b"abc") is True
        assert secure_compare(b"abc", "abc") is True

    def test_non_ascii_round_trip(self) -> None:
        assert secure_compare("pässwörd", "pässwörd") is True
        assert secure_compare("pässwörd", "passwd") is False

    def test_rejects_unsupported_type(self) -> None:
        with pytest.raises(TimingAttackError):
            secure_compare(123, "123")  # type: ignore[arg-type]

    def test_rejects_mixed_unsupported_types(self) -> None:
        with pytest.raises(TimingAttackError):
            secure_compare("123", 123)  # type: ignore[arg-type]

    def test_bytes_helper_rejects_non_bytes(self) -> None:
        with pytest.raises(TimingAttackError):
            secure_compare_bytes("not-bytes", b"x")  # type: ignore[arg-type]

    def test_bytes_helper_accepts_bytearray(self) -> None:
        assert secure_compare_bytes(bytearray(b"abc"), b"abc") is True

    def test_bytes_helper_rejects_mismatched_length(self) -> None:
        assert secure_compare_bytes(b"abc", b"abcd") is False


class TestConstantTimeEquals:
    def test_strings_use_constant_time_path(self) -> None:
        assert constant_time_equals("a", "a") is True
        assert constant_time_equals("a", "b") is False

    def test_non_string_values_fall_back_to_equality(self) -> None:
        assert constant_time_equals(5, 5) is True
        assert constant_time_equals(5, 6) is False
        assert constant_time_equals(None, None) is True


class TestTimingResistance:
    """Empirical evidence that comparison time does not depend on content."""

    @staticmethod
    def _measure(candidate: bytes, expected: bytes, rounds: int = 3_000) -> float:
        """Return the total time spent comparing *candidate* to *expected*."""
        start = time.perf_counter()
        for _ in range(rounds):
            secure_compare_bytes(candidate, expected)
        return time.perf_counter() - start

    def test_early_difference_is_not_faster_than_late_difference(self) -> None:
        expected = b"A" * 64
        early_mismatch = b"B" + b"A" * 63
        late_mismatch = b"A" * 63 + b"B"

        early = self._measure(early_mismatch, expected)
        late = self._measure(late_mismatch, expected)

        # Allow generous slack for scheduler noise, but a short-circuiting
        # implementation would be orders of magnitude faster for the early
        # mismatch. The bound catches that while tolerating jitter.
        ratio = early / late if late > 0 else 1.0
        assert 0.5 < ratio < 2.0, f"timing ratio {ratio:.3f} suggests a side channel"

    def test_equal_inputs_are_not_faster_than_unequal_inputs(self) -> None:
        expected = b"A" * 64
        equal = self._measure(expected, expected)
        unequal = self._measure(b"A" * 63 + b"B", expected)
        ratio = unequal / equal if equal > 0 else 1.0
        assert 0.5 < ratio < 2.0, f"timing ratio {ratio:.3f} suggests a side channel"

    def test_length_difference_does_not_short_circuit(self) -> None:
        long_value = b"A" * 256
        short_value = b"A" * 16
        long_time = self._measure(long_value, long_value, rounds=1_500)
        short_time = self._measure(short_value, long_value, rounds=1_500)
        ratio = short_time / long_time if long_time > 0 else 1.0
        assert 0.5 < ratio < 2.0, f"timing ratio {ratio:.3f} suggests a side channel"

"""Unit tests of the value-object helpers that back the cleaning stage.

These cover the imputation strategies, the boolean parsing and the
identifier normalization, which are the primitives the dataset cleaners
rely on.
"""

from __future__ import annotations

from typing import Any

import pytest

from social_buzz_analytics.application.cleaning import (
    impute,
    iqr_outlier_map,
    parse_bool,
    winsorize,
)
from social_buzz_analytics.domain.value_objects import (
    canonical_text,
    normalize_identifier,
)


class TestImpute:
    """Tests of the :func:`impute` helper."""

    def test_median_of_an_odd_series(self) -> None:
        """The median of an odd-sized series is its middle value."""
        assert impute([1, 3, 5]) == pytest.approx(3.0)

    def test_median_of_an_even_series(self) -> None:
        """The median of an even-sized series is the mean of the middle values."""
        assert impute([1, 2, 3, 4]) == pytest.approx(2.5)

    def test_mean(self) -> None:
        """The mean strategy returns the arithmetic mean."""
        assert impute([1, 2, 3, 4], strategy="mean") == pytest.approx(2.5)

    def test_mode(self) -> None:
        """The mode strategy returns the most frequent value."""
        assert impute([1, 1, 2, 3], strategy="mode") == pytest.approx(1.0)

    def test_zero(self) -> None:
        """The zero strategy always returns zero."""
        assert impute([5, 6], strategy="zero") == 0
        assert impute([], strategy="zero") == 0

    def test_missing_values_are_ignored(self) -> None:
        """``None`` and empty strings do not take part in the computation."""
        assert impute([None, "", 2, 4], strategy="median") == pytest.approx(3.0)

    def test_non_numeric_values_are_ignored(self) -> None:
        """A non-numeric cell does not break the computation."""
        assert impute(["abc", 10, 20], strategy="median") == pytest.approx(15.0)

    def test_empty_series(self) -> None:
        """An empty series yields ``None``."""
        assert impute([]) is None
        assert impute([None, ""]) is None

    def test_only_non_numeric_values(self) -> None:
        """A series without a single number yields ``None``."""
        assert impute(["abc", "def"]) is None

    def test_unknown_strategy_is_rejected(self) -> None:
        """An unknown strategy raises a ``ValueError``."""
        with pytest.raises(ValueError, match="unknown imputation strategy"):
            impute([1, 2, 3], strategy="geometric")


class TestIqrOutlierMap:
    """Tests of the :func:`iqr_outlier_map` helper."""

    def test_extreme_values_are_clipped(self) -> None:
        """The extreme values are moved onto the fences."""
        values = [float(v) for v in range(100)] + [10_000.0]
        clipping, low, high = iqr_outlier_map(values)
        assert clipping[10_000.0] == pytest.approx(high)
        assert low < high

    def test_bulk_is_untouched(self) -> None:
        """The bulk of the distribution is not part of the clipping map."""
        values = [float(v) for v in range(100)]
        clipping, _, _ = iqr_outlier_map(values)
        assert 50.0 not in clipping

    def test_small_series_is_not_clipped(self) -> None:
        """A series of less than four values is left alone."""
        clipping, low, high = iqr_outlier_map([1.0, 2.0, 3.0])
        assert clipping == {}
        assert (low, high) == (1.0, 3.0)

    def test_empty_series(self) -> None:
        """An empty series yields an empty clipping map."""
        clipping, low, high = iqr_outlier_map([])
        assert clipping == {}
        assert (low, high) == (0.0, 0.0)

    def test_invalid_factor_is_rejected(self) -> None:
        """A non-positive factor raises a ``ValueError``."""
        with pytest.raises(ValueError, match="strictly positive"):
            iqr_outlier_map([1.0, 2.0, 3.0, 4.0], factor=0)


class TestWinsorizeEdgeCases:
    """Additional edge cases of :func:`winsorize`."""

    def test_single_value(self) -> None:
        """A single-value series is not clipped."""
        clipping, low, high = winsorize([42.0])
        assert clipping == {}
        assert (low, high) == (42.0, 42.0)

    def test_non_finite_values_are_ignored(self) -> None:
        """``NaN`` and ``inf`` do not take part in the fences."""
        values = [1.0, 2.0, 3.0, 4.0, float("nan"), float("inf")]
        clipping, low, high = winsorize(values)
        assert low == 1.0
        assert high == 4.0
        assert clipping == {}


class TestParseBool:
    """Tests of :func:`parse_bool`."""

    @pytest.mark.parametrize(
        ("raw", "expected"),
        [
            ("true", True),
            ("TRUE", True),
            ("t", True),
            ("yes", True),
            ("y", True),
            ("1", True),
            ("false", False),
            ("FALSE", False),
            ("f", False),
            ("no", False),
            ("n", False),
            ("0", False),
        ],
    )
    def test_known_tokens(self, raw: Any, expected: bool) -> None:
        """Every documented token is recognized."""
        assert parse_bool(raw) is expected

    @pytest.mark.parametrize("raw", [None, "", "  ", "maybe", "2", "on"])
    def test_unknown_tokens_use_the_default(self, raw: Any) -> None:
        """An unrecognized token returns the default."""
        assert parse_bool(raw) is None
        assert parse_bool(raw, default=True) is True

    def test_native_booleans(self) -> None:
        """A native boolean is returned unchanged."""
        assert parse_bool(True) is True
        assert parse_bool(False) is False


class TestNormalizeIdentifier:
    """Tests of :func:`normalize_identifier`."""

    def test_case_is_preserved(self) -> None:
        """The case of an identifier is never altered."""
        assert normalize_identifier("C000001") == "C000001"
        assert normalize_identifier("c000001") == "c000001"

    def test_whitespace_is_trimmed(self) -> None:
        """The surrounding whitespace is removed."""
        assert normalize_identifier("  U000001  ") == "U000001"

    def test_none_becomes_an_empty_string(self) -> None:
        """``None`` becomes an empty string."""
        assert normalize_identifier(None) == ""

    def test_non_string_values(self) -> None:
        """A non-string value is stringified."""
        assert normalize_identifier(42) == "42"

    def test_internal_whitespace_is_preserved(self) -> None:
        """Only the *surrounding* whitespace is removed."""
        assert normalize_identifier("a b") == "a b"


class TestCanonicalTextEdgeCases:
    """Additional edge cases of :func:`canonical_text`."""

    def test_internal_whitespace_is_collapsed(self) -> None:
        """The internal whitespace runs collapse into a single space."""
        assert canonical_text("a   b") == "a b"

    def test_unicode_is_normalized(self) -> None:
        """The compatibility characters are normalized."""
        assert canonical_text("ﬁ") == "fi"

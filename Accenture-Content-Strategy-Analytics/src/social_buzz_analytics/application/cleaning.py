"""Cleaning and harmonization primitives.

This module implements the reusable, dataset-agnostic part of the cleaning
stage: parsing of messy cells, imputation of missing values, categorical
harmonization and outlier control.  Each concern is a small, independently
testable unit that the dataset cleaners compose.

Design rules
------------
* Every rule is **pure**: it never mutates its input and always returns a
  new value plus a report of what it did.
* Every rule is **total**: it never raises on unexpected input, it degrades
  to a documented fallback instead.
* Rules are **composable** through the :class:`CleaningContext`, which
  accumulates the counters used by the data-quality report.
"""

from __future__ import annotations

import math
import re
from collections.abc import Sequence
from dataclasses import dataclass, field
from datetime import datetime, timezone
from difflib import SequenceMatcher
from typing import Any, Final

from ..domain.value_objects import CATEGORY_ALIASES, canonical_text, normalize_category

__all__ = [
    "CleaningContext",
    "harmonize_category",
    "parse_bool",
    "parse_datetime",
    "parse_int",
    "parse_non_negative_int",
    "winsorize",
]

_NUMERIC_RE: Final[re.Pattern[str]] = re.compile(r"[-+]?\d[\d,\s]*\.?\d*")
_THOUSANDS_SEPARATORS: Final[str] = ",  "
_DATE_FORMATS: Final[tuple[str, ...]] = (
    "%Y-%m-%dT%H:%M:%S",
    "%Y-%m-%d %H:%M:%S",
    "%Y-%m-%d %H:%M",
    "%Y-%m-%d",
    "%d/%m/%Y %H:%M:%S",
    "%d/%m/%Y",
    "%m/%d/%Y",
    "%d-%m-%Y",
    "%Y/%m/%d",
    "%b %d, %Y",
    "%d %b %Y",
)

_TRUE_TOKENS: Final[frozenset[str]] = frozenset({"true", "t", "yes", "y", "1"})
_FALSE_TOKENS: Final[frozenset[str]] = frozenset({"false", "f", "no", "n", "0"})


@dataclass(slots=True)
class CleaningContext:
    """Mutable accumulator of the counters of a cleaning run.

    Attributes:
        missing_filled: Number of cells that received an imputed value.
        values_normalized: Number of cells that were harmonized.
        outliers_clipped: Number of cells that were clipped or winsorized.
        invalid_values: Number of cells that could not be parsed at all.
    """

    missing_filled: int = 0
    values_normalized: int = 0
    outliers_clipped: int = 0
    invalid_values: int = 0
    notes: list[str] = field(default_factory=list)

    def note(self, message: str) -> None:
        """Attach a free-form note to the report."""
        self.notes.append(message)


def _strip_numeric_noise(raw: str) -> str:
    """Remove grouping separators that break numeric parsing."""
    return raw.replace(",", "").replace(" ", "").replace(" ", "")


def parse_int(raw: Any, default: int | None = 0) -> int | None:
    """Parse an integer from a messy cell.

    Handles integers, floats, numeric strings with thousand separators
    (``"12,345"``) and surrounding whitespace.

    Parameters
    ----------
    raw:
        The raw cell value.
    default:
        Value returned when the cell cannot be interpreted as a number.
        Pass ``None`` to signal "no value".

    Returns
    -------
    int | None
        The parsed integer, or ``default``.
    """
    if raw is None:
        return default
    if isinstance(raw, bool):
        return int(raw)
    if isinstance(raw, int):
        return raw
    if isinstance(raw, float):
        if math.isnan(raw) or math.isinf(raw):
            return default
        return int(raw)
    text = canonical_text(raw)
    if not text:
        return default
    try:
        return int(text)
    except ValueError:
        pass
    try:
        return int(float(text))
    except ValueError:
        pass
    match = _NUMERIC_RE.search(text)
    if match:
        candidate = _strip_numeric_noise(match.group(0))
        try:
            return int(float(candidate))
        except ValueError:
            return default
    return default


def parse_non_negative_int(raw: Any, default: int = 0) -> int:
    """Parse an integer and clamp it to ``>= 0``.

    Negative counters (a frequent artifact of corrupted exports) are
    floored at zero, because a negative impression count has no meaning.
    """
    value = parse_int(raw, default=None)
    if value is None:
        return default
    return max(0, value)


def parse_float(raw: Any, default: float | None = None) -> float | None:
    """Parse a floating point number from a messy cell.

    Returns
    -------
    float | None
        The parsed value, or ``default`` when the cell is unparsable.
    """
    if raw is None:
        return default
    if isinstance(raw, bool):
        return float(raw)
    if isinstance(raw, (int, float)):
        value = float(raw)
        if math.isnan(value) or math.isinf(value):
            return default
        return value
    text = canonical_text(raw)
    if not text:
        return default
    try:
        value = float(text)
    except ValueError:
        match = _NUMERIC_RE.search(text)
        if not match:
            return default
        try:
            value = float(_strip_numeric_noise(match.group(0)))
        except ValueError:
            return default
    if math.isnan(value) or math.isinf(value):
        return default
    return value


def parse_bool(raw: Any, default: bool | None = None) -> bool | None:
    """Parse a boolean from a messy cell.

    Recognizes ``true/t/yes/y/1`` and ``false/f/no/n/0`` in any casing.

    Returns
    -------
    bool | None
        The parsed flag, or ``default``.
    """
    if raw is None:
        return default
    if isinstance(raw, bool):
        return raw
    text = canonical_text(raw)
    if not text:
        return default
    if text in _TRUE_TOKENS:
        return True
    if text in _FALSE_TOKENS:
        return False
    return default


def parse_datetime(raw: Any, default: datetime | None = None) -> datetime | None:
    """Parse a timestamp from a messy cell.

    The function tries a list of common layouts and always returns a
    timezone-aware UTC datetime.  Naive timestamps are assumed to be UTC.

    Parameters
    ----------
    raw:
        The raw cell value.
    default:
        Value returned when the cell cannot be interpreted as a timestamp.

    Returns
    -------
    datetime | None
        The parsed timestamp in UTC, or ``default``.
    """
    if raw is None:
        return default
    if isinstance(raw, datetime):
        return raw if raw.tzinfo else raw.replace(tzinfo=timezone.utc)
    text = canonical_text(raw)
    if not text:
        return default
    # Numeric epochs (seconds or milliseconds).
    numeric = parse_float(text, default=None)
    if numeric is not None and re.fullmatch(r"-?\d+(\.\d+)?", text):
        seconds = numeric / 1000.0 if abs(numeric) > 1e11 else numeric
        try:
            return datetime.fromtimestamp(seconds, tz=timezone.utc)
        except (OverflowError, OSError, ValueError):
            return default
    for fmt in _DATE_FORMATS:
        try:
            parsed = datetime.strptime(text, fmt)
        except ValueError:
            continue
        return parsed.replace(tzinfo=timezone.utc)
    try:
        parsed = datetime.fromisoformat(text)
    except ValueError:
        return default
    return parsed if parsed.tzinfo else parsed.replace(tzinfo=timezone.utc)


def harmonize_category(raw: Any, default: str = "Other") -> str:
    """Map a raw category label onto the canonical taxonomy.

    The resolution is applied in three steps, from the most to the least
    confident:

    1. an exact lookup in the domain alias table (case and separator
       insensitive);
    2. a lookup of the head of the label, which handles the labels that
       embed a qualifier (``"Technology & Innovation"``);
    3. a fuzzy match against the alias table, which recovers the typos
       introduced by manual re-tagging (``"Technolgy"``).

    The taxonomy itself lives in the domain layer
    (:data:`social_buzz_analytics.domain.value_objects.CATEGORY_ALIASES`),
    so the business vocabulary has exactly one definition.

    Categories that cannot be resolved are mapped to ``default`` so that no
    reaction is ever lost because of an unmapped label.

    Parameters
    ----------
    raw:
        The raw category label.
    default:
        Display name used when the label cannot be resolved.

    Returns
    -------
    str
        A canonical category display name.
    """
    text = canonical_text(raw)
    if not text:
        return default
    resolved = normalize_category(text, default=default)
    if resolved != default:
        return resolved
    stripped = re.sub(r"[\s_]+", " ", text)
    if stripped != text:
        resolved = normalize_category(stripped, default=default)
        if resolved != default:
            return resolved
    return _fuzzy_category(text, default)


def _fuzzy_category(text: str, default: str, cutoff: float = 0.82) -> str:
    """Resolve a category label by fuzzy-matching the canonical taxonomy.

    The match uses the ``difflib`` ratio against every alias of the
    taxonomy; a label is accepted only above ``cutoff``, which keeps the
    fuzzy step from merging two genuinely different categories.
    """
    best_match = ""
    best_ratio = 0.0
    for alias, display in CATEGORY_ALIASES.items():
        ratio = SequenceMatcher(None, text, alias).ratio()
        if ratio > best_ratio:
            best_ratio = ratio
            best_match = display
    if best_ratio >= cutoff and best_match:
        return best_match
    return default


def winsorize(
    values: Sequence[float],
    lower_quantile: float = 0.01,
    upper_quantile: float = 0.99,
) -> tuple[dict[float, float], float, float]:
    """Compute a winsorization map for a numeric series.

    Values below the lower bound are lifted to it and values above the
    upper bound are lowered to it, which keeps the shape of the
    distribution while removing the influence of extreme outliers.

    The fences are computed with the *nearest-rank* method, so both
    bounds are values that actually occur in the series.  This makes the
    resulting clipping map easy to audit: every clipped value is moved to
    a value that the business can point at in the source data.

    Parameters
    ----------
    values:
        The numeric series.
    lower_quantile:
        Lower quantile of the series (must be in ``[0, 1)``).
    upper_quantile:
        Upper quantile of the series (must be in ``(0, 1]``).

    Returns
    -------
    tuple[dict[float, float], float, float]
        A mapping of *outlier value* to *clipped value*, the lower bound
        and the upper bound.  The mapping is empty when nothing had to be
        clipped.

    Raises
    ------
    ValueError
        If the quantiles are out of range or inverted.
    """
    if not 0.0 <= lower_quantile < 1.0:
        raise ValueError("lower_quantile must be in [0, 1)")
    if not 0.0 < upper_quantile <= 1.0:
        raise ValueError("upper_quantile must be in (0, 1]")
    if lower_quantile >= upper_quantile:
        raise ValueError("lower_quantile must be lower than upper_quantile")

    numbers = sorted(v for v in values if v is not None and math.isfinite(v))
    if len(numbers) < 4:
        return {}, (numbers[0] if numbers else 0.0), (numbers[-1] if numbers else 0.0)

    low = _nearest_rank(numbers, lower_quantile)
    high = _nearest_rank(numbers, upper_quantile)
    clipping: dict[float, float] = {}
    for value in numbers:
        if value < low:
            clipping[value] = low
        elif value > high:
            clipping[value] = high
    return clipping, low, high


def iqr_outlier_map(
    values: Sequence[float], factor: float = 1.5
) -> tuple[dict[float, float], float, float]:
    """Compute an outlier-clipping map from the interquartile range.

    The classic *tukey* rule is used: a value is an outlier when it lies
    below ``Q1 - factor * IQR`` or above ``Q3 + factor * IQR``.  Unlike a
    quantile-based fence, this rule keeps working on small series, where
    the extreme quantiles would coincide with the minimum and the maximum
    and would therefore never clip anything.

    Parameters
    ----------
    values:
        The numeric series.
    factor:
        The multiplier of the interquartile range (must be positive).

    Returns
    -------
    tuple[dict[float, float], float, float]
        A mapping of *outlier value* to *clipped value*, the lower fence
        and the upper fence.

    Raises
    ------
    ValueError
        If ``factor`` is not strictly positive.
    """
    if factor <= 0:
        raise ValueError("factor must be strictly positive")

    numbers = sorted(v for v in values if v is not None and math.isfinite(v))
    if len(numbers) < 4:
        return {}, (numbers[0] if numbers else 0.0), (numbers[-1] if numbers else 0.0)

    first_quartile = _nearest_rank(numbers, 0.25)
    third_quartile = _nearest_rank(numbers, 0.75)
    iqr = third_quartile - first_quartile
    lower_fence = first_quartile - factor * iqr
    upper_fence = third_quartile + factor * iqr

    clipping: dict[float, float] = {}
    for value in numbers:
        if value < lower_fence:
            clipping[value] = lower_fence
        elif value > upper_fence:
            clipping[value] = upper_fence
    return clipping, lower_fence, upper_fence


def _nearest_rank(sorted_values: Sequence[float], quantile: float) -> float:
    """Compute the nearest-rank quantile of a sorted series.

    The nearest-rank method returns a value that actually occurs in the
    series, which makes the fences auditable.
    """
    if not sorted_values:
        raise ValueError("cannot compute a quantile of an empty series")
    if len(sorted_values) == 1:
        return sorted_values[0]
    rank = math.ceil(quantile * len(sorted_values))
    index = min(max(rank - 1, 0), len(sorted_values) - 1)
    return sorted_values[index]


def impute(values: Sequence[Any], strategy: str = "median") -> Any:
    """Impute the missing values of a series with a central tendency.

    Parameters
    ----------
    values:
        The series to impute; ``None`` and empty strings count as missing.
    strategy:
        One of ``median``, ``mean``, ``mode`` or ``zero``.

    Returns
    -------
    Any
        The imputed value, or ``None`` when the series holds no usable
        value.

    Raises
    ------
    ValueError
        If the strategy is unknown.
    """
    if strategy not in {"median", "mean", "mode", "zero"}:
        raise ValueError(f"unknown imputation strategy: {strategy!r}")

    if strategy == "zero":
        return 0

    usable = [v for v in values if v is not None and canonical_text(v) != ""]
    if not usable:
        return None

    numbers: list[float] = []
    for value in usable:
        parsed = parse_float(value, default=None)
        if parsed is not None:
            numbers.append(parsed)
    if not numbers:
        return None

    if strategy == "mean":
        return sum(numbers) / len(numbers)
    if strategy == "median":
        ordered = sorted(numbers)
        middle = len(ordered) // 2
        if len(ordered) % 2 == 1:
            return ordered[middle]
        return (ordered[middle - 1] + ordered[middle]) / 2

    counts: dict[float, int] = {}
    for number in numbers:
        counts[number] = counts.get(number, 0) + 1
    return max(counts.items(), key=lambda item: (item[1], -item[0]))[0]

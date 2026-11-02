"""Rolling statistics used to derive the alert bands."""

from __future__ import annotations

from collections import deque
from dataclasses import dataclass
from math import isfinite, sqrt
from typing import Iterable, Sequence

from .errors import AggregationError
from .models import Band


def mean(values: Sequence[float]) -> float:
    """Arithmetic mean of a non-empty sequence of floats.

    Implemented locally instead of relying on ``math.fmean`` so that the
    package works on every interpreter (some builds ship a reduced
    ``math`` module) and so that the hot path stays allocation free.
    """
    if not values:
        raise AggregationError("cannot compute the mean of an empty sequence")
    return sum(values) / len(values)


def sample_stdev(values: Sequence[float]) -> float:
    """Sample standard deviation (Bessel corrected) of *values*.

    ``statistics.stdev`` computes the exact result with rational
    arithmetic, which is accurate but roughly two orders of magnitude
    slower.  The hot path of the alert engine evaluates this statistic for
    every tick, therefore a float-native implementation is used here.  The
    numerical difference versus the exact result is far below the noise
    floor of a market feed.

    Returns ``0.0`` for fewer than two observations.
    """
    count = len(values)
    if count < 2:
        return 0.0
    average = sum(values) / count
    variance = sum((value - average) ** 2 for value in values) / (count - 1)
    return sqrt(variance) if variance > 0.0 else 0.0




@dataclass(frozen=True, slots=True)
class ThresholdPolicy:
    """Configuration of the rolling alert band.

    Attributes
    ----------
    window_size:
        Number of observations kept in the rolling window.  Must be >= 2.
    sigma_multiplier:
        Number of standard deviations used as band half width.
    min_half_width:
        Absolute floor for the band half width.  It keeps the band usable
        while the series is still short and the observed dispersion is
        (numerically) zero.
    """

    window_size: int = 20
    sigma_multiplier: float = 3.0
    min_half_width: float = 0.005

    def __post_init__(self) -> None:
        if self.window_size < 2:
            raise AggregationError(
                f"window_size must be >= 2, got {self.window_size}"
            )
        if not isfinite(self.sigma_multiplier) or self.sigma_multiplier < 0:
            raise AggregationError(
                f"sigma_multiplier must be a finite non-negative number, "
                f"got {self.sigma_multiplier}"
            )
        if not isfinite(self.min_half_width) or self.min_half_width < 0:
            raise AggregationError(
                f"min_half_width must be a finite non-negative number, "
                f"got {self.min_half_width}"
            )


class RollingRatioTracker:
    """Maintains the alert band of a ratio series.

    The tracker is *causal*: :meth:`update` derives the band from the
    observations seen **before** the new value and only then appends the new
    value to the window.  A single anomalous tick therefore cannot widen the
    band that is supposed to detect it.

    Examples
    --------
    >>> tracker = RollingRatioTracker(ThresholdPolicy(window_size=10))
    >>> band = tracker.update(1.0)
    >>> band.lower_bound <= 1.0 <= band.upper_bound
    True
    """

    __slots__ = ("_policy", "_values")

    def __init__(self, policy: ThresholdPolicy | None = None) -> None:
        self._policy = policy or ThresholdPolicy()
        self._values: deque[float] = deque(maxlen=self._policy.window_size)

    @property
    def policy(self) -> ThresholdPolicy:
        """The threshold policy in use."""
        return self._policy

    @property
    def samples(self) -> int:
        """Number of observations currently held in the rolling window."""
        return len(self._values)

    def history(self) -> list[float]:
        """Return a copy of the rolling window, oldest observation first."""
        return list(self._values)

    def reset(self) -> None:
        """Drop every observation."""
        self._values.clear()

    def update(self, value: float) -> Band:
        """Register *value* and return the band it must be compared against."""
        if not isfinite(value):
            raise AggregationError(f"ratio must be finite, got {value!r}")

        history = list(self._values)
        if history:
            center = mean(history)
            sigma = sample_stdev(history) if len(history) >= 2 else 0.0
        else:
            # Cold start: the band is centred on the first observation so that
            # a fresh instrument can never trigger a spurious alert.
            center = value
            sigma = 0.0

        half_width = max(self._policy.sigma_multiplier * sigma, self._policy.min_half_width)
        band = Band(
            lower_bound=center - half_width,
            upper_bound=center + half_width,
            center=center,
            sigma=sigma,
            samples=len(history) + 1,
        )
        self._values.append(value)
        return band


class PriceBaseline:
    """Rolling mean of the mid prices of a single instrument.

    The baseline is the denominator of the "price versus its own recent
    average" ratio that is displayed for every instrument.
    """

    __slots__ = ("_window_size", "_values")

    def __init__(self, window_size: int = 20) -> None:
        if window_size < 1:
            raise AggregationError(f"window_size must be >= 1, got {window_size}")
        self._window_size = window_size
        self._values: deque[float] = deque(maxlen=window_size)

    @property
    def samples(self) -> int:
        """Number of prices currently held in the window."""
        return len(self._values)

    def update(self, price: float) -> float:
        """Append *price* and return the updated rolling mean."""
        if not isfinite(price) or price <= 0:
            raise AggregationError(f"price must be finite and positive, got {price!r}")
        self._values.append(price)
        return mean(self._values)

    def reset(self) -> None:
        """Drop every observation."""
        self._values.clear()


def ratios(numerator: Iterable[float], denominator: Iterable[float]) -> list[float]:
    """Element wise ratio of two iterables, skipping undefined pairs.

    Pairs where the denominator is zero (or the ratio is not finite) are
    skipped instead of raising, which keeps a partial feed from killing the
    aggregation pipeline.
    """
    result: list[float] = []
    for num, den in zip(numerator, denominator):
        if den == 0:
            continue
        ratio = num / den
        if not isfinite(ratio):
            continue
        result.append(ratio)
    return result

"""Mock market data generator producing realistic top-of-book ticks."""

from __future__ import annotations

import random
from dataclasses import dataclass
from typing import Iterator, Mapping, Sequence

from ..core.errors import TickValidationError
from ..core.models import Tick

#: Default universe of instruments used by the demo and the tests.
DEFAULT_UNIVERSE: Mapping[str, float] = {
    "AAPL": 189.50,
    "MSFT": 412.30,
    "JPM": 208.75,
    "GS": 495.10,
    "XOM": 117.40,
    "CVX": 148.90,
}


@dataclass(frozen=True, slots=True)
class InstrumentSpec:
    """Static description of a traded instrument.

    Attributes
    ----------
    symbol:
        Ticker symbol.
    reference_price:
        Price the random walk starts from.
    tick_size:
        Minimum price increment of the venue.
    spread_bps:
        Typical quoted spread in basis points of the mid price.
    volatility_bps:
        Standard deviation of the per-tick price move, in basis points.
    """

    symbol: str
    reference_price: float
    tick_size: float = 0.01
    spread_bps: float = 2.0
    volatility_bps: float = 8.0

    def __post_init__(self) -> None:
        if self.reference_price <= 0:
            raise TickValidationError(
                f"reference_price must be positive, got {self.reference_price}",
                "reference_price",
            )
        if self.tick_size <= 0:
            raise TickValidationError(
                f"tick_size must be positive, got {self.tick_size}", "tick_size"
            )


def default_universe() -> tuple[InstrumentSpec, ...]:
    """Return the default instrument universe used across the project."""
    return tuple(
        InstrumentSpec(symbol=symbol, reference_price=price)
        for symbol, price in DEFAULT_UNIVERSE.items()
    )


class MockTickGenerator:
    """Generates a continuous stream of synthetic top-of-book ticks.

    The generator walks a geometric random walk around each instrument's
    reference price and quotes a two sided market around the resulting mid
    price.  It is fully deterministic for a given ``seed`` which makes it
    usable in tests.

    Parameters
    ----------
    universe:
        The instruments to quote.  Defaults to :func:`default_universe`.
    seed:
        Seed of the internal random generator.
    start_timestamp:
        Timestamp (epoch milliseconds) of the very first tick.
    tick_interval_ms:
        Logical time increment between two consecutive ticks.
    """

    def __init__(
        self,
        universe: Sequence[InstrumentSpec] | None = None,
        seed: int | None = 1337,
        start_timestamp: int = 1_700_000_000_000,
        tick_interval_ms: int = 100,
    ) -> None:
        self._universe = tuple(default_universe() if universe is None else universe)
        if not self._universe:
            raise TickValidationError("universe must not be empty", "universe")
        self._random = random.Random(seed)
        self._prices: dict[str, float] = {
            spec.symbol: spec.reference_price for spec in self._universe
        }
        self._timestamp = start_timestamp
        self._tick_interval_ms = tick_interval_ms

    @property
    def universe(self) -> tuple[InstrumentSpec, ...]:
        """The instruments quoted by this generator."""
        return self._universe

    @property
    def timestamp(self) -> int:
        """Timestamp that will be assigned to the next produced tick."""
        return self._timestamp

    def _next_price(self, spec: InstrumentSpec) -> float:
        move_bps = self._random.gauss(0.0, spec.volatility_bps)
        factor = 1.0 + (move_bps / 10_000.0)
        price = self._prices[spec.symbol] * factor
        price = max(price, spec.tick_size)
        self._prices[spec.symbol] = price
        return price

    def _round_to_tick(self, price: float, spec: InstrumentSpec) -> float:
        return round(round(price / spec.tick_size) * spec.tick_size, 10)

    def next_tick(self) -> Tick:
        """Produce the next tick for a randomly chosen instrument."""
        spec = self._random.choice(self._universe)
        return self._tick_for(spec)

    def _tick_for(self, spec: InstrumentSpec) -> Tick:
        mid = self._next_price(spec)
        half_spread = mid * (spec.spread_bps / 10_000.0) / 2.0
        bid = self._round_to_tick(max(mid - half_spread, spec.tick_size), spec)
        ask = self._round_to_tick(max(mid + half_spread, bid), spec)
        tick = Tick(
            stock=spec.symbol,
            top_ask_price=ask,
            top_bid_price=bid,
            timestamp=self._timestamp,
        )
        self._timestamp += self._tick_interval_ms
        return tick

    def stream(self, count: int | None = None) -> Iterator[Tick]:
        """Yield ticks indefinitely, or exactly *count* of them."""
        produced = 0
        while count is None or produced < count:
            yield self.next_tick()
            produced += 1

    def burst(self, count: int) -> list[Tick]:
        """Return exactly *count* ticks as a list."""
        if count < 0:
            raise TickValidationError(f"count must not be negative, got {count}", "count")
        return list(self.stream(count))

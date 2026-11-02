"""The aggregation engine: raw ticks in, Perspective grid rows out.

The engine is a pure, in-memory state machine.  It owns no I/O, which makes
it trivial to unit test and safe to run in a tight loop.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Iterable, Iterator, Mapping

from .errors import AggregationError
from .models import (
    KIND_PAIR,
    KIND_SYMBOL,
    GridRow,
    Quote,
    Tick,
)
from .thresholds import PriceBaseline, RollingRatioTracker, ThresholdPolicy

#: A correlated pair of instruments, expressed as ``(numerator, denominator)``.
Pair = tuple[str, str]


@dataclass(slots=True)
class AggregationStats:
    """Counters describing what the engine has seen so far."""

    ticks_ingested: int = 0
    ticks_rejected: int = 0
    rows_emitted: int = 0
    alerts_emitted: int = 0
    out_of_order_ticks: int = 0
    pair_rows_emitted: int = 0

    def as_dict(self) -> dict[str, int]:
        """Return the counters as a plain dictionary."""
        return {
            "ticks_ingested": self.ticks_ingested,
            "ticks_rejected": self.ticks_rejected,
            "rows_emitted": self.rows_emitted,
            "alerts_emitted": self.alerts_emitted,
            "out_of_order_ticks": self.out_of_order_ticks,
            "pair_rows_emitted": self.pair_rows_emitted,
        }


class QuoteAggregator:
    """Aggregates incoming ticks into Perspective-ready grid rows.

    Two families of rows are produced:

    ``symbol`` rows
        One per instrument update.  ``price`` is the mid price, ``ratio`` is
        the price relative to the instrument's own rolling baseline and the
        bounds delimit the expected dispersion of that ratio.

    ``pair`` rows
        One per correlated pair that has both legs quoted.  ``ratio`` is the
        price ratio between the two instruments, which is the discrepancy
        the desk is actually interested in.

    Parameters
    ----------
    policy:
        Threshold policy controlling the rolling window and the band width.
    pairs:
        Correlated instrument pairs, e.g. ``("AAPL", "MSFT")``.
    """

    def __init__(
        self,
        policy: ThresholdPolicy | None = None,
        pairs: Iterable[Pair] = (),
    ) -> None:
        self._policy = policy or ThresholdPolicy()
        self._pairs: tuple[Pair, ...] = tuple(
            (a.strip().upper(), b.strip().upper()) for a, b in pairs
        )
        self._quotes: dict[str, Quote] = {}
        self._baselines: dict[str, PriceBaseline] = {}
        self._symbol_trackers: dict[str, RollingRatioTracker] = {}
        self._pair_trackers: dict[Pair, RollingRatioTracker] = {}
        self._stats = AggregationStats()

    # ------------------------------------------------------------------
    # Introspection
    # ------------------------------------------------------------------
    @property
    def policy(self) -> ThresholdPolicy:
        """The threshold policy in use."""
        return self._policy

    @property
    def pairs(self) -> tuple[Pair, ...]:
        """The correlated pairs monitored by the engine."""
        return self._pairs

    @property
    def stats(self) -> AggregationStats:
        """Live counters of the engine."""
        return self._stats

    @property
    def quotes(self) -> Mapping[str, Quote]:
        """Read-only view on the latest quote per instrument."""
        return dict(self._quotes)

    def latest_quote(self, symbol: str) -> Quote | None:
        """Return the latest quote of *symbol* or ``None``."""
        return self._quotes.get(symbol.strip().upper())

    # ------------------------------------------------------------------
    # Ingestion
    # ------------------------------------------------------------------
    def ingest(self, tick: Tick) -> list[GridRow]:
        """Aggregate a single tick and return the rows it produced.

        The tick must already be validated; use :meth:`ingest_raw` when the
        payload still comes straight off the wire.
        """
        if not isinstance(tick, Tick):
            raise AggregationError(
                f"expected a Tick instance, got {type(tick).__name__}"
            )

        self._stats.ticks_ingested += 1
        previous = self._quotes.get(tick.stock)
        if previous is not None and tick.timestamp < previous.timestamp:
            self._stats.out_of_order_ticks += 1

        self._quotes[tick.stock] = Quote.from_tick(tick)

        rows: list[GridRow] = [self._build_symbol_row(tick)]
        rows.extend(self._build_pair_rows(tick))

        for row in rows:
            self._stats.rows_emitted += 1
            if row.trigger_alert:
                self._stats.alerts_emitted += 1
            if row.kind == KIND_PAIR:
                self._stats.pair_rows_emitted += 1
        return rows

    def ingest_raw(self, payload: Mapping[str, Any] | Tick) -> list[GridRow]:
        """Validate and aggregate a raw payload.

        Invalid payloads are counted in :attr:`stats` and yield an empty row
        list instead of raising, so that a single malformed frame cannot tear
        down a live feed.
        """
        try:
            tick = payload if isinstance(payload, Tick) else Tick.from_dict(payload)
        except Exception:
            self._stats.ticks_rejected += 1
            return []
        return self.ingest(tick)

    def ingest_many(self, payloads: Iterable[Mapping[str, Any] | Tick]) -> list[GridRow]:
        """Aggregate a batch of payloads and return every produced row."""
        rows: list[GridRow] = []
        for payload in payloads:
            rows.extend(self.ingest_raw(payload))
        return rows

    def iter_rows(self, payloads: Iterable[Mapping[str, Any] | Tick]) -> Iterator[GridRow]:
        """Lazily aggregate payloads, yielding rows one by one."""
        for payload in payloads:
            yield from self.ingest_raw(payload)

    # ------------------------------------------------------------------
    # Internals
    # ------------------------------------------------------------------
    def _build_symbol_row(self, tick: Tick) -> GridRow:
        baseline = self._baselines.get(tick.stock)
        if baseline is None:
            baseline = PriceBaseline(self._policy.window_size)
            self._baselines[tick.stock] = baseline

        price = tick.mid_price
        mean_price = baseline.update(price)
        ratio = price / mean_price

        tracker = self._symbol_trackers.get(tick.stock)
        if tracker is None:
            tracker = RollingRatioTracker(self._policy)
            self._symbol_trackers[tick.stock] = tracker
        band = tracker.update(ratio)

        return GridRow(
            stock=tick.stock,
            kind=KIND_SYMBOL,
            price=price,
            ratio=ratio,
            upper_bound=band.upper_bound,
            lower_bound=band.lower_bound,
            trigger_alert=band.breaches(ratio),
            timestamp=tick.timestamp,
        )

    def _build_pair_rows(self, tick: Tick) -> list[GridRow]:
        rows: list[GridRow] = []
        for pair in self._pairs:
            numerator, denominator = pair
            if tick.stock not in (numerator, denominator):
                continue

            num_quote = self._quotes.get(numerator)
            den_quote = self._quotes.get(denominator)
            if num_quote is None or den_quote is None:
                # One leg has not been quoted yet: the ratio is undefined and
                # no row must be emitted.
                continue

            num_price = num_quote.mid_price
            den_price = den_quote.mid_price
            if den_price <= 0:  # pragma: no cover - prices are validated
                continue
            ratio = num_price / den_price

            tracker = self._pair_trackers.get(pair)
            if tracker is None:
                tracker = RollingRatioTracker(self._policy)
                self._pair_trackers[pair] = tracker
            band = tracker.update(ratio)

            rows.append(
                GridRow(
                    stock=f"{numerator}/{denominator}",
                    kind=KIND_PAIR,
                    price=num_price,
                    ratio=ratio,
                    upper_bound=band.upper_bound,
                    lower_bound=band.lower_bound,
                    trigger_alert=band.breaches(ratio),
                    timestamp=max(num_quote.timestamp, den_quote.timestamp),
                )
            )
        return rows

    def reset(self) -> None:
        """Forget every quote, band and counter."""
        self._quotes.clear()
        self._baselines.clear()
        self._symbol_trackers.clear()
        self._pair_trackers.clear()
        self._stats = AggregationStats()

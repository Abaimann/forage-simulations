"""Application services orchestrating the feed -> aggregation -> sink flow."""

from __future__ import annotations

import time
from dataclasses import dataclass, field
from typing import Callable, Iterable

from ..core.aggregator import AggregationStats, Pair, QuoteAggregator
from ..core.models import GridRow, Tick
from ..core.thresholds import ThresholdPolicy
from ..infrastructure.sinks import RowSink


@dataclass(slots=True)
class ThroughputReport:
    """Measured throughput of a streaming run."""

    ticks: int = 0
    rows: int = 0
    alerts: int = 0
    elapsed_seconds: float = 0.0
    ticks_per_second: float = 0.0
    rows_per_second: float = 0.0
    latencies_ms: list[float] = field(default_factory=list)

    @property
    def mean_latency_ms(self) -> float:
        """Mean end-to-end latency per tick, in milliseconds."""
        if not self.latencies_ms:
            return 0.0
        return sum(self.latencies_ms) / len(self.latencies_ms)

    @property
    def p95_latency_ms(self) -> float:
        """95th percentile of the measured latencies, in milliseconds."""
        if not self.latencies_ms:
            return 0.0
        ordered = sorted(self.latencies_ms)
        index = min(len(ordered) - 1, int(round(0.95 * (len(ordered) - 1))))
        return ordered[index]

    def as_dict(self) -> dict[str, float | int]:
        """Return the report as a plain dictionary."""
        return {
            "ticks": self.ticks,
            "rows": self.rows,
            "alerts": self.alerts,
            "elapsed_seconds": self.elapsed_seconds,
            "ticks_per_second": self.ticks_per_second,
            "rows_per_second": self.rows_per_second,
            "mean_latency_ms": self.mean_latency_ms,
            "p95_latency_ms": self.p95_latency_ms,
        }


class GridPipeline:
    """Wires a stream of ticks into a sink through the aggregation engine.

    Parameters
    ----------
    aggregator:
        The aggregation engine.  Defaults to a fresh
        :class:`~jpm_perspective_grid.core.aggregator.QuoteAggregator`.
    sink:
        Where the produced rows are written to.
    on_alert:
        Optional callback invoked with every row that triggered an alert.
    measure_latency:
        Record a per-tick latency sample.  Enabled by default; disable it for
        maximum throughput.
    """

    def __init__(
        self,
        aggregator: QuoteAggregator | None = None,
        sink: RowSink | None = None,
        on_alert: Callable[[GridRow], None] | None = None,
        measure_latency: bool = True,
    ) -> None:
        from ..infrastructure.sinks import MemorySink  # local import avoids a cycle

        self._aggregator = aggregator or QuoteAggregator()
        self._sink = sink or MemorySink()
        self._on_alert = on_alert
        self._measure_latency = measure_latency

    @property
    def aggregator(self) -> QuoteAggregator:
        """The aggregation engine in use."""
        return self._aggregator

    @property
    def sink(self) -> RowSink:
        """The sink rows are written to."""
        return self._sink

    def process(self, tick: Tick) -> list[GridRow]:
        """Aggregate a single tick and forward the produced rows."""
        rows = self._aggregator.ingest(tick)
        self._sink.write(rows)
        if self._on_alert is not None:
            for row in rows:
                if row.trigger_alert:
                    self._on_alert(row)
        return rows

    def process_many(self, ticks: Iterable[Tick]) -> list[GridRow]:
        """Aggregate a batch of ticks and forward the produced rows."""
        produced: list[GridRow] = []
        for tick in ticks:
            produced.extend(self.process(tick))
        return produced

    def run(self, ticks: Iterable[Tick]) -> ThroughputReport:
        """Consume *ticks* and return the measured throughput."""
        latencies: list[float] = []
        tick_count = 0
        row_count = 0
        alert_count = 0

        start = time.perf_counter()
        for tick in ticks:
            tick_start = time.perf_counter()
            rows = self.process(tick)
            if self._measure_latency:
                latencies.append((time.perf_counter() - tick_start) * 1000.0)
            tick_count += 1
            row_count += len(rows)
            alert_count += sum(1 for row in rows if row.trigger_alert)
        elapsed = time.perf_counter() - start

        report = ThroughputReport(
            ticks=tick_count,
            rows=row_count,
            alerts=alert_count,
            elapsed_seconds=elapsed,
            latencies_ms=latencies,
        )
        if elapsed > 0:
            report.ticks_per_second = tick_count / elapsed
            report.rows_per_second = row_count / elapsed
        return report


def build_pipeline(
    policy: ThresholdPolicy | None = None,
    pairs: Iterable[Pair] = (),
    sink: RowSink | None = None,
    on_alert: Callable[[GridRow], None] | None = None,
) -> GridPipeline:
    """Convenience factory assembling a pipeline from its parts."""
    aggregator = QuoteAggregator(policy=policy, pairs=pairs)
    return GridPipeline(aggregator=aggregator, sink=sink, on_alert=on_alert)


def stats_as_dict(stats: AggregationStats) -> dict[str, int]:
    """Return the aggregation counters as a plain dictionary."""
    return stats.as_dict()


__all__ = [
    "GridPipeline",
    "ThroughputReport",
    "build_pipeline",
    "stats_as_dict",
]

"""Unit tests for the application pipeline and the sinks."""

from __future__ import annotations

import json
import time

import pytest

from jpm_perspective_grid.application.pipeline import (
    GridPipeline,
    ThroughputReport,
    build_pipeline,
    stats_as_dict,
)
from jpm_perspective_grid.core.aggregator import QuoteAggregator
from jpm_perspective_grid.core.models import GridRow
from jpm_perspective_grid.core.thresholds import ThresholdPolicy
from jpm_perspective_grid.infrastructure.mock_feed import MockTickGenerator
from jpm_perspective_grid.infrastructure.sinks import (
    PERSPECTIVE_SCHEMA,
    MemorySink,
    rows_to_records,
)

from conftest import _coverage_is_active

#: Throughput budgets only make sense on an uninstrumented interpreter.
requires_speed = pytest.mark.skipif(
    _coverage_is_active(),
    reason="throughput budget is not meaningful under coverage tracing",
)


def _row(stock: str = "AAPL", alert: bool = False) -> GridRow:
    return GridRow(
        stock=stock,
        kind="symbol",
        price=100.0,
        ratio=1.0,
        upper_bound=1.01,
        lower_bound=0.99,
        trigger_alert=alert,
        timestamp=1_700_000_000_000,
    )


class TestMemorySink:
    def test_write_returns_the_row_count(self):
        sink = MemorySink()
        assert sink.write([_row(), _row()]) == 2

    def test_rows_are_collected(self):
        sink = MemorySink()
        sink.write([_row("AAPL"), _row("MSFT")])
        assert [row.stock for row in sink.rows] == ["AAPL", "MSFT"]

    def test_rows_property_returns_a_copy(self):
        sink = MemorySink()
        sink.write([_row()])
        sink.rows.append(_row("TSLA"))
        assert len(sink.rows) == 1

    def test_alerts_filters_on_trigger_alert(self):
        sink = MemorySink()
        sink.write([_row("AAPL"), _row("MSFT", alert=True)])
        assert [row.stock for row in sink.alerts()] == ["MSFT"]

    def test_clear_and_close(self):
        sink = MemorySink()
        sink.write([_row()])
        sink.clear()
        assert sink.rows == []
        assert sink.close() is None


class TestRowsToRecords:
    def test_records_follow_the_grid_schema(self):
        records = rows_to_records([_row()])
        assert set(records[0]) == set(PERSPECTIVE_SCHEMA)

    def test_timestamp_is_iso(self):
        records = rows_to_records([_row()])
        assert records[0]["timestamp"] == "2023-11-14T22:13:20Z"


class TestGridPipeline:
    def test_process_returns_rows_and_writes_to_the_sink(self, make_tick):
        sink = MemorySink()
        pipeline = GridPipeline(sink=sink)
        rows = pipeline.process(make_tick())
        assert len(rows) == 1
        assert len(sink.rows) == 1

    def test_process_many(self, make_tick):
        sink = MemorySink()
        pipeline = GridPipeline(sink=sink)
        rows = pipeline.process_many([make_tick(timestamp=i) for i in range(4)])
        assert len(rows) == 4
        assert len(sink.rows) == 4

    def test_alert_callback_is_invoked(self, make_tick):
        seen: list[GridRow] = []
        policy = ThresholdPolicy(window_size=5, sigma_multiplier=2.0, min_half_width=0.001)
        pipeline = GridPipeline(
            aggregator=QuoteAggregator(policy=policy), on_alert=seen.append
        )
        for index in range(10):
            pipeline.process(make_tick(ask=100.0, bid=100.0, timestamp=index))
        pipeline.process(make_tick(ask=500.0, bid=500.0, timestamp=10))
        assert seen
        assert seen[-1].trigger_alert is True

    def test_alert_callback_is_not_invoked_without_alerts(self, make_tick):
        seen: list[GridRow] = []
        pipeline = GridPipeline(on_alert=seen.append)
        pipeline.process(make_tick())
        assert seen == []

    def test_run_returns_a_throughput_report(self, make_tick):
        pipeline = GridPipeline()
        report = pipeline.run([make_tick(timestamp=i) for i in range(10)])
        assert isinstance(report, ThroughputReport)
        assert report.ticks == 10
        assert report.rows == 10
        assert report.elapsed_seconds > 0
        assert report.ticks_per_second > 0

    def test_run_counts_alerts(self, make_tick):
        policy = ThresholdPolicy(window_size=5, sigma_multiplier=2.0, min_half_width=0.001)
        pipeline = GridPipeline(aggregator=QuoteAggregator(policy=policy))
        ticks = [make_tick(ask=100.0, bid=100.0, timestamp=i) for i in range(10)]
        ticks.append(make_tick(ask=500.0, bid=500.0, timestamp=10))
        report = pipeline.run(ticks)
        assert report.alerts >= 1

    def test_latency_is_measured_by_default(self, make_tick):
        pipeline = GridPipeline()
        report = pipeline.run([make_tick(timestamp=i) for i in range(5)])
        assert len(report.latencies_ms) == 5
        assert report.mean_latency_ms >= 0
        assert report.p95_latency_ms >= 0

    def test_latency_measurement_can_be_disabled(self, make_tick):
        pipeline = GridPipeline(measure_latency=False)
        report = pipeline.run([make_tick(timestamp=i) for i in range(5)])
        assert report.latencies_ms == []

    def test_pipeline_uses_the_injected_aggregator(self, make_tick):
        aggregator = QuoteAggregator()
        pipeline = GridPipeline(aggregator=aggregator)
        pipeline.process(make_tick())
        assert pipeline.aggregator is aggregator

    def test_default_sink_is_memory(self, make_tick):
        pipeline = GridPipeline()
        assert isinstance(pipeline.sink, MemorySink)


class TestBuildPipeline:
    def test_factory_assembles_the_pipeline(self):
        pipeline = build_pipeline(
            policy=ThresholdPolicy(window_size=7), pairs=[("AAPL", "MSFT")]
        )
        assert pipeline.aggregator.policy.window_size == 7
        assert pipeline.aggregator.pairs == (("AAPL", "MSFT"),)


class TestStatsHelper:
    def test_stats_as_dict(self, make_tick):
        aggregator = QuoteAggregator()
        aggregator.ingest(make_tick())
        assert stats_as_dict(aggregator.stats)["ticks_ingested"] == 1


class TestAggregationThroughput:
    @requires_speed
    def test_engine_processes_at_least_20000_ticks_per_second(self):
        """The aggregation engine must sustain a high tick rate."""
        generator = MockTickGenerator(seed=11)
        pipeline = GridPipeline(aggregator=QuoteAggregator(pairs=[("AAPL", "MSFT")]))
        report = pipeline.run(generator.stream(20_000))
        assert report.ticks == 20_000
        assert report.ticks_per_second >= 20_000.0, (
            f"throughput too low: {report.ticks_per_second:.0f} ticks/s"
        )

    @requires_speed
    def test_engine_sustains_a_realistic_tick_rate(self):
        """The engine must comfortably exceed a realistic exchange rate."""
        generator = MockTickGenerator(seed=12)
        pipeline = GridPipeline(
            aggregator=QuoteAggregator(pairs=[("AAPL", "MSFT")]), measure_latency=False
        )
        report = pipeline.run(generator.stream(50_000))
        assert report.ticks_per_second >= 50_000.0, (
            f"throughput too low: {report.ticks_per_second:.0f} ticks/s"
        )

    def test_rows_per_tick_ratio_is_sane(self):
        generator = MockTickGenerator(seed=13)
        pipeline = GridPipeline(aggregator=QuoteAggregator(pairs=[("AAPL", "MSFT")]))
        report = pipeline.run(generator.stream(2_000))
        # One symbol row per tick plus at most one pair row per tick.
        assert report.rows >= report.ticks
        assert report.rows <= 2 * report.ticks


class TestEndToEnd:
    def test_full_flow_produces_a_perspective_ready_grid(self):
        generator = MockTickGenerator(seed=17)
        sink = MemorySink()
        pipeline = GridPipeline(
            aggregator=QuoteAggregator(pairs=[("AAPL", "MSFT")]), sink=sink
        )
        report = pipeline.run(generator.stream(500))

        assert report.ticks == 500
        assert sink.rows
        first = sink.rows[0].to_dict()
        assert set(first) == set(PERSPECTIVE_SCHEMA)
        json.dumps(first)  # must be JSON serialisable

    def test_latency_budget_is_respected(self):
        generator = MockTickGenerator(seed=19)
        pipeline = GridPipeline()
        report = pipeline.run(generator.stream(1_000))
        assert report.mean_latency_ms < 50.0
        assert report.p95_latency_ms < 50.0

    def test_latency_budget_under_coverage(self):
        """Even instrumented, the per-tick cost must stay in the millisecond
        range -- the assertion is deliberately loose so that it also holds
        while a coverage tracer is attached."""
        generator = MockTickGenerator(seed=19)
        pipeline = GridPipeline()
        report = pipeline.run(generator.stream(200))
        assert report.mean_latency_ms < 20.0

    def test_pipeline_processes_a_live_feed(self):
        from jpm_perspective_grid.infrastructure.feed import (
            TickFeedClient,
            TickFeedServer,
        )

        server = TickFeedServer().start()
        client = TickFeedClient(host=server.host, port=server.port, timeout=5.0).connect()
        try:
            generator = MockTickGenerator(seed=23)
            for tick in generator.burst(20):
                server.broadcast(tick)
            received = client.read_ticks(20)
            assert len(received) == 20
            sink = MemorySink()
            pipeline = GridPipeline(sink=sink)
            pipeline.process_many(received)
            assert len(sink.rows) == 20
        finally:
            client.close()
            server.stop()

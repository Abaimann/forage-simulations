"""Tests covering the optional Perspective integration.

The whole module is skipped when ``perspective-python`` is not installed so
that the core test suite keeps running on a bare interpreter.
"""

from __future__ import annotations

import pytest

from jpm_perspective_grid.core.aggregator import QuoteAggregator
from jpm_perspective_grid.infrastructure.mock_feed import MockTickGenerator
from jpm_perspective_grid.infrastructure.sinks import (
    PERSPECTIVE_SCHEMA,
    MemorySink,
    PerspectiveTableSink,
    rows_to_records,
)

perspective = pytest.importorskip("perspective", reason="perspective-python not installed")


class TestPerspectiveSink:
    def test_table_is_created_with_the_expected_schema(self):
        sink = PerspectiveTableSink.create(name="quotes-test")
        try:
            schema = sink.table.schema()
            assert set(schema) == set(PERSPECTIVE_SCHEMA)
            assert schema["stock"] == "string"
            assert schema["trigger_alert"] == "boolean"
        finally:
            sink.close()

    def test_rows_are_persisted_in_the_table(self):
        sink = PerspectiveTableSink.create(name="quotes-test-rows")
        try:
            generator = MockTickGenerator(seed=3)
            pipeline_rows = QuoteAggregator().ingest_many(
                [tick.to_dict() for tick in generator.burst(10)]
            )
            written = sink.write(pipeline_rows)
            assert written == 10
            assert sink.written == 10
            columns = sink.snapshot()
            assert len(columns["stock"]) == 10
        finally:
            sink.close()

    def test_empty_batch_is_a_no_op(self):
        sink = PerspectiveTableSink.create(name="quotes-test-empty")
        try:
            assert sink.write([]) == 0
            assert sink.written == 0
        finally:
            sink.close()

    def test_records_can_be_written_directly(self):
        sink = PerspectiveTableSink.create(name="quotes-test-records")
        try:
            generator = MockTickGenerator(seed=5)
            rows = QuoteAggregator().ingest_many(
                [tick.to_dict() for tick in generator.burst(5)]
            )
            sink.table.update(rows_to_records(rows))
            columns = sink.snapshot()
            assert len(columns["ratio"]) == 5
        finally:
            sink.close()

    def test_alert_column_is_boolean_in_the_table(self):
        sink = PerspectiveTableSink.create(name="quotes-test-bool")
        try:
            generator = MockTickGenerator(seed=7)
            rows = QuoteAggregator().ingest_many(
                [tick.to_dict() for tick in generator.burst(25)]
            )
            sink.write(rows)
            columns = sink.snapshot()
            assert all(isinstance(value, bool) for value in columns["trigger_alert"])
        finally:
            sink.close()

    def test_memory_sink_remains_the_default(self):
        sink = MemorySink()
        assert sink.write([]) == 0

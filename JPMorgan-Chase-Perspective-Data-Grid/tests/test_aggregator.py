"""Unit tests for the aggregation engine."""

from __future__ import annotations

import pytest

from jpm_perspective_grid.core.aggregator import QuoteAggregator
from jpm_perspective_grid.core.errors import AggregationError
from jpm_perspective_grid.core.models import KIND_PAIR, KIND_SYMBOL, Tick


class TestSymbolRows:
    def test_single_tick_produces_one_row(self, make_tick):
        agg = QuoteAggregator()
        rows = agg.ingest(make_tick())
        assert len(rows) == 1
        row = rows[0]
        assert row.stock == "AAPL"
        assert row.kind == KIND_SYMBOL
        assert row.price == pytest.approx(99.5)
        assert row.ratio == pytest.approx(1.0)
        assert row.trigger_alert is False

    def test_ratio_is_price_over_rolling_baseline(self, make_tick):
        agg = QuoteAggregator()
        agg.ingest(make_tick(ask=100.0, bid=100.0))
        rows = agg.ingest(make_tick(ask=120.0, bid=120.0, timestamp=2))
        # baseline = mean(100, 120) = 110, price = 120 -> ratio 120/110
        assert rows[0].ratio == pytest.approx(120.0 / 110.0)

    def test_band_is_centred_on_the_baseline_ratio(self, make_tick):
        agg = QuoteAggregator()
        for index in range(5):
            agg.ingest(make_tick(ask=100.0, bid=100.0, timestamp=index))
        rows = agg.ingest(make_tick(ask=100.0, bid=100.0, timestamp=5))
        assert rows[0].lower_bound < rows[0].ratio < rows[0].upper_bound

    def test_steady_stream_does_not_trigger(self, make_tick):
        agg = QuoteAggregator()
        triggered = False
        for index in range(50):
            rows = agg.ingest(make_tick(ask=100.0, bid=100.0, timestamp=index))
            triggered = triggered or rows[0].trigger_alert
        assert triggered is False

    def test_price_spike_triggers_alert(self, make_tick):
        agg = QuoteAggregator()
        for index in range(20):
            agg.ingest(make_tick(ask=100.0, bid=100.0, timestamp=index))
        rows = agg.ingest(make_tick(ask=150.0, bid=150.0, timestamp=20))
        assert rows[0].trigger_alert is True

    def test_price_crash_triggers_alert(self, make_tick):
        agg = QuoteAggregator()
        for index in range(20):
            agg.ingest(make_tick(ask=100.0, bid=100.0, timestamp=index))
        rows = agg.ingest(make_tick(ask=50.0, bid=50.0, timestamp=20))
        assert rows[0].trigger_alert is True

    def test_alert_counters_are_tracked(self, make_tick):
        agg = QuoteAggregator()
        for index in range(20):
            agg.ingest(make_tick(ask=100.0, bid=100.0, timestamp=index))
        agg.ingest(make_tick(ask=200.0, bid=200.0, timestamp=20))
        assert agg.stats.alerts_emitted == 1
        assert agg.stats.rows_emitted == 21

    def test_symbols_are_isolated(self, make_tick):
        agg = QuoteAggregator()
        agg.ingest(make_tick(stock="AAPL", ask=100.0, bid=100.0))
        rows = agg.ingest(make_tick(stock="MSFT", ask=200.0, bid=200.0, timestamp=2))
        assert rows[0].stock == "MSFT"
        assert rows[0].ratio == pytest.approx(1.0)

    def test_latest_quote_is_exposed(self, make_tick):
        agg = QuoteAggregator()
        agg.ingest(make_tick(ask=101.0, bid=99.0))
        quote = agg.latest_quote("aapl")
        assert quote is not None
        assert quote.mid_price == pytest.approx(100.0)

    def test_latest_quote_of_unknown_symbol_is_none(self):
        assert QuoteAggregator().latest_quote("NVDA") is None


class TestPairRows:
    def test_pair_row_requires_both_legs(self, make_tick):
        agg = QuoteAggregator(pairs=[("AAPL", "MSFT")])
        rows = agg.ingest(make_tick(stock="AAPL"))
        assert len(rows) == 1
        assert rows[0].kind == KIND_SYMBOL

    def test_pair_row_is_emitted_once_both_legs_known(self, make_tick):
        agg = QuoteAggregator(pairs=[("AAPL", "MSFT")])
        agg.ingest(make_tick(stock="AAPL", ask=100.0, bid=100.0))
        rows = agg.ingest(make_tick(stock="MSFT", ask=200.0, bid=200.0, timestamp=2))
        assert len(rows) == 2
        pair_row = rows[1]
        assert pair_row.kind == KIND_PAIR
        assert pair_row.stock == "AAPL/MSFT"
        assert pair_row.ratio == pytest.approx(100.0 / 200.0)
        assert pair_row.price == pytest.approx(100.0)

    def test_pair_ratio_tracks_the_discrepancy(self, make_tick):
        agg = QuoteAggregator(pairs=[("AAPL", "MSFT")])
        agg.ingest(make_tick(stock="AAPL", ask=100.0, bid=100.0))
        rows = agg.ingest(make_tick(stock="MSFT", ask=200.0, bid=200.0, timestamp=2))
        assert rows[1].ratio == pytest.approx(0.5)

    def test_pair_alert_on_discrepancy(self, make_tick):
        agg = QuoteAggregator(pairs=[("AAPL", "MSFT")])
        for index in range(20):
            agg.ingest(make_tick(stock="AAPL", ask=100.0, bid=100.0, timestamp=index))
            agg.ingest(make_tick(stock="MSFT", ask=200.0, bid=200.0, timestamp=index))
        rows = agg.ingest(make_tick(stock="MSFT", ask=100.0, bid=100.0, timestamp=99))
        pair_row = next(row for row in rows if row.kind == KIND_PAIR)
        assert pair_row.trigger_alert is True

    def test_unrelated_symbol_does_not_create_pair_rows(self, make_tick):
        agg = QuoteAggregator(pairs=[("AAPL", "MSFT")])
        agg.ingest(make_tick(stock="AAPL"))
        rows = agg.ingest(make_tick(stock="TSLA", timestamp=2))
        assert len(rows) == 1
        assert rows[0].kind == KIND_SYMBOL

    def test_multiple_pairs_are_supported(self, make_tick):
        agg = QuoteAggregator(pairs=[("AAPL", "MSFT"), ("JPM", "GS")])
        agg.ingest(make_tick(stock="AAPL"))
        agg.ingest(make_tick(stock="JPM", timestamp=2))
        rows = agg.ingest(make_tick(stock="GS", timestamp=3))
        assert any(row.kind == KIND_PAIR for row in rows)

    def test_pair_counters(self, make_tick):
        agg = QuoteAggregator(pairs=[("AAPL", "MSFT")])
        agg.ingest(make_tick(stock="AAPL"))
        agg.ingest(make_tick(stock="MSFT", timestamp=2))
        assert agg.stats.pair_rows_emitted == 1

    def test_pair_timestamp_is_the_most_recent_leg(self, make_tick):
        agg = QuoteAggregator(pairs=[("AAPL", "MSFT")])
        agg.ingest(make_tick(stock="AAPL", timestamp=10))
        rows = agg.ingest(make_tick(stock="MSFT", timestamp=20))
        pair_row = next(row for row in rows if row.kind == KIND_PAIR)
        assert pair_row.timestamp == 20


class TestIngestionRobustness:
    def test_ingest_requires_a_tick(self):
        with pytest.raises(AggregationError):
            QuoteAggregator().ingest({"stock": "AAPL"})  # type: ignore[arg-type]

    def test_ingest_raw_counts_invalid_payloads(self, raw_tick_payload):
        agg = QuoteAggregator()
        payload = raw_tick_payload()
        payload["top_bid_price"] = 1_000.0  # crossed market
        assert agg.ingest_raw(payload) == []
        assert agg.stats.ticks_rejected == 1
        assert agg.stats.ticks_ingested == 0

    def test_ingest_raw_accepts_a_tick_instance(self, make_tick):
        agg = QuoteAggregator()
        assert len(agg.ingest_raw(make_tick())) == 1
        assert agg.stats.ticks_ingested == 1

    def test_ingest_raw_rejects_missing_fields(self):
        agg = QuoteAggregator()
        assert agg.ingest_raw({"stock": "AAPL"}) == []
        assert agg.stats.ticks_rejected == 1

    def test_ingest_many(self, raw_tick_payload):
        agg = QuoteAggregator()
        rows = agg.ingest_many([raw_tick_payload(timestamp=i) for i in range(5)])
        assert len(rows) == 5

    def test_iter_rows_is_lazy(self, raw_tick_payload):
        agg = QuoteAggregator()
        payloads = [raw_tick_payload(timestamp=i) for i in range(3)]
        iterator = agg.iter_rows(payloads)
        assert next(iterator).stock == "AAPL"

    def test_out_of_order_ticks_are_counted(self, make_tick):
        agg = QuoteAggregator()
        agg.ingest(make_tick(timestamp=100))
        agg.ingest(make_tick(timestamp=50))
        assert agg.stats.out_of_order_ticks == 1

    def test_out_of_order_tick_is_still_aggregated(self, make_tick):
        agg = QuoteAggregator()
        agg.ingest(make_tick(timestamp=100))
        rows = agg.ingest(make_tick(timestamp=50))
        assert len(rows) == 1

    def test_reset_clears_state(self, make_tick):
        agg = QuoteAggregator(pairs=[("AAPL", "MSFT")])
        agg.ingest(make_tick())
        agg.reset()
        assert agg.stats.ticks_ingested == 0
        assert agg.latest_quote("AAPL") is None
        assert agg.quotes == {}

    def test_stats_as_dict(self, make_tick):
        agg = QuoteAggregator()
        agg.ingest(make_tick())
        stats = agg.stats.as_dict()
        assert stats["ticks_ingested"] == 1
        assert set(stats) == {
            "ticks_ingested",
            "ticks_rejected",
            "rows_emitted",
            "alerts_emitted",
            "out_of_order_ticks",
            "pair_rows_emitted",
        }


class TestAggregationInvariants:
    def test_price_equals_the_mid_of_the_tick(self, make_tick):
        agg = QuoteAggregator()
        rows = agg.ingest(make_tick(ask=101.0, bid=99.0))
        assert rows[0].price == pytest.approx(100.0)

    def test_bounds_are_ordered(self, make_tick):
        agg = QuoteAggregator()
        for index in range(10):
            rows = agg.ingest(make_tick(ask=100.0 + index, bid=100.0 + index, timestamp=index))
        assert rows[0].lower_bound <= rows[0].upper_bound

    def test_ratio_is_always_positive(self, make_tick):
        agg = QuoteAggregator()
        for index in range(10):
            rows = agg.ingest(make_tick(ask=100.0 + index * 3, bid=100.0 + index * 3, timestamp=index))
            assert rows[0].ratio > 0

    def test_tick_object_is_immutable(self, make_tick):
        tick = make_tick()
        with pytest.raises(Exception):
            tick.stock = "TSLA"  # type: ignore[misc]

    def test_aggregator_accepts_a_raw_tick_with_extra_fields(self):
        agg = QuoteAggregator()
        rows = agg.ingest_raw(
            {
                "stock": "AAPL",
                "top_ask_price": 100.0,
                "top_bid_price": 99.0,
                "timestamp": 1,
                "volume": 1234,
            }
        )
        assert len(rows) == 1

    def test_aggregator_rejects_non_mapping_payload(self):
        agg = QuoteAggregator()
        assert agg.ingest_raw([1, 2, 3]) == []  # type: ignore[arg-type]
        assert agg.stats.ticks_rejected == 1

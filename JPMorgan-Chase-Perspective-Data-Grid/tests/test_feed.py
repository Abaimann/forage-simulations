"""Unit tests for the mock feed generator and the TCP transport."""

from __future__ import annotations

import socket
import threading
import time

import pytest

from jpm_perspective_grid.core.errors import (
    FeedConnectionError,
    FeedProtocolError,
    TickValidationError,
)
from jpm_perspective_grid.core.models import Tick
from jpm_perspective_grid.infrastructure.feed import (
    MAX_FRAME_BYTES,
    TickFeedClient,
    TickFeedServer,
)
from jpm_perspective_grid.infrastructure.mock_feed import (
    InstrumentSpec,
    MockTickGenerator,
    default_universe,
)

from conftest import _coverage_is_active


class TestMockTickGenerator:
    def test_default_universe_is_not_empty(self):
        assert len(default_universe()) >= 2

    def test_generated_ticks_are_valid(self):
        generator = MockTickGenerator(seed=1)
        for tick in generator.stream(50):
            assert isinstance(tick, Tick)
            assert tick.top_bid_price <= tick.top_ask_price
            assert tick.top_ask_price > 0

    def test_generation_is_deterministic_for_a_fixed_seed(self):
        first = [t.to_json() for t in MockTickGenerator(seed=42).stream(30)]
        second = [t.to_json() for t in MockTickGenerator(seed=42).stream(30)]
        assert first == second

    def test_different_seeds_produce_different_streams(self):
        first = [t.to_json() for t in MockTickGenerator(seed=1).stream(30)]
        second = [t.to_json() for t in MockTickGenerator(seed=2).stream(30)]
        assert first != second

    def test_timestamps_are_monotonic(self):
        ticks = MockTickGenerator(seed=3).burst(20)
        assert all(b.timestamp > a.timestamp for a, b in zip(ticks, ticks[1:]))

    def test_timestamps_advance_by_the_configured_interval(self):
        generator = MockTickGenerator(seed=3, tick_interval_ms=250)
        ticks = generator.burst(5)
        assert ticks[1].timestamp - ticks[0].timestamp == 250

    def test_burst_returns_the_requested_number_of_ticks(self):
        assert len(MockTickGenerator(seed=3).burst(17)) == 17

    def test_burst_rejects_negative_count(self):
        with pytest.raises(TickValidationError):
            MockTickGenerator(seed=3).burst(-1)

    def test_empty_universe_is_rejected(self):
        with pytest.raises(TickValidationError):
            MockTickGenerator(universe=[])

    def test_instrument_spec_rejects_non_positive_reference_price(self):
        with pytest.raises(TickValidationError):
            InstrumentSpec(symbol="AAPL", reference_price=0.0)

    def test_instrument_spec_rejects_non_positive_tick_size(self):
        with pytest.raises(TickValidationError):
            InstrumentSpec(symbol="AAPL", reference_price=10.0, tick_size=0.0)

    def test_custom_universe_is_respected(self):
        generator = MockTickGenerator(
            universe=[InstrumentSpec(symbol="ONLY", reference_price=50.0)], seed=5
        )
        assert {t.stock for t in generator.burst(20)} == {"ONLY"}

    def test_prices_stay_near_the_reference(self):
        generator = MockTickGenerator(
            universe=[
                InstrumentSpec(
                    symbol="AAPL", reference_price=100.0, volatility_bps=5.0
                )
            ],
            seed=9,
        )
        for tick in generator.burst(100):
            assert 90.0 < tick.mid_price < 110.0


class TestFeedServerLifecycle:
    def test_port_is_zero_before_start(self):
        assert TickFeedServer().port == 0

    def test_start_binds_an_ephemeral_port(self):
        server = TickFeedServer().start()
        try:
            assert server.port > 0
        finally:
            server.stop()

    def test_starting_twice_is_rejected(self):
        server = TickFeedServer().start()
        try:
            with pytest.raises(FeedConnectionError):
                server.start()
        finally:
            server.stop()

    def test_stop_is_idempotent(self):
        server = TickFeedServer().start()
        server.stop()
        server.stop()

    def test_context_manager(self):
        with TickFeedServer() as server:
            assert server.port > 0

    def test_broadcast_without_clients_is_a_no_op(self):
        server = TickFeedServer().start()
        try:
            assert server.broadcast(Tick("AAPL", 100.0, 99.0, 1)) == 0
        finally:
            server.stop()


class TestFeedHandshake:
    def test_client_is_registered_after_connect(self):
        server = TickFeedServer().start()
        client = TickFeedClient(host=server.host, port=server.port).connect()
        try:
            assert server.client_count == 1
        finally:
            client.close()
            server.stop()

    def test_client_without_handshake_is_not_registered(self):
        server = TickFeedServer().start()
        client = TickFeedClient(host=server.host, port=server.port, handshake=False)
        client.connect()
        try:
            time.sleep(0.2)
            assert server.client_count == 0
        finally:
            client.close()
            server.stop()

    def test_ack_is_consumed_by_the_handshake(self):
        server = TickFeedServer().start()
        client = TickFeedClient(host=server.host, port=server.port).connect()
        try:
            server.broadcast(Tick("AAPL", 100.0, 99.0, 1))
            # The ack must not be mistaken for a tick.
            assert client.read_tick() == Tick("AAPL", 100.0, 99.0, 1)
        finally:
            client.close()
            server.stop()

    def test_handshake_against_a_non_feed_server_fails(self):
        import socket as _socket

        listener = _socket.socket(_socket.AF_INET, _socket.SOCK_STREAM)
        listener.bind(("127.0.0.1", 0))
        listener.listen(1)
        port = listener.getsockname()[1]

        def _accept_and_close() -> None:
            try:
                conn, _ = listener.accept()
                conn.close()
            except OSError:
                pass

        threading.Thread(target=_accept_and_close, daemon=True).start()
        try:
            with pytest.raises(FeedConnectionError):
                TickFeedClient(host="127.0.0.1", port=port, timeout=2.0).connect()
        finally:
            listener.close()

    def test_wait_for_clients_times_out_when_nobody_connects(self):
        server = TickFeedServer().start()
        try:
            assert server.wait_for_clients(1, timeout=0.2) is False
        finally:
            server.stop()

    def test_wait_for_clients_returns_true_once_connected(self):
        server = TickFeedServer().start()
        client = TickFeedClient(host=server.host, port=server.port).connect()
        try:
            assert server.wait_for_clients(1, timeout=2.0) is True
        finally:
            client.close()
            server.stop()


class TestFeedServerClientRoundTrip:
    def test_client_receives_broadcast_ticks(self):
        server = TickFeedServer().start()
        client = TickFeedClient(host=server.host, port=server.port).connect()
        try:
            tick = Tick("AAPL", 100.0, 99.0, 42)
            assert server.broadcast(tick) == 1
            received = client.read_tick()
            assert received == tick
        finally:
            client.close()
            server.stop()

    def test_multiple_clients_receive_the_same_tick(self):
        server = TickFeedServer().start()
        client_a = TickFeedClient(host=server.host, port=server.port).connect()
        client_b = TickFeedClient(host=server.host, port=server.port).connect()
        try:
            deadline = time.monotonic() + 2.0
            while server.client_count < 2 and time.monotonic() < deadline:
                time.sleep(0.01)
            tick = Tick("MSFT", 200.0, 199.0, 7)
            server.broadcast(tick)
            assert client_a.read_tick() == tick
            assert client_b.read_tick() == tick
        finally:
            client_a.close()
            client_b.close()
            server.stop()

    def test_broadcast_many(self):
        server = TickFeedServer().start()
        client = TickFeedClient(host=server.host, port=server.port).connect()
        try:
            ticks = [Tick("AAPL", 100.0 + i, 99.0 + i, i) for i in range(5)]
            server.broadcast_many(ticks)
            assert client.read_ticks(5) == ticks
        finally:
            client.close()
            server.stop()

    def test_read_ticks_returns_empty_list_when_server_stops(self):
        server = TickFeedServer().start()
        client = TickFeedClient(host=server.host, port=server.port).connect()
        server.stop()
        assert client.read_ticks(3) == []
        client.close()

    def test_client_reads_a_dict_payload(self):
        server = TickFeedServer().start()
        client = TickFeedClient(host=server.host, port=server.port).connect()
        try:
            server.broadcast(
                {
                    "stock": "AAPL",
                    "top_ask_price": 100.0,
                    "top_bid_price": 99.0,
                    "timestamp": 5,
                }
            )
            tick = client.read_tick()
            assert tick.stock == "AAPL"
        finally:
            client.close()
            server.stop()


class TestFeedClientErrors:
    def test_connect_to_a_closed_port_fails(self):
        # Bind and immediately release a port so that nothing listens on it.
        probe = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        probe.bind(("127.0.0.1", 0))
        port = probe.getsockname()[1]
        probe.close()
        with pytest.raises(FeedConnectionError):
            TickFeedClient(host="127.0.0.1", port=port, timeout=1.0).connect()

    def test_connecting_twice_is_rejected(self):
        server = TickFeedServer().start()
        client = TickFeedClient(host=server.host, port=server.port).connect()
        try:
            with pytest.raises(FeedConnectionError):
                client.connect()
        finally:
            client.close()
            server.stop()

    def test_reading_without_connecting_fails(self):
        with pytest.raises(FeedConnectionError):
            TickFeedClient(host="127.0.0.1", port=1).read_tick()

    def test_malformed_frame_raises_without_handler(self):
        server = TickFeedServer().start()
        client = TickFeedClient(host=server.host, port=server.port).connect()
        try:
            server.broadcast_raw(b"not-json\n")
            with pytest.raises(FeedProtocolError):
                client.read_tick()
        finally:
            client.close()
            server.stop()

    def test_malformed_frame_is_skipped_with_handler(self):
        received: list[str] = []
        server = TickFeedServer().start()
        client = TickFeedClient(
            host=server.host, port=server.port, on_malformed=received.append
        ).connect()
        try:
            server.broadcast_raw(b"not-json\n")
            server.broadcast(Tick("AAPL", 100.0, 99.0, 1))
            tick = client.read_tick()
            assert tick.stock == "AAPL"
            assert received == ["not-json"]
        finally:
            client.close()
            server.stop()

    def test_oversized_frame_is_rejected(self):
        server = TickFeedServer().start()
        client = TickFeedClient(host=server.host, port=server.port, timeout=5.0).connect()
        try:
            server.broadcast_raw(b"x" * (MAX_FRAME_BYTES + 1024))
            with pytest.raises(FeedProtocolError):
                client.read_tick()
        finally:
            client.close()
            server.stop()

    def test_read_ticks_rejects_negative_count(self):
        client = TickFeedClient(host="127.0.0.1", port=1)
        with pytest.raises(ValueError):
            client.read_ticks(-1)

    def test_server_drops_broken_clients(self):
        server = TickFeedServer().start()
        client = TickFeedClient(host=server.host, port=server.port).connect()
        try:
            raw = socket.create_connection((server.host, server.port), timeout=2.0)
            raw.close()
            time.sleep(0.05)
            # Broadcasting to a dead peer must not raise.
            server.broadcast(Tick("AAPL", 100.0, 99.0, 1))
            client.close()
        finally:
            server.stop()


class TestStreamingThroughput:
    @pytest.mark.skipif(
        _coverage_is_active(),
        reason="throughput budget is not meaningful under coverage tracing",
    )
    def test_feed_sustains_a_high_tick_rate(self):
        """The transport must deliver at least 500 ticks/s end to end."""
        server = TickFeedServer().start()
        client = TickFeedClient(host=server.host, port=server.port, timeout=10.0).connect()
        total = 2_000

        def publisher() -> None:
            for index in range(total):
                server.broadcast(Tick("AAPL", 100.0 + index * 0.01, 99.0 + index * 0.01, index))

        thread = threading.Thread(target=publisher, daemon=True)
        start = time.perf_counter()
        thread.start()
        received = client.read_ticks(total)
        elapsed = time.perf_counter() - start
        thread.join(timeout=5.0)
        client.close()
        server.stop()

        assert len(received) == total
        assert elapsed > 0
        assert total / elapsed >= 500.0, f"throughput too low: {total / elapsed:.0f} ticks/s"

    def test_frames_are_delivered_in_order(self):
        server = TickFeedServer().start()
        client = TickFeedClient(host=server.host, port=server.port, timeout=10.0).connect()
        try:
            ticks = [Tick("AAPL", 100.0 + i, 99.0 + i, i) for i in range(200)]
            server.broadcast_many(ticks)
            received = client.read_ticks(len(ticks))
            assert [t.timestamp for t in received] == [t.timestamp for t in ticks]
        finally:
            client.close()
            server.stop()

    def test_a_slow_client_does_not_block_the_publisher(self):
        """Publishing must not stall because a consumer is not reading."""
        server = TickFeedServer().start()
        client = TickFeedClient(host=server.host, port=server.port, timeout=10.0).connect()
        try:
            start = time.perf_counter()
            for index in range(500):
                server.broadcast(Tick("AAPL", 100.0, 99.0, index))
            elapsed = time.perf_counter() - start
            assert elapsed < 2.0, f"publisher blocked for {elapsed:.2f}s"
        finally:
            client.close()
            server.stop()

    def test_slow_client_is_disconnected_when_its_queue_overflows(self):
        server = TickFeedServer(queue_size=16).start()
        client = TickFeedClient(host=server.host, port=server.port, timeout=10.0).connect()
        try:
            for index in range(5_000):
                server.broadcast(Tick("AAPL", 100.0, 99.0, index))
            time.sleep(0.3)
            assert server.client_count == 0
        finally:
            client.close()
            server.stop()

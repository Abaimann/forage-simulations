"""Command line entry point of the trading grid toolkit.

Examples
--------
Run a self-contained demo (mock feed -> aggregation -> in-memory grid)::

    python -m jpm_perspective_grid demo --ticks 500

Run the tick feed server on port 5555::

    python -m jpm_perspective_grid serve --port 5555

Connect a client to a running feed and print the grid rows::

    python -m jpm_perspective_grid client --host 127.0.0.1 --port 5555 --ticks 100
"""

from __future__ import annotations

import argparse
import json
import sys
from typing import Sequence

from .application.pipeline import GridPipeline, ThroughputReport
from .core.aggregator import QuoteAggregator
from .core.errors import FeedError
from .core.models import GridRow
from .core.thresholds import ThresholdPolicy
from .infrastructure.feed import TickFeedClient, TickFeedServer
from .infrastructure.mock_feed import MockTickGenerator
from .infrastructure.sinks import MemorySink, PerspectiveTableSink, RowSink

DEFAULT_PAIRS: tuple[tuple[str, str], ...] = (
    ("AAPL", "MSFT"),
    ("JPM", "GS"),
    ("XOM", "CVX"),
)


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="jpm_perspective_grid",
        description="Real-time Perspective data grid and stream processor.",
    )
    sub = parser.add_subparsers(dest="command", required=True)

    demo = sub.add_parser("demo", help="run the full pipeline on a mock feed")
    demo.add_argument("--ticks", type=int, default=500, help="number of ticks to process")
    demo.add_argument("--seed", type=int, default=1337, help="random seed")
    demo.add_argument("--window", type=int, default=20, help="rolling window size")
    demo.add_argument("--sigma", type=float, default=3.0, help="sigma multiplier")
    demo.add_argument(
        "--min-half-width", type=float, default=0.005, help="minimum band half width"
    )
    demo.add_argument("--json", action="store_true", help="print JSON output only")

    serve = sub.add_parser("serve", help="run the tick feed server")
    serve.add_argument("--host", default="127.0.0.1")
    serve.add_argument("--port", type=int, default=5555)
    serve.add_argument("--seed", type=int, default=1337)
    serve.add_argument("--rate", type=float, default=50.0, help="ticks per second")
    serve.add_argument("--duration", type=float, default=0.0, help="0 = run forever")

    client = sub.add_parser("client", help="consume a running tick feed server")
    client.add_argument("--host", default="127.0.0.1")
    client.add_argument("--port", type=int, default=5555)
    client.add_argument("--ticks", type=int, default=100)
    client.add_argument("--window", type=int, default=20)
    client.add_argument("--sigma", type=float, default=3.0)
    client.add_argument("--json", action="store_true", help="print JSON rows only")
    client.add_argument(
        "--perspective", action="store_true", help="write into a live Perspective table"
    )
    client.add_argument("--table", default="quotes", help="name of the Perspective table")

    live = sub.add_parser("live", help="run server, client and grid in one process")
    live.add_argument("--host", default="127.0.0.1")
    live.add_argument("--port", type=int, default=0)
    live.add_argument("--seed", type=int, default=1337)
    live.add_argument("--rate", type=float, default=50.0, help="ticks per second")
    live.add_argument("--duration", type=float, default=10.0, help="seconds to run")
    live.add_argument("--json", action="store_true", help="print JSON rows only")
    live.add_argument(
        "--perspective", action="store_true", help="write into a live Perspective table"
    )
    live.add_argument("--table", default="quotes", help="name of the Perspective table")

    bench = sub.add_parser("bench", help="measure the aggregation throughput")
    bench.add_argument("--ticks", type=int, default=20_000)
    bench.add_argument("--seed", type=int, default=7)

    dash = sub.add_parser("dashboard", help="serve the browser dashboard")
    dash.add_argument("--host", default="127.0.0.1")
    dash.add_argument("--port", type=int, default=8888)

    return parser


def _print_alert(row: GridRow) -> None:
    """Print a single alerting row (used as the pipeline alert callback)."""
    print(
        f"ALERT {row.stock} ratio={row.ratio:.6f} "
        f"band=[{row.lower_bound:.6f}, {row.upper_bound:.6f}] price={row.price:.4f}"
    )


def _cmd_demo(args: argparse.Namespace) -> int:
    policy = ThresholdPolicy(
        window_size=args.window,
        sigma_multiplier=args.sigma,
        min_half_width=args.min_half_width,
    )
    generator = MockTickGenerator(seed=args.seed)
    sink = MemorySink()
    pipeline = GridPipeline(
        aggregator=QuoteAggregator(policy=policy, pairs=DEFAULT_PAIRS),
        sink=sink,
        # In JSON mode the alert callback must stay silent, otherwise the
        # document would not be machine parsable.
        on_alert=None if args.json else _print_alert,
    )
    report = pipeline.run(generator.stream(args.ticks))

    if args.json:
        print(
            json.dumps(
                {
                    "throughput": report.as_dict(),
                    "stats": pipeline.aggregator.stats.as_dict(),
                },
                indent=2,
            )
        )
        return 0

    print(f"processed {report.ticks} ticks -> {report.rows} rows")
    print(
        f"throughput: {report.ticks_per_second:,.0f} ticks/s, "
        f"{report.rows_per_second:,.0f} rows/s"
    )
    print(
        f"latency: mean {report.mean_latency_ms:.3f} ms, "
        f"p95 {report.p95_latency_ms:.3f} ms"
    )
    print("stats:", pipeline.aggregator.stats.as_dict())
    alerts = sink.alerts()
    print(f"alerts: {len(alerts)}")
    for row in alerts[:10]:
        print(
            f"  {row.stock:<12} kind={row.kind:<6} ratio={row.ratio:.6f} "
            f"band=[{row.lower_bound:.6f}, {row.upper_bound:.6f}]"
        )
    return 0


def _cmd_serve(args: argparse.Namespace) -> int:
    import time

    generator = MockTickGenerator(seed=args.seed)
    server = TickFeedServer(host=args.host, port=args.port).start()
    print(f"tick feed server listening on {server.host}:{server.port}")
    interval = 1.0 / args.rate if args.rate > 0 else 0.0
    deadline = time.monotonic() + args.duration if args.duration > 0 else None
    try:
        while deadline is None or time.monotonic() < deadline:
            tick = generator.next_tick()
            server.broadcast(tick)
            if interval:
                time.sleep(interval)
    except KeyboardInterrupt:  # pragma: no cover - interactive
        pass
    finally:
        server.stop()
        print("tick feed server stopped")
    return 0


def _cmd_client(args: argparse.Namespace) -> int:
    policy = ThresholdPolicy(window_size=args.window, sigma_multiplier=args.sigma)
    sink: RowSink = MemorySink()
    if args.perspective:
        sink = PerspectiveTableSink.create(name=args.table)
    pipeline = GridPipeline(
        aggregator=QuoteAggregator(policy=policy, pairs=DEFAULT_PAIRS),
        sink=sink,
    )
    try:
        client = TickFeedClient(host=args.host, port=args.port).connect()
    except FeedError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2
    try:
        for tick in client.ticks():
            produced = pipeline.process(tick)
            if args.json:
                for row in produced:
                    print(row.to_json())
            elif produced and produced[-1].trigger_alert:
                _print_alert(produced[-1])
            if pipeline.aggregator.stats.ticks_ingested >= args.ticks:
                break
    finally:
        client.close()

    print(f"consumed {pipeline.aggregator.stats.ticks_ingested} ticks")
    print("stats:", pipeline.aggregator.stats.as_dict())
    if args.perspective:
        columns = sink.snapshot()  # type: ignore[union-attr]
        print(f"perspective table '{args.table}' holds {len(columns['stock'])} rows")
    return 0


def _cmd_live(args: argparse.Namespace) -> int:
    """Run server, client and grid in a single process."""
    import threading
    import time

    generator = MockTickGenerator(seed=args.seed)
    server = TickFeedServer(host=args.host, port=args.port).start()
    sink: RowSink = MemorySink()
    if args.perspective:
        sink = PerspectiveTableSink.create(name=args.table)
    pipeline = GridPipeline(
        aggregator=QuoteAggregator(pairs=DEFAULT_PAIRS),
        sink=sink,
        on_alert=None if args.json else _print_alert,
    )
    client = TickFeedClient(host=server.host, port=server.port, timeout=5.0).connect()
    interval = 1.0 / args.rate if args.rate > 0 else 0.0
    deadline = time.monotonic() + args.duration if args.duration > 0 else None
    print(f"live grid running on {server.host}:{server.port}")
    try:
        while deadline is None or time.monotonic() < deadline:
            server.broadcast(generator.next_tick())
            time.sleep(interval)
            tick = client.read_tick()
            produced = pipeline.process(tick)
            if args.json:
                for row in produced:
                    print(row.to_json())
    except KeyboardInterrupt:  # pragma: no cover - interactive
        pass
    finally:
        client.close()
        server.stop()

    print("stats:", pipeline.aggregator.stats.as_dict())
    if args.perspective:
        columns = sink.snapshot()  # type: ignore[union-attr]
        print(f"perspective table '{args.table}' holds {len(columns['stock'])} rows")
    return 0


def _cmd_bench(args: argparse.Namespace) -> int:
    generator = MockTickGenerator(seed=args.seed)
    pipeline = GridPipeline(aggregator=QuoteAggregator(pairs=DEFAULT_PAIRS))
    report = pipeline.run(generator.stream(args.ticks))
    print(json.dumps(report.as_dict(), indent=2))
    return 0


def _cmd_dashboard(args: argparse.Namespace) -> int:
    from .infrastructure.dashboard import serve_dashboard

    try:
        serve_dashboard(host=args.host, port=args.port)
    except KeyboardInterrupt:  # pragma: no cover - interactive
        print("dashboard stopped")
    return 0


def main(argv: Sequence[str] | None = None) -> int:
    """Entry point of the ``jpm-perspective-grid`` console script."""
    parser = _build_parser()
    args = parser.parse_args(argv)
    handlers = {
        "demo": _cmd_demo,
        "serve": _cmd_serve,
        "client": _cmd_client,
        "live": _cmd_live,
        "bench": _cmd_bench,
        "dashboard": _cmd_dashboard,
    }
    return handlers[args.command](args)


if __name__ == "__main__":  # pragma: no cover
    sys.exit(main())

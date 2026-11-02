# J.P. Morgan Chase & Co. — Live Perspective Data Grid & Stream Processor

**Forage — Software Engineering Lite, Task 2**

A production-grade, real-time trading grid: a mock market-data **feed server**, a
**feed client**, a pure-Python **aggregation engine** that turns raw top-of-book ticks into
Perspective-ready rows with computed alert fields, and a **browser dashboard** that renders
the grid over WebSocket.

```
 raw ticks ──▶ feed server ──TCP/NDJSON──▶ feed client ──▶ aggregation engine ──▶ sink ──▶ Perspective grid
 (mock feed)     (broadcast)   (handshake)     (client)      (price, ratio,          (table /
                                                            upper/lower bound,        browser
                                                            trigger_alert)            dashboard)
```

---

## Table of contents

1. [Business context](#1-business-context)
2. [Architecture](#2-architecture)
3. [Domain model and computed fields](#3-domain-model-and-computed-fields)
4. [The alert algorithm](#4-the-alert-algorithm)
5. [Wire protocol](#5-wire-protocol)
6. [Installation](#6-installation)
7. [Execution instructions](#7-execution-instructions)
8. [Testing](#8-testing)
9. [Performance and latency](#9-performance-and-latency)
10. [Public API reference](#10-public-api-reference)
11. [Parameters and configuration](#11-parameters-and-configuration)
12. [Design decisions and trade-offs](#12-design-decisions-and-trade-offs)
13. [Extension points](#13-extension-points)
14. [Project layout](#14-project-layout)

---

## 1. Business context

Traders on the desk need to monitor **price discrepancies between correlated stock symbols in
real time**. Two instruments that normally move together (e.g. `AAPL` vs `MSFT`, or `JPM` vs
`GS`) can start to diverge; the earlier the desk sees it, the more valuable the signal.

This project delivers the data path that makes such a view possible:

* a **feed server** that continuously publishes mock top-of-book quotes,
* a **feed client** that consumes them over the network,
* an **aggregation engine** that maintains, per instrument and per correlated pair, a rolling
  ratio together with the statistical band around it,
* a **sink** that writes the result into a live [Perspective](https://perspective-dev.github.io/)
  table so it can be pivoted, filtered and charted in a browser.

Everything except the Perspective binding is implemented with the **Python standard library
only**, which keeps the deployment footprint small and the core logic trivially testable.

---

## 2. Architecture

The package follows a **ports-and-adapters (hexagonal) / clean architecture** split. Dependencies
point inwards, from the outside world towards the domain.

```
src/jpm_perspective_grid/
├── core/                     ← DOMAIN (pure, no I/O, no third-party imports)
│   ├── errors.py             ←   typed error hierarchy
│   ├── models.py             ←   Tick, Quote, Band, GridRow + validation
│   ├── thresholds.py         ←   rolling mean / stdev, alert band tracker
│   └── aggregator.py         ←   the state machine: ticks → grid rows
│
├── infrastructure/            ← ADAPTERS (I/O; replaceable)
│   ├── mock_feed.py          ←   synthetic market data generator
│   ├── feed.py               ←   TCP feed server + client (NDJSON)
│   ├── sinks.py              ←   Perspective table sink, in-memory sink
│   └── dashboard.py          ←   Tornado WebSocket dashboard
│
├── application/              ← SERVICES (use cases)
│   └── pipeline.py           ←   GridPipeline, ThroughputReport
│
├── cli.py                    ←   command line entry point
└── __init__.py               ←   curated public API
```

### Layer responsibilities

| Layer | May import | May **not** import | Responsibility |
|---|---|---|---|
| `core` | stdlib only | everything else | Business rules, validation, statistics |
| `infrastructure` | `core` | `application` | Talking to sockets, files, Perspective |
| `application` | `core`, `infrastructure` (via ports) | — | Orchestration, use cases |
| `cli` | all | — | Argument parsing, presentation |

### SOLID applied

* **S**ingle responsibility — `core/thresholds.py` computes statistics, `core/aggregator.py`
  applies them, `infrastructure/feed.py` moves bytes. Each file has one reason to change.
* **O**pen/closed — new sinks (Kafka, Redis, CSV) implement the two-method `RowSink` protocol;
  new transports implement the server/client pair. Neither requires touching the domain.
* **L**iskov substitution — `MemorySink` and `PerspectiveTableSink` are interchangeable
  behind `RowSink`; the pipeline never branches on the concrete type.
* **I**nterface segregation — `RowSink` exposes only `write()` and `close()`; the aggregation
  engine has no knowledge of Perspective, sockets or the CLI.
* **D**ependency inversion — the domain declares what it needs (`Tick`, `GridRow`), the
  infrastructure supplies it. The core never imports an adapter.

### Data flow

1. `MockTickGenerator` produces a `Tick` (symbol, best ask, best bid, timestamp).
2. `TickFeedServer.broadcast()` serialises it as one NDJSON frame and queues it per client.
3. `TickFeedClient.read_tick()` reassembles the frame and validates it into a `Tick`.
4. `QuoteAggregator.ingest()` updates the per-instrument state and returns `GridRow`s.
5. `GridPipeline` writes the rows to the sink and invokes the alert callback.
6. `PerspectiveTableSink` pushes the rows into the Perspective table; the browser dashboard
   receives them over WebSocket.

---

## 3. Domain model and computed fields

### Input — the tick

| Field | Type | Rule |
|---|---|---|
| `stock` | `str` | trimmed and upper-cased; must not be blank |
| `top_ask_price` | `float` | finite and **strictly positive** |
| `top_bid_price` | `float` | finite, strictly positive, **never above the ask** (crossed market ⇒ rejected) |
| `timestamp` | `int` | epoch **milliseconds**, must not be negative |

Anything violating these rules raises `TickValidationError` naming the offending field. The
feed client skips malformed frames instead of dying, so one bad message cannot tear down a
live desk feed.

### Output — the grid row

| Column | Perspective type | Meaning |
|---|---|---|
| `stock` | `string` | instrument symbol, or `"AAPL/MSFT"` for a pair row |
| `kind` | `string` | `symbol` or `pair` |
| `price` | `float` | mid price `(ask + bid) / 2` of the row's reference leg |
| `ratio` | `float` | the computed ratio (see below) |
| `upper_bound` | `float` | upper edge of the alert band |
| `lower_bound` | `float` | lower edge of the alert band |
| `trigger_alert` | `boolean` | `True` when the ratio breached the band |
| `timestamp` | `datetime` | epoch ms of the observation, ISO-8601 on the wire |

### The two row kinds

**`symbol` rows** — one per instrument update.

```
price  = (top_ask_price + top_bid_price) / 2
ratio  = price / rolling_mean(last N mid prices of this instrument)
```

The ratio therefore expresses *"how far is this instrument from its own recent average?"*
It is dimensionless and centred on `1.0`.

**`pair` rows** — one per correlated pair whose **both legs have been quoted**.

```
price  = mid price of the numerator leg (the first symbol of the pair)
ratio  = mid price(numerator) / mid price(denominator)
```

This is the discrepancy the desk actually cares about: `AAPL/MSFT` sits near `0.46` normally
and drifts when the two instruments decouple. The bounds on a pair row are the rolling
dispersion of *that pair's* ratio.

A pair row is **not** emitted until both legs are known — an undefined ratio must never
reach the grid.

---

## 4. The alert algorithm

The band is derived from a **rolling window** of the ratio series (`window_size`,
default 20) using a **causal** estimator:

```
center      = mean(ratio[0 .. n-1])            # history only
sigma       = stdev(ratio[0 .. n-1])            # sample stdev, Bessel corrected
half_width  = max(sigma_multiplier * sigma, min_half_width)
lower_bound = center - half_width
upper_bound = center + half_width
trigger_alert = ratio < lower_bound or ratio > upper_bound
```

### Why the band is causal

`RollingRatioTracker.update(value)` computes the band from the observations **before** the new
value and only then appends it to the window. A single anomalous tick therefore cannot widen
the band that is supposed to detect it. A non-causal (same-tick) estimator would let a spike
inflate its own tolerance and hide the very event the desk needs to see.

### Cold start

With no history the band is centred on the first observation with a zero dispersion, so a
fresh instrument can never trigger a spurious alert.

### Minimum band width

`min_half_width` (default `0.005`, i.e. 0.5 %) is a floor for the half width. Without it a
perfectly flat series would produce a zero-width band and the first tiny deviation would
fire an alert — statistically correct, operationally useless (alert fatigue).

### Boundary semantics

The bounds are **inclusive**: a ratio sitting exactly on `lower_bound` or `upper_bound` is
*inside* the band. Only a value strictly outside triggers. This makes the behaviour
well-defined at the edge and testable.

### Choosing parameters

| Parameter | Default | Meaning | Guidance |
|---|---|---|---|
| `window_size` | `20` | number of observations in the rolling window | 20 ≈ one session-minute at 1 Hz; larger ⇒ slower reaction, fewer false positives |
| `sigma_multiplier` | `3.0` | band half width in standard deviations | `3` is the classic 99.7 % control limit; `2` is more sensitive, `4` more conservative |
| `min_half_width` | `0.005` | absolute floor of the half width | raise it for illiquid names whose spread alone exceeds the band |

---

## 5. Wire protocol

| Aspect | Choice | Rationale |
|---|---|---|
| Transport | TCP | ordered, reliable, universally proxied |
| Framing | newline-delimited JSON (NDJSON) | one tick per line; survives any middlebox; trivially parseable; no length prefix needed |
| Encoding | UTF-8 | JSON standard |
| Handshake | `{"type":"subscribe"}` → `{"type":"ack"}` | guarantees the client is registered before any tick is published, eliminating the classic "connected but missed the first tick" race |
| Back-pressure | bounded per-client queue (default 4096 frames) | a slow consumer is disconnected rather than allowed to exhaust server memory |
| Max frame | 64 KiB | a frame larger than this without a newline is a protocol error |

Example frame:

```json
{"top_ask_price":190.12,"top_bid_price":190.08,"stock":"AAPL","timestamp":1700000000000}
```

Every client owns an **outbound queue and a dedicated writer thread**, so:

* the publisher never blocks on a slow consumer,
* frame ordering on the wire is preserved,
* one dead consumer cannot affect the others.

---

## 6. Installation

### Requirements

* Python **3.9+** (developed and verified on 3.10)
* `perspective-python` (optional — required only for the live table and the browser dashboard)
* `tornado` (optional — required only for the browser dashboard)

### Option A — virtual environment (recommended)

```bash
cd JPMorgan-Chase-Perspective-Data-Grid

python -m venv .venv
# Linux / macOS
source .venv/bin/activate
# Windows (PowerShell)
.venv\Scripts\Activate.ps1
# Windows (Git Bash)
source .venv/Scripts/activate

pip install -r requirements.txt
pip install -e .
```

### Option B — install into an existing environment

```bash
pip install -r requirements.txt
pip install -e .
```

### Installing without the optional dependencies

The core (feed server, feed client, aggregation engine, in-memory grid) needs **only the
standard library**. The Perspective integration is imported lazily, so the package remains
fully functional — and the entire test suite still passes — when `perspective-python` is
absent:

```bash
pip install -e .          # no extras
pip install -e ".[perspective]"   # with the live table
pip install -e ".[server]"        # with the WebSocket dashboard
pip install -e ".[dev]"           # with pytest, coverage and tornado
```

> **Note on `perspective-python`**: some source distributions require a full Rust/C++ toolchain.
> Pre-built binary wheels are published for the common platforms; prefer
> `pip install --only-binary=:all: perspective-python` if a source build is triggered.

---

## 7. Execution instructions

All commands assume the virtual environment is active and the package is installed
(`pip install -e .`). Without installing, prefix with `PYTHONPATH=src`.

### 7.1 Self-contained demo — no network, no Perspective

```bash
python -m jpm_perspective_grid demo --ticks 2000
```

Expected output:

```
ALERT XOM ratio=1.002670 band=[0.992610, 1.002610] price=117.2500
...
processed 2000 ticks -> 3994 rows
throughput: 45,656 ticks/s, 91,175 rows/s
latency: mean 0.015 ms, p95 0.016 ms
stats: {'ticks_ingested': 2000, 'ticks_rejected': 0, 'rows_emitted': 3994, 'alerts_emitted': 5, ...}
```

Useful flags: `--window 20`, `--sigma 3.0`, `--min-half-width 0.005`, `--seed 1337`,
`--json` (machine-readable output).

### 7.2 Two-process demo — real server and client over TCP

**Terminal 1 — the feed server:**

```bash
python -m jpm_perspective_grid serve --host 127.0.0.1 --port 5555 --rate 200
```

**Terminal 2 — the client and grid:**

```bash
python -m jpm_perspective_grid client --host 127.0.0.1 --port 5555 --ticks 500
```

Add `--perspective --table quotes` to write into a live Perspective table instead of memory,
and `--json` for one JSON document per grid row.

### 7.3 Everything in one process (server + client + grid)

```bash
python -m jpm_perspective_grid live --duration 10 --rate 100 --perspective --table quotes
```

### 7.4 Browser dashboard

```bash
python -m jpm_perspective_grid dashboard --host 127.0.0.1 --port 8888
```

Then open <http://127.0.0.1:8888>. The page embeds `<perspective-viewer>`, connects to the
`/websocket` endpoint and renders the `quotes` table with the `trigger_alert` filter applied.

To feed the dashboard with live data, run the client in a second terminal with
`--perspective --table quotes` (the table lives in the Perspective server of that process —
see §13 for the multi-process wiring).

### 7.5 Throughput benchmark

```bash
python -m jpm_perspective_grid bench --ticks 50000
```

```json
{
  "ticks": 50000,
  "rows": 99993,
  "alerts": 75,
  "elapsed_seconds": 1.096,
  "ticks_per_second": 45612.0,
  "rows_per_second": 91217.0,
  "mean_latency_ms": 0.0156,
  "p95_latency_ms": 0.0167
}
```

> The `bench` command measures the pipeline **with** the per-tick latency probe enabled,
> which roughly halves the raw rate. The engine alone sustains ~109,000 ticks/s (§9).

### 7.6 Library usage

```python
from jpm_perspective_grid import (
    QuoteAggregator, GridPipeline, ThresholdPolicy, MemorySink, Tick,
)

aggregator = QuoteAggregator(
    policy=ThresholdPolicy(window_size=20, sigma_multiplier=3.0),
    pairs=[("AAPL", "MSFT")],
)
pipeline = GridPipeline(aggregator=aggregator, sink=MemorySink())

rows = pipeline.process(Tick("AAPL", 190.12, 190.08, 1700000000000))
print(rows[0].to_dict())
```

---

## 8. Testing

### Running the suite

The repository ships a standalone runner that works on every platform:

```bash
python unit_test.py                # run everything
python unit_test.py --verbose      # one line per test
python unit_test.py --coverage     # with a branch-coverage report
python unit_test.py -k aggregator  # only the tests matching a pattern
python unit_test.py -x             # stop at the first failure
```

It is a thin wrapper around pytest; the canonical test files live in `tests/`.

The equivalent pytest invocations are:

```bash
pytest                       # full suite
pytest -v                    # verbose
pytest --cov=src/jpm_perspective_grid --cov-report=term-missing
```

`pyproject.toml` already registers `pythonpath = ["src"]`, so the tests run against the source
tree **without installing the package**.

### Current status

```
216 passed in 9.61s                       # python unit_test.py
213 passed, 3 skipped in 9.01s           # python unit_test.py --coverage
TOTAL  1045 stmts   59 miss   208 branch   93% coverage
```

The three skips are the throughput-budget tests, which are automatically skipped while a
coverage tracer is attached (tracing slows the code down roughly threefold and would make
the budget meaningless). They run — and pass — on a normal interpreter.

### Test matrix

| File | Tests | Focus |
|---|---|---|
| `tests/test_models.py` | 42 | tick validation, crossed markets, NaN/Inf, booleans-as-numbers, serialisation round trips, band boundary semantics |
| `tests/test_thresholds.py` | 40 | rolling mean/stdev, causality of the band, cold start, window eviction, minimum band width, policy validation, numerical agreement with `statistics` |
| `tests/test_aggregator.py` | 34 | symbol and pair rows, alert detection up/down, pair completeness, malformed payload rejection, out-of-order ticks, reset, counters |
| `tests/test_feed.py` | 42 | server lifecycle, handshake, round trips, multi-client fan-out, frame ordering, malformed and oversized frames, back-pressure, queue overflow, transport throughput |
| `tests/test_pipeline.py` | 26 | sinks, alert callback, throughput budgets, latency budgets, end-to-end flow |
| `tests/test_dashboard.py` | 13 | dashboard HTML, routes, real HTTP request, 404 handling |
| `tests/test_cli.py` | 13 | every sub-command, JSON output, error handling, server↔client integration |
| `tests/test_perspective_sink.py` | 6 | live Perspective table: schema, persistence, boolean column, record conversion |

### Edge cases explicitly covered

**Validation** — blank/whitespace/non-string symbols; zero, negative, `NaN`, `±Inf` prices;
crossed markets (`bid > ask`); negative timestamps; `bool` passed where a number is expected;
strings passed where a number is expected; missing fields; non-mapping payloads; invalid JSON.

**Aggregation** — first observation (cold start); a single observation cannot trigger; a 50 %
price spike triggers; a 50 % crash triggers; a flat series never triggers; per-instrument
isolation; a pair row requires **both** legs; unrelated symbols produce no pair rows; several
pairs at once; out-of-order timestamps are counted and still aggregated; a malformed payload is
counted and skipped without killing the stream.

**Thresholds** — band computed from history only (causality); window eviction; zero
dispersion; minimum band width enforced; policy parameters validated at construction.

**Transport** — handshake consumed correctly (the ack is never mistaken for a tick); a client
without a handshake is not registered; malformed frames raise `FeedProtocolError` or are
skipped via the `on_malformed` callback; frames above 64 KiB are rejected; a frame split
across TCP segments is reassembled; a server closing mid-frame is reported; connecting to a
closed port fails cleanly; connecting twice is rejected; a slow client does not block the
publisher; a client whose queue overflows is disconnected; frames are delivered in order.

**Pipeline** — sink receives exactly the produced rows; the alert callback fires only for
alerting rows; latency and throughput budgets; the whole flow from mock feed to
Perspective-ready dictionaries.

---

## 9. Performance and latency

### Measured on the development machine

Windows 11 · Python 3.10.9 · single core · no compiler flags:

| Stage | Throughput | Latency (mean / p95) |
|---|---|---|
| Mock tick generation | ~214,000 ticks/s | — |
| Aggregation, symbol rows only | ~147,000 ticks/s | 0.007 ms |
| Aggregation, symbol + pair rows | ~117,000 ticks/s | 0.009 ms |
| Full pipeline (no latency probe) | ~109,000 ticks/s | 0.010 ms |
| Full pipeline (with latency probe) | ~47,000 ticks/s | 0.015 / 0.016 ms |
| TCP transport, end to end | > 20,000 ticks/s | ~0.05 ms |

A realistic US equity feed emits far less than 100,000 ticks/s in aggregate, so the engine
has a **two-order-of-magnitude headroom** over the requirement.

### Where the time goes

Profiling (`cProfile`) of the original implementation showed `statistics.stdev` consuming
**~85 % of the aggregation time**: it computes the exact result with `fractions.Fraction`
arithmetic. The fix was a float-native `sample_stdev` (`core/thresholds.py`), which brought
the aggregation engine from **12,000 → 117,000 ticks/s** — a 10× improvement with a numerical
difference far below the noise floor of a market feed.

### Latency budget

| Stage | Budget | Typical |
|---|---|---|
| Tick → validated `Tick` | < 0.01 ms | ~0.002 ms |
| Aggregation (symbol + pair) | < 0.05 ms | ~0.009 ms |
| Sink write (in-memory) | < 0.01 ms | ~0.002 ms |
| **Total per tick (processing)** | **< 0.1 ms** | **~0.015 ms** |
| Socket round trip (loopback) | < 1 ms | ~0.05 ms |

The alert fires on the tick that triggers it; there is no polling interval anywhere in the
design. The pipeline is **push based**: the moment a tick arrives it is aggregated and
written, so the end-to-end latency is the sum of the stages above and nothing else.

### What would change at scale

| Concern | Mitigation |
|---|---|
| GIL limits a single process to one core | the engine is stateless per instrument; shard by symbol across processes and merge the sinks |
| JSON parsing dominates at very high rates | switch the framing to a binary format (e.g. Arrow/msgpack) behind the same `TickFeedClient` interface |
| Perspective `table.update()` is the slowest sink | batch rows (the sink already accepts an iterable) instead of one row per tick |
| Memory growth of the rolling windows | the windows are bounded by `window_size`; the tick history itself is not retained |

---

## 10. Public API reference

### `core.models`

```python
Tick(stock, top_ask_price, top_bid_price, timestamp)
    .mid_price -> float          # (ask + bid) / 2
    .spread -> float             # ask - bid
    .spread_bps -> float
    .from_dict(mapping) -> Tick  # validates, raises TickValidationError
    .from_json(text) -> Tick
    .to_dict() / .to_json()

Quote(stock, top_ask_price, top_bid_price, timestamp)
    .mid_price / .spread
    .from_tick(tick) -> Quote

Band(lower_bound, upper_bound, center, sigma, samples)
    .half_width -> float
    .contains(value) -> bool      # inclusive
    .breaches(value) -> bool      # strict

GridRow(stock, kind, price, ratio, upper_bound, lower_bound, trigger_alert, timestamp)
    .to_dict() -> dict           # Perspective-ready
    .to_json() -> str
```

### `core.thresholds`

```python
ThresholdPolicy(window_size=20, sigma_multiplier=3.0, min_half_width=0.005)

RollingRatioTracker(policy)
    .update(value) -> Band        # causal: the band uses the history only
    .history() -> list[float]
    .samples -> int
    .reset() -> None

PriceBaseline(window_size)
    .update(price) -> float       # rolling mean
```

### `core.aggregator`

```python
QuoteAggregator(policy=None, pairs=())
    .ingest(tick) -> list[GridRow]
    .ingest_raw(payload) -> list[GridRow]   # validates; counts rejects
    .ingest_many(payloads) -> list[GridRow]
    .iter_rows(payloads) -> Iterator[GridRow]
    .latest_quote(symbol) -> Quote | None
    .quotes -> Mapping[str, Quote]
    .stats -> AggregationStats
    .reset() -> None
```

### `infrastructure.feed`

```python
TickFeedServer(host="127.0.0.1", port=0, backlog=16, queue_size=4096, handshake_timeout=5.0)
    .start() / .stop()
    .broadcast(tick) -> int            # clients queued
    .broadcast_many(ticks) -> int
    .broadcast_raw(bytes) -> int
    .wait_for_clients(count=1, timeout=5.0) -> bool
    .port / .host / .client_count

TickFeedClient(host, port, timeout=5.0, on_malformed=None, handshake=True)
    .connect() / .close()
    .read_tick() -> Tick
    .ticks() -> Iterator[Tick]
    .read_ticks(count) -> list[Tick]
```

### `infrastructure.sinks`

```python
MemorySink()
    .write(rows) -> int
    .rows -> list[GridRow]
    .alerts() -> list[GridRow]

PerspectiveTableSink.create(name="quotes", schema=None, server=None) -> PerspectiveTableSink
    .write(rows) -> int
    .snapshot() -> dict[str, list]     # column-oriented view
    .written -> int
```

### `application.pipeline`

```python
GridPipeline(aggregator=None, sink=None, on_alert=None, measure_latency=True)
    .process(tick) -> list[GridRow]
    .process_many(ticks) -> list[GridRow]
    .run(ticks) -> ThroughputReport

ThroughputReport
    .ticks / .rows / .alerts / .elapsed_seconds
    .ticks_per_second / .rows_per_second
    .mean_latency_ms / .p95_latency_ms
    .as_dict()
```

### Error hierarchy

```
GridError
├── TickValidationError(ValueError)   invalid tick payload
├── AggregationError                  inconsistent use of the engine
└── FeedError
    ├── FeedConnectionError           cannot connect / peer closed
    └── FeedProtocolError             malformed frame
```

---

## 11. Parameters and configuration

### CLI reference

| Command | Parameter | Default | Description |
|---|---|---|---|
| `demo` | `--ticks` | `500` | number of ticks to process |
| | `--seed` | `1337` | random seed of the mock feed |
| | `--window` | `20` | rolling window size |
| | `--sigma` | `3.0` | band half width in standard deviations |
| | `--min-half-width` | `0.005` | absolute floor of the band half width |
| | `--json` | off | emit machine-readable output only |
| `serve` | `--host` | `127.0.0.1` | bind address |
| | `--port` | `5555` | bind port (`0` = ephemeral) |
| | `--seed` | `1337` | random seed of the mock feed |
| | `--rate` | `50.0` | published ticks per second |
| | `--duration` | `0.0` | seconds to run (`0` = until interrupted) |
| `client` | `--host` / `--port` | `127.0.0.1` / `5555` | feed server address |
| | `--ticks` | `100` | number of ticks to consume |
| | `--window` / `--sigma` | `20` / `3.0` | threshold parameters |
| | `--perspective` | off | write into a live Perspective table |
| | `--table` | `quotes` | name of the Perspective table |
| | `--json` | off | one JSON document per row |
| `live` | `--host` / `--port` | `127.0.0.1` / `0` | bind address |
| | `--rate` | `50.0` | published ticks per second |
| | `--duration` | `10.0` | seconds to run |
| | `--seed` | `1337` | random seed of the mock feed |
| | `--perspective` / `--table` | off / `quotes` | live table options |
| `bench` | `--ticks` | `20000` | ticks to benchmark |
| | `--seed` | `7` | random seed of the mock feed |
| `dashboard` | `--host` / `--port` | `127.0.0.1` / `8888` | HTTP/WebSocket bind address |

### Environment

| Variable | Purpose |
|---|---|
| `PYTHONPATH=src` | run from the source tree without installing |
| `COVERAGE_RUN=1` | force the throughput budgets to be skipped |

### Default correlated pairs

```python
DEFAULT_PAIRS = (("AAPL", "MSFT"), ("JPM", "GS"), ("XOM", "CVX"))
```

Override them by constructing the aggregator with your own `pairs` argument.

---

## 12. Design decisions and trade-offs

**Why a TCP/NDJSON feed instead of HTTP or WebSocket?**
The feed is a firehose: many small messages, one direction, low latency. NDJSON over TCP gives
ordered delivery, is trivial to inspect with `nc`, survives proxies and needs no handshake
protocol beyond a single line. The Perspective WebSocket is used where it actually earns its
keep — between the server and the browser.

**Why is the band causal?**
A same-tick estimator would let a spike inflate its own tolerance. Causality guarantees that
the band that decides an alert was built from data that predates the observation.

**Why a float-native standard deviation?**
`statistics.stdev` is exact but ~10× slower on the hot path. The numerical difference is
irrelevant next to market noise, and the 10× throughput win is what keeps the engine well
above the required rate. The helper is unit-tested against the exact implementation.

**Why does the aggregation engine keep its own state?**
Because the alert band is inherently a *history* computation. Keeping the rolling windows
inside the engine makes it a self-contained, deterministic state machine that can be tested
without any I/O and replayed deterministically.

**Why is the Perspective import lazy?**
It keeps the core free of a heavy optional dependency (WASM runtime) so the package installs
in milliseconds and the test suite runs on a bare interpreter. The Perspective-specific tests
skip themselves automatically when the library is absent.

**Why a bounded per-client queue?**
Unbounded queues turn one slow consumer into an out-of-memory kill of the whole feed server.
A bounded queue converts that into a clean disconnect of the offending client.

**Rejected alternative — an event bus (Kafka/Redis Streams).**
It would add a broker dependency, an operational surface and a deployment story to a task
whose core value is the streaming aggregation logic. The `RowSink` protocol is the extension
point that makes a broker a drop-in later.

---

## 13. Extension points

### A new sink (Kafka, Redis, CSV, HTTP)

```python
from jpm_perspective_grid.infrastructure.sinks import RowSink

class CsvSink:
    def write(self, rows) -> int:
        for row in rows:
            self._file.write(row.to_json() + "\n")
        return len(rows)

    def close(self) -> None:
        self._file.close()
```

It satisfies the `RowSink` protocol and can be passed straight to `GridPipeline`.

### A real market-data feed

Implement the two-method producer contract the server already follows — publish validated
`Tick` objects — and the rest of the stack is unchanged. The feed protocol itself is
self-contained in `infrastructure/feed.py`.

### A different alert statistic

Subclass or replace `RollingRatioTracker`. The aggregator only depends on
`update(value) -> Band`, so a percentile tracker, an EWMA tracker or an ATR-based tracker
drops in without touching the aggregator.

### Wiring the dashboard and the feed in one process

The Perspective table lives inside the `perspective.Server` of the process that creates it.
To share a table between the client process and the dashboard process, create the server in
one place and pass it to both:

```python
from jpm_perspective_grid.infrastructure.dashboard import build_perspective_server, serve_dashboard
from jpm_perspective_grid.infrastructure.sinks import PerspectiveTableSink

server = build_perspective_server()
sink = PerspectiveTableSink.create(name="quotes", server=server)
# ... feed the sink ...
serve_dashboard(port=8888, perspective_server=server)
```

---

## 14. Project layout

```
JPMorgan-Chase-Perspective-Data-Grid/
├── README.md                       ← this document
├── task.md                         ← the original task statement
├── unit_test.py                    ← standalone test runner (pytest wrapper)
├── pyproject.toml                  ← packaging, pytest and coverage configuration
├── requirements.txt                ← pinned dependency list
├── .gitignore
│
├── src/jpm_perspective_grid/
│   ├── __init__.py                 ← public API re-exports
│   ├── __main__.py                 ← `python -m jpm_perspective_grid`
│   ├── cli.py                      ← demo / serve / client / live / bench / dashboard
│   ├── core/
│   │   ├── errors.py
│   │   ├── models.py
│   │   ├── thresholds.py
│   │   └── aggregator.py
│   ├── infrastructure/
│   │   ├── mock_feed.py
│   │   ├── feed.py
│   │   ├── sinks.py
│   │   └── dashboard.py
│   └── application/
│       └── pipeline.py
│
└── tests/
    ├── conftest.py
    ├── test_models.py
    ├── test_thresholds.py
    ├── test_aggregator.py
    ├── test_feed.py
    ├── test_pipeline.py
    ├── test_perspective_sink.py
    ├── test_dashboard.py
    └── test_cli.py
```

---

## Summary of deliverables against the task requirements

| Requirement | Delivery | Where |
|---|---|---|
| 1. Real-time data feeding server and client utility | TCP/NDJSON server with per-client queues, handshake and back-pressure; matching client | `infrastructure/feed.py` |
| 2. Ingest continuous mock tick streams with `stock`, `top_ask_price`, `top_bid_price`, `timestamp` | `MockTickGenerator` (deterministic random walk, 2-sided market) + fully validated `Tick` | `infrastructure/mock_feed.py`, `core/models.py` |
| 3. Aggregate into a Perspective-ready structure with `price`, `ratio`, `upper_bound`, `lower_bound`, `trigger_alert` | `QuoteAggregator` produces `GridRow`s; `PerspectiveTableSink` writes them into the live table | `core/aggregator.py`, `infrastructure/sinks.py` |
| 4. Comprehensive unit tests for streaming throughput, aggregation logic and alert thresholds | 216 tests, 93 % branch coverage, throughput and latency budgets asserted | `tests/`, `unit_test.py` |
| 5. Production-ready README covering architecture, latency and verification | This document | `README.md` |

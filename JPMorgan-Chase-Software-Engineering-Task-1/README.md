# Task 1: Stock Price Data Feed Analysis

JPMorgan Chase & Co. — Software Engineering Lite.

A dependency-free Python utility that parses quotes from a stock market data
feed, computes the correct stock price, and computes ratios between two stock
prices without divide-by-zero errors.

| File | Purpose |
| --- | --- |
| `client.py` | Implementation: quote parsing, price computation, ratio computation, CLI. |
| `unit_test.py` | 60 unit tests covering calculation accuracy and edge cases. |
| `sample_quotes.csv` | Small sample feed used by the CLI examples below. |
| `task.md` | The original task brief. |

---

## Requirements coverage

| # | Requirement | Where it lives |
| --- | --- | --- |
| 1 | Parse quotes with `stock`, `top_bid_price`, `top_ask_price`, `timestamp` | `StockQuote`, `parse_stock_quote()`, `parse_stock_quotes()`, `read_quotes()` — `client.py:106`, `client.py:149`, `client.py:185` |
| 2 | Stock price = `(top_bid_price + top_ask_price) / 2` | `compute_stock_price()` — `client.py:249` |
| 3 | Ratio of two prices, avoiding divide-by-zero | `compute_stock_price_ratio()`, `safe_compute_stock_price_ratio()` — `client.py:260`, `client.py:290` |
| 4 | Unit tests for accuracy and edge cases | `unit_test.py` |
| 5 | Comprehensive README | this file |

---

## How it works

### 1. Parsing

`parse_stock_quote(record)` turns one raw feed record into an immutable
`StockQuote` dataclass:

```python
from client import parse_stock_quote

quote = parse_stock_quote({
    "stock": "AAPL",
    "top_bid_price": 100.00,
    "top_ask_price": 102.00,
    "timestamp": "2024-01-02T09:30:00",
})

quote.stock          # 'AAPL'
quote.top_bid_price  # 100.0
quote.top_ask_price  # 102.0
quote.timestamp      # '2024-01-02T09:30:00'
```

The parser is deliberately tolerant of real-world feed schemas:

- **Field aliases** — `stock`/`symbol`/`ticker`, `top_bid_price`/`bid_price`/`bid`,
  `top_ask_price`/`ask_price`/`ask`, `timestamp`/`time`/`date` are all accepted.
- **Value coercion** — prices given as strings (`"100.00"`, `"1,000.5"`,
  `"$100.00"`, `"USD 100.00"`) are converted to floats.
- **Validation** — a missing or non-numeric field raises `StockPriceError`
  (a `ValueError` subclass) with the offending record and field name. Booleans
  and `NaN` are rejected as prices.
- **Error context** — `parse_stock_quotes()` reports which index failed:
  `failed to parse quote at index 1: top_bid_price must be a number, got 'oops'`.

Files are read with `read_quotes(path)`, which dispatches on extension:

| Extension | Format |
| --- | --- |
| `.csv` | Header row with column names; uses the `csv` module. |
| `.json` | A JSON array of quote objects, a single quote object, or a wrapper object with a `quotes` / `data` / `records` / `results` list. |
| `.jsonl` / `.ndjson` | One JSON quote object per line. |

### 2. Computing the stock price

The correct stock price is the midpoint of the top-of-book spread:

```
stock_price = (top_bid_price + top_ask_price) / 2
```

```python
from client import compute_stock_price

compute_stock_price(quote)   # 101.0
```

`compute_stock_price()` also accepts the quote's `.stock_price` property:

```python
quote.stock_price            # 101.0
quote.spread                 # 2.0  (ask - bid)
```

Results are rounded to 10 decimal places (`PRICE_PRECISION`) so that binary
floating-point noise such as `0.1 + 0.2 = 0.30000000000000004` does not leak
into comparisons.

### 3. Computing a price ratio

```python
from client import compute_stock_price_ratio, safe_compute_stock_price_ratio

compute_stock_price_ratio(112.0, 55.0)          # 2.0363636364
compute_stock_price_ratio(100.0, 0.0)            # raises ZeroDenominatorError
safe_compute_stock_price_ratio(100.0, 0.0)       # None  (never raises)
safe_compute_stock_price_ratio(100.0, 0.0, default=0.0)   # 0.0
```

Two variants are provided so the caller can choose the behaviour:

- **`compute_stock_price_ratio(numerator, denominator)`** — the strict API. A
  zero denominator raises `ZeroDenominatorError`, a domain-specific subclass of
  `ValueError`. A raw `ZeroDivisionError` never escapes.
- **`safe_compute_stock_price_ratio(numerator, denominator, default=None)`** —
  the non-raising API. Returns `default` for a zero denominator.

Both are used in production paths: `StockPriceFeed.price_ratio()` uses the safe
variant (returning `None` for an undefined ratio), while the CLI reports an
undefined ratio as a friendly message instead of a traceback.

### 4. The feed container

`StockPriceFeed` wraps a list of quotes with lookup helpers:

```python
from client import StockPriceFeed

feed = StockPriceFeed.from_csv("sample_quotes.csv")

feed.symbols              # ['AAPL', 'MSFT', 'GOOG', 'AMZN', 'TSLA', 'ZERO']
feed.price_for("AAPL")    # 112.0  (latest quote for the symbol)
feed.price_for("aapl")    # 112.0  (case insensitive)
feed.prices()             # {'AAPL': 112.0, 'MSFT': 55.0, ...}
feed.price_ratio("AAPL", "MSFT")   # 2.0363636364
feed.quotes_for("AAPL")   # [both AAPL quotes]
feed.summary()            # [(stock, bid, ask, price, timestamp), ...]
```

`price_for()` raises `KeyError` for an unknown symbol; `price_ratio()` returns
`None` when either price is zero.

---

## Running the code

No installation and no third-party dependencies are required — only Python 3.8+
(the standard library is used throughout). Run everything from this directory.

### Run the unit tests

```bash
python -m unittest unit_test -v
```

or

```bash
python unit_test.py
```

Expected output:

```
Ran 60 tests in 0.02s

OK
```

### Run the CLI

List every quote with its computed price:

```bash
python client.py --file sample_quotes.csv --list
```

```
stock               bid          ask        price  timestamp
AAPL              100.0        102.0        101.0  2024-01-02T09:30:00
MSFT               50.0         60.0         55.0  2024-01-02T09:30:01
GOOG              150.0        170.0        160.0  2024-01-02T09:30:02
AMZN              185.0        187.5       186.25  2024-01-02T09:30:03
TSLA              240.0        244.0        242.0  2024-01-02T09:30:04
AAPL              110.0        114.0        112.0  2024-01-02T09:31:00
ZERO                0.0          0.0          0.0  2024-01-02T09:30:05
```

Compute the ratio of two stock prices:

```bash
python client.py --file sample_quotes.csv --ratio AAPL:MSFT
```

```
ratio AAPL/MSFT: 2.0363636364 (112.0 / 55.0)
```

A ratio against a zero price is reported as undefined rather than crashing:

```bash
python client.py --file sample_quotes.csv --ratio MSFT:ZERO
```

```
ratio MSFT/ZERO: undefined (denominator price is zero)
```

CLI options:

| Option | Description |
| --- | --- |
| `--file`, `-f` | Path to a `.csv` / `.json` / `.jsonl` quote feed (required). |
| `--ratio STOCK_A:STOCK_B` | Compute the price ratio of `STOCK_A` over `STOCK_B`. |
| `--list` | Print every quote with its computed price. |

Exit codes: `0` success, `1` a data or lookup error (unknown symbol, undefined
ratio), `2` a usage error (missing `--file`, malformed `--ratio`).

### Use it as a library

```python
from client import StockPriceFeed, compute_stock_price_ratio

feed = StockPriceFeed.from_file("sample_quotes.csv")
ratio = compute_stock_price_ratio(feed.price_for("AAPL"), feed.price_for("MSFT"))
print(ratio)  # 2.0363636364
```

---

## Test coverage

`unit_test.py` contains 60 tests in four groups.

**`TestComputeStockPrice`** — price accuracy:

- midpoint of bid and ask, including non-round values (`10.25`/`10.75` → `10.5`)
- identical bid and ask, zero prices, negative prices
- `.stock_price` property agrees with the function
- no floating-point noise (`0.1`/`0.2` → `0.15`)
- `spread` = ask − bid
- non-`StockQuote` input is rejected

**`TestComputeStockPriceRatio`** — ratio accuracy and divide-by-zero safety:

- normal ratios above and below 1, equal prices → `1.0`
- **zero denominator raises `ZeroDenominatorError`, and specifically not
  `ZeroDivisionError`** (the core of requirement 3)
- zero numerator → `0.0`
- negative prices
- `safe_compute_stock_price_ratio` returns `None` / a custom default
- ratio of two prices computed from quotes
- result rounding to 10 decimals

**`TestParseStockQuote`** — parsing:

- full record, string prices, integer prices, currency-prefixed prices
- field aliases (`symbol`/`bid_price`/`ask_price`/`time`)
- missing `stock`, missing bid, missing ask → `StockPriceError`
- non-numeric, empty, `None`, boolean and `NaN` prices → `StockPriceError`
- non-mapping record → `StockPriceError`
- optional and unparseable timestamps; ISO timestamp parsing
- batch parsing, with the failing index reported

**`TestStockPriceFeed`** — feed behaviour and file I/O:

- length, unique symbol ordering, case-insensitive lookup
- latest quote wins for a repeated symbol
- unknown symbol → `KeyError`
- price ratio between symbols; zero-price numerator and denominator cases
- reading `.csv`, `.json` (array), and `.jsonl` feeds
- missing file → `FileNotFoundError`; unsupported extension → `StockPriceError`

**`TestCli`** — command line smoke tests: `--list`, `--ratio`, missing `--file`,
and unknown symbol each return the expected exit code.

---

## Design notes

- **Standard library only.** No `pip install` step is needed, so the code runs
  in any Python 3.8+ environment — including a grading sandbox with no network
  access.
- **Immutability.** `StockQuote` is a frozen dataclass, so a parsed quote cannot
  be mutated after the fact; the feed holds the quotes and derives prices from
  them.
- **Explicit errors over silent `None`.** The strict ratio function raises a
  typed, catchable error naming the problem instead of letting a
  `ZeroDivisionError` propagate with a bare traceback.
- **Rounding at the boundary.** Prices and ratios are rounded once, at return
  time, so floating-point noise never accumulates through a calculation chain.
- **Latest quote wins.** When a symbol appears more than once in a feed,
  `price_for()` uses the most recent record, which is the correct interpretation
  of a time-ordered market data feed.

## Type checking

The code is clean under Pyright in standard mode:

```bash
pip install pyright
pyright client.py unit_test.py
```

```
0 errors, 0 warnings, 0 informations
```

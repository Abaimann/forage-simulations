"""Stock price data feed analysis utility.

Implements the JPMorgan Chase & Co. Software Engineering Lite - Task 1
("Stock Price Data Feed Analysis") requirements:

  1. Parse stock quotes containing ``stock``, ``top_bid_price``,
     ``top_ask_price`` and ``timestamp``.
  2. Compute the correct stock price as ``(top_bid_price + top_ask_price) / 2``.
  3. Compute the ratio of two stock prices without divide-by-zero errors.
  4. (tests live in ``unit_test.py``)
  5. (documentation lives in ``README.md``)

The module is dependency free (standard library only) and can be used either
as a library::

    from client import StockPriceFeed, compute_stock_price_ratio

    feed = StockPriceFeed.from_csv("quotes.csv")
    price = feed.price_for("AAPL")
    ratio = compute_stock_price_ratio(price, other_price)

or as a command line tool::

    python client.py --file quotes.csv --ratio AAPL:MSFT
"""

from __future__ import annotations

import argparse
import csv
import json
import sys
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, Iterable, Iterator, List, Mapping, Optional, Sequence, Tuple

__all__ = [
    "StockQuote",
    "StockPriceFeed",
    "StockPriceError",
    "ZeroDenominatorError",
    "parse_stock_quote",
    "parse_stock_quotes",
    "read_quotes",
    "compute_stock_price",
    "compute_stock_price_ratio",
    "safe_compute_stock_price_ratio",
    "main",
]

# Number of decimals kept when rounding prices, to avoid binary float noise
# (e.g. 0.1 + 0.2 == 0.30000000000000004).
PRICE_PRECISION = 10

# Accepted aliases for the mandatory fields of a quote record.
_STOCK_KEYS = ("stock", "symbol", "ticker", "name")
_BID_KEYS = ("top_bid_price", "bid_price", "bid", "topbid")
_ASK_KEYS = ("top_ask_price", "ask_price", "ask", "topask")
_TIMESTAMP_KEYS = ("timestamp", "time", "date", "datetime")


class StockPriceError(ValueError):
    """Raised when a quote record is malformed and cannot be parsed."""


class ZeroDenominatorError(StockPriceError):
    """Raised when a ratio is requested with a zero denominator price."""


def _first_present(record: Mapping[str, Any], keys: Sequence[str]) -> Optional[Any]:
    """Return the first non-``None`` value found in ``record`` for ``keys``."""
    for key in keys:
        if key in record and record[key] is not None:
            return record[key]
    return None


def _coerce_price(value: Any, field_name: str) -> float:
    """Convert ``value`` into a float price, raising ``StockPriceError`` on junk."""
    if isinstance(value, bool):  # bool is an int subclass - reject explicitly.
        raise StockPriceError(f"{field_name} must be a number, got {value!r}")
    if isinstance(value, (int, float)):
        price = float(value)
    else:
        text = str(value).strip().replace(",", "")
        # Strip common currency markers such as "$100.00" or "USD 100.00".
        for prefix in ("$", "€", "£", "¥", "USD", "EUR", "GBP"):
            if text.upper().startswith(prefix):
                text = text[len(prefix):].strip()
                break
        if not text:
            raise StockPriceError(f"{field_name} must be a number, got an empty value")
        try:
            price = float(text)
        except ValueError as exc:
            raise StockPriceError(
                f"{field_name} must be a number, got {value!r}"
            ) from exc
    if price != price:  # NaN check
        raise StockPriceError(f"{field_name} must be a number, got NaN")
    return price


@dataclass(frozen=True)
class StockQuote:
    """A single quote tick received from a stock market data feed."""

    stock: str
    top_bid_price: float
    top_ask_price: float
    timestamp: Optional[str] = None

    @property
    def stock_price(self) -> float:
        """The correct stock price: ``(top_bid_price + top_ask_price) / 2``."""
        return compute_stock_price(self)

    @property
    def spread(self) -> float:
        """Difference between the ask and the bid (``ask - bid``)."""
        return round(self.top_ask_price - self.top_bid_price, PRICE_PRECISION)

    @property
    def parsed_timestamp(self) -> Optional[datetime]:
        """Best-effort parsing of ``timestamp`` into a ``datetime``."""
        if not self.timestamp:
            return None
        text = str(self.timestamp).strip().replace("Z", "+00:00")
        try:
            return datetime.fromisoformat(text)
        except ValueError:
            for fmt in ("%Y-%m-%d %H:%M:%S", "%Y-%m-%d", "%H:%M:%S", "%d/%m/%Y %H:%M:%S"):
                try:
                    return datetime.strptime(text, fmt)
                except ValueError:
                    continue
        return None

    def to_dict(self) -> Dict[str, Any]:
        return {
            "stock": self.stock,
            "top_bid_price": self.top_bid_price,
            "top_ask_price": self.top_ask_price,
            "timestamp": self.timestamp,
        }


def parse_stock_quote(record: Mapping[str, Any]) -> StockQuote:
    """Parse a single raw feed record into a :class:`StockQuote`.

    The record must provide a stock identifier plus a bid and an ask price.
    Common field aliases (``bid_price``/``bid``, ``symbol``/``ticker`` ...)
    are accepted so that feeds with slightly different schemas still work.

    Raises:
        StockPriceError: if a required field is missing or not numeric.
    """
    if not isinstance(record, Mapping):
        raise StockPriceError(f"quote record must be a mapping, got {type(record).__name__}")

    stock = _first_present(record, _STOCK_KEYS)
    if stock is None or not str(stock).strip():
        raise StockPriceError(f"quote record is missing a 'stock' field: {dict(record)!r}")
    stock = str(stock).strip()

    bid = _first_present(record, _BID_KEYS)
    if bid is None:
        raise StockPriceError(f"quote record is missing 'top_bid_price': {dict(record)!r}")

    ask = _first_present(record, _ASK_KEYS)
    if ask is None:
        raise StockPriceError(f"quote record is missing 'top_ask_price': {dict(record)!r}")

    timestamp = _first_present(record, _TIMESTAMP_KEYS)

    return StockQuote(
        stock=stock,
        top_bid_price=_coerce_price(bid, "top_bid_price"),
        top_ask_price=_coerce_price(ask, "top_ask_price"),
        timestamp=None if timestamp is None else str(timestamp),
    )


def parse_stock_quotes(records: Iterable[Mapping[str, Any]]) -> List[StockQuote]:
    """Parse an iterable of raw feed records into :class:`StockQuote` objects."""
    quotes: List[StockQuote] = []
    for index, record in enumerate(records):
        try:
            quotes.append(parse_stock_quote(record))
        except StockPriceError as exc:
            raise StockPriceError(f"failed to parse quote at index {index}: {exc}") from exc
    return quotes


def _iter_csv_records(path: Path) -> Iterator[Dict[str, Any]]:
    with path.open("r", newline="", encoding="utf-8-sig") as handle:
        for row in csv.DictReader(handle):
            yield {k: v for k, v in row.items() if k is not None}


def _iter_json_records(path: Path) -> Iterator[Dict[str, Any]]:
    with path.open("r", encoding="utf-8") as handle:
        text = handle.read().strip()
    if not text:
        return
    try:
        payload: Any = json.loads(text)
    except json.JSONDecodeError:
        # JSON Lines fallback: one JSON object per line.
        for line in text.splitlines():
            line = line.strip()
            if line:
                yield json.loads(line)
        return
    if isinstance(payload, Mapping):
        # Either a single quote or a wrapper such as {"quotes": [...]}.
        for key in ("quotes", "data", "records", "results"):
            if key in payload and isinstance(payload[key], list):
                for item in payload[key]:
                    yield item
                return
        yield dict(payload)
    elif isinstance(payload, list):
        for item in payload:
            yield item
    else:
        raise StockPriceError(f"unsupported JSON payload in {path.name}: expected object or array")


def read_quotes(path: "str | Path") -> List[StockQuote]:
    """Read quotes from a ``.csv``, ``.json`` or ``.jsonl`` feed file."""
    file_path = Path(path)
    if not file_path.exists():
        raise FileNotFoundError(f"quote file not found: {file_path}")

    suffix = file_path.suffix.lower()
    if suffix == ".csv":
        records: Iterable[Dict[str, Any]] = _iter_csv_records(file_path)
    elif suffix in (".json", ".jsonl", ".ndjson"):
        records = _iter_json_records(file_path)
    else:
        raise StockPriceError(
            f"unsupported feed file type {suffix!r}; expected .csv, .json or .jsonl"
        )
    return parse_stock_quotes(records)


def compute_stock_price(quote: StockQuote) -> float:
    """Compute the correct stock price for ``quote``.

    The stock price is the midpoint between the top bid and the top ask:
    ``(top_bid_price + top_ask_price) / 2``.
    """
    if not isinstance(quote, StockQuote):
        raise StockPriceError(f"expected a StockQuote, got {type(quote).__name__}")
    return round((quote.top_bid_price + quote.top_ask_price) / 2, PRICE_PRECISION)


def compute_stock_price_ratio(
    numerator: float,
    denominator: float,
    precision: int = PRICE_PRECISION,
) -> float:
    """Return the ratio ``numerator / denominator`` of two stock prices.

    Divide-by-zero errors are avoided: a zero denominator raises the
    domain-specific :class:`ZeroDenominatorError` (a ``ValueError``) instead of
    the built-in ``ZeroDivisionError``. Use
    :func:`safe_compute_stock_price_ratio` when a non-raising variant is wanted.

    Args:
        numerator: the dividend price.
        denominator: the divisor price.
        precision: number of decimals to round the result to.

    Returns:
        The rounded ratio.

    Raises:
        ZeroDenominatorError: if ``denominator`` is zero.
    """
    if denominator == 0:
        raise ZeroDenominatorError(
            "cannot compute a price ratio: the denominator price is zero"
        )
    return round(numerator / denominator, precision)


def safe_compute_stock_price_ratio(
    numerator: float,
    denominator: float,
    default: Optional[float] = None,
    precision: int = PRICE_PRECISION,
) -> Optional[float]:
    """Ratio helper that never raises and returns ``default`` for a zero denominator."""
    if denominator == 0:
        return default
    return round(numerator / denominator, precision)


@dataclass
class StockPriceFeed:
    """An in-memory collection of quotes with price lookup helpers."""

    quotes: List[StockQuote] = field(default_factory=list)

    def __post_init__(self) -> None:
        self.quotes = list(self.quotes)

    # -- constructors ---------------------------------------------------
    @classmethod
    def from_records(cls, records: Iterable[Mapping[str, Any]]) -> "StockPriceFeed":
        return cls(parse_stock_quotes(records))

    @classmethod
    def from_csv(cls, path: "str | Path") -> "StockPriceFeed":
        return cls(read_quotes(path))

    @classmethod
    def from_file(cls, path: "str | Path") -> "StockPriceFeed":
        return cls(read_quotes(path))

    # -- accessors -------------------------------------------------------
    def __len__(self) -> int:
        return len(self.quotes)

    def __iter__(self) -> Iterator[StockQuote]:
        return iter(self.quotes)

    @property
    def symbols(self) -> List[str]:
        """Unique stock symbols present in the feed, in first-seen order."""
        seen: List[str] = []
        for quote in self.quotes:
            if quote.stock not in seen:
                seen.append(quote.stock)
        return seen

    def quotes_for(self, stock: str) -> List[StockQuote]:
        """All quotes for ``stock`` (case insensitive)."""
        target = str(stock).strip().upper()
        return [q for q in self.quotes if q.stock.upper() == target]

    def price_for(self, stock: str) -> float:
        """The stock price of the most recent quote for ``stock``.

        Raises:
            KeyError: when no quote exists for the symbol.
        """
        quotes = self.quotes_for(stock)
        if not quotes:
            raise KeyError(f"no quote found for stock {stock!r}")
        latest = quotes[-1]
        return compute_stock_price(latest)

    def price_ratio(self, stock_a: str, stock_b: str) -> Optional[float]:
        """Ratio of the price of ``stock_a`` to the price of ``stock_b``.

        Returns ``None`` when either price is zero (divide-by-zero avoided).
        """
        numerator = self.price_for(stock_a)
        denominator = self.price_for(stock_b)
        return safe_compute_stock_price_ratio(numerator, denominator)

    def prices(self) -> Dict[str, float]:
        """Mapping of symbol -> latest stock price for every symbol in the feed."""
        return {symbol: self.price_for(symbol) for symbol in self.symbols}

    def summary(self) -> List[Tuple[str, float, float, float, Optional[str]]]:
        """Per-quote rows: ``(stock, bid, ask, price, timestamp)``."""
        return [
            (
                q.stock,
                q.top_bid_price,
                q.top_ask_price,
                compute_stock_price(q),
                q.timestamp,
            )
            for q in self.quotes
        ]


def _parse_args(argv: Optional[Sequence[str]] = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        prog="client.py",
        description="Parse a stock quote feed, compute stock prices and price ratios.",
    )
    parser.add_argument(
        "--file",
        "-f",
        dest="file",
        help="Path to a .csv/.json/.jsonl quote feed file.",
    )
    parser.add_argument(
        "--ratio",
        metavar="STOCK_A:STOCK_B",
        help="Compute the price ratio of STOCK_A over STOCK_B.",
    )
    parser.add_argument(
        "--list",
        action="store_true",
        help="Print every quote with its computed stock price.",
    )
    return parser.parse_args(argv)


def main(argv: Optional[Sequence[str]] = None) -> int:
    """Command line entry point. Returns a process exit code."""
    args = _parse_args(argv)

    if not args.file:
        print("error: --file is required (path to a quote feed)", file=sys.stderr)
        return 2

    try:
        feed = StockPriceFeed.from_file(args.file)
    except FileNotFoundError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2
    except StockPriceError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1

    if args.list or (not args.ratio):
        print(f"{'stock':<10} {'bid':>12} {'ask':>12} {'price':>12}  timestamp")
        for stock, bid, ask, price, timestamp in feed.summary():
            print(f"{stock:<10} {bid:>12} {ask:>12} {price:>12}  {timestamp or ''}")

    if args.ratio:
        if ":" not in args.ratio:
            print("error: --ratio must be formatted as STOCK_A:STOCK_B", file=sys.stderr)
            return 2
        stock_a, stock_b = (part.strip() for part in args.ratio.split(":", 1))
        try:
            numerator = feed.price_for(stock_a)
            denominator = feed.price_for(stock_b)
        except KeyError as exc:
            print(f"error: {exc}", file=sys.stderr)
            return 1
        ratio = safe_compute_stock_price_ratio(numerator, denominator)
        if ratio is None:
            print(
                f"ratio {stock_a}/{stock_b}: undefined (denominator price is zero)",
            )
            return 1
        print(
            f"ratio {stock_a}/{stock_b}: {ratio} "
            f"({numerator} / {denominator})"
        )

    return 0


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())

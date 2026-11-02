"""Immutable domain models for the trading grid.

The domain layer is intentionally dependency free: it contains no I/O, no
third-party imports and no framework specific types.  Everything in here can
be unit tested in isolation.
"""

from __future__ import annotations

import json
import math
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any, Final, Mapping

from .errors import TickValidationError

#: Canonical wire field names of a single tick.
TICK_FIELDS: Final[tuple[str, ...]] = (
    "stock",
    "top_ask_price",
    "top_bid_price",
    "timestamp",
)

#: Dimensions computed by the aggregation engine for the Perspective grid.
GRID_FIELDS: Final[tuple[str, ...]] = (
    "stock",
    "kind",
    "price",
    "ratio",
    "upper_bound",
    "lower_bound",
    "trigger_alert",
    "timestamp",
)

#: Row kind produced for a single instrument.
KIND_SYMBOL: Final[str] = "symbol"

#: Row kind produced for a correlated instrument pair.
KIND_PAIR: Final[str] = "pair"


def normalize_symbol(symbol: Any) -> str:
    """Normalise a ticker symbol to its canonical upper-case form.

    Raises
    ------
    TickValidationError
        If the symbol is missing, not a string or blank after trimming.
    """
    if symbol is None:
        raise TickValidationError("stock symbol is missing", "stock")
    if not isinstance(symbol, str):
        raise TickValidationError(
            f"stock symbol must be a string, got {type(symbol).__name__}", "stock"
        )
    normalized = symbol.strip().upper()
    if not normalized:
        raise TickValidationError("stock symbol must not be blank", "stock")
    return normalized


def _coerce_price(value: Any, field: str) -> float:
    """Validate and convert a price-like field into a finite ``float``."""
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise TickValidationError(
            f"{field} must be a number, got {type(value).__name__}", field
        )
    price = float(value)
    if not math.isfinite(price):
        raise TickValidationError(f"{field} must be finite, got {value!r}", field)
    if price <= 0.0:
        raise TickValidationError(f"{field} must be strictly positive, got {price!r}", field)
    return price


def _coerce_timestamp(value: Any) -> int:
    """Validate and convert a timestamp into epoch milliseconds."""
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise TickValidationError(
            f"timestamp must be a number, got {type(value).__name__}", "timestamp"
        )
    if not math.isfinite(float(value)):
        raise TickValidationError("timestamp must be finite", "timestamp")
    timestamp = int(value)
    if timestamp < 0:
        raise TickValidationError(
            f"timestamp must not be negative, got {timestamp}", "timestamp"
        )
    return timestamp


@dataclass(frozen=True, slots=True)
class Tick:
    """A single top-of-book quote update.

    Attributes
    ----------
    stock:
        Canonical (upper-case, trimmed) ticker symbol.
    top_ask_price:
        Best ask price, strictly positive.
    top_bid_price:
        Best bid price, strictly positive and never above ``top_ask_price``.
    timestamp:
        Exchange timestamp in epoch milliseconds.
    """

    stock: str
    top_ask_price: float
    top_bid_price: float
    timestamp: int

    def __post_init__(self) -> None:
        object.__setattr__(self, "stock", normalize_symbol(self.stock))
        ask = _coerce_price(self.top_ask_price, "top_ask_price")
        bid = _coerce_price(self.top_bid_price, "top_bid_price")
        if bid > ask:
            raise TickValidationError(
                f"crossed market: top_bid_price ({bid}) > top_ask_price ({ask})",
                "top_bid_price",
            )
        object.__setattr__(self, "top_ask_price", ask)
        object.__setattr__(self, "top_bid_price", bid)
        object.__setattr__(self, "timestamp", _coerce_timestamp(self.timestamp))

    @property
    def mid_price(self) -> float:
        """Mid price, i.e. the average of the best bid and the best ask."""
        return (self.top_ask_price + self.top_bid_price) / 2.0

    @property
    def spread(self) -> float:
        """Absolute spread between the best ask and the best bid."""
        return self.top_ask_price - self.top_bid_price

    @property
    def spread_bps(self) -> float:
        """Spread expressed in basis points of the mid price."""
        mid = self.mid_price
        if mid <= 0.0:  # pragma: no cover - unreachable, prices are validated
            return 0.0
        return (self.spread / mid) * 10_000.0

    @classmethod
    def from_dict(cls, payload: Mapping[str, Any]) -> "Tick":
        """Build a tick from a mapping, validating every field.

        Raises
        ------
        TickValidationError
            If a mandatory field is missing or invalid.
        """
        if not isinstance(payload, Mapping):
            raise TickValidationError(
                f"tick payload must be a mapping, got {type(payload).__name__}"
            )
        missing = [name for name in TICK_FIELDS if name not in payload]
        if missing:
            raise TickValidationError(
                f"missing mandatory field(s): {', '.join(sorted(missing))}",
                sorted(missing)[0],
            )
        return cls(
            stock=payload["stock"],
            top_ask_price=payload["top_ask_price"],
            top_bid_price=payload["top_bid_price"],
            timestamp=payload["timestamp"],
        )

    @classmethod
    def from_json(cls, raw: str) -> "Tick":
        """Parse a JSON document into a tick.

        Raises
        ------
        TickValidationError
            If the document is not valid JSON or does not describe a tick.
        """
        try:
            payload = json.loads(raw)
        except (json.JSONDecodeError, TypeError) as exc:
            raise TickValidationError(f"payload is not valid JSON: {exc}") from exc
        return cls.from_dict(payload)

    def to_dict(self) -> dict[str, Any]:
        """Return the canonical wire representation of the tick."""
        return {
            "stock": self.stock,
            "top_ask_price": self.top_ask_price,
            "top_bid_price": self.top_bid_price,
            "timestamp": self.timestamp,
        }

    def to_json(self) -> str:
        """Return the tick as a compact JSON document."""
        return json.dumps(self.to_dict(), separators=(",", ":"), sort_keys=True)


@dataclass(frozen=True, slots=True)
class Quote:
    """The most recent consolidated quote of a single instrument."""

    stock: str
    top_ask_price: float
    top_bid_price: float
    timestamp: int

    @classmethod
    def from_tick(cls, tick: Tick) -> "Quote":
        """Derive a quote from an incoming tick."""
        return cls(
            stock=tick.stock,
            top_ask_price=tick.top_ask_price,
            top_bid_price=tick.top_bid_price,
            timestamp=tick.timestamp,
        )

    @property
    def mid_price(self) -> float:
        """Mid price of the quote."""
        return (self.top_ask_price + self.top_bid_price) / 2.0

    @property
    def spread(self) -> float:
        """Absolute spread of the quote."""
        return self.top_ask_price - self.top_bid_price


@dataclass(frozen=True, slots=True)
class Band:
    """An alert band ``[lower_bound, upper_bound]`` around a centre value.

    The band is derived from the *history* of a ratio series; the observation
    that produced the band is therefore compared against data that predates
    it, which keeps alerts causal rather than self-referential.
    """

    lower_bound: float
    upper_bound: float
    center: float
    sigma: float
    samples: int

    @property
    def half_width(self) -> float:
        """Half of the band width."""
        return (self.upper_bound - self.lower_bound) / 2.0

    def contains(self, value: float) -> bool:
        """Return ``True`` when *value* lies inside the closed band."""
        return self.lower_bound <= value <= self.upper_bound

    def breaches(self, value: float) -> bool:
        """Return ``True`` when *value* lies strictly outside the band.

        The bounds themselves are *not* breaches: a value sitting exactly on a
        bound is considered inside the tolerance.
        """
        return value < self.lower_bound or value > self.upper_bound


@dataclass(frozen=True, slots=True)
class GridRow:
    """A single row of the Perspective data grid.

    Attributes
    ----------
    stock:
        Instrument symbol (or ``"AAPL/MSFT"`` for pair rows).
    kind:
        Either :data:`KIND_SYMBOL` or :data:`KIND_PAIR`.
    price:
        Mid price the row was computed from.
    ratio:
        Computed ratio (price versus its rolling baseline, or the price ratio
        of a correlated pair).
    upper_bound:
        Upper edge of the alert band.
    lower_bound:
        Lower edge of the alert band.
    trigger_alert:
        ``True`` when the ratio breached the band.
    timestamp:
        Epoch milliseconds the row was produced at.
    """

    stock: str
    kind: str
    price: float
    ratio: float
    upper_bound: float
    lower_bound: float
    trigger_alert: bool
    timestamp: int

    def to_dict(self) -> dict[str, Any]:
        """Return the row in a shape that is directly consumable by
        ``perspective.Table.update``."""
        return {
            "stock": self.stock,
            "kind": self.kind,
            "price": float(self.price),
            "ratio": float(self.ratio),
            "upper_bound": float(self.upper_bound),
            "lower_bound": float(self.lower_bound),
            "trigger_alert": bool(self.trigger_alert),
            "timestamp": epoch_ms_to_iso(self.timestamp),
        }

    def to_json(self) -> str:
        """Return the row as a compact JSON document."""
        return json.dumps(self.to_dict(), separators=(",", ":"), sort_keys=True)


def epoch_ms_to_iso(timestamp_ms: int) -> str:
    """Convert epoch milliseconds into an ISO-8601 UTC timestamp.

    ``perspective`` maps the ``datetime`` column type onto epoch
    milliseconds, but accepts ISO-8601 documents as well which is far more
    convenient when debugging.
    """
    moment = datetime.fromtimestamp(timestamp_ms / 1000.0, tz=timezone.utc)
    return moment.isoformat().replace("+00:00", "Z")

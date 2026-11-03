"""Timestamp normalization utilities.

Factory sensors emit time in wildly inconsistent shapes: naive local strings,
ISO-8601 with offsets, epoch seconds, epoch milliseconds and naive epochs.
Every one of them is folded into timezone-aware UTC here so the rest of the
pipeline can assume a single temporal representation.
"""

from __future__ import annotations

import re
from datetime import datetime, timedelta, timezone

from ..domain.exceptions import NormalizationError

#: Formats attempted, in order, when the payload is a string.
#: Numeric slash/dash dates are handled separately by :func:`_parse_numeric_date`
#: because their day/month order is ambiguous.
_SUPPORTED_FORMATS: tuple[str, ...] = (
    "%Y-%m-%dT%H:%M:%S.%f",
    "%Y-%m-%dT%H:%M:%S",
    "%Y-%m-%dT%H:%M",
    "%Y-%m-%d %H:%M:%S.%f",
    "%Y-%m-%d %H:%M:%S",
    "%Y-%m-%d %H:%M",
    "%Y-%m-%d",
    "%Y/%m/%d %H:%M:%S",
    "%Y/%m/%d",
    "%d-%m-%Y %H:%M:%S",
    "%d-%m-%Y",
)

#: Regex matching numeric dates such as ``01/05/2024 08:00:00``.
#: The year component is optional so that partial dates such as ``01/05`` are
#: supported (they are anchored to the year 2000).
_NUMERIC_DATE_RE = re.compile(
    r"^(?P<a>\d{1,4})[/\-](?P<b>\d{1,2})"
    r"(?:[/\-](?P<c>\d{1,4}))?"
    r"(?:[ T](?P<hour>\d{1,2}):(?P<minute>\d{2})(?::(?P<second>\d{2})(?:\.(?P<frac>\d+))?)?)?$"
)

#: Epoch magnitudes above which the unit is interpreted differently.
_EPOCH_MS_THRESHOLD = 1e11
_EPOCH_US_THRESHOLD = 1e14
_EPOCH_NS_THRESHOLD = 1e17


def to_utc(value: datetime) -> datetime:
    """Return ``value`` as timezone-aware UTC.

    Naive datetimes are *assumed* to be UTC (documented, configurable at the
    pipeline level via ``assume_naive_is_utc``).
    """
    if value.tzinfo is None:
        return value.replace(tzinfo=timezone.utc)
    return value.astimezone(timezone.utc)


def _from_epoch(number: float) -> datetime:
    """Interpret a numeric epoch using magnitude-based unit detection."""
    magnitude = abs(number)
    if magnitude >= _EPOCH_NS_THRESHOLD:
        seconds = number / 1e9
    elif magnitude >= _EPOCH_US_THRESHOLD:
        seconds = number / 1e6
    elif magnitude >= _EPOCH_MS_THRESHOLD:
        seconds = number / 1e3
    else:
        seconds = number
    try:
        return datetime.fromtimestamp(seconds, tz=timezone.utc)
    except (OverflowError, OSError, ValueError) as exc:
        raise NormalizationError(f"epoch timestamp out of range: {number!r}") from exc


def _parse_numeric_date(text: str, day_first: bool) -> datetime | None:
    """Parse a numeric slash/dash date, resolving the day/month ambiguity.

    Resolution order:

    1. If the first component exceeds 12 it can only be a day -> day-first.
    2. If the second component exceeds 12 it can only be a day -> month-first.
    3. Otherwise the date is genuinely ambiguous and the ``day_first`` policy
       decides (day-first is the default, matching the predominantly European
       legacy systems of the plant network).

    Returns ``None`` when the text does not match a numeric date at all.
    """
    match = _NUMERIC_DATE_RE.match(text)
    if match is None:
        return None

    a = int(match.group("a"))
    b = int(match.group("b"))
    c_raw = match.group("c")
    c = int(c_raw) if c_raw is not None else 0

    if c_raw is None:
        # Two-component date: day/month without a year.
        if a > 12:
            day, month = a, b
        elif b > 12:
            month, day = a, b
        elif day_first:
            day, month = a, b
        else:
            month, day = a, b
        year = 2000
    elif len(match.group("a")) == 4:
        year, month, day = a, b, c
    elif len(c_raw) == 4:
        if a > 12:
            day, month, year = a, b, c
        elif b > 12:
            month, day, year = a, b, c
        elif day_first:
            day, month, year = a, b, c
        else:
            month, day, year = a, b, c
    else:
        # Neither component is a four-digit year: assume the current century.
        if a > 12:
            day, month = a, b
        elif b > 12:
            month, day = a, b
        elif day_first:
            day, month = a, b
        else:
            month, day = a, b
        year = 2000 + c

    try:
        base = datetime(year, month, day)
    except ValueError:
        return None

    hour = int(match.group("hour") or 0)
    minute = int(match.group("minute") or 0)
    second = int(match.group("second") or 0)
    frac = match.group("frac")
    microsecond = int((frac or "0").ljust(6, "0")[:6])

    try:
        return base.replace(hour=hour, minute=minute, second=second, microsecond=microsecond)
    except ValueError:
        return None


def parse_timestamp(raw: object, day_first: bool = True) -> datetime:
    """Parse a heterogeneous timestamp into timezone-aware UTC.

    Supported inputs
    ----------------
    * ``datetime`` instances (naive values are assumed UTC).
    * ``int`` / ``float`` epoch seconds, milliseconds, microseconds or
      nanoseconds (unit inferred from magnitude).
    * Numeric strings (same epoch handling).
    * ISO-8601 strings, with or without fractional seconds and offset.
    * A curated set of legacy date formats.

    Parameters
    ----------
    raw:
        The value to parse.
    day_first:
        Policy applied to ambiguous numeric dates such as ``05/01/2024``.
        ``True`` (default) interprets them as day-first, ``False`` as
        month-first.

    Raises
    ------
    NormalizationError
        If the value cannot be interpreted as a timestamp.
    """
    if isinstance(raw, datetime):
        return to_utc(raw)

    if isinstance(raw, bool):
        raise NormalizationError(f"cannot parse boolean {raw!r} as timestamp")

    if isinstance(raw, (int, float)):
        return _from_epoch(float(raw))

    if not isinstance(raw, str):
        raise NormalizationError(f"cannot parse {type(raw).__name__} as timestamp")

    text = raw.strip()
    if not text:
        raise NormalizationError("cannot parse empty string as timestamp")

    # Numeric string -> epoch.
    try:
        numeric = float(text)
    except ValueError:
        numeric = None
    if numeric is not None and numeric == numeric:
        return _from_epoch(numeric)

    # ISO-8601, handling the trailing "Z" suffix explicitly (py<3.11 ISO
    # parsing does not accept it) and naive/offset variants.
    iso_candidate = text
    if iso_candidate.endswith(("Z", "z")):
        iso_candidate = iso_candidate[:-1] + "+00:00"
    try:
        return to_utc(datetime.fromisoformat(iso_candidate))
    except ValueError:
        pass

    # Numeric slash/dash dates with an explicit day/month disambiguation.
    numeric_date = _parse_numeric_date(text, day_first)
    if numeric_date is not None:
        return to_utc(numeric_date)

    for fmt in _SUPPORTED_FORMATS:
        try:
            return to_utc(datetime.strptime(text, fmt))
        except ValueError:
            continue

    raise NormalizationError(f"unrecognised timestamp format: {raw!r}")


def normalize_timestamp(raw: object) -> datetime:
    """Alias of :func:`parse_timestamp` kept for readability at call sites."""
    return parse_timestamp(raw)


def iso8601(value: datetime) -> str:
    """Render ``value`` as a canonical UTC ISO-8601 string."""
    return to_utc(value).isoformat()


def seconds_between(earlier: datetime, later: datetime) -> float:
    """Return the number of seconds between two instants (may be negative)."""
    return (to_utc(later) - to_utc(earlier)).total_seconds()


def floor_to_second(value: datetime) -> datetime:
    """Truncate microseconds, used when de-duplicating records."""
    return to_utc(value).replace(microsecond=0)


def ensure_utc_now() -> datetime:
    """Current instant in UTC (isolated for deterministic testing)."""
    return datetime.now(timezone.utc)


def shift(value: datetime, seconds: float) -> datetime:
    """Return ``value`` shifted by ``seconds``."""
    return to_utc(value) + timedelta(seconds=seconds)

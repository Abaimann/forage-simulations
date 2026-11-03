"""CSV telemetry parser.

Legacy linesystems export CSV with inconsistent headers, delimiters and
quoting conventions. The parser:

* sniffs the delimiter (``,`` ``;`` ``\\t`` ``|``) when not configured,
* tolerates a UTF-8 BOM and surrounding whitespace in headers,
* maps legacy column names onto canonical field names,
* skips blank lines and reports rows with a wrong column count.
"""

from __future__ import annotations

import csv
from pathlib import Path
from typing import Any, Iterator, Mapping

from ...application.ports import SourceConfig, TelemetrySource
from ...domain.exceptions import ParseError

#: Legacy/alias column names mapped onto canonical names.
_COLUMN_ALIASES: Mapping[str, str] = {
    "sensor_id": "sensor_id",
    "sensorid": "sensor_id",
    "sensor": "sensor_id",
    "device_id": "sensor_id",
    "deviceid": "sensor_id",
    "device": "sensor_id",
    "tag": "sensor_id",
    "machine_id": "machine_id",
    "machineid": "machine_id",
    "machine": "machine_id",
    "asset_id": "machine_id",
    "assetid": "machine_id",
    "asset": "machine_id",
    "equipment_id": "machine_id",
    "line_id": "machine_id",
    "timestamp": "timestamp",
    "ts": "timestamp",
    "time": "timestamp",
    "event_time": "timestamp",
    "eventtime": "timestamp",
    "datetime": "timestamp",
    "date_time": "timestamp",
    "recorded_at": "timestamp",
    "reading_time": "timestamp",
    "value": "value",
    "reading": "value",
    "val": "value",
    "measurement": "value",
    "reading_value": "value",
    "readingvalue": "value",
    "amount": "value",
    "sensor_type": "sensor_type",
    "sensortype": "sensor_type",
    "type": "sensor_type",
    "metric": "sensor_type",
    "kind": "sensor_type",
    "unit": "unit",
    "units": "unit",
    "uom": "unit",
    "unit_of_measure": "unit",
    "temperature": "temperature",
    "temp": "temperature",
    "temp_c": "temperature",
    "temperature_c": "temperature",
    "vibration": "vibration",
    "vib": "vibration",
    "vibration_hz": "vibration",
    "frequency": "vibration",
    "freq": "vibration",
    "error_code": "error_code",
    "errorcode": "error_code",
    "error": "error_code",
    "code": "error_code",
    "fault_code": "error_code",
    "alarm_code": "error_code",
}

#: Candidate delimiters used when sniffing.
_SNIFF_DELIMITERS: tuple[str, ...] = (",", ";", "\t", "|")

#: Minimum number of header cells expected for a valid telemetry CSV.
_MIN_COLUMNS = 3


def _sniff_delimiter(sample: str) -> str:
    """Guess the delimiter of a CSV sample using the :mod:`csv` sniffer."""
    try:
        dialect = csv.Sniffer().sniff(sample, delimiters="".join(_SNIFF_DELIMITERS))
        return dialect.delimiter
    except csv.Error:
        # Fall back to counting occurrences in the header line.
        header = sample.splitlines()[0] if sample.splitlines() else ""
        counts = {d: header.count(d) for d in _SNIFF_DELIMITERS}
        best = max(counts, key=lambda d: counts[d])
        return best if counts[best] > 0 else ","


def _canonical_header(raw: str) -> str:
    """Normalize and map a raw CSV header cell onto a canonical field name."""
    cleaned = raw.strip().lstrip("\ufeff").strip('"').strip().lower()
    cleaned = cleaned.replace(" ", "_").replace("-", "_")
    return _COLUMN_ALIASES.get(cleaned, cleaned)


class CsvTelemetryParser(TelemetrySource):
    """Reads delimited telemetry files into raw mapping records."""

    def read(self, config: SourceConfig) -> Iterator[Mapping[str, Any]]:
        """Yield one mapping per CSV data row."""
        path = Path(config.path)
        try:
            text = path.read_text(encoding=config.encoding)
        except OSError as exc:
            raise ParseError(f"cannot read file: {exc}", source=str(path)) from exc
        except UnicodeDecodeError as exc:
            raise ParseError(f"cannot decode file as {config.encoding}: {exc}", source=str(path)) from exc

        if not text.strip():
            return

        delimiter = config.delimiter or _sniff_delimiter(text[:4096])
        reader = csv.reader(text.splitlines(), delimiter=delimiter)

        try:
            header = next(reader)
        except StopIteration:  # pragma: no cover - guarded by the empty check above
            return

        if len(header) < _MIN_COLUMNS:
            raise ParseError(
                f"CSV header has {len(header)} columns, expected at least {_MIN_COLUMNS}",
                source=str(path),
            )

        canonical_header = [_canonical_header(cell) for cell in header]

        for row in reader:
            if not row or all(not cell.strip() for cell in row):
                continue
            if len(row) != len(canonical_header):
                # Structurally broken row: skip it rather than misalign values.
                continue
            record: dict[str, Any] = {}
            for key, value in zip(canonical_header, row):
                if not key:
                    continue
                cell = value.strip()
                # Several source columns may map onto the same canonical field
                # (typical during a schema-drift window). A populated value must
                # never be overwritten by an empty one.
                if key in record and not cell:
                    continue
                record[key] = cell
            yield record

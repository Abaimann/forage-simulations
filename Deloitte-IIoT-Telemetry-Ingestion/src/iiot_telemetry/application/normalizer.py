"""Normalization of heterogeneous raw payloads into canonical sensor readings.

This module is the anti-corruption layer of the pipeline. It absorbs the
messiness of legacy factory-floor formats:

* **Schema drift** - field renaming (``sensor_id`` / ``sensorId`` / ``device_id``).
* **Structural variance** - flat records, nested ``readings`` objects, arrays of
  readings, and "wide" rows where one physical row holds several sensor values.
* **Unit variance** - temperature in F/K, vibration in mm/s or g.
* **Corruption** - sentinel values (``-999``, ``N/A``, ``NaN``), truncated
  numbers, malformed timestamps.
"""

from __future__ import annotations

import math
import re
from dataclasses import dataclass, field
from typing import Any, Iterable, Mapping, Sequence

from ..domain.contracts import DataContract, SensorContract
from ..domain.exceptions import ContractViolation, NormalizationError
from ..domain.models import RejectReason, RejectedRecord, SensorReading, SensorType, Timestamp
from .timestamp import parse_timestamp

#: Sentinel values that legacy devices emit to signal "no data".
_SENTINELS: frozenset[str] = frozenset(
    {
        "",
        "-",
        "--",
        "n/a",
        "na",
        "null",
        "none",
        "nil",
        "nan",
        "unknown",
        "error",
        "err",
        "timeout",
        "disconnected",
        "offline",
        "-999",
        "-9999",
        "999",
        "9999",
        "1e309",
        "inf",
        "-inf",
        "+inf",
        "infinity",
        "-infinity",
    }
)

_NUMERIC_RE = re.compile(r"^[+-]?(\d+\.?\d*|\.\d+)([eE][+-]?\d+)?$")

#: Canonical field name -> accepted source aliases (case-insensitive).
_FIELD_ALIASES: Mapping[str, tuple[str, ...]] = {
    "sensor_id": ("sensor_id", "sensorid", "sensor", "device_id", "deviceid", "device", "id", "tag"),
    "machine_id": ("machine_id", "machineid", "machine", "asset_id", "assetid", "asset", "equipment_id", "line_id"),
    "timestamp": ("timestamp", "ts", "time", "event_time", "eventtime", "datetime", "date_time", "recorded_at", "reading_time"),
    "value": ("value", "reading", "val", "measurement", "reading_value", "readingvalue", "reading_val", "amount"),
    "sensor_type": ("sensor_type", "sensortype", "type", "metric", "kind", "sensor_category"),
    "unit": ("unit", "units", "uom", "unit_of_measure", "unitofmeasure"),
    "error_code": ("error_code", "errorcode", "error", "code", "fault_code", "alarm_code"),
    "temperature": ("temperature", "temp", "temp_c", "temperature_c", "temperaturec", "ambient_temperature"),
    "vibration": ("vibration", "vib", "vibration_hz", "vibrationhz", "vib_hz", "frequency", "freq"),
}

#: Reverse lookup: alias -> canonical field.
_ALIAS_TO_FIELD: Mapping[str, str] = {
    alias: canonical for canonical, aliases in _FIELD_ALIASES.items() for alias in aliases
}

#: Canonical "wide" fields that implicitly determine the sensor type.
_TYPE_FROM_FIELD: Mapping[str, SensorType] = {
    "temperature": SensorType.TEMPERATURE,
    "vibration": SensorType.VIBRATION,
    "error_code": SensorType.ERROR_CODE,
}

#: Units that unambiguously identify a sensor type. Legacy exports often omit
#: the ``sensor_type`` column but keep the physical unit.
_TYPE_FROM_UNIT: Mapping[str, SensorType] = {
    "c": SensorType.TEMPERATURE,
    "celsius": SensorType.TEMPERATURE,
    "degc": SensorType.TEMPERATURE,
    "\u00b0c": SensorType.TEMPERATURE,
    "f": SensorType.TEMPERATURE,
    "fahrenheit": SensorType.TEMPERATURE,
    "k": SensorType.TEMPERATURE,
    "kelvin": SensorType.TEMPERATURE,
    "hz": SensorType.VIBRATION,
    "hertz": SensorType.VIBRATION,
    "khz": SensorType.VIBRATION,
    "mhz": SensorType.VIBRATION,
    "rpm": SensorType.VIBRATION,
    "code": SensorType.ERROR_CODE,
    "error": SensorType.ERROR_CODE,
    "err": SensorType.ERROR_CODE,
}

#: Keys that never carry reading payloads but may appear in wide rows.
_IGNORED_KEYS: frozenset[str] = frozenset(
    {
        "metadata",
        "meta",
        "tags",
        "labels",
        "quality",
        "quality_flags",
        "site",
        "plant",
        "region",
        "line",
        "location",
        "firmware",
        "firmware_version",
        "serial",
        "serial_number",
        "comment",
        "notes",
        "status",
        "battery",
        "rssi",
        "lat",
        "lon",
        "latitude",
        "longitude",
    }
)

#: Unit conversions into the canonical unit of each sensor type.
#: Each entry maps a lower-cased source unit to ``(target_unit, factor, offset)``
#: where ``canonical = raw * factor + offset``.
_UNIT_CONVERSIONS: Mapping[SensorType, Mapping[str, tuple[str, float, float]]] = {
    SensorType.TEMPERATURE: {
        "c": ("C", 1.0, 0.0),
        "celsius": ("C", 1.0, 0.0),
        "degc": ("C", 1.0, 0.0),
        "\u00b0c": ("C", 1.0, 0.0),
        "f": ("C", 5.0 / 9.0, -32.0 * 5.0 / 9.0),
        "fahrenheit": ("C", 5.0 / 9.0, -32.0 * 5.0 / 9.0),
        "degf": ("C", 5.0 / 9.0, -32.0 * 5.0 / 9.0),
        "\u00b0f": ("C", 5.0 / 9.0, -32.0 * 5.0 / 9.0),
        "k": ("C", 1.0, -273.15),
        "kelvin": ("C", 1.0, -273.15),
    },
    SensorType.VIBRATION: {
        "hz": ("Hz", 1.0, 0.0),
        "hertz": ("Hz", 1.0, 0.0),
        "khz": ("Hz", 1000.0, 0.0),
        "mhz": ("Hz", 1_000_000.0, 0.0),
        "rpm": ("Hz", 1.0 / 60.0, 0.0),
        "mm_s": ("Hz", 1.0, 0.0),
        "m_s2": ("Hz", 1.0, 0.0),
        "g": ("Hz", 1.0, 0.0),
    },
    SensorType.ERROR_CODE: {},
}


@dataclass(frozen=True, slots=True)
class NormalizationSettings:
    """Tunable knobs for the normalization stage."""

    assume_naive_is_utc: bool = True
    drop_missing_optional_fields: bool = True
    max_records_per_batch: int = 1_000_000


@dataclass
class NormalizationResult:
    """Outcome of normalizing a batch of raw payloads."""

    readings: list[SensorReading] = field(default_factory=list)
    rejected: list[RejectedRecord] = field(default_factory=list)
    schema_drift_detected: bool = False
    observed_fields: set[str] = field(default_factory=set)

    @property
    def accepted_count(self) -> int:
        return len(self.readings)

    @property
    def rejected_count(self) -> int:
        return len(self.rejected)


class TelemetryNormalizer:
    """Converts raw payload dictionaries into validated :class:`SensorReading`."""

    def __init__(
        self,
        contract: DataContract | None = None,
        settings: NormalizationSettings | None = None,
    ) -> None:
        self.contract = contract or DataContract()
        self.settings = settings or NormalizationSettings()

    # -- public API -------------------------------------------------------- #

    def normalize_batch(
        self,
        payloads: Sequence[Mapping[str, Any]],
        source: str = "<memory>",
    ) -> NormalizationResult:
        """Normalize a batch of raw payloads, collecting rejects instead of raising."""
        result = NormalizationResult()
        if len(payloads) > self.settings.max_records_per_batch:
            raise NormalizationError(
                f"batch of {len(payloads)} exceeds limit {self.settings.max_records_per_batch}"
            )
        for index, payload in enumerate(payloads):
            if not isinstance(payload, Mapping):
                result.rejected.append(
                    RejectedRecord(
                        reason=RejectReason.SCHEMA_DRIFT,
                        detail=f"payload is {type(payload).__name__}, expected mapping",
                        source=source,
                        record_index=index,
                    )
                )
                continue
            if not payload:
                result.rejected.append(
                    RejectedRecord(
                        reason=RejectReason.EMPTY_PAYLOAD,
                        detail="empty payload",
                        source=source,
                        record_index=index,
                    )
                )
                continue
            result.observed_fields.update(str(k) for k in payload.keys())
            try:
                readings = self._normalize_payload(payload)
            except (ContractViolation, NormalizationError) as exc:
                result.rejected.append(
                    RejectedRecord(
                        reason=self._classify(exc),
                        detail=str(exc),
                        source=source,
                        raw_payload=dict(payload),
                        record_index=index,
                    )
                )
                continue
            result.readings.extend(readings)
        return result

    def normalize(self, payload: Mapping[str, Any], source: str = "<memory>") -> SensorReading:
        """Normalize exactly one payload into a single reading.

        Raises
        ------
        ContractViolation / NormalizationError
            When the payload cannot be promoted to a reading.
        """
        readings = self._normalize_payload(payload)
        if len(readings) > 1:
            raise NormalizationError(
                f"payload contains {len(readings)} readings; use normalize_batch()"
            )
        return readings[0]

    # -- internals --------------------------------------------------------- #

    @staticmethod
    def _classify(exc: Exception) -> RejectReason:
        """Map an exception onto the reason why the record was rejected.

        Timestamp problems surface as a ``ContractViolation`` carrying the
        ``timestamp.*`` rule (see :meth:`_build_reading`); a bare
        ``NormalizationError`` therefore denotes a structural problem, i.e.
        schema drift.
        """
        if isinstance(exc, NormalizationError):
            return RejectReason.SCHEMA_DRIFT
        rule = getattr(exc, "rule", "")
        # A missing mandatory field is reported as such, whatever the field is.
        if rule.endswith(".required") or rule.endswith(".empty"):
            return RejectReason.MISSING_REQUIRED_FIELD
        if rule.startswith("value"):
            return RejectReason.INVALID_NUMERIC_VALUE
        if rule.startswith("sensor_type"):
            return RejectReason.UNKNOWN_SENSOR_TYPE
        if rule.startswith("timestamp"):
            return RejectReason.INVALID_TIMESTAMP
        return RejectReason.MISSING_REQUIRED_FIELD

    def _normalize_payload(self, payload: Mapping[str, Any]) -> list[SensorReading]:
        """Expand one payload into zero or more canonical readings."""
        candidates = self._extract_candidates(payload)
        readings: list[SensorReading] = []
        for candidate in candidates:
            readings.append(self._build_reading(candidate))
        return readings

    def _extract_candidates(
        self,
        payload: Mapping[str, Any],
        context: Mapping[str, Any] | None = None,
    ) -> list[dict[str, Any]]:
        """Flatten a payload into one or more flat candidate dictionaries.

        Handles nested containers (``readings``/``values``/``metrics``), arrays of
        readings and wide rows containing several typed measurements.

        Field names are canonicalised up-front (aliases resolved), so every
        later stage works with a single vocabulary.

        Context fields (sensor id, machine id, timestamp) defined on the parent
        object are inherited by nested readings that do not define them.
        """
        flat: dict[str, Any] = {}
        nested_containers: list[Any] = []

        # Context inherited from the parent object takes lower precedence than
        # the values defined on this object itself.
        if context:
            for key, value in context.items():
                flat.setdefault(key, value)

        for key, value in payload.items():
            lowered = str(key).strip().lower()
            if lowered in ("readings", "values", "metrics", "measurements", "data", "payload"):
                nested_containers.append(value)
                continue
            if lowered in _IGNORED_KEYS:
                continue
            flat[_ALIAS_TO_FIELD.get(lowered, lowered)] = value

        candidates: list[dict[str, Any]] = []
        # Context propagated from the parent into nested readings.
        context = {
            key: flat[key]
            for key in ("sensor_id", "machine_id", "timestamp", "unit")
            if key in flat
        }

        # 1) Nested containers: either a list of readings or a mapping of
        #    type -> value (or type -> {value, timestamp, ...}).
        for container in nested_containers:
            if isinstance(container, list):
                for item in container:
                    if isinstance(item, Mapping):
                        candidates.extend(self._extract_candidates(item, context))
            elif isinstance(container, Mapping):
                flat.update(
                    {
                        _ALIAS_TO_FIELD.get(str(k).strip().lower(), str(k).strip().lower()): v
                        for k, v in container.items()
                    }
                )
            else:
                raise NormalizationError(
                    f"unsupported nested container type {type(container).__name__}"
                )

        # 2) Split off the typed columns (temperature / vibration / error code).
        #    They are removed from the flat mapping because they describe the
        #    measurement rather than the reading's context.
        typed: dict[str, Any] = {}
        for canonical in _TYPE_FROM_FIELD:
            if canonical in flat:
                raw_value = flat.pop(canonical)
                if raw_value is not None:
                    typed[canonical] = raw_value

        if "value" in flat:
            # 3) Long form: a single reading carrying an explicit value. A
            #    typed column, when present, only identifies the sensor type;
            #    the explicit value always wins over the typed measurement.
            candidate = dict(flat)
            if "sensor_type" not in candidate and typed:
                candidate["sensor_type"] = _TYPE_FROM_FIELD[next(iter(typed))].value
            candidates.append(candidate)
        elif typed:
            # 4) Wide form: one reading per typed column, sharing the context.
            shared = {k: v for k, v in flat.items() if k != "sensor_type"}
            for canonical, value in typed.items():
                candidate = dict(shared)
                candidate["value"] = value
                candidate["sensor_type"] = _TYPE_FROM_FIELD[canonical].value
                candidates.append(candidate)

        if not candidates:
            raise ContractViolation(
                "payload does not contain a recognizable reading", "payload.unrecognized"
            )
        return candidates

    def _build_reading(self, candidate: Mapping[str, Any]) -> SensorReading:
        """Validate and convert a flat candidate into a :class:`SensorReading`."""
        normalized = {_ALIAS_TO_FIELD.get(k, k): v for k, v in candidate.items()}

        sensor_id = self._require_text(normalized, "sensor_id")
        machine_id = self._require_text(normalized, "machine_id")

        sensor_type = self._resolve_sensor_type(normalized)
        sensor_contract = self.contract.contract_for(sensor_type)

        if "timestamp" not in normalized or normalized["timestamp"] is None:
            raise ContractViolation("timestamp is required", "timestamp.required")
        try:
            moment = parse_timestamp(normalized["timestamp"])
        except NormalizationError as exc:
            raise ContractViolation(str(exc), "timestamp.invalid") from exc

        if "value" not in normalized or normalized["value"] is None:
            raise ContractViolation("value is required", "value.required")
        raw_value = normalized["value"]
        value = self._coerce_number(raw_value)
        if value is None:
            raise ContractViolation(f"value {raw_value!r} is not a usable number", "value.not_numeric")

        unit, value = self._convert_unit(sensor_type, value, normalized.get("unit"))
        sensor_contract.validate_value(value)

        return SensorReading(
            sensor_id=sensor_id,
            machine_id=machine_id,
            sensor_type=sensor_type,
            timestamp=Timestamp(moment),
            value=float(value),
            unit=unit,
            source="",
            quality_flags=(),
        )

    @staticmethod
    def _require_text(normalized: Mapping[str, Any], field_name: str) -> str:
        if field_name not in normalized or normalized[field_name] is None:
            raise ContractViolation(f"{field_name} is required", f"{field_name}.required")
        value = normalized[field_name]
        if isinstance(value, bool) or not isinstance(value, (str, int)):
            raise ContractViolation(
                f"{field_name} must be a string, got {type(value).__name__}", f"{field_name}.type"
            )
        text = str(value).strip()
        if not text:
            raise ContractViolation(f"{field_name} must not be empty", f"{field_name}.empty")
        return text

    def _resolve_sensor_type(self, normalized: Mapping[str, Any]) -> SensorType:
        """Determine the sensor type of a candidate.

        Resolution order: an explicit ``sensor_type`` wins, then the physical
        unit (legacy exports frequently omit the type column), and finally the
        contract rejects the record as unresolvable.
        """
        raw_type = normalized.get("sensor_type")
        if raw_type is not None and str(raw_type).strip():
            try:
                return SensorType.from_raw(raw_type)
            except ContractViolation as exc:
                raise ContractViolation(str(exc), "sensor_type.unknown") from exc
        # Infer from the physical unit: legacy exports frequently omit the
        # sensor_type column while keeping the unit.
        raw_unit = normalized.get("unit")
        if isinstance(raw_unit, str) and raw_unit.strip():
            unit_key = (
                raw_unit.strip().lower().replace("°", "\u00b0").replace(" ", "_")
            )
            inferred = _TYPE_FROM_UNIT.get(unit_key)
            if inferred is not None:
                return inferred
        raise ContractViolation("sensor_type is required", "sensor_type.required")

    @staticmethod
    def _coerce_number(raw: Any) -> float | None:
        """Best-effort conversion of a raw value into a float.

        Returns ``None`` for sentinels, non-numeric strings, booleans and
        values that cannot be represented as a finite float.
        """
        if isinstance(raw, bool):
            return None
        if isinstance(raw, (int, float)):
            value = float(raw)
            return value if math.isfinite(value) else None
        if not isinstance(raw, str):
            return None
        text = raw.strip()
        if text.lower() in _SENTINELS:
            return None

        # Plain numeric text first: this must be attempted before any
        # unit-suffix stripping, otherwise "78.5" would truncate to "78".
        if _NUMERIC_RE.match(text):
            try:
                value = float(text)
            except ValueError:  # pragma: no cover - guarded by the regex
                return None
            return value if math.isfinite(value) else None

        # Fall back to stripping a trailing unit suffix such as "82.5C".
        match = re.match(r"^([+-]?(?:\d+\.?\d*|\.\d+)(?:[eE][+-]?\d+)?)\s*[^\d\s].*$", text)
        if not match:
            return None
        # The regex guarantees a parsable numeric prefix.
        value = float(match.group(1))
        return value if math.isfinite(value) else None

    def _convert_unit(
        self,
        sensor_type: SensorType,
        value: float,
        raw_unit: Any,
    ) -> tuple[str, float]:
        """Convert ``value`` into the canonical unit for ``sensor_type``."""
        canonical_unit = self.contract.contract_for(sensor_type).unit
        if raw_unit is None or not isinstance(raw_unit, str) or not raw_unit.strip():
            return canonical_unit, value
        key = raw_unit.strip().lower().replace("°", "\u00b0").replace(" ", "_")
        conversions = _UNIT_CONVERSIONS.get(sensor_type, {})
        if key not in conversions:
            return canonical_unit, value
        target_unit, factor, offset = conversions[key]
        return target_unit, value * factor + offset


def deduplicate(readings: Iterable[SensorReading]) -> tuple[list[SensorReading], list[SensorReading]]:
    """Split ``readings`` into (unique, duplicates).

    Identity is ``(machine_id, sensor_id, timestamp, sensor_type)``. The first
    occurrence wins, which keeps the result deterministic for replays.
    """
    seen: set[tuple[str, str, str, SensorType]] = set()
    unique: list[SensorReading] = []
    duplicates: list[SensorReading] = []
    for reading in readings:
        key = (
            reading.machine_id,
            reading.sensor_id,
            reading.timestamp.iso8601,
            reading.sensor_type,
        )
        if key in seen:
            duplicates.append(reading)
            continue
        seen.add(key)
        unique.append(reading)
    return unique, duplicates


def contract_for_reading(reading: SensorReading, contract: DataContract) -> SensorContract:
    """Convenience accessor returning the governing contract of a reading."""
    return contract.contract_for(reading.sensor_type)

"""Declarative data contracts used to validate incoming telemetry.

A :class:`DataContract` captures the agreed shape and physical plausibility
of a sensor reading. Contracts are intentionally data (not code) so they can
be versioned, shipped per plant line, and overridden per deployment.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Mapping

from .exceptions import ContractViolation
from .models import SensorType


@dataclass(frozen=True, slots=True)
class FieldSpec:
    """Specification of a single canonical field."""

    name: str
    required: bool = True
    aliases: tuple[str, ...] = ()
    type_hint: str = "string"


@dataclass(frozen=True, slots=True)
class SensorContract:
    """Per sensor-type contract: units, physical bounds and required fields."""

    sensor_type: SensorType
    unit: str
    min_value: float | None = None
    max_value: float | None = None
    integer_only: bool = False
    expected_interval_seconds: float | None = None
    fields: tuple[FieldSpec, ...] = ()

    def validate_value(self, value: float) -> None:
        """Validate a numeric reading against physical bounds.

        Raises
        ------
        ContractViolation
            If the value is non-finite, non-integral where required, or
            outside the configured physical range.
        """
        if value != value or value in (float("inf"), float("-inf")):  # NaN / infinity
            raise ContractViolation(f"value must be finite, got {value!r}", "value.finite")
        if self.integer_only and float(value) != int(value):
            raise ContractViolation(f"value must be integral, got {value!r}", "value.integer")
        if self.min_value is not None and value < self.min_value:
            raise ContractViolation(
                f"value {value} below physical minimum {self.min_value}", "value.min"
            )
        if self.max_value is not None and value > self.max_value:
            raise ContractViolation(
                f"value {value} above physical maximum {self.max_value}", "value.max"
            )

    def expected_fields(self) -> tuple[str, ...]:
        """Canonical field names that must be present for this contract."""
        return tuple(f.name for f in self.fields if f.required)


DEFAULT_FIELDS: tuple[FieldSpec, ...] = (
    FieldSpec("sensor_id", aliases=("sensor", "sensorId", "device_id", "deviceId", "id")),
    FieldSpec("machine_id", aliases=("machine", "machineId", "asset_id", "assetId", "asset")),
    FieldSpec("timestamp", aliases=("ts", "time", "event_time", "eventTime", "datetime", "dateTime")),
    FieldSpec("value", aliases=("reading", "val", "measurement", "reading_value", "readingValue")),
    FieldSpec("sensor_type", aliases=("type", "sensorType", "metric", "kind")),
    FieldSpec("unit", required=False, aliases=("units", "uom", "unit_of_measure")),
)

DEFAULT_CONTRACTS: Mapping[SensorType, SensorContract] = {
    SensorType.TEMPERATURE: SensorContract(
        sensor_type=SensorType.TEMPERATURE,
        unit="C",
        min_value=-90.0,
        max_value=400.0,
        expected_interval_seconds=60.0,
        fields=DEFAULT_FIELDS,
    ),
    SensorType.VIBRATION: SensorContract(
        sensor_type=SensorType.VIBRATION,
        unit="Hz",
        min_value=0.0,
        max_value=20000.0,
        expected_interval_seconds=60.0,
        fields=DEFAULT_FIELDS,
    ),
    SensorType.ERROR_CODE: SensorContract(
        sensor_type=SensorType.ERROR_CODE,
        unit="code",
        min_value=0.0,
        max_value=65535.0,
        integer_only=True,
        expected_interval_seconds=60.0,
        fields=DEFAULT_FIELDS,
    ),
}


@dataclass(frozen=True, slots=True)
class DataContract:
    """Aggregate contract describing the full ingestion schema."""

    contracts: Mapping[SensorType, SensorContract] = field(default_factory=lambda: dict(DEFAULT_CONTRACTS))
    allowed_machine_id_prefixes: tuple[str, ...] = ()
    max_records_per_batch: int = 1_000_000

    def contract_for(self, sensor_type: SensorType) -> SensorContract:
        """Return the contract governing ``sensor_type``.

        Raises
        ------
        ContractViolation
            If the sensor type is not covered by the contract set.
        """
        try:
            return self.contracts[sensor_type]
        except KeyError as exc:
            raise ContractViolation(
                f"no data contract defined for sensor type {sensor_type.value}", "contract.missing"
            ) from exc

    def resolve_alias(self, canonical: str, candidate: str) -> bool:
        """Whether ``candidate`` is an accepted alias for the canonical field."""
        contract = next(iter(self.contracts.values()), None)
        if contract is None:
            return False
        for spec in contract.fields:
            if spec.name == canonical:
                return candidate == spec.name or candidate in spec.aliases
        return candidate == canonical

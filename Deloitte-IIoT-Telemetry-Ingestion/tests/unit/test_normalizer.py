"""Unit tests for the normalization stage (schema drift, corruption, units)."""

from __future__ import annotations

from datetime import timezone

import pytest

from iiot_telemetry.application.normalizer import (
    NormalizationSettings,
    TelemetryNormalizer,
    contract_for_reading,
    deduplicate,
)
from iiot_telemetry.domain.contracts import DataContract, SensorContract
from iiot_telemetry.domain.exceptions import ContractViolation, NormalizationError
from iiot_telemetry.domain.models import RejectReason, SensorType


class TestCanonicalPayload:
    """The happy path: a well-formed payload becomes a canonical reading."""

    def test_long_form_payload_is_normalized(self, normalizer: TelemetryNormalizer) -> None:
        reading = normalizer.normalize(
            {
                "sensor_id": "TEMP-01",
                "machine_id": "PRESS-01",
                "sensor_type": "temperature",
                "timestamp": "2024-05-01T08:00:00Z",
                "value": 78.5,
                "unit": "C",
            }
        )
        assert reading.sensor_id == "TEMP-01"
        assert reading.machine_id == "PRESS-01"
        assert reading.sensor_type is SensorType.TEMPERATURE
        assert reading.value == 78.5
        assert reading.unit == "C"
        assert reading.timestamp.value.tzinfo is timezone.utc

    def test_wide_row_yields_one_reading_per_typed_column(
        self, normalizer: TelemetryNormalizer
    ) -> None:
        result = normalizer.normalize_batch(
            [
                {
                    "device_id": "MIX-01",
                    "machine_id": "LATHE-03",
                    "timestamp": "2024-05-01T08:00:00Z",
                    "temperature": 80.0,
                    "vibration": 12.5,
                    "error_code": 0,
                }
            ]
        )
        assert result.accepted_count == 3
        types = {r.sensor_type for r in result.readings}
        assert types == {SensorType.TEMPERATURE, SensorType.VIBRATION, SensorType.ERROR_CODE}

    def test_nested_readings_array_is_expanded(self, normalizer: TelemetryNormalizer) -> None:
        result = normalizer.normalize_batch(
            [
                {
                    "sensor_id": "TEMP-01",
                    "machine_id": "PRESS-01",
                    "readings": [
                        {
                            "sensor_type": "temperature",
                            "timestamp": "2024-05-01T08:00:00Z",
                            "value": 10.0,
                        },
                        {
                            "sensor_type": "vibration",
                            "timestamp": "2024-05-01T08:00:00Z",
                            "value": 3.0,
                        },
                    ],
                }
            ]
        )
        assert result.accepted_count == 2

    def test_nested_mapping_container_is_flattened(self, normalizer: TelemetryNormalizer) -> None:
        result = normalizer.normalize_batch(
            [
                {
                    "sensor_id": "TEMP-01",
                    "machine_id": "PRESS-01",
                    "data": {
                        "sensor_type": "temperature",
                        "timestamp": "2024-05-01T08:00:00Z",
                        "value": 42.0,
                    },
                }
            ]
        )
        assert result.accepted_count == 1
        assert result.readings[0].value == 42.0

    def test_metadata_fields_are_ignored(self, normalizer: TelemetryNormalizer) -> None:
        reading = normalizer.normalize(
            {
                "sensor_id": "TEMP-01",
                "machine_id": "PRESS-01",
                "sensor_type": "temperature",
                "timestamp": "2024-05-01T08:00:00Z",
                "value": 50.0,
                "plant": "Stuttgart",
                "firmware": "1.2.3",
                "battery": 88,
                "rssi": -60,
            }
        )
        assert reading.value == 50.0


class TestSchemaDrift:
    """Field renames and legacy aliases must not break ingestion."""

    @pytest.mark.parametrize(
        "sensor_key",
        ["sensor_id", "sensorId", "device_id", "deviceId", "device", "sensor", "id", "tag"],
    )
    def test_sensor_id_aliases(self, normalizer: TelemetryNormalizer, sensor_key: str) -> None:
        reading = normalizer.normalize(
            {
                sensor_key: "TEMP-01",
                "machine_id": "PRESS-01",
                "sensor_type": "temperature",
                "timestamp": "2024-05-01T08:00:00Z",
                "value": 10.0,
            }
        )
        assert reading.sensor_id == "TEMP-01"

    @pytest.mark.parametrize(
        "machine_key",
        ["machine_id", "machineId", "machine", "asset_id", "assetId", "asset", "equipment_id"],
    )
    def test_machine_id_aliases(self, normalizer: TelemetryNormalizer, machine_key: str) -> None:
        reading = normalizer.normalize(
            {
                "sensor_id": "TEMP-01",
                machine_key: "PRESS-01",
                "sensor_type": "temperature",
                "timestamp": "2024-05-01T08:00:00Z",
                "value": 10.0,
            }
        )
        assert reading.machine_id == "PRESS-01"

    @pytest.mark.parametrize(
        "time_key",
        ["timestamp", "ts", "time", "event_time", "eventTime", "datetime", "dateTime", "recorded_at"],
    )
    def test_timestamp_aliases(self, normalizer: TelemetryNormalizer, time_key: str) -> None:
        reading = normalizer.normalize(
            {
                "sensor_id": "TEMP-01",
                "machine_id": "PRESS-01",
                "sensor_type": "temperature",
                time_key: "2024-05-01T08:00:00Z",
                "value": 10.0,
            }
        )
        assert reading.timestamp.iso8601.startswith("2024-05-01T08:00:00")

    @pytest.mark.parametrize("value_key", ["value", "reading", "val", "measurement", "reading_value"])
    def test_value_aliases(self, normalizer: TelemetryNormalizer, value_key: str) -> None:
        reading = normalizer.normalize(
            {
                "sensor_id": "TEMP-01",
                "machine_id": "PRESS-01",
                "sensor_type": "temperature",
                "timestamp": "2024-05-01T08:00:00Z",
                value_key: 33.3,
            }
        )
        assert reading.value == 33.3

    @pytest.mark.parametrize("type_key", ["sensor_type", "sensorType", "type", "metric", "kind"])
    def test_sensor_type_aliases(self, normalizer: TelemetryNormalizer, type_key: str) -> None:
        reading = normalizer.normalize(
            {
                "sensor_id": "TEMP-01",
                "machine_id": "PRESS-01",
                type_key: "temperature",
                "timestamp": "2024-05-01T08:00:00Z",
                "value": 10.0,
            }
        )
        assert reading.sensor_type is SensorType.TEMPERATURE

    @pytest.mark.parametrize("unit_key", ["unit", "units", "uom", "unit_of_measure"])
    def test_unit_aliases(self, normalizer: TelemetryNormalizer, unit_key: str) -> None:
        reading = normalizer.normalize(
            {
                "sensor_id": "TEMP-01",
                "machine_id": "PRESS-01",
                "sensor_type": "temperature",
                "timestamp": "2024-05-01T08:00:00Z",
                "value": 10.0,
                unit_key: "C",
            }
        )
        assert reading.unit == "C"

    def test_field_names_are_case_insensitive(self, normalizer: TelemetryNormalizer) -> None:
        reading = normalizer.normalize(
            {
                "SENSOR_ID": "TEMP-01",
                "Machine_ID": "PRESS-01",
                "Sensor_Type": "Temperature",
                "Timestamp": "2024-05-01T08:00:00Z",
                "Value": 10.0,
            }
        )
        assert reading.sensor_id == "TEMP-01"

    def test_sensor_type_is_inferred_from_typed_column(
        self, normalizer: TelemetryNormalizer
    ) -> None:
        reading = normalizer.normalize(
            {
                "sensor_id": "TEMP-01",
                "machine_id": "PRESS-01",
                "timestamp": "2024-05-01T08:00:00Z",
                "temperature": 91.0,
            }
        )
        assert reading.sensor_type is SensorType.TEMPERATURE
        assert reading.value == 91.0

    def test_observed_fields_are_reported(self, normalizer: TelemetryNormalizer) -> None:
        result = normalizer.normalize_batch(
            [
                {
                    "sensor_id": "TEMP-01",
                    "machine_id": "PRESS-01",
                    "sensor_type": "temperature",
                    "timestamp": "2024-05-01T08:00:00Z",
                    "value": 10.0,
                }
            ]
        )
        assert "sensor_id" in result.observed_fields


class TestSensorTypeResolution:
    """Sensor type resolution and its error paths."""

    @pytest.mark.parametrize(
        ("raw", "expected"),
        [
            ("temperature", SensorType.TEMPERATURE),
            ("TEMP", SensorType.TEMPERATURE),
            ("Temperature-C", SensorType.TEMPERATURE),
            ("temp", SensorType.TEMPERATURE),
            ("vibration", SensorType.VIBRATION),
            ("VIB_HZ", SensorType.VIBRATION),
            ("frequency", SensorType.VIBRATION),
            ("error_code", SensorType.ERROR_CODE),
            ("ErrorCode", SensorType.ERROR_CODE),
            ("fault", SensorType.ERROR_CODE),
        ],
    )
    def test_aliases_resolve(
        self, normalizer: TelemetryNormalizer, raw: str, expected: SensorType
    ) -> None:
        reading = normalizer.normalize(
            {
                "sensor_id": "S-1",
                "machine_id": "M-1",
                "sensor_type": raw,
                "timestamp": "2024-05-01T08:00:00Z",
                "value": 1.0,
            }
        )
        assert reading.sensor_type is expected

    def test_unknown_sensor_type_is_rejected(self, normalizer: TelemetryNormalizer) -> None:
        result = normalizer.normalize_batch(
            [
                {
                    "sensor_id": "S-1",
                    "machine_id": "M-1",
                    "sensor_type": "pressure",
                    "timestamp": "2024-05-01T08:00:00Z",
                    "value": 1.0,
                }
            ]
        )
        assert result.rejected_count == 1
        assert result.rejected[0].reason is RejectReason.UNKNOWN_SENSOR_TYPE

    def test_missing_sensor_type_is_rejected(self, normalizer: TelemetryNormalizer) -> None:
        result = normalizer.normalize_batch(
            [
                {
                    "sensor_id": "S-1",
                    "machine_id": "M-1",
                    "timestamp": "2024-05-01T08:00:00Z",
                    "value": 1.0,
                }
            ]
        )
        assert result.rejected_count == 1


class TestCorruptValues:
    """Corrupted sensor readings must be quarantined, never crash the run."""

    @pytest.mark.parametrize(
        "bad_value",
        ["", "   ", "-", "--", "N/A", "na", "null", "None", "NaN", "unknown", "ERROR",
         "-999", "9999", "inf", "-inf", "not-a-number", "abc", True, None],
    )
    def test_sentinel_values_are_rejected(
        self, normalizer: TelemetryNormalizer, bad_value: object
    ) -> None:
        result = normalizer.normalize_batch(
            [
                {
                    "sensor_id": "TEMP-01",
                    "machine_id": "PRESS-01",
                    "sensor_type": "temperature",
                    "timestamp": "2024-05-01T08:00:00Z",
                    "value": bad_value,
                }
            ]
        )
        assert result.accepted_count == 0
        assert result.rejected_count == 1

    def test_numeric_string_is_accepted(self, normalizer: TelemetryNormalizer) -> None:
        reading = normalizer.normalize(
            {
                "sensor_id": "TEMP-01",
                "machine_id": "PRESS-01",
                "sensor_type": "temperature",
                "timestamp": "2024-05-01T08:00:00Z",
                "value": "78.5",
            }
        )
        assert reading.value == 78.5

    def test_value_with_unit_suffix_is_accepted(self, normalizer: TelemetryNormalizer) -> None:
        reading = normalizer.normalize(
            {
                "sensor_id": "TEMP-01",
                "machine_id": "PRESS-01",
                "sensor_type": "temperature",
                "timestamp": "2024-05-01T08:00:00Z",
                "value": "82.5C",
            }
        )
        assert reading.value == 82.5

    def test_scientific_notation_is_accepted(self, normalizer: TelemetryNormalizer) -> None:
        reading = normalizer.normalize(
            {
                "sensor_id": "TEMP-01",
                "machine_id": "PRESS-01",
                "sensor_type": "temperature",
                "timestamp": "2024-05-01T08:00:00Z",
                "value": "1.25e2",
            }
        )
        assert reading.value == 125.0

    def test_infinity_is_rejected(self, normalizer: TelemetryNormalizer) -> None:
        result = normalizer.normalize_batch(
            [
                {
                    "sensor_id": "TEMP-01",
                    "machine_id": "PRESS-01",
                    "sensor_type": "temperature",
                    "timestamp": "2024-05-01T08:00:00Z",
                    "value": float("inf"),
                }
            ]
        )
        assert result.rejected_count == 1

    def test_value_above_physical_maximum_is_rejected(
        self, normalizer: TelemetryNormalizer
    ) -> None:
        result = normalizer.normalize_batch(
            [
                {
                    "sensor_id": "TEMP-01",
                    "machine_id": "PRESS-01",
                    "sensor_type": "temperature",
                    "timestamp": "2024-05-01T08:00:00Z",
                    "value": 5000.0,
                }
            ]
        )
        assert result.rejected_count == 1
        assert "maximum" in result.rejected[0].detail

    def test_value_below_physical_minimum_is_rejected(
        self, normalizer: TelemetryNormalizer
    ) -> None:
        result = normalizer.normalize_batch(
            [
                {
                    "sensor_id": "TEMP-01",
                    "machine_id": "PRESS-01",
                    "sensor_type": "temperature",
                    "timestamp": "2024-05-01T08:00:00Z",
                    "value": -500.0,
                }
            ]
        )
        assert result.rejected_count == 1
        assert "minimum" in result.rejected[0].detail

    def test_negative_vibration_is_rejected(self, normalizer: TelemetryNormalizer) -> None:
        result = normalizer.normalize_batch(
            [
                {
                    "sensor_id": "VIB-01",
                    "machine_id": "PRESS-01",
                    "sensor_type": "vibration",
                    "timestamp": "2024-05-01T08:00:00Z",
                    "value": -1.0,
                }
            ]
        )
        assert result.rejected_count == 1

    def test_non_integral_error_code_is_rejected(self, normalizer: TelemetryNormalizer) -> None:
        result = normalizer.normalize_batch(
            [
                {
                    "sensor_id": "ERR-01",
                    "machine_id": "PRESS-01",
                    "sensor_type": "error_code",
                    "timestamp": "2024-05-01T08:00:00Z",
                    "value": 1.5,
                }
            ]
        )
        assert result.rejected_count == 1
        assert "integral" in result.rejected[0].detail

    def test_error_code_above_maximum_is_rejected(self, normalizer: TelemetryNormalizer) -> None:
        result = normalizer.normalize_batch(
            [
                {
                    "sensor_id": "ERR-01",
                    "machine_id": "PRESS-01",
                    "sensor_type": "error_code",
                    "timestamp": "2024-05-01T08:00:00Z",
                    "value": 99999,
                }
            ]
        )
        assert result.rejected_count == 1


class TestRequiredFields:
    """Missing mandatory fields are reported with a precise reason."""

    @pytest.mark.parametrize("field", ["sensor_id", "machine_id", "timestamp", "value"])
    def test_missing_required_field_is_rejected(
        self, normalizer: TelemetryNormalizer, field: str
    ) -> None:
        payload = {
            "sensor_id": "TEMP-01",
            "machine_id": "PRESS-01",
            "sensor_type": "temperature",
            "timestamp": "2024-05-01T08:00:00Z",
            "value": 10.0,
        }
        payload.pop(field)
        result = normalizer.normalize_batch([payload])
        assert result.rejected_count == 1
        assert result.rejected[0].reason is RejectReason.MISSING_REQUIRED_FIELD

    @pytest.mark.parametrize("field", ["sensor_id", "machine_id"])
    def test_blank_identifier_is_rejected(
        self, normalizer: TelemetryNormalizer, field: str
    ) -> None:
        payload = {
            "sensor_id": "TEMP-01",
            "machine_id": "PRESS-01",
            "sensor_type": "temperature",
            "timestamp": "2024-05-01T08:00:00Z",
            "value": 10.0,
        }
        payload[field] = "   "
        result = normalizer.normalize_batch([payload])
        assert result.rejected_count == 1

    def test_invalid_timestamp_is_rejected(self, normalizer: TelemetryNormalizer) -> None:
        result = normalizer.normalize_batch(
            [
                {
                    "sensor_id": "TEMP-01",
                    "machine_id": "PRESS-01",
                    "sensor_type": "temperature",
                    "timestamp": "yesterday-ish",
                    "value": 10.0,
                }
            ]
        )
        assert result.rejected_count == 1
        assert result.rejected[0].reason is RejectReason.INVALID_TIMESTAMP

    def test_non_mapping_payload_is_rejected(self, normalizer: TelemetryNormalizer) -> None:
        result = normalizer.normalize_batch(["not-a-mapping"])  # type: ignore[list-item]
        assert result.rejected_count == 1
        assert result.rejected[0].reason is RejectReason.SCHEMA_DRIFT

    def test_empty_payload_is_rejected(self, normalizer: TelemetryNormalizer) -> None:
        result = normalizer.normalize_batch([{}])
        assert result.rejected_count == 1
        assert result.rejected[0].reason is RejectReason.EMPTY_PAYLOAD

    def test_unrecognizable_payload_is_rejected(self, normalizer: TelemetryNormalizer) -> None:
        result = normalizer.normalize_batch([{"foo": "bar"}])
        assert result.rejected_count == 1
        assert result.rejected[0].reason is RejectReason.MISSING_REQUIRED_FIELD


class TestUnitConversion:
    """Unit normalization into the canonical unit per sensor type."""

    def test_fahrenheit_is_converted_to_celsius(self, normalizer: TelemetryNormalizer) -> None:
        reading = normalizer.normalize(
            {
                "sensor_id": "TEMP-01",
                "machine_id": "PRESS-01",
                "sensor_type": "temperature",
                "timestamp": "2024-05-01T08:00:00Z",
                "value": 212.0,
                "unit": "F",
            }
        )
        assert reading.value == pytest.approx(100.0)
        assert reading.unit == "C"

    def test_kelvin_is_converted_to_celsius(self, normalizer: TelemetryNormalizer) -> None:
        reading = normalizer.normalize(
            {
                "sensor_id": "TEMP-01",
                "machine_id": "PRESS-01",
                "sensor_type": "temperature",
                "timestamp": "2024-05-01T08:00:00Z",
                "value": 373.15,
                "unit": "K",
            }
        )
        assert reading.value == pytest.approx(100.0)

    def test_celsius_is_unchanged(self, normalizer: TelemetryNormalizer) -> None:
        reading = normalizer.normalize(
            {
                "sensor_id": "TEMP-01",
                "machine_id": "PRESS-01",
                "sensor_type": "temperature",
                "timestamp": "2024-05-01T08:00:00Z",
                "value": 100.0,
                "unit": "C",
            }
        )
        assert reading.value == 100.0

    def test_kilohertz_is_converted_to_hertz(self, normalizer: TelemetryNormalizer) -> None:
        reading = normalizer.normalize(
            {
                "sensor_id": "VIB-01",
                "machine_id": "PRESS-01",
                "sensor_type": "vibration",
                "timestamp": "2024-05-01T08:00:00Z",
                "value": 2.5,
                "unit": "kHz",
            }
        )
        assert reading.value == pytest.approx(2500.0)
        assert reading.unit == "Hz"

    def test_rpm_is_converted_to_hertz(self, normalizer: TelemetryNormalizer) -> None:
        reading = normalizer.normalize(
            {
                "sensor_id": "VIB-01",
                "machine_id": "PRESS-01",
                "sensor_type": "vibration",
                "timestamp": "2024-05-01T08:00:00Z",
                "value": 60.0,
                "unit": "rpm",
            }
        )
        assert reading.value == pytest.approx(1.0)

    def test_unknown_unit_keeps_canonical_unit(self, normalizer: TelemetryNormalizer) -> None:
        reading = normalizer.normalize(
            {
                "sensor_id": "TEMP-01",
                "machine_id": "PRESS-01",
                "sensor_type": "temperature",
                "timestamp": "2024-05-01T08:00:00Z",
                "value": 100.0,
                "unit": "fahrenheitish",
            }
        )
        assert reading.unit == "C"
        assert reading.value == 100.0

    def test_missing_unit_uses_canonical_unit(self, normalizer: TelemetryNormalizer) -> None:
        reading = normalizer.normalize(
            {
                "sensor_id": "VIB-01",
                "machine_id": "PRESS-01",
                "sensor_type": "vibration",
                "timestamp": "2024-05-01T08:00:00Z",
                "value": 10.0,
            }
        )
        assert reading.unit == "Hz"


class TestBatchBehaviour:
    """Batch-level behaviour of the normalizer."""

    def test_batch_exceeding_limit_raises(self) -> None:
        normalizer = TelemetryNormalizer(
            settings=NormalizationSettings(max_records_per_batch=2)
        )
        with pytest.raises(NormalizationError):
            normalizer.normalize_batch([{"a": 1}, {"b": 2}, {"c": 3}])

    def test_mixed_batch_keeps_valid_records(self, normalizer: TelemetryNormalizer) -> None:
        result = normalizer.normalize_batch(
            [
                {
                    "sensor_id": "TEMP-01",
                    "machine_id": "PRESS-01",
                    "sensor_type": "temperature",
                    "timestamp": "2024-05-01T08:00:00Z",
                    "value": 10.0,
                },
                {"garbage": True},
                {
                    "sensor_id": "TEMP-02",
                    "machine_id": "PRESS-01",
                    "sensor_type": "temperature",
                    "timestamp": "2024-05-01T08:01:00Z",
                    "value": 11.0,
                },
            ]
        )
        assert result.accepted_count == 2
        assert result.rejected_count == 1

    def test_rejected_record_keeps_source_and_index(self, normalizer: TelemetryNormalizer) -> None:
        result = normalizer.normalize_batch([{"garbage": True}], source="file.json")
        assert result.rejected[0].source == "file.json"
        assert result.rejected[0].record_index == 0
        assert result.rejected[0].to_dict()["reason"] == "missing_required_field"

    def test_normalize_single_rejects_multi_reading_payload(
        self, normalizer: TelemetryNormalizer
    ) -> None:
        with pytest.raises(NormalizationError):
            normalizer.normalize(
                {
                    "sensor_id": "MIX-01",
                    "machine_id": "M-1",
                    "timestamp": "2024-05-01T08:00:00Z",
                    "temperature": 1.0,
                    "vibration": 2.0,
                }
            )

    def test_unsupported_nested_container_is_rejected(
        self, normalizer: TelemetryNormalizer
    ) -> None:
        result = normalizer.normalize_batch(
            [{"sensor_id": "S-1", "machine_id": "M-1", "readings": 42}]
        )
        assert result.rejected_count == 1
        assert result.rejected[0].reason is RejectReason.SCHEMA_DRIFT

    def test_nested_list_with_non_mapping_items(self, normalizer: TelemetryNormalizer) -> None:
        result = normalizer.normalize_batch(
            [
                {
                    "sensor_id": "S-1",
                    "machine_id": "M-1",
                    "readings": [
                        "not-a-mapping",
                        {
                            "sensor_type": "temperature",
                            "timestamp": "2024-05-01T08:00:00Z",
                            "value": 10.0,
                        },
                    ],
                }
            ]
        )
        assert result.accepted_count == 1

    def test_typed_column_with_null_value_is_skipped(
        self, normalizer: TelemetryNormalizer
    ) -> None:
        # A null typed column carries no measurement; the explicit value wins.
        result = normalizer.normalize_batch(
            [
                {
                    "sensor_id": "S-1",
                    "machine_id": "M-1",
                    "sensor_type": "temperature",
                    "timestamp": "2024-05-01T08:00:00Z",
                    "value": 10.0,
                    "vibration": None,
                }
            ]
        )
        assert result.accepted_count == 1
        assert result.readings[0].sensor_type is SensorType.TEMPERATURE

    def test_typed_column_identifies_the_sensor_type_of_an_explicit_value(
        self, normalizer: TelemetryNormalizer
    ) -> None:
        # A long-form row carrying both a value and a typed column: the typed
        # column identifies the measurement type.
        result = normalizer.normalize_batch(
            [
                {
                    "sensor_id": "S-1",
                    "machine_id": "M-1",
                    "timestamp": "2024-05-01T08:00:00Z",
                    "value": 10.0,
                    "vibration": 12.0,
                }
            ]
        )
        assert result.accepted_count == 1
        assert result.readings[0].sensor_type is SensorType.VIBRATION

    def test_non_string_identifier_is_rejected(self, normalizer: TelemetryNormalizer) -> None:
        result = normalizer.normalize_batch(
            [
                {
                    "sensor_id": ["S-1"],
                    "machine_id": "M-1",
                    "sensor_type": "temperature",
                    "timestamp": "2024-05-01T08:00:00Z",
                    "value": 10.0,
                }
            ]
        )
        assert result.rejected_count == 1

    def test_non_string_value_type_is_rejected(self, normalizer: TelemetryNormalizer) -> None:
        result = normalizer.normalize_batch(
            [
                {
                    "sensor_id": "S-1",
                    "machine_id": "M-1",
                    "sensor_type": "temperature",
                    "timestamp": "2024-05-01T08:00:00Z",
                    "value": {"nested": 1},
                }
            ]
        )
        assert result.rejected_count == 1

    def test_unrecognised_unit_does_not_resolve_the_sensor_type(
        self, normalizer: TelemetryNormalizer
    ) -> None:
        result = normalizer.normalize_batch(
            [
                {
                    "sensor_id": "S-1",
                    "machine_id": "M-1",
                    "timestamp": "2024-05-01T08:00:00Z",
                    "value": 10.0,
                    "unit": "widgets",
                }
            ]
        )
        assert result.rejected_count == 1
        assert result.rejected[0].reason is RejectReason.MISSING_REQUIRED_FIELD


class TestDeduplicate:
    """Duplicate suppression."""

    def test_identical_readings_are_deduplicated(self, normalizer: TelemetryNormalizer) -> None:
        payload = {
            "sensor_id": "TEMP-01",
            "machine_id": "PRESS-01",
            "sensor_type": "temperature",
            "timestamp": "2024-05-01T08:00:00Z",
            "value": 10.0,
        }
        result = normalizer.normalize_batch([payload, dict(payload)])
        unique, duplicates = deduplicate(result.readings)
        assert len(unique) == 1
        assert len(duplicates) == 1

    def test_distinct_timestamps_are_kept(self, normalizer: TelemetryNormalizer) -> None:
        base = {
            "sensor_id": "TEMP-01",
            "machine_id": "PRESS-01",
            "sensor_type": "temperature",
            "value": 10.0,
        }
        result = normalizer.normalize_batch(
            [
                {**base, "timestamp": "2024-05-01T08:00:00Z"},
                {**base, "timestamp": "2024-05-01T08:01:00Z"},
            ]
        )
        unique, duplicates = deduplicate(result.readings)
        assert len(unique) == 2
        assert duplicates == []

    def test_different_sensor_types_are_not_duplicates(
        self, normalizer: TelemetryNormalizer
    ) -> None:
        base = {
            "sensor_id": "TEMP-01",
            "machine_id": "PRESS-01",
            "timestamp": "2024-05-01T08:00:00Z",
            "value": 10.0,
        }
        result = normalizer.normalize_batch(
            [
                {**base, "sensor_type": "temperature"},
                {**base, "sensor_type": "vibration"},
            ]
        )
        unique, duplicates = deduplicate(result.readings)
        assert len(unique) == 2
        assert duplicates == []


class TestContractHelpers:
    """Helpers around the data contract objects."""

    def test_contract_for_reading(self, normalizer: TelemetryNormalizer) -> None:
        reading = normalizer.normalize(
            {
                "sensor_id": "TEMP-01",
                "machine_id": "PRESS-01",
                "sensor_type": "temperature",
                "timestamp": "2024-05-01T08:00:00Z",
                "value": 10.0,
            }
        )
        contract = contract_for_reading(reading, normalizer.contract)
        assert contract.sensor_type is SensorType.TEMPERATURE

    def test_missing_contract_raises(self) -> None:
        contract = DataContract(contracts={})
        with pytest.raises(ContractViolation):
            contract.contract_for(SensorType.TEMPERATURE)

    def test_resolve_alias(self) -> None:
        contract = DataContract()
        assert contract.resolve_alias("sensor_id", "device_id") is True
        assert contract.resolve_alias("sensor_id", "unrelated") is False

    def test_resolve_alias_without_contracts(self) -> None:
        contract = DataContract(contracts={})
        assert contract.resolve_alias("sensor_id", "device_id") is False

    def test_expected_fields(self) -> None:
        contract = DataContract().contract_for(SensorType.TEMPERATURE)
        assert "sensor_id" in contract.expected_fields()

    def test_sensor_contract_validate_value_accepts_valid(self) -> None:
        contract = SensorContract(sensor_type=SensorType.TEMPERATURE, unit="C")
        contract.validate_value(100.0)

    def test_sensor_contract_validate_value_rejects_nan(self) -> None:
        contract = SensorContract(sensor_type=SensorType.TEMPERATURE, unit="C")
        with pytest.raises(ContractViolation):
            contract.validate_value(float("nan"))

    def test_sensor_contract_validate_value_rejects_infinity(self) -> None:
        contract = SensorContract(sensor_type=SensorType.TEMPERATURE, unit="C")
        with pytest.raises(ContractViolation):
            contract.validate_value(float("inf"))

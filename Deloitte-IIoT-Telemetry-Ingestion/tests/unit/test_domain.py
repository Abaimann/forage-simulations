"""Unit tests for the domain entities, value objects and contracts.

These exercise the invariants enforced by the domain layer itself, including
the defensive branches that protect the pipeline from malformed input.
"""

from __future__ import annotations

from datetime import datetime, timezone

import pytest

from iiot_telemetry.domain.contracts import DataContract, FieldSpec, SensorContract
from iiot_telemetry.domain.exceptions import ContractViolation
from iiot_telemetry.domain.models import (
    AnomalyFlag,
    DropoutEvent,
    HealthScore,
    PipelineReport,
    RejectReason,
    RejectedRecord,
    SensorReading,
    SensorType,
    Severity,
    Timestamp,
)


class TestSensorType:
    """Behaviour of the :class:`SensorType` enumeration."""

    def test_from_raw_accepts_an_enum_member(self) -> None:
        assert SensorType.from_raw(SensorType.TEMPERATURE) is SensorType.TEMPERATURE

    def test_from_raw_rejects_non_strings(self) -> None:
        with pytest.raises(ContractViolation):
            SensorType.from_raw(42)

    def test_from_raw_rejects_unknown_labels(self) -> None:
        with pytest.raises(ContractViolation):
            SensorType.from_raw("pressure")

    def test_from_raw_normalizes_case_and_separators(self) -> None:
        assert SensorType.from_raw(" Error-Code ") is SensorType.ERROR_CODE


class TestSeverity:
    """Behaviour of the :class:`Severity` enumeration."""

    @pytest.mark.parametrize(
        ("severity", "rank"),
        [(Severity.INFO, 0), (Severity.WARNING, 1), (Severity.CRITICAL, 2)],
    )
    def test_rank(self, severity: Severity, rank: int) -> None:
        assert severity.rank == rank


class TestTimestamp:
    """Invariants of the :class:`Timestamp` value object."""

    def test_requires_a_datetime(self) -> None:
        with pytest.raises(ContractViolation):
            Timestamp("2024-05-01")  # type: ignore[arg-type]

    def test_rejects_naive_datetimes(self) -> None:
        with pytest.raises(ContractViolation):
            Timestamp(datetime(2024, 5, 1, 8, 0, 0))

    def test_iso8601_rendering(self) -> None:
        stamp = Timestamp(datetime(2024, 5, 1, 8, 0, 0, tzinfo=timezone.utc))
        assert stamp.iso8601 == "2024-05-01T08:00:00+00:00"

    def test_epoch_seconds(self) -> None:
        stamp = Timestamp(datetime(2024, 5, 1, 8, 0, 0, tzinfo=timezone.utc))
        assert stamp.epoch_seconds == 1714550400.0

    def test_str_returns_the_iso_rendering(self) -> None:
        stamp = Timestamp(datetime(2024, 5, 1, 8, 0, 0, tzinfo=timezone.utc))
        assert str(stamp) == stamp.iso8601


class TestSensorReading:
    """Invariants of the :class:`SensorReading` entity."""

    def _reading(self, **overrides) -> SensorReading:
        payload = {
            "sensor_id": "TEMP-01",
            "machine_id": "PRESS-01",
            "sensor_type": SensorType.TEMPERATURE,
            "timestamp": Timestamp(datetime(2024, 5, 1, 8, 0, 0, tzinfo=timezone.utc)),
            "value": 80.0,
        }
        payload.update(overrides)
        return SensorReading(**payload)  # type: ignore[arg-type]

    def test_rejects_an_empty_sensor_id(self) -> None:
        with pytest.raises(ContractViolation):
            self._reading(sensor_id="  ")

    def test_rejects_an_empty_machine_id(self) -> None:
        with pytest.raises(ContractViolation):
            self._reading(machine_id="")

    def test_rejects_a_non_numeric_value(self) -> None:
        with pytest.raises(ContractViolation):
            self._reading(value="hot")  # type: ignore[arg-type]

    def test_rejects_a_boolean_value(self) -> None:
        with pytest.raises(ContractViolation):
            self._reading(value=True)  # type: ignore[arg-type]

    def test_key_combines_machine_and_sensor(self) -> None:
        assert self._reading().key == ("PRESS-01", "TEMP-01")

    def test_integer_values_are_accepted(self) -> None:
        reading = self._reading(value=42)
        assert reading.value == 42


class TestResultEntities:
    """Serialisation behaviour of the analytics result entities."""

    def test_anomaly_flag_to_dict(self, make_reading) -> None:
        flag = AnomalyFlag(
            reading=make_reading(),
            baseline=79.5,
            std_dev=1.25,
            z_score=4.2,
            moving_average=79.5,
            severity=Severity.WARNING,
            rule="sigma_3",
        )
        payload = flag.to_dict()
        assert payload["z_score"] == 4.2
        assert payload["severity"] == "warning"
        assert payload["rule"] == "sigma_3"

    def test_dropout_event_to_dict(self, make_reading) -> None:
        reading = make_reading()
        event = DropoutEvent(
            machine_id="PRESS-01",
            sensor_id="TEMP-01",
            sensor_type=SensorType.TEMPERATURE,
            last_seen=reading.timestamp,
            next_seen=reading.timestamp,
            gap_seconds=300.0,
        )
        payload = event.to_dict()
        assert payload["gap_seconds"] == 300.0
        assert payload["sensor_type"] == "temperature"

    def test_health_score_to_dict(self) -> None:
        score = HealthScore(
            machine_id="PRESS-01",
            score=87.5,
            status="healthy",
            factors={"anomaly": 0.1},
            reading_count=10,
            anomaly_count=1,
            dropout_count=0,
        )
        payload = score.to_dict()
        assert payload["score"] == 87.5
        assert payload["factors"]["anomaly"] == 0.1

    def test_rejected_record_to_dict(self) -> None:
        rejected = RejectedRecord(
            reason=RejectReason.DUPLICATE,
            detail="duplicate reading",
            source="file.json",
            record_index=7,
        )
        payload = rejected.to_dict()
        assert payload["reason"] == "duplicate"
        assert payload["record_index"] == 7

    def test_pipeline_report_to_dict(self) -> None:
        report = PipelineReport(
            records_ingested=5,
            records_rejected=2,
            anomalies_detected=1,
            dropouts_detected=0,
            machines=1,
            sensors=3,
        )
        payload = report.to_dict()
        assert payload["records_ingested"] == 5
        assert payload["rejected"] == []


class TestContracts:
    """Behaviour of the contract objects."""

    def test_field_spec_aliases(self) -> None:
        spec = FieldSpec("sensor_id", aliases=("device_id",))
        assert spec.aliases == ("device_id",)

    def test_optional_fields_are_excluded_from_expected_fields(self) -> None:
        contract = SensorContract(
            sensor_type=SensorType.TEMPERATURE,
            unit="C",
            fields=(FieldSpec("sensor_id"), FieldSpec("unit", required=False)),
        )
        assert contract.expected_fields() == ("sensor_id",)

    def test_resolve_alias_for_an_unknown_canonical_field(self) -> None:
        contract = DataContract()
        # "unknown_field" is not part of the contract, so only an exact match
        # is accepted.
        assert contract.resolve_alias("unknown_field", "unknown_field") is True
        assert contract.resolve_alias("unknown_field", "other") is False

    def test_resolve_alias_for_a_known_canonical_field(self) -> None:
        contract = DataContract()
        assert contract.resolve_alias("sensor_id", "device_id") is True
        assert contract.resolve_alias("sensor_id", "nonsense") is False

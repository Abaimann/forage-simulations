"""Ingestion pipeline orchestrator.

This is the application service that drives the full ETL flow:

.. code-block:: text

    source --> parse --> normalize --> validate --> enrich
                                                      |
                             sink <-- persist <-------+
                                            (report)

Design rules honoured here:

* **Single responsibility** - the orchestrator sequences steps; it does not
  implement parsing, validation or statistics itself.
* **Dependency inversion** - sources and sinks are injected via ports.
* **Fail isolation** - a malformed record is quarantined, never fatal.
* **Determinism** - readings are sorted before analytics so results do not
  depend on the order in which files happen to be processed.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Sequence

from ..adapters.parsers.registry import build_source
from ..domain.contracts import DataContract
from ..domain.exceptions import ParseError
from ..domain.models import (
    AnomalyFlag,
    DropoutEvent,
    PipelineReport,
    RejectReason,
    RejectedRecord,
    SensorReading,
)
from .analytics import (
    DropoutDetector,
    HealthScorerConfig,
    MachineHealthScorer,
    MovingAverage,
    MovingAverageConfig,
    SigmaAnomalyDetector,
    SigmaDetectorConfig,
)
from .normalizer import NormalizationSettings, TelemetryNormalizer, deduplicate
from .ports import IngestionSettings, SinkConfig, SourceConfig, TelemetrySink


@dataclass(frozen=True, slots=True)
class IngestionResult:
    """Complete outcome of an ingestion run."""

    readings: tuple[SensorReading, ...]
    anomalies: tuple[AnomalyFlag, ...]
    dropouts: tuple[DropoutEvent, ...]
    rejected: tuple[RejectedRecord, ...]
    report: PipelineReport

    @property
    def health_scores(self) -> tuple[object, ...]:
        """Health scores computed during the run."""
        return self.report.health_scores


class IngestionPipeline:
    """Orchestrates parsing, normalization, validation and analytics."""

    def __init__(
        self,
        settings: IngestionSettings | None = None,
        contract: DataContract | None = None,
        sink: TelemetrySink | None = None,
    ) -> None:
        self.settings = settings or IngestionSettings()
        self.contract = contract or DataContract()
        self.sink = sink
        self.normalizer = TelemetryNormalizer(
            contract=self.contract,
            settings=NormalizationSettings(
                max_records_per_batch=self.contract.max_records_per_batch
            ),
        )
        self.moving_average = MovingAverage(
            MovingAverageConfig(window=self.settings.moving_average_window)
        )
        self.detector = SigmaAnomalyDetector(
            SigmaDetectorConfig(
                sigma_threshold=self.settings.sigma_threshold,
                baseline_window=self.settings.baseline_window,
                min_baseline_samples=self.settings.min_baseline_samples,
            )
        )
        self.scorer = MachineHealthScorer(
            HealthScorerConfig(
                dropout_gap_factor=self.settings.dropout_gap_factor,
                expected_interval_seconds=self.settings.expected_interval_seconds,
            )
        )
        self.dropout_detector = DropoutDetector(
            HealthScorerConfig(
                dropout_gap_factor=self.settings.dropout_gap_factor,
                expected_interval_seconds=self.settings.expected_interval_seconds,
            )
        )

    # -- public API -------------------------------------------------------- #

    def run(self) -> IngestionResult:
        """Execute a full ingestion run over the configured sources."""
        readings: list[SensorReading] = []
        rejected: list[RejectedRecord] = []

        for source_config in self.settings.sources:
            readings.extend(self._ingest_source(source_config, rejected))

        if self.settings.dedupe:
            unique, duplicates = deduplicate(readings)
            for duplicate in duplicates:
                rejected.append(
                    RejectedRecord(
                        reason=RejectReason.DUPLICATE,
                        detail=(
                            f"duplicate of sensor={duplicate.sensor_id} "
                            f"at {duplicate.timestamp.iso8601}"
                        ),
                        source=duplicate.source,
                    )
                )
            readings = unique

        if self.settings.sort_readings:
            readings.sort(key=lambda r: (r.timestamp.value, r.machine_id, r.sensor_id))

        anomalies, dropouts = self._analyze(readings)
        health_scores = self.scorer.scores()

        report = PipelineReport(
            records_ingested=len(readings),
            records_rejected=len(rejected),
            anomalies_detected=len(anomalies),
            dropouts_detected=len(dropouts),
            machines=len({r.machine_id for r in readings}),
            sensors=len({r.key for r in readings}),
            rejected=tuple(rejected),
            health_scores=health_scores,
        )

        if self.sink is not None:
            self.sink.write_readings(readings)
            self.sink.write_anomalies(anomalies)
            self.sink.write_rejected(rejected)
            self.sink.write_report(report)

        return IngestionResult(
            readings=tuple(readings),
            anomalies=tuple(anomalies),
            dropouts=tuple(dropouts),
            rejected=tuple(rejected),
            report=report,
        )

    def run_with_files(
        self,
        sources: Sequence[SourceConfig],
        sink_config: SinkConfig | None = None,
    ) -> IngestionResult:
        """Convenience wrapper building the settings and running the pipeline."""
        from ..adapters.sinks.file_sink import FileTelemetrySink  # local import: adapter

        sink: TelemetrySink | None = self.sink
        if sink_config is not None and sink is None:
            sink = FileTelemetrySink(sink_config)
        self.settings = IngestionSettings(
            moving_average_window=self.settings.moving_average_window,
            sigma_threshold=self.settings.sigma_threshold,
            baseline_window=self.settings.baseline_window,
            min_baseline_samples=self.settings.min_baseline_samples,
            dropout_gap_factor=self.settings.dropout_gap_factor,
            expected_interval_seconds=self.settings.expected_interval_seconds,
            dedupe=self.settings.dedupe,
            sort_readings=self.settings.sort_readings,
            sources=tuple(sources),
            sink=sink_config,
            extra=self.settings.extra,
        )
        self.sink = sink
        return self.run()

    # -- internals --------------------------------------------------------- #

    def _ingest_source(
        self,
        source_config: SourceConfig,
        rejected: list[RejectedRecord],
    ) -> list[SensorReading]:
        """Read, normalize and validate a single source."""
        source = build_source(source_config)
        source_name = str(source_config.path)
        try:
            payloads = list(source.read(source_config))
        except ParseError as exc:
            rejected.append(
                RejectedRecord(
                    reason=RejectReason.MALFORMED_JSON
                    if source_config.format in ("json", "jsonl", "auto")
                    else RejectReason.MALFORMED_CSV,
                    detail=str(exc),
                    source=source_name,
                )
            )
            return []

        result = self.normalizer.normalize_batch(payloads, source=source_name)
        rejected.extend(result.rejected)

        readings: list[SensorReading] = []
        for reading in result.readings:
            readings.append(
                SensorReading(
                    sensor_id=reading.sensor_id,
                    machine_id=reading.machine_id,
                    sensor_type=reading.sensor_type,
                    timestamp=reading.timestamp,
                    value=reading.value,
                    unit=reading.unit,
                    source=source_name,
                    quality_flags=reading.quality_flags,
                )
            )
        return readings

    def _analyze(
        self,
        readings: Sequence[SensorReading],
    ) -> tuple[list[AnomalyFlag], list[DropoutEvent]]:
        """Run the analytics stage over time-ordered readings."""
        anomalies: list[AnomalyFlag] = []
        dropouts: list[DropoutEvent] = []

        for reading in readings:
            self.moving_average.update(reading.value)
            self.scorer.observe(reading)

            dropout = self.dropout_detector.observe(reading)
            if dropout is not None:
                dropouts.append(dropout)
                self.scorer.observe_dropout(dropout)

            anomaly = self.detector.evaluate(reading)
            if anomaly is not None:
                anomalies.append(anomaly)
                self.scorer.observe_anomaly(anomaly)

        return anomalies, dropouts

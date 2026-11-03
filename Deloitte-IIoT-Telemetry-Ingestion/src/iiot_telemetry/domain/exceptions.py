"""Domain-level exception hierarchy.

Every error raised by the pipeline derives from :class:`TelemetryError` so that
boundary adapters can distinguish expected, data-quality related failures
(rejected records) from genuine programming or infrastructure faults.
"""

from __future__ import annotations


class TelemetryError(Exception):
    """Base class for every error raised by the telemetry pipeline."""


class ConfigurationError(TelemetryError):
    """Raised when pipeline configuration is missing or internally inconsistent."""


class ParseError(TelemetryError):
    """Raised when a raw payload cannot be decoded into structured records.

    Parameters
    ----------
    message:
        Human readable description of the failure.
    source:
        Identifier of the origin (file name, stream id) for diagnostics.
    record_index:
        Zero-based index of the offending record within its source, when known.
    """

    def __init__(self, message: str, source: str = "<unknown>", record_index: int | None = None) -> None:
        self.source = source
        self.record_index = record_index
        location = f"{source}[{record_index}]" if record_index is not None else source
        super().__init__(f"{message} (source={location})")


class NormalizationError(TelemetryError):
    """Raised when a record cannot be normalized into the canonical telemetry model."""


class ContractViolation(TelemetryError):
    """Raised when a record violates the configured data contract."""

    def __init__(self, message: str, rule: str = "unknown") -> None:
        self.rule = rule
        super().__init__(f"{message} [rule={rule}]")


class AnalyticsError(TelemetryError):
    """Raised when an analytics computation cannot be performed."""

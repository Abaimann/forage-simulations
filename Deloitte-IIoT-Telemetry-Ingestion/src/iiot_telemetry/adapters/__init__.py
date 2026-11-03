"""Adapters connecting the application core to concrete file formats."""

from __future__ import annotations

from .parsers.csv_parser import CsvTelemetryParser
from .parsers.json_parser import JsonTelemetryParser
from .parsers.jsonl_parser import JsonlTelemetryParser
from .parsers.registry import build_source
from .sinks.file_sink import FileTelemetrySink
from .sinks.memory_sink import InMemoryTelemetrySink

__all__ = [
    "CsvTelemetryParser",
    "FileTelemetrySink",
    "InMemoryTelemetrySink",
    "JsonTelemetryParser",
    "JsonlTelemetryParser",
    "build_source",
]

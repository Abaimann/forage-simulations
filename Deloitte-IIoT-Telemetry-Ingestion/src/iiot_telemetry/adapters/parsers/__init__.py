"""Parser adapters for JSON, JSON Lines and CSV sources."""

from __future__ import annotations

from .csv_parser import CsvTelemetryParser
from .json_parser import JsonTelemetryParser
from .jsonl_parser import JsonlTelemetryParser
from .registry import build_source, detect_format

__all__ = [
    "CsvTelemetryParser",
    "JsonTelemetryParser",
    "JsonlTelemetryParser",
    "build_source",
    "detect_format",
]

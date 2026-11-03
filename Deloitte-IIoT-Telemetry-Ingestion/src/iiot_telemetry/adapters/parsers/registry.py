"""Parser registry: chooses the right reader for a source file."""

from __future__ import annotations

from pathlib import Path

from ...application.ports import SourceConfig, TelemetrySource
from .csv_parser import CsvTelemetryParser
from .json_parser import JsonTelemetryParser
from .jsonl_parser import JsonlTelemetryParser

#: File extension -> parser format.
_EXTENSION_MAP: dict[str, str] = {
    ".json": "json",
    ".jsonl": "jsonl",
    ".ndjson": "jsonl",
    ".csv": "csv",
    ".tsv": "csv",
    ".txt": "csv",
}


def detect_format(path: Path) -> str:
    """Infer the payload format of ``path`` from its extension and content.

    Files with an unknown extension are sniffed: a leading ``[`` or ``{``
    indicates JSON, otherwise the file is treated as CSV.
    """
    suffix = path.suffix.lower()
    if suffix in _EXTENSION_MAP:
        return _EXTENSION_MAP[suffix]

    try:
        with path.open("r", encoding="utf-8", errors="replace") as handle:
            head = handle.read(2048)
    except OSError:
        return "csv"

    stripped = head.lstrip()
    if stripped.startswith(("[", "{")):
        # A single JSON document is JSON; several objects on separate lines
        # are JSON Lines.
        lines = [line for line in stripped.splitlines() if line.strip()]
        if len(lines) > 1 and all(line.lstrip().startswith("{") for line in lines):
            return "jsonl"
        return "json"
    return "csv"


def build_source(config: SourceConfig) -> TelemetrySource:
    """Return the parser matching ``config``.

    Raises
    ------
    ValueError
        If the requested format has no registered parser.
    """
    fmt = config.format
    if fmt == "auto":
        fmt = detect_format(Path(config.path))
    if fmt == "json":
        return JsonTelemetryParser()
    if fmt == "jsonl":
        return JsonlTelemetryParser()
    if fmt == "csv":
        return CsvTelemetryParser()
    raise ValueError(f"no parser registered for format {fmt!r}")

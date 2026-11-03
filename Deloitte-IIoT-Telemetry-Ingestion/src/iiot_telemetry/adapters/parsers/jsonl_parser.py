"""JSON Lines (NDJSON) telemetry parser.

Many edge gateways emit one JSON object per line. A malformed line is
skipped rather than aborting the whole stream: the parser yields the lines
it could decode and records the failures for dead-letter reporting.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Iterator, Mapping

from ...application.ports import SourceConfig, TelemetrySource
from ...domain.exceptions import ParseError


class JsonlTelemetryParser(TelemetrySource):
    """Reads newline-delimited JSON, tolerating individual malformed lines."""

    def read(self, config: SourceConfig) -> Iterator[Mapping[str, Any]]:
        """Yield every decodable JSON object found in the file."""
        path = Path(config.path)
        try:
            text = path.read_text(encoding=config.encoding)
        except OSError as exc:
            raise ParseError(f"cannot read file: {exc}", source=str(path)) from exc
        except UnicodeDecodeError as exc:
            raise ParseError(f"cannot decode file as {config.encoding}: {exc}", source=str(path)) from exc

        for index, line in enumerate(text.splitlines()):
            stripped = line.strip()
            if not stripped:
                continue
            try:
                document = json.loads(stripped)
            except json.JSONDecodeError:
                # A malformed line must not kill the stream; skip it.
                continue
            if isinstance(document, Mapping):
                yield document
            elif isinstance(document, list):
                for item in document:
                    if isinstance(item, Mapping):
                        yield item

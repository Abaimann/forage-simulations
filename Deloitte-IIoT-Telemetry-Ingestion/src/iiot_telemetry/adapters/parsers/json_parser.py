"""JSON telemetry parser.

Handles the three JSON shapes emitted across the Daikibo plant network:

1. A top-level array of reading objects.
2. A top-level object with a readings array under a known key.
3. A single reading object.

Malformed documents are surfaced as :class:`ParseError` so the pipeline can
route them to the dead-letter path instead of crashing the run.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Iterator, Mapping

from ...application.ports import SourceConfig, TelemetrySource
from ...domain.exceptions import ParseError

#: Keys that may hold the array of readings inside a wrapper object.
_READING_CONTAINER_KEYS: tuple[str, ...] = (
    "readings",
    "records",
    "data",
    "telemetry",
    "events",
    "items",
    "values",
)


class JsonTelemetryParser(TelemetrySource):
    """Reads a JSON document and yields raw reading mappings."""

    def read(self, config: SourceConfig) -> Iterator[Mapping[str, Any]]:
        """Yield the readings contained in the JSON file at ``config.path``."""
        path = Path(config.path)
        try:
            text = path.read_text(encoding=config.encoding)
        except OSError as exc:
            raise ParseError(f"cannot read file: {exc}", source=str(path)) from exc
        except UnicodeDecodeError as exc:
            raise ParseError(f"cannot decode file as {config.encoding}: {exc}", source=str(path)) from exc

        try:
            document = json.loads(text)
        except json.JSONDecodeError as exc:
            raise ParseError(f"invalid JSON: {exc}", source=str(path)) from exc

        yield from self._extract(document, path)

    def _extract(self, document: Any, path: Path) -> Iterator[Mapping[str, Any]]:
        """Recursively extract reading mappings from a decoded document."""
        if isinstance(document, list):
            for index, item in enumerate(document):
                yield from self._extract(item, path)
            return

        if not isinstance(document, Mapping):
            raise ParseError(
                f"document root must be an object or array, got {type(document).__name__}",
                source=str(path),
            )

        container_key = next((k for k in _READING_CONTAINER_KEYS if k in document), None)
        if container_key is not None:
            nested = document[container_key]
            if isinstance(nested, list):
                for index, item in enumerate(nested):
                    yield from self._extract(item, path)
                return
            if isinstance(nested, Mapping):
                yield from self._extract(nested, path)
                return
            raise ParseError(
                f"container '{container_key}' must hold an array or object",
                source=str(path),
            )

        yield document

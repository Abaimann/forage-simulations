"""CSV adapters.

The reader and the writer are the only components of the pipeline that know
that the source data lives in CSV files.  They implement the
:class:`~social_buzz_analytics.application.ports.DatasetReader` and
:class:`~social_buzz_analytics.application.ports.ReportWriter` ports.
"""

from __future__ import annotations

import csv
import json
from collections.abc import Iterator, Mapping, Sequence
from pathlib import Path
from typing import Any

from ..application.ports import DatasetReader, ReportWriter
from ..domain.exceptions import IngestError

__all__ = ["CsvDatasetReader", "CsvReportWriter"]


class CsvDatasetReader(DatasetReader):
    """Reads a raw dataset from a CSV file.

    The reader is defensive by design: a malformed file raises
    :class:`~social_buzz_analytics.domain.exceptions.IngestError` rather
    than propagating a low-level ``csv`` or ``UnicodeDecodeError``.
    """

    def __init__(self, encoding: str = "utf-8-sig", delimiter: str = ",") -> None:
        """Initialize the reader.

        Parameters
        ----------
        encoding:
            The text encoding of the file.  ``utf-8-sig`` transparently
            strips the byte-order mark that Excel adds to CSV exports.
        delimiter:
            The field delimiter of the file.
        """
        self._encoding = encoding
        self._delimiter = delimiter

    def read(self, path: Path) -> Iterator[Mapping[str, Any]]:
        """Yield the raw rows of the CSV file located at ``path``.

        Parameters
        ----------
        path:
            The path of the CSV file.

        Yields
        ------
        Mapping[str, Any]
            One mapping per data row; missing trailing fields are filled
            with an empty string.

        Raises
        ------
        IngestError
            If the file cannot be opened or decoded.
        """
        try:
            handle = path.open("r", encoding=self._encoding, newline="")
        except OSError as exc:
            raise IngestError(f"cannot open {path}: {exc}") from exc

        with handle:
            try:
                reader = csv.DictReader(handle, delimiter=self._delimiter)
                if reader.fieldnames is None:
                    raise IngestError(f"{path} has no header row")
                for row in reader:
                    yield {
                        (key or "").strip(): ("" if value is None else value)
                        for key, value in row.items()
                        if key is not None
                    }
            except UnicodeDecodeError as exc:
                raise IngestError(f"{path} is not valid {self._encoding}: {exc}") from exc
            except csv.Error as exc:
                raise IngestError(f"{path} is not a valid CSV file: {exc}") from exc


class CsvReportWriter(ReportWriter):
    """Writes the analytical summaries as CSV and JSON files."""

    def __init__(self, output_dir: Path, encoding: str = "utf-8") -> None:
        """Initialize the writer.

        Parameters
        ----------
        output_dir:
            The directory receiving the artifacts.  It is created when it
            does not exist yet.
        encoding:
            The text encoding of the written files.
        """
        self._output_dir = Path(output_dir)
        self._encoding = encoding

    @property
    def output_dir(self) -> Path:
        """The directory receiving the artifacts."""
        return self._output_dir

    def write_csv(self, name: str, rows: Sequence[Mapping[str, Any]]) -> Path:
        """Write ``rows`` as a CSV file.

        The header is derived from the keys of the first row; when the
        collection is empty, an empty file is written so that downstream
        consumers always find the artifact.

        Parameters
        ----------
        name:
            File name of the artifact.
        rows:
            The rows to persist.

        Returns
        -------
        Path
            The path of the written file.
        """
        self._output_dir.mkdir(parents=True, exist_ok=True)
        target = self._output_dir / name
        if not rows:
            target.write_text("", encoding=self._encoding)
            return target

        fieldnames: list[str] = []
        for row in rows:
            for key in row:
                if key not in fieldnames:
                    fieldnames.append(key)

        with target.open("w", encoding=self._encoding, newline="") as handle:
            writer = csv.DictWriter(handle, fieldnames=fieldnames, extrasaction="ignore")
            writer.writeheader()
            for row in rows:
                writer.writerow({key: _csv_value(row.get(key)) for key in fieldnames})
        return target

    def write_json(self, name: str, payload: Mapping[str, Any]) -> Path:
        """Write ``payload`` as a pretty-printed JSON file.

        Parameters
        ----------
        name:
            File name of the artifact.
        payload:
            The JSON-serializable payload.

        Returns
        -------
        Path
            The path of the written file.
        """
        self._output_dir.mkdir(parents=True, exist_ok=True)
        target = self._output_dir / name
        target.write_text(
            json.dumps(payload, indent=2, sort_keys=False, default=str),
            encoding=self._encoding,
        )
        return target


def _csv_value(value: Any) -> Any:
    """Convert a value into something the CSV writer can serialize."""
    if value is None:
        return ""
    if isinstance(value, bool):
        return "true" if value else "false"
    if isinstance(value, (int, float, str)):
        return value
    return str(value)

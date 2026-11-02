"""Adapters that publish aggregated rows into sinks.

Two sinks are provided:

* :class:`PerspectiveTableSink` -- writes rows into a ``perspective`` table
  so that the grid can be visualised in Jupyter/VS Code or served to a
  browser over WebSocket.
* :class:`MemorySink` -- collects rows in memory, used by tests and by the
  CLI when Perspective is not available.
"""

from __future__ import annotations

from typing import Any, Iterable, Protocol, runtime_checkable

from ..core.models import GRID_FIELDS, GridRow

#: Schema of the Perspective grid.
PERSPECTIVE_SCHEMA: dict[str, str] = {
    "stock": "string",
    "kind": "string",
    "price": "float",
    "ratio": "float",
    "upper_bound": "float",
    "lower_bound": "float",
    "trigger_alert": "boolean",
    "timestamp": "datetime",
}


@runtime_checkable
class RowSink(Protocol):
    """Sink receiving aggregated rows."""

    def write(self, rows: Iterable[GridRow]) -> int:
        """Persist *rows* and return the number of rows written."""
        ...

    def close(self) -> None:
        """Release any resource held by the sink."""
        ...


class MemorySink:
    """In-memory sink collecting every row it receives."""

    def __init__(self) -> None:
        self._rows: list[GridRow] = []

    @property
    def rows(self) -> list[GridRow]:
        """A copy of the collected rows."""
        return list(self._rows)

    def write(self, rows: Iterable[GridRow]) -> int:
        """Append *rows* to the internal buffer."""
        batch = list(rows)
        self._rows.extend(batch)
        return len(batch)

    def alerts(self) -> list[GridRow]:
        """Return only the rows that triggered an alert."""
        return [row for row in self._rows if row.trigger_alert]

    def clear(self) -> None:
        """Drop every buffered row."""
        self._rows.clear()

    def close(self) -> None:
        """No-op; the sink holds no external resource."""
        return None


class PerspectiveTableSink:
    """Writes rows into a live ``perspective`` table.

    Parameters
    ----------
    table:
        An existing ``perspective.Table`` instance.
    """

    def __init__(self, table: Any) -> None:
        self._table = table
        self._written = 0

    @classmethod
    def create(
        cls,
        name: str = "quotes",
        schema: dict[str, str] | None = None,
        server: Any | None = None,
    ) -> "PerspectiveTableSink":
        """Create a brand new table (and a Perspective server if needed).

        The Perspective WASM engine is imported lazily so that the rest of the
        package (and its unit tests) keep working when the optional
        dependency is not installed.
        """
        try:
            import perspective  # noqa: PLC0415  (optional dependency)
        except ImportError as exc:  # pragma: no cover - depends on environment
            raise RuntimeError(
                "perspective-python is required for the Perspective sink; "
                "install it with `pip install perspective-python`"
            ) from exc

        resolved_schema = dict(schema or PERSPECTIVE_SCHEMA)
        if server is None:
            server = perspective.Server()
        client = server.new_local_client()
        table = client.table(resolved_schema, name=name)
        return cls(table)

    @property
    def table(self) -> Any:
        """The underlying Perspective table."""
        return self._table

    @property
    def written(self) -> int:
        """Total number of rows written so far."""
        return self._written

    def write(self, rows: Iterable[GridRow]) -> int:
        """Push *rows* into the Perspective table."""
        batch = list(rows)
        if not batch:
            return 0
        payload = [row.to_dict() for row in batch]
        self._table.update(payload)
        self._written += len(payload)
        return len(payload)

    def snapshot(self) -> dict[str, list[Any]]:
        """Return the current table content as a column oriented mapping."""
        return self._table.view().to_columns()

    def close(self) -> None:
        """Remove the table from its Perspective server."""
        remove = getattr(self._table, "remove", None)
        if callable(remove):
            try:
                remove()
            except Exception:  # pragma: no cover - best effort cleanup
                pass


def rows_to_records(rows: Iterable[GridRow]) -> list[dict[str, Any]]:
    """Convert rows into plain dictionaries following :data:`GRID_FIELDS`."""
    return [{field: row.to_dict()[field] for field in GRID_FIELDS} for row in rows]

"""Allow ``python -m iiot_telemetry`` execution.

The module is intentionally a two-line shim around the CLI entry point; the
``if __name__ == "__main__"`` guard is excluded from coverage because the
behaviour it guards is covered through :func:`iiot_telemetry.cli.main`.
"""

from __future__ import annotations

from .cli import main

if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())

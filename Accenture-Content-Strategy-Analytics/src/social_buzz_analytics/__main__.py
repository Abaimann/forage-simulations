"""Allow the package to be executed with ``python -m social_buzz_analytics``."""

from __future__ import annotations

from .cli import main

if __name__ == "__main__":
    raise SystemExit(main())

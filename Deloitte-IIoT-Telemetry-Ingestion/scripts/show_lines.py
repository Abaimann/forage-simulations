"""Print source lines flagged as uncovered by coverage, with line numbers."""

from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def main() -> None:
    """Show the requested source lines."""
    for spec in sys.argv[1:]:
        path_part, _, ranges = spec.partition("=")
        path = ROOT / path_part
        lines = path.read_text(encoding="utf-8").splitlines()
        print(f"--- {path_part} ---")
        for chunk in ranges.split(","):
            if "-" in chunk:
                start, end = chunk.split("-")
                start, end = int(start), int(end)
            else:
                start = end = int(chunk)
            for number in range(start, end + 1):
                if 1 <= number <= len(lines):
                    print(f"{number:4d}| {lines[number - 1]}")


if __name__ == "__main__":
    main()

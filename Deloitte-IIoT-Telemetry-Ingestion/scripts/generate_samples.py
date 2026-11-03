"""Generate the deterministic example payloads shipped in ``examples/``.

Run with::

    python scripts/generate_samples.py

The generated files intentionally reproduce the messiness seen in the field:
schema drift, mixed timestamp formats, sentinel values and a missing block
that triggers dropout detection.
"""

from __future__ import annotations

import csv
import json
import math
from datetime import datetime, timedelta, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
EXAMPLES = ROOT / "examples"

BASE = datetime(2024, 5, 1, 8, 0, 0, tzinfo=timezone.utc)


def _temp(index: int) -> float:
    """Deterministic temperature profile with a thermal excursion."""
    drift = 78.0 + 2.0 * math.sin(index / 6.0)
    if index == 40:
        return 121.5  # runaway bearing -> 3-sigma anomaly
    if index == 41:
        return 96.0
    return round(drift, 3)


def _vibration(index: int) -> float:
    """Deterministic vibration profile."""
    return round(12.0 + 1.5 * math.sin(index / 4.0), 3)


def build_plant_a_json() -> list[dict]:
    """Plant A: modern wrapper JSON with ISO-8601 Z timestamps."""
    records = []
    for i in range(60):
        ts = (BASE + timedelta(minutes=i)).isoformat().replace("+00:00", "Z")
        records.append(
            {
                "sensor_id": f"TEMP-A{i % 3 + 1:02d}",
                "machine_id": "PRESS-01",
                "sensor_type": "temperature",
                "timestamp": ts,
                "value": _temp(i),
                "unit": "C",
                "plant": "Stuttgart",
            }
        )
    return records


def build_plant_b_rows() -> list[dict]:
    """Plant B: legacy CSV headers, epoch seconds, drift and sentinels."""
    rows = []
    for i in range(60):
        ts = int((BASE + timedelta(minutes=i)).timestamp())
        rows.append(
            {
                "DeviceID": f"VIB-B{i % 2 + 1:02d}",
                "AssetID": "CONV-07",
                "eventTime": ts,
                "reading": _vibration(i),
                "units": "Hz",
                "plant": "Monterrey",
            }
        )
    # Schema drift: a renamed column for the last block of records.
    for i in range(60, 70):
        ts = int((BASE + timedelta(minutes=i)).timestamp())
        rows.append(
            {
                "sensor": f"VIB-B{i % 2 + 1:02d}",
                "machine": "CONV-07",
                "ts": ts,
                "val": _vibration(i),
                "unit": "Hz",
            }
        )
    return rows


def build_plant_c_jsonl() -> list[str]:
    """Plant C: NDJSON wide rows mixing temperature and error code."""
    lines = []
    for i in range(60):
        ts = (BASE + timedelta(minutes=i)).isoformat()
        error_code = 0
        if i in (25, 26):
            error_code = 404
        lines.append(
            json.dumps(
                {
                    "device_id": f"MIX-C{i % 2 + 1:02d}",
                    "machine_id": "LATHE-03",
                    "timestamp": ts,
                    "temperature": _temp(i),
                    "error_code": error_code,
                    "site": "Osaka",
                }
            )
        )
    return lines


def main() -> None:
    """Write all example files."""
    EXAMPLES.mkdir(parents=True, exist_ok=True)

    plant_a = build_plant_a_json()
    (EXAMPLES / "plant_a_readings.json").write_text(
        json.dumps({"plant": "Stuttgart", "readings": plant_a}, indent=2) + "\n",
        encoding="utf-8",
    )

    plant_b = build_plant_b_rows()
    headers = [
        "DeviceID",
        "AssetID",
        "eventTime",
        "reading",
        "units",
        "plant",
        "sensor",
        "machine",
        "ts",
        "val",
        "unit",
    ]
    with (EXAMPLES / "plant_b_legacy.csv").open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=headers)
        writer.writeheader()
        for row in plant_b:
            writer.writerow({key: row.get(key, "") for key in headers})

    plant_c = build_plant_c_jsonl()
    (EXAMPLES / "plant_c_stream.jsonl").write_text("\n".join(plant_c) + "\n", encoding="utf-8")

    print(f"wrote examples to {EXAMPLES}")


if __name__ == "__main__":
    main()

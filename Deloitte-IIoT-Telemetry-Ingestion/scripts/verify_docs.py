"""Verify that the behaviours documented in README.md actually hold.

This script is a documentation audit: it exercises the exact examples and
claims stated in the README so that the documentation cannot drift away from
the implementation.
"""

from __future__ import annotations

import json
import sys
import tempfile
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from iiot_telemetry import (  # noqa: E402
    DataContract,
    IngestionPipeline,
    IngestionSettings,
    SinkConfig,
    SourceConfig,
    TelemetryNormalizer,
    parse_timestamp,
)

FAILURES: list[str] = []


def check(label: str, condition: bool, detail: str = "") -> None:
    """Record the outcome of a single documentation claim."""
    if condition:
        print(f"  OK   {label}")
    else:
        FAILURES.append(f"{label}: {detail}")
        print(f"  FAIL {label} {detail}")


def section(title: str) -> None:
    """Print a section header."""
    print(f"\n== {title} ==")


def main() -> None:
    """Run every documentation check."""
    root = Path(__file__).resolve().parents[1]

    section("README 5.4 / 10.4 - library usage example")
    settings = IngestionSettings(
        sources=(SourceConfig(path=root / "examples/plant_a_readings.json"),),
        sigma_threshold=3.0,
        baseline_window=50,
        min_baseline_samples=10,
    )
    pipeline = IngestionPipeline(settings=settings)
    result = pipeline.run()
    check("records_ingested == 60", result.report.records_ingested == 60,
          f"got {result.report.records_ingested}")
    check("anomalies_detected >= 1", result.report.anomalies_detected >= 1,
          f"got {result.report.anomalies_detected}")
    check("anomalies expose to_dict()", all(isinstance(a.to_dict(), dict) for a in result.anomalies))

    section("README 7.2 - timestamp table")
    cases = [
        ("2024-05-01T08:00:00Z", (2024, 5, 1, 8, 0, 0)),
        ("2024-05-01T10:00:00+02:00", (2024, 5, 1, 8, 0, 0)),
        ("2024-05-01 08:00:00", (2024, 5, 1, 8, 0, 0)),
        ("1714550400", (2024, 5, 1, 8, 0, 0)),
        ("1714550400000", (2024, 5, 1, 8, 0, 0)),
        ("1714550400000000", (2024, 5, 1, 8, 0, 0)),
        ("1714550400000000000", (2024, 5, 1, 8, 0, 0)),
        ("2024/05/01", (2024, 5, 1, 0, 0, 0)),
        ("01/05/24", (2024, 5, 1, 0, 0, 0)),
    ]
    for raw, expected in cases:
        got = parse_timestamp(raw)
        check(f"parse {raw!r}", (got.year, got.month, got.day, got.hour, got.minute, got.second) == expected,
              f"got {got.isoformat()}")
    check("naive timestamps are UTC", parse_timestamp("2024-05-01 08:00:00").tzinfo is timezone.utc)

    section("README 7.4 - unit conversions")
    normalizer = TelemetryNormalizer()

    def norm(**kw):
        payload = {
            "sensor_id": "S", "machine_id": "M", "sensor_type": "temperature",
            "timestamp": "2024-05-01T08:00:00Z", "value": 0.0,
        }
        payload.update(kw)
        return normalizer.normalize(payload)

    check("C = (F - 32) * 5/9", abs(norm(value=212.0, unit="F").value - 100.0) < 1e-9,
          str(norm(value=212.0, unit="F").value))
    check("C = K - 273.15", abs(norm(value=373.15, unit="K").value - 100.0) < 1e-9,
          str(norm(value=373.15, unit="K").value))
    vib = normalizer.normalize({
        "sensor_id": "S", "machine_id": "M", "sensor_type": "vibration",
        "timestamp": "2024-05-01T08:00:00Z", "value": 2.5, "unit": "kHz",
    })
    check("Hz = kHz * 1000", abs(vib.value - 2500.0) < 1e-9, str(vib.value))
    rpm = normalizer.normalize({
        "sensor_id": "S", "machine_id": "M", "sensor_type": "vibration",
        "timestamp": "2024-05-01T08:00:00Z", "value": 60.0, "unit": "rpm",
    })
    check("Hz = rpm / 60", abs(rpm.value - 1.0) < 1e-9, str(rpm.value))

    section("README 7.3 - sentinels rejected")
    for sentinel in ("", "-", "--", "N/A", "na", "null", "none", "nil", "NaN",
                     "unknown", "error", "err", "timeout", "disconnected",
                     "offline", "-999", "-9999", "999", "9999", "inf", "-inf"):
        res = normalizer.normalize_batch([{
            "sensor_id": "S", "machine_id": "M", "sensor_type": "temperature",
            "timestamp": "2024-05-01T08:00:00Z", "value": sentinel,
        }])
        if res.accepted_count != 0:
            check(f"sentinel {sentinel!r} rejected", False, "was accepted")
            break
    else:
        check("all documented sentinels are rejected", True)

    section("README 8 - contract bounds")
    over = normalizer.normalize_batch([{
        "sensor_id": "S", "machine_id": "M", "sensor_type": "temperature",
        "timestamp": "2024-05-01T08:00:00Z", "value": 400.5,
    }])
    check("temperature > 400 rejected", over.accepted_count == 0)
    under = normalizer.normalize_batch([{
        "sensor_id": "S", "machine_id": "M", "sensor_type": "temperature",
        "timestamp": "2024-05-01T08:00:00Z", "value": -90.5,
    }])
    check("temperature < -90 rejected", under.accepted_count == 0)
    nonint = normalizer.normalize_batch([{
        "sensor_id": "S", "machine_id": "M", "sensor_type": "error_code",
        "timestamp": "2024-05-01T08:00:00Z", "value": 1.5,
    }])
    check("non-integral error_code rejected", nonint.accepted_count == 0)
    check("DataContract is importable and constructible", DataContract() is not None)

    section("README 10.3 - output artefacts")
    with tempfile.TemporaryDirectory() as tmp:
        out = Path(tmp) / "telemetry.jsonl"
        IngestionPipeline(settings=settings).run_with_files(
            [SourceConfig(path=root / "examples/plant_a_readings.json")],
            SinkConfig(path=out),
        )
        for suffix in ("readings", "anomalies", "rejected", "report"):
            target = out.with_name(f"telemetry_{suffix}.jsonl")
            check(f"{suffix}.jsonl written", target.exists())
        report = json.loads(out.with_name("telemetry_report.jsonl").read_text(encoding="utf-8"))
        check("report has documented keys",
              set(report) >= {"records_ingested", "records_rejected", "anomalies_detected",
                              "dropouts_detected", "machines", "sensors",
                              "rejected", "health_scores"})
        score = report["health_scores"][0]
        check("health score has documented keys",
              set(score) >= {"machine_id", "score", "status", "factors",
                             "reading_count", "anomaly_count", "dropout_count"})

    section("README 6.4 - shape support")
    shapes = [
        ({"sensor_id": "S", "machine_id": "M", "sensor_type": "temperature",
          "timestamp": "2024-05-01T08:00:00Z", "value": 78.5}, 1),
        ({"sensor_id": "S", "machine_id": "M", "timestamp": "2024-05-01T08:00:00Z",
          "temperature": 78.5, "vibration": 12.0}, 2),
        ({"sensor_id": "S", "machine_id": "M",
          "readings": [{"sensor_type": "temperature", "timestamp": "2024-05-01T08:00:00Z", "value": 1.0},
                       {"sensor_type": "vibration", "timestamp": "2024-05-01T08:00:00Z", "value": 2.0}]}, 2),
        ({"sensor_id": "S", "machine_id": "M",
          "data": {"sensor_type": "temperature", "timestamp": "2024-05-01T08:00:00Z", "value": 1.0}}, 1),
        ({"sensor_id": "S", "machine_id": "M", "timestamp": "2024-05-01T08:00:00Z",
          "value": 78.5, "vibration": 12.0}, 1),
    ]
    for payload, expected in shapes:
        res = normalizer.normalize_batch([payload])
        check(f"shape {sorted(payload)[:3]} -> {expected} reading(s)",
              res.accepted_count == expected, f"got {res.accepted_count}")

    section("README 9.4 - health score formula")
    from iiot_telemetry.application.analytics import HealthScorerConfig, MachineHealthScorer

    scorer = MachineHealthScorer(HealthScorerConfig())
    readings = []
    for i in range(10):
        readings.append({
            "sensor_id": "S", "machine_id": "M", "sensor_type": "temperature",
            "timestamp": f"2024-05-01T08:{i:02d}:00Z", "value": 80.0,
        })
    normed = normalizer.normalize_batch(readings)
    for r in normed.readings:
        scorer.observe(r)
    score = scorer.score("M")
    check("healthy machine scores 100", score.score == 100.0, str(score.score))
    check("status is healthy", score.status == "healthy", score.status)

    section("README 12.1 - coverage / test count")
    print("  (run pytest separately to confirm the 373/100% figures)")

    print("\n" + "=" * 60)
    if FAILURES:
        print(f"{len(FAILURES)} DOCUMENTATION CLAIM(S) FAILED:")
        for failure in FAILURES:
            print(f"  - {failure}")
        raise SystemExit(1)
    print("All documentation claims verified.")


if __name__ == "__main__":
    main()

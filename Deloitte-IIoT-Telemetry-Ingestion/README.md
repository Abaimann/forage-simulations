# Daikibo Industrials — IIoT Telemetry Ingestion Pipeline

**Client:** Daikibo Industrials (manufacturing plants across 4 continents)
**Engagement:** Deloitte — Technology Consulting, Task 1
**Component:** Telemetry Ingestion & Analytics (ETL) Module

---

## Table of Contents

1. [Business Problem](#1-business-problem)
2. [Solution Overview](#2-solution-overview)
3. [Architecture](#3-architecture)
4. [Data Flow](#4-data-flow)
5. [Canonical Data Schema](#5-canonical-data-schema)
6. [Input Format Support](#6-input-format-support)
7. [Normalization Rules](#7-normalization-rules)
8. [Data Contracts](#8-data-contracts)
9. [Analytics](#9-analytics)
10. [Installation & Execution](#10-installation--execution)
11. [Configuration Parameters](#11-configuration-parameters)
12. [Testing](#12-testing)
13. [Project Layout](#13-project-layout)
14. [Production Deployment Notes](#14-production-deployment-notes)
15. [Extending the Pipeline](#15-extending-the-pipeline)
16. [Limitations & Future Work](#16-limitations--future-work)

---

## 1. Business Problem

Daikibo's production lines emit telemetry from heterogeneous legacy systems:

| Plant | Line | Legacy system | Format | Volume |
|---|---|---|---|---|
| Stuttgart | PRESS-01 | Siemens S7 gateway | JSON (wrapper) | ~60 rec/min |
| Monterrey | CONV-07 | Custom MES export | CSV, renamed columns | ~70 rec/min |
| Osaka | LATHE-03 | Edge broker (NDJSON) | JSON Lines, wide rows | ~120 rec/min |

The raw streams exhibit, in production:

- **Schema drift** — the same logical field is named `sensor_id`, `sensorId`, `DeviceID` or `tag`.
- **Structural variance** — long form (`value` + `sensor_type`), wide form (one row, many typed columns) and nested (`{"readings": [...]}`).
- **Temporal variance** — ISO-8601 with `Z`, naive local strings, epoch seconds, epoch milliseconds.
- **Physical variance** — °C / °F / K, Hz / kHz / RPM.
- **Corruption** — sentinel values (`-999`, `N/A`, `NaN`, `ERROR`), truncated rows, dropped heartbeats.

Without normalization, no cross-plant comparison or anomaly detection is possible. This module is the single ingestion point that makes the data trustworthy.

---

## 2. Solution Overview

A dependency-free Python ETL pipeline that:

1. **Parses** JSON, JSON Lines and CSV through pluggable source adapters.
2. **Normalizes** raw payloads into a canonical, UTC-anchored schema — absorbing schema drift, structural variance, unit variance and corruption.
3. **Validates** every reading against declarative, per-sensor-type data contracts.
4. **Analyzes** the stream: trailing moving averages, 3-sigma anomaly detection, sensor-dropout detection and per-machine health scoring.
5. **Persists** four artefacts — readings, anomalies, rejected records (dead-letter) and a run report.

**Design principles**

| Principle | Application |
|---|---|
| Clean architecture | Domain → Application → Adapters; dependencies point inward only. |
| Dependency inversion | The core depends on `TelemetrySource` / `TelemetrySink` ports, never on files. |
| Single responsibility | One class per concern; parsers parse, the normalizer normalizes, the detector detects. |
| Open/closed | New formats, transports and sensor types are added without touching the core. |
| Fail isolation | A corrupt record is quarantined; it never aborts the run. |
| Determinism | Readings are sorted before analytics, so results never depend on file ordering. |
| Testability | Pure functions and injected collaborators; no global state, no I/O in the domain. |

---

## 3. Architecture

```text
┌──────────────────────────────────────────────────────────────────────────────┐
│                              ADAPTERS  (I/O)                                 │
│                                                                              │
│  parsers/                          sinks/                                   │
│  ├── JsonTelemetryParser  ──┐     ├── FileTelemetrySink   → .jsonl/.json/.csv│
│  ├── JsonlTelemetryParser ─┤     └── InMemoryTelemetrySink → tests           │
│  └── CsvTelemetryParser  ──┘                                                  │
│           │                                                                  │
│           │ registry.build_source() auto-detects the format                 │
└───────────┼──────────────────────────────────────────────────────────────────┘
            │  TelemetrySource port            │  TelemetrySink port
            ▼                                 ▲
┌──────────────────────────────────────────────────────────────────────────────┐
│                           APPLICATION  (orchestration)                       │
│                                                                              │
│  pipeline.py ── IngestionPipeline                                           │
│    ├── normalizer.py ── TelemetryNormalizer   (anti-corruption layer)       │
│    ├── timestamp.py   ── parse_timestamp()     (UTC normalization)          │
│    └── analytics.py   ── MovingAverage                                         │
│                         SigmaAnomalyDetector                                  │
│                         DropoutDetector                                      │
│                         MachineHealthScorer                                  │
└──────────────────────────────────────────────────────────────────────────────┘
            │                                    ▲
            ▼                                    │
┌──────────────────────────────────────────────────────────────────────────────┐
│                              DOMAIN  (pure)                                  │
│                                                                              │
│  models.py     ── SensorReading, Timestamp, AnomalyFlag, HealthScore, ...     │
│  contracts.py  ── DataContract, SensorContract (validation rules)           │
│  exceptions.py ── TelemetryError hierarchy                                   │
└──────────────────────────────────────────────────────────────────────────────┘
```

**Layer rules**

- **Domain** imports nothing from the project. It has no I/O and no framework dependency.
- **Application** depends on the domain and on *ports* (abstract interfaces) only.
- **Adapters** depend on the application ports and implement them.
- The `adapters` package may import `application`; `application` never imports `adapters` at module level (the one local import, in `run_with_files`, is deliberate and documented).

---

## 4. Data Flow

```text
 ┌──────────┐   ┌─────────┐   ┌────────────┐   ┌──────────┐   ┌───────────┐
 │  SOURCE  │──▶│  PARSE  │──▶│ NORMALIZE  │──▶│ VALIDATE │──▶│  ANALYZE  │
 │ file/URL │   │ decode  │   │ alias map  │   │ contract │   │ statistics│
 └──────────┘   └─────────┘   └────────────┘   └──────────┘   └───────────┘
                      │              │                │                │
                      │              │                │                ▼
                      │              │                │        ┌───────────────┐
                      │              │                │        │  SINK (write) │
                      │              │                │        │  readings     │
                      ▼              ▼                ▼        │  anomalies    │
                 ┌────────────────────────────────────────┐   │  rejected     │
                 │        DEAD-LETTER (rejected)         │   │  report       │
                 │  reason · detail · source · index     │   └───────────────┘
                 └────────────────────────────────────────┘
```

**Stage details**

| # | Stage | Responsibility | Failure mode |
|---|---|---|---|
| 1 | **Parse** | Decode the file into raw mappings. Detect format by extension, then content. | Whole file quarantined (`MALFORMED_JSON` / `MALFORMED_CSV`). |
| 2 | **Normalize** | Canonicalize field names, expand wide/nested shapes, resolve sensor type, convert units, coerce values. | Record quarantined (`SCHEMA_DRIFT`, `MISSING_REQUIRED_FIELD`, …). |
| 3 | **Validate** | Enforce physical bounds, integrality and finiteness per sensor type. | Record quarantined (`OUT_OF_RANGE`, `INVALID_NUMERIC_VALUE`). |
| 4 | **Deduplicate** | Remove exact repeats on `(machine_id, sensor_id, timestamp, sensor_type)`. | Repeat quarantined (`DUPLICATE`). |
| 5 | **Sort** | Order readings by timestamp so analytics are deterministic. | — |
| 6 | **Analyze** | Moving average, 3-sigma anomaly detection, dropout detection, health scoring. | — |
| 7 | **Persist** | Write readings, anomalies, rejected records and the report. | — |

**Reject reasons** (`RejectReason` enum)

`malformed_json` · `malformed_csv` · `missing_required_field` · `invalid_timestamp` ·
`invalid_numeric_value` · `out_of_range` · `unknown_sensor_type` · `schema_drift` ·
`duplicate` · `empty_payload` · `io_error`

---

## 5. Canonical Data Schema

### 5.1 Normalized reading (`SensorReading` → `*_readings.jsonl`)

| Field | Type | Required | Description |
|---|---|---|---|
| `sensor_id` | string | yes | Identifier of the emitting sensor. |
| `machine_id` | string | yes | Identifier of the machine/asset. |
| `sensor_type` | enum | yes | `temperature` \| `vibration` \| `error_code`. |
| `timestamp` | string | yes | **Timezone-aware UTC ISO-8601**, e.g. `2024-05-01T08:40:00+00:00`. |
| `value` | float | yes | Numeric measurement, converted to the canonical unit. |
| `unit` | string | yes | Canonical unit: `C`, `Hz` or `code`. |
| `source` | string | yes | Origin file path (audit trail). |
| `quality_flags` | string[] | no | Reserved for future data-quality markers. |

### 5.2 Anomaly (`AnomalyFlag` → `*_anomalies.jsonl`)

| Field | Type | Description |
|---|---|---|
| `sensor_id` / `machine_id` / `sensor_type` | string / string / enum | Identifies the offending stream. |
| `timestamp` | string | UTC ISO-8601 of the offending reading. |
| `value` | float | The anomalous measurement. |
| `unit` | string | Canonical unit. |
| `baseline` | float | Rolling mean of the previous window (excluding the offending point). |
| `std_dev` | float | Population standard deviation of the baseline. |
| `z_score` | float | `(value − baseline) / std_dev`. |
| `moving_average` | float | Trailing moving average at that point. |
| `severity` | enum | `info` \| `warning` \| `critical`. |
| `rule` | string | The rule that fired, e.g. `sigma_3`. |

### 5.3 Machine health (`HealthScore`, inside the report)

| Field | Type | Description |
|---|---|---|
| `machine_id` | string | Machine identifier. |
| `score` | float | Health score, `0.0` – `100.0` (higher is healthier). |
| `status` | enum | `healthy` (≥ 80) \| `degraded` (≥ 50) \| `critical` (< 50) \| `unknown`. |
| `factors.anomaly` | float | Anomaly ratio (anomalies ÷ readings), capped at 1. |
| `factors.error` | float | Error-code ratio (non-zero error codes ÷ readings). |
| `factors.dropout` | float | Dropout ratio (dropouts ÷ `max_dropout_count`). |
| `reading_count` / `anomaly_count` / `dropout_count` | int | Raw counters behind the ratios. |

### 5.4 Run report (`*_report.jsonl`)

```json
{
  "records_ingested": 250,
  "records_rejected": 0,
  "anomalies_detected": 4,
  "dropouts_detected": 0,
  "machines": 3,
  "sensors": 7,
  "rejected": [],
  "health_scores": [ /* one entry per machine */ ]
}
```

---

## 6. Input Format Support

### 6.1 JSON

Three root shapes are accepted:

```jsonc
// (a) array of readings
[{ "sensor_id": "TEMP-01", "value": 78.5 }, ...]

// (b) wrapper object
{ "plant": "Stuttgart", "readings": [ /* ... */ ] }

// (c) single reading object
{ "sensor_id": "TEMP-01", "value": 78.5 }
```

Wrapper keys recognized: `readings`, `records`, `data`, `telemetry`, `events`, `items`, `values`.

### 6.2 JSON Lines (NDJSON)

One JSON object per line. A malformed line is **skipped**, not fatal — the remaining lines still ingest.

### 6.3 CSV

- Delimiter auto-detected among `,` `;` `\t` `|` (override with `--delimiter` semantics via `SourceConfig`).
- UTF-8 BOM stripped; header cells trimmed and lower-cased.
- Legacy column names mapped onto canonical names.
- Blank rows skipped; rows with a wrong column count skipped (values are never misaligned).
- When several columns map to the same canonical field, **a populated value is never overwritten by an empty one** — this is what makes mid-file schema drift survivable.

### 6.4 Shape support

| Shape | Example | Result |
|---|---|---|
| Long form | `{"value": 78.5, "sensor_type": "temperature"}` | 1 reading |
| Wide form | `{"temperature": 78.5, "vibration": 12.0}` | 2 readings (one per typed column) |
| Nested array | `{"readings": [{...}, {...}]}` | 1 reading per element |
| Nested object | `{"data": {"value": 78.5, ...}}` | 1 reading |
| Explicit value + typed column | `{"value": 78.5, "vibration": 12.0}` | 1 reading — the **explicit value wins**; the typed column only identifies the sensor type |

---

## 7. Normalization Rules

### 7.1 Field aliases

| Canonical | Accepted source names |
|---|---|
| `sensor_id` | `sensor`, `sensorId`, `device_id`, `deviceId`, `device`, `id`, `tag` |
| `machine_id` | `machine`, `machineId`, `asset_id`, `assetId`, `asset`, `equipment_id`, `line_id` |
| `timestamp` | `ts`, `time`, `event_time`, `eventTime`, `datetime`, `dateTime`, `recorded_at`, `reading_time` |
| `value` | `reading`, `val`, `measurement`, `reading_value`, `readingValue`, `amount` |
| `sensor_type` | `type`, `sensorType`, `metric`, `kind`, `sensor_category` |
| `unit` | `units`, `uom`, `unit_of_measure` |

Matching is case-insensitive; `-` and spaces normalize to `_`.

### 7.2 Timestamps → UTC

| Input | Interpretation |
|---|---|
| `2024-05-01T08:00:00Z` | ISO-8601 UTC. |
| `2024-05-01T10:00:00+02:00` | Offset converted to UTC. |
| `2024-05-01 08:00:00` | Naive → assumed UTC. |
| `1714550400` | Epoch **seconds** (unit inferred from magnitude). |
| `1714550400000` | Epoch **milliseconds**. |
| `1714550400000000` | Epoch **microseconds**. |
| `1714550400000000000` | Epoch **nanoseconds**. |
| `01/05/2024` | Day-first (configurable); auto-disambiguated when a component exceeds 12. |
| `2024/05/01` | Year-first. |
| `01/05/24` | Two-digit year → 2024. |

Ambiguity policy: if the first component > 12 the date is day-first; if the second > 12 it is month-first; otherwise the `day_first` policy applies (**day-first by default**, matching the predominantly European legacy systems of the plant network).

### 7.3 Values

- Numeric strings are coerced (`"78.5"` → `78.5`); a trailing unit suffix is tolerated (`"82.5C"` → `82.5`).
- Scientific notation is supported (`"1.25e2"` → `125.0`).
- **Sentinels are rejected**: `""`, `-`, `--`, `N/A`, `na`, `null`, `none`, `nil`, `NaN`, `unknown`, `error`, `err`, `timeout`, `disconnected`, `offline`, `-999`, `-9999`, `999`, `9999`, `inf`, `-inf`, `1e309`.
- Booleans are rejected (a boolean is not a measurement).
- `NaN` / `±inf` are rejected.

### 7.4 Units

| Sensor type | Accepted units | Canonical |
|---|---|---|
| `temperature` | `C`, `°C`, `celsius`, `F`, `°F`, `fahrenheit`, `K`, `kelvin` | `C` |
| `vibration` | `Hz`, `hertz`, `kHz`, `MHz`, `rpm`, `mm/s`, `m/s²`, `g` | `Hz` |
| `error_code` | `code`, `error` | `code` |

Conversion is affine: `C = (F − 32) × 5/9`, `C = K − 273.15`, `Hz = rpm ÷ 60`, `Hz = kHz × 1000`.

### 7.5 Sensor-type resolution

1. An explicit `sensor_type` (with alias expansion: `temp`, `VIB_HZ`, `fault`, …).
2. The physical unit (`Hz` → vibration, `C` → temperature, `code` → error code) — legacy exports frequently omit the type column.
3. Otherwise the record is rejected as `missing_required_field`.

---

## 8. Data Contracts

Contracts are **data, not code**, so they can be versioned and overridden per plant line.

| Sensor type | Unit | Min | Max | Integral | Expected interval |
|---|---|---|---|---|---|
| `temperature` | `C` | −90.0 | 400.0 | no | 60 s |
| `vibration` | `Hz` | 0.0 | 20 000.0 | no | 60 s |
| `error_code` | `code` | 0 | 65 535 | **yes** | 60 s |

Every reading is checked for: required fields present · identifiers non-empty and string-typed · timestamp parseable · value finite, numeric, integral where required, and within physical bounds.

Override per deployment:

```python
from iiot_telemetry.domain.contracts import DataContract, SensorContract
from iiot_telemetry.domain.models import SensorType

contract = DataContract(
    contracts={
        SensorType.TEMPERATURE: SensorContract(
            sensor_type=SensorType.TEMPERATURE,
            unit="C",
            min_value=-40.0,      # plant-specific range
            max_value=250.0,
            expected_interval_seconds=30.0,
        )
    }
)
pipeline = IngestionPipeline(settings=settings, contract=contract)
```

---

## 9. Analytics

### 9.1 Moving average

Trailing simple moving average over a fixed window (default 5 samples). Implemented with a bounded `deque`, so memory is constant regardless of stream length.

### 9.2 3-sigma anomaly detection

For each reading:

1. Take the rolling baseline of the **previous** `baseline_window` samples (default 50) for that `(machine_id, sensor_id)`.
2. Once at least `min_baseline_samples` (default 10) points are available, compute the **population** standard deviation and the z-score:
   `z = (value − baseline) / std_dev`.
3. Flag the reading when `z > sigma_threshold` (default **3.0**).

Two design points that matter:

- **The offending reading is excluded from its own baseline.** A single extreme value therefore cannot mask itself — the z-score reflects the *historical* operating envelope.
- **Baselines are isolated per sensor and per machine.** A noisy sensor on machine A never shifts the baseline of machine B.

Severity bands: `z ≥ 6` → critical · `z ≥ 4.5` → warning · otherwise info.

Detection applies to `temperature` by default; the sensor types are configurable.

### 9.3 Dropout detection

A dropout is reported when the gap between two consecutive readings of the same sensor exceeds `dropout_gap_factor × expected_interval_seconds` (default 3 × 60 s = 180 s). Out-of-order and zero/negative gaps are ignored.

### 9.4 Machine health score

```text
score = 100
        − anomaly_weight  × min(1, anomalies / readings)     # 50
        − error_weight    × min(1, error_codes / readings)   # 30
        − dropout_weight  × min(1, dropouts / max_dropouts)  # 20
score = clamp(score, 0, 100)
```

Status bands: `healthy` ≥ 80 · `degraded` ≥ 50 · `critical` < 50.

---

## 10. Installation & Execution

### 10.1 Requirements

- **Python ≥ 3.10** (developed and verified on 3.10.9).
- **Runtime dependencies: none** — the standard library only. This is deliberate: the module must run on factory-edge runtimes with restricted package availability.
- Development extras: `pytest`, `pytest-cov`.

### 10.2 Install

```bash
# From the project root
python -m pip install -e .          # runtime
python -m pip install -e ".[dev]"    # runtime + test tooling
```

Or run without installing, using the `src/` layout directly:

```bash
export PYTHONPATH=src
python -m iiot_telemetry --help
```

### 10.3 CLI

```bash
# Ingest a directory of mixed-format files
python -m iiot_telemetry --input ./data --output ./out/telemetry.jsonl

# Ingest a single file with custom analytics parameters
python -m iiot_telemetry -i line3.csv -o out.jsonl \
    --sigma 2.5 --baseline-window 100 --min-baseline-samples 20

# Print the report to stdout without writing files
python -m iiot_telemetry -i ./data --print-report
```

After `pip install -e .` the console script is also available:

```bash
iiot-ingest --input ./data --output ./out/telemetry.jsonl
```

**Exit codes**

| Code | Meaning |
|---|---|
| `0` | Run completed (rejected records are *not* an error). |
| `2` | Input path missing, or no readable input files found. |

### 10.4 Library usage

```python
from pathlib import Path

from iiot_telemetry import IngestionPipeline, IngestionSettings, SinkConfig, SourceConfig

settings = IngestionSettings(
    sources=(SourceConfig(path=Path("examples/plant_a_readings.json")),),
    sigma_threshold=3.0,
    baseline_window=50,
    min_baseline_samples=10,
)

pipeline = IngestionPipeline(settings=settings)
result = pipeline.run()

print(result.report.records_ingested)   # 60
print(result.report.anomalies_detected)  # 1
for anomaly in result.anomalies:
    print(anomaly.to_dict())
```

Writing to disk:

```python
from iiot_telemetry import SinkConfig

result = pipeline.run_with_files(
    [SourceConfig(path=Path("examples/plant_a_readings.json"))],
    SinkConfig(path=Path("out/telemetry.jsonl")),
)
```

This produces four files next to each other:

```text
out/
├── telemetry_readings.jsonl    # normalized readings
├── telemetry_anomalies.jsonl   # detected anomalies
├── telemetry_rejected.jsonl    # dead-letter records
└── telemetry_report.jsonl      # run report + health scores
```

### 10.5 Regenerate the sample payloads

```bash
python scripts/generate_samples.py
```

---

## 11. Configuration Parameters

### 11.1 CLI options

| Option | Default | Description |
|---|---|---|
| `-i`, `--input` | *required* | Input file **or** directory (scanned recursively). |
| `-o`, `--output` | — | Base output path; artefacts are written as `<name>_readings.jsonl` etc. |
| `--format` | `auto` | `auto` \| `json` \| `jsonl` \| `csv`. |
| `--output-format` | `jsonl` | `jsonl` \| `json` \| `csv`. |
| `--sigma` | `3.0` | Anomaly z-score threshold. |
| `--baseline-window` | `50` | Samples in the rolling baseline. |
| `--min-baseline-samples` | `10` | Samples required before detection activates. |
| `--moving-average-window` | `5` | Trailing moving-average window. |
| `--expected-interval` | `60.0` | Expected sampling interval (s), used for dropout detection. |
| `--no-dedupe` | off | Keep duplicate records. |
| `--print-report` | off | Print the report to stdout even when `--output` is given. |

### 11.2 `IngestionSettings`

| Field | Type | Default | Description |
|---|---|---|---|
| `moving_average_window` | `int` | `5` | Moving-average window. |
| `sigma_threshold` | `float` | `3.0` | Anomaly threshold. |
| `baseline_window` | `int` | `50` | Rolling baseline size. |
| `min_baseline_samples` | `int` | `10` | Warm-up samples before detection. |
| `dropout_gap_factor` | `float` | `3.0` | Multiplier on the expected interval. |
| `expected_interval_seconds` | `float` | `60.0` | Nominal sampling period. |
| `dedupe` | `bool` | `True` | Remove exact duplicates. |
| `sort_readings` | `bool` | `True` | Sort by timestamp before analytics. |
| `sources` | `tuple[SourceConfig]` | `()` | Input sources. |
| `sink` | `SinkConfig \| None` | `None` | Output target. |

### 11.3 `SourceConfig` / `SinkConfig`

| Field | Type | Default | Description |
|---|---|---|---|
| `SourceConfig.path` | `Path` | — | File to read. |
| `SourceConfig.encoding` | `str` | `"utf-8"` | Text encoding. |
| `SourceConfig.format` | `str` | `"auto"` | Payload format. |
| `SourceConfig.delimiter` | `str \| None` | `None` | CSV delimiter override. |
| `SinkConfig.path` | `Path` | — | Base output path. |
| `SinkConfig.format` | `str` | `"jsonl"` | Output format. |

---

## 12. Testing

### 12.1 Running the suite

```bash
python -m pytest                       # 373 tests
python -m pytest --cov=iiot_telemetry --cov-report=term-missing
python -m pytest -m "not integration"  # unit tests only
```

**Current status: 373 passed, 0 failed — 100.00 % statement and branch coverage.**

Coverage is enforced at build time: `pyproject.toml` sets `fail_under = 100`, so a drop below full coverage fails the run.

### 12.2 Test organization

| File | Scope |
|---|---|
| `tests/unit/test_timestamp.py` | Every accepted and rejected timestamp shape, day/month ambiguity, epoch units. |
| `tests/unit/test_normalizer.py` | Schema drift (every alias), shape variance, corruption, unit conversion, contract validation, dedup. |
| `tests/unit/test_analytics.py` | Moving average, 3-sigma detection, baseline isolation, severity bands, dropout detection, health scoring and every status band. |
| `tests/unit/test_parsers.py` | JSON/JSONL/CSV shapes, delimiter sniffing, BOM, malformed input, format detection. |
| `tests/unit/test_sinks.py` | All output formats, empty artefacts, heterogeneous CSV headers, directory creation. |
| `tests/unit/test_pipeline.py` | Orchestration, multi-source merging, quarantine, dedup, sorting, anomaly and dropout integration. |
| `tests/unit/test_domain.py` | Entity invariants, value-object contracts, serialisation. |
| `tests/unit/test_cli.py` | Argument parsing, single file / directory ingestion, exit codes, output artefacts. |
| `tests/integration/test_pipeline_integration.py` | End-to-end runs over the shipped example payloads plus hostile-input scenarios. |

### 12.3 Edge cases covered

**Corrupt inputs** — malformed JSON/CSV, invalid UTF-8, missing files, empty files, wrong column counts, truncated numbers, `NaN`/`inf`, every sentinel value, boolean values, out-of-range values, non-integral error codes.

**Schema drift** — 20+ field aliases across four canonical identifiers, case and separator variance, renamed columns mid-file, wide/long/nested shape changes, missing `sensor_type` (inferred from the unit), unit changes (°C → °F → K, Hz → kHz → RPM).

**Sensor dropouts** — gaps beyond the threshold, per-sensor isolation, out-of-order and negative gaps.

**Timestamps** — 12 distinct formats, epoch unit inference by magnitude, ambiguous day/month resolution in both directions, invalid dates, out-of-range hours, naive datetimes.

**Determinism** — out-of-order records are sorted before analytics; identical inputs always produce identical reports.

---

## 13. Project Layout

```text
Deloitte-IIoT-Telemetry-Ingestion/
├── pyproject.toml                     # packaging, pytest & coverage configuration
├── README.md                          # this document
├── task.md                            # original engagement brief
│
├── src/iiot_telemetry/
│   ├── __init__.py                    # public API surface
│   ├── __main__.py                    # `python -m iiot_telemetry`
│   ├── cli.py                         # command-line interface
│   │
│   ├── domain/                        # PURE — no I/O, no framework
│   │   ├── models.py                  # SensorReading, Timestamp, AnomalyFlag, HealthScore…
│   │   ├── contracts.py               # DataContract, SensorContract, FieldSpec
│   │   └── exceptions.py              # error hierarchy
│   │
│   ├── application/                   # orchestration, no concrete I/O
│   │   ├── pipeline.py                # IngestionPipeline — the use case
│   │   ├── normalizer.py              # TelemetryNormalizer — anti-corruption layer
│   │   ├── timestamp.py               # UTC timestamp normalization
│   │   ├── analytics.py               # MovingAverage, SigmaAnomalyDetector, HealthScorer…
│   │   └── ports.py                   # TelemetrySource / TelemetrySink interfaces
│   │
│   └── adapters/                      # CONCRETE I/O
│       ├── parsers/
│       │   ├── json_parser.py
│       │   ├── jsonl_parser.py
│       │   ├── csv_parser.py
│       │   └── registry.py            # format detection & parser selection
│       └── sinks/
│           ├── file_sink.py
│           └── memory_sink.py
│
├── tests/
│   ├── conftest.py                    # shared fixtures
│   ├── unit/                          # 8 unit-test modules
│   └── integration/                   # end-to-end scenarios
│
├── examples/                          # sample payloads (3 formats)
│   ├── plant_a_readings.json
│   ├── plant_b_legacy.csv
│   └── plant_c_stream.jsonl
│
└── scripts/
    ├── generate_samples.py            # regenerate the example payloads
    ├── debug_csv.py                   # parser inspection helper
    ├── epoch_helper.py                # epoch reference helper
    └── show_lines.py                  # source-line inspection helper
```

---

## 14. Production Deployment Notes

### 14.1 Scaling the ingestion path

The current implementation buffers a batch per source file. For continuous, high-volume streams:

- **Replace the source adapter** with a Kafka / MQTT / Kinesis consumer implementing `TelemetrySource.read()`. The core is unchanged.
- **Chunk the payloads** — `NormalizationSettings.max_records_per_batch` (default 1 000 000) bounds memory per batch; lower it for tighter memory control.
- **Stream the analytics** — `SigmaAnomalyDetector`, `MovingAverage` and `DropoutDetector` are already streaming-friendly (bounded deques), so they can process indefinitely without growing.
- **Partition by sensor** — for parallelism, shard by `sensor_id` so each partition keeps a coherent per-sensor baseline. Note that the pipeline currently sorts globally before analytics; in a partitioned deployment, sort within the partition.

### 14.2 Reliability

- **Dead-letter handling** — every rejected record is written to `*_rejected.jsonl` with `reason`, `detail`, `source` and `record_index`. Route this file to object storage or a quarantine topic for replay after the upstream contract is fixed.
- **Idempotency** — duplicate suppression on `(machine_id, sensor_id, timestamp, sensor_type)` makes replays safe. The first occurrence wins, so the result is deterministic.
- **Schema drift alerting** — a rising `schema_drift` or `missing_required_field` rate is the earliest signal that an upstream system changed its export format.
- **Retry** — file-based sources are read once per run; schedule the job at a cadence that matches the source's refresh rate, or move to an event-driven adapter.

### 14.3 Observability

The report is a ready-made SLI payload. Recommended alerts:

| Signal | Condition | Meaning |
|---|---|---|
| `records_rejected / records_ingested` | > 5 % | Upstream contract break or sensor malfunction. |
| `anomalies_detected` | spike vs. 7-day baseline | Genuine process excursion. |
| `dropouts_detected` | > 0 for a critical line | Network or device failure. |
| `health_scores[].status` | `critical` | Machine requires maintenance. |

Ship `*_report.jsonl` to the telemetry bus and forward it to the monitoring stack.

### 14.4 Security

- The runtime has **no third-party dependencies**, shrinking the supply-chain surface to zero.
- The pipeline performs **no network I/O and no dynamic evaluation** — inputs are parsed with `json` and `csv`, never `eval`/`exec`.
- Untrusted payloads are handled defensively: size-bounded batches, sentinel filtering, physical range checks, and full quarantine of anything unparseable.
- Run as an unprivileged user; the pipeline needs write access only to its output directory.
- For untrusted file uploads, enforce a maximum file size and run the ingestion in a sandbox.

### 14.5 Configuration management

Plant-specific configuration (contracts, intervals, sigma thresholds) belongs in version-controlled deployment manifests rather than in code. `DataContract` and `IngestionSettings` are plain dataclasses and can be loaded from JSON/YAML by the deployment wrapper.

### 14.6 Operational runbook

| Symptom | Likely cause | Action |
|---|---|---|
| All records rejected as `missing_required_field` | Upstream renamed a required column | Inspect `*_rejected.jsonl`; extend `_FIELD_ALIASES` or the CSV alias map. |
| All records rejected as `invalid_timestamp` | Upstream changed its date format | Add the format to `_SUPPORTED_FORMATS` / the numeric-date regex. |
| No anomalies detected | Baseline never warms up | Lower `--min-baseline-samples` or raise `--baseline-window`. |
| Too many anomalies | Threshold too tight for a noisy line | Raise `--sigma` or exclude that sensor type. |
| Constant dropouts | Sampling interval differs from the expectation | Adjust `--expected-interval` / `--dropout-gap-factor`. |

---

## 15. Extending the Pipeline

### 15.1 A new input format (e.g. Avro)

Implement the `TelemetrySource` port and register it:

```python
from iiot_telemetry.application.ports import SourceConfig, TelemetrySource

class AvroTelemetryParser(TelemetrySource):
    def read(self, config: SourceConfig):
        yield from decode_avro(config.path)   # yields raw mappings
```

Then add `"avro"` to `build_source()` in `adapters/parsers/registry.py`. The domain and application layers need **no change**.

### 15.2 A new output transport (e.g. Kafka)

Implement the `TelemetrySink` port:

```python
class KafkaTelemetrySink(TelemetrySink):
    def write_readings(self, readings): ...
    def write_anomalies(self, anomalies): ...
    def write_rejected(self, rejected): ...
    def write_report(self, report): ...
```

Inject it into `IngestionPipeline(settings=..., sink=KafkaTelemetrySink(...))`.

### 15.3 A new sensor type

1. Add the member to `SensorType` and an alias in `SensorType.from_raw`.
2. Add a `SensorContract` (unit, physical bounds, integrality) to `DEFAULT_CONTRACTS`.
3. Add the canonical field to `_FIELD_ALIASES` and `_TYPE_FROM_FIELD`.
4. Add the unit conversions to `_UNIT_CONVERSIONS`.

The analytics layer needs no change unless the type should be anomaly-detected — then add it to `SigmaDetectorConfig.sensor_types`.

### 15.4 A new analytics rule

Add a focused class to `application/analytics.py` exposing the same streaming shape as `SigmaAnomalyDetector` (`evaluate(reading) -> result | None`), and wire it into `IngestionPipeline._analyze`.

---

## 16. Limitations & Future Work

| Limitation | Impact | Planned direction |
|---|---|---|
| Batching, not streaming | Memory grows with the size of one source file | Kafka/MQTT adapter with chunked, bounded batches. |
| Global sort before analytics | High memory on very large inputs | Partition by `sensor_id` and sort within partitions. |
| Anomaly detection covers `temperature` only by default | Vibration excursions are not flagged | Configure `SigmaDetectorConfig.sensor_types`; per-type thresholds. |
| Static baseline | A slowly drifting baseline is learned as normal | Add exponential moving average / adaptive baseline modes. |
| No seasonality model | Daily/weekly cycles are treated as noise | Add STL decomposition or a seasonal baseline. |
| Health score is a linear weighting | Weights are not calibrated against failure data | Re-fit weights against the historical maintenance log. |
| No schema registry | Drift is detected but not versioned | Adopt a schema registry (Avro/JSON Schema) per plant. |
| Local files only | Not suited to event-driven sources | Implement the `TelemetrySource` port over Kafka/MQTT. |

---

## Appendix A — Glossary

| Term | Meaning |
|---|---|
| **Canonical schema** | The single normalized representation every stage of the pipeline agrees on. |
| **Schema drift** | An upstream system changing field names, types or structure without notice. |
| **Anti-corruption layer** | The component absorbing legacy format quirks so the domain stays clean. |
| **Dead-letter** | The store of records that failed validation, kept for audit and replay. |
| **Baseline** | The rolling window of *previous* readings used as the reference for z-scores. |
| **Z-score** | `(value − mean) / std_dev`; the number of standard deviations from normal. |
| **Dropout** | A gap in a sensor stream longer than the expected sampling interval. |
| **Wide form** | A row carrying several typed measurements in separate columns. |
| **Long form** | A row carrying a single measurement in a generic `value` column. |

## Appendix B — Verification Record

```text
$ python -m pytest tests/ -q --cov=iiot_telemetry --cov-report=term-missing
373 passed
Required test coverage of 100.0% reached. Total coverage: 100.00%
```

All 23 source modules report **100 %** statement and branch coverage. The suite covers the
happy path, schema drift, corrupt inputs, schema-drift transitions, sensor dropouts,
timestamp ambiguity, unit conversion and every analytics branch.

# Lyft Fleet Maintenance — Clean Architecture Refactoring

A modular refactoring of the Lyft rental-car fleet maintenance domain, built with the
**Strategy** and **Factory** patterns on top of a **Clean Architecture** layering.

The system answers one question: *given a vehicle and a set of readings, does it need
service, and why?* Every rule that drives that answer lives in a single, swappable place.

---

## Table of contents

1. [Business context](#1-business-context)
2. [Architecture](#2-architecture)
3. [UML diagrams](#3-uml-diagrams)
4. [Domain model](#4-domain-model)
5. [Service criteria (Strategy)](#5-service-criteria-strategy)
6. [Factories](#6-factories)
7. [Configuration reference](#7-configuration-reference)
8. [Public API reference](#8-public-api-reference)
9. [Getting started](#9-getting-started)
10. [Running the tests](#10-running-the-tests)
11. [Extending the system](#11-extending-the-system)
12. [Design decisions and trade-offs](#12-design-decisions-and-trade-offs)
13. [Project layout](#13-project-layout)

---

## 1. Business context

Lyft operates a rental-car fleet. Each vehicle is made of three serviceable systems, and
each system ages differently:

| System | Ages by | Example rule |
|---|---|---|
| Engine | Distance driven (or a dashboard telltale) | Capulet: service after more than 30 000 miles |
| Battery | Calendar time | Nubbin: four year lifetime, Spindler: three years |
| Tyre | Sensor wear | Carrigan: any wheel at 90 % wear; Octoprime: combined wear of 3.0 |

The fleet contains five models, each a different combination of those parts:

| Model | Engine | Battery | Tyres | Fleet inspection |
|---|---|---|---|---|
| Calliope | Capulet | Spindler | Carrigan | every 2 years |
| Glissando | Willoughby | Spindler | Octoprime | every 2 years |
| Palindrome | Sternman | Nubbin | Carrigan | every 4 years |
| Rorschach | Willoughby | Nubbin | Octoprime | every 4 years |
| Thovex | Capulet | Nubbin | Carrigan | every 4 years |

### The problem with the legacy design

The original codebase mixed all three concerns:

```python
# Legacy: a car IS an engine, and it reaches for the wall clock itself.
class Calliope(CapuletEngine):
    def needs_service(self):
        service_threshold_date = self.last_service_date.replace(year=self.last_service_date.year + 2)
        if service_threshold_date < datetime.today().date() or self.engine_should_be_serviced():
            return True
        return False
```

Four defects follow directly from that shape:

1. **Wrong abstraction.** A car inherits from an engine, so `isinstance(calliope, Engine)`
   is `True`. A car *has* an engine; it is not one.
2. **Duplicated rules.** The five model classes each re-implemented the same date
   arithmetic, so a rule change required five edits.
3. **Hidden coupling to the environment.** `datetime.today()` is called *inside* the
   rule, so the result depends on when the test runs. The service logic is untestable
   without freezing the clock.
4. **Data smuggled through constructors.** Engines were constructed with
   `current_mileage` and `last_service_mileage`, so an "engine" was really a snapshot of
   one inspection. One engine object could not be reused across inspections.

### What this refactoring changes

| Legacy | Refactored |
|---|---|
| `class Calliope(CapuletEngine)` | `class Calliope(Car)` — a *composition* of parts |
| Rules inlined in each model | Rules isolated in `ServiceCriterion` strategies |
| `datetime.today()` inside the rule | `current_date` supplied via `ServiceContext` |
| Readings baked into constructors | Stateless components, readings passed at evaluation time |
| Five duplicated `create_<model>` methods | One `CarFactory` registry |
| `and` / `or` inconsistently mixed | Explicit, tested composition rules |

---

## 2. Architecture

### Layered design (Clean Architecture)

Dependencies point **inwards only**. The domain knows nothing about the application
layer, the factories, or the outside world.

```
┌───────────────────────────────────────────────────────────────────────────┐
│  infrastructure/            Factory pattern, registries, adapters          │
│  ────────────────────────────────────────────────────────────────────────  │
│    factory.py               EngineFactory / BatteryFactory / TireFactory   │
│                             CarFactory                                    │
│         ▲ depends on                                                        │
├───────────────────────────────────────────────────────────────────────────┤
│  application/               Use cases, DTOs, orchestration               │
│  ────────────────────────────────────────────────────────────────────────  │
│    fleet_service.py         FleetMaintenanceService, ServiceReport,        │
│                             VehicleInspection                            │
│         ▲ depends on                                                        │
├───────────────────────────────────────────────────────────────────────────┤
│  domain/                    Pure business rules — no I/O, no clock         │
│  ────────────────────────────────────────────────────────────────────────  │
│    serviceable.py           Serviceable (the shared contract)             │
│    criteria.py              ServiceCriterion + the strategies             │
│    value_objects.py         ServiceContext (immutable readings snapshot)  │
│    components/engine.py     Engine  → Capulet / Willoughby / Sternman     │
│    components/battery.py    Battery → Nubbin / Spindler                   │
│    components/tire.py       Tire    → Carrigan / Octoprime                 │
│    car.py                   Car aggregate + the five models               │
├───────────────────────────────────────────────────────────────────────────┤
│  config.py                  All tunable thresholds (no magic numbers)     │
│  errors.py                  FleetError hierarchy                          │
└───────────────────────────────────────────────────────────────────────────┘
```

**Layer responsibilities**

| Layer | May depend on | Must never contain |
|---|---|---|
| `domain` | `config`, `errors` | I/O, `datetime.now()`, framework code |
| `application` | `domain`, `infrastructure` | servicing rules |
| `infrastructure` | `domain` | business decisions |

### SOLID mapping

| Principle | How it is honoured |
|---|---|
| **S**ingle Responsibility | A criterion decides one thing. An engine only aggregates criteria. A factory only resolves names to builders. |
| **O**pen/Closed | New models, engines, batteries, tyres and criteria are added by *registering* or *injecting* — never by editing existing classes. |
| **L**iskov Substitution | Every criterion is substitutable for `ServiceCriterion`; every component for `Serviceable`. `Car` accepts any `Engine`/`Battery`/`Tire`. |
| **I**nterface Segregation | `Serviceable` exposes only `needs_service` (+ an optional `service_reasons`). `ServiceCriterion` exposes only `is_due` and `describe`. |
| **D**ependency Inversion | The application layer depends on the `Serviceable` abstraction; the domain depends on nothing. |

### Design patterns used

* **Strategy** — `ServiceCriterion` is the strategy interface; `MileageCriterion`,
  `CalendarCriterion` and `WearThresholdCriterion` are interchangeable algorithms.
* **Factory** — `CarFactory` and the three component factories resolve a name to a
  ready-to-use object graph.
* **Registry** — each factory is an open name → builder registry, making the factory
  itself extensible.
* **Composite** — `AnyCriterion` / `AllCriterion` compose criteria into larger rules.
* **Value Object** — `ServiceContext` is a frozen, validated snapshot of readings.
* **Dependency Injection** — every component receives its rules through the constructor.

---

## 3. UML diagrams

### 3.1 Class diagram — domain layer

```
┌────────────────────────────────────────────────────────────────────────────┐
│ «abstract» Serviceable                                                   │
├────────────────────────────────────────────────────────────────────────────┤
│ + needs_service(context : ServiceContext) : bool                          │
│ + service_reasons(context : ServiceContext) : Tuple[str, ...]             │
└────────────────────────────────────────────────────────────────────────────┘
        ▲                    ▲                    ▲
        │                    │                    │
┌───────┴────────┐  ┌────────┴───────┐  ┌────────┴───────┐
│ Engine         │  │ Battery        │  │ Tire           │
├────────────────┤  ├────────────────┤  ├────────────────┤
│ - criteria     │  │ - criteria     │  │ - criteria     │
│ - name         │  │ - name         │  │ - name         │
├────────────────┤  ├────────────────┤  ├────────────────┤
│ + name         │  │ + name         │  │ + name         │
│ + criteria     │  │ + criteria     │  │ + criteria     │
│ + needs_service│  │ + needs_service│  │ + needs_service│
│ + service_reasons│ │ + service_reasons│ │ + service_reasons│
└────────────────┘  └────────────────┘  └────────────────┘
        ▲   ▲   ▲          ▲   ▲           ▲   ▲
        │   │   │          │   │           │   │
   ┌────┘   │   └────┐ ┌────┘   └────┐ ┌────┘   └────┐
   │Capulet  │Willoughby│Nubbin Spindler│Carrigan Octoprime│
   │ Engine  │ Engine  │Battery Battery│  Tire     Tire  │
   └─────────┴─────────┘└────────┴─────┘└────────┴──────┘

┌────────────────────────────────────────────────────────────────────────────┐
│ Car  (composes parts; contains no servicing logic of its own)             │
├────────────────────────────────────────────────────────────────────────────┤
│ - engine : Engine                                                        │
│ - battery : Battery                                                      │
│ - tire : Tire                                                            │
│ - inspection_criteria : Tuple[ServiceCriterion, ...]                      │
│ - name : str                                                             │
├────────────────────────────────────────────────────────────────────────────┤
│ + engine / battery / tire / components / inspection_criteria : read-only  │
│ + needs_service(context) : bool                                          │
│ + service_reasons(context) : Tuple[str, ...]                             │
└────────────────────────────────────────────────────────────────────────────┘
        ▲            ▲            ▲            ▲            ▲
        │            │            │            │            │
  ┌─────────┐  ┌───────────┐  ┌──────────┐  ┌──────────┐  ┌────────┐
  │Calliope │  │ Glissando │  │Palindrome│  │ Rorschach│  │ Thovex │
  └─────────┘  └───────────┘  └──────────┘  └──────────┘  └────────┘
```

### 3.2 Class diagram — criteria (Strategy)

```
┌────────────────────────────────────────────────────────────────────────────┐
│ «abstract» ServiceCriterion                                              │
├────────────────────────────────────────────────────────────────────────────┤
│ + is_due(context : ServiceContext) : bool          «abstract»            │
│ + describe() : str                                 «abstract»            │
│ + __str__() : str                                                      │
└────────────────────────────────────────────────────────────────────────────┘
     ▲              ▲              ▲                 ▲              ▲
     │              │              │                 │              │
┌────┴─────┐  ┌─────┴──────┐  ┌────┴────────┐  ┌─────┴──────┐  ┌────┴──────┐
│Mileage   │  │Calendar    │  │WearThreshold│  │WarningLight│  │Any / All  │
│Criterion │  │Criterion   │  │Criterion    │  │Criterion   │  │Criterion  │
├──────────┤  ├────────────┤  ├─────────────┤  ├────────────┤  ├───────────┤
│interval_ │  │interval_   │  │threshold    │  │            │  │criteria   │
│miles     │  │years       │  │aggregation  │  │            │  │: Tuple    │
├──────────┤  ├────────────┤  ├─────────────┤  └────────────┘  └───────────┘
│is_due:   │  │is_due:     │  │is_due: MAX  │
│miles >   │  │current >   │  │  any >= thr │
│interval  │  │threshold   │  │  SUM >= thr │
└──────────┘  └────────────┘  └─────────────┘
```

### 3.3 Sequence diagram — inspecting a vehicle

```
Fleet/Caller      FleetMaintenanceService   CarFactory    Car     Engine  Criterion
      │                    │                    │           │       │        │
      │ build_inspection   │                    │           │       │        │
      │───────────────────>│                    │           │       │        │
      │                    │ create("calliope") │           │       │        │
      │                    │───────────────────>│           │       │        │
      │                    │                    │ new Car(  │       │        │
      │                    │                    │  engine,  │       │        │
      │                    │                    │  battery, │       │        │
      │                    │                    │  tire)    │       │        │
      │                    │                    │──────────>│       │        │
      │                    │ new ServiceContext(...)         │       │        │
      │<───────────────────│ VehicleInspection                │       │        │
      │                    │                    │           │       │        │
      │ inspect_fleet      │                    │           │       │        │
      │───────────────────>│ car.needs_service(ctx)          │       │        │
      │                    │─────────────────────────────────>│       │        │
      │                    │                    │ engine.needs_service(ctx)   │
      │                    │                    │           │──────>│        │
      │                    │                    │           │       │─is_due─>│
      │                    │                    │           │       │<───────│
      │                    │                    │           │<──────│        │
      │                    │                    │           │  (any criterion due?) │
      │<───────────────────│ ServiceReport     │           │       │        │
```

### 3.4 Sequence diagram — strategy swap (adding a rule)

```
Developer                    Engine                         NewCriterion
    │                            │                                 │
    │ define new criterion       │                                 │
    │─────────────────────────────────────────────────────────────>│
    │                            │                                 │
    │ inject into a component    │                                 │
    │────────────────────────────────────────────>│                │
    │                            │ criteria = (old, new)          │
    │                            │                                 │
    │ needs_service(ctx)         │                                 │
    │───────────────────────────>│                                 │
    │                            │────is_due(ctx)────────────────>│
    │                            │<───────────────────────────────│
```

---

## 4. Domain model

### 4.1 `Serviceable` — the shared contract

Every serviceable thing implements one method. This is the interface that decouples
the engine, battery and car components.

```python
class Serviceable(ABC):
    @abstractmethod
    def needs_service(self, context: ServiceContext) -> bool: ...

    def service_reasons(self, context: ServiceContext) -> tuple[str, ...]:
        return ()
```

`service_reasons` is an optional refinement: it explains *why* a service is due. The
base implementation returns an empty tuple, so a minimal implementation only needs
`needs_service`.

### 4.2 `ServiceContext` — the immutable readings snapshot

A frozen dataclass that carries every reading needed for a decision. Validating it
once, at construction, means no component ever has to re-check its inputs.

| Field | Type | Meaning | Constraint |
|---|---|---|---|
| `current_mileage` | `int` | Odometer reading now | `>= 0` |
| `last_service_mileage` | `int` | Odometer at last service | `0 <= x <= current_mileage` |
| `current_date` | `date` | Date of inspection | `>= last_service_date` |
| `last_service_date` | `date` | Date of last service | — |
| `tire_wear` | `tuple[float, ...]` | Per-wheel wear ratios | each in `[0.0, 1.0]` |
| `warning_light_on` | `bool` | Engine warning telltale | — |

Derived properties: `miles_since_service`, `days_since_service`, `max_tire_wear`,
`total_tire_wear`.

Invalid data raises `InvalidServiceContextError` immediately — a corrupted reading is
a bug that must surface at the boundary, not a silent service decision.

### 4.3 `Car` — the aggregate

```python
class Car(Serviceable):
    def __init__(self, engine, battery, tire, *, inspection_criteria=(), name="Car"): ...

    def needs_service(self, context: ServiceContext) -> bool:
        if any(component.needs_service(context) for component in self.components):
            return True
        return any(criterion.is_due(context) for criterion in self._inspection_criteria)
```

A vehicle needs service as soon as **one** of its systems is due. (The legacy code
mixed `and` and `or` across implementations — a vehicle with a healthy engine and a
dead battery is still unsafe to rent.)

---

## 5. Service criteria (Strategy)

Each criterion implements two methods and holds no state.

| Criterion | Fires when | Parameters |
|---|---|---|
| `MileageCriterion` | miles since last service **>** interval | `interval_miles` |
| `CalendarCriterion` | current date **>** last service + N years | `interval_years` |
| `WearThresholdCriterion` | sensor wear reaches the limit | `threshold`, `aggregation` |
| `WarningLightCriterion` | the engine warning light is on | — |
| `AnyCriterion` | any child criterion is due | `criteria` |
| `AllCriterion` | every child criterion is due | `criteria` |

### Aggregation modes

`WearThresholdCriterion` supports two ways of reading a set of wheel sensors:

| Mode | Rule | Used by |
|---|---|---|
| `Aggregation.MAX` | **any** single wheel at or above the threshold | Carrigan (0.9) |
| `Aggregation.SUM` | the **combined** wear at or above the threshold | Octoprime (3.0) |

The difference is real: a set at `[1.0, 0.5, 0.5, 0.5]` fails Carrigan but passes
Octoprime.

### Boundary semantics

All comparisons are **strictly greater** for distance and time, and **greater than or
equal** for wear. This is deliberate and matches the legacy wording:

* exactly 30 000 miles → **not** due (the rule says "more than 30 000");
* exactly 3 years → **not** due;
* wear exactly 0.9 → **due** ("at or above 0.9").

Every boundary is covered by a dedicated test.

### Calendar arithmetic

`add_years` clamps 29 February to 28 February in a non-leap target year instead of
raising, so a leap-day service date never crashes a maintenance decision.

---

## 6. Factories

### 6.1 `CarFactory`

```python
factory = CarFactory()
car = factory.create("calliope")        # -> Calliope
car = factory.create("CALLIOPE")        # case-insensitive
car = factory.create("call-iope")       # separators are ignored
car = factory.create("glissade")        # historical alias -> Glissando
cars = factory.create_many(["calliope", "thovex"])
```

Unknown names raise `UnknownComponentError` (a `KeyError` subclass) and the message
lists the available models.

### 6.2 Component factories

`EngineFactory`, `BatteryFactory` and `TireFactory` resolve a component name:

```python
EngineFactory().create("capulet")     # -> CapuletEngine
BatteryFactory().create("nubbin")     # -> NubbinBattery
TireFactory().create("octoprime")     # -> OctoprimeTire
```

### 6.3 Extending the registries

The factories are open registries — new entries are added at runtime, and the factory
code is never edited:

```python
factory = CarFactory()
factory.register("limo", Limo)                 # a new model
factory.register_alias("gliss", "glissando")   # a new spelling
```

### 6.4 `FleetMaintenanceService`

The application-layer entry point. It replaces the five duplicated
`create_<model>(current_date, last_service_date, current_mileage, last_service_mileage, wear)`
methods with one uniform call:

```python
service = FleetMaintenanceService()

inspection = service.build_inspection(
    "calliope",
    current_mileage=40_000,
    last_service_mileage=0,
    current_date=date(2024, 6, 1),
    last_service_date=date(2022, 6, 1),
    tire_wear=(0.1, 0.2, 0.3, 0.4),
    warning_light_on=False,
    vehicle_id="LYFT-1001",
)

report = service.inspect(inspection.vehicle, inspection.context)
print(report.needs_service)   # True
print(report.reasons)         # ('Engine Capulet: more than 30000 miles ...',)
```

`inspect_fleet` evaluates a whole fleet and returns one `ServiceReport` per vehicle.

---

## 7. Configuration reference

Every tunable threshold lives in `src/lyft_fleet/config.py`. There are no magic numbers
in the domain.

| Constant | Default | Meaning |
|---|---|---|
| `CAPULET_SERVICE_INTERVAL_MILES` | `30_000` | Capulet engine service interval |
| `WILLOUGHBY_SERVICE_INTERVAL_MILES` | `60_000` | Willoughby engine service interval |
| `NUBBIN_BATTERY_LIFETIME_YEARS` | `4` | Nubbin battery calendar lifetime |
| `SPINDLER_BATTERY_LIFETIME_YEARS` | `3` | Spindler battery calendar lifetime |
| `CARRIGAN_TIRE_WEAR_THRESHOLD` | `0.9` | Per-wheel Carrigan wear limit |
| `OCTOPRIME_TIRE_TOTAL_WEAR_THRESHOLD` | `3.0` | Combined Octoprime wear limit |
| `CALLIOPE_INSPECTION_INTERVAL_YEARS` | `2` | Calliope fleet inspection interval |
| `GLISSANDO_INSPECTION_INTERVAL_YEARS` | `2` | Glissando fleet inspection interval |
| `PALINDROME_INSPECTION_INTERVAL_YEARS` | `4` | Palindrome fleet inspection interval |
| `RORSCHACH_INSPECTION_INTERVAL_YEARS` | `4` | Rorschach fleet inspection interval |
| `THOVEX_INSPECTION_INTERVAL_YEARS` | `4` | Thovex fleet inspection interval |
| `MODEL_ALIASES` | `{"glissade": "glissando", "glissado": "glissando"}` | Historical model spellings |

### Runtime parameters

| Parameter | Type | Range / notes |
|---|---|---|
| `current_mileage` | `int` | `>= 0` |
| `last_service_mileage` | `int` | `0 <= x <= current_mileage` |
| `current_date` | `date` | `>= last_service_date` |
| `last_service_date` | `date` | any date |
| `tire_wear` | `tuple[float, ...]` | each value in `[0.0, 1.0]`; empty means "no sensor data" |
| `warning_light_on` | `bool` | `True`/`False` |
| `engine` / `battery` / `tire` | `Engine` / `Battery` / `Tire` | injected into `Car` |
| `inspection_criteria` | `tuple[ServiceCriterion, ...]` | car-level rules; defaults to the model's interval |

---

## 8. Public API reference

```python
from lyft_fleet import (
    # Domain
    Serviceable, ServiceContext,
    Engine, CapuletEngine, WilloughbyEngine, SternmanEngine,
    Battery, NubbinBattery, SpindlerBattery,
    Tire, CarriganTire, OctoprimeTire,
    Car, Calliope, Glissando, Palindrome, Rorschach, Thovex,
    # Strategy
    ServiceCriterion, MileageCriterion, CalendarCriterion,
    WearThresholdCriterion, WarningLightCriterion,
    AnyCriterion, AllCriterion, Aggregation,
    # Infrastructure
    CarFactory, EngineFactory, BatteryFactory, TireFactory,
    # Application
    FleetMaintenanceService, ServiceReport, VehicleInspection,
    # Errors
    FleetError, UnknownComponentError,
    InvalidServiceContextError, InvalidSpecificationError,
)
```

### Error hierarchy

```
FleetError
├── UnknownComponentError      (also a KeyError)   unknown model/part name
├── InvalidServiceContextError (also a ValueError) corrupted readings
└── InvalidSpecificationError  (also a ValueError) unusable component setup
```

---

## 9. Getting started

### Requirements

* Python **3.10+** (uses `X | Y` union syntax and `dataclass(frozen=True)`)
* `pytest` for the test suite

### Installation

```bash
# from the project root
python -m pip install -e ".[dev]"
```

Or run without installing, by adding `src` to the path (the test suite does this
automatically via `pyproject.toml`):

```bash
export PYTHONPATH=src        # Linux/macOS
set PYTHONPATH=src            # Windows CMD
$env:PYTHONPATH="src"         # PowerShell
```

### Demo

```bash
python scripts/demo.py
```

Sample output:

```
========================================================================
LYFT FLEET MAINTENANCE REPORT
Inspection date : 2024-06-01
Last service    : 2022-06-01
========================================================================
Calliope [LYFT-1001]: NEEDS SERVICE
  - Engine Capulet: more than 30000 miles driven since last service
------------------------------------------------------------------------
Glissando [LYFT-1002]: OK
------------------------------------------------------------------------
Palindrome [LYFT-1003]: NEEDS SERVICE
  - Engine Sternman: engine warning light is on
------------------------------------------------------------------------
Rorschach [LYFT-1004]: NEEDS SERVICE
  - Engine Willoughby: more than 60000 miles driven since last service
  - Tire Octoprime: combined wheel wear at or above 3.0
------------------------------------------------------------------------
Thovex [LYFT-1005]: NEEDS SERVICE
  - Tire Carrigan: any wheel wear at or above 0.9
------------------------------------------------------------------------
4 of 5 vehicles require a service.
========================================================================
```

### Library usage

```python
from datetime import date
from lyft_fleet import CarFactory, FleetMaintenanceService

service = FleetMaintenanceService(CarFactory())

inspection = service.build_inspection(
    "rorschach",
    current_mileage=95_000,
    last_service_mileage=0,
    current_date=date(2024, 6, 1),
    last_service_date=date(2022, 6, 1),
    tire_wear=(0.8, 0.8, 0.8, 0.8),
    vehicle_id="LYFT-1004",
)

for report in service.inspect_fleet([inspection]):
    print(report)
```

---

## 10. Running the tests

```bash
# Full suite with coverage
python -m pytest --cov=lyft_fleet --cov-report=term-missing

# Unit tests only
python -m pytest -m unit

# Integration tests only
python -m pytest -m integration

# Verbose, with a line per test
python -m pytest -v
```

### Quality gates

The project ships with the tooling configured in `pyproject.toml`:

```bash
python -m ruff check src tests scripts   # lint            -> All checks passed!
python -m mypy src                        # strict typing   -> Success: no issues found
python -m pytest --cov=lyft_fleet         # tests + coverage
```

### Current status

```
362 passed
TOTAL   638 statements   0 missed   108 branches   0 partial   100% coverage
ruff:  All checks passed!
mypy:  Success: no issues found in 16 source files
```

### Test layout

| File | Focus |
|---|---|
| `tests/test_value_objects.py` | `ServiceContext` validation, derived values, immutability |
| `tests/test_criteria.py` | Every strategy, boundaries, composition, contract |
| `tests/test_engine.py` | Capulet / Willoughby / Sternman rules and edge cases |
| `tests/test_battery.py` | Nubbin / Spindler calendar lifetimes |
| `tests/test_tire.py` | Carrigan / Octoprime wear thresholds and aggregation |
| `tests/test_car.py` | **All five models**, aggregate logic, extensibility |
| `tests/test_factory.py` | Registries, name normalisation, aliases, errors |
| `tests/test_fleet_service.py` | Application use cases and end-to-end flows |
| `tests/test_contracts.py` | Public API surface, error hierarchy, configuration |

### Edge cases covered

* Exact threshold boundaries (mileage, calendar, wear) — both sides of each edge.
* Zero-distance and zero-time service intervals.
* Leap-day service dates (`29 Feb` → `28 Feb` clamping).
* Missing tyre sensor data (a rule cannot trip without data).
* Out-of-range and non-numeric sensor readings.
* Negative and non-integer mileage, `bool` masquerading as `int`.
* Odometer rollback (`last_service_mileage > current_mileage`).
* A service date in the future.
* Empty rule sets and non-criterion objects injected into components.
* Unknown model / component names, including the error message contents.
* Duplicate registrations and aliasing an unknown model.
* Every model healthy, and each model failing through each of its three systems.
* The combined-vs-single-wheel tyre wear distinction.
* Immutability of contexts, components and cars.

---

## 11. Extending the system

### 11.1 Add a new criterion (new rule)

A criterion reads whatever it needs from the context. Using the readings that already
exist:

```python
from lyft_fleet.domain.criteria import ServiceCriterion

class FrequentServiceCriterion(ServiceCriterion):
    """Service when the vehicle has been driven at all since a long inspection."""

    def is_due(self, context) -> bool:
        return context.days_since_service > 730 and context.miles_since_service > 0

    def describe(self) -> str:
        return "driven since the last long inspection"
```

To read a *new* signal, add it to `ServiceContext` first (a frozen dataclass field with
a validation rule in `__post_init__`), then implement the criterion against it.

Inject the criterion anywhere a criterion is accepted:

```python
engine = Engine((FrequentServiceCriterion(), MileageCriterion(30_000)), name="Capulet")
```

No existing class is modified.

### 11.2 Add a new component

```python
from lyft_fleet.domain.components.engine import Engine
from lyft_fleet.domain.criteria import MileageCriterion

class HybridEngine(Engine):
    def __init__(self, interval_miles: int = 40_000) -> None:
        super().__init__((MileageCriterion(interval_miles),), name="Hybrid")
```

### 11.3 Add a new model

```python
from lyft_fleet.domain.car import _ModelCar
from lyft_fleet.domain.components.engine import CapuletEngine
from lyft_fleet.domain.components.battery import NubbinBattery
from lyft_fleet.domain.components.tire import CarriganTire

class Limo(_ModelCar):
    INSPECTION_INTERVAL_YEARS = 0   # no periodic inspection

    def __init__(self) -> None:
        super().__init__(
            CapuletEngine(),
            NubbinBattery(),
            CarriganTire(),
            inspection_criteria=self._default_inspection_criteria(),
            name="Limo",
        )
```

Register it so callers can build it by name:

```python
CarFactory().register("limo", Limo)
```

### 11.4 Add a new model component

```python
from lyft_fleet.domain.components.tire import Tire
from lyft_fleet.domain.criteria import WearThresholdCriterion, Aggregation

class EnduranceTire(Tire):
    def __init__(self, threshold: float = 0.95) -> None:
        super().__init__((WearThresholdCriterion(threshold, Aggregation.MAX),), name="Endurance")
```

### 11.5 Change a business threshold

Edit the constant in `config.py` — no domain code changes, and the test suite verifies
the new value.

---

## 12. Design decisions and trade-offs

| Decision | Rationale | Trade-off |
|---|---|---|
| **Composition over inheritance for models** | A car *has* an engine; it is not one. Avoids the "car is an engine" type error and duplicated rules. | Slightly more verbose model declarations. |
| **Rules as strategies, not subclass overrides** | One rule = one small, testable, reusable object. New rules need no new class hierarchy. | More objects; a component holds a tuple of criteria. |
| **`ServiceContext` instead of constructor data** | Components become stateless and reusable across inspections; the clock and odometer are explicit inputs. | One extra parameter at every call site. |
| **Frozen dataclasses** | Immutability removes a whole class of bugs and makes the domain trivially thread-safe. | Slightly more verbose construction. |
| **Registry-based factories** | Extensibility without modifying factory code; supports aliases and custom models. | Slightly more machinery than a `switch` statement. |
| **Strict `>` for distance and time** | Matches the legacy business wording ("more than 30 000 miles"). | The boundary needs an explicit test — it has one. |
| **`>=` for wear** | Matches "at or above 0.9" and fails safe on the worn side. | Documented and tested explicitly. |
| **A car is due if *any* part is due** | A vehicle with one failed system is still unfit to rent. The legacy code mixed `and`/`or`. | Slightly more service traffic than the `and` variant. |
| **Empty tyre-wear data never trips a rule** | Absent telemetry is not evidence of wear; it is missing data. The alternative (assume worst case) would over-service the fleet. | Requires a separate "no data" monitoring path in production. |
| **Validated `ServiceContext`** | Corrupt readings fail at the boundary rather than producing a silent, wrong service decision. | Callers must construct valid data. |
| **`_ModelCar` is private** | The five shipped models are the supported set; the base exists to avoid repeating the inspection-interval logic. | Custom models outside the package import a private name — acceptable for this exercise. |

### Known limitations / future work

* The domain is in-memory only; a persistence adapter (vehicle records, service
  history) is not implemented.
* `add_years` handles the leap-day clamp but not time zones — the domain uses naive
  `date` objects, which is correct for calendar intervals.
* Service scheduling (booking a garage slot) is out of scope; the domain reports
  *what* is due, not *when* to book it.
* A rule-per-mileage-and-calendar *combination* (e.g. "service every 10 000 miles
  *and* every year") is expressible via `AllCriterion` but is not used by any shipped
  model.

---

## 13. Project layout

```
Lyft-Fleet-Engine-Refactoring/
├── README.md                       ← this document
├── pyproject.toml                  ← project metadata, pytest/coverage/ruff/mypy config
├── task.md                         ← original task statement
├── scripts/
│   ├── demo.py                     ← runnable end-to-end demonstration
│   ├── smoke_check.py              ← quick import/sanity check
│   └── verify_readme.py            ← executes every code example in this README
├── src/
│   └── lyft_fleet/
│       ├── __init__.py             ← public API surface
│       ├── config.py               ← all tunable thresholds
│       ├── errors.py               ← exception hierarchy
│       ├── domain/
│       │   ├── __init__.py
│       │   ├── serviceable.py      ← Serviceable contract
│       │   ├── criteria.py         ← ServiceCriterion + strategies
│       │   ├── value_objects.py    ← ServiceContext
│       │   ├── car.py              ← Car aggregate + 5 models
│       │   └── components/
│       │       ├── __init__.py
│       │       ├── engine.py       ← Engine, Capulet, Willoughby, Sternman
│       │       ├── battery.py      ← Battery, Nubbin, Spindler
│       │       └── tire.py         ← Tire, Carrigan, Octoprime
│       ├── application/
│       │   ├── __init__.py
│       │   └── fleet_service.py    ← FleetMaintenanceService, ServiceReport
│       └── infrastructure/
│           ├── __init__.py
│           └── factory.py          ← Car/Engine/Battery/Tire factories
└── tests/
    ├── conftest.py                 ← shared fixtures
    ├── test_value_objects.py
    ├── test_criteria.py
    ├── test_engine.py
    ├── test_battery.py
    ├── test_tire.py
    ├── test_car.py
    ├── test_factory.py
    ├── test_fleet_service.py
    └── test_contracts.py
```

---

## License

MIT

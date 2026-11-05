"""High-performance ``2**k``-ary priority queue for warehouse logistics.

Public surface
--------------
:class:`KaryHeap`
    The generic power-of-two ary min/max heap.
:class:`DispatchEngine`
    The priority-driven dispatch simulation built on top of the heap.
:func:`SimulationRunner`
    Compose a workload source with the engine and run a full simulation.

Quick start
-----------
>>> from walmart_logistics import KaryHeap
>>> heap = KaryHeap[int](arity_exponent=3)
>>> for value in (7, 2, 9, 4):
...     heap.push(value)
>>> heap.pop()
2
"""

from __future__ import annotations

from walmart_logistics.application.dispatch_engine import (
    DispatchEngine,
    DispatchMetrics,
    SimulationResult,
    SimulationRunner,
)
from walmart_logistics.application.ports import WorkloadSource
from walmart_logistics.config import DispatchConfig
from walmart_logistics.data_structures.kary_heap import KaryHeap
from walmart_logistics.domain.entities import (
    DispatchPlan,
    DispatchPolicy,
    ExpressFirstPolicy,
    PackageRequest,
    PriorityClass,
    SlaUrgencyPolicy,
    SmallestFirstPolicy,
    TruckLoadEvent,
    Zone,
    build_policy,
)
from walmart_logistics.errors import (
    ConfigurationError,
    EmptyHeapError,
    InvalidArityError,
    InvalidPriorityError,
    LogisticsError,
    SimulationError,
)

__version__ = "1.0.0"

__all__ = [
    "ConfigurationError",
    "DispatchConfig",
    "DispatchEngine",
    "DispatchMetrics",
    "DispatchPlan",
    "DispatchPolicy",
    "EmptyHeapError",
    "ExpressFirstPolicy",
    "InvalidArityError",
    "InvalidPriorityError",
    "KaryHeap",
    "LogisticsError",
    "PackageRequest",
    "PriorityClass",
    "SimulationError",
    "SimulationResult",
    "SimulationRunner",
    "SlaUrgencyPolicy",
    "SmallestFirstPolicy",
    "TruckLoadEvent",
    "WorkloadSource",
    "Zone",
    "__version__",
    "build_policy",
]

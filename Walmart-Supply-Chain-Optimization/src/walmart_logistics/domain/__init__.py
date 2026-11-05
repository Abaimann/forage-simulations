"""Domain layer: value objects and dispatch policies.

The domain layer has **no** dependency on any other layer.  It only
describes the business objects of the fulfillment network and the rules
that decide which package is dispatched first.
"""

from __future__ import annotations

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

__all__ = [
    "DispatchPlan",
    "DispatchPolicy",
    "ExpressFirstPolicy",
    "PackageRequest",
    "PriorityClass",
    "SlaUrgencyPolicy",
    "SmallestFirstPolicy",
    "TruckLoadEvent",
    "Zone",
    "build_policy",
]

"""Ports (protocols) implemented by the infrastructure layer.

Defining the contract in the *application* layer and the implementation in
the *infrastructure* layer keeps the dependency arrow pointing inwards, as
required by the clean architecture.
"""

from __future__ import annotations

from collections.abc import Sequence
from typing import Protocol, runtime_checkable

from walmart_logistics.config import DispatchConfig
from walmart_logistics.domain.entities import PackageRequest, TruckLoadEvent

__all__ = ["WorkloadSource"]


@runtime_checkable
class WorkloadSource(Protocol):
    """Source of the arrivals and truck events of a simulation.

    Implementations must be deterministic for a given configuration so
    that a simulation can be replayed exactly.
    """

    def packages(self, config: DispatchConfig) -> Sequence[PackageRequest]:
        """Return the package arrivals ordered by arrival time."""
        raise NotImplementedError

    def trucks(self, config: DispatchConfig) -> Sequence[TruckLoadEvent]:
        """Return the truck loading events ordered by docking time."""
        raise NotImplementedError

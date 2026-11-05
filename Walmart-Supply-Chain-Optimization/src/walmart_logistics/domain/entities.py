"""Domain entities of the warehouse dispatch domain.

The domain layer is pure: it contains value objects and the policies that
decide *which* package is dispatched next.  It knows nothing about heaps,
timers or randomness — those live in the upper layers.

Layering (dependencies point inwards only)::

    infrastructure  ->  application  ->  domain
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum

__all__ = [
    "DispatchPolicy",
    "ExpressFirstPolicy",
    "PackageRequest",
    "PriorityClass",
    "SlaUrgencyPolicy",
    "TruckLoadEvent",
    "Zone",
    "build_policy",
]


class PriorityClass(Enum):
    """Service tier of a package inside the fulfillment network."""

    EXPRESS = "express"
    STANDARD = "standard"
    ECONOMY = "economy"

    @property
    def base_weight(self) -> int:
        """Static dispatch weight of the tier (higher = more urgent)."""
        return _PRIORITY_WEIGHTS[self]

    def __str__(self) -> str:
        return self.value


_PRIORITY_WEIGHTS: dict[PriorityClass, int] = {
    PriorityClass.EXPRESS: 3,
    PriorityClass.STANDARD: 2,
    PriorityClass.ECONOMY: 1,
}


class Zone(Enum):
    """Geographical zone of a distribution center."""

    NORTH = "north"
    SOUTH = "south"
    EAST = "east"
    WEST = "west"
    CENTRAL = "central"

    def __str__(self) -> str:
        return self.value


@dataclass(frozen=True, slots=True)
class PackageRequest:
    """A fulfillment request waiting to be loaded onto a truck.

    Attributes:
        package_id: Unique identifier of the request.
        arrival_time: Simulation timestamp of the arrival (seconds).
        sla_deadline: Simulation timestamp after which the request is late.
        priority: Service tier of the request.
        size: Number of loading slots the package consumes.
        zone: Destination zone.
    """

    package_id: str
    arrival_time: float
    sla_deadline: float
    priority: PriorityClass
    size: int = 1
    zone: Zone = Zone.CENTRAL

    @property
    def slack(self) -> float:
        """Seconds remaining before the SLA deadline (may be negative)."""
        return self.sla_deadline - self.arrival_time

    def is_late_at(self, now: float) -> bool:
        """Return ``True`` when the SLA has been breached at time ``now``."""
        return now > self.sla_deadline


@dataclass(frozen=True, slots=True)
class TruckLoadEvent:
    """A truck that becomes available for loading at a point in time.

    Attributes:
        truck_id: Unique identifier of the truck.
        ready_time: Simulation timestamp when the truck docks.
        capacity: Number of loading slots the truck offers.
        zone: Zone the truck serves.
    """

    truck_id: str
    ready_time: float
    capacity: int
    zone: Zone = Zone.CENTRAL


class DispatchPolicy:
    """Strategy deciding the dispatch order of waiting packages.

    A policy maps a package to an *urgency score*.  Higher scores are
    dispatched first, which maps directly onto a max-heap.  The dispatch
    engine never inspects the policy internals, so alternative strategies
    (expedite-first, SLA-urgency, load-balancing) can be swapped freely.
    """

    #: Human readable identifier used in reports and configuration.
    name: str = "base"

    def urgency(self, package: PackageRequest) -> float:
        """Return the urgency score of ``package`` (higher = dispatched first)."""
        raise NotImplementedError

    def __repr__(self) -> str:  # pragma: no cover - debugging helper
        return f"{type(self).__name__}(name={self.name!r})"


class ExpressFirstPolicy(DispatchPolicy):
    """Dispatch by service tier first, then by arrival order (FIFO).

    The score is a large tier component plus a small tie-breaker that keeps
    the ordering stable and reproducible for packages of the same tier.
    """

    name = "express_first"

    _TIER_SCALE = 1_000_000.0

    def urgency(self, package: PackageRequest) -> float:
        """Return the urgency score of ``package`` (higher = dispatched first)."""
        tier = package.priority.base_weight
        return tier * self._TIER_SCALE + (package.sla_deadline - package.arrival_time)


class SlaUrgencyPolicy(DispatchPolicy):
    """Dispatch by service tier first, then by remaining slack.

    The tier weight dominates the score, so an express package is always
    dispatched before an economy package; within a tier the package whose
    deadline is closest wins.  The tier bonus is deliberately much larger
    than the widest SLA window so the ordering stays stable.
    """

    name = "sla_urgency"

    _TIER_BONUS = 10_000.0

    def urgency(self, package: PackageRequest) -> float:
        """Return the urgency score of ``package`` (higher = dispatched first)."""
        slack = package.sla_deadline - package.arrival_time
        return package.priority.base_weight * self._TIER_BONUS - slack


class SmallestFirstPolicy(DispatchPolicy):
    """Dispatch small packages first to maximise truck utilisation.

    This policy is deliberately *not* SLA aware: it exists to demonstrate
    that the engine is decoupled from the ordering strategy.
    """

    name = "smallest_first"

    def urgency(self, package: PackageRequest) -> float:
        """Return the urgency score of ``package`` (higher = dispatched first)."""
        return -float(package.size)


_POLICY_REGISTRY: dict[str, type[DispatchPolicy]] = {
    ExpressFirstPolicy.name: ExpressFirstPolicy,
    SlaUrgencyPolicy.name: SlaUrgencyPolicy,
    SmallestFirstPolicy.name: SmallestFirstPolicy,
}


def build_policy(name: str) -> DispatchPolicy:
    """Instantiate a policy by name.

    Args:
        name: One of ``express_first``, ``sla_urgency`` or ``smallest_first``.

    Returns:
        A fresh policy instance.

    Raises:
        ValueError: If ``name`` is unknown.
    """
    try:
        policy_cls = _POLICY_REGISTRY[name]
    except KeyError:
        known = ", ".join(sorted(_POLICY_REGISTRY))
        raise ValueError(f"unknown dispatch policy {name!r}; expected one of: {known}") from None
    return policy_cls()


@dataclass(slots=True)
class DispatchPlan:
    """Result of one dispatch round of the engine.

    Attributes:
        truck_id: Truck that received the packages.
        packages: Packages assigned to the truck, in loading order.
        unused_capacity: Remaining slots on the truck after loading.
        wait_times: Wait time (seconds) of each assigned package.
    """

    truck_id: str
    packages: list[PackageRequest] = field(default_factory=list)
    unused_capacity: int = 0
    wait_times: list[float] = field(default_factory=list)

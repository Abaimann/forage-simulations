"""Application layer: the dispatch engine and the simulation runner.

The engine is a deterministic discrete-event simulation.  It is completely
independent from the heap implementation detail — it only depends on the
:class:`~walmart_logistics.data_structures.kary_heap.KaryHeap` public
contract, which is what makes the structure swappable (e.g. with
:mod:`heapq`) without touching the business rules.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from walmart_logistics.application.ports import WorkloadSource
from walmart_logistics.config import DispatchConfig
from walmart_logistics.data_structures.kary_heap import KaryHeap
from walmart_logistics.domain.entities import (
    DispatchPlan,
    DispatchPolicy,
    PackageRequest,
    TruckLoadEvent,
    build_policy,
)

__all__ = [
    "DispatchEngine",
    "DispatchMetrics",
    "SimulationResult",
    "SimulationRunner",
]


@dataclass(frozen=True, slots=True)
class DispatchMetrics:
    """Aggregated outcome of a dispatch simulation.

    Attributes:
        packages_arrived: Number of packages that entered the queue.
        packages_dispatched: Number of packages loaded onto a truck.
        packages_pending: Packages still waiting when the simulation ended.
        packages_late: Dispatched packages that missed their SLA.
        on_time_ratio: Share of dispatched packages shipped before their SLA
            deadline (``0.0`` when nothing shipped).
        average_wait: Mean wait time of the dispatched packages, in seconds.
        max_wait: Longest wait time observed, in seconds.
        trucks_used: Number of trucks that received at least one package.
        peak_queue_depth: Maximum number of packages waiting simultaneously.
        total_capacity_used: Sum of the loading slots consumed.
    """

    packages_arrived: int
    packages_dispatched: int
    packages_pending: int
    packages_late: int
    on_time_ratio: float
    average_wait: float
    max_wait: float
    trucks_used: int
    peak_queue_depth: int
    total_capacity_used: int


@dataclass(frozen=True, slots=True)
class SimulationResult:
    """Full result of a dispatch simulation.

    Attributes:
        metrics: Aggregated KPI values.
        plans: One entry per truck that received at least one package.
        config: The configuration the simulation ran with.
    """

    metrics: DispatchMetrics
    plans: list[DispatchPlan] = field(default_factory=list)
    config: DispatchConfig | None = None


class DispatchEngine:
    """Priority-driven dispatcher for a warehouse fulfillment center.

    Packages are pushed into a ``2**k``-ary **max**-heap ordered by the
    urgency score of the configured :class:`DispatchPolicy`.  Whenever a
    truck docks, the engine repeatedly pops the most urgent package that
    still fits into the remaining capacity.

    Args:
        config: Simulation parameters.  Defaults to :class:`DispatchConfig`.
        policy: Dispatch ordering strategy.  Defaults to the policy named in
            the configuration.

    Example:
        >>> from walmart_logistics.config import DispatchConfig
        >>> from walmart_logistics.domain.entities import TruckLoadEvent
        >>> engine = DispatchEngine(DispatchConfig(packages=3, trucks=1))
        >>> result = engine.run([], [TruckLoadEvent("T1", 0.0, 10)])
        >>> result.metrics.packages_dispatched
        0
    """

    #: Maximum number of packages inspected while looking for one that fits.
    LOOKAHEAD_LIMIT = 64

    def __init__(
        self,
        config: DispatchConfig | None = None,
        policy: DispatchPolicy | None = None,
    ) -> None:
        self._config = config if config is not None else DispatchConfig()
        self._policy = policy if policy is not None else build_policy(self._config.policy)
        self._queue = self._new_queue()

    # ------------------------------------------------------------------
    # Properties
    # ------------------------------------------------------------------
    @property
    def config(self) -> DispatchConfig:
        """The configuration this engine was built with."""
        return self._config

    @property
    def policy(self) -> DispatchPolicy:
        """The dispatch policy in use."""
        return self._policy

    @property
    def queue_depth(self) -> int:
        """Number of packages currently waiting."""
        return len(self._queue)

    # ------------------------------------------------------------------
    # Core API
    # ------------------------------------------------------------------
    def enqueue(self, package: PackageRequest) -> None:
        """Add a package to the waiting queue."""
        self._queue.push(package)

    def dispatch_truck(self, truck: TruckLoadEvent) -> DispatchPlan:
        """Load a truck with the most urgent waiting packages.

        The truck is filled until its capacity or the per-truck package cap
        is exhausted, or until no queued package fits any more.

        Packages that do not fit are set aside and re-queued once the
        loading round ends, so a single oversized express package never
        blocks the whole queue.  At most :attr:`LOOKAHEAD_LIMIT` packages
        are inspected per round, which keeps the operation bounded.

        Args:
            truck: The truck that docked.

        Returns:
            A :class:`DispatchPlan` describing what was loaded.
        """
        plan = DispatchPlan(truck_id=truck.truck_id)
        capacity = min(truck.capacity, self._config.max_packages_per_truck)
        deferred: list[PackageRequest] = []
        inspected = 0
        while capacity > 0 and self._queue and inspected < self.LOOKAHEAD_LIMIT:
            inspected += 1
            package = self._queue.pop()
            if package.size > capacity:
                deferred.append(package)
                continue
            plan.packages.append(package)
            plan.wait_times.append(max(0.0, truck.ready_time - package.arrival_time))
            capacity -= package.size
        for package in deferred:
            self._queue.push(package)
        plan.unused_capacity = capacity
        return plan

    def run(
        self,
        packages: list[PackageRequest],
        trucks: list[TruckLoadEvent],
    ) -> SimulationResult:
        """Execute the full simulation.

        Args:
            packages: The package arrivals.  They are re-ordered by arrival
                time internally, so the caller may pass them in any order.
            trucks: The truck loading events.

        Returns:
            A :class:`SimulationResult` with the aggregated metrics.
        """
        self._queue = self._new_queue()
        plans: list[DispatchPlan] = []
        dispatched = 0
        late = 0
        waits: list[float] = []
        max_wait = 0.0
        capacity_used = 0
        peak_depth = 0
        trucks_used = 0

        # Merge arrivals and truck events on a single timeline.  Arrivals
        # are processed before a truck docking at the same timestamp.
        events: list[tuple[float, int, int]] = []
        for index, package in enumerate(packages):
            events.append((package.arrival_time, 0, index))
        for index, truck in enumerate(trucks):
            events.append((truck.ready_time, 1, index))
        events.sort(key=lambda event: (event[0], event[1], event[2]))

        for _time, kind, payload in events:
            if kind == 0:
                self.enqueue(packages[payload])
                depth = len(self._queue)
                if depth > peak_depth:
                    peak_depth = depth
                continue

            truck = trucks[payload]
            plan = self.dispatch_truck(truck)
            if not plan.packages:
                continue
            trucks_used += 1
            plans.append(plan)
            dispatched += len(plan.packages)
            capacity_used += sum(package.size for package in plan.packages)
            for package, wait in zip(plan.packages, plan.wait_times, strict=True):
                waits.append(wait)
                if wait > max_wait:
                    max_wait = wait
                if truck.ready_time > package.sla_deadline:
                    late += 1

        average_wait = (sum(waits) / len(waits)) if waits else 0.0
        on_time_ratio = ((dispatched - late) / dispatched) if dispatched else 0.0
        metrics = DispatchMetrics(
            packages_arrived=len(packages),
            packages_dispatched=dispatched,
            packages_pending=len(self._queue),
            packages_late=late,
            on_time_ratio=on_time_ratio,
            average_wait=average_wait,
            max_wait=max_wait,
            trucks_used=trucks_used,
            peak_queue_depth=peak_depth,
            total_capacity_used=capacity_used,
        )
        return SimulationResult(metrics=metrics, plans=plans, config=self._config)

    # ------------------------------------------------------------------
    # Internals
    # ------------------------------------------------------------------
    def _new_queue(self) -> KaryHeap[PackageRequest]:
        """Create the waiting queue (a max-heap on the policy urgency)."""
        return KaryHeap(
            self._config.arity_exponent,
            key=self._policy.urgency,
            reverse=True,
        )


class SimulationRunner:
    """Compose a workload source with the dispatch engine.

    This is the application-level entry point used by the CLI, the demo
    script and the tests.

    Args:
        config: Simulation parameters.
        policy: Optional dispatch policy override.
        source: The workload source.  Defaults to the deterministic
            synthetic source shipped with the infrastructure layer.
    """

    def __init__(
        self,
        config: DispatchConfig | None = None,
        policy: DispatchPolicy | None = None,
        source: WorkloadSource | None = None,
    ) -> None:
        self._config = config if config is not None else DispatchConfig()
        self._policy = policy if policy is not None else build_policy(self._config.policy)
        if source is None:
            from walmart_logistics.infrastructure.workload import SyntheticWorkloadSource

            source = SyntheticWorkloadSource()
        self._source = source
        self._engine = DispatchEngine(self._config, self._policy)

    @property
    def engine(self) -> DispatchEngine:
        """The underlying dispatch engine."""
        return self._engine

    def run(self) -> SimulationResult:
        """Generate the workload and execute the simulation."""
        packages = list(self._source.packages(self._config))
        trucks = list(self._source.trucks(self._config))
        return self._engine.run(packages, trucks)

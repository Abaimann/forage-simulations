"""Infrastructure layer: deterministic synthetic workload generation.

The generator is seeded, so the same configuration always produces the
exact same arrivals and truck events.  That determinism is what makes the
simulation results reproducible and the tests meaningful.
"""

from __future__ import annotations

import random

from walmart_logistics.config import DispatchConfig
from walmart_logistics.domain.entities import (
    PackageRequest,
    PriorityClass,
    TruckLoadEvent,
    Zone,
)

__all__ = ["SyntheticWorkloadSource", "build_package", "build_truck"]

_PRIORITY_WEIGHTS: tuple[tuple[PriorityClass, float], ...] = (
    (PriorityClass.EXPRESS, 0.15),
    (PriorityClass.STANDARD, 0.55),
    (PriorityClass.ECONOMY, 0.30),
)

_ZONES: tuple[Zone, ...] = tuple(Zone)


def _weighted_priority(rng: random.Random) -> PriorityClass:
    """Draw a service tier according to the configured distribution."""
    roll = rng.random()
    cumulative = 0.0
    for tier, weight in _PRIORITY_WEIGHTS:
        cumulative += weight
        if roll < cumulative:
            return tier
    # The weights sum to 1.0, so this is only reachable through floating
    # point rounding at the very top of the range.
    return PriorityClass.ECONOMY  # pragma: no cover - defensive


def _derive_seed(*parts: int) -> int:
    """Derive a reproducible 64-bit seed from integer parts.

    ``hash()`` is avoided on purpose: it is only stable for integer inputs
    across runs, but an explicit derivation documents the intent and cannot
    be broken by a future hash randomisation policy.
    """
    seed = 0x9E3779B97F4A7C15
    for part in parts:
        seed = (seed ^ (part & 0xFFFFFFFFFFFFFFFF)) * 0x100000001B3
        seed &= 0xFFFFFFFFFFFFFFFF
    return seed


def build_package(
    index: int,
    arrival_time: float,
    config: DispatchConfig,
    rng: random.Random | None = None,
) -> PackageRequest:
    """Build a single package arrival.

    Args:
        index: Sequence number of the arrival.
        arrival_time: Timestamp of the arrival.
        config: Simulation parameters.
        rng: Optional random source.  When omitted a deterministic source
            derived from ``index`` and the configuration seed is used.

    Returns:
        The generated package.
    """
    source = rng if rng is not None else random.Random(_derive_seed(config.seed, index))
    sla_window = source.uniform(config.sla_min, config.sla_max)
    size = source.randint(1, 3)
    zone = _ZONES[source.randrange(len(_ZONES))]
    return PackageRequest(
        package_id=f"PKG-{index:07d}",
        arrival_time=arrival_time,
        sla_deadline=arrival_time + sla_window,
        priority=_weighted_priority(source),
        size=size,
        zone=zone,
    )


def build_truck(
    index: int,
    ready_time: float,
    config: DispatchConfig,
    rng: random.Random | None = None,
) -> TruckLoadEvent:
    """Build a single truck loading event.

    Args:
        index: Sequence number of the truck.
        ready_time: Timestamp at which the truck docks.
        config: Simulation parameters.
        rng: Optional random source.

    Returns:
        The generated truck event.
    """
    source = rng if rng is not None else random.Random(_derive_seed(config.seed, index, 7))
    capacity = source.randint(config.truck_capacity_min, config.truck_capacity_max)
    zone = _ZONES[source.randrange(len(_ZONES))]
    return TruckLoadEvent(
        truck_id=f"TRK-{index:05d}",
        ready_time=ready_time,
        capacity=capacity,
        zone=zone,
    )


class SyntheticWorkloadSource:
    """Deterministic generator of arrivals and truck events.

    Example:
        >>> from walmart_logistics.config import DispatchConfig
        >>> source = SyntheticWorkloadSource()
        >>> config = DispatchConfig(packages=3, trucks=2)
        >>> len(source.packages(config))
        3
    """

    def packages(self, config: DispatchConfig) -> list[PackageRequest]:
        """Return ``config.packages`` arrivals ordered by arrival time."""
        if config.packages <= 0:
            return []
        rng = random.Random(config.seed)
        times = sorted(
            rng.uniform(0.0, config.arrival_window) for _ in range(config.packages)
        )
        package_rng = random.Random(config.seed + 1)
        return [
            build_package(index, time, config, package_rng)
            for index, time in enumerate(times)
        ]

    def trucks(self, config: DispatchConfig) -> list[TruckLoadEvent]:
        """Return ``config.trucks`` docking events ordered by ready time."""
        if config.trucks <= 0:
            return []
        rng = random.Random(config.seed + 2)
        times = sorted(
            rng.uniform(config.truck_ready_min, config.truck_ready_max)
            for _ in range(config.trucks)
        )
        truck_rng = random.Random(config.seed + 3)
        return [
            build_truck(index, time, config, truck_rng)
            for index, time in enumerate(times)
        ]
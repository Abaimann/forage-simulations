"""Immutable configuration objects for the dispatch simulation.

Configuration is validated on construction so that an invalid simulation
can never start; the simulation engine therefore never has to re-check
its own inputs.
"""

from __future__ import annotations

from dataclasses import dataclass

from walmart_logistics.errors import ConfigurationError

__all__ = ["DispatchConfig"]


@dataclass(frozen=True, slots=True)
class DispatchConfig:
    """Parameters of a warehouse dispatch simulation.

    Attributes:
        packages: Number of package arrivals to generate.
        trucks: Number of truck loading events to generate.
        arity_exponent: ``k`` of the ``2**k``-ary heap backing the queue.
        policy: Name of the dispatch policy (see
            :func:`walmart_logistics.domain.entities.build_policy`).
        seed: Seed of the deterministic random generator.
        arrival_window: Simulation time span covered by the arrivals.
        sla_min / sla_max: Bounds of the randomly drawn SLA window.
        truck_capacity_min / truck_capacity_max: Bounds of the truck capacity.
        truck_ready_min / truck_ready_max: Bounds of the truck docking time.
        max_packages_per_truck: Hard cap of packages loaded onto one truck.
    """

    packages: int = 5_000
    trucks: int = 250
    arity_exponent: int = 3
    policy: str = "express_first"
    seed: int = 20240
    arrival_window: float = 3_600.0
    sla_min: float = 300.0
    sla_max: float = 1_800.0
    truck_capacity_min: int = 20
    truck_capacity_max: int = 60
    truck_ready_min: float = 0.0
    truck_ready_max: float = 3_600.0
    max_packages_per_truck: int = 60

    def __post_init__(self) -> None:
        if self.packages < 0:
            raise ConfigurationError(f"packages must be >= 0, got {self.packages}")
        if self.trucks < 0:
            raise ConfigurationError(f"trucks must be >= 0, got {self.trucks}")
        if self.arity_exponent < 1:
            raise ConfigurationError(
                f"arity_exponent must be >= 1 (arity = 2**k), got {self.arity_exponent}"
            )
        if self.arrival_window <= 0:
            raise ConfigurationError(
                f"arrival_window must be > 0, got {self.arrival_window}"
            )
        if self.sla_min <= 0:
            raise ConfigurationError(f"sla_min must be > 0, got {self.sla_min}")
        if self.sla_max < self.sla_min:
            raise ConfigurationError(
                f"sla_max ({self.sla_max}) must be >= sla_min ({self.sla_min})"
            )
        if self.truck_capacity_min <= 0:
            raise ConfigurationError(
                f"truck_capacity_min must be > 0, got {self.truck_capacity_min}"
            )
        if self.truck_capacity_max < self.truck_capacity_min:
            raise ConfigurationError(
                f"truck_capacity_max ({self.truck_capacity_max}) must be >= "
                f"truck_capacity_min ({self.truck_capacity_min})"
            )
        if self.truck_ready_min < 0:
            raise ConfigurationError(
                f"truck_ready_min must be >= 0, got {self.truck_ready_min}"
            )
        if self.truck_ready_max < self.truck_ready_min:
            raise ConfigurationError(
                f"truck_ready_max ({self.truck_ready_max}) must be >= "
                f"truck_ready_min ({self.truck_ready_min})"
            )
        if self.max_packages_per_truck <= 0:
            raise ConfigurationError(
                f"max_packages_per_truck must be > 0, got {self.max_packages_per_truck}"
            )

    @property
    def arity(self) -> int:
        """Number of children per node (``2**arity_exponent``)."""
        return 1 << self.arity_exponent

    def with_overrides(self, **overrides: object) -> DispatchConfig:
        """Return a copy of this configuration with ``overrides`` applied.

        Raises:
            ConfigurationError: If the resulting configuration is invalid.
        """
        from dataclasses import replace

        return replace(self, **overrides)  # type: ignore[arg-type]

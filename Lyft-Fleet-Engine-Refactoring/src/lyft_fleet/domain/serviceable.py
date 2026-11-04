"""The ``Serviceable`` contract shared by every serviceable component.

Keeping a single, tiny interface (``needs_service``) is what allows the fleet
engine to treat engines, batteries, tyres and whole cars uniformly.
"""

from __future__ import annotations

from abc import ABC, abstractmethod

from lyft_fleet.domain.value_objects import ServiceContext

__all__ = ["Serviceable"]


class Serviceable(ABC):
    """Anything that can be inspected and judged as "due for service"."""

    @abstractmethod
    def needs_service(self, context: ServiceContext) -> bool:
        """Return ``True`` when this component requires a service."""

    def service_reasons(self, context: ServiceContext) -> tuple[str, ...]:
        """Return human readable explanations for why a service is required.

        The default implementation returns an empty tuple; components that own
        criteria override it to explain themselves.
        """
        return ()

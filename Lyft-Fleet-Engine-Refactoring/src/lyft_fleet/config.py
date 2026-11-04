"""Centralised, immutable configuration for the Lyft fleet maintenance domain.

Every tunable service threshold lives here so that the domain code contains no
magic numbers.  Changing a policy is therefore a configuration change, not a
code change, and each value is covered by unit tests (see
``tests/test_config.py``).
"""

from __future__ import annotations

from collections.abc import Mapping
from types import MappingProxyType
from typing import Final

# --------------------------------------------------------------------------- #
# Mileage based triggers (engine service intervals)
# --------------------------------------------------------------------------- #
CAPULET_SERVICE_INTERVAL_MILES: Final[int] = 30_000
"""A Capulet engine must be serviced once it has driven more than 30 000 miles
since the last service."""

WILLOUGHBY_SERVICE_INTERVAL_MILES: Final[int] = 60_000
"""A Willoughby engine must be serviced once it has driven more than 60 000
miles since the last service."""

# --------------------------------------------------------------------------- #
# Calendar based intervals (battery lifetimes and model inspections)
# --------------------------------------------------------------------------- #
NUBBIN_BATTERY_LIFETIME_YEARS: Final[int] = 4
"""A Nubbin battery has a four year calendar lifetime."""

SPINDLER_BATTERY_LIFETIME_YEARS: Final[int] = 3
"""A Spindler battery has a three year calendar lifetime."""

CALLIOPE_INSPECTION_INTERVAL_YEARS: Final[int] = 2
"""Calliope vehicles carry an extra two year fleet inspection."""

GLISSANDO_INSPECTION_INTERVAL_YEARS: Final[int] = 2
"""Glissando vehicles carry an extra two year fleet inspection."""

PALINDROME_INSPECTION_INTERVAL_YEARS: Final[int] = 4
"""Palindrome vehicles carry an extra four year fleet inspection."""

RORSCHACH_INSPECTION_INTERVAL_YEARS: Final[int] = 4
"""Rorschach vehicles carry an extra four year fleet inspection."""

THOVEX_INSPECTION_INTERVAL_YEARS: Final[int] = 4
"""Thovex vehicles carry an extra four year fleet inspection."""

# --------------------------------------------------------------------------- #
# Sensor wear thresholds (tyre wear sensors)
# --------------------------------------------------------------------------- #
CARRIGAN_TIRE_WEAR_THRESHOLD: Final[float] = 0.9
"""A Carrigan tyre set needs service when *any* wheel reports at least 90 % wear."""

OCTOPRIME_TIRE_TOTAL_WEAR_THRESHOLD: Final[float] = 3.0
"""An Octoprime tyre set needs service when the *sum* of the wheel wear values
reaches 3.0 (i.e. an average of 75 % wear across four wheels)."""

# --------------------------------------------------------------------------- #
# Engine warning sensor
# --------------------------------------------------------------------------- #
STERNMAN_WARNING_LIGHT: Final[str] = "engine_warning_light"
"""Name of the engine warning sensor inspected by the Sternman engine."""

# --------------------------------------------------------------------------- #
# Canonical model names and their public aliases
# --------------------------------------------------------------------------- #
MODEL_ALIASES: Final[Mapping[str, str]] = MappingProxyType(
    {
        "glissade": "glissando",
        "glissado": "glissando",
    }
)
"""Historical spellings kept for backwards compatibility with the legacy fleet
tools.  Keys are normalised (lower case, no separators) aliases."""

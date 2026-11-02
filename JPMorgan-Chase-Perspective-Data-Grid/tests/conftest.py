"""Shared pytest fixtures for the test suite."""

from __future__ import annotations

import os
import sys
from pathlib import Path

import pytest

# Make the ``src`` layout importable without an installation step.
SRC = Path(__file__).resolve().parents[1] / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from jpm_perspective_grid.core.models import Tick  # noqa: E402
from jpm_perspective_grid.core.thresholds import ThresholdPolicy  # noqa: E402


def _coverage_is_active() -> bool:
    """Return ``True`` when the test run is instrumented by coverage.

    Coverage tracing slows the code down by roughly a factor of three, so
    the throughput budgets are meaningless while it is enabled.
    """
    if os.environ.get("COVERAGE_RUN"):
        return True
    return "coverage" in sys.modules and getattr(sys, "gettrace", lambda: None)() is not None



@pytest.fixture
def policy() -> ThresholdPolicy:
    """A deterministic threshold policy with a short window."""
    return ThresholdPolicy(window_size=5, sigma_multiplier=2.0, min_half_width=0.001)


@pytest.fixture
def make_tick():
    """Factory building a valid :class:`Tick` with sensible defaults."""

    def _factory(
        stock: str = "AAPL",
        ask: float = 100.0,
        bid: float = 99.0,
        timestamp: int = 1_700_000_000_000,
    ) -> Tick:
        return Tick(
            stock=stock,
            top_ask_price=ask,
            top_bid_price=bid,
            timestamp=timestamp,
        )

    return _factory


@pytest.fixture
def raw_tick_payload():
    """Factory building a raw (unvalidated) tick payload."""

    def _factory(
        stock: str = "AAPL",
        ask: float = 100.0,
        bid: float = 99.0,
        timestamp: int = 1_700_000_000_000,
    ) -> dict[str, object]:
        return {
            "stock": stock,
            "top_ask_price": ask,
            "top_bid_price": bid,
            "timestamp": timestamp,
        }

    return _factory

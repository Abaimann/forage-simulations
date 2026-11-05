"""Shared pytest fixtures for the Walmart logistics suite."""

from __future__ import annotations

import random

import pytest

from walmart_logistics.config import DispatchConfig


@pytest.fixture()
def small_config() -> DispatchConfig:
    """Return a small, fast configuration for the unit tests."""
    return DispatchConfig(packages=50, trucks=10, arity_exponent=2)


@pytest.fixture()
def rng() -> random.Random:
    """Return a deterministic random generator."""
    return random.Random(4242)

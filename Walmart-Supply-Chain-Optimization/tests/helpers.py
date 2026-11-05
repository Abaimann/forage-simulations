"""Reusable helpers shared by the test modules."""

from __future__ import annotations

import heapq
import random
from collections.abc import Iterable, Sequence

from walmart_logistics.data_structures.kary_heap import KaryHeap

__all__ = [
    "assert_sorted_ascending",
    "heap_invariant_holds",
    "heapq_sorted",
]


def heap_invariant_holds(heap: KaryHeap[int]) -> bool:
    """Return ``True`` when the heap invariant holds for every node.

    The check is written against the *public* behaviour of the heap
    (popping the elements) rather than peeking into the internals, so it
    also validates the index arithmetic.
    """
    clone = heap.copy()
    previous = None
    while clone:
        current = clone.pop()
        if previous is not None and current < previous:
            return False
        previous = current
    return True


def assert_sorted_ascending(values: Iterable[int]) -> None:
    """Assert that ``values`` is sorted in ascending order."""
    materialised = list(values)
    assert materialised == sorted(materialised)


def heapq_sorted(values: Sequence[int]) -> list[int]:
    """Return the ascending sort of ``values`` computed with :mod:`heapq`."""
    heap = list(values)
    heapq.heapify(heap)
    return [heapq.heappop(heap) for _ in range(len(heap))]


def random_values(count: int, seed: int = 4242, bound: int = 1000) -> list[int]:
    """Return ``count`` reproducible pseudo-random values."""
    return [random.Random(seed + index).randrange(bound) for index in range(count)]
